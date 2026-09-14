#!/usr/bin/env python3
"""The halo measures what name disclosure alone changes, on matched pairs, under one calibration.

Pundits plan, P5. For leaders, halo is open mean minus blinded mean, each
aggregated and calibrated separately, which mixes a disclosure effect with
different transcripts and different calibration maps. For a contract v2 study:

  - calibrate(..., shared=True) fits ONE map per (judge, model, dimension) on
    blinded run-0 grades, and the same map is applied to both modes;
  - paired_halo() matches each open grade to the blinded grade of the same
    transcript, judge and model, and averages calibrated open minus calibrated
    blinded over those pairs, with a bootstrap interval and n_pairs.

  RAW-RECOVERY     a +6 disclosure effect injected on one judge only comes back
                   as exactly +6 in that judge's raw halo and 0 in the other's
  UNSCALED         with calibration not rescaling, the person halo is the plain
                   mean of the pair differences (+3 when half the pairs carry +6)
  SCALED           with calibration rescaling, each pair difference is scaled by
                   pooled_sd / judge_sd, and the halo matches that exactly
  NULL             with no effect injected, the interval contains 0
  UNPAIRED         an open grade with no blinded partner is never used
  SHARED-KEYS      shared calibration keys carry no mode and use blinded run 0 only

  .venv/bin/python scripts/test_paired_halo.py
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("agg_halo", REPO / "scripts" / "aggregate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def grade(A, slug, sid, judge, mode, base, run=0):
    # served_model lives in telemetry, as grade.py writes it and served_model() reads it.
    return {"leader_slug": slug, "source_id": sid, "judge": judge, "mode": mode, "run": run,
            "telemetry": {"served_model": f"{judge}-model"},
            "grade": {"dimensions": {d: {"score": base} for d in A.DIMS}, "coverage": 1.0}}


def corpus(A, effect_a: float, spread: bool, n_transcripts: int = 30, seed: int = 7):
    rng = random.Random(seed)
    out = []
    for t in range(n_transcripts):
        # spread=True gives each judge a real distribution (sd >= 3, n >= 25) so
        # calibration rescales; spread=False keeps every score identical per judge.
        b_a = 50 + (rng.randint(-12, 12) if spread else 0)
        b_b = 60 + (rng.randint(-6, 6) if spread else 0)
        out.append(grade(A, "p", f"s{t}", "fable", "blinded", b_a))
        out.append(grade(A, "p", f"s{t}", "fable", "open", b_a + effect_a))
        out.append(grade(A, "p", f"s{t}", "astra", "blinded", b_b))
        out.append(grade(A, "p", f"s{t}", "astra", "open", b_b))
    return out


def main() -> int:
    print("paired halo")
    A = load()
    A.configure_scoring(json.loads((REPO / "profiles" / "pundits.json").read_text()))
    if not hasattr(A, "paired_halo"):
        check("aggregate.py exposes paired_halo", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    print("\n[SHARED-KEYS]")
    grades = corpus(A, 6.0, spread=True)
    grades.append(grade(A, "p", "s0", "fable", "blinded", 99, run=1))
    params = A.calibrate(grades, shared=True)
    check("shared calibration keys carry no mode", all(k[2] == "shared" for k in params), str(list(params)[:2]))
    fable_key = ("fable", "fable-model", "shared", A.DIMS[0])
    check("they are fitted on blinded run-0 grades only", params[fable_key]["n"] == 30, str(params[fable_key]))

    print("\n[RAW-RECOVERY / UNSCALED]")
    flat = corpus(A, 6.0, spread=False)
    p_flat = A.calibrate(flat, shared=True)
    h = A.paired_halo(flat, p_flat)["p"]
    check("the injected judge's raw halo is exactly +6", h["by_judge_raw"]["fable"] == 6.0, str(h["by_judge_raw"]))
    check("the other judge's raw halo is exactly 0", h["by_judge_raw"]["astra"] == 0.0, str(h["by_judge_raw"]))
    check("with no rescaling the person halo is the mean pair difference, +3", abs(h["overall"] - 3.0) < 1e-9, str(h))
    check("n_pairs counts every matched pair", h["n_pairs"] == 60, str(h["n_pairs"]))

    print("\n[SCALED]")
    h = A.paired_halo(grades, params)["p"]
    check("the raw halo still recovers +6", abs(h["by_judge_raw"]["fable"] - 6.0) < 1e-9, str(h["by_judge_raw"]))
    ratios = []
    for dim in A.DIMS:
        p = params[("fable", "fable-model", "shared", dim)]
        ratios.append(p["pooled_sd"] / p["judge_sd"] if p["rescaled"] else 1.0)
    weights = A.WEIGHTS
    expected_fable = sum(weights[d] * 6.0 * r for d, r in zip(A.DIMS, ratios))
    expected = (expected_fable * 30 + 0.0 * 30) / 60
    check("the calibrated halo equals +6 scaled by pooled_sd / judge_sd, averaged over pairs",
          abs(h["overall"] - expected) < 0.02, f"got {h['overall']}, expected {expected}")

    print("\n[NULL]")
    null = corpus(A, 0.0, spread=True, seed=11)
    h = A.paired_halo(null, A.calibrate(null, shared=True))["p"]
    check("with no effect the interval contains 0", h["ci_low"] <= 0.0 <= h["ci_high"], str(h))

    print("\n[UNPAIRED]")
    lonely = corpus(A, 6.0, spread=False, n_transcripts=4)
    lonely.append(grade(A, "p", "orphan", "fable", "open", 90))
    h = A.paired_halo(lonely, A.calibrate(lonely, shared=True))["p"]
    check("an open grade with no blinded partner is not paired", h["n_pairs"] == 8, str(h["n_pairs"]))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
