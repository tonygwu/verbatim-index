#!/usr/bin/env python3
"""Decide which Happy Scribe transcripts are new, and merge only those.

Two sources now cover the same people, so the same appearance can arrive twice:
a Lex Fridman episode exists both as a YouTube caption track and as a Happy
Scribe page. Grading both would count one conversation twice, inflating that
leader's transcript count and letting a single appearance move their average
twice as much as anyone else's.

Metadata cannot decide this. Titles differ between sources, Happy Scribe has no
video id, and durations come from different measurements. So the comparison is
on CONTENT: the same audio produces the same words, whoever transcribed it.

The measure is CONTAINMENT, not Jaccard. Two transcripts of one appearance
routinely differ in length, because one may omit an intro, cut an ad read, or
stop early. Jaccard punishes that difference twice, once in the numerator and
once in the denominator, and can read a genuine duplicate as distinct.
Containment asks how much of the SHORTER transcript appears in the longer one,
which is the question that actually matters here.

Comparison is only ever within one leader. Two different people cannot be the
same appearance, and skipping cross-leader pairs turns an O(n^2) sweep over the
whole corpus into a handful of small ones.

Usage:
  dedupe_transcripts.py --report            # decide, change nothing
  dedupe_transcripts.py --merge             # copy the non-duplicates across
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

WORD = re.compile(r"[a-z']+")
STAMP = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")

SHINGLE = 5
# Containment above this means the same appearance. Calibrated on this corpus:
# see --report, which prints the full distribution so the gap between duplicate
# and distinct pairs is visible rather than asserted.
# Measured on the first real cross-source run: 6 true duplicates scored
# 0.558 to 0.609, every other pair scored at or below 0.012, and NOTHING landed
# between. Duplicates do not score near 1.0 because the two sources transcribe
# the same audio differently, so a high threshold would miss them. 0.40 sits in
# the middle of the empty band rather than 0.008 under the lowest true positive.
DUP_THRESHOLD = 0.40
# Below this a pair is definitely distinct. Between the two is a grey band that
# is reported for a human to look at rather than silently resolved.
DISTINCT_THRESHOLD = 0.15


def shingles(text: str, k: int = SHINGLE) -> set[str]:
    """Word k-grams, timestamps stripped, lowercased.

    Timestamps must go before shingling. Happy Scribe marks roughly every 20
    seconds and YouTube every 60, so leaving them in would inject a stream of
    tokens that differ between two transcripts of identical speech.
    """
    toks = WORD.findall(STAMP.sub(" ", text).lower())
    if len(toks) < k:
        return set()
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def containment(a: set[str], b: set[str]) -> float:
    """Share of the smaller set that also appears in the larger one."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def load(root: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        try:
            rec = json.loads(p.read_text())
        except Exception:  # noqa: BLE001 - a half-written file from a live loop
            continue
        if "leader_slug" not in rec or "text" not in rec:
            continue
        rec["_path"] = str(p)
        out.setdefault(rec["leader_slug"], []).append(rec)
    return out


# Stitching two copies of one appearance is almost never worth it, and this
# constant is why. Measured across 38 real duplicate decisions: 37 scored
# containment ~1.0, so the shorter copy is a strict subset and a union adds
# nothing. The single partial case, Bezos on Lex #405 at 0.579, was the SAME
# audio transcribed twice: the kept copy runs 21,688 words over 132 minutes,
# which is 164 words per minute, a normal speaking rate across the whole
# episode. Nothing was missing. A 5-gram needs five consecutive words to match,
# so one different filler word breaks it even when the speech is identical.
#
# The case where a union WOULD pay is a partial duplicate whose kept copy is
# actually truncated. That is detectable rather than assumed: a transcript
# covering its own runtime at a plausible speaking rate is complete, and one
# well below that lost content. Flag it for a human instead of silently
# concatenating, because a wrong splice corrupts the document a judge reads.
TRUNCATION_WPM = 90        # below this, a transcript is not covering its runtime
PARTIAL_CONTAINMENT = 0.95  # under this, the two copies are not a clean superset


def flag_possible_truncation(kept: dict, containment: float) -> str | None:
    """Return a warning when a union might actually recover lost content."""
    if containment >= PARTIAL_CONTAINMENT:
        return None
    dur_min = (kept.get("duration_sec") or 0) / 60.0
    if dur_min <= 0:
        return None
    wpm = kept.get("word_count", 0) / dur_min
    if wpm >= TRUNCATION_WPM:
        return None
    return (f"partial duplicate (containment {containment:.3f}) AND the kept copy runs "
            f"{wpm:.0f} words/min over {dur_min:.0f} min, below {TRUNCATION_WPM}. "
            f"It may be truncated, so the discarded copy could hold content worth "
            f"recovering. Review by hand; do not auto-splice.")


