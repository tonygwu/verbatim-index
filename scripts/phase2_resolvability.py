#!/usr/bin/env python3
"""How much of the prediction corpus Phase 2 could actually resolve and score.

Read-only over data/predictions. Spends no model calls and writes nothing.
Answers the questions the Phase 2 scope in docs/PREDICTIONS-PHASE2-SCOPE.md
rests on, so a later reader re-runs this rather than trusting the numbers:

  1. how many accepted predictions carry a deadline that has already passed,
  2. how many of those survive a filter for what a score may contain,
  3. how many leaders would carry enough of them to be worth a number.

The cutoff is a date you pass, never the local clock, because "past due" is a
property of the data and of the day the reader asks, not of this machine.

Two decisions here changed on 2026-09-14 and both move the numbers:

  A deadline is read in ANY of the three schema forms. `prediction.target_date`
  is documented as "YYYY, YYYY-MM or YYYY-MM-DD", and the earlier version of
  this script parsed only the third. 68 of 475 accepted predictions carry a
  bare year or a year and month, 65 of them with the speaker naming the date
  out loud, and every one was being discarded as if it had no date at all. A
  partial date expands to its LAST day, because the claim is a deadline: "in
  2019" is false only once 2019 is over.

  The gate is a LEAD-TIME floor, not `subject_control`. Control separates "about
  my company" from "about the world"; it does not separate a forecast from an
  announcement, and it was being used for the second job. "SpaceX will do 60 to
  70 launches in the next 12 months" is control=own and is a real forecast; "our
  G4ad instances are coming in a week" is control=own and is a press release.
  What separates them is how far out the claim reaches. Control is now REPORTED
  beside every stage instead of deciding membership.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402

# SIXTY DAYS: the operator's call on 2026-09-15, replacing the 180 they set on
# 2026-09-14. The floor exists to keep an announcement from counting as a
# forecast, and at 180 it was doing that job TWICE. The scoring rule already
# discounts an easy call through p: MEASURED on this corpus, the 24 scored
# predictions priced at or above 0.8 hit 96% of the time and earn +0.136 each,
# which is the rule correctly treating a roadmap item as near-zero information.
# At 180 days the floor then threw those predictions away on top of that, and it
# cost almost all of the coverage: 100 of the 117 past-due exclusions were the
# lead-time clause alone, leaving 3 people with enough scored predictions to rank
# against 9 at 60 days.
#
# Sixty rather than zero, because the discount is not exact. The assessor
# undershoots at the top of the range, so a high-p prediction earns slightly MORE
# than zero on average, and admitting every same-quarter press release would pay
# a small premium for announcing things. The 36 predictions between 60 and 180
# days hit at 0.75, well short of the 0.82 of the set below the old floor, so
# they behave more like forecasts than like announcements.
MIN_LEAD_DAYS = 60

# The specificity levels a scored prediction may carry. The operator widened this
# from high alone to high and medium on 2026-09-27. A medium prediction names its
# outcome well enough to resolve, but leaves some latitude, such as "some" rather
# than a count. The resolver can still return `criterion_ambiguous` when that
# latitude is too wide to settle, and such a record is excluded rather than scored
# as a miss. LOW stays out. `resolve_predictions.select()` and the funnel below
# both read this one constant.
ELIGIBLE_SPECIFICITY = ("high", "medium")
SPECIFICITY_LABEL = " or ".join(ELIGIBLE_SPECIFICITY)
DAYS = {"year": 365.25, "month": 30.44, "week": 7.0, "day": 1.0}

# A word that stands for a count. These are JUDGEMENT CALLS, printed in the report so a
# reader can disagree with them rather than discover them in the source.
WORD_COUNTS = {"a": 1, "an": 1, "one": 1, "two": 2, "couple": 2, "three": 3, "few": 3,
               "several": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
               "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}

# Text that names no closing date. Each is REFUSED with its reason rather than guessed at.
REFUSALS = (
    ("recurring", re.compile(r"\bevery\b", re.I)),
    ("open_ended", re.compile(r"\b(or more|plus|at least|more than|lifetime|forever|"
                              r"eventually|someday|some day|or so|beyond)\b", re.I)),
)
UNIT = re.compile(r"\b(year|month|week|day)s?\b", re.I)
THIS_YEAR = re.compile(r"\b(this year|end of the year|end of this year|second half of this year)\b", re.I)
NEXT_YEAR = re.compile(r"\bnext year\b", re.I)
# "Over the next year" is a twelve-month span; "next year" alone is the following
# calendar year. The extractor already reads them that way in the corpus: "in the
# next year" said 2020-04-16 carries 2021-04-16, and "next year" said 2019-09-20
# carries 2020-12-31. "This time next year" is the anniversary too: the extractor
# wrote 2026-10-28 for 6b32b106, said 2025-10-28.
THE_NEXT_YEAR = re.compile(r"\b(?:the|this time) next year\b", re.I)
CALENDAR_NEXT_YEAR = "next year"   # the `how` horizon_span returns for the calendar reading
# The middle or the first half of next year closes on 30 June of the following
# year, not on 31 December: the extractor wrote 2023-06-30 for 52535f5c, "by the
# middle of next year". The second half and the end of next year are the calendar
# reading above. Review 0 of the round-4 funnel change, item 3.
MID_NEXT_YEAR = re.compile(r"\b(?:first half|middle|mid)(?:\s+of)?[\s-]+next year\b", re.I)
HALF_NEXT_YEAR = "first half of next year"   # the `how` horizon_span returns for 30 June
RANGE = re.compile(r"(\d+)\s*(?:to|or|through|-|–)\s*(\d+)\s*(year|month|week|day)s?", re.I)
NUMBER = re.compile(r"(\d+)\s*(year|month|week|day)s?", re.I)
WORDY = re.compile(r"\b(" + "|".join(WORD_COUNTS) + r")\s+(?:more\s+)?(year|month|week|day)s?\b", re.I)


def iso(value):
    """A YYYY-MM-DD date, or None. Used for statement dates, which are always full dates."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def stated_deadline(value):
    """(deadline, note) for prediction.target_date. note is ok, missing or malformed.

    A partial date expands to its last day. The schema documents three forms and all
    three are read; anything else is malformed and is counted, never guessed at.
    """
    if not value:
        return None, "missing"
    s = str(value).strip()
    for fmt, grain in (("%Y-%m-%d", "day"), ("%Y-%m", "month"), ("%Y", "year")):
        try:
            d = dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if grain == "year":
            return dt.date(d.year, 12, 31), "ok"
        if grain == "month":
            return dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1]), "ok"
        return d, "ok"
    return None, "malformed"


