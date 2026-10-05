#!/usr/bin/env python3
"""Tier R: the operator's audited prediction cases, stage by stage, replayed offline or run live.

Rescue round 4, design section 5 with critique 3 E5 and F1. Real transcripts,
records and quotes are private, so the gold cases live in the private data
repository (predictions/_eval/cases-20260929/cases.json) and this public harness
reads them through the data link. It refuses to run without that link.

WHY A SEPARATE FILE FROM eval_predictions.py. That harness scores one extraction
TREE against span labels on synthetic transcripts (precision and recall). These
cases are single assertions at five different stages (the prompt header, the
funnel, extraction, dating and the resolver), each on one real record, and a
model stage replays a recorded answer under a prompt-hash check. The two share
only the PREDICT_LIVE gate, which this file applies the same way.

STAGES
  header   deterministic: the TRANSCRIPT METADATA block under an optional override
  funnel   deterministic: phase2_resolvability's deadline, lead, eligibility and
           failing clauses under the gold statement date, with the implied-window
           configuration the case states (input.implied: 1.0 for the board's table,
           null for off; required)
  extract  one extraction call (release 2.3), then the real parser and grounding;
           the operator's quote must still be extracted (critique 2 point 5)
  dating   one call per dater per repeat (dating_lib.DATERS, Astra then Fable with web tools since
           2026-10-05; a case whose legacy input.harness names one dater runs the daters of
           its era, DATERS_BEFORE_20261005, Gemini then Fable),
           the real page and description checks, the real two-proposal merge; a
           confirmed date outside the gold band is a WRONG AUTO-CONFIRMATION. A
           repeat is recorded as r<n>.<dater>.json and replays only with every
           dater's answer; an infrastructure failure of either excludes the repeat.
           With input.pairs (2026-10-04) each repeat calls every dater in the union
           of the pairs once and judges each pair through its own merge; a failed
           call is kept as failed/r<n>.<dater>.json and excludes the repeat only for
           the pairs holding that dater (run_live_dating_pairs)
  dating_stored
           deterministic: proposals and page checks already on disk (pinned by
           sha256) or written inline, through the real merge under input.merge_version;
           the operator's audited recordings and the negative controls
  resolve  one resolver call, validated by resolution_lib; a case needing a field
           the resolver contract lacks (already_public) is BLOCKED before any call
  early    one early-call check (VD-5 c) before the deadline, validated as
           resolve_predictions --stage early validates it
  Resolve and early cases are judged over the deadline production derives with
  implied windows on; the gold names it, and every case's gold is checked against
  production BEFORE the first call (and by --estimate), so a live run never spends
  calls and then refuses.

MODES
  --offline (default)  deterministic stages run; a model stage replays each
                       recording whose prompt sha256 still matches and refuses
                       with "prompt changed; re-record live" when one does not.
                       A model case with no recording is UNRECORDED.
  --live               needs PREDICT_LIVE=1; --repeats (default 3) calls per model
                       case, each answer recorded for later replay.
  --smoke              only the gold file's "smoke" list, in its order.
  --estimate           print what --live would spend, then stop.

THE PASS RULE (k of n, critique 3 F1). Infrastructure failures (timeout, quota,
Gemini's empty answer, a CLI error) are excluded from n and counted. A case
PASSES when a majority of its valid repeats meet its assertion (2 of 3) and none
is a hard failure; any hard failure makes it HARD_FAIL; fewer than 2 valid repeats
is INCONCLUSIVE. No base rate is measured yet, so a majority is the rule until one is.

EXIT: 0 every case passed; 1 any FAIL, HARD_FAIL or changed prompt; 3 otherwise
incomplete (UNRECORDED, BLOCKED, PENDING or INCONCLUSIVE).

  .venv/bin/python scripts/eval_prediction_cases.py --gold data/predictions/_eval/cases-20260929
  .venv/bin/python scripts/eval_prediction_cases.py --gold <dir> --smoke --estimate
  PREDICT_LIVE=1 .venv/bin/python scripts/eval_prediction_cases.py --gold <dir> --smoke --live
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402

MODEL_STAGES = ("extract", "dating", "resolve", "early")
STAGES = ("header", "funnel", "dating_stored") + MODEL_STAGES
DEFAULT_HARNESS = {"extract": "astra", "dating": "gemini", "resolve": "astra", "early": "astra"}
# The only statuses that mean a dating case's answers were judged: the denominator of
# "wrong auto-confirmations: k of n". A refused recording, too few valid repeats, or no
# answer at all is not a trial (final review item 7).
JUDGED_STATUSES = ("PASS", "FAIL", "HARD_FAIL", "QUEUED")
INFRA = ("cli_timeout", "auth_or_quota", "empty_response", "cli_nonzero_exit", "transient_retryable",
         "router_no_account", "model_identity_mismatch")
REPORT_DEADLINE_RE = re.compile(r"^By [^,]{0,60},\s+[^.]{0,80}\b(will report|reports?|will confirm|reporting will confirm)\b",
                                re.I)


class Context:
    def __init__(self, data: Path, gold: Path):
        self.data, self.gold = Path(data), Path(gold)

    def path(self, rel: str) -> Path:
        p = self.data / rel
        if not p.is_file():
            raise FileNotFoundError(f"gold names {rel}, which is not under {self.data}")
        return p

    def record(self, spec: dict) -> dict:
        f = self.path(spec["file"])
        hits = [r for r in L.parse_lines(f.read_text(), str(f)) if r.get("prediction_id") == spec["prediction_id"]]
        if len(hits) != 1:
            raise FileNotFoundError(f"{spec['file']} holds {len(hits)} records with id {spec['prediction_id']}")
        return hits[0]


def _set(rec: dict, changes: dict) -> dict:
    r = copy.deepcopy(rec)
    for dotted, v in (changes or {}).items():
        node = r
        *parts, last = dotted.split(".")
        for p in parts:
            node = node.setdefault(p, {})
        node[last] = v
    if "source.statement_date" in (changes or {}) and "source.statement_date_basis" not in (changes or {}):
        r["source"]["statement_date_basis"] = L.OVERRIDE_DATE_BASIS
    if "source.statement_date" in (changes or {}):
        # The case's date is the gold day of speech. A range block stored on the record
        # describes the date it replaced, and predictions_lib.statement_date_earliest
        # would read it as this date's range (final review item 1).
        for block in ("statement_date_override", "statement_date_check"):
            if f"source.{block}" not in changes:
                r["source"].pop(block, None)
    return r


def _override(entry: dict | None) -> dict | None:
    if entry is None:
        return None
    return {"confirmed_by": "eval gold", "confirmed_at_utc": "2026-09-29T00:00:00Z", **entry}


def _transcript(case: dict, ctx: Context) -> dict:
    rec = json.loads(ctx.path(case["input"]["transcript"]).read_text())
    ov = _override(case["input"].get("override"))
    if ov:
        rec = L.apply_statement_date_override(rec, {f"{rec['leader_slug']}/{rec['source_id']}": L.check_override_entry(
            f"{rec['leader_slug']}/{rec['source_id']}", ov)})
    return rec


# ---------------------------------------------------------------------------
# Prompts (model stages)
# ---------------------------------------------------------------------------

# A resolve or early case is judged over the deadline the BOARD would use: implied
# windows on, at the operator's table (VD-6 a), scale 1.
RESOLVE_IMPLIED = 1.0


def resolve_record(case: dict, ctx: Context) -> tuple[dict, dt.date]:
    """The record a resolve or early case judges, and its deadline, exactly as production builds them.

    Production runs every record through phase2_resolvability.attach_deadlines before
    the resolver sees it, which sets the deadline and, for a claim with no date, the
    implied window and the judged block. A case that skipped this would record answers
    to a prompt production never sends (review of the combined branch, 2026-09-30).
    The gold names the deadline it expects; a disagreement refuses the case, naming
    both, rather than testing a question production does not ask. preflight() runs
    this for every case before the first call.
    """
    import phase2_resolvability as P2  # noqa: PLC0415 -- the funnel, read at call time
    rec = _set(ctx.record(case["input"]["record"]), case["input"].get("set"))
    P2.attach_deadlines([rec], derive=True, implied=RESOLVE_IMPLIED)
    derived, want = rec.get("_deadline"), dt.date.fromisoformat(case["input"]["deadline"])
    if derived != want:
        raise SystemExit(f"REFUSING {case['id']}: the gold deadline is {want}, but production derives "
                         f"{derived} ({rec.get('_basis') or rec.get('_why_none')}) for this record; fix the gold "
                         f"before recording, or the case tests a prompt production never sends")
    return rec, derived


def funnel_implied(case: dict) -> "float | None":
    """The implied-window configuration a funnel case states it tests, or raise.

    input.implied is the scale (1.0 for the board's table) or null for implied windows
    off. It is required: the funnel gives a record with no date a window only with the
    table on, so a case that does not say which it tests does not say what it tests
    (final review item 6)."""
    import phase2_resolvability as P2  # noqa: PLC0415
    inp = case["input"]
    if "implied" not in inp:
        raise SystemExit(f"REFUSING {case['id']}: a funnel case must state the implied-window configuration it "
                         f"tests, input.implied: {RESOLVE_IMPLIED} for the board's table (the resolve and early "
                         f"cases' configuration) or null for off")
    if inp["implied"] is not None and inp["implied"] not in P2.IMPLIED_SCALES:
        raise SystemExit(f"REFUSING {case['id']}: input.implied {inp['implied']!r} is not null or one of "
                         f"{list(P2.IMPLIED_SCALES)}")
    return inp["implied"]


def preflight(cases: list[dict], ctx: Context) -> list[str]:
    """Every gold defect a run would meet, found before anything is called (final review item 6).

    Each resolve and early case's gold deadline against the one production derives,
    and each funnel case's stated configuration. A case left PENDING or BLOCKED is
    skipped, since it never runs. Returned as a list, so a refusal names them all."""
    problems = []
    for c in cases:
        if c.get("pending") or (c["stage"] == "resolve" and resolve_blocked(c)):
            continue
        try:
            if c["stage"] in ("resolve", "early"):
                resolve_record(c, ctx)
            elif c["stage"] == "funnel":
                funnel_implied(c)
            elif c["stage"] == "dating":
                case_harnesses(c)
                case_pairs(c)
                case_merge_version(c)
            elif c["stage"] == "dating_stored":
                stored_inputs(c, ctx)
                case_merge_version(c)
        except SystemExit as exc:
            problems.append(str(exc))
    return problems


def case_leads(case: dict, ctx: Context) -> list[str]:
    """The leads a dating case's prompt shows every dater, as production builds them. The merge reads them too:
    two daters copying a shown day do not agree independently (review fix 3)."""
    recs_path = case["input"].get("records")
    recs = L.parse_lines(ctx.path(recs_path).read_text(), recs_path) if recs_path else []
    meta_path = ctx.data / recs_path.replace(".jsonl", ".meta.json") if recs_path else None
    meta = json.loads(meta_path.read_text()) if meta_path and meta_path.is_file() else None
    return DL.leads_from_records(recs, meta)[0]


def build_prompt(case: dict, ctx: Context, harness: str | None = None) -> str:
    """The prompt production sends. A dating prompt differs per dater (its YOUR TOOLS block), so it names one."""
    st, inp = case["stage"], case["input"]
    if st == "dating":
        if harness is None:
            raise ValueError(f"{case['id']}: a dating prompt is built for one dater; name it")
        rec = json.loads(ctx.path(inp["transcript"]).read_text())
        return DL.build_dating_prompt(rec, case_leads(case, ctx), harness=harness)[0]
    if st == "extract":
        rec = _transcript(case, ctx)
        roster = {r["slug"]: r for r in json.loads(ctx.path(inp.get("roster", "roster/final.json")).read_text())["roster"]}
        spec = L.read_spec(L.SKILL / L.EXTRACTION_SPEC)
        schema = json.dumps(json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()), indent=1)
        return L.build_extraction_prompt(rec, roster.get(rec["leader_slug"]), spec, schema, L.load_header_template())
    if st == "resolve":
        import resolution_lib as R  # noqa: PLC0415 -- another stage's module, read at call time
        rec, deadline = resolve_record(case, ctx)
        return R.build_resolver_prompt(rec, deadline, inp["today"])
    if st == "early":
        import resolution_lib as R  # noqa: PLC0415
        rec, deadline = resolve_record(case, ctx)
        return R.build_early_prompt(rec, deadline, inp["today"])
    raise ValueError(f"stage {st} has no prompt")


# ---------------------------------------------------------------------------
# Judging one answer: (status, detail), status in pass / fail / hard_fail / queued
# ---------------------------------------------------------------------------

def _dates_ok(lo, hi, band):
    return band is not None and band[0] <= lo and hi <= band[1]


DATERS_BEFORE_20261005 = ("gemini", "fable")


def case_speaker_company(case: dict, ctx: Context, slug: str) -> str:
    """The speaker's company merge-5 reads: the case's input.speaker_company, else the data root's roster. Never guessed."""
    if case["input"].get("speaker_company") is not None:
        return case["input"]["speaker_company"]
    roster = ctx.data / "roster" / "final.json"
    if not roster.is_file():
        raise SystemExit(f"REFUSING {case['id']}: no input.speaker_company and no roster at {roster}; merge-5 reads "
                         f"the speaker's company")
    hit = [r.get("company") for r in json.loads(roster.read_text())["roster"] if r.get("slug") == slug]
    if len(hit) != 1 or not isinstance(hit[0], str) or not hit[0].strip():
        raise SystemExit(f"REFUSING {case['id']}: the roster at {roster} gives {len(hit)} company entries for {slug}")
    return hit[0]


def case_merge_version(case: dict) -> str:
    """The merge rules a dating case is judged under: input.merge_version, else today's (DL.MERGE_VERSION)."""
    v = case["input"].get("merge_version") or DL.MERGE_VERSION
    DL.merge_rank(v)          # an unknown version raises here, before anything runs
    return v


def judge_dating(case: dict, ctx: Context, answers: dict) -> tuple[str, str]:
    """One repeat: every dater's answer and its page checks, {harness: (text, checks)}, through the real merge."""
    rec = json.loads(ctx.path(case["input"]["transcript"]).read_text())
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    version = case_merge_version(case)
    docs, checks_by = [], {}
    for h, (text, checks) in answers.items():
        # An answer that is not valid JSON, or fails validation, is an invalid proposal, as
        # date_recordings stores it (review fix 5): the merge reads it as invalid_proposal and
        # the other dater's confirmation stands.
        try:
            obj = L.extract_json(text)
            obj = obj if isinstance(obj, dict) else {}
        except (ValueError, json.JSONDecodeError):
            obj = {}
        docs.append({"proposal": obj, "harness": h, "daters": list(answers), "leads": case_leads(case, ctx),
                     "speaker_company": case_speaker_company(case, ctx, rec["leader_slug"])})
        checks_by[h] = checks if not DL.validate_proposal(obj, tid, version) else []
    return judge_merge(case["expect"], DL.merge(rec, docs, checks_by, version=version))


def judge_merge(ex: dict, out: dict) -> tuple[str, str]:
    """The merge's outcome against a dating case's expectation: (pass | fail | hard_fail | queued, detail).

    Two expectation shapes. The older one (cases-20260929) gives pass_within, and
    optionally soft_within and hard_outside, bands for the confirmed range. The
    operator-audit shape (cases-20261004-dating) gives "truth", the true range of the
    statement date, and judges the LAST day, which is the statement date (design D1):
      pass       the last day lies inside the truth, or, where the case names
                 "accept_bound", a RANGE (never a single day) whose last day lies in
                 that band and whose first day is not after the truth
      fail       a correct but wider bound: the range meets the truth, ends after it
      hard_fail  the range misses the truth: a wrong auto-confirmation
    A queue is "queued", and for a negative case the safe answer, so a pass.
    """
    if out["outcome"] == "queue":
        # A negative case is one the stage must NOT move; the queue is its safe answer (review item 6).
        return ("pass" if ex.get("negative") else "queued"), f"queued: {out['reason']}: {out['detail'][:160]}"
    e = out["entry"].get("statement_date_earliest") or out["entry"]["statement_date"]
    lat = out["entry"]["statement_date"]
    what = f"confirmed ({out['outcome']}) {e}..{lat}"
    # forbid_sources (2026-10-05): pages the operator checked and found to be about another occasion. An
    # entry that cites one is a wrong auto-confirmation whatever day it names, since the day came from it.
    used = {u for c in (out["entry"].get("confirmation") or {}).get("source_checks") or []
            for u in (c.get("url"), c.get("final_url")) if u} | {out["entry"].get("source_url")}
    bad = sorted(used & set(ex.get("forbid_sources") or []))
    if bad:
        return "hard_fail", f"WRONG AUTO-CONFIRMATION: {what} from {bad}, a page about another occasion"
    if "truth" in ex:
        lo, hi = ex["truth"]
        if lo <= lat <= hi:
            return "pass", f"{what}; the statement date {lat} is inside the true range {ex['truth']}"
        band = ex.get("accept_bound")
        if band and e < lat and band[0] <= lat <= band[1] and e <= hi:
            return "pass", (f"{what}; accepted as a bound: a range ending {lat}, inside {band}, never a day of "
                            f"speech")
        if e <= hi and lat >= lo:
            return "fail", f"{what}: a correct bound that meets the true range {ex['truth']} but ends after it"
        return "hard_fail", f"WRONG AUTO-CONFIRMATION: {what} misses the true range {ex['truth']}"
    if ex.get("negative"):
        # Only the statement date can be a wrong confirmation; an unsourced first day is an estimate.
        band = ex["pass_within"]
        return ("pass", f"{what}; the statement date {lat} is inside {band}") if band[0] <= lat <= band[1] else \
            ("hard_fail", f"WRONG AUTO-CONFIRMATION: {what}; the statement date {lat} is outside {band}")
    if _dates_ok(e, lat, ex["pass_within"]):
        return "pass", f"{what}, inside {ex['pass_within']}"
    hard = ex.get("hard_outside") or ex["pass_within"]
    if not (hard[0] <= lat <= hard[1]):
        return "hard_fail", f"WRONG AUTO-CONFIRMATION: {what}; the statement date {lat} is outside {hard}"
    if ex.get("soft_within") and _dates_ok(e, lat, ex["soft_within"]):
        return "fail", f"{what}: inside the upper-bound band {ex['soft_within']} but not the event {ex['pass_within']}"
    return "fail", f"{what}, not inside {ex['pass_within']}"


def judge_extract(case: dict, ctx: Context, text: str) -> tuple[str, str]:
    import extract_predictions as D  # noqa: PLC0415
    rec = _transcript(case, ctx)
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    try:
        obj = D.parse_model_output(text, json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()), tid)
    except RuntimeError as exc:
        return "fail", f"unparseable: {str(exc)[:200]}"
    prov = L.normalise_provenance("astra", {"requested_model": "eval", "served_model": "eval"}, None, "eval")
    records, _, _ = D.ground_candidates(rec, None, obj, prov, "e" * 12, "eval", "2026-09-29T00:00:00Z", {})
    want = L.normalise(case["input"]["quote_contains"])
    hits = [r for r in records if want in L.normalise(r["source"]["quote_original"])]
    if not hits:
        return "fail", "the operator's quote was not extracted (a re-extraction must keep it)"
    r = hits[0]
    p, ex, bad = r["prediction"], case["expect"], []
    if "target_date_in" in ex and p["target_date"] not in ex["target_date_in"]:
        bad.append(f"target_date {p['target_date']!r} not in {ex['target_date_in']}")
    if ex.get("target_date_null") and p["target_date"] is not None:
        bad.append(f"target_date {p['target_date']!r} should be null")
    if ex.get("target_date_text_contains") and ex["target_date_text_contains"].lower() not in (p["target_date_text"] or "").lower():
        bad.append(f"target_date_text {p['target_date_text']!r} lacks {ex['target_date_text_contains']!r}")
    for field, key in (("normalized_claim", "claim"), ("resolution_criteria", "criteria")):
        text_f = p[field] or ""
        for s in ex.get(f"{key}_not_contains", []):
            if s.lower() in text_f.lower():
                bad.append(f"{field} contains {s!r}")
        for s in ex.get(f"{key}_contains", []):
            if s.lower() not in text_f.lower():
                bad.append(f"{field} lacks {s!r}")
    if ex.get("criteria_not_report_deadline") and REPORT_DEADLINE_RE.search(p["resolution_criteria"] or ""):
        bad.append("the criterion dates the REPORT of a period's figure")
    if ex.get("criteria_names_period") and not re.search(ex["criteria_names_period"], p["resolution_criteria"] or "", re.I):
        bad.append(f"the criterion does not name the period ({ex['criteria_names_period']})")
    if bad:
        return "fail", "; ".join(bad)
    return "pass", f"target_date {p['target_date']!r}; criterion {p['resolution_criteria'][:120]!r}"


