#!/usr/bin/env python3
"""Compare two verdict sets over the SAME extracted candidates.

    .venv/bin/python scripts/verifier_compare.py --before <dir> --after <dir>

Spends no model calls. Both directories hold the same records; only the
`verification` block differs, because the second was produced by re-running the
verify stage with a different verifier.

WHAT THIS IS FOR. repo-1's supplemental corpus was verified largely by Fable,
while the published board is largely Gemini-verified. Fable is the more
permissive of the two, so records that entered on Fable's standard would put
people on the board against a bar nobody already ranked had to clear. This
measures the size of that gap on the real corpus rather than extrapolating from
one leader.

IT ALSO ISOLATES THE EXTRACTOR, WHICH NOTHING ELSE HAS. The supplemental corpus
is extractor-mixed: some sources were read by Astra and the rest by Fable. Every
record here is re-verified by the SAME verifier, so splitting the result by
extractor holds the verifier fixed and shows what the extractor is worth on its
own. The published corpus cannot answer that: its extractor and its verifier
move together.

READ A DIFFERENCE AS DISAGREEMENT, NOT AS A BUG. Verification is not
deterministic. Re-running Gemini on a record Gemini had already verified has
been observed to flip a verdict, so a record changing status is expected at some
rate and is not by itself evidence of anything.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def load(d: pathlib.Path) -> dict[str, dict]:
    """Every record by prediction_id, accepted or not."""
    out: dict[str, dict] = {}
    # see phase2_resolvability.load: _runs/ holds error logs, not records
    for f in sorted(x for x in d.glob("*/*.jsonl") if not x.parent.name.startswith("_")):
        for line in f.read_text().split("\n"):
            if not line.strip():
                continue
            r = json.loads(line)
            pid = r.get("prediction_id")
            if pid:
                out[pid] = r
    return out


def harness(r: dict, block: str) -> str:
    return ((r.get(block) or {}).get("harness")) or "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", type=pathlib.Path, required=True)
    ap.add_argument("--after", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args()

    a, b = load(args.before), load(args.after)
    shared = sorted(set(a) & set(b))
    if not shared:
        raise SystemExit(f"no prediction_id appears in both {args.before} and {args.after}")
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))

    print(f"{len(a)} records before, {len(b)} after, {len(shared)} shared")
    if only_a or only_b:
        print(f"  WARNING: {len(only_a)} only in before, {len(only_b)} only in after; "
              f"the two sets should hold the same candidates")

    vb = collections.Counter(harness(a[p], "verification") for p in shared)
    va = collections.Counter(harness(b[p], "verification") for p in shared)
    print(f"\n  verifier before: {dict(vb)}")
    print(f"  verifier after:  {dict(va)}")

    # A PARTIAL re-verification looks like agreement, because most records still
    # carry their original verdict. Refuse to report a rate until the after set is
    # actually uniform, or say plainly how much of it moved.
    changed = [p for p in shared
               if harness(a[p], "verification") != harness(b[p], "verification")]
    dominant = va.most_common(1)[0] if va else ("none", 0)
    print(f"\n  records whose verifier CHANGED: {len(changed)} of {len(shared)}")
    if dominant[1] < len(shared):
        print(f"  WARNING: the after set is not uniform. {dominant[0]} verified "
              f"{dominant[1]} of {len(shared)}, so this is a PARTIAL re-verification and "
              f"the rates below are dominated by records that never moved. Finish the run.")

    # The headline: what each verifier accepted, over the same candidates.
    acc_b = sum(1 for p in shared if a[p].get("accepted"))
    acc_a = sum(1 for p in shared if b[p].get("accepted"))
    print(f"\nACCEPTED over the same {len(shared)} candidates")
    print(f"  before  {acc_b:4}  ({acc_b / len(shared):.0%})")
    print(f"  after   {acc_a:4}  ({acc_a / len(shared):.0%})")
    if acc_b:
        print(f"  the new verifier keeps {acc_a / acc_b:.0%} of what the old one kept")

    flips = collections.Counter()
    for p in shared:
        flips[(bool(a[p].get("accepted")), bool(b[p].get("accepted")))] += 1
    print(f"\n  kept by both        {flips[(True, True)]:4}")
    print(f"  dropped by the new  {flips[(True, False)]:4}")
    print(f"  added by the new    {flips[(False, True)]:4}")
    print(f"  rejected by both    {flips[(False, False)]:4}")

    # Per leader, because that is what moves the board.
    print(f"\n{'leader':20} {'before':>7} {'after':>6} {'kept':>6}")
    per = collections.defaultdict(lambda: [0, 0])
    for p in shared:
        s = a[p]["leader_slug"]
        per[s][0] += bool(a[p].get("accepted"))
        per[s][1] += bool(b[p].get("accepted"))
    for s, (x, y) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        if x or y:
            print(f"{s:20} {x:7} {y:6} {(y / x) if x else 0:6.0%}")

    # The extractor axis, with the verifier held fixed by construction.
    print(f"\n\nEXTRACTOR EFFECT, verifier held fixed at the AFTER verifier")
    ext = collections.defaultdict(lambda: [0, 0])
    for p in shared:
        e = harness(a[p], "extraction")
        ext[e][0] += 1
        ext[e][1] += bool(b[p].get("accepted"))
    print(f"  {'extractor':12} {'candidates':>11} {'accepted':>9} {'rate':>6}")
    for e, (n, k) in sorted(ext.items(), key=lambda kv: -kv[1][0]):
        print(f"  {e:12} {n:11} {k:9} {k / n:6.0%}")
    print("  Same verifier on every row, so the difference is the extractor.")
    print("  The published corpus cannot show this: its extractor and verifier move together.")

    if args.out:
        doc = {
            "before": str(args.before), "after": str(args.after),
            "shared": len(shared), "accepted_before": acc_b, "accepted_after": acc_a,
            "verifier_before": dict(vb), "verifier_after": dict(va),
            "flips": {f"{k[0]}->{k[1]}": v for k, v in flips.items()},
            "per_leader": {s: {"before": x, "after": y} for s, (x, y) in per.items()},
            "extractor_effect": {e: {"candidates": n, "accepted": k} for e, (n, k) in ext.items()},
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
