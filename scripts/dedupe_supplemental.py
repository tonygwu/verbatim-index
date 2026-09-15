#!/usr/bin/env python3
"""Find and withdraw duplicate supplemental sources before they double-count.

Uses the SAME 5-gram containment measure and the SAME thresholds as
`dedupe_transcripts.py`, imported rather than restated, so a change there
cannot silently leave this behind.

Why this exists. A prediction quoted from two copies of one appearance is two
records with two different prediction_ids, because the id hashes the transcript
id together with the quote. Nothing downstream would merge them, and the leader
would be credited twice. The existing corpus has already paid for this once:
one appearance was counted three times, and Reed Hastings moved 3.2 points and
four ranks over a talk that appeared in the corpus three times.

The rule is the repo's own: THE LONGER SURVIVES. A short copy whose text is
contained in a longer one carries nothing the longer does not, and the longer
one keeps the surrounding question and answer that the gates need.

Default is a dry run. `--apply` removes the losing transcript AND its extracted
records together, because a transcript withdrawn without its records leaves
orphaned predictions on the board. That is the withdrawal rule this repo wrote
after 27 withdrawn transcripts kept scoring.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dedupe_transcripts import (  # noqa: E402
    DISTINCT_THRESHOLD, DUP_THRESHOLD, containment, shingles,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline", default="data/transcripts_open",
                    help="the existing corpus, checked for collisions too")
    ap.add_argument("--apply", action="store_true",
                    help="withdraw the losing copy; default is a dry run")
    args = ap.parse_args(argv)

    run = Path(args.run).resolve()
    tx, results = run / "transcripts", run / "results"
    baseline = Path(args.baseline).resolve()

    print(f"containment thresholds: duplicate >= {DUP_THRESHOLD}, "
          f"grey band {DISTINCT_THRESHOLD} to {DUP_THRESHOLD}")
    dups: list[tuple] = []
    grey: list[tuple] = []
    collisions: list[tuple] = []

    for d in sorted(p for p in tx.iterdir() if p.is_dir()):
        slug = d.name
        recs = {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}
        sh = {k: shingles(v["text"]) for k, v in recs.items()}

        old_dir = baseline / slug
        if old_dir.exists():
            for op in sorted(old_dir.glob("*.json")):
                osh = shingles(json.loads(op.read_text())["text"])
                for ns in sh:
                    c = containment(sh[ns], osh)
                    if c >= DUP_THRESHOLD:
                        collisions.append((slug, ns, op.stem, c))

        for a, b in itertools.combinations(sorted(sh), 2):
            c = containment(sh[a], sh[b])
            if c < DISTINCT_THRESHOLD:
                continue
            # The loser is the SHORTER text: it is the contained copy.
            lo, hi = sorted((a, b), key=lambda s: recs[s]["word_count"])
            row = (slug, hi, recs[hi]["word_count"], lo, recs[lo]["word_count"], c)
            (dups if c >= DUP_THRESHOLD else grey).append(row)

    if collisions:
        print(f"\nCOLLISIONS WITH THE EXISTING CORPUS: {len(collisions)}")
        for slug, ns, os_, c in sorted(collisions, key=lambda r: -r[3]):
            print(f"  {c:.3f}  {slug:18} {ns}  duplicates existing {os_}")
        print("  These must be withdrawn by hand: the existing corpus is repo-0's.")
    else:
        print("\nno collisions with the existing corpus")

    print(f"\nDUPLICATES within the supplemental set: {len(dups)}")
    for slug, hi, hw, lo, lw, c in sorted(dups, key=lambda r: -r[5]):
        print(f"  {c:.3f}  {slug}")
        print(f"          KEEP  {hi}  ({hw:,} words)")
        print(f"          DROP  {lo}  ({lw:,} words)")

    print(f"\ngrey band, kept and reported rather than dropped: {len(grey)}")
    for slug, hi, hw, lo, lw, c in sorted(grey, key=lambda r: -r[5]):
        print(f"  {c:.3f}  {slug:18} {lo} vs {hi}")

    if not args.apply:
        print("\ndry run; pass --apply to withdraw the DROP rows")
        return 0

    removed = 0
    for slug, _hi, _hw, lo, _lw, _c in dups:
        for p in (tx / slug / f"{lo}.json",
                  results / slug / f"{lo}.jsonl",
                  results / slug / f"{lo}.meta.json"):
            if p.exists():
                p.unlink()
                print(f"  removed {p.relative_to(run)}")
                removed += 1
    print(f"\nwithdrew {len(dups)} duplicate sources, {removed} files removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