def judge_resolve(case: dict, ctx: Context, text: str, telemetry: "dict | None") -> tuple[str, str]:
    import resolution_lib as R  # noqa: PLC0415
    # The record with the case's own dates, as the prompt showed it: already_public is
    # judged against THAT statement date, never the stored one.
    rec, _ = resolve_record(case, ctx)
    try:
        obj = L.extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return "fail", f"no JSON in the answer: {exc}"
    errs = (L.check_schema(obj, R.RESOLUTION_SCHEMA)
            + R.validate_resolution(obj, rec["prediction_id"], R.statement_bound(rec))
            # Production's own floor, on the harness's search telemetry; an answer
            # production would refuse is never a pass here.
            + [f"research effort: {e}" for e in R.validate_effort(obj, telemetry or {})])
    if errs:
        return "fail", f"invalid resolution: {'; '.join(errs[:3])}"
    ex, bad = case["expect"], []
    if ex.get("hard_outcomes") and obj["outcome"] in ex["hard_outcomes"]:
        return "hard_fail", f"outcome {obj['outcome']} is a hard failure for this case"
    if ex.get("outcome_in") and obj["outcome"] not in ex["outcome_in"]:
        bad.append(f"outcome {obj['outcome']} not in {ex['outcome_in']}")
    ap = obj.get("already_public")
    if ex.get("already_public") == "null" and ap is not None:
        if ex.get("hard_if_present_on_or_before") and str(ap.get("date") or "") <= ex["hard_if_present_on_or_before"]:
            return "hard_fail", f"already_public {ap} for a claim that was not yet public"
        bad.append(f"already_public should be null, got {ap}")
    if ex.get("already_public") == "present":
        if not isinstance(ap, dict):
            bad.append("already_public is null; the words repeated the previous day's news")
        else:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ap.get("date") or "")) or \
                    ap["date"] > ex["already_public_on_or_before"]:
                bad.append(f"already_public.date {ap.get('date')!r} is not on or before {ex['already_public_on_or_before']}")
            blob = f"{ap.get('where', '')} {ap.get('what_it_shows', '')}".lower()
            for group in ex.get("already_public_mentions_all", []):
                if not any(w.lower() in blob for w in group):
                    bad.append(f"already_public names none of {group}")
    for group in ex.get("sources_mention_all", []):
        blob = " ".join(f"{s.get('where', '')} {s.get('what_it_shows', '')} {s.get('date', '')}" for s in obj["sources"]).lower()
        if not any(w.lower() in blob for w in group):
            bad.append(f"no source names any of {group}")
    if bad:
        return "fail", "; ".join(bad)
    return "pass", f"outcome {obj['outcome']}; already_public {ap}"


