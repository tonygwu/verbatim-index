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
        return 1, "year", "next year"
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
    yrs = p.get("horizon_years_inferred")
    if yrs is not None:
        return add_span(said, float(yrs), "year"), "horizon_years_inferred"
    text = p.get("target_date_text")
    if text and THIS_YEAR.search(text) and not NEXT_YEAR.search(text):
        return dt.date(said.year, 12, 31), "the calendar year of the statement"
    count, unit, how = horizon_span(text)
    if count is None:
        return None, how
    return add_span(said, count, unit), how


def load(pred_dir):
    """Accepted predictions from one corpus directory, or several.

    Several, because the corpus is no longer one source. repo-1's supplemental
    run extracts predictions from shareholder letters, earnings calls and other
    web pages, and those records are the same shape but live in their own tree.
    A record carries its corpus in `_corpus`, so a later reader can tell where a
    scored prediction came from without re-deriving it.

    A prediction_id appearing in TWO corpora is a duplicate and raises. The id
    hashes the transcript and the quote, so a genuine collision means the same
    words were extracted twice, which would double-count that person.
    """
    dirs = [pathlib.Path(pred_dir)] if isinstance(pred_dir, (str, pathlib.Path)) else [pathlib.Path(d) for d in pred_dir]
    rows = []
    seen: dict[str, str] = {}
    for d in dirs:
        for f in sorted(d.glob("*/*.jsonl")):
            # split on the newline byte only; see predictions_lib.parse_lines
            for line in f.read_text().split("\n"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if not r.get("accepted"):
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


def attach_deadlines(rows, derive: bool):
    """Give every row a deadline, its basis and the reason when it has none. Nothing is dropped here."""
    notes = collections.Counter()
    refusals = collections.Counter()
    expansions = []
    for r in rows:
        d, note = stated_deadline(r["prediction"].get("target_date"))
        notes[note] += 1
        if note == "ok":
            raw = str(r["prediction"]["target_date"]).strip()
            if len(raw) < 10:
                expansions.append((raw, d))
            r["_deadline"], r["_basis"], r["_why_none"] = d, "stated", None
            continue
        if derive and note == "missing":
            d2, how = derived_deadline(r)
            if d2 is not None:
                r["_deadline"], r["_basis"], r["_why_none"] = d2, f"derived: {how}", None
                continue
            refusals[how] += 1
            r["_deadline"], r["_basis"], r["_why_none"] = None, None, how
            continue
        r["_deadline"], r["_basis"], r["_why_none"] = None, None, note
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
    spec = stage("specificity high",
                 [r for r in sane if r["prediction"].get("specificity") == "high"])
    stage(f"lead time >= {min_lead} days",
          [r for r in spec if lead_days(r) is not None and lead_days(r) >= min_lead])
    return stages


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
    for name, kept in (("past due", past), (f"past due, high specificity, lead >= {args.min_lead_days}d", scorable)):
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
