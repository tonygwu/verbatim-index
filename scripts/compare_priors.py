#!/usr/bin/env python3
"""Did telling the prior assessor to price the DEADLINE change its answers?

    .venv/bin/python scripts/compare_priors.py --run <run> --a priors_v1_event --b priors

MEASURED 2026-09-15 on the first pass: 12 of 17 scored misses priced between 0.2
and 0.6 were things that HAPPENED, just after the deadline. Cybertruck
deliveries, New Shepard's first crewed flight, New Glenn's first launch, Comma's
Navigate on Openpilot, UALink 1.0. The assessor was pricing "will this happen"
while the resolver was testing "did this happen BY the date", so every slipped
timeline was charged to the speaker twice: once as a miss, and once through a p
that was too high to have priced the slip.

That is a defect in the prompt, not in the speakers. Being late IS being wrong,
and the score should say so once; it should not say so twice. This compares the
two passes over the same predictions so the size of the correction is a measured
number rather than a claim.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load(d: Path) -> dict[str, dict]:
    return {json.loads(f.read_text())["prediction_id"]: json.loads(f.read_text())
            for f in sorted(d.glob("*/*.json"))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--a", default="priors_v1_event", help="the earlier pass")
    ap.add_argument("--b", default="priors", help="the later pass")
    ap.add_argument("--scores", type=Path, default=None,
                    help="scores.json, to split the shift by what actually happened")
    args = ap.parse_args()

    a, b = load(args.run / args.a), load(args.run / args.b)
    both = sorted(set(a) & set(b))
    if not both:
        raise SystemExit(f"no prediction has a prior in both {args.a} and {args.b}")
    d = [b[k]["p"] - a[k]["p"] for k in both]
    print(f"{len(both)} predictions priced by both passes")
    print(f"  mean p   {args.a}: {statistics.mean(a[k]['p'] for k in both):.3f}")
    print(f"  mean p   {args.b}: {statistics.mean(b[k]['p'] for k in both):.3f}")
    print(f"  mean shift {statistics.mean(d):+.3f}   sd {statistics.stdev(d) if len(d) > 1 else 0:.3f}")
    print(f"  lowered {sum(1 for x in d if x < -0.01)}, raised {sum(1 for x in d if x > 0.01)}, "
          f"unchanged {sum(1 for x in d if abs(x) <= 0.01)}")

    if args.scores:
        doc = json.loads(args.scores.read_text())
        out = {r["prediction_id"]: r.get("outcome") for r in doc["predictions"]}
        for verdict in ("occurred", "not_occurred"):
            ks = [k for k in both if out.get(k) == verdict]
            if ks:
                sh = [b[k]["p"] - a[k]["p"] for k in ks]
                print(f"  on predictions that {verdict:13} n={len(ks):3}  mean shift {statistics.mean(sh):+.3f}")
        print("\n  A correction that lowers p on the MISSES far more than on the hits would be "
              "hindsight leaking in;\n  a correction that lowers p roughly evenly is the assessor "
              "pricing slippage it could not see before.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