def judge_early(case: dict, ctx: Context, text: str, telemetry: "dict | None") -> tuple[str, str]:
    """An early call (VD-5 c) judged as resolve_predictions --stage early would: EARLY_SCHEMA,
    validate_early with the case's own statement date and range, and the effort floor."""
    import resolution_lib as R  # noqa: PLC0415
    rec, _ = resolve_record(case, ctx)
    try:
        obj = L.extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return "fail", f"no JSON in the answer: {exc}"
    errs = (L.check_schema(obj, R.EARLY_SCHEMA)
            + R.validate_early(obj, rec["prediction_id"], (rec.get("source") or {}).get("statement_date"),
                               case["input"]["today"], earliest=R.statement_bound(rec))
            + [f"research effort: {e}" for e in R.validate_effort(obj, telemetry or {})])
    if errs:
        return "fail", f"invalid early call: {'; '.join(errs[:3])}"
    ex, bad = case["expect"], []
    if ex.get("hard_outcomes") and obj["outcome"] in ex["hard_outcomes"]:
        return "hard_fail", f"outcome {obj['outcome']} is a hard failure for this case"
    if ex.get("outcome_in") and obj["outcome"] not in ex["outcome_in"]:
        bad.append(f"outcome {obj['outcome']} not in {ex['outcome_in']}")
    for group in ex.get("sources_mention_all", []):
        blob = " ".join(f"{s.get('where', '')} {s.get('what_it_shows', '')} {s.get('date', '')}"
                        for s in obj.get("sources") or []).lower()
        if not any(w.lower() in blob for w in group):
            bad.append(f"no source names any of {group}")
    if bad:
        return "fail", "; ".join(bad)
    return "pass", f"outcome {obj['outcome']}"


