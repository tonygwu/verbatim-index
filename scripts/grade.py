#!/usr/bin/env python3
"""Grade speaking transcripts with two independent judge harnesses.

Judge A: Claude Fable 5.1 at max reasoning effort, driven by `claude -p`.
Judge B: OpenAI GPT-6 Astra at max reasoning effort, driven by `codex exec`.

Both judges receive the same rubric and the same transcript and return the
same JSON schema. Raw stdout from every call is kept on disk so a human can
audit what the model actually said, not just what the parser extracted.

Design rules this script enforces:
  - Model identity is asserted from the harness telemetry, not assumed. A call
    whose telemetry names a different model than requested is a failure.
  - Every failure lands in a typed taxonomy. Nothing is silently dropped.
  - Output is validated: all 15 sub-criteria present, scores in range, the
    weighted `overall` consistent with the dimension scores, and evidence
    quotes within the 25-word cap.
  - Already-completed calls are skipped, so the run is resumable.

Usage:
  grade.py --transcripts data/transcripts_clean --out data/grades \
      --judges fable,astra --modes blinded,open --repeats 1 --workers 4
  grade.py --single data/fixtures/x.json --judges fable --repeats 5 --mode blinded
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude" / "skills" / "leader-transcript-grader"
RUBRIC_PATH = SKILL / "RUBRIC.md"
SCHEMA_PATH = SKILL / "judge_output.schema.json"

def grading_contract() -> dict:
    """Fingerprint the exact text that determines a score.

    Only two files reach a judge: RUBRIC.md and judge_output.schema.json. The
    grader's SKILL.md never does, so editing it cannot move a number. Hashing
    these two, and storing the hash in every grade record, is what makes the
    corpus auditable: without it, editing the rubric mid-run would silently
    leave a mix of scores from different rubrics with no way to tell them
    apart after the fact.

    `contract_id` is the hash of both files together, because a score is
    produced by the pair, not by either alone.
    """
    rb = RUBRIC_PATH.read_bytes()
    sb = SCHEMA_PATH.read_bytes()
    return {
        "contract_id": hashlib.sha256(rb + sb).hexdigest()[:12],
        "rubric_sha256": hashlib.sha256(rb).hexdigest(),
        "schema_sha256": hashlib.sha256(sb).hexdigest(),
        "rubric_bytes": len(rb),
        "schema_bytes": len(sb),
    }


SUBCRITERIA = ["C1", "C2", "C3", "C4", "I1", "I2", "I3", "I4", "I5", "I6", "I7", "T1", "T2", "T3", "T4"]
WEIGHTS = {"d1_clarity": 0.20, "d2_insight": 0.45, "d3_technical_depth": 0.35}
MAX_QUOTE_WORDS = 25

# Failure taxonomy.
E_CLI = "cli_nonzero_exit"
E_TIMEOUT = "cli_timeout"
E_EMPTY = "empty_response"
E_NOJSON = "no_json_in_response"
E_BADJSON = "json_parse_error"
E_SCHEMA = "schema_validation_failed"
E_MODEL_MISMATCH = "model_identity_mismatch"
E_AUTH = "auth_or_quota"
E_REFUSED = "judge_declined_to_score"
E_TOOL_ATTEMPT = "judge_attempted_tool_use"

# A judge can return valid JSON that is not a grade. GPT-6 Astra declined to
# score a Palantir CEO transcript, saying it "cannot assign the requested
# numerical scores to an assessment encompassing U.S. democracy and political
# issues", and returned qualitative observations instead. Claude Fable scored
# the same eight transcripts without objection.
#
# That is NOT a schema failure and must not be filed as one. A refusal is
# systematic: it recurs for the same subject, so one leader silently loses a
# judge while everyone else keeps two. Left buried in a validation-error count,
# it would quietly turn a two-judge score into a one-judge score for whichever
# leaders a judge finds objectionable.
REFUSAL_MARKERS = ("assessment_limit", "refusal", "cannot_comply")
# Astra phrased the same refusal three different ways across five calls, under
# two different keys. Match on the behaviour, not on one wording.
REFUSAL_PHRASES = ("cannot assign", "can't assign", "can\u2019t assign", "unable to assign",
                   "cannot complete", "can't complete", "can\u2019t complete",
                   "cannot provide", "can't provide", "decline to", "scoring schema")
REFUSAL_TEXT_KEYS = ("reason", "status", "note", "error", "message", "explanation")


def looks_like_refusal(obj: dict) -> str | None:
    """Return the judge's stated reason if this is a refusal, else None."""
    if "dimensions" in obj:
        return None
    for key in REFUSAL_MARKERS:
        if isinstance(obj.get(key), str) and obj[key].strip():
            return obj[key].strip()
    for key in REFUSAL_TEXT_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and any(ph in val.lower() for ph in REFUSAL_PHRASES):
            return val.strip()
    return None

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, file=sys.stderr, flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claude_config_dirs() -> list[str]:
    """Derive the Claude account list rather than hardcoding letters.

    Account A lives at ~/.claude but must be addressed by UNSETTING
    CLAUDE_CONFIG_DIR, not by pointing at that path. The others are the
    ~/.claude-? directories, whatever letters happen to exist.
    """
    home = Path.home()
    dirs = ["__DEFAULT__"]
    dirs.extend(sorted(str(p) for p in home.glob(".claude-?") if p.is_dir()))
    return dirs


def account_label(config_dir: str) -> str:
    """The short name this script prints for one account, and accepts for it."""
    return "default" if config_dir == "__DEFAULT__" else Path(config_dir).name


def select_named_accounts(all_dirs: list[str], names: str) -> list[str]:
    """Restrict the Fable rotation to the accounts named on the command line.

    Measured headroom cannot decide this one. An account whose subscription
    Fable window is spent still serves Fable when paid usage credits are
    enabled on it, and the usage API reports 0.00 remaining either way. So
    when only some accounts have credits, the operator has to say which.

    A name may be `default`, the config-dir basename such as `.claude-b`,
    that basename without the dot, or the full path. A name matching nothing
    raises instead of narrowing the rotation to the wrong account or to none.
    """
    by_key: dict[str, str] = {}
    for d in all_dirs:
        label = account_label(d)
        by_key[label] = d
        by_key[label.lstrip(".")] = d
        by_key[d] = d
    picked: list[str] = []
    for raw in names.split(","):
        name = raw.strip()
        if not name:
            continue
        if name not in by_key:
            raise SystemExit(
                f"--fable-accounts {name!r} matches no account. "
                f"Known: {sorted(account_label(d) for d in all_dirs)}")
        if by_key[name] not in picked:
            picked.append(by_key[name])
    if not picked:
        raise SystemExit("--fable-accounts was given but named no account")
    return picked


def fable_accounts_from_router(accounts, rows) -> tuple[list[str], dict[str, float]]:
    """Map llm-quota-router accounts and pick rows onto this script's config dirs.

    `accounts` is an iterable of (account_id, provider, config_dir, is_default)
    in configuration order; `rows` are the `ranked` plus `excluded` entries of
    one routing decision, each carrying `account` and `remaining`. Only
    provider "claude" accounts are Claude Code accounts. The default account is
    returned as the "__DEFAULT__" sentinel because it is selected by UNSETTING
    CLAUDE_CONFIG_DIR, never by naming its directory.

    An account with no row, or a row with no `remaining`, is left out of the
    headroom map rather than given 0 or 1: unmeasured is unknown, not empty.
    """
    remaining_by_id: dict[str, float] = {}
    for row in rows:
        acct = row.get("account")
        rem = row.get("remaining")
        if acct is not None and rem is not None and acct not in remaining_by_id:
            remaining_by_id[acct] = float(rem)

    dirs: list[str] = []
    headroom: dict[str, float] = {}
    for account_id, provider, config_dir, is_default in accounts:
        if provider != "claude":
            continue
        key = "__DEFAULT__" if is_default else str(config_dir)
        dirs.append(key)
        if account_id in remaining_by_id:
            headroom[key] = remaining_by_id[account_id]
    return dirs, headroom


