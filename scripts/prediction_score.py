#!/usr/bin/env python3
"""Log scores for a resolved prediction, against an ex-ante baseline probability.

Pure arithmetic. No I/O, no model calls, no clock. Two rules, both in base 2 so a
point is a bit: one doubling of the odds you assign to what actually happened.

  SPEAKER-PROBABILITY RULE, used when the speaker's own probability q is known or
  has been inferred from how strongly they stated the claim:

      E occurred      S = log2(q / p)
      E did not       S = log2((1 - q) / (1 - p))

  BASELINE-ONLY RULE, used when a prediction is a bare assertion and no q is
  assigned. The reward is the surprisal of the event; the miss penalty is set so
  that a predictor who simply calls events at the baseline rate scores zero in
  expectation, which is what stops "spray a thousand long shots" from paying:

      E occurred      R(p) = -log2(p)
      E did not       L(p) = -(p / (1 - p)) * log2(1 / p)

      because  p * R(p) + (1 - p) * L(p) = 0.

WHY p AND q ARE CLAMPED. A log score is unbounded at the ends: p = 0 with the
event occurring is +infinity, and q = 1 with the event not occurring is
-infinity. This is not hypothetical here. Three of the five stated probabilities
in the corpus are exactly 1.0. Both inputs are therefore clamped into
[CLAMP, 1 - CLAMP] and every clamp is REPORTED on the result, never applied
silently, because a clamped score is a bounded stand-in for an unbounded one and
a reader must be able to see which scores are at the wall.

CLAMP is 0.01, one part in a hundred, so a certainty capped at 0.99 costs at most
log2(0.01 / (1 - p)) when wrong. At p = 0.5 that is -5.64 points. Choosing it is
a judgement: a tighter clamp punishes a wrong certainty harder and makes a single
record dominate a leader's mean.
"""
from __future__ import annotations

import math

CLAMP = 0.01


def _clamp(value: float, name: str) -> tuple[float, bool]:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or math.isnan(float(value)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    v = float(value)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"{name} must be a probability in [0, 1], got {v!r}")
    lo, hi = CLAMP, 1.0 - CLAMP
    if v < lo:
        return lo, True
    if v > hi:
        return hi, True
    return v, False


def score(occurred: bool, p: float, q: float | None = None) -> dict:
    """Points for one resolved prediction.

    occurred: did the predicted event happen.
    p:        the ex-ante baseline probability, from a market or an assessor.
    q:        the speaker's own probability, stated or inferred. None uses the
              baseline-only rule.

    Returns the points, the rule used, the values after clamping and which inputs
    were clamped. A caller that drops `clamped` is discarding the warning.
    """
    if not isinstance(occurred, bool):
        raise ValueError(f"occurred must be a bool, got {occurred!r}")
    pc, p_clamped = _clamp(p, "p")
    out = {"p": pc, "p_raw": float(p), "q": None, "q_raw": None,
           "occurred": occurred, "clamped": [], "rule": None, "points": None}
    if p_clamped:
        out["clamped"].append("p")

    if q is None:
        out["rule"] = "baseline_only"
        out["points"] = -math.log2(pc) if occurred else (pc / (1.0 - pc)) * math.log2(pc)
        return out

    qc, q_clamped = _clamp(q, "q")
    if q_clamped:
        out["clamped"].append("q")
    out["q"], out["q_raw"] = qc, float(q)
    out["rule"] = "speaker_probability"
    out["points"] = math.log2(qc / pc) if occurred else math.log2((1.0 - qc) / (1.0 - pc))
    return out


def expected_points(p: float, q: float | None = None) -> float:
    """What this rule pays on average to a predictor whose calls are TRUE at rate p.

    Zero for the baseline-only rule at every p, which is the property that makes it
    unexploitable by volume. Positive for the speaker-probability rule only when q
    is on the correct side of p.
    """
    pc, _ = _clamp(p, "p")
    hit = score(True, p, q)["points"]
    miss = score(False, p, q)["points"]
    return pc * hit + (1.0 - pc) * miss
