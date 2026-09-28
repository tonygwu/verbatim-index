#!/usr/bin/env python3
"""The "who spoke" step: Astra splits each NEW transcript into speaker turns, and
a check-only pass flags quotes the boards credit to someone who did not say them.

WHY. Captions carry no speaker labels, so every judge infers turns while it
grades, and on marc-benioff/exacttarget-9game7 Gemini inferred them wrongly and
graded will.i.am as Benioff. MEASURED 2026-09-28 (AGENTS.md, "Can a model say who
spoke each word from the caption text alone?"): asked to do only this, four models
matched the operator's labels on 98.9 to 99.9% of words whenever they finished,
and only Astra finished every run, 20 of 20. So the step is HARD-PINNED to Astra
(operator's decision, 2026-09-28): `gpt-6-astra` at max effort, under the P3
sandbox, with no fallback model. A transcript Astra cannot segment is recorded
as failed with its taxonomy label, never segmented by something else.

WHAT IT DOES AND DOES NOT DO (operator's decisions, 2026-09-28).
  check-only    It flags; it changes no grade, no score and no prediction. Gating
                on it is a later, separate decision.
  new only      It segments a transcript whose `fetched_at_utc`, read from the
                record and never from the file's mtime, is at or after
                SEGMENT_SINCE_UTC. The existing corpus is not backfilled, because
                a call costs a median 11 minutes and ~72k tokens of Codex quota.
  leaders data  Turns are stored beside the corpus in speaker_turns/, which the
                leaders loop (repo-0) writes. The predictions board shares the
                same transcripts_open, so its new recordings are covered too.

The prompt is the one measured, byte for byte: PROMPT_TEMPLATE_SHA256 pins it, and
a changed prompt is an unmeasured segmenter, so the module refuses to run.

  segment   one Astra call per new, unsegmented transcript. Retry once; a second
            failure is final and written as a failed record. An infrastructure
            failure (quota, transient, router refusal) writes NOTHING, so the next
            cycle retries it.
  check     for every segmented transcript, flags: each blinded judge whose
            subject share sits SHARE_DISSENT_GAP or more from Astra's; each judge
            evidence quote Astra's turns give to someone else; each ACCEPTED
            prediction whose quote Astra's turns give to someone else.

  .venv/bin/python scripts/speaker_turns.py segment --data data [--dry-run]
  .venv/bin/python scripts/speaker_turns.py check --data data --out data/logs/speaker_check.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade as G  # noqa: E402
from atomicio import write_atomic  # noqa: E402
from pundits_speaker_spans import token_kinds  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
#: The container of every clone and every data checkout; the P3 sandbox denies it.
DENIED_ROOT = REPO.parent.resolve()

SEGMENTER_MODEL = "gpt-6-astra"
SEGMENT_SINCE_UTC = "2026-09-28T00:00:00Z"
MAX_ATTEMPTS = 2
TIMEOUT = 2400
INFRA_LABELS = {G.E_AUTH, G.E_TRANSIENT, "router_unavailable"}
TURNS_DIR = "speaker_turns"
DEFAULT_WORKERS = 2

MARK_EVERY = 10
FIRST_WORDS = 5
SEARCH_AHEAD = 40
SPEAKERS = ("subject", "other", "unclear")
MARKS = re.compile(r"\[\d{2}:\d{2}:\d{2}\]|>{2,}")

PROMPT = """You are labelling who is speaking in a transcript. It is a YouTube caption track for one recording. Captions carry no speaker labels, so you must infer from the words and context who is talking.

The named subject is {name} ({role}).

Recording metadata:
- Title: {title}
- Channel: {channel}
- Uploaded: {upload}
- Description: {description}

Task: divide the WHOLE transcript into consecutive speaker turns, from the first word to the last. Give each turn one speaker:
- "subject" when {name} is speaking,
- "other" when anyone else is speaking: a host, interviewer, co-guest, audience member, announcer, narrator, or a clip being played,
- "unclear" when you cannot tell who is speaking.
When a turn is "other" and you can tell who it is, put their name or role in "who".