def add_span(start: dt.date, count: float, unit: str) -> dt.date:
    """Anchor a horizon on a date. Whole years and months move by the CALENDAR, not by 365.25.

    Day arithmetic drifts: three years as 3 * 365.25 days lands on 1 January and two years
    lands on 31 December of the year before. A horizon the speaker gave in years should
    land on the anniversary, so a reader checking the date sees the year they expect.
    """
    whole = int(count)
    if unit == "year" and count == whole:
        try:
            return start.replace(year=start.year + whole)
        except ValueError:                      # 29 February into a common year
            return start.replace(year=start.year + whole, day=28)
    if unit == "month" and count == whole:
        m = start.month - 1 + whole
        y, m = start.year + m // 12, m % 12 + 1
        return dt.date(y, m, min(start.day, calendar.monthrange(y, m)[1]))
    return start + dt.timedelta(days=round(count * DAYS[unit]))


def horizon_span(text):
    """(count, unit, how) for a relative horizon, or (None, None, reason). UPPER bound of a range.

    A range closes at its far end: "10 to 15 years" is falsified only after 15 years.
    """
    if not text:
        return None, None, "no_horizon_text"
    for reason, pat in REFUSALS:
        if pat.search(text):
            return None, None, reason
    m = RANGE.search(text)
    if m:
        return max(int(m.group(1)), int(m.group(2))), m.group(3).lower(), "range upper bound"
    m = NUMBER.search(text)
    if m:
        return int(m.group(1)), m.group(2).lower(), "number and unit"
    m = WORDY.search(text)
    if m:
        return WORD_COUNTS[m.group(1).lower()], m.group(2).lower(), "word count and unit"
    if NEXT_YEAR.search(text):
        if MID_NEXT_YEAR.search(text):
            return 1, "year", HALF_NEXT_YEAR
        if THE_NEXT_YEAR.search(text):
            return 1, "year", "the next year, twelve months"
        return 1, "year", CALENDAR_NEXT_YEAR
    if not UNIT.search(text) and not re.search(r"\d", text):
        return None, None, "event_anchored"
    return None, None, "no_horizon_value"


def derived_deadline(rec):
    """(deadline, how) for a record with no stated target_date, or (None, reason).

    Everything is anchored on the statement date, so a recording with no date has no
    anchor and is refused. `horizon_years_inferred` is trusted when the pipeline wrote
    one, because that is the pipeline's own resolved horizon.
    """
    p, src = rec["prediction"], rec.get("source") or {}
    said = iso(src.get("statement_date"))
    if said is None:
        return None, "no_statement_date"
    if L.relative_phrase_crosses_new_year(rec):   # the rule lives in predictions_lib (release 2.3)
        return None, L.RANGE_CROSSES_NEW_YEAR
    yrs = p.get("horizon_years_inferred")
    if yrs is not None:
        return add_span(said, float(yrs), "year"), "horizon_years_inferred"
    text = p.get("target_date_text")
    if text and THIS_YEAR.search(text) and not NEXT_YEAR.search(text):
        return dt.date(said.year, 12, 31), "the calendar year of the statement"
    count, unit, how = horizon_span(text)
    if count is None:
        return None, how
    if how == CALENDAR_NEXT_YEAR:
        # The whole following calendar year, so the claim is false only once it is
        # over. It used to land on the anniversary, which judged "sometime next
        # year" said in September against the September after (design 3.5, A9).
        return dt.date(said.year + 1, 12, 31), "the calendar year after the statement"
    if how == HALF_NEXT_YEAR:
        return dt.date(said.year + 1, 6, 30), "the first half of the calendar year after the statement"
    return add_span(said, count, unit), how


# ---------------------------------------------------------------------------
# Open-ended trend claims
# ---------------------------------------------------------------------------
#
# "today is 20 plus percent operating margin and in the future that will only
# continue to go up" names no closing date, so it has no deadline and the funnel
# dropped it. The operator's call on 2026-09-16 is that this is too literal: a
# directional claim made four years ago HAS a track record, and refusing to look
# at it is refusing the spirit of what was said.
#
# It is still not resolvable as stated, because "will continue" can never be
# false at a single moment. What makes it testable is fixing the WINDOW: not the
# speaker's deadline, which they never gave, but the time that has actually
# elapsed. The question becomes "over the N years since they said it, did the
# direction hold", which is well posed and can come out either way.
#
# TWO GUARDS, because this is the one place the funnel stops requiring a date.
#   - the claim must be DIRECTIONAL. A vague claim with no direction gains
#     nothing from a window.
#   - enough time must have passed. Under MIN_TREND_YEARS a "continue to rise"
#     claim has not had room to be wrong, and calling it true would reward
#     recency rather than foresight.
# The window is reported as basis "trend", never as a stated or derived
# deadline, so nothing downstream mistakes it for something the speaker said.

