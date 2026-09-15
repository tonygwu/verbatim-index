#!/usr/bin/env python3
"""Draft P6 speaker labels with a model, measure them against the operator's labels, and queue only doubtful rows.

Pundits plan, P6. The operator asked (2026-09-15) to review only recordings the
model is unsure about instead of all 104. So:

  infer    one Fable call per pilot recording, tools removed, asking the same
           three questions the operator answers (subject present, main speaker,
           venue) plus a confidence. Written to its own file, never into the
           human labels file.
  review   compares every draft with the operator's labels where both exist
           (agreement per field is the calibration), and lists the rows a
           person should still check: confidence below high, subject absent,
           or any disagreement with an existing human label.

A draft is not a human label. When drafts are merged into the labels file for
rows nobody reviewed, each carries `drafted_by_model: true` and `checked_by`
naming the model, so the gate report can count and disclose them.

SPENDS SUBSCRIPTION QUOTA with `infer`. Raw `claude`, never `cl`.

  pundits_speaker_infer.py infer  --study pundits --workers 4
  pundits_speaker_infer.py review --study pundits
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from pundits_pilot import VENUES  # noqa: E402

PILOT = "data-pundits/logs/pilot"
MODELS = {"fable": "claude-fable-5-1", "sonnet": "claude-sonnet-5"}
CONFIDENCE = ("high", "medium", "low")
_lock = threading.Lock()

RULES = """You are checking one YouTube recording for a study of political commentators. You are NOT
grading anyone. Answer three questions about the named SUBJECT, using the whole transcript.

The transcript is automatic captions with no speaker labels. Work out who is talking from
introductions, how people address each other, turn-taking and content.

1. subject_present: does the SUBJECT take part live anywhere in this recording? A recording ABOUT
   the subject, where others discuss them, is false. A played clip of the subject is NOT
   presence: if the subject is heard only in clips that others play, answer false.
2. main_speaker: a host who runs the conversation counts as the main speaker, even when a guest
   talks more; running it means hosting, asking the questions, or running their own stream.
   Otherwise true if the SUBJECT speaks the most words among the live voices, or at least about a
   third of them. Played clips are not live voices.
3. venue: the format, decided by who asks the questions, not by who owns the channel:
   - guest_interview: one person runs it by asking questions and the SUBJECT is among those
     answering, however many answer together.
   - hosted_interview: the SUBJECT runs it by asking questions of one or more guests.
   - panel_show: participants trade views with each other rather than all answering one
     interviewer (split-screen arguments, roundtables, co-hosts discussing the news).
   - debate: organised opposing sides with a named opponent, usually with a moderator or turns.
   - own_show_monologue: the SUBJECT talks to the audience alone.
   - reaction_stream: the SUBJECT plays other material and comments on it.
   - tv_segment: an anchor-led broadcast news segment that is not a multi-guest panel.
   - speech_or_lecture: a prepared talk to a live audience.
   - other: none of these (for example gaming), and say what it is in reason.
   If formats mix, pick the one that fills most of the recording. If the subject is absent, use
   the format of the recording anyway.
4. confidence: high only if the transcript itself makes all three answers clear; otherwise medium
   or low. Say what made you unsure in reason.

Reply with ONLY one JSON object, no prose, exactly these keys:
{"subject_present": true|false, "main_speaker": true|false, "venue": "<one venue>",
 "confidence": "high"|"medium"|"low", "reason": "<two sentences>",
 "evidence": ["<short verbatim transcript fragment>", "<another>"]}