def resolve_blocked(case: dict) -> str | None:
    import resolution_lib as R  # noqa: PLC0415
    fields = set(case.get("requires_resolver_fields", [])) | ({"already_public"} if "already_public" in case["expect"] else set())
    need = sorted(k for k in fields if k not in R.RESOLUTION_SCHEMA["properties"])
    return (f"the resolver contract (resolution_lib.RESOLUTION_SCHEMA) lacks {need}; another agent is adding it"
            if need else None)


# ---------------------------------------------------------------------------
# Deterministic stages
# ---------------------------------------------------------------------------

def run_header(case: dict, ctx: Context) -> tuple[str, str]:
    rec = _transcript(case, ctx)
    line = next(x for x in L.speaker_header(rec, None).splitlines() if x.startswith("Statement date:"))
    bad = [f"lacks {s!r}" for s in case["expect"].get("contains", []) if s not in line]
    bad += [f"contains {s!r}" for s in case["expect"].get("not_contains", []) if s in line]
    return ("fail", f"{'; '.join(bad)}: {line}") if bad else ("pass", line)


def run_funnel(case: dict, ctx: Context) -> tuple[str, str]:
    import phase2_resolvability as P2  # noqa: PLC0415 -- another stage's module, read-only
    inp, ex = case["input"], case["expect"]
    r = _set(ctx.record(inp["record"]), inp.get("set"))
    P2.attach_deadlines([r], derive=True, implied=funnel_implied(case))
    if r.get("_deadline") is None:
        return ("pass", f"no deadline ({r['_why_none']})") if ex.get("deadline") is None else \
            ("fail", f"no deadline ({r['_why_none']}); expected {ex['deadline']}")
    flags = P2.funnel_flags(r, P2.MIN_LEAD_DAYS)
    got = {"deadline": r["_deadline"].isoformat(), "lead_days": flags["lead_days"], "eligible": flags["eligible"],
           "past_due": r["_deadline"] <= dt.date.fromisoformat(inp["as_of"])}
    bad = []
    want_deadline = ex.get("deadline")
    if isinstance(want_deadline, list):
        if not (want_deadline[0] <= got["deadline"] <= want_deadline[1]):
            bad.append(f"deadline {got['deadline']} not in {want_deadline}")
    elif want_deadline != got["deadline"]:
        bad.append(f"deadline {got['deadline']} != {want_deadline}")
    if "lead_days" in ex and not (ex["lead_days"][0] <= (got["lead_days"] or -1) <= ex["lead_days"][1]):
        bad.append(f"lead_days {got['lead_days']} not in {ex['lead_days']}")
    for k in ("eligible", "past_due"):
        if k in ex and ex[k] != got[k]:
            bad.append(f"{k} {got[k]} != {ex[k]}")
    if "failing_clauses" in ex:
        # Which clause fails, not only that one does: an implied row with no lower bound
        # fails only the lead floor, and the VD-7 lead test decides it.
        clauses = P2.failing_clauses(flags, r["prediction_id"])
        if clauses != ex["failing_clauses"]:
            bad.append(f"failing_clauses {clauses} != {ex['failing_clauses']}")
    return ("fail", "; ".join(bad) + f" ({r['_basis']})") if bad else ("pass", f"{got} ({r['_basis']})")


# ---------------------------------------------------------------------------
# Running a model case
# ---------------------------------------------------------------------------

def aggregate(outcomes: list[tuple[str, str]], infra: Counter) -> tuple[str, str]:
    valid = [o for o in outcomes if o[0] != "infra"]
    n_inf = sum(infra.values())
    tail = f"; {n_inf} infrastructure failure{'s' if n_inf != 1 else ''} excluded ({', '.join(f'{k} {v}' for k, v in sorted(infra.items()))})" if n_inf else ""
    if any(s == "hard_fail" for s, _ in valid):
        return "HARD_FAIL", next(d for s, d in valid if s == "hard_fail") + tail
    if len(valid) < 2:
        return "INCONCLUSIVE", f"{len(valid)} valid repeat(s); at least 2 are needed{tail}"
    k = sum(1 for s, _ in valid if s == "pass")
    need = len(valid) // 2 + 1
    summary = f"{k} of {len(valid)} valid repeats pass{tail}; {need} needed"
    if k >= need:
        return "PASS", summary
    if all(s == "queued" for s, _ in valid):
        return "QUEUED", summary + "; every repeat went to the human queue: " + valid[0][1]
    return "FAIL", summary + "; first miss: " + next(d for s, d in valid if s != "pass")


def judge(case, ctx, text, checks, telemetry=None):
    """A one-harness stage's answer. A dating repeat holds every dater's answer and goes to judge_dating."""
    if case["stage"] == "dating":
        raise ValueError(f"{case['id']}: a dating repeat is judged with every dater's answer (judge_dating)")
    if case["stage"] == "extract":
        return judge_extract(case, ctx, text)
    if case["stage"] == "early":
        return judge_early(case, ctx, text, telemetry)
    return judge_resolve(case, ctx, text, telemetry)


def requested_models(args) -> dict:
    return {"gemini": args.gemini_model, "astra": args.astra_model, "fable": "claude-fable-5-1",
            "fable_web": "claude-fable-5-1"}


def case_harness(case: dict) -> str:
    return case["input"].get("harness") or DEFAULT_HARNESS[case["stage"]]


