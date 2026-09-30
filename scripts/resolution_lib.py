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

SOURCES_SCHEMA = {
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
}

# The searches a resolution ran, in order. Required for EVERY outcome (critique 1
# point 6 of the rescue round-4 design: the effort floor must not bind only the
# refusals, which were already the most searched answers).
SEARCHED_SCHEMA = {"type": "array", "items": {"type": "string", "minLength": 1}}
MIN_SEARCHES = 3

# "Already public before the statement" (operator, 2026-09-29): the earliest
# report, dated on or before the statement date, that the event had happened or
# been agreed, decided or scheduled. The field names are pinned: a live smoke
# eval reads them.
ALREADY_PUBLIC_SCHEMA = {"anyOf": [{"type": "null"}, {
    "type": "object", "additionalProperties": False, "required": ["date", "where", "what_it_shows"],
    "properties": {"date": {"type": "string", "minLength": 1}, "where": {"type": "string", "minLength": 1},
                   "what_it_shows": {"type": "string", "minLength": 1}}}]}

RESOLUTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prediction_id", "outcome", "confidence", "reasoning", "sources", "unresolvable_reason",
                 "searched", "already_public"],
    "properties": {
        "prediction_id": {"type": "string", "minLength": 1},
        "outcome": {"enum": list(OUTCOMES)},
        "confidence": {"enum": ["high", "medium", "low"]},
        "reasoning": {"type": "string", "minLength": 1},
        "unresolvable_reason": {"anyOf": [{"enum": list(UNRESOLVABLE_REASONS)}, {"type": "null"}]},
        "sources": SOURCES_SCHEMA,
        "searched": SEARCHED_SCHEMA,
        "already_public": ALREADY_PUBLIC_SCHEMA,
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
        # The first day of a date range, when the record carries one; shown on the Said line.
        "statement_date_earliest": src.get("statement_date_earliest") or "",
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
        # Says where the deadline came from, because rule 7 turns on it: a TREND
        # window is this pipeline's evaluation span, not something the speaker said.
        # An IMPLIED window points at the judged block, which both prompts carry,
        # never at a rule number only the resolver has (critique 3 E3).
        "deadline_note": (
            "-- THIS IS A TREND WINDOW, not a date the speaker gave. See rule 7."
            if str(rec.get("_basis") or "").startswith("trend")
            else "-- an implied window of %s, not a date the speaker gave; see HOW THIS RECORD IS JUDGED"
            % rec["_implied"]["window_words"] if rec.get("_implied")
            else '(from the speaker\'s own wording: "%s")' % (pred.get("target_date_text") or "")),
        "target_date_text": pred.get("target_date_text") or "",
        "category": pred.get("category") or "",
        # Authored here, from the record's own fields, and identical in every stage
        # that reads prompt_facts. Empty for a record with no trigger.
        "judged": judged_block(rec),
    }


# ---------------------------------------------------------------------------
# How this record is judged: one block, in every stage's prompt
# ---------------------------------------------------------------------------
#
# Critique 1 point 12 of the rescue round-4 design: rules the resolver applies
# (a tolerance for "about", a fiscal year, a stated pace, an imposed window) must
# reach the prior too, or the prior prices one question and the resolver settles
# another, which is how a 2021 genome-cost claim priced at p=0.02 was paid +5.64
# (PRIOR_TREND_RULE). Each rule below is triggered by the record's own fields,
# never by anything a stage found, and the resulting text sits verbatim in the
# resolver, prior and early prompts. A record with no trigger gets no block, so
# its prior prompt is byte-identical to the one existing priors were priced with.
# Every text is authored, so none may carry outcome vocabulary (prior_prompt_leaks).

_NUM = (r"(?:\$|US\$|€|£)?(?:\d|one\b|two\b|three\b|four\b|five\b|six\b|seven\b|eight\b|nine\b|ten\b|twenty\b|"
        r"thirty\b|forty\b|fifty\b|a hundred|a thousand|a million|a billion|half\b|a third|a quarter)")
_FIGURE = (r"\b(?:revenue|revenues|sales|profit|profits|profitable|profitability|margin|margins|earnings|income|"
           r"EBITDA|cash flow|growth|GDP|bookings|shipments|deliveries|share of)\b")
