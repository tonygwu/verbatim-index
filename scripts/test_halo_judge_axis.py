#!/usr/bin/env python3
"""A halo whose judges disagree in sign is not a panel finding, and must not read as one.

FOUND by adversarial audit 2026-09-16. `paired_halo()` resamples TRANSCRIPTS and
averages the judges inside each transcript, so judge disagreement never widens
the interval. On the P8a2 board the two judges' halos have opposite signs for 8
of 10 people, and the one halo whose interval excluded zero was the worst case:

    asmongold   halo +2.56  95% CI [+1.64, +3.67]
                fable +6.57   gemini -1.45   gap 8.02

An 8-point disagreement in opposite directions was published with a 2-point
interval that excludes zero. That reads as "disclosure raises this person's
score" when it is one judge's effect and the other judge says the opposite.

With two judges there is no honest way to bootstrap the judge axis: the
between-judge variance would be estimated from two points. So the fix is not a
wider interval, it is refusing to call such a halo significant, and reporting the
per-judge values next to it.

  GAP        the spread between judges is reported
  SIGNS      agreement in sign is reported
  GATE       significance needs the interval to exclude zero AND the judges to agree
  CLEAN      a halo both judges agree on, with an interval clear of zero, is significant

  .venv/bin/python scripts/test_halo_judge_axis.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("agg_hja", REPO / "scripts" / "aggregate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    print("halo judge axis")
    A = load()
    if not hasattr(A, "halo_judge_agreement"):
        check("aggregate.py exposes halo_judge_agreement", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    # The real asmongold case.
    asm = A.halo_judge_agreement({"fable": 6.57, "gemini": -1.45}, ci_low=1.64, ci_high=3.67)
    print("\n[GAP]")
    check("the spread between judges is reported", round(asm["judge_gap"], 2) == 8.02, str(asm))

    print("\n[SIGNS]")
    check("opposite signs are reported as disagreement", asm["judges_agree_sign"] is False, str(asm))

    print("\n[GATE]")
    check("an interval clear of zero is NOT significant while the judges disagree",
          asm["panel_significant"] is False, str(asm))
    check("and the reason says why", "sign" in (asm.get("significance_note") or "").lower(), str(asm))

    print("\n[CLEAN]")
    # ben-shapiro: both judges negative, interval excludes zero.
    ben = A.halo_judge_agreement({"fable": -1.83, "gemini": -2.06}, ci_low=-3.84, ci_high=-0.08)
    check("a halo both judges agree on, with an interval clear of zero, is significant",
          ben["panel_significant"] is True and ben["judges_agree_sign"] is True, str(ben))
    # ezra-klein: judges disagree AND the interval spans zero.
    ezra = A.halo_judge_agreement({"fable": -1.59, "gemini": 0.67}, ci_low=-1.42, ci_high=0.50)
    check("a halo whose interval spans zero is not significant either",
          ezra["panel_significant"] is False, str(ezra))
    # A single-judge panel has no agreement to report and cannot be significant on that basis.
    one = A.halo_judge_agreement({"fable": 3.0}, ci_low=1.0, ci_high=5.0)
    check("one judge cannot agree with itself, so the flag is None rather than True",
          one["judges_agree_sign"] is None and one["panel_significant"] is False, str(one))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