def case_harnesses(case: dict) -> list[str]:
    """The harnesses ONE repeat of this case calls, each once.

    A dating case runs the stage's daters, DL.DATERS (operator decision VD-11), or
    the list its input.daters names. The gold's older input.harness, written when
    dating had one agent, must name one of them; it no longer chooses the daters.
    """
    if case["stage"] != "dating":
        return [case_harness(case)]
    if case["input"].get("pairs"):
        hs = []
        for pair in case_pairs(case):
            hs += [h for h in pair if h not in hs]
        return hs
    legacy = case["input"].get("harness")
    # A gold case written when dating had one agent names it in input.harness. Such a case was
    # recorded for the daters of its era, Gemini and Fable (VD-11), and replays with them; the
    # production daters changed on 2026-10-05 and do not reach back into old gold.
    hs = list(case["input"].get("daters") or (DATERS_BEFORE_20261005 if legacy is not None else DL.DATERS))
    if legacy is not None and legacy not in hs:
        raise SystemExit(f"REFUSING {case['id']}: input.harness {legacy!r} is not one of the case's daters {hs}; "
                         f"a dating case runs every dater (VD-11)")
    return hs


def case_pairs(case: dict) -> list[tuple[str, ...]]:
    """The dater sets a dating case is judged with, each through its own merge.

    input.pairs lists them (the 2026-10-04 comparison: Gemini with Fable, Fable with web
    tools, or Astra). One repeat calls every dater in their union ONCE, so the pairs share
    the same Gemini answer and differ only in their second dater: a paired comparison.
    Without input.pairs the case's daters are the one set.
    """
    raw = case["input"].get("pairs")
    if not raw:
        return [tuple(case_harnesses(case))]
    out = []
    for pair in raw:
        bad = [h for h in pair if h not in DL.HARNESS_TOOLS]
        if not pair or bad or len(set(pair)) != len(pair) or tuple(pair) in out:
            raise SystemExit(f"REFUSING {case['id']}: input.pairs entry {pair!r} must name distinct daters from "
                             f"{sorted(DL.HARNESS_TOOLS)}, once each")
        out.append(tuple(pair))
    return out


_REPEAT = re.compile(r"^r(\d+)(?:\.([a-z_]+))?\.json$")


def _next_repeat(d: Path) -> int:
    ns = [int(m.group(1)) for p in d.glob("r*.json") if (m := _REPEAT.match(p.name))] if d.exists() else []
    return max(ns) + 1 if ns else 0


def run_offline_dating(case: dict, ctx: Context, requested: dict) -> tuple[str, str]:
    """Replay each repeat's recordings, one per dater (r<n>.<dater>.json), through the real merge."""
    hs = case_harnesses(case)
    shas = {h: hashlib.sha256(build_prompt(case, ctx, h).encode()).hexdigest() for h in hs}
    paths = sorted((ctx.gold / "recordings" / case["id"]).glob("r*.json"))
    if not paths:
        return "UNRECORDED", (f"no recorded answer; run --live to record one (prompt sha256 "
                              f"{', '.join(f'{h} {s[:12]}' for h, s in shas.items())})")
    docs = []
    for p in paths:
        m = _REPEAT.match(p.name)
        d = json.loads(p.read_text())
        if m is None or (m.group(2) and m.group(2) != d.get("harness")):
            return "RECORDING_REFUSED", f"{p.name} is not r<n>.<dater>.json for the harness it records"
        docs.append((int(m.group(1)), p, d))
    stale = [p.name for _, p, d in docs if d.get("harness") in shas and d["prompt_sha256"] != shas[d["harness"]]]
    if stale:
        return "PROMPT_CHANGED", f"prompt changed; re-record live ({len(stale)} of {len(docs)} recordings: {stale[:3]})"
    # A recording is this case's evidence only if one of its daters made it and the
    # requested model served it (review item 5, probe E1).
    wrong = [f"{p.name}: recorded by {d.get('harness')!r} serving {d.get('served_model')!r}" for _, p, d in docs
             if d.get("harness") not in hs or d.get("served_model") != requested[d["harness"]]]
    if wrong:
        return "RECORDING_REFUSED", (f"this case's daters are {', '.join(f'{h} ({requested[h]})' for h in hs)}; "
                                     f"{len(wrong)} of {len(docs)} recordings are not: {wrong[:3]}")
    by_n: dict[int, dict] = {}
    for n, _, d in docs:
        by_n.setdefault(n, {})[d["harness"]] = d
    lacking = [f"r{n:02d} lacks {sorted(set(hs) - set(g))}" for n, g in sorted(by_n.items()) if set(g) != set(hs)]
    if lacking:
        return "RECORDING_REFUSED", f"a repeat replays only with every dater's answer ({hs}): {lacking[:3]}"
    return aggregate([judge_dating(case, ctx, {h: (g[h]["response_text"], g[h].get("source_checks") or [])
                                               for h in hs}) for _, g in sorted(by_n.items())], Counter())


