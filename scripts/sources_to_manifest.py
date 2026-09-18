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

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
KINDS = {"podcast", "interview", "keynote", "fireside", "panel"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--aliases", required=True)
    ap.add_argument("--repairs", required=True)
    ap.add_argument("--replace-aliases", action="store_true",
                    help="Overwrite aliases.json with the derived set instead of "
                         "merging into it, DROPPING any term the file holds that "
                         "discovery did not return. The dropped terms are named in "
                         "the report. Merging is the default because aliases.json "
                         "is hand-curated and is also the QA glossary.")
    ap.add_argument("--report", default=None, help="Default: <study data>/logs/manifest_report.json.")
    import study_profile as SP
    SP.add_study_arg(ap)
    args = ap.parse_args()
    SP.guard(args.study)
    args.report = args.report or f"{SP.data_link(args.study)}/logs/manifest_report.json"
    SP.guard(args.study, args.sources, args.manifest, args.aliases, args.repairs, args.report)

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
    # MERGE, do not overwrite. aliases.json is not purely derived: terms have
    # been added by hand since the last discovery run, and re-derivation is a
    # strict subset of what is on disk. MEASURED 2026-09-16 against the live
    # data/sources/discovered.json: 14 terms only on disk, 0 only derived,
    # across 7 slugs -- Alphabet, Sun Microsystems, OpenAI, comma.ai, geohot,
    # Scale AI and the rest. A wholesale write destroyed all 14.
    #
    # It is not cosmetic. grade_loop.sh:150 passes this same file to
    # qa_transcripts.py as --glossaries, which computes `known = dictionary |
    # glossary` at :142; that drives oov_rate, which drives the reject verdict,
    # which orphans a leader's grades.
    #
    # The assertion is SUBSET CONTAINMENT, never byte equality. Byte equality
    # points the wrong way: it would treat the 14 curated terms as a difference
    # to remove rather than state to keep.
    existing_aliases: dict[str, list[str]] = {}
    ap_path = Path(args.aliases)
    if ap_path.exists():
        try:
            existing_aliases = json.loads(ap_path.read_text())
        except json.JSONDecodeError as e:
            # Never silently start from empty: that is the wholesale write again.
            raise SystemExit(f"{args.aliases} exists but is not valid JSON ({e}). "
                             "Fix or remove it; refusing to overwrite a glossary "
                             "this run cannot read.")

    dropped_by_replace: dict[str, list[str]] = {}
    preserved = 0
    if args.replace_aliases:
        for slug, terms in existing_aliases.items():
            lost = sorted(set(terms) - set(aliases.get(slug, [])))
            if lost:
                dropped_by_replace[slug] = lost
        written_aliases = aliases
    else:
        # ORDER IS LOAD-BEARING, so the existing file's order is preserved and
        # new terms are only appended. The live blinder is the `wordlist is
        # None` branch of normalize_transcripts.blind(), which builds
        # `name_forms + [a for a in aliases if a]` and applies them IN THAT
        # ORDER with no length sort. Re-sorting would replace "Aaron" before
        # "Aaron Levie" and change blinded text under 2,260 existing grades.
        # Sorting looked tidy and was the wrong direction; only the opt-in
        # wordlist branch sorts longest-first for itself.
        written_aliases = {}
        for slug in list(existing_aliases) + [s for s in aliases if s not in existing_aliases]:
            kept = list(existing_aliases.get(slug, []))
            kept_set = set(kept)
            added = [a for a in aliases.get(slug, []) if a not in kept_set]
            preserved += len(kept_set - set(aliases.get(slug, [])))
            written_aliases[slug] = kept + added
        # Fail loud rather than write a file that lost a glossary term.
        for slug, terms in existing_aliases.items():
            missing_terms = sorted(set(terms) - set(written_aliases.get(slug, [])))
            if missing_terms:
                raise SystemExit(
                    f"refusing to write {args.aliases}: merge would drop "
                    f"{missing_terms!r} from {slug}. Pass --replace-aliases if "
                    "that is really intended.")

    # ensure_ascii=False so a merge that adds nothing is byte-identical to the
    # file it read. The live file holds literal UTF-8 ("Tobi Lutke" with the
    # umlaut); escaping it to \\u00fc made a no-op merge show a two-line diff,
    # which would defeat the pre-push audit that requires this file unchanged.
    # Atomic: aliases.json is the blinder input AND the QA glossary, read by
    # normalize and qa while other clones run. A torn read there flips a QA
    # verdict, which orphans grades.
    write_atomic(ap_path, json.dumps(written_aliases, indent=1, ensure_ascii=False))
    write_atomic(args.repairs, json.dumps(repairs, indent=1))

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
        "alias_terms": sum(len(v) for v in written_aliases.values()),
        "alias_terms_derived": sum(len(v) for v in aliases.values()),
        # Never a bare count on either branch: a merge that keeps state
        # silently cannot be audited, and a replace that drops curated terms
        # must name them rather than report a number.
        "alias_terms_preserved_by_merge": preserved,
        "alias_terms_dropped_by_replace": dropped_by_replace,
        "repair_pairs": sum(len(v) for v in repairs.values()),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    write_atomic(args.report, json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "rejected_detail"}, indent=2))
    if missing:
        print(f"WARNING: {len(missing)} leaders have no usable source: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
