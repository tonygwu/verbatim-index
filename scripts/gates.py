#!/usr/bin/env python3
"""Gate verdicts for the pundits study: PASS, FAIL or INCONCLUSIVE, never "the interval includes zero".

The gate vocabulary in docs/PUNDITS-PLAN.md follows Lakens (2017), two one-sided
tests. A material bound ±Δ is fixed before the data exists, and the verdict
reads a 90% interval:

  PASS          the interval lies entirely inside (−Δ, +Δ)
  FAIL          the interval lies entirely outside [−Δ, +Δ]
  INCONCLUSIVE  anything else

A wide interval that merely contains 0 is INCONCLUSIVE. That is the case the
older "interval includes zero" reading silently turned into a pass.
"""
from __future__ import annotations

import math
import random


def equivalence(lo: float, hi: float, delta: float) -> str:
    """Verdict for a 90% interval [lo, hi] against the material bound ±delta."""
    for name, v in (("lo", lo), ("hi", hi), ("delta", delta)):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or math.isnan(v):
            raise TypeError(f"{name} must be a number, got {v!r}")
    if lo > hi:
        raise ValueError(f"interval is inverted: lo {lo} > hi {hi}")
    if delta <= 0:
        raise ValueError(f"the material bound must be positive, got {delta}")
    if -delta < lo and hi < delta:
        return "PASS"
    if lo >= delta or hi <= -delta:
        return "FAIL"
    return "INCONCLUSIVE"


def mean_ci90(values: list[float], n: int = 20000, seed: int = 20260914) -> tuple[float, float]:
    """A seeded percentile bootstrap 90% interval for the mean of `values`."""
    if not values:
        raise ValueError("no values")
    rng = random.Random(seed)
    k = len(values)
    draws = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return draws[int(0.05 * n)], draws[min(int(0.95 * n), n - 1)]
