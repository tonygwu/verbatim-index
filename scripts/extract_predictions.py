#!/usr/bin/env python3
"""Extract and verify predictions from the transcript corpus, one model per stage.

Stage 1, extract: one model reads the whole transcript and proposes candidates
that pass five gates. The harness (Fable via `claude`, Astra via `codex exec`,
Gemini via `agy`) is chosen per job by the llm-quota-router from measured
headroom; the three call functions are imported from grade.py unchanged.
Every quote is grounded mechanically in the transcript; one that does not
match exactly after normalisation goes to meta.ungrounded, never to the file.

Stage 2, verify: a DIFFERENT model family re-judges each qualifying candidate
from a mechanical 400-word window and the extractor's claim. A record is
accepted only when both agree. Disagreements stay on file with both verdicts.

Both stages are resumable: a transcript whose meta says the stage succeeded
is skipped unless --force. Raw model text is written before it is parsed.
Every failure carries a taxonomy label; the run manifest and the summary
report attempted / succeeded / cached / excluded / failed, never a bare count.

This clone may write under data/predictions and nowhere else under data/;
the writer refuses any other path, and --out is checked before any call.

  .venv/bin/python scripts/extract_predictions.py --stage both --single data/transcripts_open/<slug>/<sid>.json
  .venv/bin/python scripts/extract_predictions.py --stage extract --workers 6
  .venv/bin/python scripts/extract_predictions.py --stage verify --workers 6
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import secrets
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402
from grade import (  # noqa: E402
    E_CLI, E_TIMEOUT, account_label, agy_profiles, apply_per_leader_limit, assign_accounts,
    call_astra, call_fable, call_gemini, pick_gemini_profile, stamp_failure,
)
import subprocess  # noqa: E402

GEMINI_MODEL = "gemini-3.8-flash-high"
_log_lock = threading.Lock()


def log(msg: str) -> None:
    with _log_lock:
        print(msg, file=sys.stderr, flush=True)


class RouterUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Routing: the quota router says which ACCOUNT; the provider names the harness
# ---------------------------------------------------------------------------

def route_from_selection(selection: dict, accounts: list[tuple], allow_degraded: bool) -> dict:
    """Turn one router decision into a harness and account. Pure, so it is testable.

    `selection` is the router's pick payload (decision.account, decision.provider,
    degraded). `accounts` are (id, provider, config_dir, is_default) rows. Nothing
    defaults: no account, an unknown provider, or a degraded pick without
    --allow-degraded all raise RouterUnavailable, and the job fails with
    `router_no_account` rather than silently landing on a harness.
    """
    decision = selection.get("decision") or {}
    acct = decision.get("account")
    if not acct:
        raise RouterUnavailable(f"{L.E_ROUTER}: router picked no account; reason={decision.get('reason')!r}; "
                                f"warnings={list(selection.get('warnings') or [])[:3]}")
    provider = decision.get("provider")
    harness = L.PROVIDER_TO_HARNESS.get(provider)
    if harness is None:
        raise RouterUnavailable(f"{L.E_ROUTER}: provider {provider!r} of account {acct} has no harness")
    degraded = [d for d in (selection.get("degraded") or ()) if acct in json.dumps(d)]
    # A degraded entry is the router saying its reading of this account is imperfect
    # (a stale usage snapshot, most often). It is fatal only when the router's own
    # verdict on the pick is not a clean fit; a pick it still calls fitting proceeds
    # with the flag and the reason recorded on the route, so the run can be audited.
    if degraded and not allow_degraded and decision.get("fits") is not True:
        raise RouterUnavailable(f"{L.E_ROUTER}: pick {acct} is degraded and the router does not call it a fit; "
                                f"--allow-degraded is off: {json.dumps(degraded)[:300]}")
    row = next((a for a in accounts if a[0] == acct), None)
    config_dir = None
    if harness == "fable":
        if row is None:
            raise RouterUnavailable(f"{L.E_ROUTER}: account {acct} is not in the router config")
        config_dir = "__DEFAULT__" if row[3] else str(row[2])
    return {"harness": harness, "account_id": acct, "config_dir": config_dir,
            "degraded": bool(degraded), "degraded_reason": json.dumps(degraded)[:200] if degraded else None,
            "provider": provider}


def accounts_of_harness(accounts: list[tuple], harness: str) -> list[str]:
    return [a[0] for a in accounts if L.PROVIDER_TO_HARNESS.get(a[1]) == harness]


class Router:
    """One quota-router pick per job, with a reservation so concurrent workers spread."""

    def __init__(self, exclude_ids: list[str], allow_degraded: bool, gemini_profiles: list[str]):
        from quota_router import select_account
        from quota_router.config import load_config
        self._select = select_account
        cfg = load_config()
        self.accounts = [(a.id, a.provider, a.config_dir, a.is_default_config_dir) for a in cfg.enabled_accounts()]
        self.exclude_ids = list(exclude_ids)
        self.allow_degraded = allow_degraded
        self.gemini_profiles = gemini_profiles
        self._n = 0
        self._lock = threading.Lock()

    def pick(self, pin: str | None, exclude_harness: str | None) -> dict:
        only = accounts_of_harness(self.accounts, pin) if pin else None
        exclude = list(self.exclude_ids)
        if exclude_harness:
            exclude += accounts_of_harness(self.accounts, exclude_harness)
        if only is not None and not [o for o in only if o not in exclude]:
            raise RouterUnavailable(f"{L.E_ROUTER}: pinned harness {pin} has no eligible account after exclusions")
        sel = self._select(only=only, exclude=exclude or None, record=True, no_sticky=True)
        route = route_from_selection(sel.to_dict(), self.accounts, self.allow_degraded)
        if route["harness"] == "gemini":
            with self._lock:
                idx = self._n
                self._n += 1
            if not self.gemini_profiles:
                raise RouterUnavailable(f"{L.E_ROUTER}: router chose Gemini but no agy profile is available")
            want = assign_accounts("gemini", idx, self.gemini_profiles, ["gemini"])
            route["profile_home"] = pick_gemini_profile(want, self.gemini_profiles)
        return route


def call_harness(route: dict, prompt: str, timeout: int, workdir: Path, args) -> tuple[str, dict, str | None]:
    h = route["harness"]
    if h == "fable":
        text, tel = call_fable(prompt, route["config_dir"], timeout, binary=args.fable_bin, workdir=str(workdir))
        return text, tel, account_label(route["config_dir"])
    if h == "astra":
        text, tel = call_astra(prompt, timeout, workdir, model=args.astra_model)
        return text, tel, "codex"
    if h == "gemini":
        text, tel = call_gemini(prompt, route["profile_home"], timeout, workdir=str(workdir),
                                model=args.gemini_model, binary=args.agy_bin)
        return text, tel, tel.get("profile_identity")
    raise RuntimeError(f"{E_CLI}: unknown harness {h}")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def paths_for(out: Path, slug: str, sid: str) -> tuple[Path, Path]:
    return out / slug / f"{sid}.jsonl", out / slug / f"{sid}.meta.json"


def read_transcript(rec_path: Path, tid: str) -> dict:
    """Load the transcript, or fail with a label that names what is missing.

    repo-0 retires recordings while a pass runs, so a file listed at launch can
    be gone by the time a worker reaches it. That is a withdrawn transcript, not
    a model or CLI failure, and the taxonomy must say so.
    """
    try:
        rec = json.loads(rec_path.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"{L.E_TRANSCRIPT_MISSING}: {tid} is no longer on disk at {rec_path}") from exc
    if (rec["leader_slug"], rec["source_id"]) != tuple(tid.split("/", 1)):
        raise RuntimeError(f"{L.E_TRANSCRIPT_MISSING}: {rec_path} holds "
                           f"{rec['leader_slug']}/{rec['source_id']}, not {tid}")
    return rec


def read_meta(meta_path: Path) -> dict:
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {"schema_version": L.SCHEMA_VERSION, "transcript_id": None, "extract": {"status": "not_run"},
            "verify": {"status": "not_run"}}


def write_meta(meta_path: Path, meta: dict) -> None:
    L.write_prediction_file(meta_path, json.dumps(meta, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def parse_model_output(text: str, schema: dict, expect_tid: str) -> dict:
    try:
        obj = L.extract_json(text)
    except ValueError as exc:
        raise RuntimeError(f"{L.E_NOJSON}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{L.E_BADJSON}: {exc}") from exc
    errs = L.check_schema(obj, schema)
    if errs:
        raise RuntimeError(f"{L.E_SCHEMA}: {'; '.join(errs[:5])}")
    if obj.get("transcript_id") != expect_tid:
        raise RuntimeError(f"{L.E_SCHEMA}: transcript_id {obj.get('transcript_id')!r} != {expect_tid}")
    return obj


# ---------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------

def ground_candidates(rec: dict, roster_entry: dict | None, obj: dict, provenance: dict, contract_id: str,
                      run_id: str, extracted_at: str, telemetry: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Pure: model candidates -> (records, ungrounded, dedupe_dropped)."""
    text = rec["text"]
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    grounded, ungrounded = [], []
    for c in obj["candidates"]:
        loc = L.locate_quote(text, c["quote"], c.get("timestamp_hint"))
        if "error" in loc:
            ungrounded.append({"quote": c["quote"], "reason": loc["error"], "occurrences": loc["occurrences"]})
            continue
        wc = L.quote_word_count(text[loc["start"]:loc["end"]])
        if not (L.MIN_QUOTE_WORDS <= wc <= L.MAX_QUOTE_WORDS):
            ungrounded.append({"quote": c["quote"], "reason": f"word_count_{wc}", "occurrences": loc["occurrences"]})
            continue
        r = L.make_record(rec, roster_entry, c, loc, provenance, contract_id, run_id, extracted_at, telemetry)
        grounded.append({"start": loc["start"], "end": loc["end"], "prediction_id": r["prediction_id"], "record": r})
    kept, dropped = L.dedupe_overlapping(grounded)
    records = [k["record"] for k in kept]
    # Two grounded candidates can share a normalised quote (identical text at two
    # offsets was already refused as ambiguous), but the same span can appear twice
    # in the model output; the dedupe collapsed those by overlap.
    seen: set[str] = set()
    unique = []
    for r in records:
        if r["prediction_id"] in seen:
            dropped.append({"prediction_id": r["prediction_id"], "start": r["source"]["quote_char_start"],
                            "end": r["source"]["quote_char_end"], "kept_by": r["prediction_id"]})
            continue
        seen.add(r["prediction_id"])
        unique.append(r)
    return unique, ungrounded, dropped


