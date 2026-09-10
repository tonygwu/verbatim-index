#!/usr/bin/env python3
"""Withdraw recordings from the corpus, or send them back for re-grading, from a manifest.

Two actions, both reversible renames and nothing else:

  retire   the source leaves the shelf: data/transcripts/<slug>/<sid>.json is
           renamed to <sid>.json.superseded, the name fetch_transcripts.py
           already honours so the fetcher does not bring it back. On the next
           grade_loop cycle normalize_transcripts.py --grades prunes the
           derived copies and renames the grades to .orphaned. Use it for a
           wrong-person recording.

  regrade  the source stays; every grade for it is renamed to .orphaned so
           grade.py, which skips a transcript whose grade file exists, makes
           a fresh one. Use it when the derived text changes under an existing
           grade, as the paragraph-loop collapse does for 10 transcripts.

Dry run by default. --apply performs the renames, and only in the clone that
owns data/: every clone shares one checkout, so this refuses unless
data/.daemon-clone names the clone it is run from, the same precondition the
loops use. Every entry is reported as done, skipped (already withdrawn) or
failed (source not found), never as a bare count.

Manifest format, one entry per recording:
  [{"leader_slug": "...", "source_id": "...", "action": "retire"|"regrade",
    "reason": "..."}]

Usage, in repo-0:
  .venv/bin/python scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json
  .venv/bin/python scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ACTIONS = ("retire", "regrade")


def require_daemon_clone(root: Path) -> str | None:
    """None if this clone owns data/, else the reason it does not."""
    marker = root / "data" / ".daemon-clone"
    if not marker.exists():
        return f"{marker} is missing; it must name the clone that owns data/"
    owner = marker.read_text().strip()
    here = root.resolve().name
    if here != owner:
        return f"this clone is {here!r} but {marker} names {owner!r}; run it there"
    return None


def retire(root: Path, slug: str, sid: str, apply: bool) -> dict:
    """Take a source off every shelf it sits on."""
    shelves = [root / "data" / "transcripts", root / "data" / "transcripts_hs"]
    moved, already = [], []
    for shelf in shelves:
        src = shelf / slug / f"{sid}.json"
        dst = shelf / slug / f"{sid}.json.superseded"
        if src.exists():
            if apply:
                src.rename(dst)
            moved.append(str(src.relative_to(root)))
        elif dst.exists():
            already.append(str(dst.relative_to(root)))
    if moved:
        return {"status": "done", "renamed": moved}
    if already:
        return {"status": "skipped", "detail": "already superseded", "paths": already}
    return {"status": "failed", "detail": "source not found on any shelf"}


def regrade(root: Path, slug: str, sid: str, apply: bool) -> dict:
    """Orphan every grade for one recording so the loop makes fresh ones."""
    grades = root / "data" / "grades"
    hits = [p for p in grades.glob(f"*/{slug}/{sid}__*.json") if "_raw" not in p.parts]
    if not hits:
        already = list(grades.glob(f"*/{slug}/{sid}__*.json.orphaned"))
        if already:
            return {"status": "skipped", "detail": "no live grades; already orphaned",
                    "count": len(already)}
        return {"status": "failed", "detail": "no grades found for this recording"}
    for p in hits:
        if apply:
            p.rename(str(p) + ".orphaned")
    return {"status": "done", "orphaned": sorted(str(p.relative_to(root)) for p in hits)}


def run(root: Path, manifest: list[dict], apply: bool) -> dict:
    tally = {"attempted": 0, "done": 0, "skipped": 0, "failed": 0, "entries": []}
    for e in manifest:
        for k in ("leader_slug", "source_id", "action"):
            if k not in e:
                raise SystemExit(f"manifest entry missing {k!r}: {e}")
        if e["action"] not in ACTIONS:
            raise SystemExit(f"unknown action {e['action']!r} for {e['leader_slug']}/{e['source_id']}")
        tally["attempted"] += 1
        fn = retire if e["action"] == "retire" else regrade
        r = fn(root, e["leader_slug"], e["source_id"], apply)
        tally[r["status"]] += 1
        tally["entries"].append({"leader_slug": e["leader_slug"], "source_id": e["source_id"],
                                 "action": e["action"], **r})
    return tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest")
    ap.add_argument("--apply", action="store_true", help="Perform the renames. Default is a dry run.")
    ap.add_argument("--root", default=str(REPO), help="Clone root; for tests.")
    args = ap.parse_args()
    root = Path(args.root)
    manifest = json.loads(Path(args.manifest).read_text())
    if args.apply:
        why = require_daemon_clone(root)
        if why:
            raise SystemExit(f"REFUSING TO APPLY: {why}. Only the clone that owns data/ writes it.")
    tally = run(root, manifest, args.apply)
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"{mode}: attempted {tally['attempted']}, done {tally['done']}, "
          f"skipped {tally['skipped']}, failed {tally['failed']}")
    for e in tally["entries"]:
        extra = e.get("detail") or (f"{len(e.get('renamed') or e.get('orphaned') or [])} file(s)")
        print(f"  {e['status']:8s} {e['action']:8s} {e['leader_slug']}/{e['source_id']}  {extra}")
    if not args.apply:
        print("\nnothing was changed; add --apply in the clone that owns data/")
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