MIN_TREND_YEARS = 3.0

TREND_WORDS = re.compile(
    r"\b(continue|continues|continuing|keep|keeps|remain|remains|stay|stays|"
    r"grow|grows|growing|rise|rises|rising|increase|increases|increasing|"
    r"decline|declines|declining|fall|falls|falling|decrease|decreases|"
    r"double|doubles|triple|triples|shrink|shrinks|expand|expands|"
    r"more|less|higher|lower|faster|slower|bigger|smaller|up|down)\b", re.I)


def trend_text(rec) -> str:
    p = rec.get("prediction") or {}
    s = rec.get("source") or {}
    return f"{p.get('normalized_claim') or ''} {p.get('resolution_criteria') or ''} {s.get('quote') or ''}"


def trend_window(rec, cutoff: dt.date, min_years: float = MIN_TREND_YEARS):
    """(cutoff, note) when an undated directional claim has had time to be wrong."""
    said = iso((rec.get("source") or {}).get("statement_date"))
    if not said:
        return None, "no_statement_date"
    years = (cutoff - said).days / 365.25
    if years < min_years:
        return None, f"only {years:.1f}y elapsed, under {min_years}y"
    if not TREND_WORDS.search(trend_text(rec)):
        return None, "no direction to test"
    return cutoff, f"trend over {years:.1f}y since the statement"


# ---------------------------------------------------------------------------
# Implied windows (VD-6 (a), operator 2026-09-29)
# ---------------------------------------------------------------------------
#
# A prediction with no stated deadline and no horizon the funnel can read is
# judged over a FIXED window, chosen from the speaker's words when they gave
# vague ones, else from what the claim is about. The operator fixed the table on
# 2026-09-29, before any record was judged over it, and it is pinned by
# implied_table_sha256(): a scoring config names the hash it was committed with,
# and the scorer refuses a table that no longer hashes to it (critique 1 point 3
# of the rescue round-4 design: a window chosen with the outcomes in view is not
# a window).
#
# The guards from the critiques, each a row of the table rather than a
# judgement made later:
#   - the phrase rows read the verbatim quote as well as target_date_text,
#     because release 2.2 copied vague words into neither field and 2.3 copies
#     them into target_date_text; the two versions of one record get one window
#     (critique 1 point 4);
#   - lead is the SHORTEST reading of the words, so "in the coming weeks" (two
#     weeks at the shortest) stays under the lead floor, and words with no lower
#     bound, or no words at all, are a lead only when the speaker does not
#     control the outcome (critique 1 point 2);
#   - a conditional, ordering or recurring claim is screened out by these
#     patterns over the pipeline's own claim text BEFORE any resolver runs, never
#     by a resolver that has already seen what happened (critique 1 point 5);
#   - a speaker whose own horizon is longer than the cap ("in my lifetime",
#     "decades", "at least 10 years") gets no window at all, rather than a
#     shorter one than they claimed.
# A record with two phrase rows in one field is refused as ambiguous rather than
# guessed between. MEASURED 2026-09-29 on production: 0 records.

IMPLIED_SCALES = (0.5, 1.0, 2.0)   # half and double are the sensitivity report's

IMPLIED_TABLE = {
    "cap_years": 5,
    # Read in this order; the first field holding a phrase row decides.
    "phrase_fields": ["target_date_text", "quote"],
    "phrases": [
        {"row": "coming weeks", "pattern": r"\b(?:coming weeks|next few weeks)\b", "window": [3, "month"],
         "shortest": [2, "week"]},
        {"row": "coming months", "pattern": r"\b(?:coming months|next several months|in a few months)\b",
         "window": [12, "month"], "shortest": [2, "month"]},
        {"row": "soon", "pattern": r"\b(?:soon|shortly|near[- ]term)\b", "window": [1, "year"], "shortest": None},
        {"row": "eventually", "pattern": r"\b(?:eventually|someday|some day|over time)\b",
         "window": [5, "year"], "shortest": None},
    ],
    # First match wins. "control": null matches any subject_control.
    "classes": [
        {"row": "the speaker's own company or product", "categories": ["company_business", "technology_product"],
         "control": ["own"], "window": [1, "year"]},
        {"row": "another company", "categories": ["company_business", "technology_product"],
         "control": None, "window": [3, "year"]},
        {"row": "policy or regulation", "categories": ["policy_regulation"], "control": None, "window": [3, "year"]},
        {"row": "everything else", "categories": None, "control": None, "window": [5, "year"]},
    ],
    # The speaker's own horizon is longer than the cap: no window.
    "longer_fields": ["target_date_text", "quote", "normalized_claim", "resolution_criteria"],
    "longer": [r"\blifetimes?\b", r"\bin (?:my|our|your|his|her|their) li(?:fe|ves)\b", r"\bdecades?\b",
               r"\bforever\b"],
    # "at least N years" and "more than N years" with N over the cap.
    "longer_at_least": r"\b(?:at least|more than) (\w+) years?\b",
    # Screened before any resolver runs. The extractor's own claim_form decides
    # when the record carries one (release 2.3); these patterns over the
    # pipeline's claim text decide for a record that does not.
    "claim_forms": {"simple": None, "conditional": "conditional_claim", "ordering": "ordering_claim",
                    "recurring": "recurring_claim"},
    "screen_fields": ["normalized_claim"],
    "screens": [
        ["conditional_claim", r"\b(?:if|unless|provided that|as long as|assuming|in the event that|once|when|whenever)\b"],
        ["ordering_claim", r"\b(?:before(?!\s+(?:the\s+)?(?:end|start|beginning|middle|close)\b)"
                           r"(?!\s+(?:\d|january|february|march|april|may|june|july|august|september|october|"
                           r"november|december)\b)|first to|sooner than|earlier than)\b"],
        ["recurring_claim", r"\b(?:every\s+(?:day|week|month|quarter|year|single)|each\s+(?:day|week|month|quarter|year)"
                            r"|annually)\b"],
    ],
    # Words that name an event rather than a time ("when the merger closes") get
    # no window: the claim row would impose a horizon the speaker tied to something else.
    "no_window_refusals": ["recurring", "event_anchored"],
    "lead": ("the shortest reading of the words, in days (count times phase2_resolvability.DAYS[unit], "
             "rounded); words with no lower bound, and a claim row, which has no words, count as UNDER the "
             "floor whoever controls the outcome, so the outcome-blind lead test decides them (VD-7 c)"),
}


