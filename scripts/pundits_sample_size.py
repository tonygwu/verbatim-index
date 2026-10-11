#!/usr/bin/env python3
"""P10's sample-size check for G-judge-lean, from the pilot's own grades (docs/PUNDITS-PLAN.md, P10).

The plan asks, after P8 and BEFORE P9: using pilot estimates of the per-transcript judge-minus-others sd and
the within-person ICC (the share of that variance which sits between people), project the 90% half-width of
G-judge-lean at 40 people x 12 transcripts. A projection above 2.0 means the pass region (equivalence,
delta 3) is too small, and the user should add people or accept a likely INCONCLUSIVE.

What is computed, and the choices made (each one is a judgment call, stated so it can be challenged):
  - d per transcript: each judge's blinded `overall` minus the mean of the other judges' on the same
    transcript, on transcripts every judge graded with no validation error. With two judges the two d's are
    mirror images, so one is reported. Raw scores: calibration adds a constant per judge, which the
    `score ~ transcript + judge + ...` model absorbs, so it does not change d's spread.
  - sd: the standard deviation of d around its grand mean, over transcripts.
  - ICC: one-way random-effects ICC(1) of d by person (ANOVA, unequal group sizes), floored at 0.
  - Projection for nL left and nR right people with m transcripts each: a person's mean d has variance
    sd^2 * (ICC + (1 - ICC) / m); the left-minus-right difference of group means has variance
    v * (1/nL + 1/nR); the 90% half-width is 1.645 times its square root. Heterodox people do not enter the
    left-minus-right gap, so the split is a parameter; no lean label is read (only schedule.py,
    pundits_roster.py and the P3 probe may read them).
  - Uncertainty: 2,000 bootstrap resamples of PEOPLE (seeded), each recomputing sd, ICC and the projection,
    because 10 pilot people make the ICC itself noisy.
Reads grades only; spends no quota.
    .venv/bin/python scripts/pundits_sample_size.py --data data-pundits [--splits 20/20,16/16,13/13] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

Z90 = 1.6448536269514722


def load_d(grades_root: Path, mode: str = "blinded") -> dict[str, list[float]]:
    """{person: [d per transcript]} for the first judge in name order, minus the mean of the others."""
    by_t: dict[str, dict[str, float]] = defaultdict(dict)
    person: dict[str, str] = {}
    judges = sorted(p.name for p in grades_root.iterdir() if p.is_dir() and not p.name.startswith("_"))
    if len(judges) < 2:
        raise SystemExit(f"{grades_root}: {judges} -- need at least two judges' grades")
    for j in judges:
        for f in (grades_root / j).glob("*/*.json"):
            g = json.loads(f.read_text())
            if g.get("mode") != mode or g.get("validation_errors"):
                continue
            ov = (g.get("grade") or {}).get("overall")
            if not isinstance(ov, (int, float)):
                continue
            tid = g["transcript_id"]
            if j in by_t[tid]:
                raise SystemExit(f"{tid}: two {mode} grades from {j}; one per judge is expected")
            by_t[tid][j] = float(ov)
            person[tid] = g["leader_slug"]
    out: dict[str, list[float]] = defaultdict(list)
    lead = judges[0]
    for tid, s in sorted(by_t.items()):
        if set(s) != set(judges):
            continue
        others = [s[j] for j in judges if j != lead]
        out[person[tid]].append(s[lead] - sum(others) / len(others))
    return dict(out)


def sd_icc(groups: dict[str, list[float]]) -> tuple[float, float]:
    """(sd of d around the grand mean, ICC(1) by person, floored at 0)."""
    xs = [x for g in groups.values() for x in g]
    n, k = len(xs), len(groups)
    if n < 3 or k < 2:
        raise SystemExit(f"too little data: {n} transcripts over {k} people")
    grand = statistics.fmean(xs)
    ssb = sum(len(g) * (statistics.fmean(g) - grand) ** 2 for g in groups.values())
    ssw = sum((x - statistics.fmean(g)) ** 2 for g in groups.values() for x in g)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - sum(len(g) ** 2 for g in groups.values()) / n) / (k - 1)
    icc = (msb - msw) / (msb + (n0 - 1) * msw) if (msb + (n0 - 1) * msw) > 0 else 0.0
    return statistics.stdev(xs), max(0.0, icc)


def half_width(sd: float, icc: float, n_left: int, n_right: int, m: int) -> float:
    v = sd ** 2 * (icc + (1 - icc) / m)
    return Z90 * math.sqrt(v * (1 / n_left + 1 / n_right))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="the pundits data checkout (holds grades/)")
    ap.add_argument("--splits", default="20/20,16/16,13/13", help="left/right people counts to project")
    ap.add_argument("--per-person", type=int, default=12)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)
    groups = load_d(args.data / "grades")
    sd, icc = sd_icc(groups)
    splits = [tuple(int(x) for x in s.split("/")) for s in args.splits.split(",")]
    rng = random.Random(20261011)
    people = sorted(groups)
    boot = {s: [] for s in splits}
    for _ in range(args.boot):
        pick = [rng.choice(people) for _ in people]
        g = {f"{p}#{i}": groups[p] for i, p in enumerate(pick)}
        try:
            bsd, bicc = sd_icc(g)
        except SystemExit:
            continue
        for s in splits:
            boot[s].append(half_width(bsd, bicc, s[0], s[1], args.per_person))
    n_t = sum(len(g) for g in groups.values())
    rep = {"people": len(groups), "transcripts": n_t, "sd": round(sd, 3), "icc": round(icc, 3),
           "per_person": args.per_person, "planning_assumption_half_width_20_20": round(half_width(5, 0.3, 20, 20, 12), 3),
           "projections": {f"{a}/{b}": {"half_width": round(half_width(sd, icc, a, b, args.per_person), 3),
                                        "boot_p5": round(sorted(boot[(a, b)])[int(0.05 * len(boot[(a, b)]))], 3),
                                        "boot_p95": round(sorted(boot[(a, b)])[int(0.95 * len(boot[(a, b)])) - 1], 3),
                                        "over_2": (half_width(sd, icc, a, b, args.per_person) > 2.0)}
                           for a, b in splits}}
    print(json.dumps(rep, indent=1))
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
