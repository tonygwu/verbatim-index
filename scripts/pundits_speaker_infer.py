#!/usr/bin/env python3
"""Draft P6 speaker labels with a model, measure them against the operator's labels, and queue only doubtful rows.

Pundits plan, P6. The operator asked (2026-09-15) to review only recordings the
model is unsure about instead of all 104. So:

  infer    one Fable call per recording, tools removed, asking the same
           three questions the operator answers (subject present, main speaker,
           venue) plus a confidence. Written to its own file, never into the
           human labels file. --set picks the recordings: the 104-row pilot, or
           the 218-row P6b checklist of the other 29 people.
  review   compares every draft with the operator's blind answers where both
           exist (the calibration), and lists the rows a person should still
           check: confidence below high, subject absent, or any disagreement
           with an existing human label.

A draft is not a human label. When drafts are merged into the labels file for
rows nobody reviewed, each carries `drafted_by_model: true` and `checked_by`
naming the model, so the gate report can count and disclose them.

SPENDS with `infer`: subscription quota through raw `claude` (never `cl`), or,
with --credit-pools, prepaid API credit through `quotapick run` (credit_run.py),
a different harness that each draft's telemetry names.

  pundits_speaker_infer.py infer  --study pundits --workers 4
  pundits_speaker_infer.py infer  --study pundits --set p6b --credit-pools anthropic_api_e,anthropic_api_b
  pundits_speaker_infer.py review --study pundits [--set p6b]
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
#: Each recording set's files. The pilot's checklist maps row numbers to keys in
#: its own file; P6b's checklist is keyed by recording, and a row is its 1-based
#: position in that file. The review page sorts by surname and upload date, so
#: find a P6b recording on the page by its key, never by its row.
SETS = {
    "pilot": {"root": PILOT, "manifest": "data-pundits/sources/pilot_manifest.jsonl"},
    "p6b": {"root": "data-pundits/logs/p6b", "manifest": "data-pundits/sources/p6b_manifest.jsonl"},
}
#: A draft through `quotapick run` (credit_run.py) is a different harness from
#: draft_command: tools absent, no session, an API key. This is what the router
#: must see a pool cover, times its 1.5 margin, before it admits a call. The 218
#: P6b drafts of 2026-10-18 cost at most $1.317 each (p95 $0.693).
CREDIT_EXPECTED_COST_USD = 1.5
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
3. venue: the format, decided by the other live voices, not by who hosts or owns the channel:
   - solo: the SUBJECT talks to the audience with no other live voice, including covering news.
   - reaction: the SUBJECT plays other material and comments on it, with no other live voice.
   - conversation: one or more other live voices talk with the SUBJECT, whoever hosts: interviews
     either way round, panels, co-hosted shows and TV segments.
   - debate: organised opposing sides with at least one named opponent.
   - speech: a prepared talk to a live audience.
   If formats mix, pick the one that fills most of the recording. If the subject is absent, use
   the format of the recording anyway.
4. political_content: true if the recording discusses politics, policy, news or public
   controversy for a real part of its length; false if it is only gaming, entertainment or chat.
5. confidence: high only if the transcript itself makes all your answers clear; otherwise medium
   or low. Say what made you unsure in reason.

Reply with ONLY one JSON object, no prose, exactly these keys:
{"subject_present": true|false, "main_speaker": true|false, "venue": "<one venue>",
 "political_content": true|false,
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
    for f in ("subject_present", "main_speaker", "political_content"):
        if not isinstance(a.get(f), bool):
            errs.append(f"{f} is not true/false")
    if a.get("venue") not in VENUES:
        errs.append(f"venue {a.get('venue')!r} is not one of the five")
    if a.get("confidence") not in CONFIDENCE:
        errs.append(f"confidence {a.get('confidence')!r} is not high/medium/low")
    if not isinstance(a.get("reason"), str) or not a["reason"].strip():
        errs.append("reason is empty")
    if errs:
        raise ValueError("; ".join(errs))
    return {k: a[k] for k in ("subject_present", "main_speaker", "venue", "political_content", "confidence", "reason")} | {
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
    import credit_run  # noqa: PLC0415
    # The 128,000-token cap (VI-23, VI-42). No cut-answer check here yet: most cuts on this
    # harness end while still thinking, which the token gap cannot tell from a cut answer;
    # add credit_run.truncation_detail once VI-43 can pass a thinking-only cut.
    env = credit_run.child_env()
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


def load_keys(root: Path, which: str) -> dict[int, str]:
    """Row number -> recording key for one recording set."""
    if which == "pilot":
        return {int(n): k for n, k in json.loads((root / "checklist_table_keys.json").read_text()).items()}
    # Row n is the n-th key in the file. The review page shows its own order.
    return {n: k for n, k in enumerate(json.loads((root / "human_checklist.json").read_text()), start=1)}


def next_attempt(raw_dir: Path, key: str) -> int:
    """The next attempt number for one recording: one past every raw response already kept.

    Each attempt keeps its own file, so a retry never overwrites the evidence of a
    billed failure. The first credit run named its files `<sid>.json`; that counts
    as attempt 1.
    """
    slug, sid = key.split("/", 1)
    d = raw_dir / slug
    kept = {p.name for p in d.iterdir()} if d.is_dir() else set()
    numbered = [int(name[len(sid) + 1:-5]) for name in kept
                if name.startswith(sid + ".") and name.endswith(".json") and name[len(sid) + 1:-5].isdigit()]
    return 1 + max(numbered + [1 if f"{sid}.json" in kept else 0])


def call_credit(prompt: str, key: str, which: str, pools: list[str], raw_dir: Path, spent) -> tuple[str, dict]:
    """One Fable draft on API credit. Same prompt and parse; the harness is quotapick's."""
    import credit_run
    slug, sid = key.split("/", 1)
    n = next_attempt(raw_dir, key)
    return credit_run.run(prompt, model=MODELS["fable"], effort="max", pools=pools,
                          timeout_s=credit_run.MAX_TIMEOUT_S, expected_cost_usd=CREDIT_EXPECTED_COST_USD,
                          request_id=f"speaker-{which}-{key}-{n}", raw_path=raw_dir / slug / f"{sid}.{n}.json",
                          spent=spent)