def implied_table_sha256() -> str:
    """The hash a scoring config names to switch implied windows on."""
    import hashlib
    return hashlib.sha256(json.dumps(IMPLIED_TABLE, sort_keys=True).encode()).hexdigest()


_IMPLIED_PHRASES = [(p["row"], re.compile(p["pattern"], re.I), p) for p in IMPLIED_TABLE["phrases"]]
_IMPLIED_LONGER = [re.compile(p, re.I) for p in IMPLIED_TABLE["longer"]]
_IMPLIED_AT_LEAST = re.compile(IMPLIED_TABLE["longer_at_least"], re.I)
_IMPLIED_SCREENS = [(name, re.compile(p, re.I)) for name, p in IMPLIED_TABLE["screens"]]


def _span_words(count: float, unit: str) -> str:
    return f"{count:g} {unit}{'' if count == 1 else 's'}"


def implied_phrase_rows(text: str) -> list[str]:
    """The phrase rows a text holds, in table order."""
    return [row for row, pat, _ in _IMPLIED_PHRASES if pat.search(text or "")]


def _longer_than_cap(text: str) -> bool:
    if any(p.search(text or "") for p in _IMPLIED_LONGER):
        return True
    for m in _IMPLIED_AT_LEAST.finditer(text or ""):
        w = m.group(1).lower()
        n = int(w) if w.isdigit() else WORD_COUNTS.get(w)
        if n is not None and n > IMPLIED_TABLE["cap_years"]:
            return True
    return False


def implied_deadline(rec: dict, scale: float = 1.0):
    """(deadline, basis, info) from the implied-window table, or (None, reason, None).

    Pure: reads the record's own fields and the table. `scale` is 1 for the
    board and 0.5 or 2 for the sensitivity report; it scales the window and never
    the shortest reading, which is a property of the words.
    """
    if scale not in IMPLIED_SCALES:
        raise SystemExit(f"implied window scale {scale!r}: the table is judged at {list(IMPLIED_SCALES)} only")
    p, src = rec.get("prediction") or {}, rec.get("source") or {}
    said = iso(src.get("statement_date"))
    if said is None:
        return None, "no_statement_date", None
    fields = {"target_date_text": p.get("target_date_text") or "", "quote": src.get("quote") or "",
              "normalized_claim": p.get("normalized_claim") or "",
              "resolution_criteria": p.get("resolution_criteria") or ""}
    if any(_longer_than_cap(fields[f]) for f in IMPLIED_TABLE["longer_fields"]):
        return None, "speaker_horizon_longer", None
    form = p.get("claim_form")
    if form is not None:
        if form not in IMPLIED_TABLE["claim_forms"]:
            raise SystemExit(f"prediction {rec.get('prediction_id')}: claim_form {form!r} is none of "
                             f"{sorted(IMPLIED_TABLE['claim_forms'])}; it is never read as simple")
        if IMPLIED_TABLE["claim_forms"][form]:
            return None, IMPLIED_TABLE["claim_forms"][form], None
    else:
        for name, pat in _IMPLIED_SCREENS:
            if any(pat.search(fields[f]) for f in IMPLIED_TABLE["screen_fields"]):
                return None, name, None
    chosen, where, matched = None, None, None
    for f in IMPLIED_TABLE["phrase_fields"]:
        rows = implied_phrase_rows(fields[f])
        if len(rows) > 1:
            return None, "implied_ambiguous_words", None
        if rows:
            chosen = next(x for row, _, x in _IMPLIED_PHRASES if row == rows[0])
            where = f
            matched = next(pat for row, pat, _ in _IMPLIED_PHRASES if row == rows[0]).search(fields[f]).group(0)
            break
    if chosen is not None:
        row, window, shortest = f"words: {chosen['row']}", chosen["window"], chosen["shortest"]
    else:
        cat, ctrl = p.get("category"), p.get("subject_control")
        c = next(c for c in IMPLIED_TABLE["classes"]
                 if (c["categories"] is None or cat in c["categories"])
                 and (c["control"] is None or ctrl in c["control"]))
        row, window, shortest = f"claim: {c['row']}", c["window"], None
    count, unit = window[0] * scale, window[1]
    d = add_span(said, count, unit)
    words = _span_words(count, unit)
    basis = f"implied: {row}" + (f" ({where})" if where else "") + f", {words}" + ("" if scale == 1 else f" at {scale:g}x")
    info = {"row": row, "window": list(window), "window_words": words, "scale": scale,
            "matched": matched, "matched_in": where,
            "shortest_reading_days": round(shortest[0] * DAYS[shortest[1]]) if shortest else None}
    return d, basis, info


