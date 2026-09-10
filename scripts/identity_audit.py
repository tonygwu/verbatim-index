#!/usr/bin/env python3
"""Flag transcripts whose judges all say the speaker is somebody ELSE.

WHY THIS EXISTS. On 2026-09-10 ten of C.C. Wei's twelve graded transcripts were
ten different people whose names contain "Wei": Jing Wei the illustrator,
Eugene Wei, Zhang Weiwei of Fudan, Wei Chen of Northwestern twice, Wei Li of
Intel, Nat Wei, Han-Wei Shen, a Bay Area DJ, and a retired academic. Discovery
had matched on the surname. His published 52.4 was an average over ten
strangers and two real appearances.

Every judge caught it, on the first pass, in `identity_guess`. Nothing read that
field. This script reads it.

WHAT IT IS NOT. This is a corpus-integrity check, not a blinding check. The
judges identify the speaker on almost every transcript and the repo already
documents that as a known limit. The signal here is not THAT they identified
someone; it is that they identified someone who is not the leader we filed the
transcript under.

THE ONE HARD PART: NEGATION. A judge that spots the mislabelling says so by
NAMING the leader it is not:

    "distinctly unrelated to C.C. Wei of TSMC despite the transcript ID label"
    "identification as C.C. Wei is unsupported"

A plain substring test reads both as a match and clears the very transcript the
judge was warning about. Measured on the C.C. Wei case: substring matching finds
8 of the 10, and the 2 it misses are the 2 where the judge was most explicit.
So every occurrence of the name is checked for a negation cue in a window around
it, and an occurrence that is negated does not count as a match.

The window is 60 characters before the name and 40 after. Both numbers are
judgement calls, they are pinned by scripts/test_identity_audit.py, and the
report states them so a later reader can challenge them rather than trust them.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def repo_root() -> Path:
    """No clone-absolute paths: ask git, fall back to this file's location."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


# Cues that turn "X" into "not X" when they sit next to the name. Deliberately
# short and literal: a longer list starts matching ordinary prose.
NEGATION_CUES = (
    "not ", "no relation", "unrelated", "unsupported", "despite", "rather than",
    "isn't", "is not", "cannot be", "incorrectly", "mislabel", "mismatch",
    "contrary to", "wrongly", "does not appear to be", "certainly not",
)
WINDOW_BEFORE = 60
WINDOW_AFTER = 40

# A judge that says it does not know is not evidence either way.
ABSTAIN_MARKERS = ("unknown", "cannot identify", "could not identify",
                   "unable to identify", "no identification", "not identifiable")