def fable_accounts() -> tuple[list[str], dict[str, float], str]:
    """The Claude accounts that can run the Fable judge, with measured headroom.

    Uses the llm-quota-router library (https://github.com/tonygwu/llm-quota-router)
    when it is installed: `load_config()` lists the operator's accounts and
    `select_account(model="fable", record=False)` measures every account's
    remaining Fable window without booking any quota. Without the library the
    accounts are the ~/.claude-? directories in plain order and nothing is
    measured, which is worse but never wrong. The returned note says which of
    the two happened, so the log never implies a measurement that did not occur.
    """
    try:
        from quota_router import select_account
        from quota_router.config import load_config
    except ImportError:
        dirs = claude_config_dirs()
        return dirs, {}, ("quota_router not installed: rotating over the ~/.claude-? "
                          "directories in plain order with no headroom measurement")
    try:
        cfg = load_config()
        decision = select_account(model="fable", record=False)
    except Exception as exc:  # noqa: BLE001 -- the router failing must not stop grading
        dirs = claude_config_dirs()
        return dirs, {}, f"quota_router failed ({exc!r}): keeping plain account order"
    accounts = [(a.id, a.provider, a.config_dir, a.is_default_config_dir)
                for a in cfg.enabled_accounts()]
    rows = list(decision.ranked) + list(decision.excluded)
    dirs, headroom = fable_accounts_from_router(accounts, rows)
    note = f"fable headroom measured by quota_router for {len(headroom)}/{len(dirs)} Claude accounts"
    claude_ids = {a[0] for a in accounts if a[1] == "claude"}
    for w in decision.warnings:
        # Router warnings are "<account_id>: <text>"; match the id exactly, so a
        # warning about antigravity_claude is not mistaken for one about claude.
        if any(w.startswith(f"{cid}:") for cid in claude_ids):
            note += f"\n  router warning: {w}"
    return dirs, headroom, note


def order_accounts_by_fable(accounts: list[str], headroom: dict[str, float],
                            floor: float = 0.02) -> list[str]:
    """Richest Fable window first, and drop the ones with nothing left.

    `floor` is the point below which an account is treated as exhausted.
    Accounts with no measurement keep their original position rather than
    being dropped, because an unmeasured account is unknown, not empty.
    """
    if not headroom:
        return list(accounts)
    live = [a for a in accounts if headroom.get(a, 1.0) > floor]
    if not live:                       # everything is spent; try them all anyway
        return list(accounts)
    return sorted(live, key=lambda a: -headroom.get(a, 1.0))


