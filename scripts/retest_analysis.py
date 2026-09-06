#!/usr/bin/env python3
"""Within-judge test-retest across several transcripts, and what it implies.

Single-transcript test-retest tells you a judge is stable on ONE document. It
cannot tell you whether a judge ranks a set of documents the same way twice,
which is the property that matters for a leaderboard. This grades the same
stratified sample a second time with each judge and reports:

  within-judge r    does a judge reproduce its own ordering?
  between-judge r   do the two judges agree with each other?
  disattenuated r   the between-judge correlation the judges WOULD reach if
                    neither had any measurement noise

That last one is the point. A correlation between two noisy measures is
mathematically capped at sqrt(rel_A * rel_B). So a modest between-judge r can
mean two different things, and only the retest separates them:

  judges reliable, still disagree  -> they measure different constructs
  judges themselves noisy          -> the disagreement IS the noise

Usage:
  retest_analysis.py --r0 data/grades --r1 data/grades_retest \
      --out data/logs/retest_analysis.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]
MIN_SHARE = 15


def load(root: str) -> dict:
    """{(leader, source, judge): grade} for usable blinded grades."""
    out = {}
    for p in glob.glob(f"{root}/**/*.json", recursive=True):
        if "_raw" in p or p.endswith(".tmp"):
            continue
        try:
            g = json.load(open(p))
        except Exception:
            continue
        gr = g.get("grade") or {}
        if g.get("refused") or "dimensions" not in gr or g.get("mode") != "blinded":
            continue
        share = gr.get("subject_speech_share_pct")
        if isinstance(share, int) and share < MIN_SHARE:
            continue
        out[(g["leader_slug"], g["source_id"], g["judge"])] = gr
    return out


def corr(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(num / den, 3) if den else None


def icc31(pairs):
    """ICC(3,1): two-way mixed, consistency, single measure.

    The right form here because these two runs are the only runs of interest
    and a constant offset between them is tolerated. Bands (Koo & Li 2016):
    poor <0.50, moderate 0.50-0.75, good 0.75-0.90, excellent >0.90.
    """
    n = len(pairs)
    if n < 3:
        return None
    grand = st.mean([v for p in pairs for v in p])
    row_means = [st.mean(p) for p in pairs]
    col_means = [st.mean([p[j] for p in pairs]) for j in (0, 1)]
    ms_r = 2 * sum((rm - grand) ** 2 for rm in row_means) / (n - 1)
    ss_c = n * sum((cm - grand) ** 2 for cm in col_means)
    ss_t = sum((v - grand) ** 2 for p in pairs for v in p)
    ss_e = ss_t - sum(2 * (rm - grand) ** 2 for rm in row_means) - ss_c
    ms_e = ss_e / (n - 1)
    return round((ms_r - ms_e) / (ms_r + ms_e), 3) if (ms_r + ms_e) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r0", default="data/grades")
    ap.add_argument("--r1", default="data/grades_retest")
    ap.add_argument("--out", default="data/logs/retest_analysis.json")
    args = ap.parse_args()

    a, b = load(args.r0), load(args.r1)
    keys = sorted({(l, s) for (l, s, j) in b})
    report = {"transcripts": len(keys), "within": {}, "between": {}}

    print(f"WITHIN-JUDGE TEST-RETEST  ({len(keys)} transcripts, graded twice per judge)\n")

    rel = {}
    for judge in ("fable", "astra"):
        pairs, ids = [], []
        for (l, s) in keys:
            g0, g1 = a.get((l, s, judge)), b.get((l, s, judge))
            if g0 and g1:
                pairs.append((g0["overall"], g1["overall"]))
                ids.append(f"{l}/{s}")
        if len(pairs) < 3:
            print(f"  {judge}: only {len(pairs)} pairs, too few"); continue
        r = corr([p[0] for p in pairs], [p[1] for p in pairs])
        icc = icc31(pairs)
        diffs = [p[1] - p[0] for p in pairs]
        rel[judge] = r
        report["within"][judge] = {
            "n": len(pairs), "r": r, "icc3_1": icc,
            "mean_abs_diff": round(st.mean([abs(d) for d in diffs]), 2),
            "sd_of_diff": round(st.pstdev(diffs), 2),
            "max_abs_diff": round(max(abs(d) for d in diffs), 1),
            "bias_run2_minus_run1": round(st.mean(diffs), 2),
            "score_sd": round(st.pstdev([p[0] for p in pairs]), 2),
        }
        e = report["within"][judge]
        print(f"  {judge.upper():6} n={e['n']}  r={r}  ICC(3,1)={icc}")
        print(f"         mean|diff|={e['mean_abs_diff']}  SD(diff)={e['sd_of_diff']}  "
              f"max|diff|={e['max_abs_diff']}  drift={e['bias_run2_minus_run1']:+}")
        for d in DIMS:
            dp = [(a[(l, s, judge)]["dimensions"][d]["score"],
                   b[(l, s, judge)]["dimensions"][d]["score"])
                  for (l, s) in keys if (l, s, judge) in a and (l, s, judge) in b]
            print(f"         {d:20} r={corr([x for x, _ in dp], [y for _, y in dp])}")
        print()

    # Between-judge on the SAME transcripts, so n and score range match.
    bp = [(a[(l, s, "fable")]["overall"], a[(l, s, "astra")]["overall"])
          for (l, s) in keys if (l, s, "fable") in a and (l, s, "astra") in a]
    r_between = corr([p[0] for p in bp], [p[1] for p in bp]) if len(bp) >= 3 else None
    report["between"] = {"n": len(bp), "r": r_between}
    print(f"  BETWEEN-JUDGE on the same {len(bp)} transcripts: r={r_between}")

    if r_between and rel.get("fable") and rel.get("astra") and rel["fable"] > 0 and rel["astra"] > 0:
        cap = math.sqrt(rel["fable"] * rel["astra"])
        dis = r_between / cap if cap else None
        report["attenuation"] = {
            "max_possible_between_r": round(cap, 3),
            "disattenuated_r": round(min(dis, 1.0), 3) if dis else None,
            "raw_disattenuated": round(dis, 3) if dis else None,
        }
        print(f"\n  Noise ceiling on between-judge r: sqrt({rel['fable']} x {rel['astra']}) = {cap:.3f}")
        print(f"  Disattenuated between-judge r    : {dis:.3f}")
        if dis >= 0.90:
            verdict = ("The judges measure essentially the SAME thing. The observed "
                       "between-judge gap is almost entirely their own measurement noise.")
        elif dis >= 0.75:
            verdict = ("Largely the same construct, with some genuine disagreement left "
                       "after noise is accounted for.")
        else:
            verdict = ("Real disagreement. Even with noise removed the judges rank these "
                       "transcripts differently, so they are weighting something differently.")
        report["verdict"] = verdict
        print(f"\n  VERDICT: {verdict}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(f"\n  written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
