#!/usr/bin/env python3
"""The criterion-agreement screen, on pairs whose right answer is known by hand.

Every case here is a real pair from data/predictions, or a minimal reduction of one.
The three false-positive sources this pins are the ones that made the first version
of the screen report 61.3% of the corpus as disagreeing when the true figure is 15.4%:

  - a date's month and day are not thresholds, so "2013-12-31" against
    "December 31, 2013" must not read as a dropped threshold of 12;
  - the verifier habitually appends "; a figure short of that would falsify", which
    negates by design, so polarity is compared on the main clause only;
  - two criteria that both decline to name a date AGREE about being open-ended, and
    that is not a disagreement.

And the two real defects it must still catch: a criterion that states no direction
("will / will not"), and a genuine polarity inversion.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def main() -> int:
    spec = importlib.util.spec_from_file_location("ca", ROOT / "scripts" / "criteria_agreement.py")
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)

    # ---- deadline ----
    check("DEADLINE: the date introduced by 'by' is the deadline, not the latest date named",
          C.deadline("By July 2035, the price will be lower than in July 2025.") == (2035, 7, None),
          str(C.deadline("By July 2035, the price will be lower than in July 2025.")))
    check("DEADLINE: ISO and written-out forms of one date agree",
          C.deadline("By 2013-12-31, Lever will have publicly launched.")
          == C.deadline("By December 31, 2013, Lever will have publicly launched.") == (2013, 12, 31),
          str([C.deadline("By 2013-12-31, x."), C.deadline("By December 31, 2013, x.")]))
    check("DEADLINE: a criterion naming no date has none, and is not invented",
          C.deadline("By an unspecified future date, the share will exceed half.") is None)

    # ---- the three false-positive sources ----
    check("MASK: a date's month and day are never read as thresholds",
          C.compare("By 2013-12-31, Lever will have publicly launched.",
                    "By December 31, 2013, Lever will have publicly launched.") == [],
          str(C.compare("By 2013-12-31, Lever will have publicly launched.",
                        "By December 31, 2013, Lever will have publicly launched.")))
    check("MASK: thresholds still compare after masking, and a magnitude word scales",
          C.thresholds("revenue will pass 2 billion in 2026") == {("n", 2e9)}
          and C.thresholds("margin will be above 20 percent") == {("pct", 20.0)},
          str([C.thresholds("revenue will pass 2 billion in 2026"), C.thresholds("margin will be above 20 percent")]))
    check("CLAUSE: the verifier's falsification rider does not read as a polarity disagreement",
          "polarity" not in C.compare(
              "By 2030-12-31, revenue will exceed 5 billion.",
              "By December 31, 2030, revenue will exceed 5 billion; a figure below that would falsify."),
          str(C.compare("By 2030-12-31, revenue will exceed 5 billion.",
                        "By December 31, 2030, revenue will exceed 5 billion; a figure below that would falsify.")))
    check("OPEN: two criteria that both decline to name a date agree, and carry no flag",
          C.compare("By an unspecified future date, X will happen.",
                    "By an unspecified future date, X will happen.") == [])

    # ---- the two real defects ----
    undirected = C.compare(
        "By 2025-12-25, DGX Spark will be generally available for customers to obtain.",
        "By December 25, 2025, NVIDIA DGX Spark systems will / will not be commercially available.")
    check("UNDIRECTED: a criterion saying 'will / will not' states no direction and is flagged",
          "undirected_criterion" in undirected, str(undirected))
    check("UNDIRECTED: it replaces the polarity flag rather than doubling it",
          "polarity" not in undirected, str(undirected))

    inverted = C.compare(
        "By 2028-04-02, machines will not have demonstrated capabilities surpassing humans in all domains.",
        "By 2028-04-02, machines will surpass humans in all domains where humans are intelligent.")
    check("POLARITY: a genuine inversion is caught, so a resolver cannot silently flip the outcome",
          "polarity" in inverted, str(inverted))

    mismatch = C.compare("By the end of 2022, Box's revenue for the year will be nearly a billion.",
                         "By the end of Box's fiscal 2023, which ends January 31, 2023, revenue will be nearly a billion.")
    check("DEADLINE: a calendar year against a fiscal year is a real window disagreement",
          "deadline_year" in mismatch, str(mismatch))
    check("DEADLINE: one criterion pinning a date the other leaves open is flagged, not merged",
          "deadline_missing_in_one" in C.compare(
              "By an unspecified date, Replit's user count will double.",
              "By about March 2022, Replit's registered user count will reach about 12 million."))

    # ---- the driver ----
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "criteria_agreement.py")],
                       capture_output=True, text=True, cwd=ROOT)
    check("DRIVER: exits 0 and reports a flag table over the real corpus",
          p.returncode == 0 and "MECHANICAL DISAGREEMENT SCREEN" in p.stdout, p.stderr[-400:])
    check("DRIVER: it states that it is a lower bound and carries false positives, never a bare rate",
          "LOWER bound" in p.stdout and "false positives" in p.stdout, p.stdout[-400:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