def run_live_dating(case: dict, ctx: Context, args, caller, fetcher, record_dir: Path) -> tuple[str, str]:
    """Each repeat calls every dater once, records every answer, and judges them together.

    The merge needs every dater, so an infrastructure failure of any one excludes
    the whole repeat; what the others already answered is kept under partial/,
    never replayed. A dater whose call fails for another reason fails the repeat.
    """
    hs = case_harnesses(case)
    prompts = {h: build_prompt(case, ctx, h) for h in hs}
    want = requested_models(args)
    rec = json.loads(ctx.path(case["input"]["transcript"]).read_text())
    out_dir = record_dir / case["id"]
    outcomes, infra = [], Counter()
    for i in range(args.repeats):
        got, stop = {}, None
        for h in hs:
            try:
                text, tel, identity = caller(h, prompts[h], args.timeout, Path(args.workroot) / f"{case['id']}-r{i}-{h}",
                                             args, i)
            except Exception as exc:  # noqa: BLE001 -- labelled, and never read as the model's answer
                label = L.classify_exception_detail(str(exc))
                stop = (label if label in INFRA else "fail", f"{h}: {label}: {str(exc)[:200]}")
                break
            if tel.get("served_model") != want[h]:
                # Another model answered: not this case's evidence, and not the model's fault either.
                stop = ("model_identity_mismatch", f"{h} served {tel.get('served_model')!r}, requested {want[h]!r}")
                break
            got[h] = _recording(case, i, h, prompts[h], want[h], text, tel, identity, _page_checks(text, rec, fetcher))
        where = out_dir / "partial" if stop else out_dir
        n = _next_repeat(where)
        where.mkdir(parents=True, exist_ok=True)
        for h, doc in got.items():
            (where / f"r{n:02d}.{h}.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
        if stop is None:
            outcomes.append(judge_dating(case, ctx, {h: (got[h]["response_text"], got[h]["source_checks"]) for h in hs}))
        elif stop[0] == "fail":
            outcomes.append(("fail", stop[1]))
        else:
            infra[stop[0]] += 1
            outcomes.append(("infra", stop[1]))
    return aggregate(outcomes, infra)


# Telemetry a dating recording keeps: enough to say which model and account served it and
# whether, and how much, it searched (the 2026-10-04 comparison counts searches per dater).
TELEMETRY_KEYS = ("web_search", "web_search_queries", "tool_use_counts", "attempts", "empty_retries",
                  "requested_model", "telemetry_models", "judge_model", "web_searches", "web_fetches",
                  "fetched_urls", "server_web_search_requests", "denied_or_failed", "num_turns", "cost_usd",
                  "duration_ms", "config_dir", "profile_identity", "profile_home", "sandbox_denied_roots", "router")


def _page_checks(text: str, rec: dict, fetcher) -> list[dict]:
    """Every page the answer cites, checked as production checks it (with the proposal, for a date-alone excerpt)."""
    checks = []
    try:
        obj = L.extract_json(text)
        for src in obj.get("sources") or []:
            why = DL.own_page_reason(src["url"], rec)
            checks.append(DL.refused_check(src, why) if why else
                          DL.check_source(src, rec, fetcher.fetch(src["url"]), obj))
    except (ValueError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        checks = []
    return checks


def _recording(case: dict, i: int, h: str, prompt: str, want: str, text: str, tel: dict, identity, checks) -> dict:
    return {"case": case["id"], "repeat_of_run": i, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "harness": h, "requested_model": want, "response_text": text,
            "served_model": tel.get("served_model"), "served_model_verified": tel.get("served_model_verified"),
            "identity": identity, "telemetry": {k: v for k, v in tel.items() if k in TELEMETRY_KEYS},
            "source_checks": checks, "recorded_at_utc": DL.utc_stamp()}


def _call_dater(case: dict, i: int, h: str, prompt: str, args, caller, fetcher, rec: dict, want: str):
    """One dater's call in repeat i: (recording, None), or (None, (label, detail)) with label an INFRA one or "fail"."""
    try:
        text, tel, identity = caller(h, prompt, args.timeout, Path(args.workroot) / f"{case['id']}-r{i}-{h}", args, i)
    except Exception as exc:  # noqa: BLE001 -- labelled, and never read as the model's answer
        label = L.classify_exception_detail(str(exc))
        return None, (label if label in INFRA else "fail", f"{h}: {label}: {str(exc)[:300]}")
    if tel.get("served_model") != want:
        return None, ("model_identity_mismatch", f"{h} served {tel.get('served_model')!r}, requested {want!r}")
    return _recording(case, i, h, prompt, want, text, tel, identity, _page_checks(text, rec, fetcher)), None


def _repeat_numbers(d: Path) -> list[int]:
    return sorted({int(m.group(1)) for sub in (d, d / "failed") if sub.exists() for p in sub.glob("r*.json")
                   if (m := _REPEAT.match(p.name))})


def run_live_dating_pairs(case: dict, ctx: Context, args, caller, fetcher,
                          record_dir: Path) -> list[tuple[str, str, str]]:
    """Each repeat calls every dater in the union of the case's pairs ONCE and judges every pair: [(pair, status, detail)].

    An answer is recorded as r<n>.<dater>.json; a failed call as failed/r<n>.<dater>.json
    with its label, so a replay knows which pairs that repeat can still judge. A failure
    excludes the repeat only for the pairs holding that dater, as an infrastructure
    failure (counted) or a plain fail. A dater every one of whose pairs has already lost
    a dater in the repeat is not called, and recorded as skipped, to spend no quota on
    an answer nothing could judge.
    """
    pairs, hs = case_pairs(case), case_harnesses(case)
    prompts = {h: build_prompt(case, ctx, h) for h in hs}
    want = requested_models(args)
    rec = json.loads(ctx.path(case["input"]["transcript"]).read_text())
    out_dir = record_dir / case["id"]
    results = {pr: ([], Counter()) for pr in pairs}
    for i in range(args.repeats):
        ns = _repeat_numbers(out_dir)
        n = ns[-1] + 1 if ns else 0
        got, failed = {}, {}
        for h in hs:
            if all(any(x in failed for x in pr) for pr in pairs if h in pr):
                failed[h] = ("skipped", f"{h}: not called; every pair holding it already lost a dater in this repeat")
            else:
                doc, fail = _call_dater(case, i, h, prompts[h], args, caller, fetcher, rec, want[h])
                if fail is None:
                    got[h] = doc
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / f"r{n:02d}.{h}.json").write_text(json.dumps(doc, indent=1, sort_keys=True,
                                                                           default=str) + "\n")
                    continue
                failed[h] = fail
            (out_dir / "failed").mkdir(parents=True, exist_ok=True)
            (out_dir / "failed" / f"r{n:02d}.{h}.json").write_text(json.dumps(
                {"case": case["id"], "repeat_of_run": i, "harness": h, "label": failed[h][0], "detail": failed[h][1],
                 "requested_model": want[h], "prompt_sha256": hashlib.sha256(prompts[h].encode()).hexdigest(),
                 "recorded_at_utc": DL.utc_stamp()}, indent=1, sort_keys=True) + "\n")
        for pr in pairs:
            outcomes, infra = results[pr]
            outcomes.append(_pair_outcome(case, ctx, pr, {h: d["response_text"] for h, d in got.items()},
                                          {h: d["source_checks"] for h, d in got.items()}, failed, infra))
    return [("+".join(pr), *aggregate(*results[pr])) for pr in pairs]


def _pair_outcome(case, ctx, pr, texts: dict, checks: dict, failed: dict, infra: Counter) -> tuple[str, str]:
    """One repeat's outcome for one pair: judged when every dater of the pair answered, else its failure."""
    lost = [failed[h] for h in pr if h in failed and failed[h][0] != "skipped"]
    if not lost and all(h in texts for h in pr):
        return judge_dating(case, ctx, {h: (texts[h], checks[h]) for h in pr})
    if not lost:
        raise ValueError(f"{case['id']} {pr}: a dater neither answered nor failed")
    if any(lab == "fail" for lab, _ in lost):
        return "fail", "; ".join(d for _, d in lost)
    infra[lost[0][0]] += 1
    return "infra", "; ".join(d for _, d in lost)


def run_offline_dating_pairs(case: dict, ctx: Context, requested: dict) -> list[tuple[str, str, str]]:
    """Replay a pairs case: every repeat, every pair, from r<n>.<dater>.json and failed/r<n>.<dater>.json."""
    pairs, hs = case_pairs(case), case_harnesses(case)
    shas = {h: hashlib.sha256(build_prompt(case, ctx, h).encode()).hexdigest() for h in hs}
    d = ctx.gold / "recordings" / case["id"]
    found: dict[int, dict] = {}
    for sub_dir, kind in ((d, "ok"), (d / "failed", "failed")):
        for path in sorted(sub_dir.glob("r*.json")) if sub_dir.exists() else []:
            m = _REPEAT.match(path.name)
            doc = json.loads(path.read_text())
            if m is None or m.group(2) != doc.get("harness") or doc.get("harness") not in hs:
                return [("+".join(pr), "RECORDING_REFUSED", f"{path.name} is not r<n>.<dater>.json for one of {hs}")
                        for pr in pairs]
            if kind == "ok" and doc.get("served_model") != requested[doc["harness"]]:
                return [("+".join(pr), "RECORDING_REFUSED", f"{path.name}: {doc['harness']} served "
                         f"{doc.get('served_model')!r}, not {requested[doc['harness']]!r}") for pr in pairs]
            if doc.get("prompt_sha256") != shas[doc["harness"]] and doc.get("label") != "skipped":
                return [("+".join(pr), "PROMPT_CHANGED", f"prompt changed; re-record live ({path.name})")
                        for pr in pairs]
            found.setdefault(int(m.group(1)), {})[doc["harness"]] = (kind, doc)
    if not found:
        return [("+".join(pr), "UNRECORDED", "no recorded answer; run --live to record one") for pr in pairs]
    rows = []
    for pr in pairs:
        outcomes, infra = [], Counter()
        for n, g in sorted(found.items()):
            if any(h not in g for h in pr):
                return [("+".join(x), "RECORDING_REFUSED", f"r{n:02d} has no recording or failure for "
                         f"{sorted(set(pr) - set(g))}") for x in pairs]
            texts = {h: g[h][1]["response_text"] for h in pr if g[h][0] == "ok"}
            checks = {h: g[h][1].get("source_checks") or [] for h in pr if g[h][0] == "ok"}
            failed = {h: (g[h][1]["label"], g[h][1]["detail"]) for h in pr if g[h][0] == "failed"}
            outcomes.append(_pair_outcome(case, ctx, pr, texts, checks, failed, infra))
        rows.append(("+".join(pr), *aggregate(outcomes, infra)))
    return rows


# ---------------------------------------------------------------------------
# dating_stored: a deterministic replay of proposals and checks already on disk
# ---------------------------------------------------------------------------

def _pinned(base: Path, rel: str, sha: str | None, where: str) -> bytes:
    path = base / rel
    if not path.is_file():
        raise SystemExit(f"REFUSING {where}: {path} does not exist")
    raw = path.read_bytes()
    if sha is None or hashlib.sha256(raw).hexdigest() != sha:
        raise SystemExit(f"REFUSING {where}: {path} does not match its pinned sha256 {sha!r}")
    return raw


def stored_inputs(case: dict, ctx: Context) -> tuple[dict, list[dict], dict]:
    """(transcript, docs, checks by dater) for a dating_stored case, every file checked against its sha256.

    input.proposals[dater] is {"path", "sha256"} under the data root (a stored
    proposal file) or {"inline": proposal} (a synthetic control); input.checks[dater]
    is {"path", "sha256"} under the data root, {"gold", "sha256"} under the gold
    directory (a page re-checked for this gold set), {"inline": [checks]}, or null.
    """
    inp = case["input"]
    rec = json.loads(ctx.path(inp["transcript"]).read_text())
    daters = inp["daters"]
    docs, checks_by = [], {}
    for h in daters:
        spec = inp["proposals"][h]
        if "inline" in spec:
            doc = {"proposal": spec["inline"], "harness": h, "daters": daters, "leads": []}
            if inp.get("speaker_company") is not None:
                doc["speaker_company"] = inp["speaker_company"]
        else:
            doc = json.loads(_pinned(ctx.data, spec["path"], spec.get("sha256"), f"{case['id']} {h} proposal"))
            if inp.get("speaker_company") is not None:
                if doc.get("speaker_company") not in (None, inp["speaker_company"]):
                    raise SystemExit(f"REFUSING {case['id']}: {spec['path']} records speaker_company "
                                     f"{doc['speaker_company']!r}, the gold says {inp['speaker_company']!r}")
                # A file written before merge-5 records no company; the gold names the roster's, in the open.
                doc["speaker_company"] = inp["speaker_company"]
            if doc.get("harness") != h:
                raise SystemExit(f"REFUSING {case['id']}: {spec['path']} was made by {doc.get('harness')!r}, not {h!r}")
        docs.append(doc)
        c = (inp.get("checks") or {}).get(h)
        if c is None:
            checks_by[h] = []
        elif "inline" in c:
            checks_by[h] = c["inline"]
        else:
            base, rel = (ctx.gold, c["gold"]) if "gold" in c else (ctx.data, c["path"])
            checks_by[h] = json.loads(_pinned(base, rel, c.get("sha256"), f"{case['id']} {h} checks"))["checks"]
    return rec, docs, checks_by


def run_dating_stored(case: dict, ctx: Context) -> tuple[str, str]:
    """The real merge, under the case's merge version, over stored or inline proposals and checks. No model."""
    rec, docs, checks_by = stored_inputs(case, ctx)
    version = case_merge_version(case)
    status, detail = judge_merge(case["expect"], DL.merge(rec, docs, checks_by, version=version))
    return status.upper(), f"{version}: {detail}"


def run_offline(case: dict, ctx: Context, requested: dict) -> tuple[str, str]:
    prompt = build_prompt(case, ctx)
    sha = hashlib.sha256(prompt.encode()).hexdigest()
    recs = sorted((ctx.gold / "recordings" / case["id"]).glob("*.json"))
    if not recs:
        return "UNRECORDED", f"no recorded answer; run --live to record one (prompt sha256 {sha[:12]})"
    docs = [json.loads(p.read_text()) for p in recs]
    stale = [p.name for p, d in zip(recs, docs) if d["prompt_sha256"] != sha]
    if stale:
        return "PROMPT_CHANGED", f"prompt changed; re-record live ({len(stale)} of {len(docs)} recordings: {stale[:3]})"
    # A recording is this case's evidence only if the case's harness made it and the
    # requested model served it (review item 5, probe E1).
    harness = case_harness(case)
    wrong = [f"{p.name}: recorded by {d.get('harness')!r} serving {d.get('served_model')!r}"
             for p, d in zip(recs, docs)
             if d.get("harness") != harness or d.get("served_model") != requested[harness]]
    if wrong:
        return "RECORDING_REFUSED", (f"this case runs on {harness} ({requested[harness]}); "
                                     f"{len(wrong)} of {len(docs)} recordings do not: {wrong[:3]}")
    return aggregate([judge(case, ctx, d["response_text"], d.get("source_checks") or [], d.get("telemetry"))
                      for d in docs], Counter())


def run_live(case: dict, ctx: Context, args, caller, fetcher, record_dir: Path) -> tuple[str, str]:
    prompt = build_prompt(case, ctx)
    sha = hashlib.sha256(prompt.encode()).hexdigest()
    harness = case_harness(case)
    want_model = requested_models(args)[harness]
    outcomes, infra = [], Counter()
    out_dir = record_dir / case["id"]
    for i in range(args.repeats):
        try:
            text, tel, identity = caller(harness, prompt, args.timeout,
                                         Path(args.workroot) / f"{case['id']}-r{i}", args, i)
        except Exception as exc:  # noqa: BLE001 -- labelled, and never read as the model's answer
            label = L.classify_exception_detail(str(exc))
            if label in INFRA:
                infra[label] += 1
                outcomes.append(("infra", str(exc)[:200]))
                continue
            outcomes.append(("fail", f"{label}: {str(exc)[:200]}"))
            continue
        if tel.get("served_model") != want_model:
            # Another model answered: not this case's evidence, and not the model's fault either.
            infra["model_identity_mismatch"] += 1
            outcomes.append(("infra", f"served {tel.get('served_model')!r}, requested {want_model!r}"))
            continue
        checks = []    # a one-harness stage cites no pages; dating runs in run_live_dating
        n = len(list(out_dir.glob("*.json"))) if out_dir.exists() else 0
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"r{n:02d}.json").write_text(json.dumps(
            {"case": case["id"], "prompt_sha256": sha, "harness": harness, "requested_model": want_model,
             "response_text": text,
             "served_model": tel.get("served_model"), "served_model_verified": tel.get("served_model_verified"),
             "identity": identity, "telemetry": {k: v for k, v in tel.items() if k in (
                 "web_search", "web_search_queries", "tool_use_counts", "attempts", "empty_retries",
                 "requested_model")},
             "source_checks": checks, "recorded_at_utc": DL.utc_stamp()}, indent=1, sort_keys=True, default=str) + "\n")
        outcomes.append(judge(case, ctx, text, checks, tel))
    return aggregate(outcomes, infra)