JUDGED_RULES = {
    "implied": {
        "text": ("AN IMPLIED WINDOW. The speaker named no date. This pipeline judges the claim over a fixed "
                 "window of {window} from the statement date to the deadline shown, set by a table fixed "
                 "before any record was judged ({why}). The claim holds only if the thing comes about within "
                 "that window; the same thing coming about after the deadline does not count. Judge it, and "
                 "price it, within the window, not eventually."),
    },
    "approximate": {
        "fields": ["claim", "criterion"],
        "pattern": (r"\b(?:about|around|roughly|approximately|almost|nearly|close to|some)\s+" + _NUM
                    + r"|\ba couple\b|\b(?:hundreds|thousands|dozens)\b"),
        "text": ("APPROXIMATE NUMBERS. When the claim names an approximate number: 'about', 'around', "
                 "'roughly' and 'approximately' X are met within 10% of X; 'almost' or 'nearly' X is met from "
                 "90% of X up to X; 'a couple' means two; 'hundreds' means 200 or more. Another tolerance "
                 "applies only where the speaker's own words set one."),
    },
    "pace": {
        "fields": ["claim", "criterion", "target_date_text"],
        "pattern": (r"\b(?:(?:per|each|every)\s+(?:day|week|month|quarter)|a (?:day|week)\b|daily|weekly|"
                    r"at a (?:rate|pace) of)"),
        "text": ("A STATED PACE OR SCHEDULE. When the speaker states a pace or a schedule ('ten more each day "
                 "until all 50 are out'), the pace is part of the claim: it holds only if the schedule held, "
                 "not merely the end state. Everything released at once, early or late, meets the end state "
                 "and breaks the schedule."),
    },
    "period": {
        "fields": ["claim", "criterion"],
        "pattern": (r"(?=[\s\S]*" + _FIGURE + r")[\s\S]*\b(?:fiscal|FY\s?'?\d{2,4}|full[- ]year|annual|"
                    r"quarter(?:ly)?|Q[1-4]|(?:for|in|during) (?:calendar |fiscal )?(?:the year )?(?:19|20)\d\d)\b"),
        "text": ("A FIGURE FOR A PERIOD. When the claim is about a figure for a period (a year, a fiscal year, "
                 "a quarter), it is judged on the figure for the latest such period that ends on or before the "
                 "deadline, whenever that figure is published. A figure published after the deadline still "
                 "counts; a later period's figure does not."),
    },
    "fiscal": {
        "control": "own", "category": "company_business", "figure": _FIGURE,
        "horizon": r"\b(?:this year|next year|fiscal|FY)\b",
        "text": ("A COMPANY'S FISCAL YEAR. The speaker runs the company and the claim is about its own reported "
                 "figures, so 'this year' and 'next year' mean the fiscal year the company reports on, which "
                 "may not end in December. The deadline shown may be a calendar-year stand-in for those words; "
                 "the fiscal year the speaker meant is the period judged, and the reasoning names it and when "
                 "it ended."),
    },
}
_JUDGED_RE = {k: re.compile(v["pattern"], re.I) for k, v in JUDGED_RULES.items() if "pattern" in v}


def judged_block(rec: dict) -> str:
    """The HOW THIS RECORD IS JUDGED text for one record, or '' when no rule applies.

    Pure: reads the record's own fields and `_implied`, the implied-window row
    phase2_resolvability.attach_deadlines set, and nothing a stage wrote.
    """
    pred, src = rec.get("prediction") or {}, rec.get("source") or {}
    fields = {"claim": pred.get("normalized_claim") or "", "criterion": pred.get("resolution_criteria") or "",
              "target_date_text": pred.get("target_date_text") or "", "quote": src.get("quote") or ""}
    out = []
    imp = rec.get("_implied")
    if imp:
        row = imp["row"]
        why = (f"from the speaker's words '{imp['matched']}'" if imp.get("matched")
               else "the claim is about " + row.split(": ", 1)[1])
        out.append(JUDGED_RULES["implied"]["text"].format(window=imp["window_words"], why=why))
    for key in ("approximate", "pace", "period"):
        if any(_JUDGED_RE[key].search(fields[f]) for f in JUDGED_RULES[key]["fields"]):
            out.append(JUDGED_RULES[key]["text"])
    fy = JUDGED_RULES["fiscal"]
    if (pred.get("subject_control") == fy["control"] and pred.get("category") == fy["category"]
            and re.search(fy["figure"], fields["claim"] + " " + fields["criterion"], re.I)
            and (re.search(fy["horizon"], fields["target_date_text"], re.I)
                 or re.fullmatch(r"\d{4}", str(pred.get("target_date") or "")))):
        out.append(fy["text"])
    return "".join(f"  - {t}\n" for t in out)


def _block(f: dict) -> str:
    """The shared description of one prediction. Identical text in both prompts,
    so the two stages are reading the same claim and any difference in their
    answers is the stage rather than the wording. The HOW THIS RECORD IS JUDGED
    section is appended only when a rule applies, so a record with none reads
    exactly as before 2026-09-29."""
    return _block_body(f) + (f"\nHOW THIS RECORD IS JUDGED\n{f['judged']}" if f.get("judged") else "")


def _said(f: dict) -> str:
    first = f.get("statement_date_earliest")
    if first and first != f["statement_date"]:
        return f"between {first} and {f['statement_date']}"
    return f["statement_date"]


