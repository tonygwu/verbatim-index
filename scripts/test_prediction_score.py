#!/usr/bin/env python3
"""The two log-scoring rules, pinned to the tables they were specified with.

Both tables come from the operator's specification on 2026-09-15 and are
reproduced here to three decimals. If a refactor moves a single figure, this
fails, which is the point: the scoring rule is the published number's definition.

It also pins the properties the rules exist for:
  - the baseline-only rule pays ZERO in expectation at every p, so calling a
    thousand long shots cannot generate points by volume;
  - the speaker-probability rule pays only when q sits on the correct side of p;
  - p and q are clamped rather than allowed to run to infinity, and every clamp
    is reported on the result.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
from prediction_score import CLAMP, expected_points, score  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def close(a, b, tol=0.005):
    return abs(a - b) <= tol


def main() -> int:
    # --- baseline-only rule, the operator's first table ---
    # p, correct, wrong. The 0.1% row of the source table (+9.97 / -0.010) is
    # deliberately absent: it lies beyond CLAMP, so this rule cannot produce it.
    table_a = [(0.50, 1.00, -1.000), (0.30, 1.74, -0.750), (0.20, 2.32, -0.580),
               (0.10, 3.32, -0.370), (0.05, 4.32, -0.230), (0.02, 5.64, -0.120),
               (0.01, 6.64, -0.067)]
    for p, right, wrong in table_a:
        got_r, got_w = score(True, p)["points"], score(False, p)["points"]
        check(f"BASELINE p={p:.2f}: correct {right:+.2f}, wrong {wrong:+.3f}",
              close(got_r, right, 0.01) and close(got_w, wrong, 0.01),
              f"got {got_r:+.3f} / {got_w:+.3f}")
    check("BASELINE: expected points are ZERO at every p, so volume cannot pay",
          all(close(expected_points(p), 0.0, 1e-9) for p, _, _ in table_a),
          str([round(expected_points(p), 12) for p, _, _ in table_a]))

    # --- speaker-probability rule at q = 0.75, the operator's second table ---
    table_b = [(0.50, 0.58, -1.00), (0.20, 1.91, -1.68), (0.10, 2.91, -1.85),
               (0.05, 3.91, -1.93), (0.01, 6.23, -1.99)]
    for p, right, wrong in table_b:
        got_r, got_w = score(True, p, 0.75)["points"], score(False, p, 0.75)["points"]
        check(f"SPEAKER q=0.75 p={p:.2f}: right {right:+.2f}, wrong {wrong:+.2f}",
              close(got_r, right, 0.01) and close(got_w, wrong, 0.01),
              f"got {got_r:+.3f} / {got_w:+.3f}")
    check("SPEAKER: agreeing with the baseline (q == p) scores zero either way",
          close(score(True, 0.3, 0.3)["points"], 0.0) and close(score(False, 0.3, 0.3)["points"], 0.0))
    check("SPEAKER: a q on the WRONG side of p loses when the call lands",
          score(True, 0.7, 0.2)["points"] < 0 and score(False, 0.2, 0.7)["points"] < 0)

    # --- the clamp, which is a real case in this corpus, not a hypothetical ---
    r = score(False, 0.5, 1.0)
    check("CLAMP: a stated certainty that misses is bounded, and says it was clamped",
          r["clamped"] == ["q"] and close(r["points"], -5.64, 0.01) and r["q_raw"] == 1.0,
          str(r))
    r = score(True, 0.0)
    check("CLAMP: p=0 is bounded rather than +infinity, and says so",
          r["clamped"] == ["p"] and close(r["points"], 6.64, 0.01) and r["p_raw"] == 0.0, str(r))
    check("CLAMP: a value inside the range is never marked clamped",
          score(True, 0.3, 0.6)["clamped"] == [])
    check("CLAMP: the constant is visible and is one part in a hundred", CLAMP == 0.01)

    # --- inputs are refused rather than coerced ---
    for bad, why in ((-0.1, "negative p"), (1.4, "p above 1"), ("0.3", "p as a string"),
                     (float("nan"), "p as NaN")):
        try:
            score(True, bad)
            ok = False
        except ValueError:
            ok = True
        check(f"INPUT: {why} raises rather than being coerced", ok)
    try:
        score(1, 0.5)                      # 1 is truthy but is not a bool
        ok = False
    except ValueError:
        ok = True
    check("INPUT: a non-bool outcome raises, so a truthy 1 cannot pass as 'occurred'", ok)

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
