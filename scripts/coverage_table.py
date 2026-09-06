#!/usr/bin/env python3
"""Per-leader coverage across every pipeline stage.

One row per leader, showing how many appearances survive each narrowing:
identified as candidates, fetched as transcripts, passed the quality gate,
and graded by the judges. Reading it left to right shows exactly where a
leader is losing material.

Usage:
  coverage_table.py                 # text table
  coverage_table.py --csv out.csv   # also write CSV
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

TARGET = 5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    roster = json.loads(Path("data/roster/final.json").read_text())["roster"]

    # 1. identified: ranked candidates the discovery step produced
    identified: Counter = Counter()
    mf = Path("data/sources/all.jsonl")
    if mf.exists():
        for line in mf.read_text().splitlines():
            if line.strip():
                identified[json.loads(line)["leader_slug"]] += 1
    # Happy Scribe candidates are part of the pool too. Counting only YouTube
    # made IDENT look like a ceiling it is not, and would eventually show a
    # leader with FETCH above IDENT, which reads as a bug rather than a
    # second source.
    hsf = Path("data/sources/happyscribe_candidates.json")
    if hsf.exists():
        hs = json.loads(hsf.read_text())
        if isinstance(hs, dict):
            for slug, rows in hs.items():
                if isinstance(rows, list):
                    identified[slug] += len(rows)

    # 2. fetched: transcript files actually on disk
    fetched: Counter = Counter()
    from_yt: Counter = Counter()
    from_hs: Counter = Counter()
    tdir = Path("data/transcripts")
    if tdir.exists():
        for p in tdir.rglob("*.json"):
            if p.name.endswith(".tmp"):
                continue
            fetched[p.parent.name] += 1
            try:
                method = json.loads(p.read_text()).get("fetch_method") or "happyscribe"
            except Exception:
                method = "happyscribe"
            (from_yt if method == "youtube_transcript_api" else from_hs)[p.parent.name] += 1

    # 3. gated: QA verdict of pass or review; reject does not reach a judge
    gated: Counter = Counter()
    rejected: Counter = Counter()
    qf = Path("data/logs/transcript_qa.json")
    if qf.exists():
        for r in json.loads(qf.read_text())["reports"]:
            if r["verdict"] == "reject":
                rejected[r["leader_slug"]] += 1
            else:
                gated[r["leader_slug"]] += 1

    # 4. graded: distinct transcripts with a blinded grade, plus total judge calls
    graded_tx: dict[str, set] = defaultdict(set)
    calls: Counter = Counter()
    gdir = Path("data/grades")
    if gdir.exists():
        for p in gdir.rglob("*.json"):
            if "_raw" in p.parts or p.name.endswith(".tmp"):
                continue
            try:
                g = json.loads(p.read_text())
            except Exception:
                continue
            slug = g.get("leader_slug")
            if not slug:
                continue
            calls[slug] += 1
            if g.get("mode") == "blinded" and not g.get("validation_errors"):
                graded_tx[slug].add(g["source_id"])

    # Scores, where they exist yet
    scores: dict[str, dict] = {}
    rf = Path("data/results.json")
    if rf.exists():
        for l in json.loads(rf.read_text())["leaders"]:
            if l.get("blinded"):
                scores[l["slug"]] = l["blinded"]

    rows = []
    for p in roster:
        s = p["slug"]
        rows.append({
            "leader": p["name"],
            "company": p["company"],
            "identified": identified.get(s, 0),
            "fetched": fetched.get(s, 0),
            "yt": from_yt.get(s, 0),
            "hs": from_hs.get(s, 0),
            "gated": gated.get(s, 0),
            "rejected": rejected.get(s, 0),
            "graded": len(graded_tx.get(s, ())),
            "judge_calls": calls.get(s, 0),
            "overall": scores.get(s, {}).get("overall"),
        })
    rows.sort(key=lambda r: (-r["graded"], -r["fetched"], r["leader"]))

    w = max(len(r["leader"]) for r in rows)
    c = min(24, max(len(r["company"]) for r in rows))
    print(f"{'#':>3}  {'LEADER':<{w}}  {'ORGANISATION':<{c}}  {'IDENT':>5} {'FETCH':>5} {'YT':>3} {'HS':>3} {'GATED':>5} {'REJ':>4} {'GRADED':>6} {'CALLS':>5}  {'SCORE':>5}")
    print(f"{'-'*3}  {'-'*w}  {'-'*c}  {'-'*5} {'-'*5} {'-'*3} {'-'*3} {'-'*5} {'-'*4} {'-'*6} {'-'*5}  {'-'*5}")
    for i, r in enumerate(rows, 1):
        sc = f"{r['overall']:.1f}" if r["overall"] is not None else "-"
        print(f"{i:>3}  {r['leader']:<{w}}  {r['company'][:c]:<{c}}  "
              f"{r['identified']:>5} {r['fetched']:>5} {r['yt']:>3} {r['hs']:>3} {r['gated']:>5} {r['rejected']:>4} "
              f"{r['graded']:>6} {r['judge_calls']:>5}  {sc:>5}")

    tot = {k: sum(r[k] for r in rows) for k in
           ("identified", "fetched", "yt", "hs", "gated", "rejected", "graded", "judge_calls")}
    print(f"{'-'*3}  {'-'*w}  {'-'*c}  {'-'*5} {'-'*5} {'-'*3} {'-'*3} {'-'*5} {'-'*4} {'-'*6} {'-'*5}  {'-'*5}")
    print(f"{'':>3}  {'TOTAL':<{w}}  {'':<{c}}  {tot['identified']:>5} {tot['fetched']:>5} "
          f"{tot['yt']:>3} {tot['hs']:>3} {tot['gated']:>5} {tot['rejected']:>4} "
          f"{tot['graded']:>6} {tot['judge_calls']:>5}")

    started = sum(1 for r in rows if r["fetched"] > 0)
    print()
    print(f"  leaders with any transcript : {started}/{len(rows)}")
    print(f"  leaders at target ({TARGET})       : {sum(1 for r in rows if r['fetched'] >= TARGET)}/{len(rows)}")
    print(f"  leaders with any grade      : {sum(1 for r in rows if r['graded'] > 0)}/{len(rows)}")
    print(f"  remaining to fetch          : {max(0, len(rows) * TARGET - tot['fetched'])} transcripts")
    print(f"  remaining judge calls       : ~{max(0, len(rows) * TARGET * 2 - tot['judge_calls'])} (blinded, both judges)")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        print(f"\n  csv written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
