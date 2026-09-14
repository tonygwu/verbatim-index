#!/usr/bin/env python3
"""The resolvability funnel on a fixture whose every answer is known by hand.

The traps this pins, each of which would silently inflate what Phase 2 can score:
  - a malformed target date must be DROPPED and counted, never guessed at;
  - "past due" must come from --as-of, never from the local clock;
  - a target date BEFORE its own statement date is a date-resolution defect and
    must leave the funnel rather than be resolved against the wrong window;
  - the own-control filter is what separates a forecast from a commitment.
"""
from __future__ import annotations

import datetime as dt
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


def rec(slug, target, said, *, control="external", spec="high", prob=None, accepted=True):
    return {
        "accepted": accepted, "leader_slug": slug,
        "prediction": {"target_date": target, "specificity": spec, "subject_control": control,
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "prediction_type": "binary_event"},
        "source": {"statement_date": said},
        "confidence": {"probability": prob},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def main() -> int:
    rows = [
        rec("ada", "2020-01-01", "2019-01-01"),                        # scorable
        rec("ada", "2020-06-01", "2019-01-01"),                        # scorable
        rec("ada", "2099-01-01", "2019-01-01"),                        # future, dropped
        rec("ada", "not-a-date", "2019-01-01"),                        # malformed, dropped
        rec("ada", None, "2019-01-01"),                                # undated, dropped
        rec("bob", "2018-01-01", "2019-01-01"),                        # target BEFORE the statement
        rec("bob", "2020-01-01", "2019-01-01", spec="medium"),         # low specificity, dropped
        rec("bob", "2020-01-01", "2019-01-01", control="own"),         # a commitment, dropped
        rec("bob", "2020-01-01", "2019-01-01", prob=0.7),              # scorable, and Brier-scorable
        rec("bob", "2020-01-01", "2019-01-01", accepted=False),        # rejected, never loaded
    ]
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        for slug in ("ada", "bob"):
            (d / slug).mkdir()
            (d / slug / "t1.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows if r["leader_slug"] == slug))
        run = lambda *a: subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "phase2_resolvability.py"),
             "--predictions", str(d), *a], capture_output=True, text=True)

        p = run("--as-of", "2026-09-13")
        check("FIXTURE: exits 0", p.returncode == 0, p.stderr[-400:])
        out = p.stdout
        want = [("9  accepted predictions", "the rejected record is never loaded"),
                ("7  carry a parseable target date", "the malformed and the missing date both drop"),
                ("6  target date on or before", "the 2099 target is not past due"),
                ("5  target date not BEFORE", "bob's 2018-target-from-a-2019-statement drops"),
                ("4  specificity high", "the medium-specificity record drops"),
                ("3  outcome NOT under the speaker", "the own-control commitment drops")]
        for needle, why in want:
            check(f"FUNNEL: {why}", needle in out, out)
        check("DEFECT: the bad-date record is named with both of its dates",
              "said 2019-01-01 -> target 2018-01-01" in out and "across 1 leaders" in out, out)
        check("BRIER: n is the count with a stated probability AND a past target",
              "so a Brier score today has n=1" in out, out)
        check("MARKET: zero exact matches is reported as zero, not omitted",
              "exact market matches: 0 of 9" in out, out)

        # The cutoff is an argument, not the clock: an earlier --as-of must shrink the past-due set.
        early = run("--as-of", "2019-06-01")
        # 6 past due at 2026-09-13 falls to 1 at 2019-06-01, and the one left is bob's
        # defective row, which the very next stage drops. Nothing reaches the scorable set.
        check("CUTOFF: --as-of drives 'past due', so an earlier date resolves fewer",
              "1  target date on or before 2019-06-01" in early.stdout
              and "0  target date not BEFORE the statement date" in early.stdout, early.stdout)
        missing = run()
        check("CUTOFF: --as-of is REQUIRED, so the local clock can never supply it",
              missing.returncode != 0 and "--as-of" in missing.stderr, missing.stderr[-300:])
        bad = run("--as-of", "13-09-2026")
        check("CUTOFF: a malformed --as-of fails loudly rather than defaulting",
              bad.returncode != 0 and "not a YYYY-MM-DD date" in (bad.stdout + bad.stderr), bad.stderr[-300:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