def _block_body(f: dict) -> str:
    who = ", ".join(x for x in (f["role"], f["company"]) if x)
    return f"""PREDICTION {f["prediction_id"]}

Speaker:         {f["speaker"]}{f" ({who})" if who else ""}
Said on:         {_said(f)}
Where:           {f["title"]}{f" [{f['venue']}]" if f["venue"] else ""}
Deadline:        {f["deadline"]}   {f["deadline_note"]}
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

# Rules 2, 3, 5 and 7 are unchanged from the first release. Rule 1 is design
# section 3.3; rules 4 and 6 are section 3.4 with critique 1 point 6 applied (the
# effort floor binds every outcome, and no sentence tells the resolver what a
# refusal does to a score); rule 8 is the operator's "already public" check
# (2026-09-29); rule 9 points at the judged block the prior reads too. The old
# rule 6, a company's fiscal year, is now the "fiscal" judged rule, so the prior
# sees it (critique 1 point 12). Rule 7 keeps its number because the shared
# deadline note of a trend record names it.
RESOLVER_TASK = """You are resolving a dated public prediction. Decide whether the thing
described by the resolution criterion actually happened by the deadline.

RULES

1. THE DEADLINE BOUNDS THE EVENT, NOT THE EVIDENCE. Answer "occurred" only if the
   thing the criterion describes happened ON OR BEFORE the deadline. Evidence may
   be published at any time up to today: a report, filing or letter published
   after the deadline settles the claim when what it reports happened on or before
   the deadline. A criterion worded "by <date>, X will report ..." about a period's
   figure means the period, not the date of the report; resolve it on the figure.
   Something that happened after the deadline did NOT occur; say "not_occurred"
   and give the real date in your reasoning.

2. The criterion states the SPEAKER'S predicted outcome. "occurred" means the
   speaker was RIGHT. If the criterion carries a negation, such as "will not have
   surpassed", then "occurred" means the thing indeed did not happen.

3. CITE SOMETHING for every resolution. Each source needs what it shows, where it
   is (a URL, or a specific named document, filing, release or report), and its
   date. A resolution with no source is not a resolution. If you have web search,
   use it; work from public record, not from impression.

4. "unresolvable" is correct when the public record truly cannot settle the claim.
   Before you answer "no_public_evidence" or "threshold_unmeasurable", check whether
   a published adjacent figure settles the question anyway: a full-year figure, the
   company's own guidance range, a count reported just after the deadline. Name one
   of these reasons:
     - no_public_evidence: nothing public settles it either way
     - criterion_ambiguous: the criterion has two readings that disagree
     - criterion_undirected: the criterion states no direction to test, for
       example "X will or will not happen"
     - threshold_unmeasurable: the number named is not publicly reported
     - deadline_incoherent: the deadline precedes the statement, or makes no sense
     - after_knowledge_cutoff: the window closed too recently for a public record
   Do not guess, and do not refuse where the evidence exists.

5. "confidence" is about the RESOLUTION, not about the prediction. Use "high" when
   a cited source settles it directly, "medium" when it follows from cited sources
   by a short step, "low" when you are reading between the lines.

6. SEARCH BEFORE YOU ANSWER, WHATEVER THE ANSWER. Run at least three web searches
   with different queries before you answer, and list every query you ran in
   "searched", in the order you ran them, copied exactly as you ran it. Opening a
   page is not a search. Where the claim is about a company,
   include its own filings, releases and reports, and news dated near the deadline.
   This holds for every answer: "occurred" needs a source that shows the event, or
   the period's figure, on or before the deadline; "not_occurred" needs a source
   that shows it did not happen, or searches that would have found it had it
   happened; "unresolvable" needs the searches that failed to settle it.

7. SOME CLAIMS ARE A DIRECTION OVER A WINDOW, NOT AN EVENT BY A DATE. If the
   deadline line says THIS IS A TREND WINDOW, the speaker named no closing date,
   and the question is different: over the time that has elapsed since they
   spoke, did the direction they claimed actually hold? Judge the overall trend
   rather than a single moment. "Margin will only continue to go up", said four
   years ago, is TRUE if margin is meaningfully higher across that span and FALSE
   if it is flat or lower; one weak quarter does not decide it. Give the value
   near the statement and the value now, and cite both. Answer "unresolvable" if
   the quantity is not publicly reported across the window.

8. ALREADY PUBLIC BEFORE IT WAS SAID. Check whether the event itself, or a credible
   report that it had been agreed, decided or scheduled, was already public BEFORE
   the statement date. If it was, fill "already_public" with the earliest such
   source: its date, which is strictly before the statement date (before the first
   day, when the Said line gives a range), where it is, and what it shows. A report
   dated the same day does not count. A rumour, or another person's forecast, is not
   enough; a report that the deal was agreed, the product announced or the date set
   is. Still answer the outcome as usual. If you find no such report, "already_public"
   is null.

9. HOW THIS RECORD IS JUDGED. When the prediction below carries a section with that
   heading, apply it exactly. The assessor who estimated the prediction's
   likelihood read the same section.

Answer with one JSON object and nothing else:

{
  "prediction_id": "<copy it back exactly>",
  "outcome": "occurred" | "not_occurred" | "unresolvable",
  "confidence": "high" | "medium" | "low",
  "sources": [{"what_it_shows": "...", "where": "...", "date": "YYYY-MM-DD or null"}],
  "searched": ["the first query you ran", "the second", "the third", "..."],
  "already_public": null or {"date": "YYYY-MM-DD", "where": "...", "what_it_shows": "..."},
  "unresolvable_reason": null or one of the reasons named in rule 4,
  "reasoning": "two to five sentences: what the criterion required, what the record shows, and by when"
}
"""


def build_resolver_prompt(rec: dict, deadline: dt.date, today: str) -> str:
    f = prompt_facts(rec, deadline)
    return (f"{RESOLVER_TASK}\nToday is {today}. Everything up to today is fair game as evidence.\n\n"
            f"{'=' * 70}\n{_block(f)}{'=' * 70}\n\nAnswer with the JSON object now.\n")


# ---------------------------------------------------------------------------
# Stage 1b: the early call, before the deadline (VD-5 (c), operator 2026-09-29)
# ---------------------------------------------------------------------------
#
# "As Bayesian as possible": a prediction already settled before its deadline
# scores NOW, in both directions. Occurred when a dated source shows the
# criterion already met; not_occurred when it can no longer happen, or when the
# subject itself has publicly moved its own target past the deadline. Everything
# else is still_open. The scorer queues every early call for a fresh resolution
# at the deadline, which replaces it (score_predictions), so neither direction
# gets two looks (critique 1 point 9). The prior is the at-deadline prior, byte
# for byte: build_prior_prompt never reads anything early.

EARLY_OUTCOMES = ("occurred", "not_occurred", "still_open")
EARLY_BASES = ("cannot_happen", "target_moved")

EARLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prediction_id", "outcome", "not_occurred_basis", "confidence", "sources", "searched",
                 "already_public", "reasoning"],
    "properties": {
        "prediction_id": {"type": "string", "minLength": 1},
        "outcome": {"enum": list(EARLY_OUTCOMES)},
        "not_occurred_basis": {"anyOf": [{"enum": list(EARLY_BASES)}, {"type": "null"}]},
        "confidence": {"enum": ["high", "medium", "low"]},
        "sources": SOURCES_SCHEMA,
        "searched": SEARCHED_SCHEMA,
        "already_public": ALREADY_PUBLIC_SCHEMA,
        "reasoning": {"type": "string", "minLength": 1},
    },
}

EARLY_TASK = """You are checking a dated public prediction BEFORE its deadline. The deadline
has NOT passed. Decide only whether the claim is ALREADY settled.

RULES

1. Answer "occurred" only if a cited source, dated after the statement date and on
   or before today, shows that the thing the criterion describes has already
   happened, in full. A claim about a state AT the deadline (a price, a count or a
   share at the end of a period) is not settled because it holds today: the time
   left can still undo it, so answer "still_open".

2. Answer "not_occurred" only in one of two cases, and name which one in
   "not_occurred_basis":
     - "cannot_happen": a cited source shows it can no longer happen by the
       deadline: the event it names has taken place with another result, the
       thing was cancelled, or a law or a physical fact now rules it out. A low
       probability is not enough.
     - "target_moved": the subject of the claim itself, the company or the person
       the claim is about, has publicly moved its own target or schedule past the
       deadline, shown by a cited source dated after the statement date. Doubts
       voiced by others are not enough; the subject's own statement or filing is.

3. Answer "still_open" in every other case. This is the normal answer. When you
   answer it, "not_occurred_basis" is null and no source is needed.

4. The criterion states the SPEAKER'S predicted outcome. "occurred" means the
   speaker was RIGHT. If the criterion carries a negation, "occurred" means the
   thing indeed did not happen.

5. CITE SOMETHING for "occurred" and "not_occurred": what each source shows, where
   it is (a URL, or a specific named document, filing, release or report), and its
   date. Work from the public record, not from impression.

6. SEARCH BEFORE YOU ANSWER, WHATEVER THE ANSWER. Run at least three web searches
   with different queries before you answer, and list every query you ran in
   "searched", in the order you ran them, copied exactly as you ran it. Opening a
   page is not a search.

7. ALREADY PUBLIC BEFORE IT WAS SAID. Check whether the event itself, or a credible
   report that it had been agreed, decided or scheduled, was already public BEFORE
   the statement date. If it was, fill "already_public" with the earliest such
   source: its date, which is strictly before the statement date (before the first
   day, when the Said line gives a range), where it is, and what it shows. A report
   dated the same day does not count. Otherwise "already_public" is null.

8. HOW THIS RECORD IS JUDGED. When the prediction below carries a section with that
   heading, apply it exactly.

9. "confidence" is about your answer: "high" when a cited source settles it
   directly, "medium" when it follows by a short step, "low" otherwise.

Answer with one JSON object and nothing else:

{
  "prediction_id": "<copy it back exactly>",
  "outcome": "occurred" | "not_occurred" | "still_open",
  "not_occurred_basis": null | "cannot_happen" | "target_moved",
  "confidence": "high" | "medium" | "low",
  "sources": [{"what_it_shows": "...", "where": "...", "date": "YYYY-MM-DD or null"}],
  "searched": ["the first query you ran", "the second", "the third", "..."],
  "already_public": null or {"date": "YYYY-MM-DD", "where": "...", "what_it_shows": "..."},
  "reasoning": "two to five sentences: what the criterion requires, what is already on the record, and why that settles it or not"
}
"""


def build_early_prompt(rec: dict, deadline: dt.date, today: str) -> str:
    f = prompt_facts(rec, deadline)
    return (f"{EARLY_TASK}\nToday is {today}. The deadline is {f['deadline']}, which has not passed.\n\n"
            f"{'=' * 70}\n{_block(f)}{'=' * 70}\n\nAnswer with the JSON object now.\n")


def validate_early(obj: dict, expect_id: str, said: "str | None", today: str,
                   earliest: "str | None" = None) -> list[str]:
    """Rules the schema cannot express for an early call. A decided answer needs a
    source dated after the statement and on or before today, and a not_occurred
    names its basis; still_open names none. `earliest` is statement_bound(rec),
    the day an already_public report must precede; it defaults to `said`."""
    errs: list[str] = []
    if obj.get("prediction_id") != expect_id:
        errs.append(f"prediction_id {obj.get('prediction_id')!r} != {expect_id!r}")
    outcome, basis = obj.get("outcome"), obj.get("not_occurred_basis")
    if outcome == "not_occurred" and basis not in EARLY_BASES:
        errs.append(f"not_occurred needs not_occurred_basis in {list(EARLY_BASES)}, has {basis!r}")
    if outcome != "not_occurred" and basis is not None:
        errs.append(f"outcome {outcome!r} carries not_occurred_basis {basis!r}")
    if outcome in ("occurred", "not_occurred"):
        if not said:
            errs.append("an early call needs the record's statement date, and it has none")
        else:
            lo, hi = dt.date.fromisoformat(str(said)[:10]), dt.date.fromisoformat(today)
            dated = []
            for s in obj.get("sources") or []:
                try:
                    dated.append(dt.date.fromisoformat(str(s.get("date"))[:10]))
                except ValueError:
                    continue
            if not any(lo < x <= hi for x in dated):
                errs.append(f"an early {outcome} needs a source dated after the statement date {lo} and on or "
                            f"before today {hi}; the dates cited are {[str(x) for x in dated] or 'none'}")
    errs += _searched_errors(obj)
    errs += already_public_errors(obj, earliest if earliest is not None else said)
    return errs


def early_record(rec: dict, deadline: dt.date, obj: dict, *, run_id: str, harness: str, account: str | None,
                 telemetry: dict, checked_at: str, as_of: str, prompt_sha: str, release: str,
                 code_revision: str) -> dict:
    return {
        "policy_release": release, "prompt_sha256": prompt_sha, "code_revision": code_revision,
        "prediction_id": rec["prediction_id"], "leader_slug": rec["leader_slug"],
        "transcript_id": rec["transcript_id"], "stage": "early",
        "statement_date": (rec.get("source") or {}).get("statement_date"),
        "statement_date_basis": (rec.get("source") or {}).get("statement_date_basis"),
        # The FULL window: the fresh check at the deadline judges this same one.
        "deadline": deadline.isoformat(), "as_of": as_of,
        "outcome": obj["outcome"], "not_occurred_basis": obj["not_occurred_basis"],
        "early_called": obj["outcome"] != "still_open",
        "confidence": obj["confidence"], "sources": obj["sources"], "searched": obj["searched"],
        "already_public": obj["already_public"], "reasoning": obj["reasoning"],
        "checked_at_utc": checked_at, "run_id": run_id, "harness": harness, "account": account,
        "telemetry": telemetry,
    }


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


# Appended to PRIOR_TASK for a TREND record only, so every other prior prompt is
# byte-identical to the one the existing priors were priced with. It states the
# resolver's rule 7 from the prior's side. Without it the two stages price
# different events: FOUND 2026-09-27, a 2021 claim that genome sequencing would
# fall to ten cents was priced at p=0.02 for the endpoint and resolved "occurred"
# on the direction, paying +5.64 points. `test_prior_trend_alignment.py`.
PRIOR_TREND_RULE = """
THIS RECORD IS JUDGED OVER A TREND WINDOW. PRICE THE DIRECTION, NOT THE ENDPOINT.
The speaker named no closing date. This pipeline judges the claim over the window
from the statement date to the deadline shown, and the question it will be judged
on is: over that window, does the DIRECTION the speaker claimed hold? A claim that
a cost "will fall to ten cents" is judged on whether the cost falls meaningfully
across the window, not whether the literal endpoint is reached inside it. A claim
that a margin "will only continue to go up" is judged on whether it is
meaningfully higher across the window, and one weak quarter does not decide it.
So p is the probability, seen from the statement date, that the claimed direction
holds meaningfully over the whole window. Where the direction and the endpoint are
the same thing, price that thing.
"""


def build_prior_prompt(rec: dict, deadline: dt.date) -> str:
    """Blind by construction: it reads `prompt_facts`, which cannot see a resolution.

    There is deliberately no `today` argument. Telling this stage the current date
    invites it to reason forward to what it knows happened since.
    """
    f = prompt_facts(rec, deadline)
    task = PRIOR_TASK + (PRIOR_TREND_RULE if str(rec.get("_basis") or "").startswith("trend") else "")
    return (f"{task}\n{'=' * 70}\n{_block(f)}{'=' * 70}\n\n"
            f"Stand on {f['statement_date']}. Answer with the JSON object now.\n")


# ---------------------------------------------------------------------------
# Stage 3: forecast or announcement, under the lead floor (VD-7 (c))
# ---------------------------------------------------------------------------
#
# The operator's call, 2026-09-29: a record said less than MIN_LEAD_DAYS before
# its own deadline is scorable only when it is a FORECAST, about the world or
# about the speaker's own organisation's RESULTS (numbers it does not directly
# control). An announcement of the speaker's own plans or schedule, and a relay
# of someone else's already-published schedule, stay out. The label is
# OUTCOME-BLIND, like the prior: it reads prompt_facts, which cannot reach a
# resolution, runs on the no-tools harness, and the same leak screen applies.

LEAD_TEST_LABELS = ("world_forecast", "own_results_forecast", "own_plan_announcement", "relay")
FORECAST_LABELS = ("world_forecast", "own_results_forecast")

LEAD_TEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prediction_id", "label", "reason"],
    "properties": {
        "prediction_id": {"type": "string", "minLength": 1},
        "label": {"enum": list(LEAD_TEST_LABELS)},
        "reason": {"type": "string", "minLength": 1},
    },
}

LEAD_TEST_TASK = """FORECAST OR ANNOUNCEMENT. You are sorting one statement into a kind. You are
NOT asked whether it came true. Do not try to recall what happened after it was
said; read only what was said, who said it and when.