def extract_one(job: dict) -> dict:
    t0 = time.time()
    args, rec_path = job["args"], Path(job["path"])
    # The id comes from the path, so an excluded or withdrawn transcript is
    # skipped without opening a file repo-0 may have deleted since the listing.
    tid = L.transcript_id_from_path(rec_path)
    slug, sid = tid.split("/", 1)
    jsonl_path, meta_path = paths_for(job["out"], slug, sid)
    meta = read_meta(meta_path)
    meta["transcript_id"] = tid
    base = {"id": tid, "stage": "extract", "run": job["run_id"]}

    if tid in job["exclusions"]:
        if meta["extract"].get("status") != "excluded":
            meta["extract"] = {"status": "excluded", "reason": job["exclusions"][tid]["reason"],
                               "evidence": job["exclusions"][tid]["evidence"], "run_id": job["run_id"]}
            if not args.dry_run:
                write_meta(meta_path, meta)
        return {**base, "status": "excluded"}
    if meta["extract"].get("status") == "ok" and not args.force:
        return {**base, "status": "cached"}
    rec = read_transcript(rec_path, tid)

    workdir = job["workroot"] / f"{slug}-{sid}__extract__{job['run_id']}"
    workdir.mkdir(parents=True, exist_ok=True)
    prompt = L.build_extraction_prompt(rec, job["roster"].get(slug), job["spec"], job["schema_text"])
    if args.dry_run:
        (workdir / "prompt.txt").write_text(prompt)
        return {**base, "status": "dry_run", "prompt_chars": len(prompt), "workdir": str(workdir)}

    try:
        route = job["router"].pick(None if args.extractor == "auto" else args.extractor, None)
        text, telemetry, account = call_harness(route, prompt, args.timeout, workdir, args)
    except subprocess.TimeoutExpired:
        detail = f"{E_TIMEOUT}: no answer within {args.timeout}s"
        return _extract_failed(meta, meta_path, base, detail, t0, args)
    except (RuntimeError, OSError) as exc:
        return _extract_failed(meta, meta_path, base, str(exc), t0, args)

    raw_path = job["out"] / "_raw" / "extract" / route["harness"] / slug / f"{sid}__{route['harness']}__{job['run_id']}.txt"
    L.write_prediction_file(raw_path, text)
    extracted_at = L.utc_now()
    try:
        obj = parse_model_output(text, job["schema"], tid)
    except RuntimeError as exc:
        return _extract_failed(meta, meta_path, base, str(exc), t0, args, harness=route["harness"])

    provenance = L.normalise_provenance(route["harness"], telemetry, account, route["account_id"])
    records, ungrounded, dropped = ground_candidates(rec, job["roster"].get(slug), obj, provenance,
                                                     job["contract"]["contract_id"], job["run_id"], extracted_at, telemetry)
    L.write_prediction_file(jsonl_path, L.serialise_lines(records))
    meta["extract"] = {
        "status": "ok", "run_id": job["run_id"], **provenance, "contract_id": job["contract"]["contract_id"],
        "extracted_at_utc": extracted_at, "elapsed_sec": round(time.time() - t0, 1),
        "candidates_returned": len(obj["candidates"]), "candidates_grounded": len(records) + len(dropped),
        "candidates_written": len(records), "qualifying_written": sum(1 for r in records if r["extraction"]["qualifies"]),
        "ungrounded": ungrounded, "dedupe_dropped": dropped, "cap_hit": obj["cap_hit"],
        "estimated_total_qualifying": obj["estimated_total_qualifying"],
        "candidates_considered": obj["candidates_considered"],
        "subject_speech_share_estimate_pct": obj["subject_speech_share_estimate_pct"],
        "attribution_notes": obj["attribution_notes"], "raw": str(raw_path.relative_to(job["out"])),
    }
    # A forced re-extraction replaces the file, so any earlier verification is void.
    meta["verify"] = {"status": "not_run"}
    write_meta(meta_path, meta)
    return {**base, "status": "ok", "harness": route["harness"], "account": account,
            "candidates_returned": len(obj["candidates"]), "written": len(records),
            "ungrounded": len(ungrounded), "elapsed": round(time.time() - t0, 1)}


