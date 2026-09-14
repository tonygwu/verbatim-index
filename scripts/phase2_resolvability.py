#!/usr/bin/env python3
"""How much of the prediction corpus Phase 2 could actually resolve and score.

Read-only over data/predictions. Spends no model calls and writes nothing.
Answers three questions the Phase 2 scope in docs/PREDICTIONS-PHASE2-SCOPE.md
rests on, so a later reader re-runs this rather than trusting the numbers:

  1. how many accepted predictions have a target date that has already passed,
  2. how many of those survive a filter for what a FORESIGHT score may contain,
  3. how many leaders would carry enough of them to be worth a number.

The cutoff is a date you pass, never the local clock, because "past due" is a
property of the data and of the day the reader asks, not of this machine.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())


def iso(value):
    """A date, or None. A malformed date is None and is COUNTED, never guessed at."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def load(pred_dir: pathlib.Path):
    rows = []
    for f in sorted(pred_dir.glob("*/*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("accepted"):
                rows.append(r)
    if not rows:
        raise SystemExit(f"no accepted predictions under {pred_dir}")
    return rows


def funnel(rows, cutoff: dt.date):
    """Each stage names what it drops. A stage that drops nothing still prints."""
    stages = []

    def stage(label, keep):
        stages.append((label, keep))
        return keep

    stage("accepted predictions", rows)
    dated = stage("carry a parseable target date",
                  [r for r in rows if iso(r["prediction"].get("target_date"))])
    past = stage(f"target date on or before {cutoff.isoformat()}",
                 [r for r in dated if iso(r["prediction"]["target_date"]) <= cutoff])
    sane = stage("target date not BEFORE the statement date",
                 [r for r in past
                  if not (iso((r.get("source") or {}).get("statement_date"))
                          and iso(r["prediction"]["target_date"])
                          < iso((r.get("source") or {}).get("statement_date")))])
    spec = stage("specificity high",
                 [r for r in sane if r["prediction"].get("specificity") == "high"])
    stage("outcome NOT under the speaker's own control",
          [r for r in spec if r["prediction"].get("subject_control") != "own"])
    return stages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", type=pathlib.Path, default=ROOT / "data" / "predictions")
    ap.add_argument("--as-of", required=True,
                    help="the cutoff date, YYYY-MM-DD. Required: 'past due' depends on the day "
                         "you ask, and reading it off the local clock is what this repo forbids.")
    ap.add_argument("--min-per-leader", type=int, default=5,
                    help="how many scorable predictions a leader needs to carry a number (default 5, "
                         "the leaderboard's own MIN_TRANSCRIPTS_TO_RANK)")
    args = ap.parse_args()

    cutoff = iso(args.as_of)
    if cutoff is None:
        raise SystemExit(f"--as-of {args.as_of!r} is not a YYYY-MM-DD date")

    rows = load(args.predictions)
    stages = funnel(rows, cutoff)

    print(f"corpus: {len(rows)} accepted predictions, as of {cutoff.isoformat()}\n")
    print("RESOLVABILITY FUNNEL")
    prev = None
    for label, kept in stages:
        drop = "" if prev is None else f"  (-{prev - len(kept)})"
        print(f"  {len(kept):5d}  {label}{drop}")
        prev = len(kept)
    scorable = stages[-1][1]
    past = stages[2][1]

    print("\nWHAT A RESOLUTION PASS WOULD READ (the past-due set, by category)")
    for k, v in collections.Counter(r["prediction"]["category"] for r in past).most_common():
        print(f"  {v:5d}  {k}")
    print("\n  by who controls the outcome")
    for k, v in collections.Counter(r["prediction"]["subject_control"] for r in past).most_common():
        print(f"  {v:5d}  {k}")

    print(f"\nPER-LEADER COVERAGE (floor {args.min_per_leader})")
    for name, kept in (("past due", past), ("scorable as foresight", scorable)):
        per = collections.Counter(r["leader_slug"] for r in kept)
        enough = sorted((v, k) for k, v in per.items() if v >= args.min_per_leader)
        print(f"  {name}: {len(per)} leaders have at least one; "
              f"{len(enough)} reach {args.min_per_leader}; top {per.most_common(5)}")

    probs = [r for r in rows if (r.get("confidence") or {}).get("probability") is not None]
    scored_now = [r for r in probs
                  if iso(r["prediction"].get("target_date"))
                  and iso(r["prediction"]["target_date"]) <= cutoff]
    print(f"\nPROPER SCORING (Brier needs a stated probability AND an outcome)")
    print(f"  {len(probs)} of {len(rows)} accepted predictions carry a probability the speaker said")
    print(f"  {len(scored_now)} of those are past due, so a Brier score today has n={len(scored_now)}")

    cons = collections.Counter((r.get("consensus") or {}).get("status") for r in rows)
    exact = sum(1 for r in rows if (r.get("consensus") or {}).get("exact_match"))
    print(f"\nMARKET-RELATIVE SCORING (needs a contemporaneous market price)")
    print(f"  exact market matches: {exact} of {len(rows)}; status counts {dict(cons)}")

    # Identity, not equality: two predictions can hold equal dicts and "in" would
    # match the wrong one. The funnel keeps the same objects, so id() is exact.
    sane_ids = {id(r) for r in stages[3][1]}
    bad = [r for r in stages[2][1] if id(r) not in sane_ids]
    print(f"\nDATE DEFECTS TO CLEAR BEFORE RESOLVING")
    print(f"  {len(bad)} past-due predictions target a date BEFORE their own statement date, "
          f"across {len(set(r['leader_slug'] for r in bad))} leaders:")
    for r in bad:
        print(f"    {r['leader_slug']:20s} said {(r.get('source') or {}).get('statement_date')} "
              f"-> target {r['prediction']['target_date']}  ({r['prediction'].get('target_date_text')!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