def draft_row(n: int, key: str, model_key: str, call) -> tuple[dict, str]:
    """(entry, outcome) for one row. `call()` returns (text, telemetry) or raises.

    The telemetry is kept even when the answer does not parse, so a paid answer
    always names its pool and its cost.
    """
    entry = {"row": n, "key": key, "model": MODELS[model_key]}
    try:
        text, tel = call()
    except Exception as exc:  # noqa: BLE001 -- recorded with its type, and counted
        entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
        return entry, "error:" + type(exc).__name__ + ":" + str(exc).split(":", 1)[0][:40]
    entry["telemetry"] = tel
    try:
        entry |= parse_answer(text)
    except (ValueError, json.JSONDecodeError) as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
        return entry, "error:" + type(exc).__name__ + ":" + str(exc).split(":", 1)[0][:40]
    return entry, "drafted"


def run_rows(todo: list[int], draft, write, workers: int) -> Counter:
    """Draft every row in `todo` and tally the outcomes.

    `draft(n)` returns (entry, outcome); `write(entry)` keeps it. Once one call
    finds the pools exhausted, no further call is made: those rows are counted as
    skipped and written nowhere, so the next run picks them up.
    """
    tally: Counter = Counter()
    exhausted = threading.Event()

    def one(n: int) -> None:
        if exhausted.is_set():
            with _lock:
                tally["skipped:pools_exhausted"] += 1
            return
        entry, outcome = draft(n)
        if outcome.startswith("error:PoolsExhausted"):
            exhausted.set()
        with _lock:
            tally[outcome] += 1
            write(entry)
            print(f"  row {n:3} {entry['key']:50} {outcome}", flush=True)

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    return tally


def exit_code(tally: Counter) -> int:
    """1 when any row failed or was skipped, so a partial run never reads as done."""
    return 1 if any(k.startswith(("error", "skipped")) for k in tally) else 0


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
        # Only what a person labelled. The guide stopped asking about main
        # speaker on 2026-09-15, so a P6b label has no such field, and a missing
        # field is not a disagreement.
        for f in (f for f in ("subject_present", "main_speaker", "venue") if f in human):
            if human.get(f) != draft[f] and not (f == "venue" and not human.get("subject_present")):
                why.append(f"disagrees with the operator on {f}: operator {human.get(f)!r}, model {draft[f]!r}")
    return why