def assign_accounts(judge: str, idx: int, accounts: list[str], judges: list[str]) -> str:
    """Pick the account for one job, counting per judge rather than globally.

    The bug this replaces: jobs are enumerated over product(paths, judges),
    so with judges = [fable, astra] every Fable job has an even index. Under
    `accounts[idx % len(accounts)]` that reaches only the even-numbered
    accounts, which on this machine were the two with no Fable allowance
    left. Dividing by the judge count restores a per-judge sequence, so
    Fable walks all of them.
    """
    if not accounts:
        raise ValueError("no accounts to rotate over")
    n_judges = max(1, len(judges))
    return accounts[(idx // n_judges) % len(accounts)]


def apply_per_leader_limit(paths, limit, slug_of):
    """Keep at most `limit` transcripts per leader.

    `limit` is None for no cap and 0 for none at all. The old code tested
    the value for truthiness, so 0 read as "no cap" and a pass meant to be
    skipped instead graded the whole corpus.
    """
    if limit is None:
        return list(paths)
    if limit < 0:
        raise ValueError(f"--limit-per-leader must be >= 0, got {limit}")
    if limit == 0:
        return []
    by_leader: dict[str, list] = {}
    for p in paths:
        by_leader.setdefault(slug_of(p), []).append(p)
    kept = []
    for slug in sorted(by_leader):
        kept.extend(sorted(by_leader[slug], key=str)[:limit])
    return kept


def order_breadth_first(jobs: list[dict]) -> list[dict]:
    """Round-robin the queue across leaders instead of walking them alphabetically.

    The queue is built by itertools.product over a SORTED path list, so every
    cycle presented the leaders in the same order. A judge that runs out of
    quota part-way down therefore stopped in the same place every time.

    MEASURED 2026-09-06: Fable held blinded grades for exactly the
    alphabetically first 20 slugs and none of the last 20. Its failures split
    57 in the prefix against 168 in the suffix, because the live quota was all
    spent on the prefix and everything after it failed fast on the session
    limit. yann-lecun sorts 40th of 40 and had 8 transcripts ready and 0 Fable
    grades, while half the roster kept deepening. That is a coverage bias, not
    a backlog: re-running the same order can never fix it.

    Ordering by how many grades a leader already has gives every leader its
    first grade before any leader gets its second, so a quota stop truncates
    depth evenly across the roster instead of amputating the tail of the
    alphabet. Grades already on disk count towards that depth, or a
    well-covered leader would jump the queue again on the next cycle.
    """
    done: dict[tuple, int] = {}
    cached, pending = [], []
    for job in jobs:
        key = (job["judge"], job["mode"], job["rec"]["leader_slug"])
        if Path(job["dest"]).exists():
            done[key] = done.get(key, 0) + 1
            cached.append(job)          # costs no quota, so let it resolve first
        else:
            pending.append((key, job))

    depth = dict(done)
    ranked = []
    for key, job in pending:
        d = depth.get(key, 0)
        ranked.append((d, key[2], job))
        depth[key] = d + 1
    ranked.sort(key=lambda t: (t[0], t[1]))
    return cached + [t[2] for t in ranked]


# How many times a refusing judge is retried on the SAME model.
# MEASURED 2026-09-07: Astra refused 11 blinded transcripts on content grounds,
# and a controlled re-run of three found the refusals are not deterministic. It
# refused elon-musk/lex-fridman-jn3kpf and tim-cook/the-uptake-by-bridgemake-fwv5jc
# in production and graded both on the re-run, same transcript and prompt. Only
# alex-karp/the-free-press-qdqhf7 refused twice.
#
# There is deliberately NO fallback to another model. A second model's grades
# could not be calibrated: there would only ever be a handful of them, far below
# aggregate.MIN_CALIBRATION_N, so they would enter the leaderboard unrescaled and
# about six points high, and only on the leaders where refusals concentrate. A
# grade that cannot be calibrated is not worth having, so the call is not made.
REFUSAL_ATTEMPTS = 3


def _policy_fields(job: dict) -> dict:
    """The retry outcome, flattened onto the grade record.

    `served_model` is what aggregate.py keys calibration on, so a judge whose
    model is bumped mid-corpus is never pooled across two distributions.
    """
    p = job.get("_policy") or {}
    if not p:
        return {}
    return {"served_model": p.get("served_model"),
            "refusal_attempts": p.get("attempts")}


def grade_with_refusal_policy(call, primary: str, attempts: int = REFUSAL_ATTEMPTS):
    """Retry a refusing judge on the same model, up to `attempts` times.

    `call(model)` must return `(parsed_object, telemetry)`.

    Returns `(obj, telemetry, info)` where info carries `attempts`,
    `served_model` and `refused`. A transcript that grades first time costs
    exactly one call: there is no speculative retry.
    """
    obj, telemetry, n = None, {}, 0
    for _ in range(max(1, attempts)):
        n += 1
        obj, telemetry = call(primary)
        if looks_like_refusal(obj) is None:
            return obj, telemetry, {"attempts": n, "served_model": primary, "refused": False}
    return obj, telemetry, {"attempts": n, "served_model": primary, "refused": True}


def count_tool_events(events: list[dict]) -> dict[str, int]:
    """Count the tools a codex judge actually used, from the stream we already parse.

    MEASURED 2026-09-07: `codex exec` with these exact production flags answers
    "YES - web.run" when asked whether it has web search, and the judge was
    observed running web_search and citing a page that named the blinded
    subject. `-s read-only` restricts the filesystem, not the network, and none
    of five candidate config keys switched it off.

    The behaviour is deliberately left alone, because changing it now would make
    new grades incomparable with the corpus already graded. What is not
    acceptable is that it was INVISIBLE: across 706 Astra grades nothing recorded
    whether a lookup happened, so the exposure could not be measured at all.
    Only completed items are counted, since a started item that never finishes
    did not return anything to the judge.
    """
    counts = {"web_search": 0, "command_execution": 0, "file_search": 0}
    for e in events:
        if e.get("type") != "item.completed":
            continue
        kind = (e.get("item") or {}).get("type")
        if kind in counts:
            counts[kind] += 1
    return counts


def stamp_failure(rec: dict) -> dict:
    """Put the time on a failure record, in UTC, before it is written.

    MEASURED 2026-09-07: data/logs/grade_errors_blind.jsonl held 75 failures and
    not one carried a timestamp, so telling a Fable spend-limit failure from an
    hour ago apart from one two days old meant inferring it from somewhere else.
    The file is also rewritten whole each run, which makes a bare count read as
    current when it may not be.

    The clock is datetime.now(timezone.utc), never a file mtime and never the
    local clock, per the repo rule. An existing stamp is left alone so a record
    that already carries its own time is not overwritten with the write time.
    """
    if not rec.get("failed_at_utc"):
        rec["failed_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return rec


def classify_cli_failure(rc: int, stdout: str, stderr: str) -> tuple[str, str]:
    """Work out why the Claude CLI exited non-zero.

    The CLI puts the reason in STDOUT, not stderr. A quota refusal exits 1
    with empty stderr and `result` saying "You've reached your Fable limit".
    A blocked tool call exits 1 with `stop_reason: tool_use`. The old code
    raised on the return code before reading stdout, so 262 failures across
    two unrelated causes were all logged as a bare `cli_nonzero_exit` with
    nothing to tell them apart.
    """
    payload = None
    if stdout and stdout.strip().startswith("{"):
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None

    if payload is not None:
        result = str(payload.get("result") or "")
        low = result.lower()
        # "spend limit" and the cc_cli_limit_message marker cover the PAID
        # usage-credit refusal, which shares no wording with the subscription
        # one: it says "You've hit your monthly spend limit", so none of
        # "reached your", "usage limit" or "quota" matches it. Without them a
        # quota stop is logged as cli_nonzero_exit and reads as a crash.
        #
        # "session limit" is the 5-hour window, a third wording again: "You've
        # hit your session limit · resets 2:40pm". Captured from claude-e on
        # 2026-09-07, where 75 refusals in one pass were all filed as crashes.
        # The family is "You've <verb> your <scope> limit", and this matcher
        # tests whole phrases, so every new <scope> the CLI ships needs adding.
        if any(s in low for s in ("reached your", "usage limit", "rate limit",
                                  "out of credit", "quota", "upgrade to",
                                  "spend limit", "session limit",
                                  "cc_cli_limit_message")):
            return E_AUTH, f"{E_AUTH}: {result[:400]}"
        if payload.get("stop_reason") == "tool_use":
            return E_TOOL_ATTEMPT, (
                f"{E_TOOL_ATTEMPT}: judge tried to call a tool and the turn budget ended the run. "
                f"turns={payload.get('num_turns')} denials={len(payload.get('permission_denials') or [])}")
        if result:
            return E_CLI, f"{E_CLI}: rc={rc} result={result[:400]}"

    return E_CLI, f"{E_CLI}: rc={rc} stderr={(stderr or '')[:400]}"


def build_judge_prompt(rec: dict, mode: str, rubric: str, schema: str) -> str:
    ident = "BLINDED" if mode == "blinded" else "OPEN"
    if mode == "blinded":
        identity_block = (
            "This transcript is BLINDED. The speaker's name and their company have been replaced\n"
            "with the placeholders [SUBJECT] and [COMPANY]. You are not told who this is.\n"
            "Do not attempt to defeat the blinding in order to score. If you work out who it is\n"
            "anyway, record that in identity_guess and identity_basis, then set the recognition\n"
            "aside completely. Your scores must come from the words alone."
        )
        header = (
            f"Format as declared by the publisher: {rec.get('declared_kind')}\n"
            f"Approximate year: {rec.get('declared_year')}\n"
            f"Duration: {round((rec.get('duration_sec') or 0) / 60)} minutes\n"
            f"Transcript length: {rec.get('word_count')} words\n"
        )
    else:
        identity_block = (
            "This transcript is NOT blinded. You can see who is speaking.\n"
            "You must STILL score only from what is said in this transcript. Do not use anything\n"
            "you know about this person, their company, their products, their results, their\n"
            "reputation, or what happened after they spoke. A successful company must not raise\n"
            "a score and a struggling one must not lower it."
        )
        header = (
            f"Speaker: {rec.get('_speaker_name')}\n"
            f"Role at the time: {rec.get('_speaker_role')}\n"
            f"Venue: {rec.get('declared_venue')}\n"
            f"Title: {rec.get('yt_title') or rec.get('declared_title')}\n"
            f"Format: {rec.get('declared_kind')}\n"
            f"Approximate year: {rec.get('declared_year')}\n"
            f"Duration: {round((rec.get('duration_sec') or 0) / 60)} minutes\n"
            f"Transcript length: {rec.get('word_count')} words\n"
        )

    return f"""You are an expert evaluator of how technology business leaders think, judged purely from
what they say in public. Apply the rubric below to one transcript and return one JSON object.

=========================== RUBRIC ===========================
{rubric}
======================== END RUBRIC ==========================

CONDITION: {ident}

{identity_block}

TRANSCRIPT METADATA
{header}
This transcript came from automatic speech recognition. It has no speaker labels, so an
interview runs the questions and answers together. Work out from context which turns belong
to the subject and score ONLY the subject's speech. Proper nouns are frequently corrupted;
read through the corruption and do not penalise it. Timestamps appear as [hh:mm:ss] markers
roughly every minute.

=========================== TRANSCRIPT ===========================
{rec['text']}
======================== END TRANSCRIPT ==========================

Return ONE JSON object and nothing else. No preamble, no markdown fences, no commentary.
It must validate against this schema:

{schema}

Requirements that are checked automatically and will cause your output to be rejected:
- transcript_id must be exactly: {rec['leader_slug']}/{rec['source_id']}
- All 15 sub-criteria must appear, exactly once each, with codes: {' '.join(SUBCRITERIA)}
- Each sub-criterion score is an integer 1 to 5, or 0 meaning not observed.
- Each dimension score is an integer 1 to 100.
- overall must equal 0.20*d1 + 0.45*d2 + 0.35*d3, within 0.5.
- coverage must equal the share of the 15 sub-criteria you scored above 0.
- Every evidence quote must be {MAX_QUOTE_WORDS} words or fewer, and must be text the SUBJECT
  said, not the interviewer.
- Every dimension needs substantive `reasoning` and a real `counterevidence`. A human will
  read these and decide whether they agree with you, so make the argument rather than
  asserting the number.

Use the full 1 to 100 range. 50 is genuinely ordinary for a senior technology executive.
Do not compress everyone into the 70s and 80s because these are accomplished people."""


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no opening brace in response")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced braces in response")


def validate(obj: dict, expect_id: str) -> list[str]:
    errs: list[str] = []
    if obj.get("transcript_id") != expect_id:
        errs.append(f"transcript_id {obj.get('transcript_id')!r} != {expect_id!r}")

    subs = obj.get("subcriteria")
    if not isinstance(subs, list):
        errs.append("subcriteria missing or not a list")
    else:
        codes = [s.get("code") for s in subs if isinstance(s, dict)]
        missing = [c for c in SUBCRITERIA if c not in codes]
        extra = [c for c in codes if c not in SUBCRITERIA]
        dupes = [c for c in set(codes) if codes.count(c) > 1]
        if missing:
            errs.append(f"missing sub-criteria: {missing}")
        if extra:
            errs.append(f"unknown sub-criteria: {extra}")
        if dupes:
            errs.append(f"duplicated sub-criteria: {dupes}")
        for s in subs:
            sc = s.get("score")
            if not isinstance(sc, int) or not (0 <= sc <= 5):
                errs.append(f"{s.get('code')} score {sc!r} outside 0-5")

    dims = obj.get("dimensions") or {}
    for key in WEIGHTS:
        d = dims.get(key)
        if not isinstance(d, dict):
            errs.append(f"dimension {key} missing")
            continue
        sc = d.get("score")
        if not isinstance(sc, int) or not (1 <= sc <= 100):
            errs.append(f"{key} score {sc!r} outside 1-100")
        if len((d.get("reasoning") or "").split()) < 20:
            errs.append(f"{key} reasoning too short to audit")
        if not (d.get("counterevidence") or "").strip():
            errs.append(f"{key} counterevidence empty")
        for ev in d.get("evidence") or []:
            n = len((ev.get("quote") or "").split())
            if n > MAX_QUOTE_WORDS:
                errs.append(f"{key} evidence quote is {n} words, cap is {MAX_QUOTE_WORDS}")

    if all(isinstance(dims.get(k), dict) and isinstance(dims[k].get("score"), int) for k in WEIGHTS):
        want = sum(WEIGHTS[k] * dims[k]["score"] for k in WEIGHTS)
        got = obj.get("overall")
        if not isinstance(got, (int, float)) or abs(got - want) > 0.5:
            errs.append(f"overall {got!r} != weighted {round(want, 2)}")

    if isinstance(subs, list) and subs:
        scored = sum(1 for s in subs if isinstance(s.get("score"), int) and s["score"] > 0)
        want_cov = scored / len(SUBCRITERIA)
        got_cov = obj.get("coverage")
        if not isinstance(got_cov, (int, float)) or abs(got_cov - want_cov) > 0.08:
            errs.append(f"coverage {got_cov!r} != observed share {round(want_cov, 3)}")
    return errs


def fable_command(prompt: str, binary: str) -> list[str]:
    """The judge invocation, in one place so the tool-block test checks the real thing.

    Two flags here are load-bearing and were both wrong before 2026-09-06.

    `--permission-prompts none` is what actually denies tools. `--allowedTools ""`
    does NOT: with it alone the judge issued a Read against data/roster/final.json
    and `permission_denials` came back empty, which means nothing stopped it. A
    judge that can read the roster can undo the blinding.

    `--max-turns` must leave room to recover. At 1 the run died on the tool
    attempt itself, which is what produced most of the harness's failures. The
    denial only helps if the model gets a turn afterwards to answer without it.
    """
    return [
        binary, "-p", prompt,
        "--model", "claude-fable-5-1",
        "--effort", "max",
        "--output-format", "json",
        "--allowedTools", "",
        "--permission-prompts", "none",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--setting-sources", "",
        "--max-turns", "6",
    ]


def call_fable(prompt: str, config_dir: str, timeout: int, binary: str = "claude",
               workdir: str | None = None) -> tuple[str, dict]:
    """Run the Claude Fable 5.1 judge. Returns (text, telemetry).

    `binary` must be the plain `claude` CLI. The account is chosen here, per
    call, from the rotation that main() built with the llm-quota-router
    library; a wrapper that picks its own account (such as the router's `cl`
    launcher) would override that choice, and `cl` also injects
    --dangerously-skip-permissions, which hands the judge tool access to the
    repository it is being blinded against.
    """
    env = dict(os.environ)
    if config_dir == "__DEFAULT__":
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    cmd = fable_command(prompt, binary)
    # Run outside the repository. The judge should not be standing in a
    # directory that contains the roster it is being blinded against.
    jail = Path(workdir) if workdir else Path(os.environ.get("TMPDIR", "/tmp")) / "judge-jail"
    jail.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=env, cwd=str(jail), stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        _etype, detail = classify_cli_failure(proc.returncode, proc.stdout, proc.stderr)
        raise RuntimeError(detail)
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"{E_CLI}: {str(payload.get('result'))[:400]}")
    used = payload.get("modelUsage") or {}
    judge_models = [m for m in used if "fable" in m.lower()]
    if not judge_models:
        raise RuntimeError(f"{E_MODEL_MISMATCH}: telemetry names {list(used)} with no Fable model")
    telemetry = {
        "harness": f"{binary} -p",
        "requested_model": "claude-fable-5-1",
        "telemetry_models": list(used),
        "judge_model": judge_models[0],
        "canonical_model": used[judge_models[0]].get("canonicalModel"),
        "effort": "max",
        "config_dir": config_dir,
        "cost_usd": payload.get("total_cost_usd"),
        "duration_ms": payload.get("duration_ms"),
        "thinking_tokens": (payload.get("usage") or {}).get("output_tokens_details", {}).get("thinking_tokens"),
        "input_tokens": used[judge_models[0]].get("inputTokens"),
        "output_tokens": used[judge_models[0]].get("outputTokens"),
    }
    return payload.get("result") or "", telemetry


def call_astra(prompt: str, timeout: int, workdir: Path,
               model: str = "gpt-6-astra") -> tuple[str, dict]:
    """Run the Astra judge via codex exec. Returns (text, telemetry).

    `model` is a parameter because this arm falls back to another model when
    it refuses repeatedly. The served model is recorded in the telemetry, so
    aggregate.py can calibrate each model on its own distribution."""
    out_file = workdir / "astra_last_message.txt"
    cmd = [
        "codex", "exec",
        "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
        "-c", "model_provider=openai",
        "-c", "preferred_auth_method=chatgpt",
        "-m", model,
        "-c", "model_reasoning_effort=max",
        "-s", "read-only",
        "--json",
        "-o", str(out_file),
        prompt,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, cwd=str(workdir))
    events = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    errors = [e for e in events if e.get("type") == "error"
              or (e.get("item") or {}).get("type") == "error"]
    fatal = [e for e in events if e.get("type") in ("turn.failed", "error")]
    if fatal:
        msg = json.dumps(fatal[0])[:600]
        kind = E_AUTH if ("401" in msg or "quota" in msg.lower() or "rate" in msg.lower()) else E_CLI
        raise RuntimeError(f"{kind}: {msg}")
    if proc.returncode != 0:
        raise RuntimeError(f"{E_CLI}: rc={proc.returncode} stderr={(proc.stderr or '')[:600]}")

    text = out_file.read_text() if out_file.exists() else ""
    if not text:
        msgs = [i["item"]["text"] for i in events
                if (i.get("item") or {}).get("type") == "agent_message"]
        text = msgs[-1] if msgs else ""

    usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), {}) or {}
    # codex does not echo the served model in its event stream, so assert on the
    # absence of a model-rejection error plus the presence of reasoning tokens,
    # and record the request exactly as made.
    telemetry = {
        "harness": "codex exec",
        "requested_model": model,
        # What answered. NOT independently verified: the codex --json stream
        # carries thread.started, turn.started, item.completed and
        # turn.completed only, and stderr names no model either, so there is
        # nothing in the response to assert against. This records what was
        # asked for. The reasoning-token check below is the one identity
        # assertion the harness can actually make.
        "served_model": model,
        "effort": "max",
        "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "nonfatal_events": [json.dumps(e)[:200] for e in errors][:5],
        # What the judge actually reached for. This arm has live web search and
        # keeps it deliberately; recording the count is what makes the exposure
        # measurable instead of merely accepted.
        "tool_use_counts": count_tool_events(events),
        "web_search_queries": [
            (e.get("item") or {}).get("query") for e in events
            if e.get("type") == "item.completed"
            and (e.get("item") or {}).get("type") == "web_search"
        ][:10],
    }
    if telemetry["reasoning_output_tokens"] in (None, 0):
        raise RuntimeError(f"{E_MODEL_MISMATCH}: no reasoning tokens reported; "
                           f"max reasoning effort did not take effect. usage={usage}")
    return text, telemetry


