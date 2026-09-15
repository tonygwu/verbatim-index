#!/usr/bin/env python3
"""The resolvability funnel on a fixture whose every answer is known by hand.

The traps this pins, each of which would silently change what Phase 2 can score:
  - a target date in ANY schema form (YYYY, YYYY-MM, YYYY-MM-DD) must be read, and a
    partial one expands to its LAST day, because the claim is a deadline;
  - a malformed target date must be DROPPED and counted SEPARATELY from a missing one,
    never guessed at and never silently merged with "undated";
  - "past due" must come from --as-of, never from the local clock;
  - a target date BEFORE its own statement date is a date-resolution defect and
    must leave the funnel rather than be resolved against the wrong window;
  - a deadline DERIVED from a relative horizon is labelled as derived and is refused
    whenever the text is open-ended, recurring or anchored to an event, not a date;
  - the lead-time floor is what separates a forecast from an announcement, and
    subject_control is REPORTED beside it rather than used as a gate.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(slug, target, said, *, control="external", spec="high", prob=None, accepted=True,
        horizon="explicit", text="x", years=None):
    return {
        "accepted": accepted, "leader_slug": slug,
        "prediction": {"target_date": target, "specificity": spec, "subject_control": control,
                       "category": "company_business", "horizon": horizon, "target_date_text": text,
                       "horizon_years_inferred": years, "prediction_type": "binary_event"},
        "source": {"statement_date": said},
        "confidence": {"probability": prob},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def main() -> int:
    rows = [
        # --- stated deadlines, all three schema forms ---
        rec("ada", "2020-01-01", "2019-01-01"),                        # scorable, 365 days lead
        rec("ada", "2020-06-01", "2019-01-01"),                        # scorable, 517 days lead
        rec("ada", "2020", "2019-01-01"),                              # BARE YEAR -> 2020-12-31, scorable
        rec("ada", "2020-06", "2019-01-01"),                           # YEAR-MONTH -> 2020-06-30, scorable
        rec("ada", "2099-01-01", "2019-01-01"),                        # future, dropped
        rec("ada", "not-a-date", "2019-01-01"),                        # malformed, dropped and counted apart
        rec("ada", None, "2019-01-01", horizon="none", text=None),     # open-ended, dropped
        rec("bob", "2018-01-01", "2019-01-01"),                        # target BEFORE the statement
        rec("bob", "2020-01-01", "2019-01-01", spec="medium"),         # low specificity, dropped
        rec("bob", "2020-01-01", "2019-01-01", control="own"),         # a commitment: KEPT, and reported as own
        rec("bob", "2019-03-01", "2019-01-01"),                        # 59 days lead: an announcement, dropped
        rec("bob", "2020-01-01", "2019-01-01", prob=0.7),              # scorable, and Brier-scorable
        rec("bob", "2020-01-01", "2019-01-01", accepted=False),        # rejected, never loaded
        # --- derived deadlines: no target_date, a relative horizon instead ---
        rec("cy", None, "2019-01-01", text="in the next few years"),          # -> 2022-01-01, derived
        rec("cy", None, "2019-01-01", text="in 10 to 15 years"),              # upper bound 15y -> 2034, future
        rec("cy", None, "2019-01-01", horizon="inferable", text=None, years=2),  # -> 2021-01-01, derived
        rec("cy", None, None, text="in the next few years"),                  # no statement date: no anchor
        rec("cy", None, "2019-01-01", text="in my lifetime"),                 # refused: not a deadline
        rec("cy", None, "2019-01-01", text="every three months"),             # refused: recurring
        rec("cy", None, "2019-01-01", text="over the next year or more"),     # refused: open upper bound
        rec("cy", None, "2019-01-01", text="as we introduce mountain lion"),  # refused: anchored to an event
    ]
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        for slug in ("ada", "bob", "cy"):
            (d / slug).mkdir()
            (d / slug / "t1.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows if r["leader_slug"] == slug))
        run = lambda *a: subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "phase2_resolvability.py"),
             "--predictions", str(d), *a], capture_output=True, text=True)

        p = run("--as-of", "2026-09-13")
        check("FIXTURE: exits 0", p.returncode == 0, p.stderr[-600:])
        out = p.stdout

        # 20 accepted. Stated deadlines: 5 of ada's 7 parse (not-a-date and the None do not) and
        # all 5 of bob's accepted rows = 10. cy contributes 3 derived, so 13 carry a deadline.
        want = [("20  accepted predictions", "the rejected record is never loaded"),
                ("13  carry a deadline", "bare-year and year-month dates are read, and 3 deadlines are derived"),
                ("11  deadline on or before", "the 2099 target and the 15-year derivation are not past due"),
                ("10  deadline not BEFORE the statement date", "bob's 2018-target-from-a-2019-statement drops"),
                ("9  specificity high", "the medium-specificity record drops"),
                ("8  lead time >= 180 days", "the 59-day announcement drops")]
        for needle, why in want:
            check(f"FUNNEL: {why}", needle in out, out)

        check("PARSE: a bare year expands to 31 December, so it is past due rather than dropped",
              "2020 -> 2020-12-31" in out, out)
        check("PARSE: a year and month expands to the last day of that month",
              "2020-06 -> 2020-06-30" in out, out)
        check("PARSE: a malformed date is counted apart from a missing one, never merged with it",
              "1  target_date present but malformed" in out and "9  no target_date at all" in out, out)

        check("DERIVE: a derived deadline is labelled as derived and counted separately",
              "10 stated in prediction.target_date, 3 derived from a relative horizon" in out, out)
        check("DERIVE: each refusal is named with its reason rather than silently dropped",
              all(s in out for s in ("open_ended", "recurring", "event_anchored", "no_statement_date")), out)
        check("DERIVE: --no-derive falls back to stated deadlines only",
              "10  carry a deadline" in run("--as-of", "2026-09-13", "--no-derive").stdout)

        check("CONTROL: own-control records are KEPT and reported as a split, not filtered out",
              "control=own" in out and "outcome NOT under the speaker" not in out, out)
        check("LEAD: the floor is an argument, so a different floor moves the count",
              "5  lead time >= 400 days" in run("--as-of", "2026-09-13", "--min-lead-days", "400").stdout)

        check("DEFECT: the bad-date record is named with both of its dates",
              "said 2019-01-01 -> target 2018-01-01" in out and "across 1 leaders" in out, out)
        check("BRIER: n is the count with a stated probability AND a past deadline",
              "so a Brier score today has n=1" in out, out)
        check("MARKET: zero exact matches is reported as zero, not omitted",
              "exact market matches: 0 of 20" in out, out)

        # The cutoff is an argument, not the clock: an earlier --as-of must shrink the past-due set.
        early = run("--as-of", "2019-06-01")
        check("CUTOFF: --as-of drives 'past due', so an earlier date resolves fewer",
              "2  deadline on or before 2019-06-01" in early.stdout
              and "1  deadline not BEFORE the statement date" in early.stdout, early.stdout)
        missing = run()
        check("CUTOFF: --as-of is REQUIRED, so the local clock can never supply it",
              missing.returncode != 0 and "--as-of" in missing.stderr, missing.stderr[-300:])
        bad = run("--as-of", "13-09-2026")
        check("CUTOFF: a malformed --as-of fails loudly rather than defaulting",
              bad.returncode != 0 and "not a YYYY-MM-DD date" in (bad.stdout + bad.stderr), bad.stderr[-300:])

    spec = importlib.util.spec_from_file_location("p2", ROOT / "scripts" / "phase2_resolvability.py")
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)

    check("UNIT: every documented target_date form parses to its LAST day",
          P.stated_deadline("2020") == (dt.date(2020, 12, 31), "ok")
          and P.stated_deadline("2020-02") == (dt.date(2020, 2, 29), "ok")   # a leap February
          and P.stated_deadline("2020-06-15") == (dt.date(2020, 6, 15), "ok"),
          str([P.stated_deadline(v) for v in ("2020", "2020-02", "2020-06-15")]))
    check("UNIT: a missing and a malformed target_date are different answers",
          P.stated_deadline(None) == (None, "missing") and P.stated_deadline("not-a-date") == (None, "malformed")
          and P.stated_deadline("2020-13") == (None, "malformed"),
          str([P.stated_deadline(v) for v in (None, "not-a-date", "2020-13")]))

    said = {"prediction": {"horizon_years_inferred": None}, "source": {"statement_date": "2019-01-01"}}
    def derive(text, years=None):
        r = {"prediction": {"horizon_years_inferred": years, "target_date_text": text},
             "source": {"statement_date": "2019-01-01"}}
        return P.derived_deadline(r)
    check("UNIT: a range closes at its UPPER bound, so 10 to 15 years is 15 years out",
          derive("in 10 to 15 years")[0] == dt.date(2034, 1, 1)
          and derive("for the next 5-7 years")[0] == dt.date(2026, 1, 1),
          str([derive("in 10 to 15 years"), derive("for the next 5-7 years")]))
    check("UNIT: a word count resolves through the printed table, and a digit beats it",
          derive("in the next few years")[0] == dt.date(2022, 1, 1)
          and derive("in 2 years")[0] == dt.date(2021, 1, 1), str([derive("in the next few years"), derive("in 2 years")]))
    check("UNIT: 'this year' anchors on the statement year, not a year from the statement",
          derive("by the end of the year")[0] == dt.date(2019, 12, 31)
          and derive("sometime next year")[0] == dt.date(2020, 1, 1), str([derive("by the end of the year"), derive("sometime next year")]))
    check("UNIT: text that names no closing date is refused with its reason, never guessed at",
          derive("in my lifetime") == (None, "open_ended")
          and derive("in the next five plus years") == (None, "open_ended")
          and derive("many more than ten years in the future") == (None, "open_ended")
          and derive("Every three months") == (None, "recurring")
          and derive("as we introduce mountain lion") == (None, "event_anchored")
          and derive("in the coming months") == (None, "no_horizon_value"),
          str([derive(t) for t in ("in my lifetime", "in the next five plus years",
                                   "many more than ten years in the future", "Every three months",
                                   "as we introduce mountain lion", "in the coming months")]))
    check("UNIT: a recording with no statement date has no anchor and is refused",
          P.derived_deadline({"prediction": {"horizon_years_inferred": 3, "target_date_text": "in three years"},
                              "source": {"statement_date": None}}) == (None, "no_statement_date"))
    check("UNIT: the pipeline's own resolved horizon wins over the text",
          derive("in the next few years", years=1)[0] == dt.date(2020, 1, 1))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