The transcript below has a position marker such as ⟨120⟩ immediately before word 120, every {every} words. Words are counted from 0, and timestamp marks such as [00:01:02] count as words. Markers are not part of what was said. For each turn report:
- "marker": the number of the nearest marker at or before the turn's first word,
- "first_words": the turn's first {first} words exactly as they appear in the transcript, without markers,
- "speaker": "subject", "other" or "unclear",
- "who": optional, for "other".
A turn lasts until the next turn starts. Start a new turn only where the speaker changes.

Use only this text. Do not look anything up, and do not use any tool.

Return ONLY a JSON object, with no other text: {{"turns": [{{"marker": 0, "first_words": "...", "speaker": "other", "who": "host"}}]}}

TRANSCRIPT:
{text}
"""
#: The template measured on 2026-09-28; verified against the experiment's recorded
#: per-recording prompt hashes on all ten recordings before it was pinned.
PROMPT_TEMPLATE_SHA256 = "e95d21bc671593b4b1b9daffc3bb56a6a645b89e30cb5d76facae82d34451d76"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def assert_prompt_pinned() -> None:
    if sha(PROMPT) != PROMPT_TEMPLATE_SHA256:
        raise SystemExit("REFUSING: the segmentation prompt differs from the one measured on 2026-09-28. "
                         "A changed prompt is an unmeasured segmenter: re-run speaker_segment_probe.py "
                         "against the operator's labels, then update PROMPT_TEMPLATE_SHA256.")


def marked_text(tokens: list[str]) -> str:
    return " ".join((f"⟨{i}⟩ " if i % MARK_EVERY == 0 else "") + t for i, t in enumerate(tokens))


def norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


def build_prompt(rec: dict, person: dict, tokens: list[str]) -> str:
    return PROMPT.format(name=person["name"], role=person.get("role") or "", every=MARK_EVERY, first=FIRST_WORDS,
                         title=rec.get("yt_title") or rec.get("declared_title") or "",
                         channel=rec.get("yt_channel") or "", upload=rec.get("yt_upload_date") or "",
                         description=(rec.get("yt_description") or "")[:700], text=marked_text(tokens))


def parse_turns(text: str) -> list[dict]:
    """The turns list out of a response. A response that is not that JSON raises."""
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if m:
        s = m.group(1)
    obj = json.loads(s[s.index("{"): s.rindex("}") + 1])
    turns = obj["turns"]
    if not isinstance(turns, list) or not turns:
        raise ValueError("turns is not a non-empty list")
    for t in turns:
        if t.get("speaker") not in SPEAKERS or not isinstance(t.get("marker"), int):
            raise ValueError(f"malformed turn {json.dumps(t)[:200]}")
    return turns


def resolve(turns: list[dict], tokens: list[str]) -> tuple[list[dict], dict]:
    """Turns as end-exclusive word ranges, and how each start was fixed.

    The first words fix the exact start; the marker only says where to look. A turn
    whose words cannot be found within SEARCH_AHEAD of its marker starts at the
    marker and is counted as `start_from_marker_only`, never hidden.
    """
    # Timestamp and turn marks are not words a speaker said, and the model is asked to
    # quote first words without markers, so they never take part in a match.
    normed = ["" if MARKS.fullmatch(t) else norm(t) for t in tokens]
    starts, how = [], {"by_words": 0, "start_from_marker_only": 0}
    for t in turns:
        m = max(0, min(t["marker"], len(tokens) - 1))
        # Models copy a timestamp into first_words despite the instruction (seen in the
        # pilot on all three arms), so marks are dropped from both sides of the match.
        want = [w for w in (norm(x) for x in str(t.get("first_words") or "").split()
                            if not MARKS.fullmatch(x)) if w][:FIRST_WORDS]
        found = None
        if want:
            for i in range(m, min(len(tokens), m + SEARCH_AHEAD)):
                if not normed[i]:
                    continue
                got = [w for w in normed[i:i + len(want) + 3] if w][:len(want)]
                if got == want:
                    found = i
                    break
        how["by_words" if found is not None else "start_from_marker_only"] += 1
        starts.append((found if found is not None else m, t["speaker"], t.get("who")))
    starts.sort(key=lambda x: x[0])
    ranges = []
    for k, (a, spk, who) in enumerate(starts):
        b = starts[k + 1][0] if k + 1 < len(starts) else len(tokens)
        if b > a:
            ranges.append({"start": a, "end": b, "speaker": spk, "who": who})
    return ranges, how


def labels_from(ranges: list[dict], n: int) -> list[str | None]:
    lab = [None] * n
    for r in ranges:
        for i in range(r["start"], r["end"]):
            lab[i] = r["speaker"]
    return lab


def speaker_of(labels: list, kinds: list[str], a: int, z: int) -> str:
    """Who said words a..z-1, by the turns: subject, other, both, unclear or unlabelled."""
    got = {labels[i] for i in range(a, z) if kinds[i] == "speech"}
    if not got or None in got:
        return "unlabelled"
    if "unclear" in got:
        return "unclear"
    return "both" if len(got) > 1 else next(iter(got))


# ------------------------------------------------------------------- segment --

def turns_path(data: Path, key: str) -> Path:
    slug, sid = key.split("/", 1)
    return data / TURNS_DIR / slug / f"{sid}.json"


def select(data: Path, since: str) -> tuple[list[str], dict]:
    """Recordings to segment, and a report of every recording that was not chosen and why."""
    todo, skipped = [], {"before_cutoff": 0, "done": 0, "missing_fetched_at": []}
    for f in sorted((data / "transcripts_open").glob("*/*.json")):
        key = f"{f.parent.name}/{f.stem}"
        rec = json.loads(f.read_text())
        when = rec.get("fetched_at_utc")
        if not when:
            # Never fall back to the file's mtime: a loop touches files constantly.
            skipped["missing_fetched_at"].append(key)
            continue
        if when < since:
            skipped["before_cutoff"] += 1
            continue
        out = turns_path(data, key)
        if out.exists() and json.loads(out.read_text()).get("text_sha256") == sha(rec["text"]):
            skipped["done"] += 1
            continue
        todo.append(key)
    return todo, skipped


def failure_label(exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return G.E_TIMEOUT
    msg = str(exc)
    return msg.split(":", 1)[0].strip() if ":" in msg else type(exc).__name__


def segment_one(data: Path, key: str, person: dict, router, work_root: Path, call=None) -> dict:
    """Segment one recording. Returns the report row; writes the turns record unless the
    last failure was infrastructure, which the next cycle retries."""
    call = call or G.call_astra
    rec = json.loads((data / "transcripts_open" / f"{key}.json").read_text())
    tokens = rec["text"].split()
    prompt = build_prompt(rec, person, tokens)
    errors, text, tel, route = [], None, None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = data / TURNS_DIR / "_raw" / f"{key}__a{attempt}.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        work = work_root / f"{key.replace('/', '__')}__a{attempt}"
        work.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            route = router.pick("astra", None)
            text, tel = call(prompt, TIMEOUT, work, model=SEGMENTER_MODEL, raw_response_path=raw,
                             wrapper=G.sandbox_wrapper(DENIED_ROOT), config_dir=route["config_dir"])
            turns = parse_turns(text)
            ranges, how = resolve(turns, tokens)
            break
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append({"attempt": attempt, "label": "unparseable", "error": str(exc)[:300],
                           "seconds": round(time.time() - t0)})
        except Exception as exc:  # noqa: BLE001 - every failure is recorded with its taxonomy label
            label = "router_unavailable" if type(exc).__name__ == "RouterUnavailable" else failure_label(exc)
            errors.append({"attempt": attempt, "label": label, "error": str(exc)[:300],
                           "seconds": round(time.time() - t0)})
    else:
        last = errors[-1]["label"]
        if last in INFRA_LABELS:
            return {"key": key, "outcome": "infra_retry_next_cycle", "label": last, "errors": errors}
        record = {"schema_version": 1, "key": key, "status": "failed", "failure": last, "errors": errors,
                  "attempts": len(errors), "text_sha256": sha(rec["text"]), "token_count": len(tokens),
                  "prompt_template_sha256": PROMPT_TEMPLATE_SHA256, "requested_model": SEGMENTER_MODEL,
                  "segmented_at_utc": utc()}
        write_atomic(turns_path(data, key), json.dumps(record, indent=1, ensure_ascii=False) + "\n")
        return {"key": key, "outcome": "failed", "label": last, "errors": errors}
    kinds = token_kinds(tokens)
    labels = labels_from(ranges, len(tokens))
    speech = [i for i in range(len(tokens)) if kinds[i] == "speech"]
    share = round(100 * sum(1 for i in speech if labels[i] == "subject") / len(speech), 1) if speech else None
    record = {"schema_version": 1, "key": key, "status": "ok", "attempts": len(errors) + 1, "errors": errors,
              "text_sha256": sha(rec["text"]), "token_count": len(tokens),
              "prompt_template_sha256": PROMPT_TEMPLATE_SHA256, "prompt_sha256": sha(prompt),
              "requested_model": SEGMENTER_MODEL, "account_id": route.get("account_id"),
              "telemetry": tel, "segmented_at_utc": utc(),
              "turns": turns, "ranges": ranges, "starts": how, "subject_share_pct": share}
    write_atomic(turns_path(data, key), json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    return {"key": key, "outcome": "ok", "attempts": record["attempts"], "subject_share_pct": share}


def segment(args, router=None, call=None) -> int:
    assert_prompt_pinned()
    data = Path(args.data)
    todo, skipped = select(data, args.since)
    if args.keys:
        wanted = set(args.keys.split(","))
        todo = [k for k in todo if k in wanted]
    report = {"since": args.since, "selected": len(todo), "skipped": skipped, "attempted": 0,
              "succeeded": 0, "failed": 0, "infra_retry_next_cycle": 0, "error_taxonomy": {}, "rows": []}
    if skipped["missing_fetched_at"]:
        print(f"REFUSED {len(skipped['missing_fetched_at'])} transcript(s) with no fetched_at_utc: "
              f"{skipped['missing_fetched_at'][:5]}")
    if args.dry_run or not todo:
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
        print("would segment:" if todo else "nothing to segment", *todo[:20])
        return 0
    work_root = Path(tempfile.gettempdir()).resolve() / "verbatim-speaker-turns"
    if work_root.is_relative_to(DENIED_ROOT):
        raise SystemExit(f"REFUSING: working directory {work_root} is inside the sandboxed container")
    roster = {p["slug"]: p for p in json.loads((data / "roster" / "final.json").read_text())["roster"]}
    if router is None:
        from extract_predictions import Router
        router = Router(exclude_ids=[], allow_degraded=False, gemini_profiles=[])
    lock = threading.Lock()

    def one(key):
        row = segment_one(data, key, roster[key.split("/")[0]], router, work_root, call)
        with lock:
            report["attempted"] += 1
            report["rows"].append(row)
            if row["outcome"] == "ok":
                report["succeeded"] += 1
            else:
                report["failed" if row["outcome"] == "failed" else "infra_retry_next_cycle"] += 1
                report["error_taxonomy"][row["label"]] = report["error_taxonomy"].get(row["label"], 0) + 1
            print(f"{utc()} {key}: {row['outcome']}" + (f" ({row['label']})" if row.get("label") else ""), flush=True)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(one, todo))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
    return 0


# --------------------------------------------------------------------- check --

def check(args) -> int:
    from pundits_verify_page import locate
    from wrong_person_screen import SHARE_DISSENT_GAP
    data = Path(args.data)
    report = {"generated_at_utc": utc(), "share_dissent_gap": SHARE_DISSENT_GAP, "segmented": 0,
              "failed_segmentations": [], "stale": [],
              "checked": {"judge_shares": 0, "evidence_quotes": 0, "evidence_not_located": 0,
                          "prediction_quotes": 0},
              "flags": {"share_dissent": [], "evidence_quotes": [], "prediction_quotes": []},
              "unclear_or_unlabelled": {"evidence_quotes": 0, "prediction_quotes": 0}}
    for tp in sorted((data / TURNS_DIR).glob("*/*.json")):
        if tp.parent.name == "_raw":
            continue
        t = json.loads(tp.read_text())
        key = t["key"]
        if t["status"] != "ok":
            report["failed_segmentations"].append({"key": key, "failure": t["failure"]})
            continue
        rec = json.loads((data / "transcripts_open" / f"{key}.json").read_text())
        raw = rec["text"]
        if sha(raw) != t["text_sha256"]:
            # The words moved under the turns, so every offset is suspect. Say so.
            report["stale"].append(key)
            continue
        report["segmented"] += 1
        tokens = raw.split()
        kinds = token_kinds(tokens)
        labels = labels_from(t["ranges"], len(tokens))
        slug, sid = key.split("/", 1)
        for gp in sorted((data / "grades").glob(f"*/{slug}/{sid}__*__blinded__r0.json")):
            g = json.loads(gp.read_text())
            body = g.get("grade") or {}
            if g.get("validation_errors") or not isinstance(body.get("dimensions"), dict):
                continue
            share = body.get("subject_speech_share_pct")
            if isinstance(share, (int, float)) and t["subject_share_pct"] is not None:
                report["checked"]["judge_shares"] += 1
                if abs(share - t["subject_share_pct"]) >= SHARE_DISSENT_GAP:
                    report["flags"]["share_dissent"].append(
                        {"key": key, "judge": g["judge"], "judge_share": share, "astra_share": t["subject_share_pct"]})
            for dim, d in sorted(body["dimensions"].items()):
                for e in d.get("evidence") or []:
                    span = locate(e.get("quote") or "", raw)
                    if span is None:
                        report["checked"]["evidence_not_located"] += 1
                        continue
                    report["checked"]["evidence_quotes"] += 1
                    who = speaker_of(labels, kinds, span[0], span[1] + 1)
                    if who in ("other", "both"):
                        report["flags"]["evidence_quotes"].append(
                            {"key": key, "judge": g["judge"], "dimension": dim, "astra_says": who,
                             "quote": (e.get("quote") or "")[:160]})
                    elif who != "subject":
                        report["unclear_or_unlabelled"]["evidence_quotes"] += 1
        pp = data / "predictions" / slug / f"{sid}.jsonl"
        for line in (pp.read_text().splitlines() if pp.exists() else []):
            if not line.strip():
                continue
            p = json.loads(line)
            if p.get("accepted") is not True:
                continue
            s = p["source"]
            a, z = s["quote_char_start"], s["quote_char_end"]
            if raw[a:z] != s["quote_original"]:
                raise SystemExit(f"REFUSING: prediction {p['prediction_id']} offsets do not reproduce its quote in {key}")
            toks = list(re.finditer(r"\S+", raw))
            inside = [i for i, m in enumerate(toks) if m.end() > a and m.start() < z]
            report["checked"]["prediction_quotes"] += 1
            who = speaker_of(labels, kinds, inside[0], inside[-1] + 1)
            if who in ("other", "both"):
                report["flags"]["prediction_quotes"].append(
                    {"key": key, "prediction_id": p["prediction_id"], "astra_says": who, "quote": s["quote"][:160]})
            elif who != "subject":
                report["unclear_or_unlabelled"]["prediction_quotes"] += 1
    if args.out:
        write_atomic(Path(args.out), json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    f = report["flags"]
    print(f"speaker check: {report['segmented']} segmented transcript(s); "
          f"{len(f['prediction_quotes'])} published prediction quote(s), {len(f['evidence_quotes'])} judge evidence "
          f"quote(s) and {len(f['share_dissent'])} judge share(s) disagree with Astra's turns; "
          f"{len(report['failed_segmentations'])} failed segmentation(s), {len(report['stale'])} stale")
    for kind in ("prediction_quotes", "evidence_quotes", "share_dissent"):
        for x in f[kind]:
            print(f"REVIEW {kind}: {json.dumps(x, ensure_ascii=False)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("segment")
    s.add_argument("--data", default="data")
    s.add_argument("--since", default=SEGMENT_SINCE_UTC, help="fetched_at_utc cutoff (UTC ISO)")
    s.add_argument("--keys", help="restrict to these slug/source_id recordings (still subject to --since)")
    s.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    s.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--data", default="data")
    c.add_argument("--out")
    args = ap.parse_args()
    return {"segment": segment, "check": check}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
