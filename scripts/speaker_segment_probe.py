#!/usr/bin/env python3
"""Can an LLM reading only the caption text say who spoke each word?

The judges already do this implicitly: the rubric says "infer turn boundaries from
context", and a judge that infers them wrongly scores the wrong person, as Gemini did
on marc-benioff/exacttarget-9game7. This probe makes the step explicit. Each model
reads one whole transcript, with the named subject and the recording's metadata, and
returns the speaker turns. Its turns are scored against the operator's word ranges
from the speaker-check page (`speaker_audit_page.py`), which are the ground truth.

  run    SPENDS SUBSCRIPTION QUOTA. One call per arm, recording and repeat. Raw CLI
         output and parsed turns go under --out; nothing is scored.
  score  Reads a run and a copy of the answers file, and reports per arm: word
         accuracy on the words the person labelled, a confusion table, words the
         model left unclear, and the quote answers the model's turns imply, derived
         with the same `quote_review` the page uses.

Every arm runs under the P3 sandbox, which denies reads under the verbatim-index
container, so no model can open the answers file. The Claude arms also have every
built-in tool removed and their session transcripts are checked for tool calls.
Astra and Gemini keep provider-side web search, which cannot be switched off (see
AGENTS.md); their search counts are recorded, never hidden.

Turns are reported by position, which a model cannot count reliably across
thousands of words. So the transcript carries a marker before every tenth word, and
each turn names its nearest marker AND its first five words. The words fix the
exact start; a turn whose words cannot be found near its marker falls back to the
marker and is counted, per arm, as `start_from_marker_only`.

  .venv/bin/python scripts/speaker_segment_probe.py run --data ../data \\
      --page data/predictions/_experiments/RUN/leaders/speaker_check.html \\
      --keys marc-benioff/exacttarget-9game7 --arms fable,opus,astra,gemini \\
      --repeats 2 --out data/predictions/_experiments/RUN/segmentation/NAME
  .venv/bin/python scripts/speaker_segment_probe.py score \\
      --run data/predictions/_experiments/RUN/segmentation/NAME \\
      --answers data/predictions/_experiments/RUN/leaders/human_answers.json \\
      --page data/predictions/_experiments/RUN/leaders/speaker_check.html
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade as G  # noqa: E402
from atomicio import write_atomic  # noqa: E402
from pundits_speaker_spans import quote_review, sidecar_path, token_kinds  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
#: The container of every clone and every data checkout; the P3 sandbox denies it.
DENIED_ROOT = REPO.parent.resolve()
MARK_EVERY = 10
FIRST_WORDS = 5
SEARCH_AHEAD = 40
SPEAKERS = ("subject", "other", "unclear")
ARMS = {
    "fable": {"kind": "claude", "model": "claude-fable-5-1", "effort": "max"},
    "opus": {"kind": "claude", "model": "claude-opus-5-5", "effort": "max"},
    "astra": {"kind": "astra", "model": "gpt-6-astra", "effort": "max"},
    "gemini": {"kind": "gemini", "model": G.GEMINI_MODEL, "effort": "high (in the model name)"},
}
# Written down before the run, per arm: one retry after any failure. A call that
# fails both attempts is the MODEL's failure and counts as wrong for every word and
# quote the person labelled in that recording (operator's rule, 2026-09-28), unless
# its last error is infrastructure (INFRA_LABELS), which says nothing about the model
# and removes that recording from every arm instead.
# Gemini's own harness also retries transients inside the call; its attempt count
# is recorded in telemetry, and that asymmetry is reported as a named confound.
MAX_ATTEMPTS = 2
TIMEOUT = 2400
INFRA_LABELS = {G.E_AUTH, G.E_TRANSIENT}

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


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def marked_text(tokens: list[str]) -> str:
    return " ".join((f"⟨{i}⟩ " if i % MARK_EVERY == 0 else "") + t for i, t in enumerate(tokens))


def norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


def build_prompt(rec: dict, person: dict, tokens: list[str]) -> str:
    return PROMPT.format(name=person["name"], role=person.get("role") or "", every=MARK_EVERY, first=FIRST_WORDS,
                         title=rec.get("yt_title") or rec.get("declared_title") or "",
                         channel=rec.get("yt_channel") or "", upload=rec.get("yt_upload_date") or "",
                         description=(rec.get("yt_description") or "")[:700], text=marked_text(tokens))


def call_claude(prompt: str, model: str, config_dir: str, workdir: Path, raw: Path) -> tuple[str, dict]:
    """The Fable judge's argv with the model swapped, under the sandbox, with no tools.

    Served identity is asserted from `modelUsage`, and the session transcript must
    show zero tool calls, exactly as the pundits harness requires of Fable.
    """
    cmd = G.fable_command(prompt, "claude")
    cmd[cmd.index("--model") + 1] = model
    cmd = [*G.sandbox_wrapper(DENIED_ROOT), *cmd, "--tools", ""]
    env = dict(os.environ, CLAUDE_CONFIG_DIR=config_dir)
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env,
                          cwd=str(workdir), stdin=subprocess.DEVNULL)
    G.save_cli_response(raw, proc)
    if proc.returncode != 0:
        raise RuntimeError(G.classify_cli_failure(proc.returncode, proc.stdout, proc.stderr)[1])
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"{G.E_CLI}: {str(payload.get('result'))[:400]}")
    used = payload.get("modelUsage") or {}
    served = [m for m in used if model in m]
    if not served:
        raise RuntimeError(f"{G.E_MODEL_MISMATCH}: requested {model}, telemetry names {list(used)}")
    calls = G.fable_transcript_tool_calls(config_dir, payload.get("session_id"))
    if calls is None:
        raise RuntimeError(f"{G.E_NO_TRANSCRIPT}: no session transcript, so tool use cannot be ruled out")
    if calls:
        raise RuntimeError(f"{G.E_TOOL_ATTEMPT}: {len(calls)} tool call(s): {json.dumps(calls[:2])[:300]}")
    return payload.get("result") or "", {
        "requested_model": model, "served_model": served[0], "served_model_verified": True,
        "telemetry_models": list(used), "config_dir": config_dir, "effort": "max",
        "transcript_tool_calls": 0, "output_tokens": used[served[0]].get("outputTokens"),
        "duration_ms": payload.get("duration_ms")}


def call_arm(arm: str, prompt: str, workdir: Path, raw: Path, accounts: dict) -> tuple[str, dict]:
    spec = ARMS[arm]
    if spec["kind"] == "claude":
        return call_claude(prompt, spec["model"], accounts["claude"], workdir, raw)
    if spec["kind"] == "astra":
        text, tel = G.call_astra(prompt, TIMEOUT, workdir, model=spec["model"], raw_response_path=raw,
                                 wrapper=G.sandbox_wrapper(DENIED_ROOT), config_dir=accounts["codex"])
        return text, {**tel, "served_model_verified": False}
    text, tel = G.call_gemini(prompt, accounts["gemini"], TIMEOUT, workdir=str(workdir), model=spec["model"],
                              wrapper=G.sandbox_wrapper(DENIED_ROOT))
    write_atomic(raw, json.dumps({"response": text, "telemetry": tel}, ensure_ascii=False) + "\n")
    return text, tel


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
    """Turns as end-exclusive word ranges, and how each start was fixed."""
    # Timestamp and turn marks are not words a speaker said, and the model is asked to
    # quote first words without markers, so they never take part in a match.
    normed = ["" if re.fullmatch(r"\[\d{2}:\d{2}:\d{2}\]|>{2,}", t) else norm(t) for t in tokens]
    starts, how = [], {"by_words": 0, "start_from_marker_only": 0}
    for t in turns:
        m = max(0, min(t["marker"], len(tokens) - 1))
        # Models copy a timestamp into first_words despite the instruction (seen in the
        # pilot on all three arms), so marks are dropped from both sides of the match.
        want = [w for w in (norm(x) for x in str(t.get("first_words") or "").split()
                            if not re.fullmatch(r"\[\d{2}:\d{2}:\d{2}\]|>{2,}", x)) if w][:FIRST_WORDS]
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


def run(args) -> int:
    data, page = Path(args.data), Path(args.page)
    roster = {p["slug"]: p for p in json.loads((data / "roster" / "final.json").read_text())["roster"]}
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"REFUSING: {out} is not empty; name a new run directory")
    arms = args.arms.split(",")
    if set(arms) - set(ARMS):
        raise SystemExit(f"REFUSING: unknown arm(s) {sorted(set(arms) - set(ARMS))}")
    keys = args.keys.split(",") if args.keys else []
    cells = None
    if args.retry_infra_of:
        # Exactly the cells an earlier run lost to infrastructure, with their repeat
        # numbers, so `merge` can put each result back where the failure was.
        prior = json.loads(Path(args.retry_infra_of).read_text())
        cells = sorted((r["arm"], r["key"], r["repeat"]) for r in prior if failure_label(r) in INFRA_LABELS)
        if not cells:
            raise SystemExit("nothing to retry: no infrastructure failure in " + args.retry_infra_of)
        keys = sorted({k for _, k, _ in cells})
        arms = sorted({a for a, _, _ in cells})
    elif not keys:
        raise SystemExit("REFUSING: name --keys, or --retry-infra-of an earlier results.json")
    jobs, prompts = [], {}
    for key in keys:
        side = json.loads(sidecar_path(page, key).read_text())
        rec = json.loads((data / "transcripts_open" / f"{key}.json").read_text())
        if hashlib.sha256(rec["text"].encode()).hexdigest() != side["text_sha256"]:
            raise SystemExit(f"REFUSING: {key} transcript differs from the one the page was built on")
        prompts[key] = build_prompt(rec, roster[key.split("/")[0]], side["tokens"])
        jobs += [(arm, key, r) for r in range(args.repeats) for arm in arms] if cells is None else \
            [c for c in cells if c[1] == key]
    accounts = {"claude": str(Path(args.claude_config_dir).expanduser()),
                "codex": str(Path(args.codex_home).expanduser()), "gemini": str(Path(args.gemini_home).expanduser())}
    scratch = Path(args.scratch)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "started_at_utc": utc(), "arms": {a: ARMS[a] for a in arms}, "keys": keys,
                "retry_infra_of": args.retry_infra_of, "cells": [list(c) for c in cells] if cells else None,
                "repeats": args.repeats, "max_attempts": MAX_ATTEMPTS, "timeout_s": TIMEOUT,
                "accounts": accounts, "sandbox_denies": str(DENIED_ROOT),
                "code_revision": subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
                "prompt_sha256": {k: hashlib.sha256(p.encode()).hexdigest() for k, p in prompts.items()}}
    write_atomic(out / "manifest.json", json.dumps(manifest, indent=1) + "\n")
    lock = threading.Lock()
    results = []

    def one(job):
        arm, key, r = job
        tag = f"{arm}__{key.replace('/', '__')}__r{r}"
        rec = {"arm": arm, "key": key, "repeat": r, "attempts": 0, "outcome": None, "errors": []}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            rec["attempts"] = attempt
            raw = out / "raw" / f"{tag}__a{attempt}.json"
            raw.parent.mkdir(parents=True, exist_ok=True)
            work = scratch / f"{tag}__a{attempt}"
            shutil.rmtree(work, ignore_errors=True)
            t0 = time.time()
            try:
                text, tel = call_arm(arm, prompts[key], work, raw, accounts)
            except subprocess.TimeoutExpired:
                rec["errors"].append({"attempt": attempt, "error": f"{G.E_TIMEOUT}: no answer within {TIMEOUT} s",
                                      "seconds": round(time.time() - t0)})
                continue
            except Exception as exc:  # noqa: BLE001 - every failure is recorded with its taxonomy label
                rec["errors"].append({"attempt": attempt, "error": str(exc)[:500], "seconds": round(time.time() - t0)})
                continue
            rec.update({"telemetry": tel, "seconds": round(time.time() - t0), "raw": str(raw.relative_to(out))})
            try:
                rec["turns"] = parse_turns(text)
                rec["outcome"] = "parsed"
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                rec["outcome"] = "unparseable"
                rec["parse_error"] = str(exc)[:300]
                rec["response_head"] = text[:500]
            break
        else:
            rec["outcome"] = "failed"
        with lock:
            results.append(rec)
            print(f"{utc()} {tag}: {rec['outcome']} after {rec['attempts']} attempt(s)"
                  f"{'; ' + rec['errors'][-1]['error'][:160] if rec['errors'] else ''}", flush=True)
            write_atomic(out / "results.json", json.dumps(sorted(results, key=lambda x: (x["key"], x["arm"], x["repeat"])),
                                                         indent=1, ensure_ascii=False) + "\n")

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(one, jobs))
    tally = {}
    for r in results:
        tally.setdefault(r["arm"], {}).setdefault(r["outcome"], 0)
        tally[r["arm"]][r["outcome"]] += 1
    print(json.dumps({"attempted": len(jobs), "by_arm_outcome": tally}))
    return 0


def labels_from(ranges: list[dict], n: int) -> list[str | None]:
    lab = [None] * n
    for r in ranges:
        for i in range(r["start"], r["end"]):
            lab[i] = r["speaker"]
    return lab


def failure_label(r: dict) -> str | None:
    """None for a parsed run; otherwise the taxonomy label of what finally failed."""
    if r["outcome"] == "parsed":
        return None
    if r["outcome"] == "unparseable":
        return "unparseable"
    if not r.get("errors"):
        return r["outcome"]
    last = r["errors"][-1]
    # Runs before 2026-09-28 stored subprocess.TimeoutExpired's own text, which names
    # no taxonomy label; the attempt ran exactly TIMEOUT seconds.
    if last["error"].startswith("Command '") and last.get("seconds", 0) >= TIMEOUT:
        return G.E_TIMEOUT
    return last["error"].split(":", 1)[0]


def merge(args) -> int:
    """A new run directory: the base run, with each INFRASTRUCTURE failure replaced by
    the top-up run's result for the same arm, recording and repeat.

    Only infrastructure failures may be topped up: they say nothing about the model,
    so a fresh try under the same attempt cap is a retry of the harness, not a second
    chance for the model. A model failure is final, and a top-up result for one
    refuses the merge. Both inputs are left as they are.
    """
    base, top, out = Path(args.base), Path(args.topup), Path(args.out)
    if out.exists():
        raise SystemExit(f"REFUSING: {out} exists")
    results = json.loads((base / "results.json").read_text())
    extra = {(r["arm"], r["key"], r["repeat"]): r for r in json.loads((top / "results.json").read_text())}
    merged, replaced = [], []
    for r in results:
        k = (r["arm"], r["key"], r["repeat"])
        if k in extra:
            if failure_label(r) not in INFRA_LABELS:
                raise SystemExit(f"REFUSING: {k} ended in {failure_label(r) or 'a parsed answer'}, "
                                 "not an infrastructure failure; only those may be topped up")
            t = extra.pop(k)
            merged.append({**t, "raw": str(Path("..") / top.name / t["raw"]) if t.get("raw") else None,
                           "topped_up_from": {"run": base.name, "attempts": r["attempts"], "errors": r["errors"]}})
            replaced.append(f"{k[0]} {k[1]} r{k[2]}: {failure_label(r)} -> {failure_label(t) or 'parsed'}")
        else:
            merged.append(r)
    if extra:
        raise SystemExit(f"REFUSING: the top-up has results the base run lacks: {sorted(extra)}")
    manifest = json.loads((base / "manifest.json").read_text())
    manifest["topups"] = manifest.get("topups", []) + [{"run": top.name, "replaced": replaced, "merged_at_utc": utc()}]
    out.mkdir(parents=True)
    write_atomic(out / "manifest.json", json.dumps(manifest, indent=1) + "\n")
    write_atomic(out / "results.json", json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    print("\n".join(replaced) or "nothing replaced")
    return 0


def score(args) -> int:
    run_dir, page = Path(args.run), Path(args.page)
    results = json.loads((run_dir / "results.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    answers = json.loads(Path(args.answers).read_text())
    data = json.loads(re.search(r"^const D = (\{.*\});$", page.read_text(), re.M).group(1).replace("<\\/", "</"))
    quotes = {r["key"]: r["quotes"] for r in data["quote_rows"]}
    report = {"answers_sha256": hashlib.sha256(Path(args.answers).read_bytes()).hexdigest(), "scored_at_utc": utc(),
              "arms": {}, "per_run": [], "not_scored": []}
    keys = sorted({r["key"] for r in results} & set(answers.get("spans", {})))
    # A recording is scored only when every arm has every repeat in. A model failure
    # counts against that arm alone; an infrastructure failure removes the recording
    # from EVERY arm, so no arm is scored on words another arm never had the chance at.
    arms = sorted({r["arm"] for r in results})
    for key in keys:
        runs = [r for r in results if r["key"] == key]
        bad = [f"{r['arm']} r{r['repeat']}: infrastructure ({failure_label(r)})" for r in runs
               if failure_label(r) in INFRA_LABELS]
        # A run still in progress, or never started, is missing, not absent from the design.
        have = {(r["arm"], r["repeat"]) for r in runs}
        bad += [f"{a} r{i}: not yet run" for a in manifest["arms"] for i in range(manifest["repeats"])
                if (a, i) not in have]
        if bad:
            report["not_scored"].append({"key": key, "reason": bad})
            continue
        side = json.loads(sidecar_path(page, key).read_text())
        toks, kinds = side["tokens"], token_kinds(side["tokens"])
        human_ann = answers["spans"][key]
        human = labels_from(human_ann["ranges"], len(toks))
        for r in runs:
            failed = failure_label(r)
            ranges, how = resolve(r["turns"], toks) if failed is None else ([], None)
            model = labels_from(ranges, len(toks))
            cmp_ = [(human[i], model[i]) for i in range(len(toks))
                    if kinds[i] == "speech" and human[i] in ("subject", "other")]
            conf = {}
            for h, m in cmp_:
                conf[f"{h}->{m}"] = conf.get(f"{h}->{m}", 0) + 1
            correct = sum(1 for h, m in cmp_ if h == m)
            # Per-speaker recall, because the labelled words lean heavily toward the
            # subject: the cards centre on quotes credited to the subject, so a model
            # that calls every word "subject" would score high on accuracy alone.
            recall = {s: (round(sum(1 for h, m in cmp_ if h == s and m == s) / n_s, 4) if n_s else None)
                      for s in ("subject", "other") for n_s in [sum(1 for h, _ in cmp_ if h == s)]}
            all_subject = round(sum(1 for h, _ in cmp_ if h == "subject") / len(cmp_), 4) if cmp_ else None
            speech = [i for i in range(len(toks)) if kinds[i] == "speech"]
            share = None if failed else sum(1 for i in speech if model[i] == "subject") / len(speech)
            ann = {"key": key, "text_sha256": side["text_sha256"], "token_count": side["token_count"],
                   "checked_by": "model", "ranges": [{"start": x["start"], "end": x["end"], "speaker": x["speaker"],
                                                      "origin": "human"} for x in ranges]}
            qres = []
            for q in quotes.get(key, []):
                h = (answers["attribution"].get(q["qid"]) or {}).get("answer")
                if not h:
                    continue
                qres.append({"qid": q["qid"], "human": h,
                             "model": "failed" if failed else quote_review(q, side, ann)["answer"]})
            row = {"arm": r["arm"], "key": key, "repeat": r["repeat"], "words_compared": len(cmp_),
                   "word_accuracy": round(correct / len(cmp_), 4) if cmp_ else None, "recall": recall,
                   "baseline_all_subject": all_subject, "confusion": conf,
                   "failed": failed, "turns": len(r.get("turns") or []), "starts": how,
                   "model_subject_share_pct": None if share is None else round(100 * share, 1),
                   "quotes": qres, "quotes_agree": sum(1 for q in qres if q["human"] == q["model"]),
                   "served_model": (r.get("telemetry") or {}).get("served_model"),
                   "web_search_queries": (r.get("telemetry") or {}).get("web_search_queries")}
            report["per_run"].append(row)
    for arm in arms:
        rows = [x for x in report["per_run"] if x["arm"] == arm]
        n = sum(x["words_compared"] for x in rows)
        ok = sum(round(x["word_accuracy"] * x["words_compared"]) for x in rows if x["word_accuracy"] is not None)
        per = {sp: [sum(v for k, v in x["confusion"].items() if k.startswith(sp + "->")) for x in rows] for sp in ("subject", "other")}
        hit = {sp: [x["confusion"].get(f"{sp}->{sp}", 0) for x in rows] for sp in ("subject", "other")}
        done = [x for x in rows if not x["failed"]]
        n_done = sum(x["words_compared"] for x in done)
        ok_done = sum(round(x["word_accuracy"] * x["words_compared"]) for x in done if x["word_accuracy"] is not None)
        report["arms"][arm] = {"runs_scored": len(rows), "words_compared": n,
                               # Headline: a failed run scores 0 on every word it was asked about.
                               "word_accuracy": round(ok / n, 4) if n else None,
                               "word_accuracy_completed_runs": round(ok_done / n_done, 4) if n_done else None,
                               "failed_runs": [f"{x['key']} r{x['repeat']}: {x['failed']}" for x in rows if x["failed"]],
                               "subject_recall": round(sum(hit["subject"]) / sum(per["subject"]), 4) if sum(per["subject"]) else None,
                               "other_recall": round(sum(hit["other"]) / sum(per["other"]), 4) if sum(per["other"]) else None,
                               "baseline_all_subject": round(sum(per["subject"]) / n, 4) if n else None,
                               "quotes_agree": f"{sum(x['quotes_agree'] for x in rows)}/{sum(len(x['quotes']) for x in rows)}",
                               "excluded_infra": [f"{r['key']} r{r['repeat']}: {failure_label(r)}" for r in results
                                                  if r["arm"] == arm and failure_label(r) in INFRA_LABELS]}
    write_atomic(Path(args.report or run_dir / "score.json"), json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(report["arms"], indent=1))
    for x in report["per_run"]:
        print(f"{x['arm']:7} {x['key'][:40]:40} r{x['repeat']} {'FAILED ' + x['failed'] + ' ' if x['failed'] else ''}"
              f"acc={x['word_accuracy']} n={x['words_compared']} "
              f"quotes {x['quotes_agree']}/{len(x['quotes'])} share={x['model_subject_share_pct']} "
              f"turns={x['turns']} starts={x['starts']} {x['confusion']}")
    if report["not_scored"]:
        print("NOT SCORED:", json.dumps(report["not_scored"]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    for a in ("--data", "--page", "--out"):
        r.add_argument(a, required=True)
    r.add_argument("--keys", help="comma-separated slug/source_id recordings")
    r.add_argument("--retry-infra-of", help="an earlier results.json: rerun exactly its infrastructure failures")
    r.add_argument("--arms", default="fable,opus,astra,gemini")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--claude-config-dir", default="~/.claude-b")
    r.add_argument("--codex-home", default="~/.codex")
    r.add_argument("--gemini-home", default="~")
    r.add_argument("--scratch", required=True, help="per-call working directories, OUTSIDE the container")
    m = sub.add_parser("merge")
    for a in ("--base", "--topup", "--out"):
        m.add_argument(a, required=True)
    s = sub.add_parser("score")
    for a in ("--run", "--answers", "--page"):
        s.add_argument(a, required=True)
    s.add_argument("--report")
    args = ap.parse_args()
    if args.cmd == "run" and Path(args.scratch).resolve().is_relative_to(DENIED_ROOT):
        raise SystemExit("REFUSING: --scratch sits inside the sandboxed container; the models could not work there")
    return {"run": run, "merge": merge, "score": score}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