def quality(rec: dict) -> tuple:
    """Rank two copies of one appearance. Higher is better.

    A human-made caption track beats machine output. Beyond that, more timestamp
    markers means a judge can cite a position more precisely, and a longer
    transcript means less was cut. Deliberately NOT preferring one source over
    the other by name: the attributes decide.
    """
    track = rec.get("caption_track") or ""
    human = 1 if track == "manual" else 0
    return (human, rec.get("n_timestamp_marks") or 0, rec.get("word_count") or 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--youtube", default="data/transcripts")
    ap.add_argument("--happyscribe", default="data/transcripts_hs")
    ap.add_argument("--merge", action="store_true",
                    help="Copy non-duplicate Happy Scribe transcripts into the YouTube "
                         "directory, which is the one the rest of the pipeline reads.")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--sweep", action="store_true",
                    help="Deduplicate the merged corpus against ITSELF, regardless of source. "
                         "Catches the same talk re-uploaded to several YouTube channels, which "
                         "the cross-source pass never compares.")
    ap.add_argument("--grades", default="data/grades",
                    help="Grades directory to orphan retired transcripts' grades from. "
                         "Must match the corpus in --youtube; the two used to be able to "
                         "disagree, because this path was hardcoded.")
    ap.add_argument("--out", default="data/logs/dedupe.json")
    ap.add_argument("--threshold", type=float, default=DUP_THRESHOLD)
    args = ap.parse_args()
    if not (args.merge or args.report):
        args.report = True

    yt = load(Path(args.youtube))
    hs = load(Path(args.happyscribe))
    print(f"  youtube:     {sum(len(v) for v in yt.values())} transcripts, {len(yt)} leaders",
          file=sys.stderr)
    print(f"  happyscribe: {sum(len(v) for v in hs.values())} transcripts, {len(hs)} leaders",
          file=sys.stderr)

    decisions: list[dict] = []
    pair_scores: list[float] = []

    for slug, hs_recs in sorted(hs.items()):
        yt_recs = yt.get(slug, [])
        yt_sh = [(r, shingles(r["text"])) for r in yt_recs]
        # Compare against already-accepted Happy Scribe items too, so two Happy
        # Scribe pages of the same episode do not both get in.
        accepted: list[tuple[dict, set]] = []
        for rec in sorted(hs_recs, key=quality, reverse=True):
            sh = shingles(rec["text"])
            best = (0.0, None, None)
            for other, osh in yt_sh + accepted:
                # A transcript merged on an EARLIER cycle now sits in the corpus
                # under its own id, so without this guard it matches itself at
                # containment 1.0, gets declared a duplicate, and supersedes the
                # copy already merged. The next cycle re-fetches it and does the
                # same again. Observed live: the corpus cycled 222 -> 214 every
                # pass, and the churn also spent YouTube's scarce allowance
                # re-fetching transcripts that were about to be deleted.
                if other.get("source_id") == rec["source_id"]:
                    continue
                c = containment(sh, osh)
                pair_scores.append(c)
                if c > best[0]:
                    best = (c, other, "youtube" if (other, osh) in yt_sh else "happyscribe")
            score, match, side = best
            already = any(o.get("source_id") == rec["source_id"] for o, _ in yt_sh)
            if already:
                decisions.append({
                    "leader_slug": slug, "hs_source_id": rec["source_id"],
                    "verdict": "already_merged", "containment": None,
                    "matches": rec["source_id"], "matches_source": "corpus",
                    "action": "none",
                    "why": "this exact transcript is already in the corpus from an "
                           "earlier cycle; nothing to merge and nothing to supersede",
                })
                continue
            if score >= args.threshold:
                keep_hs = quality(rec) > quality(match)
                decisions.append({
                    "leader_slug": slug, "hs_source_id": rec["source_id"],
                    "verdict": "duplicate", "containment": round(score, 3),
                    "matches": match["source_id"], "matches_source": side,
                    "action": "replace_existing" if keep_hs else "drop_happyscribe",
                    "why": (f"{round(score*100)}% of the shorter transcript's 5-grams appear in "
                            f"the other; keeping the "
                            f"{'happyscribe' if keep_hs else side} copy on "
                            f"track/timestamps/length"),
                })
            elif score >= DISTINCT_THRESHOLD:
                decisions.append({
                    "leader_slug": slug, "hs_source_id": rec["source_id"],
                    "verdict": "review", "containment": round(score, 3),
                    "matches": match["source_id"] if match else None,
                    "action": "drop_happyscribe",
                    "why": "in the grey band between distinct and duplicate; dropped to be safe, "
                           "and reported so a human can look",
                })
            else:
                decisions.append({
                    "leader_slug": slug, "hs_source_id": rec["source_id"],
                    "verdict": "new", "containment": round(score, 3),
                    "matches": match["source_id"] if match else None,
                    "action": "merge",
                })
                accepted.append((rec, sh))

    dup = [d for d in decisions if d["verdict"] == "duplicate"]
    rev = [d for d in decisions if d["verdict"] == "review"]
    new = [d for d in decisions if d["verdict"] == "new"]

    summary = {
        "happyscribe_examined": len(decisions),
        "new": len(new),
        "duplicate": len(dup),
        "needs_review": len(rev),
        "threshold": args.threshold,
        "distinct_threshold": DISTINCT_THRESHOLD,
        "pairs_compared": len(pair_scores),
        "containment_distribution": {
            "max": round(max(pair_scores), 3) if pair_scores else None,
            "p99": round(sorted(pair_scores)[int(len(pair_scores) * 0.99)], 3) if pair_scores else None,
            "median": round(sorted(pair_scores)[len(pair_scores) // 2], 3) if pair_scores else None,
        },
        "new_by_leader": {},
    }
    for d in new:
        summary["new_by_leader"][d["leader_slug"]] = summary["new_by_leader"].get(d["leader_slug"], 0) + 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "decisions": decisions}, indent=1))

    if args.sweep:
        # A same-source sweep, because duplicates are not only a cross-source
        # problem. Reed Hastings had one talk on three different YouTube
        # channels at containment 0.85, 0.62 and 0.61, and the cross-source pass
        # never compares YouTube against YouTube so it saw none of them. Title
        # matching missed them too, because each channel titled it differently.
        corpus = load(Path(args.youtube))
        retired: list[dict] = []
        for slug, recs in sorted(corpus.items()):
            sh = [(r, shingles(r["text"])) for r in recs]
            # Best first, so a cluster is always represented by its strongest copy.
            sh.sort(key=lambda t: quality(t[0]), reverse=True)
            kept: list[tuple[dict, set]] = []
            for rec, s_ in sh:
                dup_of = None
                for other, osh in kept:
                    if containment(s_, osh) >= args.threshold:
                        dup_of = (other, containment(s_, osh))
                        break
                if dup_of:
                    other, c = dup_of
                    src = Path(rec["_path"])
                    src.rename(str(src) + ".superseded")
                    retired.append({
                        "leader_slug": slug, "retired": rec["source_id"],
                        "kept": other["source_id"], "containment": round(c, 3),
                        "why": "same appearance re-published under another title or channel",
                    })
                else:
                    kept.append((rec, s_))
        # A retired transcript may already have grades. Those must go too, or the
        # leader keeps scoring on an appearance that is no longer in the corpus.
        orphans = []
        for r in retired:
            for gp in Path(args.grades).rglob(f"{r['retired']}__*.json"):
                gp.rename(str(gp) + ".orphaned")
                orphans.append(str(gp))
        print(json.dumps({
            "sweep_retired": len(retired),
            "orphaned_grades_removed": len(orphans),
            "detail": retired,
        }, indent=2))
        return 0

    if args.merge:
        by_id = {(r["leader_slug"], r["source_id"]): r for recs in hs.values() for r in recs}
        merged = replaced = 0
        for d in decisions:
            if d["action"] not in ("merge", "replace_existing"):
                continue
            rec = by_id[(d["leader_slug"], d["hs_source_id"])]
            dest = Path(args.youtube) / d["leader_slug"] / f"{d['hs_source_id']}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: v for k, v in rec.items() if k != "_path"}
            payload["dedupe"] = {k: d[k] for k in ("verdict", "containment", "matches") if k in d}
            tmp = dest.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
            os.replace(tmp, dest)
            merged += 1
            if d["action"] == "replace_existing":
                # Retire the weaker copy rather than deleting it, so the choice
                # stays auditable.
                old = Path(args.youtube) / d["leader_slug"] / f"{d['matches']}.json"
                if old.exists():
                    shutil.move(str(old), str(old) + ".superseded")
                    replaced += 1
        summary["merged_into_corpus"] = merged
        summary["superseded_existing"] = replaced
        Path(args.out).write_text(json.dumps({"summary": summary, "decisions": decisions}, indent=1))

    print(json.dumps(summary, indent=2))
    for d in dup[:10]:
        print(f"  DUPLICATE {d['leader_slug']}/{d['hs_source_id']} ~ {d['matches']} "
              f"(containment {d['containment']})", file=sys.stderr)
    for d in rev[:10]:
        print(f"  REVIEW    {d['leader_slug']}/{d['hs_source_id']} ~ {d['matches']} "
              f"(containment {d['containment']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