"""


def build_prompt(person: dict, row: dict, rec: dict) -> str:
    handles = ", ".join(person.get("handles") or []) or "none"
    return (f"{RULES}\nSUBJECT: {person['name']} (also known as: {handles}); usual show: {person['show']}\n"
            f"Video title: {rec.get('yt_title') or row['title']}\nUploaded by channel: {rec.get('yt_channel') or row['venue']}\n"
            f"Duration: {round((rec.get('duration_sec') or 0) / 60)} minutes\n\nTRANSCRIPT:\n{rec['text']}\n")


def parse_answer(text: str) -> dict:
    start = (text or "").find("{")
    if start < 0:
        raise ValueError("no JSON object in the answer")
    # The FIRST object only. A greedy {.*} swallowed text after it and failed on
    # rows 52, 96 and 101 of the first live batch ("Extra data").
    a, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(a, dict):
        raise ValueError("the answer's JSON is not an object")
    errs = []
    for f in ("subject_present", "main_speaker"):
        if not isinstance(a.get(f), bool):
            errs.append(f"{f} is not true/false")
    if a.get("venue") not in VENUES:
        errs.append(f"venue {a.get('venue')!r} is not one of the nine")
    if a.get("confidence") not in CONFIDENCE:
        errs.append(f"confidence {a.get('confidence')!r} is not high/medium/low")
    if not isinstance(a.get("reason"), str) or not a["reason"].strip():
        errs.append("reason is empty")
    if errs:
        raise ValueError("; ".join(errs))
    return {k: a[k] for k in ("subject_present", "main_speaker", "venue", "confidence", "reason")} | {
        "evidence": [e for e in (a.get("evidence") or []) if isinstance(e, str)][:3]}


def draft_command(prompt: str, model_key: str) -> list[str]:
    """Raw `claude`, tools removed, same isolation flags as the judge argv in grade.fable_command.

    Sonnet exists because drafting all 104 rows on Fable spent account A's 5-hour
    window on 2026-09-15 (76 of 104 calls failed with budget 0), and Fable is the
    judge whose quota pilot grading needs.
    """
    cmd = ["claude", "-p", prompt, "--model", MODELS[model_key]]
    if model_key == "fable":
        cmd += ["--effort", "max"]
    return cmd + ["--output-format", "json", "--allowedTools", "", "--tools", "", "--permission-prompts", "none",
                  "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "",
                  "--max-turns", "6"]


def call_model(prompt: str, model_key: str, config_dir: str | None, timeout: int = 1800) -> tuple[str, dict]:
    env = dict(os.environ)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)  # account A lives outside any config dir; see CLAUDE.md
    with tempfile.TemporaryDirectory(prefix="speaker-infer-") as jail:
        proc = subprocess.run(draft_command(prompt, model_key), capture_output=True, text=True,
                              timeout=timeout, env=env, cwd=jail, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"cli exit {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}")
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"cli error: {str(payload.get('result'))[:300]}")
    used = list((payload.get("modelUsage") or {}).keys())
    if not any(model_key in m.lower() for m in used):
        raise RuntimeError(f"model mismatch: requested {MODELS[model_key]}, telemetry names {used}")
    return payload.get("result") or "", {"telemetry_models": used, "session_id": payload.get("session_id"),
                                         "duration_ms": payload.get("duration_ms"), "config_dir": config_dir or "default"}


def needs_review(draft: dict, human: dict | None) -> list[str]:
    why = []
    if draft.get("error"):
        return ["the model gave no usable answer"]
    if draft["confidence"] != "high":
        why.append(f"model confidence {draft['confidence']}")
    if not draft["subject_present"]:
        why.append("model says the subject is absent")
    elif not draft["main_speaker"]:
        why.append("model says the subject is not the main speaker")
    if human:
        for f in ("subject_present", "main_speaker", "venue"):
            if human.get(f) != draft[f] and not (f == "venue" and not human.get("subject_present")):
                why.append(f"disagrees with the operator on {f}: operator {human.get(f)!r}, model {draft[f]!r}")
    return why


def calibration(drafts: dict, human: dict) -> dict:
    both = [k for k in drafts if k in human and not drafts[k].get("error")]
    out = {"rows_compared": len(both)}
    for f in ("subject_present", "main_speaker", "venue"):
        rows = [k for k in both if f != "venue" or human[k]["subject_present"]]
        agree = sum(human[k][f] == drafts[k][f] for k in rows)
        out[f] = {"agree": agree, "of": len(rows)}
    high = [k for k in both if drafts[k]["confidence"] == "high"]
    out["high_confidence"] = {"rows": len(high), "all_three_agree": sum(
        all(human[k][f] == drafts[k][f] for f in ("subject_present", "main_speaker")) and
        (not human[k]["subject_present"] or human[k]["venue"] == drafts[k]["venue"]) for k in high)}
    return out


def main() -> int:
    import study_profile as SP
    from atomicio import write_atomic
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("infer")
    i.add_argument("--workers", type=int, default=4)
    i.add_argument("--rows", default=None, help="Comma-separated checklist row numbers; default all.")
    i.add_argument("--config-dirs", default="",
                   help="Comma-separated CLAUDE_CONFIG_DIRs to rotate over; empty means the default account.")
    r = sub.add_parser("review")
    for x in (i, r):
        SP.add_study_arg(x)
        x.add_argument("--model", choices=sorted(MODELS), default="fable",
                       help="Drafts from different models are kept in separate files and never mixed.")
    args = ap.parse_args()
    root = REPO / PILOT
    SP.guard(args.study, str(root))
    keys = {int(n): k for n, k in json.loads((root / "checklist_table_keys.json").read_text()).items()}
    suffix = "" if args.model == "fable" else f"_{args.model}"
    drafts_path = root / f"speaker_inference{suffix}.jsonl"
    drafts = {}
    if drafts_path.exists():
        for line in drafts_path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                drafts[d["key"]] = d
    human_path = root / "human_labels.json"
    human = json.loads(human_path.read_text()) if human_path.exists() else {}

    if args.cmd == "infer":
        roster = {p["slug"]: p for p in json.loads((REPO / "data-pundits/roster/final.json").read_text())["roster"]}
        manifest = {f"{x['leader_slug']}/{x['source_id']}": x for x in
                    map(json.loads, (REPO / "data-pundits/sources/pilot_manifest.jsonl").read_text().splitlines()) if x}
        rows = sorted(keys) if not args.rows else [int(x) for x in args.rows.split(",")]
        todo = [n for n in rows if keys[n] not in drafts or drafts[keys[n]].get("error")]
        print(f"{len(rows)} rows requested, {len(rows) - len(todo)} already drafted, {len(todo)} to call", flush=True)
        tally: Counter = Counter()

        def one(n: int) -> None:
            key = keys[n]
            slug, sid = key.split("/", 1)
            rec = json.loads((REPO / "data-pundits/transcripts" / slug / f"{sid}.json").read_text())
            entry = {"row": n, "key": key, "model": MODELS[args.model]}
            dirs = [d.strip() for d in args.config_dirs.split(",")] if args.config_dirs else [""]
            try:
                text, tel = call_model(build_prompt(roster[slug], manifest[key], rec), args.model,
                                       os.path.expanduser(dirs[n % len(dirs)]) or None)
                entry |= parse_answer(text) | {"telemetry": tel}
                outcome = "drafted"
            except Exception as exc:  # noqa: BLE001 -- recorded with its type, and counted
                entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
                outcome = "error:" + type(exc).__name__
            with _lock:
                tally[outcome] += 1
                with open(drafts_path, "a") as fh:
                    fh.write(json.dumps(entry) + "\n")
                print(f"  row {n:3} {key:50} {outcome}", flush=True)

        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(one, todo))
        print(json.dumps({"attempted": len(todo), "outcomes": dict(tally)}, indent=1))
        return 1 if any(k.startswith("error") for k in tally) else 0

    queue = []
    for n in sorted(keys):
        k = keys[n]
        d = drafts.get(k)
        if d is None:
            queue.append({"row": n, "key": k, "why": ["no model draft yet"]})
            continue
        why = needs_review(d, human.get(k))
        if why and not (k in human and all("disagrees" not in w for w in why)):
            queue.append({"row": n, "key": k, "why": why, "model": {f: d.get(f) for f in
                                                                     ("subject_present", "main_speaker", "venue", "confidence", "reason")}})
    report = {"calibration_against_operator": calibration(drafts, human), "rows": len(keys),
              "drafted": sum(1 for k in keys.values() if k in drafts and not drafts[k].get("error")),
              "operator_labelled": sum(1 for k in keys.values() if k in human),
              "to_review": queue}
    report["model"] = MODELS[args.model]
    write_atomic(root / f"speaker_review_queue{suffix}.json", json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "to_review"} | {"to_review": len(queue)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