# ----------------------------------------------------------------------------
# Judge C: Gemini 3.8 Flash (High), driven by the Antigravity CLI (`agy`).
# ----------------------------------------------------------------------------

GEMINI_MODEL = "gemini-3.8-flash-high"

#: Where the non-default Antigravity profiles live. See agy_profiles().
AGY_HOME_ROOT = Path.home() / ".agy-homes"

#: Quota and auth wordings seen from `agy`. The router's failure_text module
#: parses the deadline out of "Individual quota reached. ... Resets in 25m54s",
#: so the same family of phrases has to be recognised here or a quota stop is
#: filed as a crash. Matched as whole phrases, like classify_cli_failure does.
AGY_QUOTA_PHRASES = (
    "quota reached", "quota exceeded", "resource_exhausted", "rate limit",
    "resets in", "no credit information", "out of credit", "429",
)
AGY_AUTH_PHRASES = ("not signed in", "unauthenticated", "please log in", "login required")


def agy_profiles(root: Path | None = None, default_home: str | None = None) -> list[str]:
    """Every Antigravity profile on this machine, DERIVED rather than listed.

    A profile is a HOME: `agy` reads $HOME/.gemini/antigravity-cli/ and there is
    no AGY_CONFIG_DIR. Verified 2026-09-07 by grepping the binary for every env
    var naming a config, dir, profile or account; the only path resolution is
    os.UserHomeDir. So a second account is a second HOME.

    The list is a glob, never hardcoded letters. This repo's operator has been
    bitten twice by hardcoded account letters, once when Claude account D
    arrived and once when E did, so assume a third Antigravity account will
    appear and that nothing here may need editing when it does.

    Membership is NOT gated on a token file being present. Identity for the
    default profile comes from the macOS Keychain, and `agy` answers normally
    with its token file deleted outright, so a token check would wrongly drop
    the main account. An unauthenticated profile therefore reaches the harness
    and fails loudly with E_AUTH, which is the right outcome: it is reported,
    not silently skipped.
    """
    root = AGY_HOME_ROOT if root is None else root
    homes = [default_home or str(Path.home())]
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if (d / ".gemini" / "antigravity-cli").is_dir():
                homes.append(str(d))
    return homes


