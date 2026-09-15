#!/usr/bin/env python3
"""Phase 2, stages 1 and 2: what happened, and how likely it looked beforehand.

Pure functions only. Prompt building, output validation and the sidecar record
shape live here so they can be tested without spending a model call, exactly as
`predictions_lib` holds the extraction contract.

TWO STAGES, AND THE WALL BETWEEN THEM
-------------------------------------
The resolver decides whether the predicted thing happened, and must cite
something for it. The prior assessor decides how likely it looked on the day it
was said, and must never learn the answer. A prior chosen by a reader who
already knows the outcome is not an ex-ante probability: knowing a prediction
failed invites a lower p, which shrinks the penalty, and knowing it landed
invites a higher p, which shrinks the reward. Both squash every score toward
zero, so the wall is what makes the number mean anything.

The wall is structural, not a request in the prompt. `build_prior_prompt` reads
a fixed list of fields off the record and cannot reach a resolution even when
one is attached, and `test_resolution_lib.py` proves it by attaching an outcome
and asserting the prompt is byte-identical. What the wall does NOT do is remove
what the model already knows from training, which is why the prior stage runs on
the sandboxed harness and why `docs/PREDICTIONS-SCORING.md` carries a measured
hindsight figure rather than a claim of blindness.

THE DEADLINE IS THE ONE THE FUNNEL COMPUTED
-------------------------------------------
Both prompts state a deadline, and it comes from `phase2_resolvability`, never
from a second parser here. `prediction.target_date` is documented in three forms
and a partial one expands to its LAST day; a resolver told "2020" instead of
"2020-12-31" would resolve a year-long claim against New Year's Day.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The resolver may only answer with one of these. "unresolvable" is a first-class
# answer, not a failure: a resolver with no way to decline invents evidence.
OUTCOMES = ("occurred", "not_occurred", "unresolvable")

# Why a resolution could not be reached. A free-text reason would not aggregate,
# and "we could not find out" and "the claim has no single answer" are different
# problems with different fixes.
UNRESOLVABLE_REASONS = (
    "no_public_evidence",      # nothing found either way
    "criterion_ambiguous",     # the criterion admits two readings that disagree
    "criterion_undirected",    # the criterion states no direction to test
    "threshold_unmeasurable",  # the quantity named is not publicly reported
    "deadline_incoherent",     # the deadline precedes the statement, or is unreadable
    "after_knowledge_cutoff",  # the window closed too recently to have a public record
)

# Clamp bounds, shared with prediction_score.CLAMP. A model that answers 0 or 1
# is asserting certainty, and a log score of a wrong certainty is infinite.
P_MIN, P_MAX = 0.01, 0.99

RESOLUTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prediction_id", "outcome", "confidence", "reasoning", "sources", "unresolvable_reason"],
    "properties": {
        "prediction_id": {"type": "string", "minLength": 1},
        "outcome": {"enum": list(OUTCOMES)},
        "confidence": {"enum": ["high", "medium", "low"]},
        "reasoning": {"type": "string", "minLength": 1},
        "unresolvable_reason": {"anyOf": [{"enum": list(UNRESOLVABLE_REASONS)}, {"type": "null"}]},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["what_it_shows", "where", "date"],
                "properties": {
                    "what_it_shows": {"type": "string", "minLength": 1},
                    "where": {"type": "string", "minLength": 1},
                    "date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
            },
        },
    },
}

PRIOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prediction_id", "p", "reference_class", "reasoning"],
    "properties": {
        "prediction_id": {"type": "string", "minLength": 1},
        "p": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reference_class": {"type": "string", "minLength": 1},
        "reasoning": {"type": "string", "minLength": 1},
    },
}


# ---------------------------------------------------------------------------
# What each stage is allowed to see
# ---------------------------------------------------------------------------

def prompt_facts(rec: dict, deadline: "dt.date | None") -> dict:
    """The fields BOTH stages may read, pulled off the record in one place.

    Nothing here touches `rec["resolution"]` or any sidecar. Adding a field is a
    deliberate edit to this function, which is what makes the blindness testable.
    """
    src = rec.get("source") or {}
    pred = rec.get("prediction") or {}
    spk = rec.get("speaker") or {}
    return {
        "prediction_id": rec["prediction_id"],
        "speaker": spk.get("name") or "",
        "role": spk.get("role") or "",
        "company": spk.get("company") or "",
        "statement_date": src.get("statement_date") or "",
        "venue": src.get("venue") or "",
        "title": src.get("title") or "",
        "quote": src.get("quote") or "",
        "context_before": (src.get("context_before") or "")[-1200:],
        "context_after": (src.get("context_after") or "")[:1200],
        "claim": pred.get("normalized_claim") or "",
        "criterion": pred.get("resolution_criteria") or "",
        # A missing deadline SAYS so. The repair stage runs over records the funnel
        # could not date, and a placeholder date there would be read as a real one.
        "deadline": deadline.isoformat() if deadline else "(no closing date this pipeline could read)",
        "target_date_text": pred.get("target_date_text") or "",
        "category": pred.get("category") or "",
    }


def _block(f: dict) -> str:
    """The shared description of one prediction. Identical text in both prompts,
    so the two stages are reading the same claim and any difference in their
    answers is the stage rather than the wording."""
    who = ", ".join(x for x in (f["role"], f["company"]) if x)
    return f"""PREDICTION {f["prediction_id"]}