def blind_answers(label: dict) -> dict | None:
    """The answers a person gave before seeing the model's draft, or None if none survive.

    The review page hides the draft until every question has an answer. A label first
    changed after that carries draft_shown and keeps the earlier answers in
    answers_before_draft. A label with draft_shown and no such copy was saved by the
    older page, which showed the draft at once, so none of its answers are blind.
    """
    if "answers_before_draft" in label:
        return label["answers_before_draft"]
    return None if label.get("draft_shown") else label


def _agreement(rows: list, blind: dict, drafts: dict, f: str) -> dict:
    # A field counts only on rows where a person labelled it (P6b labels carry no
    # main_speaker), and venue only where the subject is present.
    rows = [k for k in rows if f in blind[k] and (f != "venue" or blind[k]["subject_present"])]
    return {"agree": sum(blind[k][f] == drafts[k][f] for k in rows), "of": len(rows)}


def calibration(drafts: dict, human: dict) -> dict:
    # Compared on blind answers only: an answer given with the draft on screen is
    # anchored on it, so it says nothing about the draft's accuracy. Leaving a
    # corrected label out instead would drop exactly the rows where the person first
    # disagreed with the model, and raise the agreement.
    blind = {k: blind_answers(human[k]) for k in drafts if k in human}
    assisted = [k for k in blind if blind[k] is None]
    both = [k for k in blind if blind[k] is not None and not drafts[k].get("error")]
    out = {"rows_compared": len(both), "assisted_labels_left_out": len(assisted)}
    for f in ("subject_present", "main_speaker", "venue"):
        out[f] = _agreement(both, blind, drafts, f)
    # Older drafts predate the political question; they are counted, not compared.
    has_political = [k for k in both if isinstance(drafts[k].get("political_content"), bool)]
    out["political_content"] = {**_agreement(has_political, blind, drafts, "political_content"),
                                "draft_missing": len(both) - len(has_political)}
    # The page lists a draft that needs no review under "Model was confident", which
    # tells the person, before they answer, that the model found the subject present.
    # So presence is also reported for that section alone, and for the rest.
    confident = [k for k in both if not needs_review(drafts[k], None)]
    out["subject_present_by_section"] = {
        "model_confident": _agreement(confident, blind, drafts, "subject_present"),
        "check_first": _agreement([k for k in both if k not in confident], blind, drafts, "subject_present")}
    # What changed once the draft was on screen, and how much of it moved to the model.
    changed = [k for k in both if "answers_before_draft" in human[k]]
    out["changed_after_draft"] = {"labels": len(changed)}
    for f in ("subject_present", "venue", "political_content"):
        moved = [k for k in changed if f in blind[k] and human[k].get(f) != blind[k][f]]
        out["changed_after_draft"][f] = {"changed": len(moved),
                                         "to_model": sum(human[k].get(f) == drafts[k].get(f) for k in moved)}
    high = [k for k in both if drafts[k]["confidence"] == "high"]
    # "all three" means every one of the three a person labelled on that row.
    out["high_confidence"] = {"rows": len(high), "all_three_agree": sum(
        all(blind[k][f] == drafts[k][f] for f in ("subject_present", "main_speaker") if f in blind[k]) and
        (not blind[k]["subject_present"] or blind[k]["venue"] == drafts[k]["venue"]) for k in high)}
    return out