def estimate(cases: list[dict], repeats: int) -> str:
    """What --live would spend. A pending or blocked case spends nothing, so it is not counted (review item 15)."""
    model = [c for c in cases if c["stage"] in MODEL_STAGES and not c.get("pending")]
    blocked = [c for c in model if c["stage"] == "resolve" and resolve_blocked(c)]
    model = [c for c in model if c not in blocked]
    by: Counter = Counter()
    for c in model:
        try:
            hs = case_harnesses(c)
        except SystemExit:
            continue          # preflight names it, and --estimate then refuses
        for h in hs:
            by[h] += repeats
    return (f"live run: {len(model)} model cases x {repeats} repeats: {sum(by.values())} calls "
            f"({', '.join(f'{h} {n}' for h, n in sorted(by.items()))}); a dating repeat calls each of its daters "
            f"once (production: {', '.join(DL.DATERS)}); {len(blocked)} blocked case(s) spend nothing; dating cases "
            f"also fetch "
            f"every cited page, direct then Wayback")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", type=Path, required=True, help="the gold directory holding cases.json")
    ap.add_argument("--data", type=Path, default=None, help="the data root the cases name; default the data link")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="the default: replay recorded answers")
    mode.add_argument("--live", action="store_true", help="call the models (needs PREDICT_LIVE=1)")
    ap.add_argument("--smoke", action="store_true", help="only the gold file's smoke list, in its order")
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    ap.add_argument("--estimate", action="store_true", help="print what --live would spend, and stop")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--record-dir", type=Path, default=None, help="where --live writes answers; default <gold>/recordings")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--workroot", default=str(Path(os.environ.get("TMPDIR", "/tmp")) / "case-eval-work"))
    ap.add_argument("--gemini-model", default="gemini-3.8-flash-high")
    # The agy-as-user wrapper runs only this path, and --live dating reaches the
    # router-config rotation through date_recordings.call_agent with these args.
    # "agy" here stopped every live dating eval at preflight with wrapper exit 77.
    ap.add_argument("--agy-bin", default="/usr/local/bin/agy")
    ap.add_argument("--astra-model", default="gpt-6-astra")
    ap.add_argument("--codex-home", default=None)
    ap.add_argument("--fable-bin", default="claude")
    ap.add_argument("--fable-config-dir", default=None,
                    help="a pin: Fable calls rotate over these Claude config dirs; with none the quota router "
                         "picks the account for each call (date_recordings.fable_account)")
    ap.add_argument("--allow-degraded", action="store_true",
                    help="spend a Fable call on a router pick it does not call a fit; refused without it")
    return ap


