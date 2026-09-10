#!/usr/bin/env python3
"""Turn the discovery workflow's output into a fetch manifest, aliases and repairs.

The discovery workflow returns one record per leader holding proposed sources
plus the speech-recognition variants of that leader's name and product terms
its agent actually observed. This splits that into the three files the rest of
the pipeline consumes, and refuses to pass along anything malformed.

Usage:
  sources_to_manifest.py --sources data/sources/discovered.json \
      --manifest data/sources/all.jsonl --aliases data/sources/aliases.json \
      --repairs data/sources/repairs.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
KINDS = {"podcast", "interview", "keynote", "fireside", "panel"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--aliases", required=True)
    ap.add_argument("--repairs", required=True)
    ap.add_argument("--report", default="data/logs/manifest_report.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.sources).read_text())
    leaders = payload["leaders"] if isinstance(payload, dict) else payload

    rows: list[dict] = []  # candidates, ranked; the fetcher takes the first N that work
    aliases: dict[str, list[str]] = {}
    repairs: dict[str, list[dict]] = {}
    rejected: list[dict] = []
    seen_global: dict[str, str] = {}

    for led in leaders:
        slug = led["leader_slug"]
        aliases[slug] = sorted({a.strip() for a in led.get("aliases", []) if a and a.strip()})
        seen_pairs = set()
        clean_repairs = []
        for r in led.get("repairs", []):
            w, right = (r.get("wrong") or "").strip(), (r.get("right") or "").strip()
            if w and right and w.lower() != right.lower() and (w.lower(), right.lower()) not in seen_pairs:
                seen_pairs.add((w.lower(), right.lower()))
                clean_repairs.append({"wrong": w, "right": right})
        repairs[slug] = clean_repairs

        for s in led.get("sources", []):
            vid = (s.get("video_id") or "").strip()
            why = None
            if not VIDEO_ID.match(vid):
                why = f"video_id {vid!r} is not an 11-character YouTube id"
            elif vid in seen_global and seen_global[vid] != slug:
                why = f"video_id already claimed by {seen_global[vid]}"
            if why:
                rejected.append({"leader_slug": slug, "source_id": s.get("source_id"),
                                 "video_id": vid, "reason": why})
                continue
            seen_global[vid] = slug
            kind = (s.get("kind") or "interview").strip().lower()
            rows.append({
                "leader_slug": slug,
                "source_id": re.sub(r"[^a-z0-9-]", "-", (s.get("source_id") or vid).lower()),
                "video_id": vid,
                "title": s.get("title") or "untitled",
                "venue": s.get("venue") or "unknown",
                "kind": kind if kind in KINDS else "interview",
                # 0 means unknown. This used to read `or 2024`, which turned every
                # missing year into 2024 and put "Approximate year: 2024" in front
                # of every judge on every grade while the uploads ran 2009-2026.
                # The fetcher overrides it with YouTube's upload date anyway.
                "year": int(s.get("year") or 0),
                # Rank carries the discovery ordering through to the fetcher, which
                # walks a leader's candidates in this order and stops once it has
                # enough. Without it the fetcher would try all 14 and waste caption
                # requests that the rate limit makes scarce.
                "rank": int(s.get("rank") or 999),
            })

    # A source_id must be unique within a leader or the fetch step overwrites files.
    per_leader = Counter((r["leader_slug"], r["source_id"]) for r in rows)
    for r in rows:
        if per_leader[(r["leader_slug"], r["source_id"])] > 1:
            r["source_id"] = f"{r['source_id']}-{r['video_id'][:6].lower()}"

    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    with open(args.manifest, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    Path(args.aliases).write_text(json.dumps(aliases, indent=1))
    Path(args.repairs).write_text(json.dumps(repairs, indent=1))

    counts = Counter(r["leader_slug"] for r in rows)
    thin = {s: n for s, n in counts.items() if n < 3}
    missing = [led["leader_slug"] for led in leaders if counts.get(led["leader_slug"], 0) == 0]
    report = {
        "leaders_in": len(leaders),
        "sources_accepted": len(rows),
        "sources_rejected": len(rejected),
        "rejection_reasons": dict(Counter(x["reason"].split(";")[0].split(" already")[0] for x in rejected)),
        "rejected_detail": rejected,
        "per_leader_counts": dict(sorted(counts.items())),
        "leaders_with_fewer_than_3": thin,
        "leaders_with_zero": missing,
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "alias_terms": sum(len(v) for v in aliases.values()),
        "repair_pairs": sum(len(v) for v in repairs.values()),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "rejected_detail"}, indent=2))
    if missing:
        print(f"WARNING: {len(missing)} leaders have no usable source: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