def agy_identity_from_log(log_path: Path) -> str | None:
    """Which account served ONE call, read from the log that call wrote.

    Takes an explicit path rather than searching a directory. The first version
    of this picked the newest log by st_mtime and got the wrong account: a
    profile directory carries its old logs when it is renamed or reused, and
    mtime records when a file was TOUCHED, not what is in it. That is the
    repo's standing rule about never deriving logical time from the filesystem,
    arriving in a new place. `agy --log-file` removes the guesswork entirely by
    naming the file up front, so there is nothing to sort and nothing to infer.

    Best-effort. A run that logs no address returns None and the grade is still
    written, because discarding a real answer over a missing log line would be
    the worse failure.
    """
    try:
        hits = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                          log_path.read_text(errors="ignore"))
    except OSError:
        return None
    return hits[-1] if hits else None


def classify_agy_failure(rc: int, blob: str) -> tuple[str, str]:
    """Work out why `agy` failed, from stdout, stderr and the result event together.

    Same shape as classify_cli_failure for the Claude CLI, and for the same
    reason: a quota stop and a crash both exit non-zero, and a bare
    cli_nonzero_exit count cannot tell them apart afterwards.
    """
    low = (blob or "").lower()
    if any(s in low for s in AGY_QUOTA_PHRASES):
        return E_AUTH, f"{E_AUTH}: {blob[:400]}"
    if any(s in low for s in AGY_AUTH_PHRASES):
        return E_AUTH, f"{E_AUTH}: {blob[:400]}"
    # A model name agy does not know is rejected before any inference happens.
    # That is an identity failure, not a crash: it means this harness asked for
    # a model this CLI cannot serve.
    if "invalid model selection" in low or "not recognized as a known model" in low:
        return E_MODEL_MISMATCH, f"{E_MODEL_MISMATCH}: {blob[:400]}"
    return E_CLI, f"{E_CLI}: rc={rc} {blob[:400]}"


def gemini_command(prompt: str, model: str, binary: str, print_timeout_s: int,
                   log_path: Path) -> list[str]:
    """The Gemini judge invocation, in one place so the tool test checks the real thing.

    `--output-format stream-json` is load-bearing and is NOT a formatting
    preference. It is the only output mode that names the model that answered:
    the `init` event carries {"model": "..."}, and the plain `json` mode carries
    no model field anywhere. Without it this arm could assert nothing about
    model identity, which is exactly the position the Astra arm is stuck in.

    `--disable-slash-commands` stops a transcript line beginning with "/" from
    being expanded as a slash command or skill before the judge reads it.

    There is deliberately NO --dangerously-skip-permissions, for the same reason
    fable_command() runs the plain `claude` binary: it auto-approves every tool,
    and a judge that can read this repository can read the roster it is blinded
    against. Reads outside the working directory are denied by default, verified
    2026-09-07, and the judge is run in a jail dir away from the corpus.

    --print-timeout sits below the subprocess timeout so `agy` exits on its own
    and prints a parseable result event, rather than being killed mid-write.

    `--log-file` pins this call's log to a known path. Without it the account
    that served a call could only be guessed at by sorting a shared directory
    by mtime, which returned the wrong account on 2026-09-07 because a renamed
    profile keeps its old logs.
    """
    return [
        binary, "-p", prompt,
        "--model", model,
        "--output-format", "stream-json",
        "--disable-slash-commands",
        "--print-timeout", f"{print_timeout_s}s",
        "--log-file", str(log_path),
    ]