def _extract_failed(meta, meta_path, base, detail, t0, args, harness=None) -> dict:
    etype = L.classify_exception_detail(detail)
    meta["extract"] = {"status": "failed", "error_type": etype, "detail": detail[:600], "harness": harness,
                       "run_id": base["run"], "elapsed_sec": round(time.time() - t0, 1)}
    if not args.dry_run:
        write_meta(meta_path, meta)
    return {**base, "status": "failed", "error_type": etype, "detail": detail[:600]}


# ---------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------

def apply_verdicts(records: list[dict], verdicts: list[dict], provenance: dict, contract_id: str,
                   run_id: str, verified_at: str, telemetry: dict) -> None:
    """Pure over the given records: write the verification block and the derived booleans."""
    by_id = {v["prediction_id"]: v for v in verdicts}
    for r in records:
        v = by_id.get(r["prediction_id"])
        if v is None:
            continue
        ver = {"status": "ok", **provenance, "contract_id": contract_id, "run_id": run_id,
               "verified_at_utc": verified_at, "gates": {g: bool(v["gates"][g]) for g in L.GATES},
               "attribution": v["attribution"], "claim_faithful": bool(v["claim_faithful"]),
               "qualifies_stated": bool(v["qualifies"]), "qualifies": None, "agreement": None,
               "verifier_resolution_criteria": v["resolution_criteria"], "notes": v.get("notes"), "telemetry": telemetry}
        ver["qualifies"] = L.verification_qualifies(ver)
        ver["agreement"] = r["extraction"]["qualifies"] == ver["qualifies"]
        r["verification"] = ver
        r["accepted"] = L.compute_accepted(r)