def main(argv: list[str] | None = None, caller=None, opener=None, sleep=time.sleep) -> int:
    args = build_parser().parse_args(argv)
    data = (args.data or L.data_root())
    if not (data / "predictions").is_dir():
        raise SystemExit(f"REFUSING: the cases name private records under a data root, and {data} has no "
                         f"predictions/ directory. Link the data checkout (ln -s <data> data) or pass --data.")
    doc = json.loads((args.gold / "cases.json").read_text())
    cases = doc["cases"]
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"duplicate case ids in {args.gold / 'cases.json'}")
    if args.smoke:
        by = {c["id"]: c for c in cases}
        missing = [x for x in doc.get("smoke", []) if x not in by]
        if missing or not doc.get("smoke"):
            raise SystemExit(f"the smoke list names unknown cases {missing}" if missing else "the gold file has no smoke list")
        cases = [by[x] for x in doc["smoke"]]
    if args.only:
        want = [x for x in args.only.split(",") if x]
        unknown = [x for x in want if x not in {c["id"] for c in cases}]
        if unknown:
            raise SystemExit(f"--only names cases that are not in the selection: {unknown}")
        cases = [c for c in cases if c["id"] in want]
    if not cases:
        raise SystemExit("the selection is empty: no case would run")
    for c in cases:
        if c["stage"] not in STAGES:
            raise SystemExit(f"case {c['id']}: unknown stage {c['stage']!r}")
    ctx = Context(data, args.gold)
    # Every gold defect, before any case runs and before any call: a --live run must
    # never spend calls on early cases and then refuse a later one (final review item 6).
    problems = preflight(cases, ctx)
    if args.estimate:
        print(estimate(cases, args.repeats))
        if problems:
            raise SystemExit(f"REFUSING: --live would refuse these {len(problems)} case(s) before its first call:\n  "
                             + "\n  ".join(problems))
        return 0
    if problems:
        raise SystemExit(f"REFUSING before any case runs: {len(problems)} gold defect(s):\n  " + "\n  ".join(problems))
    if args.live and os.environ.get("PREDICT_LIVE") != "1":
        raise SystemExit("refusing to call a model: set PREDICT_LIVE=1 for --live (it spends quota; run --estimate first)")
    if args.live:
        import date_recordings as DR  # noqa: PLC0415
        caller = caller or DR.call_agent
        fetcher = DR.PoliteFetcher(opener, sleep=sleep)
        print(estimate(cases, args.repeats) + ". SPENDS QUOTA.")
    rows = []
    for c in cases:
        if c.get("pending"):
            status, detail = "PENDING", c["pending"]
        elif c["stage"] == "resolve" and resolve_blocked(c):
            status, detail = "BLOCKED", resolve_blocked(c)
        elif c["stage"] == "header":
            status, detail = run_header(c, ctx)
            status = status.upper()
        elif c["stage"] == "funnel":
            status, detail = run_funnel(c, ctx)
            status = status.upper()
        elif c["stage"] == "dating_stored":
            status, detail = run_dating_stored(c, ctx)
        elif c["stage"] == "dating" and c["input"].get("pairs"):
            per_pair = (run_live_dating_pairs(c, ctx, args, caller, fetcher, args.record_dir or args.gold / "recordings")
                        if args.live else run_offline_dating_pairs(c, ctx, requested_models(args)))
            for pair, status, detail in per_pair:
                rows.append({"id": f"{c['id']}[{pair}]", "operator_case": c.get("operator_case"), "stage": c["stage"],
                             "pair": pair, "status": status, "detail": detail})
                print(f"[{status}] {c['id']}[{pair}]  {detail}")
            continue
        elif args.live and c["stage"] == "dating":
            status, detail = run_live_dating(c, ctx, args, caller, fetcher, args.record_dir or args.gold / "recordings")
        elif args.live:
            status, detail = run_live(c, ctx, args, caller, fetcher, args.record_dir or args.gold / "recordings")
        elif c["stage"] == "dating":
            status, detail = run_offline_dating(c, ctx, requested_models(args))
        else:
            status, detail = run_offline(c, ctx, requested_models(args))
        rows.append({"id": c["id"], "operator_case": c.get("operator_case"), "stage": c["stage"], "status": status,
                     "detail": detail})
        print(f"[{status}] {c['id']} ({detail})" if status == "PASS" and "valid repeats" in detail
              else f"[{status}] {c['id']}  {detail}")
    tally = Counter(r["status"] for r in rows)
    wrong = sum(1 for r in rows if r["stage"] == "dating" and r["status"] == "HARD_FAIL")
    print(f"\n{dict(sorted(tally.items()))}")
    dating = [r for r in rows if r["stage"] == "dating"]
    judged = [r for r in dating if r["status"] in JUDGED_STATUSES]
    # 0 errors in n cases bounds the error rate below about 3/n at 95%, no lower (critique 3 C4).
    unjudged = Counter(r["status"] for r in dating if r["status"] not in JUDGED_STATUSES)
    print(f"dating: wrong auto-confirmations: {wrong} of {len(judged)} judged dating cases "
          f"({len(dating) - len(judged)} of {len(dating)} not judged"
          + (f": {', '.join(f'{k} {v}' for k, v in sorted(unjudged.items()))})" if unjudged else ")"))
    stored = [r for r in rows if r["stage"] == "dating_stored"]
    if stored:
        print(f"dating_stored (no model): {dict(sorted(Counter(r['status'] for r in stored).items()))}; wrong "
              f"auto-confirmations {sum(1 for r in stored if r['status'] == 'HARD_FAIL')} of {len(stored)}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"gold": str(args.gold), "mode": "live" if args.live else "offline",
                                           "rows": rows, "tally": tally, "at_utc": DL.utc_stamp()}, indent=1) + "\n")
    if tally["FAIL"] or tally["HARD_FAIL"] or tally["PROMPT_CHANGED"] or tally["RECORDING_REFUSED"]:
        return 1
    return 0 if set(tally) <= {"PASS"} else 3


if __name__ == "__main__":
    sys.exit(main())