This statement is here because its timing does not show whether it is a
forecast. Either the date it names falls soon after it was said, or it names no
date and only its words set a window, as the Deadline line below says. A
statement like that can be an announcement of the speaker's own plan, which is
not a forecast, or a real forecast. Decide which kind it is.

KINDS

  "world_forecast"         a forecast about something outside the speaker's own
                           organisation: markets, the economy, an election, a
                           technology in general, another company, a policy.
  "own_results_forecast"   a forecast of the speaker's OWN organisation's results
                           that customers, markets or competitors decide, not the
                           organisation itself: revenue, profit, cash flow,
                           volume, sign-ups, market share, a ranking.
  "own_plan_announcement"  the speaker's own organisation, or the speaker in
                           person, has decided the thing, and the statement says
                           when it happens: a launch, a release, a rollout, an
                           event, a publication, a hire, a trip, a talk, a
                           schedule. Whether it happens is a decision the speaker's
                           side makes.
  "relay"                  someone else's already-published plan or schedule,
                           repeated by the speaker: a rival's launch date, a
                           conference agenda, a government's announced timetable.

When a statement mixes kinds, choose by the part the resolution criterion tests.
Between an announcement and a forecast of the speaker's own organisation, ask
whether the organisation can simply make it happen on that date. If it can, it is
an announcement.

Answer with one JSON object and nothing else:

{
  "prediction_id": "<copy it back exactly>",
  "label": "world_forecast" | "own_results_forecast" | "own_plan_announcement" | "relay",
  "reason": "one or two sentences naming what in the statement decides the kind"
}
"""


def build_lead_test_prompt(rec: dict, deadline: dt.date) -> str:
    """Blind like the prior: prompt_facts cannot reach a resolution, and there is no today."""
    f = prompt_facts(rec, deadline)
    return f"{LEAD_TEST_TASK}\n{'=' * 70}\n{_block(f)}{'=' * 70}\n\nAnswer with the JSON object now.\n"


def validate_lead_test(obj: dict, expect_id: str) -> list[str]:
    errs = []
    if obj.get("prediction_id") != expect_id:
        errs.append(f"prediction_id {obj.get('prediction_id')!r} != {expect_id!r}")
    if not str(obj.get("reason") or "").strip():
        errs.append("a label needs its reason")
    return errs


def lead_test_record(rec: dict, deadline: dt.date, obj: dict, *, run_id: str, harness: str, account: str | None,
                     telemetry: dict, labelled_at: str, prompt_sha: str, leaks: list[str], release: str,
                     code_revision: str) -> dict:
    return {
        "policy_release": release, "prompt_sha256": prompt_sha, "prompt_leak_words": leaks,
        "code_revision": code_revision, "prediction_id": rec["prediction_id"], "leader_slug": rec["leader_slug"],
        "transcript_id": rec["transcript_id"], "stage": "lead_test",
        "statement_date": (rec.get("source") or {}).get("statement_date"),
        "statement_date_basis": (rec.get("source") or {}).get("statement_date_basis"),
        "deadline": deadline.isoformat(), "label": obj["label"], "reason": obj["reason"],
        "labelled_at_utc": labelled_at, "run_id": run_id, "harness": harness, "account": account,
        "telemetry": telemetry,
    }


# ---------------------------------------------------------------------------
# Validation of what came back
# ---------------------------------------------------------------------------

def _searched_errors(obj: dict) -> list[str]:
    """The effort floor, for EVERY outcome: at least MIN_SEARCHES distinct queries listed."""
    listed = obj.get("searched")
    if not isinstance(listed, list):
        return [f"searched is {listed!r}, not a list of the queries run"]
    distinct = {normalise_query(q) for q in listed if normalise_query(q)}
    if len(distinct) < MIN_SEARCHES:
        return [f"searched lists {len(distinct)} distinct queries; every outcome needs at least {MIN_SEARCHES}"]
    return []


def statement_bound(rec: dict) -> "str | None":
    """The day an `already_public` report must come strictly before: the FIRST day of
    the record's date range when it carries one (statement_date_earliest, which the
    dating work adds), else its statement date. A malformed first day is refused."""
    src = rec.get("source") or {}
    first = src.get("statement_date_earliest")
    if first is None:
        return src.get("statement_date")
    try:
        dt.date.fromisoformat(str(first))
    except ValueError:
        raise ValueError(f"prediction {rec.get('prediction_id')}: statement_date_earliest {first!r} is not "
                         f"YYYY-MM-DD") from None
    return str(first)


def already_public_errors(obj: dict, said: "str | None") -> list[str]:
    """A report dated ON or after the statement cannot show the thing was public before it.

    `said` is statement_bound(rec). The same day is refused too: a report
    published that day may have followed the words (review 2026-09-30)."""
    ap = obj.get("already_public")
    if ap is None:
        return []
    try:
        when = dt.date.fromisoformat(str(ap.get("date")))
    except ValueError:
        return [f"already_public date {ap.get('date')!r} is not YYYY-MM-DD"]
    if not said:
        return ["already_public is given, but the record has no statement date to compare it with"]
    if when >= dt.date.fromisoformat(str(said)[:10]):
        return [f"already_public date {when} is not strictly before the statement date {said}; a report on or "
                f"after the statement cannot show the thing was public before it"]
    return []


def validate_resolution(obj: dict, expect_id: str, said: "str | None") -> list[str]:
    """Rules the schema cannot express. Each one is a way a resolution could be
    wrong while still being well-formed JSON. `said` is the record's statement
    date, which an `already_public` date may not follow."""
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
    errs += _searched_errors(obj)
    errs += already_public_errors(obj, said)
    return errs


def normalise_query(q) -> str:
    """One search query as compared: case, curly quotes and runs of spaces do not make a new query."""
    s = str(q).casefold().translate(str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}))
    return " ".join(s.split())


def distinct_queries(queries) -> int:
    return len({normalise_query(q) for q in queries if normalise_query(q)})


def validate_effort(obj: dict, telemetry: dict) -> list[str]:
    """The floor on what the HARNESS searched, for every outcome, and `searched` checked against it.

    The telemetry is grade.web_search_actions: every query of every completed
    search action. A page open is not a search, and one action carrying three
    queries is three (review 2026-09-30: counting items refused 24 hits of 129
    calls for the wrong reason). `searched` is the model's own account; each entry
    must be a query the harness ran, compared by normalise_query. Telemetry without
    the record is refused, never assumed."""
    ws = (telemetry or {}).get("web_search")
    if not isinstance(ws, dict) or not isinstance(ws.get("queries"), list):
        return ["telemetry records no web_search block of queries run, so the research effort cannot be shown"]
    ran = {normalise_query(q) for q in ws["queries"] if normalise_query(q)}
    errs = []
    if len(ran) < MIN_SEARCHES:
        errs.append(f"the harness ran {len(ran)} distinct search queries; every outcome needs at least {MIN_SEARCHES}")
    never = [q for q in obj.get("searched") or [] if normalise_query(q) and normalise_query(q) not in ran]
    if never:
        errs.append(f"searched lists queries the harness never ran: {never[:4]}")
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
                      account: str | None, telemetry: dict, resolved_at: str, as_of: str,
                      prompt_sha: str, release: str, code_revision: str) -> dict:
    return {
        # Which policy judged this, so a board never silently mixes two (critique
        # 3 A2). A sidecar written before the release carries none and is "legacy".
        "policy_release": release,
        "prompt_sha256": prompt_sha,
        "code_revision": code_revision,
        "searched": obj["searched"],
        "already_public": obj["already_public"],
        "prediction_id": rec["prediction_id"],
        "leader_slug": rec["leader_slug"],
        "transcript_id": rec["transcript_id"],
        "stage": "resolve",
        # The date this was resolved against. A statement-date override makes a
        # sidecar built under the old date stale, and the scorer drops it by this.
        "statement_date": (rec.get("source") or {}).get("statement_date"),
        "statement_date_basis": (rec.get("source") or {}).get("statement_date_basis"),
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
                 leaks: list[str], release: str, code_revision: str) -> dict:
    p_raw = float(obj["p"])
    return {
        "policy_release": release,
        "code_revision": code_revision,
        "prediction_id": rec["prediction_id"],
        "leader_slug": rec["leader_slug"],
        "transcript_id": rec["transcript_id"],
        "stage": "prior",
        # The date this was priced at; see resolution_record.
        "statement_date": (rec.get("source") or {}).get("statement_date"),
        "statement_date_basis": (rec.get("source") or {}).get("statement_date_basis"),
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


# Each stage writes its own tree, so no stage can read another's by glob.
SIDECAR_SUBDIRS = {"resolve": "resolutions", "prior": "priors", "early": "early", "lead_test": "lead_tests"}


def sidecar_path(root: Path, stage: str, slug: str, prediction_id: str) -> Path:
    if stage not in SIDECAR_SUBDIRS:
        raise ValueError(f"unknown stage {stage!r}")
    return root / SIDECAR_SUBDIRS[stage] / slug / f"{prediction_id}.json"


def load_sidecars(root: Path, stage: str) -> dict[str, dict]:
    """Every sidecar of a stage, keyed by prediction_id. Raises on a duplicate id
    rather than letting one silently win."""
    if stage not in SIDECAR_SUBDIRS:
        raise ValueError(f"unknown stage {stage!r}")
    out: dict[str, dict] = {}
    sub = root / SIDECAR_SUBDIRS[stage]
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


# ---------------------------------------------------------------------------
# The release that pins every stage's policy (critique 3 A2)
# ---------------------------------------------------------------------------
#
# The resolver, prior, early-call and lead-test prompts are code, outside the
# extraction contract that POLICY_RELEASE.json pins, so until 2026-09-30 a
# change to any of them left no trace: 476 resolutions carried no prompt hash,
# and A7's resolver prompt had to be inferred from commit times. Every text, rule
# and schema that shapes an answer is hashed here, and the hash is pinned. A stage
# calls check_policy_release() before any call, so an edit that was not released
# is refused rather than judged under the old name, and every sidecar records the
# release it was written under. A sidecar written before this existed carries no
# release; the scorer names it LEGACY_RELEASE and refuses a board that mixes
# releases unless its config names every one (score_predictions.release_problem).
#
# Cutting a release: change the text, run test_resolution_policy.py, and put the
# new id and sha256 below and in that test.

POLICY_RELEASE = ("resolution-2026-09-30", "daf8df3e1cdbe2af764f2a1b11ebb14d942860315a216117ad3f9026754a7aeb")
LEGACY_RELEASE = "legacy"
# Every release ever cut, oldest first, so a board scored after the next release
# can still name this one. A sidecar naming anything else is refused.
KNOWN_RELEASES = ("resolution-2026-09-30",)


def _policy_fixture() -> dict:
    """A fixed record whose rendering pins the shared block's layout, judged section included."""
    return {
        "prediction_id": "fixture", "leader_slug": "fixture", "transcript_id": "fixture/t", "_basis": "stated",
        "speaker": {"name": "N", "role": "R", "company": "C"},
        "source": {"statement_date": "2020-01-01", "venue": "V", "title": "T", "quote": "Q",
                   "context_before": "B", "context_after": "A"},
        "prediction": {"normalized_claim": "Revenue will be about 5 billion for fiscal 2020.",
                       "resolution_criteria": "Revenue for fiscal 2020 will be about 5 billion.",
                       "target_date": "2020", "target_date_text": "this year", "category": "company_business",
                       "subject_control": "own"},
        "_implied": {"row": "words: soon", "window_words": "1 year", "matched": "soon"},
    }