def verify_one(job: dict) -> dict:
    t0 = time.time()
    args, rec_path = job["args"], Path(job["path"])
    tid = L.transcript_id_from_path(rec_path)
    slug, sid = tid.split("/", 1)
    jsonl_path, meta_path = paths_for(job["out"], slug, sid)
    meta = read_meta(meta_path)
    base = {"id": tid, "stage": "verify", "run": job["run_id"]}
    if meta["extract"].get("status") != "ok":
        return {**base, "status": "skipped", "reason": f"extract status {meta['extract'].get('status')}"}
    if meta["verify"].get("status") in ("ok", "nothing_to_verify") and not args.force:
        return {**base, "status": "cached"}
    rec = read_transcript(rec_path, tid)
    records = L.parse_lines(jsonl_path.read_text(), str(jsonl_path))
    pending = [r for r in records if r["extraction"]["qualifies"]
               and (args.force or r["verification"]["status"] == "not_run")]
    if not pending:
        meta["verify"] = {"status": "nothing_to_verify", "run_id": job["run_id"], "candidates_verified": 0,
                          "accepted": sum(1 for r in records if r["accepted"]), "rejected": 0}
        if not args.dry_run:
            write_meta(meta_path, meta)
        return {**base, "status": "nothing_to_verify"}

    ext_harness = meta["extract"].get("harness")
    if args.verifier != "auto" and args.verifier == ext_harness:
        detail = f"{L.E_VERIFIER_SAME}: --verifier {args.verifier} is the harness that extracted {tid}"
        return _verify_failed(meta, meta_path, base, detail, t0, args)

    header = L.speaker_header(rec, job["roster"].get(slug))
    workdir = job["workroot"] / f"{slug}-{sid}__verify__{job['run_id']}"
    workdir.mkdir(parents=True, exist_ok=True)
    batches = [pending[i:i + L.VERIFY_BATCH] for i in range(0, len(pending), L.VERIFY_BATCH)]
    all_verdicts: list[dict] = []
    provenance = None
    telemetry_all: list[dict] = []
    for bi, batch in enumerate(batches):
        bundle = {"header": header, "transcript_id": tid,
                  "candidates": [{"prediction_id": r["prediction_id"], "quote_original": r["source"]["quote_original"],
                                  "normalized_claim": r["prediction"]["normalized_claim"],
                                  "timestamp_mark": r["source"]["timestamp_mark"],
                                  "context_before": r["source"]["context_before"],
                                  "context_after": r["source"]["context_after"]} for r in batch]}
        prompt = L.build_verification_prompt(bundle, job["spec"], job["schema_text"])
        if args.dry_run:
            (workdir / f"prompt_{bi}.txt").write_text(prompt)
            continue
        try:
            route = job["router"].pick(None if args.verifier == "auto" else args.verifier, ext_harness)
            if route["harness"] == ext_harness:
                raise RuntimeError(f"{L.E_VERIFIER_SAME}: router returned the extractor's harness {ext_harness}")
            text, telemetry, account = call_harness(route, prompt, args.timeout, workdir / f"b{bi}", args)
        except subprocess.TimeoutExpired:
            return _verify_failed(meta, meta_path, base, f"{E_TIMEOUT}: no answer within {args.timeout}s", t0, args)
        except (RuntimeError, OSError) as exc:
            return _verify_failed(meta, meta_path, base, str(exc), t0, args)
        raw_path = job["out"] / "_raw" / "verify" / route["harness"] / slug / f"{sid}__{route['harness']}__{job['run_id']}_b{bi}.txt"
        L.write_prediction_file(raw_path, text)
        try:
            obj = parse_model_output(text, job["schema"], tid)
        except RuntimeError as exc:
            return _verify_failed(meta, meta_path, base, str(exc), t0, args)
        want = {r["prediction_id"] for r in batch}
        got = [v["prediction_id"] for v in obj["verdicts"]]
        if set(got) != want or len(got) != len(want):
            return _verify_failed(meta, meta_path, base,
                                  f"{L.E_SCHEMA}: verdict ids {sorted(got)} != candidates {sorted(want)}", t0, args)
        provenance = L.normalise_provenance(route["harness"], telemetry, account, route["account_id"])
        telemetry_all.append(telemetry)
        all_verdicts.extend(obj["verdicts"])
    if args.dry_run:
        return {**base, "status": "dry_run", "batches": len(batches), "workdir": str(workdir)}

    verified_at = L.utc_now()
    apply_verdicts(records, all_verdicts, provenance, job["contract"]["contract_id"], job["run_id"], verified_at,
                   {"batches": telemetry_all})
    L.write_prediction_file(jsonl_path, L.serialise_lines(records))
    accepted = sum(1 for r in records if r["accepted"])
    meta["verify"] = {"status": "ok", "run_id": job["run_id"], **provenance, "contract_id": job["contract"]["contract_id"],
                      "verified_at_utc": verified_at, "elapsed_sec": round(time.time() - t0, 1),
                      "candidates_verified": len(pending), "batches": len(batches),
                      "accepted": accepted, "rejected": len(pending) - sum(1 for r in pending if r["accepted"]),
                      "disagreements": sum(1 for r in pending if r["verification"]["agreement"] is False)}
    write_meta(meta_path, meta)
    return {**base, "status": "ok", "harness": provenance["harness"], "verified": len(pending),
            "accepted": accepted, "elapsed": round(time.time() - t0, 1)}