def merge_drafts(drafts: dict, human: dict, model: str) -> tuple[dict, dict]:
    """Human labels unchanged, plus a model draft for every row nobody labelled.

    A draft enters as a label only for presence, venue and political content (the
    fields the P6 gate reads), marked drafted_by_model with checked_by naming the
    model, so the gate report can count and disclose it. A human label always wins.
    """
    merged = {k: dict(v) for k, v in human.items()}
    added, skipped = 0, []
    for key, d in sorted(drafts.items()):
        if key in human:
            continue
        if d.get("error"):
            skipped.append(key)
            continue
        if not isinstance(d.get("political_content"), bool):
            raise RuntimeError(f"draft for {key} has no political_content; re-draft it with the current instructions")
        merged[key] = {"subject_present": d["subject_present"], "venue": d["venue"],
                       "political_content": d["political_content"], "checked_by": f"model:{model}",
                       "drafted_by_model": True, "notes": f"model draft, confidence {d['confidence']}: {d['reason']}"}
        added += 1
    return merged, {"human_labels": len(human), "merged_from_model": added, "skipped_errors": skipped}


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
    i.add_argument("--credit-pools", default="",
                   help="Comma-separated quotapick credit pools; each Fable draft runs through `quotapick run "
                        "--only` these pools on prepaid API credit instead of a subscription account.")
    r = sub.add_parser("review")
    mg = sub.add_parser("merge", help="Write labels_merged.json: human labels plus model drafts for unlabelled rows.")
    for x in (i, r, mg):
        SP.add_study_arg(x)
        x.add_argument("--model", choices=sorted(MODELS), default="fable",
                       help="Drafts from different models are kept in separate files and never mixed.")
        x.add_argument("--set", dest="which", choices=sorted(SETS), default="pilot",
                       help="Which recordings: the 104-row pilot, or the P6b checklist of the other 29 people.")
    args = ap.parse_args()
    root = REPO / SETS[args.which]["root"]
    SP.guard(args.study, str(root))
    keys = load_keys(root, args.which)
    pools = [p.strip() for p in getattr(args, "credit_pools", "").split(",") if p.strip()]
    if pools and (args.model != "fable" or args.config_dirs):
        ap.error("--credit-pools runs Fable on API credit; it takes neither --model sonnet nor --config-dirs")
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
        manifest = {}
        for x in map(json.loads, filter(str.strip, (REPO / SETS[args.which]["manifest"]).read_text().splitlines())):
            # No key repeats in either manifest today; if one ever does, the first wins.
            manifest.setdefault(f"{x['leader_slug']}/{x['source_id']}", x)
        rows = sorted(keys) if not args.rows else [int(x) for x in args.rows.split(",")]
        unknown = [n for n in rows if n not in keys]
        if unknown:
            ap.error(f"--rows names rows the {args.which} checklist does not have: {unknown}")
        todo = [n for n in rows if keys[n] not in drafts or drafts[keys[n]].get("error")]
        print(f"{len(rows)} rows requested, {len(rows) - len(todo)} already drafted, {len(todo)} to call"
              + (f", on credit pools {pools}" if pools else ""), flush=True)
        cost = {"usd": 0.0}
        dirs = [d.strip() for d in args.config_dirs.split(",")] if args.config_dirs else [""]

        def spent(usd: float) -> None:
            with _lock:
                cost["usd"] += usd

        def draft(n: int) -> tuple[dict, str]:
            key = keys[n]
            slug, sid = key.split("/", 1)
            rec = json.loads((REPO / "data-pundits/transcripts" / slug / f"{sid}.json").read_text())
            prompt = build_prompt(roster[slug], manifest[key], rec)
            if pools:
                return draft_row(n, key, args.model, lambda: call_credit(
                    prompt, key, args.which, pools, root / "_raw" / "speaker_inference", spent))
            return draft_row(n, key, args.model, lambda: call_model(
                prompt, args.model, os.path.expanduser(dirs[n % len(dirs)]) or None))

        def write(entry: dict) -> None:
            with open(drafts_path, "a") as fh:
                fh.write(json.dumps(entry) + "\n")

        tally = run_rows(todo, draft, write, args.workers)
        # Costs the responses named. A timeout names none, so the sum can be short
        # of what the pool's ledger books for the run.
        print(json.dumps({"attempted": len(todo), "outcomes": dict(tally), "cost_usd": round(cost["usd"], 4)}, indent=1))
        return exit_code(tally)

    if args.cmd == "merge":
        merged, rep = merge_drafts(drafts, human, MODELS[args.model])
        write_atomic(root / "labels_merged.json", json.dumps(merged, indent=1, ensure_ascii=False))
        print(json.dumps(rep | {"total_labels": len(merged), "rows": len(keys)}, indent=1))
        return 1 if rep["skipped_errors"] else 0

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