def _policy_parts() -> dict:
    return {
        "resolver_task": RESOLVER_TASK, "prior_task": PRIOR_TASK, "prior_trend_rule": PRIOR_TREND_RULE,
        "early_task": EARLY_TASK, "lead_test_task": LEAD_TEST_TASK, "lead_test_labels": list(LEAD_TEST_LABELS),
        "forecast_labels": list(FORECAST_LABELS),
        "judged_rules": JUDGED_RULES, "min_searches": MIN_SEARCHES, "leak_words": list(_LEAK_WORDS),
        "schemas": {"resolution": RESOLUTION_SCHEMA, "prior": PRIOR_SCHEMA, "early": EARLY_SCHEMA,
                    "lead_test": LEAD_TEST_SCHEMA},
        "block": _block(prompt_facts(_policy_fixture(), dt.date(2020, 12, 31))),
    }


def policy_release() -> tuple[str, str]:
    """(release id, sha256 of every text, rule and schema in this checkout)."""
    import hashlib
    return POLICY_RELEASE[0], hashlib.sha256(json.dumps(_policy_parts(), sort_keys=True).encode()).hexdigest()


def check_policy_release() -> str:
    """The release id, or ValueError when a text changed without a new release."""
    rid, sha = policy_release()
    if sha != POLICY_RELEASE[1]:
        raise ValueError(f"resolution_release_mismatch: the resolver, prior, early or lead-test policy in this "
                         f"checkout hashes to {sha[:12]}, but release {rid} pins {POLICY_RELEASE[1][:12]}; cut a new "
                         f"release (resolution_lib.POLICY_RELEASE) before spending a call under changed rules")
    return rid