def implied_lead(info: dict, min_lead: int) -> tuple[bool, str]:
    """(lead_ok, why) for an implied window: the shortest reading of the words, never the window.

    Words with no lower bound, and a claim row, which has no words, allow the
    thing at once, so they count as under the floor whoever controls the
    outcome, and the outcome-blind lead test decides (review 2026-09-30 of VD-7 c).
    """
    s = info["shortest_reading_days"]
    if s is not None:
        return s >= min_lead, (f"the words ({info['matched']!r}) allow it within {s} days at the shortest, "
                               f"{'at or over' if s >= min_lead else 'under'} the {min_lead}-day floor")
    words = f"the words ({info['matched']!r})" if info.get("matched") else "it names no time at all, so it"
    return False, (f"{words} set no lower bound, so it counts as under the {min_lead}-day floor, and an "
                   f"outcome-blind check decides whether it is a forecast")


def superseded_by_override(r: dict, date_overrides: dict) -> str | None:
    """Why a record no longer counts under the override file, or None when it does.

    A record from an overridden transcript must carry the override's date under
    the override basis, which only a re-extraction produces. A record extracted
    under the upload date is stale: its claim text and deadline embed the wrong
    year. A record carrying an override the file no longer holds is stale too.
    """
    src = r.get("source") or {}
    ov = date_overrides.get(r.get("transcript_id"))
    if ov is not None:
        if src.get("statement_date_basis") != L.OVERRIDE_DATE_BASIS or src.get("statement_date") != ov["statement_date"]:
            return (f"extracted under {src.get('statement_date_basis')} {src.get('statement_date')}; "
                    f"the override says {ov['statement_date']}")
        return None
    if src.get("statement_date_basis") == L.OVERRIDE_DATE_BASIS:
        return "carries a statement-date override the override file no longer holds"
    return None