def count_gemini_tool_events(events: list[dict]) -> tuple[dict[str, int], list[str]]:
    """Count the tools the Gemini judge used, and capture what it looked up.

    MEASURED 2026-09-07: this judge has live web search and it CANNOT be turned
    off. Asked directly, it ran search_web and reported the tool succeeded. The
    permission system recognises exactly three grant actions plus mcp, and the
    CLI rejects any rule naming a builtin tool, logging
    `ignoring invalid deny entry "search_web": invalid grant string` and
    `unknown action "search_web"` for the search_web(*) form. Network-level
    blocking does not help either, because the search runs behind the model
    rather than from this client.

    So this arm carries the same exposure the Astra arm does, and it is recorded
    for the same reason: it was accepted deliberately, so it must be visible.
    Only DONE steps count. A tool step that ended in ERROR returned nothing to
    the judge, and counting it would overstate what the judge actually saw.
    """
    counts: dict[str, int] = {}
    queries: list[str] = []
    for e in events:
        if e.get("event") != "step_update":
            continue
        su = e.get("step_update") or {}
        if su.get("step_type") != "tool" or su.get("state") != "DONE":
            continue
        name = su.get("tool_name") or "unknown"
        counts[name] = counts.get(name, 0) + 1
        params = (su.get("tool_info") or {}).get("parameters") or {}
        for key in ("query", "Query", "url", "Url", "AbsolutePath"):
            if params.get(key):
                queries.append(f"{name}: {str(params[key])[:160]}")
                break
    return counts, queries[:10]