def norm(s: str | None) -> str:
    """Lowercase, punctuation to spaces, whitespace squashed.

    Punctuation has to go so that "C.C. Wei" and "C. C. Wei" and "CC Wei" all
    reduce to the same string. That is also why the name test below is a
    substring test rather than a token test.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def occurrences(haystack: str, needle: str) -> list[int]:
    out, i = [], haystack.find(needle)
    while i != -1:
        out.append(i)
        i = haystack.find(needle, i + 1)
    return out


def name_is_negated(text: str, start: int, length: int) -> bool:
    lo = max(0, start - WINDOW_BEFORE)
    hi = min(len(text), start + length + WINDOW_AFTER)
    window = text[lo:hi]
    return any(cue in window for cue in NEGATION_CUES)


def judge_verdict(guess: str | None, full_name: str, company: str) -> str:
    """One of: abstain, match, mismatch.

    match     the judge names this leader, and does not name them only to deny
              that it is them.
    mismatch  the judge names somebody, and it is not this leader.
    abstain   the judge says it does not know. Not evidence either way.
    """
    g = norm(guess)
    if not g:
        return "abstain"
    if any(m in g for m in ABSTAIN_MARKERS):
        # "unknown" alone abstains. But a judge that names someone AND says the
        # label is unsupported is a mismatch, so only abstain when no other
        # person is offered. The cheap test for that: nothing but the marker.
        if len(g.split()) <= 4:
            return "abstain"
    hits = occurrences(g, full_name)
    if hits:
        if any(not name_is_negated(g, h, len(full_name)) for h in hits):
            return "match"
        return "mismatch"        # named only to be ruled out
    # Initials and nicknames: surname plus the company is the leader too.
    surname = full_name.split()[-1] if full_name else ""
    comp_first = company.split()[0] if company else ""
    if surname and comp_first:
        for h in occurrences(g, surname):
            if comp_first in g and not name_is_negated(g, h, len(surname)):
                return "match"
    if any(m in g for m in ABSTAIN_MARKERS):
        return "abstain"
    return "mismatch"


def load_grades(grades_dir: Path) -> list[dict]:
    out = []
    for p in grades_dir.rglob("*.json"):
        if "_raw" in p.parts:
            continue
        try:
            rec = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise SystemExit(f"unreadable grade file {p}: {e}")
        if not isinstance(rec.get("grade"), dict):
            continue
        if "identity_guess" not in rec["grade"]:
            continue            # a refusal or an invalid record, counted below
        out.append(rec)
    return out


def audit(grades: list[dict], roster: dict[str, dict]) -> dict:
    per_tx: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    unknown_slugs: Counter = Counter()
    for g in grades:
        slug = g.get("leader_slug")
        r = roster.get(slug)
        if r is None:
            unknown_slugs[slug] += 1
            continue
        v = judge_verdict(g["grade"].get("identity_guess"),
                          norm(r["name"]), norm(r.get("company") or r.get("organisation") or ""))
        per_tx[(slug, g["source_id"])].append((g.get("judge", "?"), v))

    confirmed, suspect, clean, no_opinion = [], [], 0, 0
    for (slug, sid), votes in sorted(per_tx.items()):
        opinions = [(j, v) for j, v in votes if v != "abstain"]
        if not opinions:
            no_opinion += 1
            continue
        mismatches = [j for j, v in opinions if v == "mismatch"]
        if len(mismatches) == len(opinions):
            row = {"leader_slug": slug, "source_id": sid,
                   "judges_naming_someone_else": sorted(mismatches),
                   "judges_abstaining": sorted(j for j, v in votes if v == "abstain")}
            (confirmed if len(mismatches) >= 2 else suspect).append(row)
        else:
            clean += 1

    return {
        "attempted": len(grades),
        "transcripts_examined": len(per_tx),
        "verdicts": {
            "confirmed_wrong_person": len(confirmed),
            "suspect_single_judge": len(suspect),
            "consistent_with_roster": clean,
            "no_judge_expressed_an_opinion": no_opinion,
        },
        "confirmed": confirmed,
        "suspect": suspect,
        "grades_with_no_identity_field": None,   # filled by caller
        "unknown_leader_slugs": dict(unknown_slugs),
        "method": {
            "negation_cues": list(NEGATION_CUES),
            "window_before_chars": WINDOW_BEFORE,
            "window_after_chars": WINDOW_AFTER,
            "confirmed_requires_n_judges": 2,
            "note": "A judge that names the leader ONLY to rule them out is a mismatch, "
                    "not a match. Substring matching without this finds 8 of the 10 "
                    "known C.C. Wei cases.",
        },
    }


def main() -> int:
    root = repo_root()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grades", default=str(root / "data" / "grades"))
    ap.add_argument("--roster", default=str(root / "data" / "roster" / "final.json"))
    ap.add_argument("--out", default=None, help="write the full report as JSON")
    ap.add_argument("--fail-on-confirmed", action="store_true",
                    help="exit 1 when any transcript is confirmed wrong-person")
    args = ap.parse_args()

    roster_path, grades_path = Path(args.roster), Path(args.grades)
    if not roster_path.exists():
        raise SystemExit(f"roster not found: {roster_path}")
    if not grades_path.exists():
        raise SystemExit(f"grades directory not found: {grades_path}")

    roster = {r["slug"]: r for r in json.loads(roster_path.read_text())["roster"]}
    grades = load_grades(grades_path)
    if not grades:
        raise SystemExit(f"no gradeable records under {grades_path}; refusing to "
                         f"report a clean audit over an empty set")

    report = audit(grades, roster)
    total_files = sum(1 for p in grades_path.rglob("*.json") if "_raw" not in p.parts)
    report["grades_with_no_identity_field"] = total_files - report["attempted"]

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))

    v = report["verdicts"]
    print(f"identity audit over {report['attempted']} grades "
          f"({report['grades_with_no_identity_field']} carried no identity_guess and were skipped), "
          f"{report['transcripts_examined']} transcripts")
    print(f"  confirmed wrong person (2+ judges agree) : {v['confirmed_wrong_person']}")
    print(f"  suspect (a single judge)                 : {v['suspect_single_judge']}")
    print(f"  consistent with the roster               : {v['consistent_with_roster']}")
    print(f"  no judge expressed an opinion            : {v['no_judge_expressed_an_opinion']}")
    if report["unknown_leader_slugs"]:
        print(f"  grades for slugs not in the roster       : {report['unknown_leader_slugs']}")

    for label, rows in (("CONFIRMED", report["confirmed"]), ("SUSPECT", report["suspect"])):
        if rows:
            print(f"\n{label}:")
            for r in rows:
                print(f"  {r['leader_slug']}/{r['source_id']}  "
                      f"named someone else by: {', '.join(r['judges_naming_someone_else'])}")

    if args.fail_on_confirmed and report["confirmed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
