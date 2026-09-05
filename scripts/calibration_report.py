#!/usr/bin/env python3
"""Measure how repeatable the rubric is on one fixture transcript.

The same transcript is graded N times by each judge under identical
conditions. Whatever spread appears is pure rubric-and-model noise, because
nothing about the input changed. That number sets the floor for how far apart
two leaders must be before a difference between them means anything.

Reports, per judge and per dimension: mean, standard deviation, range, and the
coefficient of variation. Also reports agreement on the discrete fields
(venue type, venue challenge, coverage, identity recognition), because a rubric
that produces stable numbers from unstable readings is not actually stable.

Usage:
  calibration_report.py --grades data/grades_smoke --out data/logs/calibration.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]
SUBCRITERIA = ["C1", "C2", "C3", "C4", "I1", "I2", "I3", "I4", "I5", "I6", "I7", "T1", "T2", "T3", "T4"]


def spread(vals: list[float]) -> dict:
    if not vals:
        return {}
    m = st.mean(vals)
    sd = st.stdev(vals) if len(vals) > 1 else 0.0
    return {
        "n": len(vals),
        "mean": round(m, 2),
        "sd": round(sd, 2),
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "range": round(max(vals) - min(vals), 1),
        "cv_pct": round(100 * sd / m, 1) if m else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    runs = defaultdict(list)
    for path in Path(args.grades).rglob("*.json"):
        if "_raw" in path.parts:
            continue
        r = json.loads(path.read_text())
        if "grade" not in r:
            continue
        runs[(r["judge"], r["mode"])].append(r)

    report = {"per_judge": {}, "cross_judge": {}, "notes": []}

    for (judge, mode), rs in sorted(runs.items()):
        g = [r["grade"] for r in rs]
        entry = {
            "runs": len(rs),
            "elapsed_sec": spread([r["elapsed_sec"] for r in rs]),
            "overall": spread([x["overall"] for x in g]),
            "dimensions": {d: spread([x["dimensions"][d]["score"] for x in g]) for d in DIMS},
            "coverage": spread([x["coverage"] for x in g]),
            "venue_challenge": spread([x["venue_challenge"] for x in g]),
            "venue_type_agreement": dict(Counter(x["venue_type"] for x in g)),
            "subject_share_pct": spread([x["subject_speech_share_pct"] for x in g]),
            "identity_recognised_runs": sum(1 for x in g if x["identity_confident"]),
            "asr_quality": dict(Counter(x["asr_quality"] for x in g)),
            "red_flag_count": spread([len(x["red_flags"]) for x in g]),
        }
        # Sub-criteria stability: how often does a code get the same score?
        sub_sd = {}
        for code in SUBCRITERIA:
            vals = []
            for x in g:
                m = {s["code"]: s["score"] for s in x["subcriteria"]}
                if code in m:
                    vals.append(m[code])
            if len(vals) > 1:
                sub_sd[code] = {"mode_score": Counter(vals).most_common(1)[0][0],
                                "sd": round(st.stdev(vals), 2),
                                "values": vals}
        entry["subcriteria_stability"] = sub_sd
        entry["most_unstable_subcriteria"] = sorted(
            sub_sd.items(), key=lambda kv: -kv[1]["sd"])[:4]
        report["per_judge"][f"{judge}|{mode}"] = entry

    # Cross-judge: how does the gap between judges compare to each judge's own noise?
    by_mode = defaultdict(dict)
    for (judge, mode), rs in runs.items():
        by_mode[mode][judge] = [r["grade"]["overall"] for r in rs]
    for mode, jd in by_mode.items():
        if len(jd) < 2:
            continue
        names = sorted(jd)
        a, b = jd[names[0]], jd[names[1]]
        within = st.mean([st.stdev(a) if len(a) > 1 else 0, st.stdev(b) if len(b) > 1 else 0])
        between = abs(st.mean(a) - st.mean(b))
        report["cross_judge"][mode] = {
            "judges": names,
            f"{names[0]}_mean": round(st.mean(a), 2),
            f"{names[1]}_mean": round(st.mean(b), 2),
            "between_judge_gap": round(between, 2),
            "mean_within_judge_sd": round(within, 2),
            "gap_in_units_of_noise": round(between / within, 1) if within else None,
        }

    # The number that actually matters downstream.
    all_sd = [e["overall"]["sd"] for e in report["per_judge"].values() if e["overall"].get("sd") is not None]
    if all_sd:
        noise = st.mean(all_sd)
        report["headline"] = {
            "mean_within_judge_sd_overall": round(noise, 2),
            "least_significant_difference_95pct": round(2.77 * noise, 1),
            "interpretation": (
                f"Repeat grading of one unchanged transcript moves the overall score by about "
                f"{noise:.1f} points of standard deviation. Two leaders whose overall scores differ by less "
                f"than roughly {2.77 * noise:.0f} points are not distinguishable by this method, and their "
                f"ranks should be read as a tie."
            ),
        }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
