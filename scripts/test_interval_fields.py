#!/usr/bin/env python3
"""Pundits P8A2-STATE decisions 4 and 5: the open score gets an interval, and every interval says how coarse it is.

Decision 4: plan P5 requires an interval beside every published score, and the open score had none.
Decision 5: a person on n recordings allows only C(2n-1, n) distinct resamples with replacement; at n = 5 that
is 126, so "20,000 resamples" overstated the interval's resolution. aggregate.interval_fields() writes
ci_low / ci_high and distinct_resamples for a contract-v2 study (pundits) on both blocks, and for the leaders
study (v1) only the blinded interval it always wrote, so the leaders results.json is byte-identical.
Synthetic rows, no data, no quota.
  .venv/bin/python scripts/test_interval_fields.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aggregate as A  # noqa: E402

FAILED = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


rng = random.Random(3)


def rows(n):
    return [{**{f"cal_{d}": rng.uniform(40, 80) for d in A.DIMS}, "coverage": 1.0} for _ in range(n)]


check("distinct resamples of 5 recordings is 126", A.distinct_resamples(5) == 126, str(A.distinct_resamples(5)))
check("one recording has one resample", A.distinct_resamples(1) == 1)
check("14 recordings have over 20 million", A.distinct_resamples(14) == 20058300, str(A.distinct_resamples(14)))

b, o = rows(5), rows(4)
v2b, v2o = A.interval_fields(b, True), A.interval_fields(o, True)
check("v2: the blinded block gets an interval and its resample count",
      {"ci_low", "ci_high", "distinct_resamples"} <= set(v2b) and v2b["distinct_resamples"] == 126, str(v2b))
check("v2: the open block gets them too (decision 4)",
      {"ci_low", "ci_high", "distinct_resamples"} <= set(v2o) and v2o["distinct_resamples"] == 35, str(v2o))
check("v2: the interval brackets the point estimate's range",
      v2b["ci_low"] is not None and v2b["ci_low"] <= v2b["ci_high"], str(v2b))
v1 = A.interval_fields(b, False)
check("v1 (leaders): exactly the fields it always had", set(v1) == {"ci_low", "ci_high"}, str(v1))
check("v1 (leaders): the same interval bootstrap_ci gives", (v1["ci_low"], v1["ci_high"]) == A.bootstrap_ci(b, A.WEIGHTS, A.DIMS))
check("no rows, no fields", A.interval_fields([], True) == {})

print(f"\n{'OK' if not FAILED else 'FAILED'}: {len(FAILED)} failing check(s)")
sys.exit(1 if FAILED else 0)