Speaker:         {f["speaker"]}{f" ({who})" if who else ""}
Said on:         {f["statement_date"]}
Where:           {f["title"]}{f" [{f['venue']}]" if f["venue"] else ""}
Deadline:        {f["deadline"]}   (from the speaker's own wording: "{f["target_date_text"]}")
Category:        {f["category"]}

WHAT WAS SAID, verbatim:
  "{f["quote"]}"

Surrounding words, for context only:
  ...{f["context_before"]}  [[QUOTE]]  {f["context_after"]}...

The claim, as this pipeline recorded it:
  {f["claim"]}

The resolution criterion, as this pipeline recorded it:
  {f["criterion"]}
"""


# ---------------------------------------------------------------------------
# Stage 1: the resolver
# ---------------------------------------------------------------------------

RESOLVER_TASK = """You are resolving a dated public prediction. Decide whether the thing
described by the resolution criterion actually happened by the deadline.

RULES

1. Answer "occurred" only if the criterion was satisfied ON OR BEFORE the deadline.
   Something that happened a year late did NOT occur for this purpose; say
   "not_occurred" and record the real date in your reasoning.

2. The criterion states the SPEAKER'S predicted outcome. "occurred" means the
   speaker was RIGHT. If the criterion carries a negation, such as "will not have
   surpassed", then "occurred" means the thing indeed did not happen.

3. CITE SOMETHING for every resolution. Each source needs what it shows, where it
   is (a URL, or a specific named document, filing, release or report), and its
   date. A resolution with no source is not a resolution. If you have web search,
   use it; work from public record, not from impression.

4. You may answer "unresolvable", and you should whenever the honest answer is
   that you cannot tell. This is a real answer and costs nothing. Use it when:
     - no_public_evidence: nothing public settles it either way
     - criterion_ambiguous: the criterion has two readings that disagree
     - criterion_undirected: the criterion states no direction to test, for
       example "X will or will not happen"
     - threshold_unmeasurable: the number named is not publicly reported
     - deadline_incoherent: the deadline precedes the statement, or makes no sense
     - after_knowledge_cutoff: the window closed too recently for a public record
   Never guess in order to avoid answering "unresolvable". A wrong outcome is far
   more expensive here than an honest refusal, because it is scored as if true.

5. "confidence" is about the RESOLUTION, not about the prediction. Use "high" when
   a cited source settles it directly, "medium" when it follows from cited sources
   by a short step, "low" when you are reading between the lines.

Answer with one JSON object and nothing else:

{
  "prediction_id": "<copy it back exactly>",
  "outcome": "occurred" | "not_occurred" | "unresolvable",
  "confidence": "high" | "medium" | "low",
  "sources": [{"what_it_shows": "...", "where": "...", "date": "YYYY-MM-DD or null"}],
  "unresolvable_reason": null or one of the reasons named in rule 4,
  "reasoning": "two to five sentences: what the criterion required, what the record shows, and by when"
}
"""


def build_resolver_prompt(rec: dict, deadline: dt.date, today: str) -> str:
    f = prompt_facts(rec, deadline)
    return (f"{RESOLVER_TASK}\nToday is {today}. Everything up to today is fair game as evidence.\n\n"
            f"{'=' * 70}\n{_block(f)}{'=' * 70}\n\nAnswer with the JSON object now.\n")


# ---------------------------------------------------------------------------
# Stage 2: the prior assessor. It never learns the outcome.
# ---------------------------------------------------------------------------

PRIOR_TASK = """You are estimating how likely a prediction looked AT THE MOMENT IT WAS MADE.

You are NOT being asked what happened. Do not try to recall what happened, and do
not reason backwards from anything you may remember. The question is what a
well-informed observer, standing on the statement date with only what was public
THEN, should have believed.

PRICE THE DEADLINE, NOT JUST THE EVENT. This is the single most common way to get
this wrong. The claim is FALSE if the thing happens LATE. A product that shipped
eighteen months after the date named here did NOT satisfy this prediction, and your
p must be the probability that it happened BY the deadline, not the probability
that it happened at all. Announced hardware, launch dates, standards releases and
capability thresholds slip constantly, and the slip is usually the whole question.
If you would say "this will certainly happen eventually, but on that timetable it
is a coin flip", then p is the coin flip.

HOW TO THINK ABOUT IT

1. Put yourself on the statement date. Everything after it is unknown to you.
2. Name a reference class and its base rate. "Shipping dates announced at a
   keynote for the following quarter" and "a ten-year forecast about an entire
   industry" have very different hit rates, and the reference class is doing most
   of the work in your answer. Pick a class whose base rate is about hitting the
   DATE, not about the thing eventually existing.
3. Adjust for what was public on that date: the state of the technology, whether
   the thing was already announced or already underway, how far off the deadline
   was, and how demanding the threshold is.
4. Adjust for who is speaking. A chief executive announcing their OWN company's
   roadmap for next year decides it themselves and is usually right, so p is high.
   The same person forecasting a whole market ten years out controls nothing.
   Being able to decide it is not the same as being able to decide it ON TIME.

CALIBRATION ANCHORS, all of them about meeting the DEADLINE:
  0.90-0.95  already announced, already built, deadline near, speaker controls it
  0.70-0.85  on a public roadmap, normal execution risk
  0.45-0.65  a genuine toss-up; informed people disagreed at the time
  0.20-0.35  needs something to go right that usually does not
  0.05-0.15  a bold call against the consensus of the day

Give a real number. Do not park every answer at 0.5. Stay inside 0.01 to 0.99:
0 and 1 are claims of certainty and cannot be scored.

Answer with one JSON object and nothing else:

{
  "prediction_id": "<copy it back exactly>",
  "p": 0.35,
  "reference_class": "one line naming the class you priced against and its rough base rate",
  "reasoning": "two to four sentences, all of it reasoning available on the statement date"
}
"""


def build_prior_prompt(rec: dict, deadline: dt.date) -> str:
    """Blind by construction: it reads `prompt_facts`, which cannot see a resolution.

    There is deliberately no `today` argument. Telling this stage the current date
    invites it to reason forward to what it knows happened since.
    """
    f = prompt_facts(rec, deadline)
    return (f"{PRIOR_TASK}\n{'=' * 70}\n{_block(f)}{'=' * 70}\n\n"
            f"Stand on {f['statement_date']}. Answer with the JSON object now.\n")


# ---------------------------------------------------------------------------
# Validation of what came back
# ---------------------------------------------------------------------------

def validate_resolution(obj: dict, expect_id: str) -> list[str]:
    """Rules the schema cannot express. Each one is a way a resolution could be
    wrong while still being well-formed JSON."""
    errs: list[str] = []
    if obj.get("prediction_id") != expect_id:
        errs.append(f"prediction_id {obj.get('prediction_id')!r} != {expect_id!r}")
    outcome = obj.get("outcome")
    reason = obj.get("unresolvable_reason")
    sources = obj.get("sources") or []
    if outcome == "unresolvable":
        if reason is None:
            errs.append("outcome is unresolvable with no unresolvable_reason")
    else:
        if reason is not None:
            errs.append(f"outcome {outcome!r} carries unresolvable_reason {reason!r}")
        if not sources:
            errs.append(f"outcome {outcome!r} cites no source; a resolution without evidence is not one")
    return errs


def validate_prior(obj: dict, expect_id: str) -> list[str]:
    errs: list[str] = []
    if obj.get("prediction_id") != expect_id:
        errs.append(f"prediction_id {obj.get('prediction_id')!r} != {expect_id!r}")
    p = obj.get("p")
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        errs.append(f"p {p!r} is not a number")
    elif not (0.0 <= float(p) <= 1.0):
        errs.append(f"p {p} outside [0, 1]")
    return errs


# A prior prompt that leaked the answer would be invisible in the output, so the
# leak is checked on the PROMPT, before the call. These are the words a resolution
# would arrive in. Matched case-insensitively on word boundaries.
_LEAK_WORDS = ("occurred", "not_occurred", "unresolvable", "outcome", "actually happened",
               "in hindsight", "turned out", "as we now know", "did happen", "did not happen")
_LEAK_RE = re.compile("|".join(re.escape(w) for w in _LEAK_WORDS), re.I)


# The fields whose text is QUOTED rather than authored here. A speaker may say
# "the outcome" or "as it turned out" about something else entirely, and the
# pipeline's own criterion may contain "occurred" as ordinary English. None of
# that tells the assessor what happened to THIS prediction.
VERBATIM_FIELDS = ("quote", "context_before", "context_after", "claim", "criterion",
                   "title", "venue", "speaker", "role", "company", "target_date_text")


def prior_prompt_leaks(prompt: str, facts: dict | None = None) -> list[str]:
    """Words that would tell the prior stage what happened. Empty list means clean.

    Scans only the text THIS FILE writes. Pass `facts` from `prompt_facts` and the
    quoted material is removed before the scan, because a screen that reads the
    speaker's own words cannot separate "the outcome was obvious" said in 2014
    from an instruction telling the assessor how this prediction ended.

    MEASURED 2026-09-15: without the mask, 7 of 225 past-due records trip it, and
    all 7 are the word appearing inside a quote, a context window or the recorded
    criterion. Refusing those would have dropped seven real predictions to protect
    against a leak that was never there.

    The structural guarantee is separate and stronger: `build_prior_prompt` cannot
    reach a resolution at all, which `test_resolution_lib.py` proves by attaching
    one. This screen is the second line, over the wording.
    """
    if facts:
        for key in VERBATIM_FIELDS:
            value = facts.get(key)
            if value:
                prompt = prompt.replace(str(value), " ")
    return sorted({m.group(0).lower() for m in _LEAK_RE.finditer(prompt)})


# ---------------------------------------------------------------------------
# The sidecar records
# ---------------------------------------------------------------------------

def resolution_record(rec: dict, deadline: dt.date, obj: dict, *, run_id: str, harness: str,
                      account: str | None, telemetry: dict, resolved_at: str, as_of: str) -> dict:
    return {
        "prediction_id": rec["prediction_id"],
        "leader_slug": rec["leader_slug"],
        "transcript_id": rec["transcript_id"],
        "stage": "resolve",
        # A missing deadline SAYS so. The repair stage runs over records the funnel
        # could not date, and a placeholder date there would be read as a real one.
        "deadline": deadline.isoformat() if deadline else "(no closing date this pipeline could read)",
        "as_of": as_of,
        "outcome": obj["outcome"],
        "confidence": obj["confidence"],
        "sources": obj["sources"],
        "unresolvable_reason": obj["unresolvable_reason"],
        "reasoning": obj["reasoning"],
        "resolved_at_utc": resolved_at,
        "run_id": run_id,
        "harness": harness,
        "account": account,
        "telemetry": telemetry,
    }


def prior_record(rec: dict, deadline: dt.date, obj: dict, *, run_id: str, harness: str,
                 account: str | None, telemetry: dict, assessed_at: str, prompt_sha: str,
                 leaks: list[str]) -> dict:
    p_raw = float(obj["p"])
    return {
        "prediction_id": rec["prediction_id"],
        "leader_slug": rec["leader_slug"],
        "transcript_id": rec["transcript_id"],
        "stage": "prior",
        # A missing deadline SAYS so. The repair stage runs over records the funnel
        # could not date, and a placeholder date there would be read as a real one.
        "deadline": deadline.isoformat() if deadline else "(no closing date this pipeline could read)",
        "p": min(max(p_raw, P_MIN), P_MAX),
        "p_raw": p_raw,
        "clamped": not (P_MIN <= p_raw <= P_MAX),
        "reference_class": obj["reference_class"],
        "reasoning": obj["reasoning"],
        # Proof of what this stage was shown. The hash pins the prompt and the
        # screen records that it carried no outcome vocabulary.
        "prompt_sha256": prompt_sha,
        "prompt_leak_words": leaks,
        "assessed_at_utc": assessed_at,
        "run_id": run_id,
        "harness": harness,
        "account": account,
        "telemetry": telemetry,
    }


def sidecar_path(root: Path, stage: str, slug: str, prediction_id: str) -> Path:
    if stage not in ("resolve", "prior"):
        raise ValueError(f"unknown stage {stage!r}")
    return root / ("resolutions" if stage == "resolve" else "priors") / slug / f"{prediction_id}.json"


def load_sidecars(root: Path, stage: str) -> dict[str, dict]:
    """Every sidecar of a stage, keyed by prediction_id. Raises on a duplicate id
    rather than letting one silently win."""
    out: dict[str, dict] = {}
    sub = root / ("resolutions" if stage == "resolve" else "priors")
    if not sub.exists():
        return out
    for f in sorted(sub.glob("*/*.json")):
        obj = json.loads(f.read_text())
        pid = obj["prediction_id"]
        if pid in out:
            raise ValueError(f"duplicate {stage} sidecar for {pid}: {f}")
        out[pid] = obj
    return out


# ---------------------------------------------------------------------------
# Stage 0: repairing a criterion that no resolver could act on
# ---------------------------------------------------------------------------
#
# `docs/PREDICTIONS-CRITERIA-AGREEMENT.md` found 26 records carrying a criterion a
# resolver would act on incorrectly: 18 state no direction to test ("X will / will
# not happen") and 8 state the OPPOSITE of what the speaker said, so resolving them
# scores the speaker backwards. Both trace to one line of the old ELIGIBILITY.md
# G2, which was repaired in `cfec9e6`. That fix governs future extractions only.
# The records already on disk still carry the broken text, so they are repaired
# here, against the QUOTE, which is the thing that cannot be wrong.
#
# The repair is an OVERLAY, never an edit of the record. This clone may only write
# under `data/predictions/_experiments/`, and a record edited in place would also
# invalidate the extraction contract hash that the record carries.

REPAIR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prediction_id", "verdict", "criterion", "reasoning"],
    "properties": {
        "prediction_id": {"type": "string", "minLength": 1},
        "verdict": {"enum": ["already_correct", "repaired", "cannot_repair"]},
        "criterion": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
        "reasoning": {"type": "string", "minLength": 1},
    },
}

REPAIR_TASK = """A resolution criterion is the sentence a later reader tests to decide
whether a prediction came true. Some criteria in this corpus were written under a
specification that allowed two mistakes, and you are fixing one record.

THE TWO RULES A CRITERION MUST FOLLOW

1. STATE ONE DIRECTION. The criterion asserts what happens. It must never offer a
   choice. "Apple will / will not ship the product by 2020" is unresolvable,
   because both answers satisfy it. Rewrite it to assert the thing the speaker
   actually claimed.

2. TRUE MEANS THE SPEAKER WAS RIGHT. The criterion states the SPEAKER'S predicted
   outcome, never its falsification. If the speaker said "machines will not surpass
   humans within ten years", the criterion is "By <date>, machines will NOT have
   surpassed humans", keeping the speaker's negation. Do not flip it into the
   thing that would prove the speaker wrong.

THE QUOTE IS THE AUTHORITY. The claim and the criterion below were both written by
earlier stages of this pipeline and either may be wrong. When they disagree with
the quote, the quote wins.

ANSWER
  "already_correct" if the criterion follows both rules as written. Say so rather
    than rewriting it for style; an unnecessary rewrite is a change to the corpus.
  "repaired" with the corrected criterion. Keep the deadline and any numeric
    threshold exactly as they are. Change only the direction and the polarity.
  "cannot_repair" with criterion null, if the quote does not support any single
    testable direction.

Answer with one JSON object and nothing else:

{
  "prediction_id": "<copy it back exactly>",
  "verdict": "already_correct" | "repaired" | "cannot_repair",
  "criterion": "the criterion to use, or null for cannot_repair",
  "reasoning": "one to three sentences: which rule was broken, and what the quote supports"
}
"""


def build_repair_prompt(rec: dict, deadline: "dt.date | None", verifier_criterion: str,
                        flags: list[str]) -> str:
    f = prompt_facts(rec, deadline)
    return (f"""{REPAIR_TASK}
{'=' * 70}
{_block(f)}
A second model, checking the same quote, wrote this criterion instead:
  {verifier_criterion or "(none recorded)"}

A mechanical screen flagged this record for: {", ".join(flags)}
{'=' * 70}

Answer with the JSON object now.
""")


def validate_repair(obj: dict, expect_id: str) -> list[str]:
    errs: list[str] = []
    if obj.get("prediction_id") != expect_id:
        errs.append(f"prediction_id {obj.get('prediction_id')!r} != {expect_id!r}")
    verdict, crit = obj.get("verdict"), obj.get("criterion")
    if verdict == "cannot_repair":
        if crit is not None:
            errs.append("cannot_repair must carry a null criterion")
    elif not (isinstance(crit, str) and crit.strip()):
        errs.append(f"verdict {verdict!r} needs a criterion")
    elif UNDIRECTED_RE.search(crit):
        # The one defect this stage exists to remove may not survive it, under
        # EITHER verdict. An earlier version checked only "repaired", so a model
        # could wave an undirected criterion through as "already_correct" and the
        # stage would report a clean run over a criterion nothing can resolve.
        errs.append(f"verdict {verdict!r} leaves the criterion undirected: {crit[:120]!r}")
    return errs


# Same pattern as scripts/test_criterion_spec.py. `\s+` throughout, because the
# first version of that test used a literal space and PASSED against the very
# specification it was written to catch, where the phrase wrapped across a line.
UNDIRECTED_RE = re.compile(r"will\s*/\s*will\s+not|will\s+not\s*/\s*will|will\s+or\s+will\s+not", re.I)


def load_repairs(root: Path) -> dict[str, dict]:
    """Repaired criteria by prediction_id. Only a "repaired" verdict overlays anything."""
    out: dict[str, dict] = {}
    sub = root / "criteria_repairs"
    if not sub.exists():
        return out
    for fp in sorted(sub.glob("*/*.json")):
        obj = json.loads(fp.read_text())
        pid = obj["prediction_id"]
        if pid in out:
            raise ValueError(f"duplicate repair for {pid}: {fp}")
        out[pid] = obj
    return out


def apply_repairs(rows: list[dict], repairs: dict[str, dict]) -> tuple[int, int]:
    """Overlay repaired criteria onto records in memory. Returns (applied, unrepairable).

    The original text is kept at `prediction.resolution_criteria_original`, so a
    reader of any sidecar can see what the resolver was shown AND what it replaced.
    """
    applied = unrepairable = 0
    for r in rows:
        rep = repairs.get(r["prediction_id"])
        if not rep:
            continue
        if rep["verdict"] == "repaired":
            r["prediction"]["resolution_criteria_original"] = r["prediction"]["resolution_criteria"]
            r["prediction"]["resolution_criteria"] = rep["criterion"]
            applied += 1
        elif rep["verdict"] == "cannot_repair":
            r["_unrepairable"] = True
            unrepairable += 1
    return applied, unrepairable
