#!/usr/bin/env python3
"""A judge that is failing hard stops the run, instead of burning the rest of the quota.

docs/PUNDITS-PLAN.md, P8: "Retry cap per judge: 15% of that judge's nominal calls
in each component. Reaching the cap stops the run with an error taxonomy, rather
than retrying further."

FOUND by adversarial audit 2026-09-16: no code implemented it. grade.py has no
internal retry loop at all, so the cap has to act on the FAILURE RATE of the run
in flight. Measured on the P8a2 top-up, against 64 nominal calls per judge:

    fable   25 failures  39% of nominal   (22 of them auth_or_quota)
    gemini  18 failures  28% of nominal

Fable's session window was empty for most of that run. Every call after the
window closed was quota spent to learn the same thing again. A budget stops
dispatching for that judge and lets the other one finish.

  CAP        the budget is a share of that judge's own scheduled calls
  FLOOR      a tiny run still allows at least one failure, so it cannot trip instantly
  SPEND      failures count against the budget and successes do not
  STOP       a judge over budget is stopped; the other judges keep going
  REPORT     the stop is a named taxonomy entry, never a silent truncation

  .venv/bin/python scripts/test_retry_budget.py
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
    spec = importlib.util.spec_from_file_location("grade_rb", REPO / "scripts" / "grade.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    print("retry budget")
    G = load()
    if not hasattr(G, "FailureBudget"):
        check("grade.py exposes FailureBudget", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    print("\n[CAP]")
    b = G.FailureBudget({"fable": 64, "gemini": 64}, share=0.15)
    check("15% of 64 scheduled calls is a budget of 9", b.cap("fable") == 9, str(b.caps))

    print("\n[FLOOR]")
    tiny = G.FailureBudget({"fable": 3}, share=0.15)
    check("a 3-call run still allows at least one failure, not zero",
          tiny.cap("fable") >= 1, str(tiny.caps))

    print("\n[SPEND]")
    for _ in range(9):
        b.record("fable", failed=True)
    check("nine failures sit exactly at the budget and do not stop the judge",
          not b.exhausted("fable"), f"fable failures={b.failures['fable']} cap={b.cap('fable')}")
    for _ in range(50):
        b.record("fable", failed=False)
    check("successes do not spend the budget",
          not b.exhausted("fable"), f"failures={b.failures['fable']}")
    b.record("fable", failed=True)
    check("the tenth failure exhausts it", b.exhausted("fable"), str(b.failures))

    print("\n[STOP]")
    check("the other judge is unaffected", not b.exhausted("gemini"), str(b.failures))
    check("a judge with no budget entry is never stopped", not b.exhausted("astra"))
    check("the reason names the judge, the count and the cap",
          "fable" in b.reason("fable") and "10" in b.reason("fable") and "9" in b.reason("fable"),
          b.reason("fable"))

    print("\n[REPORT]")
    check("an exhausted budget lists the judges it stopped",
          b.stopped() == ["fable"], str(b.stopped()))
    fresh = G.FailureBudget({"fable": 64}, share=0.15)
    check("a clean run stops nobody", fresh.stopped() == [], str(fresh.stopped()))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