def load(pred_dir, date_overrides: "dict | None" = None, superseded: "list | None" = None):
    """Accepted predictions from one corpus directory, or several.

    Several, because the corpus is no longer one source. repo-1's supplemental
    run extracts predictions from shareholder letters, earnings calls and other
    web pages, and those records are the same shape but live in their own tree.
    A record carries its corpus in `_corpus`, so a later reader can tell where a
    scored prediction came from without re-deriving it.

    A prediction_id appearing in TWO corpora is a duplicate and raises. The id
    hashes the transcript and the quote, so a genuine collision means the same
    words were extracted twice, which would double-count that person.

    With `date_overrides` (predictions_lib.load_statement_date_overrides), a
    record extracted under a date the override replaced is SUPERSEDED before the
    duplicate check: it is left out, appended to `superseded` with the reason, and
    announced on stderr. So a re-extraction that kept the same prediction_id does
    not collide with the stale record, and one that got a new id does not sit
    beside it. Without the file, nothing changes.
    """
    dirs = [pathlib.Path(pred_dir)] if isinstance(pred_dir, (str, pathlib.Path)) else [pathlib.Path(d) for d in pred_dir]
    rows = []
    seen: dict[str, str] = {}
    for d in dirs:
            # An underscore-prefixed directory is NOT a leader. `_runs/` holds the
            # error logs every stage writes, which are JSONL and glob identically to
            # records. They survive today only because an error line carries no
            # `accepted` key, so the filter below drops it by accident; an error log
            # that ever gained that field would enter the corpus silently.
            # deploy_predictions.sh already applies this rule when it counts records.
        for f in sorted(x for x in d.glob("*/*.jsonl") if not x.parent.name.startswith("_")):
            # split on the newline byte only; see predictions_lib.parse_lines
            for line in f.read_text().split("\n"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if not r.get("accepted"):
                    continue
                why = superseded_by_override(r, date_overrides) if date_overrides is not None else None
                if why:
                    gone = {"prediction_id": r.get("prediction_id"), "transcript_id": r.get("transcript_id"),
                            "leader_slug": r.get("leader_slug"), "corpus": str(d),
                            "statement_date": (r.get("source") or {}).get("statement_date"),
                            "override_date": (date_overrides.get(r.get("transcript_id")) or {}).get("statement_date"),
                            "reason": why}
                    print(f"superseded by statement-date override: {gone['transcript_id']} "
                          f"{gone['prediction_id']}: {why}", file=sys.stderr)
                    if superseded is not None:
                        superseded.append(gone)
                    continue
                # Only a REAL id can be a duplicate. A record without one cannot be
                # deduped at all, and treating a missing key as a collision would
                # reject every such corpus on its second record.
                pid = r.get("prediction_id")
                if pid and pid in seen:
                    raise SystemExit(f"prediction_id {pid} appears in both {seen[pid]} and {d}; "
                                     f"the same quote would be scored twice")
                if pid:
                    seen[pid] = str(d)
                r["_corpus"] = d.name
                rows.append(r)
    if not rows:
        raise SystemExit(f"no accepted predictions under {[str(d) for d in dirs]}")
    return rows


def attach_deadlines(rows, derive: bool, trend_cutoff: "dt.date | None" = None,
                     min_trend_years: float = MIN_TREND_YEARS, implied: "float | None" = None):
    """Give every row a deadline, its basis and the reason when it has none. Nothing is dropped here.

    `trend_cutoff` opts in to the open-ended trend window above. It is off unless
    a caller passes a date, so every existing number is reproduced exactly.

    `implied` opts in to the implied-window table at that scale (1 for the
    board, 0.5 or 2 for the sensitivity report). It is off unless a caller passes
    one. With it, a record the funnel cannot date is judged over the table's
    window instead of a trend window: the table is fixed at the statement date,
    while a trend window grows with the as-of, so a record would otherwise change
    basis as it aged. A trend record already RESOLVED keeps its frozen window;
    resolve_predictions.select() restores it from the resolution. An implied row
    carries `_implied`, the table row that set it; a row without one carries no
    such key, so the policy switched off leaves every row as it was.
    """
    if implied is not None and not derive:
        raise SystemExit("implied windows come after the funnel's own reading of the words; pass derive=True")
    notes = collections.Counter()
    refusals = collections.Counter()
    expansions = []
    trends = collections.Counter()
    for r in rows:
        d, note = stated_deadline(r["prediction"].get("target_date"))
        notes[note] += 1
        if note == "ok":
            raw = str(r["prediction"]["target_date"]).strip()
            if len(raw) < 10:
                expansions.append((raw, d))
            r["_deadline"], r["_basis"], r["_why_none"] = d, "stated", None
            continue
        if implied is not None and note == "missing":
            # The operator's phrase rows beat the funnel's own word counts ("in a
            # few months" is 12 months by the table, 3 by WORD_COUNTS), so the 2.2
            # and 2.3 versions of one record agree; a number the speaker said still
            # wins, because it is not a vague word.
            tdt = r["prediction"].get("target_date_text") or ""
            if L.relative_phrase_crosses_new_year(r):
                # "this year" or "next year" said on a range of days across 31 December
                # names a different year for each end. derived_deadline refuses it, and
                # no implied window may stand in for it either (final review item 4).
                # Refused here, in code, so IMPLIED_TABLE and its pinned sha256 are
                # unchanged; checked before the phrase rows, which skip the funnel's
                # own reading.
                refusals[L.RANGE_CROSSES_NEW_YEAR] += 1
                r["_deadline"], r["_basis"], r["_why_none"] = None, None, L.RANGE_CROSSES_NEW_YEAR
                continue
            # With a phrase row in target_date_text and no number, the table decides
            # outright, a window or a refusal; otherwise the funnel's own reading first.
            phrase = not re.search(r"\d", tdt) and bool(implied_phrase_rows(tdt))
            d2, how = (None, None) if phrase else derived_deadline(r)
            if d2 is not None:
                r["_deadline"], r["_basis"], r["_why_none"] = d2, f"derived: {how}", None
                continue
            d4, basis4, info4 = implied_deadline(r, implied)
            if d4 is not None and how not in IMPLIED_TABLE["no_window_refusals"]:
                r["_deadline"], r["_basis"], r["_why_none"], r["_implied"] = d4, basis4, None, info4
                notes["implied_windows"] += 1
                continue
            # The table's own refusal names more (a horizon longer than the cap, a
            # screen); a recurring claim or words tied to an event get none either.
            why = basis4 if d4 is None else how
            refusals[why] += 1
            r["_deadline"], r["_basis"], r["_why_none"] = None, None, why
            continue
        if derive and note == "missing":
            d2, how = derived_deadline(r)
            if d2 is not None:
                r["_deadline"], r["_basis"], r["_why_none"] = d2, f"derived: {how}", None
                continue
            if trend_cutoff:
                d3, why3 = trend_window(r, trend_cutoff, min_trend_years)
                if d3 is not None:
                    r["_deadline"], r["_basis"], r["_why_none"] = d3, f"trend: {why3}", None
                    trends["window applied"] += 1
                    continue
                trends[why3.split(",")[0]] += 1
            refusals[how] += 1
            r["_deadline"], r["_basis"], r["_why_none"] = None, None, how
            continue
        if trend_cutoff and note == "missing":
            d3, why3 = trend_window(r, trend_cutoff, min_trend_years)
            if d3 is not None:
                r["_deadline"], r["_basis"], r["_why_none"] = d3, f"trend: {why3}", None
                trends["window applied"] += 1
                continue
            trends[why3.split(",")[0]] += 1
        r["_deadline"], r["_basis"], r["_why_none"] = None, None, note
    if trend_cutoff:
        notes["trend_windows"] = trends["window applied"]
    return notes, refusals, expansions


def lead_days(r):
    said = iso((r.get("source") or {}).get("statement_date"))
    return (r["_deadline"] - said).days if said and r["_deadline"] else None


def control_split(rows):
    c = collections.Counter(r["prediction"].get("subject_control") for r in rows)
    return "  ".join(f"control={k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))


def funnel(rows, cutoff: dt.date, min_lead: int):
    """Each stage names what it drops and reports its control split. Control never gates."""
    stages = []

    def stage(label, keep):
        stages.append((label, keep))
        return keep

    stage("accepted predictions", rows)
    dated = stage("carry a deadline", [r for r in rows if r["_deadline"]])
    past = stage(f"deadline on or before {cutoff.isoformat()}",
                 [r for r in dated if r["_deadline"] <= cutoff])
    sane = stage("deadline not BEFORE the statement date",
                 [r for r in past
                  if not (iso((r.get("source") or {}).get("statement_date"))
                          and r["_deadline"] < iso((r.get("source") or {}).get("statement_date")))])
    spec = stage(f"specificity {SPECIFICITY_LABEL}",
                 [r for r in sane if r["prediction"].get("specificity") in ELIGIBLE_SPECIFICITY])
    stage(f"lead time >= {min_lead} days",
          [r for r in spec if lead_days(r) is not None and lead_days(r) >= min_lead])
    return stages


# ---------------------------------------------------------------------------
# Why a past-due record is not eligible: ONE order for every reader
# ---------------------------------------------------------------------------
#
# The eligibility clauses, in the order funnel() above applies them: a window
# that closes before it opens, then specificity, then lead time. Lead time splits
# in two: a record with no statement date has no lead time at all ("undated"),
# and one that has a date and falls short is "lead_under_floor". A record that
# fails several clauses is named by the FIRST one here.
#
# One constant, because three readers name the reason: the resolve and prior
# stages (resolve_predictions.narrow, which skips what it names), the scorer
# (score_predictions.join, which writes `not_eligible:<reason>`) and the page.
# FOUND 2026-09-29 by both reviews of the rescue round-4 funnel change: the
# scorer and the page each kept an order, and they differed, so a vague undated
# record read `not_eligible:specificity` in scores.json and "undated" on its card.
INELIGIBLE_REASONS = ("deadline_before_statement", "specificity", "undated", "lead_under_floor")
# The flags failing_clauses() reads. resolve_predictions.select() writes every one.
CLAUSE_FLAGS = ("deadline_before_statement", "specificity_ok", "lead_days", "lead_ok")
REASON_FLAGS = ("eligible",) + CLAUSE_FLAGS


# VD-7 (c), operator 2026-09-29: under the lead floor, these outcome-blind labels
# (resolution_lib.LEAD_TEST_LABELS) are forecasts and may be scored; an
# announcement of the speaker's own plans and a relay may not.
LEAD_TEST_FORECASTS = ("world_forecast", "own_results_forecast")


def funnel_flags(r: dict, min_lead: int, lead_labels: "dict[str, str] | None" = None) -> dict:
    """The eligibility flags of one record that carries a deadline (attach_deadlines).

    resolve_predictions.select() writes these onto every past-due record, and the
    scorer copies them into scores.json. The page asks the same function about a
    record scores.json does not carry (not yet due, or past due after scoring), so
    a card never promises a check that no stage will make. Pure: reads only `r`.

    The three clauses together are the operator's eligibility rule: a real forecast
    is specific enough (ELIGIBLE_SPECIFICITY, high or medium since 2026-09-27),
    reaches at least `min_lead` days out, and has a coherent window. A trend window
    IS the elapsed time, so the lead floor is met by construction and specificity is
    not what makes it testable: a trend record is eligible.
    """
    if r.get("_deadline") is None:
        raise SystemExit(f"prediction {r.get('prediction_id')} has no deadline, so it has no funnel flags; "
                         f"attach_deadlines() gives one first")
    said = iso((r.get("source") or {}).get("statement_date"))
    lead = lead_days(r)
    is_trend = str(r.get("_basis") or "").startswith("trend")
    implied = r.get("_implied")
    if implied is not None:
        # An implied window is imposed, so the window itself is no lead: the
        # shortest reading of the words is (critique 1 point 2).
        lead_ok, lead_rule = implied_lead(implied, min_lead)
    else:
        lead_ok = lead is not None and lead >= min_lead
    flags = {
        "basis": r["_basis"],
        "deadline_before_statement": bool(said and r["_deadline"] < said),
        "specificity_high": r["prediction"].get("specificity") == "high",
        "specificity_ok": r["prediction"].get("specificity") in ELIGIBLE_SPECIFICITY,
        "lead_days": lead,
        "lead_ok": lead_ok,
        "trend": is_trend,
    }
    if implied is not None:
        # Only on an implied row, so every other row's flags are byte-identical.
        flags["implied"] = {**{k: implied[k] for k in ("row", "window_words", "scale", "matched", "matched_in",
                                                         "shortest_reading_days")}, "lead_rule": lead_rule}
    if (lead_labels is not None and not lead_ok and lead is not None and not is_trend
            and flags["specificity_ok"] and not flags["deadline_before_statement"]):
        # Under the floor, the outcome-blind label decides (VD-7 (c)); at or over
        # it, nothing changes. Only a record the floor ALONE keeps out is asked
        # about, as the lead_test stage labels only those. `lead_labels` is None
        # when the policy is off, so no row gains the key.
        label = lead_labels.get(r.get("prediction_id"))
        flags["lead_test"] = {"label": label}
        if label in LEAD_TEST_FORECASTS:
            flags["lead_ok"] = True
    flags["eligible"] = is_trend or (flags["specificity_ok"] and flags["lead_ok"]
                                     and not flags["deadline_before_statement"])
    return flags


def failing_clauses(flags: dict, pid: str = "?") -> list[str]:
    """Every eligibility clause these funnel flags fail, in INELIGIBLE_REASONS order.

    Pure: reads only `flags`. Flags that lack a key the clauses read are refused,
    never read as passing."""
    missing = [k for k in CLAUSE_FLAGS if k not in flags]
    if missing:
        raise SystemExit(f"prediction {pid}'s funnel flags lack {missing}; they come from "
                         f"resolve_predictions.select(), which writes all of {list(REASON_FLAGS)}")
    fails = {"deadline_before_statement": bool(flags["deadline_before_statement"]),
             "specificity": not flags["specificity_ok"],
             "undated": flags["lead_days"] is None,
             "lead_under_floor": flags["lead_days"] is not None and not flags["lead_ok"]}
    return [c for c in INELIGIBLE_REASONS if fails[c]]


def ineligible_reason(pid: str, flags: dict) -> str | None:
    """Why a past-due record is not eligible, or None when it is.

    The first clause in INELIGIBLE_REASONS that the flags fail. One reason per
    record, so the counts add up. Pure: reads only `flags`. Flags that say
    ineligible and fail no clause, or lack a key the rule reads, are refused,
    never guessed at."""
    if "eligible" not in flags:
        raise SystemExit(f"prediction {pid}'s funnel flags lack ['eligible']; they come from "
                         f"resolve_predictions.select(), which writes all of {list(REASON_FLAGS)}")
    fails = failing_clauses(flags, pid)
    if flags["eligible"]:
        return None
    if not fails:
        raise SystemExit(f"prediction {pid} is marked ineligible, but its funnel flags name no reason: {flags}")
    return fails[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", type=pathlib.Path, default=ROOT / "data" / "predictions")
    ap.add_argument("--as-of", required=True,
                    help="the cutoff date, YYYY-MM-DD. Required: 'past due' depends on the day "
                         "you ask, and reading it off the local clock is what this repo forbids.")
    ap.add_argument("--min-per-leader", type=int, default=5,
                    help="how many scorable predictions a leader needs to carry a number (default 5, "
                         "the leaderboard's own MIN_TRANSCRIPTS_TO_RANK)")
    ap.add_argument("--min-lead-days", type=int, default=MIN_LEAD_DAYS,
                    help=f"the minimum gap from statement to deadline (default {MIN_LEAD_DAYS}). Below "
                         "this a claim is an announcement rather than a forecast.")
    ap.add_argument("--no-derive", action="store_true",
                    help="do not derive a deadline from a relative horizon; use stated dates only")
    args = ap.parse_args()

    cutoff = iso(args.as_of)
    if cutoff is None:
        raise SystemExit(f"--as-of {args.as_of!r} is not a YYYY-MM-DD date")

    rows = load(args.predictions)
    notes, refusals, expansions = attach_deadlines(rows, derive=not args.no_derive)
    stages = funnel(rows, cutoff, args.min_lead_days)

    print(f"corpus: {len(rows)} accepted predictions, as of {cutoff.isoformat()}\n")
    print("RESOLVABILITY FUNNEL")
    prev = None
    for label, kept in stages:
        drop = "" if prev is None else f"  (-{prev - len(kept)})"
        print(f"  {len(kept):5d}  {label}{drop}")
        print(f"         {control_split(kept)}")
        prev = len(kept)

    dated = stages[1][1]
    n_stated = sum(1 for r in dated if r["_basis"] == "stated")
    n_derived = len(dated) - n_stated
    print("\nWHERE THE DEADLINES CAME FROM")
    print(f"  {n_stated} stated in prediction.target_date, "
          f"{n_derived} derived from a relative horizon")
    print(f"  {notes['missing']:5d}  no target_date at all")
    print(f"  {notes['malformed']:5d}  target_date present but malformed (dropped, never guessed at)")
    if expansions:
        shown = sorted({(raw, d.isoformat()) for raw, d in expansions})
        print(f"  {len(expansions)} partial dates expanded to their last day, for example: "
              + ", ".join(f"{raw} -> {d}" for raw, d in shown[:4]))
    if refusals:
        print("  relative horizons REFUSED, with the reason:")
        for k, v in refusals.most_common():
            print(f"    {v:5d}  {k}")
    print(f"  word counts used when the speaker gave no number: "
          + ", ".join(f"{k}={v}" for k, v in list(WORD_COUNTS.items())[:6]) + ", ...")

    past, scorable = stages[2][1], stages[-1][1]

    print("\nWHAT A RESOLUTION PASS WOULD READ (the past-due set, by category)")
    for k, v in collections.Counter(r["prediction"]["category"] for r in past).most_common():
        print(f"  {v:5d}  {k}")

    print(f"\nPER-LEADER COVERAGE (floor {args.min_per_leader})")
    for name, kept in (("past due", past), (f"past due, specificity {SPECIFICITY_LABEL}, lead >= {args.min_lead_days}d", scorable)):
        per = collections.Counter(r["leader_slug"] for r in kept)
        enough = sorted((v, k) for k, v in per.items() if v >= args.min_per_leader)
        print(f"  {name}: {len(per)} leaders have at least one; "
              f"{len(enough)} reach {args.min_per_leader}; top {per.most_common(5)}")

    probs = [r for r in rows if (r.get("confidence") or {}).get("probability") is not None]
    scored_now = [r for r in probs if r["_deadline"] and r["_deadline"] <= cutoff]
    print("\nPROPER SCORING (Brier needs a stated probability AND an outcome)")
    print(f"  {len(probs)} of {len(rows)} accepted predictions carry a probability the speaker said")
    print(f"  {len(scored_now)} of those are past due, so a Brier score today has n={len(scored_now)}")

    cons = collections.Counter((r.get("consensus") or {}).get("status") for r in rows)
    exact = sum(1 for r in rows if (r.get("consensus") or {}).get("exact_match"))
    print("\nMARKET-RELATIVE SCORING (needs a contemporaneous market price)")
    print(f"  exact market matches: {exact} of {len(rows)}; status counts {dict(cons)}")

    # Identity, not equality: two predictions can hold equal dicts and "in" would
    # match the wrong one. The funnel keeps the same objects, so id() is exact.
    sane_ids = {id(r) for r in stages[3][1]}
    bad = [r for r in stages[2][1] if id(r) not in sane_ids]
    print("\nDATE DEFECTS TO CLEAR BEFORE RESOLVING")
    print(f"  {len(bad)} past-due predictions target a date BEFORE their own statement date, "
          f"across {len(set(r['leader_slug'] for r in bad))} leaders:")
    for r in bad:
        print(f"    {r['leader_slug']:20s} said {r['source']['statement_date']} -> "
              f"target {r['prediction']['target_date']}  ({r['prediction']['target_date_text']!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