def _verify_failed(meta, meta_path, base, detail, t0, args) -> dict:
    etype = L.classify_exception_detail(detail)
    meta["verify"] = {"status": "failed", "error_type": etype, "detail": detail[:600],
                      "run_id": base["run"], "elapsed_sec": round(time.time() - t0, 1)}
    if not args.dry_run:
        write_meta(meta_path, meta)
    return {**base, "status": "failed", "error_type": etype, "detail": detail[:600]}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def summarise(results: list[dict], stage: str) -> dict:
    rs = [r for r in results if r["stage"] == stage]
    tax: dict[str, int] = {}
    for r in rs:
        if r["status"] == "failed":
            tax[r["error_type"]] = tax.get(r["error_type"], 0) + 1
    elapsed = [r["elapsed"] for r in rs if "elapsed" in r]
    s = {"stage": stage, "attempted": len(rs)}
    for k in ("ok", "cached", "excluded", "failed", "dry_run", "skipped", "nothing_to_verify"):
        s[k] = sum(1 for r in rs if r["status"] == k)
    s["succeeded"] = s["ok"] + s["cached"] + s["nothing_to_verify"]
    s["error_taxonomy"] = tax
    s["median_elapsed_sec"] = round(statistics.median(elapsed), 1) if elapsed else None
    if stage == "extract":
        s["candidates_written"] = sum(r.get("written", 0) for r in rs)
        s["ungrounded"] = sum(r.get("ungrounded", 0) for r in rs)
    else:
        s["verified"] = sum(r.get("verified", 0) for r in rs)
        s["accepted"] = sum(r.get("accepted", 0) for r in rs)
    return s


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcripts", default="data/transcripts_open")
    ap.add_argument("--roster", default="data/roster/final.json")
    ap.add_argument("--out", default="data/predictions")
    ap.add_argument("--stage", choices=["extract", "verify", "both"], default="both")
    ap.add_argument("--extractor", choices=["auto", "fable", "astra", "gemini"], default="auto")
    ap.add_argument("--verifier", choices=["auto", "fable", "astra", "gemini"], default="auto")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--limit-per-leader", type=int, default=None)
    ap.add_argument("--leaders", default="", help="comma-separated slugs; empty means all")
    ap.add_argument("--single", default=None)
    ap.add_argument("--list", default=None, help="a file naming one transcript path per line; replaces --transcripts")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--errors", default=None, help="default <out>/_runs/<run_id>_errors.jsonl")
    ap.add_argument("--exclude", default=str(L.REPO / "scripts" / "predictions_exclusions.json"))
    ap.add_argument("--no-exclude", action="store_true")
    ap.add_argument("--router-exclude", default="antigravity_claude", help="account ids never eligible")
    ap.add_argument("--allow-degraded", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="build prompts into the workdir; no calls, no writes under --out")
    ap.add_argument("--fable-bin", default="claude")
    ap.add_argument("--agy-bin", default="agy")
    ap.add_argument("--astra-model", default="gpt-6-astra")
    ap.add_argument("--gemini-model", default=GEMINI_MODEL)
    ap.add_argument("--skill-dir", default=str(L.SKILL))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("refusing --fable-bin cl: it injects --dangerously-skip-permissions (see AGENTS.md)")
    out = L.guard_data_path(args.out)  # raises before any call if --out is elsewhere under data/
    skill = Path(args.skill_dir)
    stages = ["extract", "verify"] if args.stage == "both" else [args.stage]

    roster = {r["slug"]: r for r in json.loads(Path(args.roster).read_text())["roster"]}
    exclusions = {} if args.no_exclude else L.load_exclusions(args.exclude)
    if args.single:
        paths = [Path(args.single)]
    elif args.list:
        paths = [Path(line.strip()) for line in Path(args.list).read_text().splitlines() if line.strip()]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            raise SystemExit(f"--list names {len(missing)} missing file(s): {missing[:3]}")
    else:
        paths = sorted(Path(args.transcripts).rglob("*.json"))
    if args.leaders:
        want = set(args.leaders.split(","))
        paths = [p for p in paths if p.parent.name in want]
    if not paths:
        raise SystemExit("no transcripts found")
    if args.limit_per_leader is not None:
        paths = apply_per_leader_limit(paths, args.limit_per_leader, lambda p: p.parent.name)

    run_id = f"{L.utc_now().replace(':', '').replace('-', '')}-{args.stage}-{secrets.token_hex(4)}"
    workroot = Path(os.environ.get("TMPDIR", "/tmp")) / "predict-work"
    contracts = {"extract": L.extraction_contract(skill), "verify": L.verification_contract(skill)}
    specs = {"extract": (skill / L.EXTRACTION_SPEC).read_text(), "verify": (skill / L.VERIFICATION_SPEC).read_text()}
    schemas = {"extract": json.loads((skill / L.EXTRACTOR_SCHEMA).read_text()),
               "verify": json.loads((skill / L.VERIFIER_SCHEMA).read_text())}
    log(f"[run {run_id}] {len(paths)} transcripts, stages {stages}, out {out}, "
        f"contracts extract={contracts['extract']['contract_id']} verify={contracts['verify']['contract_id']}")

    router = None
    if not args.dry_run:
        profiles = agy_profiles()
        router = Router([x for x in args.router_exclude.split(",") if x], args.allow_degraded, profiles)
        log(f"[run {run_id}] router accounts: {[a[0] for a in router.accounts]}; excluded {router.exclude_ids}; "
            f"agy profiles {len(profiles)}")

    results: list[dict] = []
    for stage in stages:
        fn = extract_one if stage == "extract" else verify_one
        jobs = [{"args": args, "path": str(p), "out": out, "roster": roster, "exclusions": exclusions,
                 "router": router, "run_id": run_id, "workroot": workroot, "contract": contracts[stage],
                 "spec": specs[stage], "schema": schemas[stage],
                 "schema_text": json.dumps(schemas[stage], indent=1)} for p in paths]
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fn, j): j for j in jobs}
            for fut in cf.as_completed(futs):
                try:
                    r = fut.result()
                except L.RefusedDataWrite:
                    raise
                except Exception as exc:  # noqa: BLE001 -- one job must not kill the pass
                    r = {"id": L.transcript_id_from_path(futs[fut]["path"]), "stage": stage, "run": run_id, "status": "failed",
                         "error_type": L.classify_exception_detail(str(exc)), "detail": f"{type(exc).__name__}: {exc}"[:600]}
                results.append(r)
                log(json.dumps(r, ensure_ascii=False)[:400])

    summaries = [summarise(results, s) for s in stages]
    if not args.dry_run:
        failed = [stamp_failure(dict(r)) for r in results if r["status"] == "failed"]
        errors_path = Path(args.errors) if args.errors else out / "_runs" / f"{run_id}_errors.jsonl"
        L.write_prediction_file(errors_path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in failed))
        manifest = {"run_id": run_id, "args": {k: v for k, v in vars(args).items()}, "stages": stages,
                    "extraction_contract": contracts["extract"], "verification_contract": contracts["verify"],
                    "transcripts": len(paths), "summaries": summaries, "results": results,
                    "router_accounts": [a[0] for a in router.accounts] if router else None,
                    "finished_at_utc": L.utc_now()}
        L.write_prediction_file(out / "_runs" / f"{run_id}.json", json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False))
    for s in summaries:
        print(json.dumps(s, sort_keys=True))
    return 0 if all(s["failed"] == 0 for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
