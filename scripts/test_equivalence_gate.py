#!/usr/bin/env python3
"""The equivalence gate every pundits gate uses: PASS, FAIL or INCONCLUSIVE, never "includes zero".

Pundits plan, gate vocabulary (Lakens 2017, TOST). A material bound ±Δ is fixed
before the data exists. PASS: the 90% interval lies entirely inside (−Δ, +Δ).
FAIL: it lies entirely outside [−Δ, +Δ]. INCONCLUSIVE: anything else. A wide
interval that merely contains 0 is INCONCLUSIVE, which is the whole point.

  .venv/bin/python scripts/test_equivalence_gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("equivalence gate")
    try:
        import gates
    except Exception as exc:
        check("gates is importable", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    eq = gates.equivalence
    check("a narrow interval inside the bounds passes", eq(-1.2, 1.8, 3.0) == "PASS")
    check("a wide interval that contains 0 is inconclusive, not a pass", eq(-15.0, 15.0, 3.0) == "INCONCLUSIVE")
    check("an interval crossing one bound is inconclusive", eq(1.0, 4.5, 3.0) == "INCONCLUSIVE")
    check("an interval entirely above the bound fails", eq(3.5, 7.0, 3.0) == "FAIL")
    check("an interval entirely below the negative bound fails", eq(-9.0, -3.2, 3.0) == "FAIL")
    check("touching the bound is not inside it", eq(-3.0, 1.0, 3.0) == "INCONCLUSIVE")
    check("an interval sitting exactly on the bound fails, since it is not inside", eq(3.0, 6.0, 3.0) == "FAIL")
    for bad in ((2.0, 1.0, 3.0), (-1.0, 1.0, 0.0), (-1.0, 1.0, -2.0), (None, 1.0, 3.0)):
        try:
            eq(*bad)
            refused = False
        except (ValueError, TypeError):
            refused = True
        check(f"malformed input {bad} is refused, not judged", refused)
    lo, hi = gates.mean_ci90([1.0, 2.0, 3.0, 4.0, 5.0], n=2000, seed=1)
    check("mean_ci90 brackets the sample mean", lo < 3.0 < hi, f"{lo}, {hi}")
    lo2, hi2 = gates.mean_ci90([1.0, 2.0, 3.0, 4.0, 5.0], n=2000, seed=1)
    check("and is reproducible for a fixed seed", (lo, hi) == (lo2, hi2))
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
