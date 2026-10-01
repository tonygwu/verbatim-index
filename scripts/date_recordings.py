#!/usr/bin/env python3
"""The dating stage: find when each recording's words were spoken, and prove it from a page.

Rescue round 4, design section 1, as the operator decided it on 2026-09-29
(VD-8 (c), "see what happens"): ONE agent per recording names the event and its
date range and cites sources with verbatim excerpts; a script with no model then
fetches every cited page and must find the excerpt on it, with a date inside the
agent's range. The recording's own page never counts. A confirmed date becomes an
entry in THIS RUN's override file, never production's (critique 3 A5); anything
else goes to the run's queue with its reason, for a person.

Three stages, run in order by default:
  propose   one agent call per transcript (SPENDS QUOTA). A proposal on disk is
            reused, so a re-run pays only for what failed.
  check     one polite HTTP fetch per cited page, direct and then from its
            Wayback copy. No model. Keeps each page's sha256 and a window
            around the excerpt, never the page.
  merge     dating_lib.merge_one per transcript. Writes <run-dir>/overrides.json
            (loaded back through the production loader before it is kept),
            <run-dir>/queue.json and <run-dir>/runs/<run_id>.json.

THE HARNESS (operator, 2026-09-29): Gemini by default, because the Codex quota is
short; Astra and Fable on request. Both Gemini and Astra have live web search.
Fable in this harness has NO working web tools, so its proposal comes from memory;
the page check applies to it exactly as to any other.

Dry run by default: prints the scope and what a run would spend, writes nothing.
--run spends quota and says so first.

  .venv/bin/python scripts/date_recordings.py --run-dir data/predictions/_experiments/dating-<name>
  .venv/bin/python scripts/date_recordings.py --run-dir data/predictions/_experiments/dating-<name> --run
  .venv/bin/python scripts/date_recordings.py --run-dir ... --run --ids ids.txt --limit 10
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import random
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402

GEMINI_MODEL = "gemini-3.8-flash-high"
UNDATED_BASES = ("youtube_upload_date", "publication_date", "unknown")
USER_AGENT = "verbatim-index-dating/1.0 (one fetch per cited page; https://verbatim-predictions.tonygwu.com)"
MAX_PAGE_BYTES = 5_000_000
_log_lock = threading.Lock()


def log(msg: str) -> None:
    with _log_lock:
        print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Where a run may write
# ---------------------------------------------------------------------------

def guard_run_dir(run_dir: Path, data_root: Path) -> Path:
    """The run's own directory, or exit. Never production: critique 3 A5.

    Under the data root it must be predictions/_experiments/dating-<name>, so the
    override file it writes can never be predictions/statement_date_overrides.json,
    which every clone's scorer reads on its next push.
    """
    p = Path(run_dir).resolve()
    root = Path(data_root).resolve()
    if p == root or root in p.parents:
        exp = root / "predictions" / "_experiments"
        if p.parent != exp or not p.name.startswith("dating-"):
            raise SystemExit(f"REFUSING --run-dir {run_dir}: under the data root a dating run lives at "
                             f"{exp}/dating-<name>, never in production or another experiment's folder")
    elif not p.name.startswith("dating-"):
        raise SystemExit(f"REFUSING --run-dir {run_dir}: a dating run's directory is named dating-<name>")
    return p


def write(path: Path, text: str) -> None:
    L.write_prediction_file(path, text)


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

def load_production_overrides(path: Path, explicit: bool) -> dict:
    """The operator's entries, read only to skip what the operator already dated (review item 16).

    A file named on the command line must exist. The default file may be absent, and
    that is said, never passed over in silence.
    """
    if not path.exists():
        if explicit:
            raise SystemExit(f"--production-overrides {path} does not exist")
        print(f"no production override file at {path}; no transcript is skipped as already dated by the operator")
        return {}
    return json.loads(path.read_text()).get("overrides") or {}


def select_scope(pred_dirs: list[Path], troots: list[Path], ids_file: Path | None, production: dict,
                 limit: int | None) -> tuple[list[dict], Counter, list[str]]:
    """(jobs, exclusions by reason, missing transcripts). Every exclusion is counted, none is silent.

    Default scope (design 1.2): each transcript with an accepted record whose date is
    an upload date, a publication date or unknown, and each transcript holding a
    record the 2.3 date checks hold. Out, and counted: a transcript that states its
    own date (overriding one is decision D9, not taken) and one the operator has
    already dated. With --ids, exactly the named transcripts, each of which must exist.
    """
    records: dict[str, list[dict]] = {}
    metas: dict[str, dict] = {}
    for d in pred_dirs:
        for f in sorted(Path(d).glob("*/*.jsonl")):
            if f.parent.name.startswith("_"):
                continue
            tid = f"{f.parent.name}/{f.name[:-len('.jsonl')]}"
            records.setdefault(tid, []).extend(L.parse_lines(f.read_text(), str(f)))
        for mp in sorted(Path(d).glob("*/*.meta.json")):
            if not mp.parent.name.startswith("_"):
                tid = f"{mp.parent.name}/{mp.name[:-len('.meta.json')]}"
                metas[tid] = json.loads(mp.read_text())
                records.setdefault(tid, [])
    excluded: Counter = Counter()
    if ids_file is not None:
        wanted = [x.strip() for x in Path(ids_file).read_text().splitlines() if x.strip()]
    else:
        wanted = []
        for tid, recs in sorted(records.items()):
            acc = [r for r in recs if r.get("accepted")]
            held = [r for r in recs if r.get("date_hold")]
            # The extractor's or verifier's doubt, from the meta file, so a transcript all
            # of whose candidates were refused is still dated (review item 18).
            doubted = any(((metas.get(tid) or {}).get(stage) or {}).get("statement_date_doubt", {}).get("doubt")
                          == L.HOLDING_DOUBT for stage in ("extract", "verify"))
            if not acc and not held and not doubted:
                excluded["no accepted or held record"] += 1
                continue
            bases = {(r.get("source") or {}).get("statement_date_basis") for r in acc + held + (recs if doubted else [])}
            if tid in production and production[tid].get("confirmed_by") == "operator":
                excluded["operator override already present"] += 1
                continue
            if bases & set(UNDATED_BASES) or held or (doubted and "stated_in_page" not in bases):
                wanted.append(tid)
            elif "stated_in_page" in bases:
                excluded["stated_in_page (not dated by this stage)"] += 1
            else:
                excluded["already dated by an override"] += 1
    jobs, missing = [], []
    for tid in wanted:
        slug, sid = tid.split("/", 1)
        hits = [r / slug / f"{sid}.json" for r in troots if (r / slug / f"{sid}.json").is_file()]
        if not hits:
            missing.append(tid)
            continue
        jobs.append({"tid": tid, "path": hits[0], "records": records.get(tid, []), "meta": metas.get(tid)})
    if ids_file is not None and missing:
        raise SystemExit(f"--ids names {len(missing)} transcript(s) that are under none of the transcript roots: "
                         f"{missing[:5]}")
    if limit is not None:
        excluded[f"beyond --limit {limit}"] += max(0, len(jobs) - limit)
        jobs = jobs[:limit]
    return jobs, excluded, missing


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

_gemini_lock = threading.Lock()
_gemini_profiles: list[str] | None = None


def call_agent(harness: str, prompt: str, timeout: int, workdir: Path, args, idx: int) -> tuple[str, dict, str | None]:
    """One call on the chosen harness: (text, telemetry, account identity). Raises with a taxonomy label."""
    import grade as G  # noqa: PLC0415 -- the harness module is heavy and only a real run needs it
    global _gemini_profiles
    workdir.mkdir(parents=True, exist_ok=True)
    if harness == "gemini":
        with _gemini_lock:
            if _gemini_profiles is None:
                _gemini_profiles = G.agy_profiles()
            profiles = list(_gemini_profiles)
        if not profiles:
            raise RuntimeError(f"{G.E_CLI}: no Antigravity profile is available")
        home = G.pick_gemini_profile(G.assign_accounts("gemini", idx, profiles, ["gemini"]), profiles)
        text, tel = G.call_gemini(prompt, home, timeout, workdir=str(workdir), model=args.gemini_model,
                                  binary=args.agy_bin)
        return text, tel, tel.get("profile_identity")
    if harness == "astra":
        text, tel = G.call_astra(prompt, timeout, workdir, model=args.astra_model,
                                 config_dir=args.codex_home or None)
        return text, {**tel, "served_model_verified": False}, G.account_label(args.codex_home or "__DEFAULT__")
    if harness == "fable":
        cfg = args.fable_config_dir or "__DEFAULT__"
        text, tel = G.call_fable(prompt, cfg, timeout, binary=args.fable_bin, workdir=str(workdir))
        return text, {**tel, "served_model": tel.get("judge_model"), "served_model_verified": True}, G.account_label(cfg)
    raise RuntimeError(f"cli_nonzero_exit: unknown harness {harness}")


HARNESSES = ("gemini", "astra", "fable")


def daters(args) -> list[str]:
    """The harnesses that propose a date for each transcript, in the order the merge reads them.

    Default DL.DATERS, Gemini then Fable (operator decision VD-11, 2026-10-01). A
    single name runs one dater, whose merge is the one-agent rule of VD-8 (c).
    """
    names = [x.strip() for x in (args.harness or "").split(",")]
    bad = [x for x in names if x not in HARNESSES]
    if not names or bad or len(set(names)) != len(names):
        raise SystemExit(f"--harness {args.harness!r}: give one or more of {list(HARNESSES)}, comma-separated, "
                         f"each once")
    return names


def requested_model(args, harness: str) -> str:
    return {"gemini": args.gemini_model, "astra": args.astra_model, "fable": "claude-fable-5-1"}[harness]


def proposal_path(run_dir: Path, tid: str, harness: str) -> Path:
    slug, sid = tid.split("/", 1)
    return run_dir / "proposals" / slug / f"{sid}.{harness}.json"


def propose_one(job: dict, harness: str, args, run_dir: Path, run_id: str, caller, idx: int) -> dict:
    tid = job["tid"]
    slug, sid = tid.split("/", 1)
    dest = proposal_path(run_dir, tid, harness)
    base = {"id": tid, "stage": "propose", "harness": harness}
    if dest.exists() and not args.redo:
        cached = json.loads(dest.read_text())
        return {**base, "status": "cached", **({"invalid": True} if cached.get("answer_errors") else {})}
    rec = json.loads(Path(job["path"]).read_text())
    leads, dropped = DL.leads_from_records(job["records"], job["meta"])
    prompt, meta = DL.build_dating_prompt(rec, leads, harness=harness)
    sha = hashlib.sha256(prompt.encode()).hexdigest()
    write(run_dir / "prompts" / slug / f"{sid}.{harness}.txt", prompt)
    t0 = time.time()
    try:
        text, tel, identity = caller(harness, prompt, args.timeout,
                                     Path(args.workroot) / run_id / f"{slug}-{sid}-{harness}", args, idx)
    except Exception as exc:  # noqa: BLE001 -- every failure is labelled, and none becomes a date
        detail = str(exc)[:500]
        return {**base, "status": "failed", "error_type": L.classify_exception_detail(detail), "detail": detail,
                "prompt_sha256": sha}
    write(run_dir / "raw" / slug / f"{sid}.{harness}.{run_id}.txt", text)
    # An answer the model gave but that fails validation is STORED as an invalid proposal
    # (review fix 5): the merge reads it as invalid_proposal, so it neither confirms nor
    # agrees, and the other dater's confirmation stands. It is final, like any answer on
    # disk; --redo asks again. Only infrastructure failures above write nothing.
    failure = None
    try:
        obj = L.extract_json(text)
        if not isinstance(obj, dict):
            raise ValueError(f"the answer is a {type(obj).__name__}, not a JSON object")
        errs = DL.validate_proposal(obj, tid)
        if errs:
            failure = (L.E_SCHEMA, errs)
    except (ValueError, json.JSONDecodeError) as exc:
        obj, failure = {}, (L.E_NOJSON, [str(exc)[:300]])
    own_date, own_basis = L.own_statement_date(rec)
    # daters: every harness this run asked, so a merge or entry that leaves one out is refused.
    doc = {"schema_version": 1, "transcript_id": tid, "run_id": run_id, "harness": harness, "daters": daters(args),
           "requested_model": tel.get("requested_model") or requested_model(args, harness),
           "served_model": tel.get("served_model"), "served_model_verified": bool(tel.get("served_model_verified")),
           "identity": identity, "profile_home": tel.get("profile_home"),
           "prompt_sha256": sha, "prompt_meta": meta, "leads": leads, "leads_dropped": dropped,
           "own_date": own_date, "own_basis": own_basis, "proposal": obj,
           "telemetry": {k: tel.get(k) for k in ("web_search_queries", "tool_use_counts", "denied_actions",
                                                 "input_tokens", "output_tokens", "thinking_tokens",
                                                 "reasoning_output_tokens", "attempts", "empty_retries")},
           "elapsed_sec": round(time.time() - t0, 1), "proposed_at_utc": DL.utc_stamp(),
           **({"answer_errors": failure[1], "answer_error_type": failure[0]} if failure else {})}
    write(dest, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    if failure:
        return {**base, "status": "failed", "error_type": failure[0], "detail": "; ".join(failure[1][:4]),
                "prompt_sha256": sha, "stored": True}
    return {**base, "status": "ok", "verdict": obj["verdict"], "identity": identity}


# ---------------------------------------------------------------------------
# Polite fetching (the polite-bulk-fetching pattern: pace, back off, break)
# ---------------------------------------------------------------------------

def urllib_opener(url: str, timeout: int) -> tuple[int, str, bytes, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 -- http(s) only, checked by the caller
            return r.status, r.geturl(), r.read(MAX_PAGE_BYTES + 1), r.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        return exc.code, url, b"", None


class PoliteFetcher:
    """One gap between all requests, backoff on 429/503, a breaker per host, a Wayback fallback."""

    THROTTLE = (429, 503)
    PERMANENT = (401, 403, 404, 410, 451)

    def __init__(self, opener=None, sleep=time.sleep, interval: float = 1.5, timeout: int = 25, retries: int = 2,
                 breaker: int = 5):
        self.opener, self.sleep, self.interval, self.timeout = opener or urllib_opener, sleep, interval, timeout
        self.retries, self.breaker = retries, breaker
        self._lock, self._next = threading.Lock(), 0.0
        self._streak: Counter = Counter()
        self.outcomes: Counter = Counter()

    def _pace(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval * random.uniform(0.7, 1.3)
            wait = start - now
        if wait > 0:
            self.sleep(wait)

    def _get(self, url: str) -> dict:
        host = urllib.parse.urlsplit(url).hostname or ""
        if self._streak[host] >= self.breaker:
            return {"status": None, "final_url": url, "body": b"", "error": f"breaker open for {host}: "
                    f"{self._streak[host]} throttles in a row"}
        last = None
        for attempt in range(self.retries + 1):
            if attempt:
                self.sleep(4.0 * 2 ** (attempt - 1) * random.uniform(0.8, 1.2))
            self._pace()
            try:
                status, final, body, ctype = self.opener(url, self.timeout)
            except Exception as exc:  # noqa: BLE001 -- a network error is an outcome, recorded
                last = {"status": None, "final_url": url, "body": b"", "error": f"{type(exc).__name__}: {exc}"[:200]}
                continue
            if status in self.THROTTLE:
                self._streak[host] += 1
                last = {"status": status, "final_url": final, "body": b"", "error": f"HTTP {status} (throttled)"}
                continue
            self._streak[host] = 0
            if len(body) > MAX_PAGE_BYTES:
                return {"status": status, "final_url": final, "body": b"", "error": f"page over {MAX_PAGE_BYTES} bytes"}
            return {"status": status, "final_url": final, "body": body, "content_type": ctype,
                    "error": None if status == 200 else f"HTTP {status}"}
        last["error"] += f" after {self.retries + 1} attempts"
        return last

    def fetch(self, url: str) -> dict:
        if not url.lower().startswith(("http://", "https://")):
            self.outcomes["not_http"] += 1
            return {"status": None, "final_url": url, "body": b"", "via": None, "error": "not an http(s) URL"}
        direct = self._get(url)
        if direct["error"] is None:
            self.outcomes["direct"] += 1
            return {**direct, "via": "direct"}
        avail = self._get("https://archive.org/wayback/available?url=" + urllib.parse.quote(DL.unwrap_wayback(url), safe=""))
        snap = None
        if avail["error"] is None:
            try:
                snap = (json.loads(avail["body"]).get("archived_snapshots") or {}).get("closest")
            except (ValueError, AttributeError):
                snap = None
        if not snap or not snap.get("available") or not snap.get("timestamp"):
            self.outcomes["failed"] += 1
            return {**direct, "via": "direct", "error": f"direct: {direct['error']}; wayback: no capture"}
        wb = self._get(f"http://web.archive.org/web/{snap['timestamp']}id_/{DL.unwrap_wayback(url)}")
        if wb["error"] is None:
            self.outcomes["wayback"] += 1
            return {**wb, "via": "wayback"}
        self.outcomes["failed"] += 1
        return {**wb, "via": "wayback", "error": f"direct: {direct['error']}; wayback: {wb['error']}"}


def no_pages_to_check(doc: dict, tid: str) -> str | None:
    """Why a stored proposal needs no page fetch, or None: cannot_date, or an answer that failed validation (the
    merge reads it as invalid_proposal; review fix 5)."""
    prop = doc.get("proposal")
    if doc.get("answer_errors") or not isinstance(prop, dict) or DL.validate_proposal(prop, tid):
        return "invalid answer"
    return "cannot_date" if prop["verdict"] == "cannot_date" else None


def checks_path(run_dir: Path, tid: str, harness: str) -> Path:
    slug, sid = tid.split("/", 1)
    return run_dir / "source_checks" / slug / f"{sid}.{harness}.json"


def check_one(tid: str, harness: str, rec: dict, doc_path: Path, run_dir: Path, fetcher: PoliteFetcher,
              redo: bool) -> dict:
    dest = checks_path(run_dir, tid, harness)
    sha = hashlib.sha256(doc_path.read_bytes()).hexdigest()
    base = {"id": tid, "stage": "check", "harness": harness}
    if dest.exists() and not redo and json.loads(dest.read_text()).get("proposal_sha256") == sha:
        return {**base, "status": "cached"}
    prop = json.loads(doc_path.read_text())["proposal"]
    checks = []
    for src in prop["sources"]:
        why = DL.own_page_reason(src["url"], rec)
        checks.append(DL.refused_check(src, why) if why else DL.check_source(src, rec, fetcher.fetch(src["url"])))
    write(dest, json.dumps({"schema_version": 1, "transcript_id": tid, "proposal_sha256": sha, "checks": checks,
                            "checked_at_utc": DL.utc_stamp()}, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return {**base, "status": "ok", "fetched": sum(c["fetched"] for c in checks),
            "refused_own_page": sum(1 for c in checks if c["refused"]), "excerpt_found": sum(c["excerpt_found"] for c in checks)}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def summarise(results: list[dict], stage: str) -> dict:
    rs = [r for r in results if r["stage"] == stage]
    tax = Counter(r["error_type"] for r in rs if r["status"] == "failed")
    s = {"attempted": len(rs), "succeeded": sum(1 for r in rs if r["status"] in ("ok", "cached")),
         "cached": sum(1 for r in rs if r["status"] == "cached"), "failed": sum(1 for r in rs if r["status"] == "failed"),
         "skipped": sum(1 for r in rs if r["status"] == "skipped"), "error_taxonomy": dict(tax),
         # Invalid answers stored on disk (review fix 5): failed when made, cached after, never hidden.
         "invalid_answers_on_disk": sum(1 for r in rs if r.get("invalid") or r.get("stored"))}
    return s


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True, help="this run's own directory, data/predictions/_experiments/dating-<name>")
    ap.add_argument("--run", action="store_true", help="SPEND QUOTA and fetch pages; without it, a dry run that writes nothing")
    ap.add_argument("--stage", choices=["propose", "check", "merge", "all"], default="all")
    ap.add_argument("--harness", default=",".join(DL.DATERS),
                    help="the daters, comma-separated: each proposes a date for every transcript, and the merge "
                         "reads them all. Default gemini,fable (operator decision VD-11, 2026-10-01): gemini has web "
                         "search; fable has NO working web tools in this harness, so its proposal comes from memory, "
                         "and every excerpt it cites must still pass the same page check as any other. astra (web "
                         "search) on request. One name runs one dater")
    ap.add_argument("--data-root", type=Path, default=None,
                    help="the data checkout the run belongs to; default this clone's data link. The run directory "
                         "must be <data-root>/predictions/_experiments/dating-<name>")
    ap.add_argument("--predictions", type=Path, action="append", default=None, help="record trees; default data/predictions")
    ap.add_argument("--transcripts", type=Path, action="append", default=None,
                    help="transcript roots; default data/transcripts_open and data/transcripts_web")
    ap.add_argument("--production-overrides", type=Path, default=None,
                    help=f"read only, to skip transcripts the operator already dated; default data/{L.DATE_OVERRIDES_FILE}")
    ap.add_argument("--ids", type=Path, default=None, help="a file of transcript ids (slug/source_id), one per line")
    ap.add_argument("--limit", type=int, default=None, help="first N transcripts, for a pilot")
    ap.add_argument("--redo", action="store_true", help="propose and check again even where a result is on disk")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--gemini-model", default=GEMINI_MODEL)
    ap.add_argument("--agy-bin", default="agy")
    ap.add_argument("--astra-model", default="gpt-6-astra")
    ap.add_argument("--codex-home", default=None)
    ap.add_argument("--fable-bin", default="claude")
    ap.add_argument("--fable-config-dir", default=None)
    ap.add_argument("--workroot", default=str(Path(os.environ.get("TMPDIR", "/tmp")) / "dating-work"))
    return ap


def main(argv: list[str] | None = None, caller=None, opener=None, sleep=time.sleep) -> int:
    args = build_parser().parse_args(argv)
    hs = daters(args)
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("REFUSING --fable-bin cl: it injects --dangerously-skip-permissions (see AGENTS.md)")
    data = (args.data_root or L.data_root()).resolve()
    run_dir = guard_run_dir(Path(args.run_dir), data)
    pred_dirs = args.predictions or [data / "predictions"]
    troots = args.transcripts or [data / d for d in L.TRANSCRIPT_DIRS]
    production = load_production_overrides(args.production_overrides or data / L.DATE_OVERRIDES_FILE,
                                           explicit=args.production_overrides is not None)
    jobs, excluded, missing = select_scope(pred_dirs, troots, args.ids, production, args.limit)
    by_tid = {j["tid"]: j for j in jobs}

    lines = [f"in scope: {len(jobs)} transcripts"] + [f"  excluded, {k}: {v}" for k, v in sorted(excluded.items())]
    if missing:
        lines.append(f"  transcript file missing under every root: {len(missing)} {missing[:5]}")
    calls = len(jobs) * len(hs)
    if not args.run:
        sample = DL.build_dating_prompt(json.loads(jobs[0]["path"].read_text()),
                                        DL.leads_from_records(jobs[0]["records"], jobs[0]["meta"])[0],
                                        harness=hs[0])[1] if jobs else None
        print("DRY RUN: nothing is called, fetched or written.")
        print("\n".join(lines).replace("  excluded, ", "  "))
        print(f"a real run would spend {calls} calls: "
              + ", ".join(f"{h} {len(jobs)} ({requested_model(args, h)})" for h in hs)
              + f", one per transcript per dater (call_gemini may retry an empty or transient answer inside one call), "
                f"and up to {calls * 3 * 3} HTTP GETs at about 3 cited pages each, direct then Wayback")
        if sample:
            print(f"first prompt ({hs[0]}): {sample}")
        return 0

    print(f"SPENDS QUOTA: up to {calls} calls ("
          + ", ".join(f"{h} {len(jobs)} {requested_model(args, h)}" for h in hs)
          + f") for the proposals not already on disk under {run_dir}, and HTTP fetches of every page they cite.")
    print("\n".join(lines))
    run_id = f"{DL.utc_stamp().replace(':', '').replace('-', '')}-{secrets.token_hex(3)}"
    caller = caller or call_agent
    fetcher = PoliteFetcher(opener, sleep=sleep)
    results: list[dict] = []
    stages = ["propose", "check", "merge"] if args.stage == "all" else [args.stage]

    if "propose" in stages:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(propose_one, j, h, args, run_dir, run_id, caller, i * len(hs) + k)
                    for i, j in enumerate(jobs) for k, h in enumerate(hs)]
            for f in cf.as_completed(futs):
                r = f.result()
                results.append(r)
                log(json.dumps(r)[:300])

    if "check" in stages:
        for tid, job in by_tid.items():
            for h in hs:
                pp = proposal_path(run_dir, tid, h)
                if not pp.exists():
                    results.append({"id": tid, "harness": h, "stage": "check", "status": "skipped",
                                    "reason": "no proposal"})
                    continue
                why_not = no_pages_to_check(json.loads(pp.read_text()), tid)
                if why_not:
                    results.append({"id": tid, "harness": h, "stage": "check", "status": "skipped",
                                    "reason": why_not})
                    continue
                r = check_one(tid, h, json.loads(job["path"].read_text()), pp, run_dir, fetcher, args.redo)
                results.append(r)
                log(json.dumps(r)[:300])

    merge_report = None
    if "merge" in stages:
        overrides, checks_out, queue, not_proposed = {}, {}, [], []
        missing_proposals: dict[str, list[str]] = {}
        missing_checks: dict[str, list[str]] = {}
        merge_errors: list[str] = []
        rel = str(run_dir.relative_to(data)) if data in run_dir.parents else str(run_dir)
        for tid, job in sorted(by_tid.items()):
            # Every dater's proposal, or no merge: one dater alone could confirm a day the
            # other's own page contradicts (VD-11). The transcript waits, named, for a re-run.
            lacking = [h for h in hs if not proposal_path(run_dir, tid, h).exists()]
            if lacking:
                not_proposed.append(tid)
                missing_proposals[tid] = lacking
                continue
            docs, checks_by, refs, unchecked = [], {}, {}, []
            for h in hs:
                pp = proposal_path(run_dir, tid, h)
                doc = json.loads(pp.read_text())
                sha = hashlib.sha256(pp.read_bytes()).hexdigest()
                docs.append(doc)
                refs[h] = {"path": str(pp.relative_to(run_dir)), "sha256": sha}
                checks_by[h] = []
                if not no_pages_to_check(doc, tid):
                    cp = checks_path(run_dir, tid, h)
                    cdoc = json.loads(cp.read_text()) if cp.exists() else None
                    if cdoc is None or cdoc["proposal_sha256"] != sha:
                        unchecked.append(h)
                        continue
                    checks_by[h] = cdoc["checks"]
            if unchecked:
                not_proposed.append(tid)
                missing_checks[tid] = unchecked
                continue
            try:
                out = DL.merge(json.loads(job["path"].read_text()), docs, checks_by, refs, run_rel=rel)
            except Exception as exc:  # noqa: BLE001 -- one transcript's defect never stops the others (review fix 4)
                out = {"outcome": "queue", "reason": "merge_error", "detail": f"{type(exc).__name__}: {exc}"[:500],
                       "checks": []}
                merge_errors.append(tid)
            if out["outcome"] == "override":
                overrides[tid] = {**out["entry"], "confirmed_at_utc": DL.utc_stamp()}
            elif out["outcome"] == "check":
                # It confirms the transcript's own date: a check, which supersedes no record.
                checks_out[tid] = {**out["entry"], "confirmed_at_utc": DL.utc_stamp()}
            else:
                queue.append({"transcript_id": tid, "reason": out["reason"], "detail": out["detail"],
                              "by_dater": out.get("by_dater") or {hs[0]: out["reason"]},
                              "proposals": {h: r["path"] for h, r in refs.items()}, "checks": out["checks"]})
        ov_path = run_dir / "overrides.json"
        how = (f"daters {', '.join(hs)}: a cited page or description check of either, or both naming the same day "
               f"(VD-11)" if len(hs) > 1 else f"one {hs[0]} agent plus a page or description check (VD-8 (c))")
        body = json.dumps({"schema_version": 1, "notes": f"Dating run {run_dir.name}, merge {DL.MERGE_VERSION}, "
                           f"{how}. Not production: pass this file with --date-overrides.", "overrides": overrides},
                          indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        staged = run_dir / "overrides.json.candidate"
        write(staged, body)
        # The file must load through the loader every stage uses, re-verifying each
        # entry from its stored proposals and windows, before it replaces the last one.
        L.load_statement_date_overrides(staged, troots)
        write(ov_path, body)
        staged.unlink()
        ck_body = json.dumps({"schema_version": 1, "notes": f"Dating run {run_dir.name}, merge {DL.MERGE_VERSION}: "
                              f"checks that CONFIRM a transcript's own date. Pass with --date-checks.",
                              "checks": checks_out}, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        staged = run_dir / "checks.json.candidate"
        write(staged, ck_body)
        L.load_statement_date_checks(staged, troots)
        write(run_dir / "checks.json", ck_body)
        staged.unlink()
        write(run_dir / "queue.json", json.dumps({"schema_version": 1, "queue": queue}, indent=1, sort_keys=True,
                                                 ensure_ascii=False) + "\n")
        merge_report = {"confirmed": len(overrides), "checked": len(checks_out), "queued": len(queue),
                        "queued_by_reason": dict(Counter(q["reason"] for q in queue)), "not_proposed": not_proposed,
                        "missing_proposals": missing_proposals, "missing_checks": missing_checks,
                        "merge_errors": merge_errors,
                        "by_method": dict(Counter(e["confirmation"]["method"]
                                                  for e in list(overrides.values()) + list(checks_out.values())))}

    report = {"run_id": run_id, "daters": hs,
              "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
              "scope": len(jobs), "excluded": dict(excluded), "missing": missing,
              "propose": summarise(results, "propose"), "check": summarise(results, "check"),
              "fetch_outcomes": dict(fetcher.outcomes), "merge": merge_report, "results": results,
              "finished_at_utc": DL.utc_stamp()}
    write(run_dir / "runs" / f"{run_id}.json", json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False,
                                                          default=str) + "\n")
    for st in ("propose", "check"):
        s = report[st]
        print(f"{st}: attempted {s['attempted']}, succeeded {s['succeeded']} (cached {s['cached']}), "
              f"failed {s['failed']} {s['error_taxonomy']}, skipped {s['skipped']}, "
              f"invalid answers on disk {s['invalid_answers_on_disk']}")
    print(f"fetch outcomes: {dict(fetcher.outcomes)}")
    if merge_report:
        waiting = Counter(h for v in merge_report["missing_proposals"].values() for h in v)
        unchecked_n = Counter(h for v in merge_report["missing_checks"].values() for h in v)
        print(f"merge: confirmed {merge_report['confirmed']} (overrides), checked {merge_report['checked']} "
              f"(own date confirmed), by method {merge_report['by_method']}, queued {merge_report['queued']} "
              f"{merge_report['queued_by_reason']}; not merged {len(merge_report['not_proposed'])}"
              + "".join(f"; waiting for {h}: {n}" for h, n in sorted(waiting.items()))
              + "".join(f"; {h} proposal not checked: {n}" for h, n in sorted(unchecked_n.items()))
              + (f"; merge errors: {len(merge_report['merge_errors'])}" if merge_report["merge_errors"] else ""))
    return 1 if report["propose"]["failed"] or report["check"]["failed"] or (merge_report or {}).get("merge_errors") \
        else 0


if __name__ == "__main__":
    sys.exit(main())