def call_gemini(prompt: str, profile_home: str, timeout: int,
                workdir: str | None = None, model: str = GEMINI_MODEL,
                binary: str = "agy") -> tuple[str, dict]:
    """Run the Gemini 3.8 Flash judge via the Antigravity CLI. Returns (text, telemetry).

    The account is chosen here, per call, by setting HOME, because that is the
    only thing that selects an Antigravity profile. Note that the DEFAULT
    profile takes its identity from the macOS Keychain rather than from the
    token file in that directory, so the account this reaches is whatever the
    Keychain currently holds. agy_identity_from_log() reads it back out of
    this call's own log and the answer is recorded on the grade, not assumed.
    """
    env = dict(os.environ)
    env["HOME"] = profile_home
    # A stale value for either of these in the inherited shell would silently
    # change which account or which backend answers. GEMINI_API_KEY switches agy
    # to the raw Gemini API when settings.json names that provider, which would
    # serve a different model with no subscription quota behind it.
    env.pop("GEMINI_API_KEY", None)
    env.pop("CLAUDE_CONFIG_DIR", None)

    # Run outside the repository, like the Fable arm: the judge should not stand
    # in a directory holding the roster it is blinded against. Reads outside the
    # working directory are refused by agy, so the jail is what makes that bite.
    jail = Path(workdir) if workdir else Path(os.environ.get("TMPDIR", "/tmp")) / "judge-jail"
    jail.mkdir(parents=True, exist_ok=True)

    print_timeout = max(60, timeout - 60)
    log_path = jail / "agy-cli.log"
    cmd = gemini_command(prompt, model, binary, print_timeout, log_path)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=env, cwd=str(jail), stdin=subprocess.DEVNULL)

    events = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    init = next((e.get("init") for e in events if e.get("event") == "init"), None)
    result = next((e.get("result") for e in reversed(events) if e.get("event") == "result"), None)

    if result is None:
        blob = f"{proc.stdout or ''} {proc.stderr or ''}"
        raise RuntimeError(classify_agy_failure(proc.returncode, blob)[1])
    if result.get("status") != "SUCCESS":
        raise RuntimeError(classify_agy_failure(proc.returncode, json.dumps(result))[1])

    # Model identity, asserted rather than assumed. A model name agy does not
    # know is rejected up front with a non-zero exit, so this catches the other
    # case: a request that was accepted and served by something else.
    served = (init or {}).get("model")
    if not served:
        raise RuntimeError(f"{E_MODEL_MISMATCH}: no init event named a model, so nothing "
                           f"verifies that {model} answered")
    if served != model:
        raise RuntimeError(f"{E_MODEL_MISMATCH}: requested {model}, telemetry names {served}")

    text = result.get("response") or ""
    denied = result.get("denied_actions") or []
    if not text.strip():
        # FOUND 2026-09-07: a denied tool can end the turn with status SUCCESS
        # and an EMPTY response. Observed when a read outside the working
        # directory was refused: the judge gave up and returned "". Writing that
        # as a grade would file a silent non-answer as a result, so it fails
        # here instead, carrying what was denied so the cause is legible.
        raise RuntimeError(f"{E_EMPTY}: status SUCCESS with an empty response. "
                           f"denied_actions={json.dumps(denied)[:300]}")

    usage = result.get("usage") or {}
    counts, queries = count_gemini_tool_events(events)
    telemetry = {
        "harness": f"{binary} -p",
        "requested_model": model,
        # Independently verified, unlike the Astra arm: the init event names the
        # model that answered, so this is a reading rather than an echo.
        "served_model": served,
        "served_model_verified": True,
        "profile_home": profile_home,
        # Which account actually served this call, read from THIS call's log.
        "profile_identity": agy_identity_from_log(log_path),
        "duration_seconds": result.get("duration_seconds"),
        "num_turns": result.get("num_turns"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "thinking_tokens": usage.get("thinking_tokens"),
        "cache_read_tokens": usage.get("cache_read_tokens"),
        "denied_actions": [d.get("action") for d in denied if isinstance(d, dict)],
        "tool_use_counts": counts,
        "web_search_queries": queries,
    }
    if telemetry["thinking_tokens"] in (None, 0):
        # The "-high" suffix IS the reasoning setting for this model family, so
        # zero thinking tokens means the high-effort variant did not take effect.
        # Same assertion the Astra arm makes with reasoning_output_tokens.
        raise RuntimeError(f"{E_MODEL_MISMATCH}: no thinking tokens reported, so the "
                           f"high-effort variant did not take effect. usage={usage}")
    return text, telemetry


def grade_one(job: dict) -> dict:
    rec = job["rec"]
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    dest = Path(job["dest"])
    raw_dest = Path(job["raw_dest"])
    if dest.exists() and not job["force"]:
        return {"status": "cached", "id": tid, "judge": job["judge"], "mode": job["mode"], "run": job["run"]}

    prompt = build_judge_prompt(rec, job["mode"], job["rubric"], job["schema"])
    t0 = time.time()
    try:
        if job["judge"] == "fable":
            text, telemetry = call_fable(prompt, job["config_dir"], job["timeout"],
                                         job["fable_bin"], job["workdir"])
        elif job["judge"] == "gemini":
            # No refusal-retry wrapper here, deliberately. The retry exists
            # because Astra refuses some politically-charged transcripts
            # non-deterministically. Whether this judge does the same has not
            # been measured, and adding a retry now would hide the evidence
            # needed to answer that. If refusals show up in the taxonomy, the
            # measurement comes first and the retry second.
            text, telemetry = call_gemini(prompt, job["gemini_profile"], job["timeout"],
                                          job["workdir"], job["gemini_model"],
                                          job["agy_bin"])
        else:
            # Astra refuses some politically-charged transcripts, and the refusal
            # is not deterministic: two of three re-run transcripts graded fine
            # the second time. So retry the same model, and only fall back to
            # another model when it keeps refusing.
            attempts_log: list[dict] = []

            def _one(model: str, _p=prompt, _j=job, _log=attempts_log):
                txt, tel = call_astra(_p, _j["timeout"], Path(_j["workdir"]), model)
                _log.append(tel)
                try:
                    return extract_json(txt), tel
                except Exception:
                    # Unparseable is not a refusal. Hand it back so the normal
                    # JSON error path classifies it instead of burning retries.
                    return {"__unparseable__": txt}, tel

            obj_or_raw, telemetry, policy = grade_with_refusal_policy(
                _one, primary=job["astra_model"])
            if "__unparseable__" in obj_or_raw:
                text = obj_or_raw["__unparseable__"]
            else:
                text = json.dumps(obj_or_raw)
            job["_policy"] = policy
    except subprocess.TimeoutExpired:
        return {"status": "failed", "id": tid, "judge": job["judge"], "mode": job["mode"],
                "run": job["run"], "error_type": E_TIMEOUT, "detail": f"exceeded {job['timeout']}s"}
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        etype = next((e for e in (E_CLI, E_TIMEOUT, E_AUTH, E_MODEL_MISMATCH, E_TOOL_ATTEMPT)
                      if detail.startswith(e)), E_CLI)
        return {"status": "failed", "id": tid, "judge": job["judge"], "mode": job["mode"],
                "run": job["run"], "error_type": etype, "detail": detail[:800]}

    elapsed = round(time.time() - t0, 1)
    raw_dest.parent.mkdir(parents=True, exist_ok=True)
    raw_dest.write_text(text)

    if not text.strip():
        return {"status": "failed", "id": tid, "judge": job["judge"], "mode": job["mode"],
                "run": job["run"], "error_type": E_EMPTY, "detail": "harness returned no text"}
    try:
        obj = extract_json(text)
    except Exception as exc:  # noqa: BLE001
        etype = E_NOJSON if "no opening brace" in str(exc) else E_BADJSON
        return {"status": "failed", "id": tid, "judge": job["judge"], "mode": job["mode"],
                "run": job["run"], "error_type": etype, "detail": str(exc)[:400],
                "raw_path": str(raw_dest)}

    refusal = looks_like_refusal(obj)
    if refusal:
        record = {
            "transcript_id": tid, "leader_slug": rec["leader_slug"],
            "source_id": rec["source_id"], "judge": job["judge"], "mode": job["mode"],
            "run": job["run"], "graded_at_utc": utcnow(), "elapsed_sec": elapsed,
            "telemetry": telemetry, "grading_contract": job["contract"],
            "refused": True, "refusal_reason": refusal, "grade": obj,
            "validation_errors": [],
            **_policy_fields(job),
        }
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
        os.replace(tmp, dest)
        return {"status": "refused", "id": tid, "judge": job["judge"], "mode": job["mode"],
                "run": job["run"], "error_type": E_REFUSED, "detail": refusal[:300],
                "path": str(dest), "elapsed": elapsed}

    errs = validate(obj, tid)
    record = {
        "transcript_id": tid,
        "leader_slug": rec["leader_slug"],
        "source_id": rec["source_id"],
        "judge": job["judge"],
        "mode": job["mode"],
        "run": job["run"],
        "graded_at_utc": utcnow(),
        "grading_contract": job["contract"],
        "elapsed_sec": elapsed,
        "telemetry": telemetry,
        "validation_errors": errs,
        "grade": obj,
        **_policy_fields(job),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    os.replace(tmp, dest)

    if errs:
        return {"status": "invalid", "id": tid, "judge": job["judge"], "mode": job["mode"],
                "run": job["run"], "error_type": E_SCHEMA, "detail": "; ".join(errs)[:600],
                "path": str(dest), "elapsed": elapsed}
    return {"status": "ok", "id": tid, "judge": job["judge"], "mode": job["mode"], "run": job["run"],
            "overall": obj.get("overall"), "d1": obj["dimensions"]["d1_clarity"]["score"],
            "d2": obj["dimensions"]["d2_insight"]["score"], "d3": obj["dimensions"]["d3_technical_depth"]["score"],
            "coverage": obj.get("coverage"), "elapsed": elapsed, "path": str(dest)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts", help="Directory of normalized transcript JSON files.")
    ap.add_argument("--single", help="Grade one transcript file (used for calibration).")
    ap.add_argument("--roster", help="Roster JSON, needed to fill speaker name/role in open mode.")
    ap.add_argument("--out", default="data/grades")
    ap.add_argument("--judges", default="fable,astra")
    ap.add_argument("--modes", default="blinded,open")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--run-offset", type=int, default=0, help="Start run numbering here, to add repeats later.")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--limit-per-leader", type=int, default=None,
                    help="Grade at most N transcripts per leader, chosen by sorted source_id so the "
                         "choice is deterministic and repeatable. Used for the unblinded arm, which "
                         "only needs enough transcripts per leader to estimate the reputation halo. "
                         "What it drops is logged, never silent.")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--errors", default="data/logs/grade_errors.jsonl")
    ap.add_argument("--astra-model", default="gpt-6-astra",
                    help="Primary model for the Astra arm.")
    ap.add_argument("--fable-bin", default="claude",
                    help="Binary that runs the Fable judge. Must be the plain claude CLI: "
                         "account rotation happens in this script, via the llm-quota-router "
                         "library, and the cl launcher is refused because it picks its own "
                         "account and forces bypass-permissions mode.")
    ap.add_argument("--fable-accounts", default=os.environ.get("FABLE_ACCOUNTS", ""),
                    help="Comma-separated account names to pin the Fable rotation to, "
                         "e.g. 'default' or 'default,.claude-b'. Use it when only some "
                         "accounts can serve Fable, such as when only one has paid usage "
                         "credits enabled. Overrides the measured-headroom ordering.")
    ap.add_argument("--gemini-model", default=GEMINI_MODEL,
                    help="Model for the Gemini arm, as the Antigravity CLI names it. "
                         "The effort level is part of the name (-high/-medium/-low); "
                         "there is no separate effort flag for this family.")
    ap.add_argument("--agy-bin", default="agy",
                    help="Binary that runs the Gemini judge. Must be the plain agy CLI.")
    ap.add_argument("--gemini-profiles", default=os.environ.get("GEMINI_PROFILES", ""),
                    help="Comma-separated Antigravity profile HOMEs to pin the Gemini "
                         "rotation to, or their basenames under ~/.agy-homes. Default is "
                         "every profile found. Unlike the Fable rotation this cannot be "
                         "ordered by headroom: Antigravity exposes no usage endpoint at "
                         "all, so the rotation is plain round-robin.")
    args = ap.parse_args()

    rubric = RUBRIC_PATH.read_text()
    schema = SCHEMA_PATH.read_text()
    contract = grading_contract()
    log(f"grading contract {contract['contract_id']} "
        f"(rubric {contract['rubric_sha256'][:8]}, schema {contract['schema_sha256'][:8]})")

    roster_by_slug: dict[str, dict] = {}
    if args.roster and Path(args.roster).exists():
        roster_by_slug = {r["slug"]: r for r in json.loads(Path(args.roster).read_text())["roster"]}

    if args.single:
        paths = [Path(args.single)]
    else:
        paths = sorted(Path(args.transcripts).rglob("*.json"))
    if not paths:
        raise SystemExit("no transcripts found")

    if args.limit_per_leader is not None:
        slug_of = {p: json.loads(p.read_text())["leader_slug"] for p in paths}
        kept = apply_per_leader_limit(paths, args.limit_per_leader, slug_of.get)
        dropped = [p for p in paths if p not in set(kept)]
        log(f"--limit-per-leader {args.limit_per_leader}: keeping {len(kept)} transcripts, "
            f"dropping {len(dropped)} across {len(set(slug_of.values()))} leaders")
        if args.limit_per_leader == 0:
            log("  limit is 0, so this pass grades nothing and exits")
            return 0
        if dropped:
            log("  dropped: " + ", ".join(sorted(p.parent.name + "/" + p.stem for p in dropped)[:12])
                + (" ..." if len(dropped) > 12 else ""))
        paths = kept

    judges = [j.strip() for j in args.judges.split(",") if j.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("--fable-bin cl is refused: cl picks its own account, so the "
                         "Fable rotation cannot take effect, and it injects "
                         "--dangerously-skip-permissions, which lets the judge read the "
                         "roster it is blinded against. Use the plain claude CLI.")
    # Route Fable by measured FABLE headroom. The general-pool number misleads:
    # an account can have plenty of general quota and no Fable weekly left, and
    # every Fable call there fails while Astra succeeds. Falling back to the
    # plain account list is safe: it is only worse, never wrong.
    all_dirs, headroom, routing_note = fable_accounts()
    log(routing_note)
    if headroom:
        shown = ", ".join(f"{account_label(a)}={headroom.get(a, float('nan')):.2f}"
                          for a in all_dirs)
        log(f"fable headroom measured: {shown}")
    else:
        log("no fable headroom measured")
    if args.fable_accounts:
        cfg_dirs = select_named_accounts(all_dirs, args.fable_accounts)
        log(f"--fable-accounts pinned the Fable rotation to "
            f"{[account_label(a) for a in cfg_dirs]}. Measured headroom is ignored: "
            f"an account out of subscription quota still serves Fable from paid "
            f"usage credits, and the usage API reports 0.00 remaining either way.")
    else:
        cfg_dirs = order_accounts_by_fable(all_dirs, headroom)
        skipped = [a for a in all_dirs if a not in cfg_dirs]
        if skipped:
            log(f"  excluded as exhausted: {[account_label(a) for a in skipped]}")
    log(f"fable accounts in rotation: {[account_label(a) for a in cfg_dirs]}")

    # The Gemini rotation is round-robin and nothing more. There is no headroom
    # ordering because there is no headroom to read: `agy` exposes no usage or
    # quota subcommand and writes no quota field anywhere on disk, so the
    # llm-quota-router adapter reports these pools as unobservable with
    # confidence 0.0. Ranking them would mean inventing the numbers, and a
    # router that invents numbers sends every call to an exhausted pool.
    # What IS available is failure-learned: a quota stop names its own reset
    # time, and classify_agy_failure files it as E_AUTH so the taxonomy shows it.
    gem_profiles = agy_profiles()
    if args.gemini_profiles:
        wanted = [w.strip() for w in args.gemini_profiles.split(",") if w.strip()]
        resolved = []
        for w in wanted:
            hits = [h for h in gem_profiles if h == w or Path(h).name == w]
            if not hits:
                raise SystemExit(f"--gemini-profiles: no Antigravity profile matches {w!r}. "
                                 f"Known: {[Path(h).name or h for h in gem_profiles]}")
            resolved.append(hits[0])
        gem_profiles = resolved
    if "gemini" in judges:
        if not gem_profiles:
            raise SystemExit("no Antigravity profiles found: the Gemini arm needs at least "
                             "the default HOME with ~/.gemini/antigravity-cli present")
        # Paths only. The account each profile serves is recorded per grade
        # from that call's own log; asserting it here, before any call has been
        # made, would mean guessing from stale files.
        log(f"gemini profiles in rotation (round-robin, no headroom is measurable): "
            f"{gem_profiles}")

    workroot = Path(os.environ.get("TMPDIR", "/tmp")) / "grade-work"
    workroot.mkdir(parents=True, exist_ok=True)

    jobs = []
    for i, (path, judge, mode, run) in enumerate(
            itertools.product(paths, judges, modes, range(args.run_offset, args.run_offset + args.repeats))):
        rec = json.loads(path.read_text())
        person = roster_by_slug.get(rec["leader_slug"], {})
        rec["_speaker_name"] = person.get("name", rec["leader_slug"].replace("-", " ").title())
        rec["_speaker_role"] = person.get("role", "technology executive")
        stem = f"{rec['source_id']}__{judge}__{mode}__r{run}"
        wd = workroot / f"{rec['leader_slug']}-{stem}"
        wd.mkdir(parents=True, exist_ok=True)
        jobs.append({
            "rec": rec, "judge": judge, "mode": mode, "run": run,
            "rubric": rubric, "schema": schema, "timeout": args.timeout, "force": args.force,
            "contract": contract,
            "config_dir": assign_accounts(judge, i, cfg_dirs, judges),
            "fable_bin": args.fable_bin,
            "astra_model": args.astra_model,
            "gemini_model": args.gemini_model,
            "agy_bin": args.agy_bin,
            # Same per-judge index arithmetic as the Fable rotation: jobs are
            # enumerated over product(paths, judges, ...), so dividing by the
            # judge count is what stops this arm from reaching only every Nth
            # profile. See assign_accounts() for the bug that motivated it.
            "gemini_profile": assign_accounts("gemini", i, gem_profiles, judges)
                              if gem_profiles else None,
            "workdir": str(wd),
            "dest": str(Path(args.out) / judge / rec["leader_slug"] / f"{stem}.json"),
            "raw_dest": str(Path(args.out) / "_raw" / judge / rec["leader_slug"] / f"{stem}.txt"),
        })

    # Order the queue breadth-first across leaders. A judge that runs out of
    # quota mid-pass must leave every leader equally shallow, not leave the
    # tail of the alphabet with no grades at all. See order_breadth_first().
    jobs = order_breadth_first(jobs)

    log(f"{len(jobs)} grading calls queued "
        f"({len(paths)} transcripts x {len(judges)} judges x {len(modes)} modes x {args.repeats} repeats)")
    pending_jobs = [j for j in jobs if not Path(j["dest"]).exists()]
    if pending_jobs:
        lead = []
        for j in pending_jobs[:len(set(x["rec"]["leader_slug"] for x in pending_jobs))]:
            if j["rec"]["leader_slug"] not in lead:
                lead.append(j["rec"]["leader_slug"])
        log(f"  {len(pending_jobs)} of them are not yet on disk, "
            f"spanning {len(set(j['rec']['leader_slug'] for j in pending_jobs))} leaders; "
            f"first to run: {', '.join(lead[:5])}"
            + (" ..." if len(lead) > 5 else ""))

    results = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(grade_one, j) for j in jobs]
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            tag = r["status"].upper()
            extra = f" overall={r['overall']}" if r["status"] == "ok" else f" {r.get('error_type','')}"
            log(f"[{done}/{len(jobs)}] {tag} {r['judge']}/{r['mode']}/r{r['run']} {r['id']}{extra}")

    ok = [r for r in results if r["status"] == "ok"]
    cached = [r for r in results if r["status"] == "cached"]
    invalid = [r for r in results if r["status"] == "invalid"]
    refused = [r for r in results if r["status"] == "refused"]
    failed = [r for r in results if r["status"] == "failed"]

    Path(args.errors).parent.mkdir(parents=True, exist_ok=True)
    with open(args.errors, "w") as fh:
        for r in failed + invalid + refused:
            fh.write(json.dumps(stamp_failure(r)) + "\n")

    tax: dict[str, int] = {}
    for r in failed + invalid + refused:
        tax[r.get("error_type", "unknown")] = tax.get(r.get("error_type", "unknown"), 0) + 1

    print(json.dumps({
        "attempted": len(jobs),
        "succeeded": len(ok) + len(cached),
        "newly_graded": len(ok),
        "cached": len(cached),
        "invalid_schema": len(invalid),
        "judge_refusals": len(refused),
        "failed": len(failed),
        "error_taxonomy": tax,
        "median_elapsed_sec": sorted(r["elapsed"] for r in ok)[len(ok) // 2] if ok else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
