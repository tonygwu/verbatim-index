#!/usr/bin/env python3
"""Repair ASR proper-noun corruption and optionally blind speaker identity.

Two transformations, both fully logged so any change is auditable:

1. REPAIR. Automatic speech recognition mangles proper nouns constantly:
   company names, product names, people's names, technical terms. A model
   proposes an explicit find -> replace list per leader after reading the
   transcript; this script applies only those listed pairs, counting each
   substitution. The model never rewrites free text, so the transcript stays
   verbatim apart from the listed, counted swaps.

2. BLIND. Replace the subject's name and company with neutral placeholders,
   so a judge cannot lean on the reputation of the person or the company.
   Blinding is partial by nature: a transcript full of product names can
   still reveal who is speaking. The leakage this leaves is measured at
   judging time, not hidden here.

Usage:
  normalize_transcripts.py --transcripts data/transcripts --out data/transcripts_clean \
      --roster data/roster/final.json --repairs data/sources/repairs.json \
      --mode blinded --log data/logs/normalize.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

SUBJECT_TOKEN = "[SUBJECT]"
COMPANY_TOKEN = "[COMPANY]"


def apply_repairs(text: str, pairs: list[dict]) -> tuple[str, list[dict]]:
    """Apply explicit find -> replace pairs, whole-phrase and case-insensitive.

    Each pair is {"wrong": "...", "right": "..."}. Substitutions are counted;
    a pair that matches nothing is reported with count 0 rather than dropped,
    so a repair list that missed its target is visible.
    """
    applied = []
    for pair in pairs:
        wrong = (pair.get("wrong") or "").strip()
        right = (pair.get("right") or "").strip()
        if not wrong or not right or wrong.lower() == right.lower():
            continue
        pattern = re.compile(r"\b" + re.escape(wrong) + r"\b", re.IGNORECASE)
        text, n = pattern.subn(right, text)
        applied.append({"wrong": wrong, "right": right, "count": n})
    return text, applied


def collapse_loops(text: str, max_repeats: int = 2) -> tuple[str, dict]:
    """Collapse runs where speech recognition stutters on the same token.

    Measured on real transcripts: an interview contained "you" repeated eight
    times and another "flo" seventeen times, each a ~40 token artefact of the
    recogniser hitting music or crosstalk. Both sat inside otherwise clean
    22,000 word conversations. Discarding those transcripts threw away 99.6%
    good material to avoid 0.4% noise, so the run is repaired rather than the
    transcript rejected.

    Only immediate repetition of the SAME token is collapsed, and never below
    two instances, so genuine emphasis survives. Every removal is counted.
    """
    words = text.split()
    if not words:
        return text, {"tokens_removed": 0, "runs_collapsed": 0}
    out: list[str] = []
    removed = runs = 0
    i = 0
    while i < len(words):
        j = i
        key = words[i].strip(".,!?").lower()
        while j + 1 < len(words) and words[j + 1].strip(".,!?").lower() == key:
            j += 1
        run_len = j - i + 1
        if run_len > max_repeats and key:
            out.extend(words[i:i + max_repeats])
            removed += run_len - max_repeats
            runs += 1
        else:
            out.extend(words[i:j + 1])
        i = j + 1
    return " ".join(out), {"tokens_removed": removed, "runs_collapsed": runs}


TIMESTAMP = re.compile(r"^\[\d\d:\d\d:\d\d\]$")


def collapse_paragraph_loops(text: str, window: int = 20, island: int | None = None,
                             min_share: float = 0.05) -> tuple[str, dict]:
    """Remove paragraph-scale replays: any run of `window` content tokens that
    already occurred earlier in the transcript, at any alignment.

    `collapse_loops` above repairs a recogniser stuttering on one token. It
    cannot see a live stream that replays the same segment: sam-altman/
    the-economic-times-vfilis is 64,068 words of an eight-minute interview
    looped 39 times, and every judge read all of it. MEASURED 2026-09-10 on
    569 transcripts: 8 are more than 10% repeated by this measure, the worst
    four 76-96%. A stride-40 block measure had put the worst at 19.6% and
    found only 3, because a loop whose period is not a multiple of the block
    never lines up with it; this match is alignment-free.

    Timestamps are ignored for matching, because each replay carries fresh
    ones, and kept in the output. A replay is never byte-identical: the
    recogniser renders the same audio a little differently each time, and
    every such difference leaves a hole of up to `window` tokens that no
    repeated window can cover. A surviving run shorter than `island` tokens
    (default: the window) that sits between removed material and more
    removed material, or at the head of a removed run, is that residue and
    goes too.

    Nothing is removed unless at least `min_share` of the content repeats.
    Below that a repeat is a cold-open teaser or a sponsor read, both
    harmless, and collapsing them would rewrite 114 derived transcripts on
    the 2026-09-10 corpus to fix 10. The share is still measured and
    reported for every transcript, so the gate is visible, not silent.
    """
    if island is None:
        island = window
    all_toks = text.split()
    if not all_toks:
        return text, {"repeat_share": 0.0, "tokens_removed": 0, "content_tokens": 0}
    content_idx = [i for i, t in enumerate(all_toks) if not TIMESTAMP.match(t)]
    content = [all_toks[i] for i in content_idx]
    mask = [False] * len(content)
    seen: dict[tuple[str, ...], int] = {}
    for i in range(len(content) - window + 1):
        key = tuple(content[i:i + window])
        p = seen.get(key)
        if p is None:
            seen[key] = i
            continue
        for j in range(i, i + window):
            mask[j] = True
        # A replay is never byte-identical. The recogniser's first slip inside
        # a copy leaves the tokens before it uncovered, because no window that
        # contains the slip repeats. Walk back from this match and its
        # original together, and keep masking while they still agree, allowing
        # a few slips in a row. Bounded by one window, so a genuine sentence
        # before a replay cannot be eaten.
        back, slips = 1, 0
        while back <= window and i - back > p - back >= 0 and not mask[i - back]:
            if content[i - back] == content[p - back]:
                slips = 0
            else:
                slips += 1
                if slips > 3:
                    break
            mask[i - back] = True
            back += 1
        if slips:
            # Do not keep a trailing run of slips: it may be real speech.
            for q in range(i - back + 1, i - back + 1 + slips):
                if 0 <= q < len(mask) and content[q] != content[q - (i - p)]:
                    mask[q] = False
    repeat_share = sum(mask) / len(content) if content else 0.0
    if repeat_share < min_share:
        return text, {"repeat_share": round(repeat_share, 4), "tokens_removed": 0,
                      "content_tokens": len(content), "below_min_share": True}
    k = 0
    while k < len(mask):
        if mask[k]:
            k += 1
            continue
        j = k
        while j < len(mask) and not mask[j]:
            j += 1
        if (j - k) < island and k > 0 and j < len(mask):
            for q in range(k, j):
                mask[q] = True
        k = j
    drop = {content_idx[q] for q, m in enumerate(mask) if m}
    out: list[str] = []
    for i, t in enumerate(all_toks):
        if i in drop:
            continue
        if TIMESTAMP.match(t) and out and TIMESTAMP.match(out[-1]):
            out[-1] = t  # keep one marker per gap, the later one
            continue
        out.append(t)
    return " ".join(out), {"repeat_share": round(repeat_share, 4), "tokens_removed": len(drop),
                           "content_tokens": len(content)}


def name_variants(full_name: str) -> list[str]:
    """Longest first, so 'Jensen Huang' is replaced before 'Huang' alone."""
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    out = {full_name.strip()}
    if len(parts) >= 2:
        out.add(" ".join(parts[-2:]))
        out.add(parts[-1])
        out.add(parts[0])
    # Possessives are handled by the word-boundary regex plus an explicit 's form.
    return sorted((v for v in out if len(v) > 2), key=len, reverse=True)


# Words that carry no identifying force on their own, so blinding them would
# gut the transcript without hiding anything.
GENERIC_COMPANY_WORDS = {
    "cloud", "platform", "platforms", "systems", "group", "holdings", "labs",
    "technologies", "technology", "software", "digital", "solutions", "networks",
    "the", "and", "inc", "corp", "corporation", "company", "ai", "data", "global",
    "international", "services", "products", "works", "studio", "studios", "media",
}


def company_variants(company: str) -> list[str]:
    """Every form of the company name worth removing, longest first.

    A multi-word name must also give up its distinctive parts. Blinding
    "Google Cloud" while leaving bare "Google" in the text hides nothing.
    """
    c = company.strip()
    out = {c}
    stripped = re.sub(
        r"\b(inc|corp|corporation|technologies|technology|labs|group|holdings|plc|ltd|llc|co)\b\.?",
        "", c, flags=re.I,
    ).strip(" ,.")
    if len(stripped) > 2:
        out.add(stripped)
    for part in re.split(r"[\s/&-]+", stripped):
        if len(part) >= 4 and part.lower() not in GENERIC_COMPANY_WORDS:
            out.add(part)
    return sorted((v for v in out if len(v) > 2), key=len, reverse=True)


def load_dictionary() -> set[str]:
    for path in ("/usr/share/dict/words", "/usr/dict/words"):
        p = Path(path)
        if p.exists():
            return {w.strip().lower() for w in p.read_text(errors="ignore").splitlines() if w.strip()}
    raise SystemExit("no system dictionary at /usr/share/dict/words; fuzzy blinding needs it "
                     "to tell a mangled surname from an ordinary English word")


# Thresholds for treating an unknown token as a mangled form of the name.
# Both bars must be cleared. The spelling bar alone is far too loose: it
# matched the contraction "that's" to the name "Thomas" 34 times in one
# transcript, which would have handed the judge a mutilated document.
FUZZY_SPELLING = 0.64
FUZZY_SOUND = 0.80
# A genuinely mangled surname appears a handful of times. An ordinary word
# caught by accident appears constantly, so frequency is a cheap second guard.
FUZZY_MAX_OCCURRENCES = 25

_VOWELS = set("aeiouy")


def consonant_skeleton(word: str) -> str:
    """Reduce a word to the consonant sounds that survive speech recognition.

    Vowels are what automatic speech recognition gets wrong, and spelling
    conventions for the same sound differ (c and k, ph and f). Stripping both
    leaves a skeleton where "curran" and "kurian" both become "krn", while
    "that's" becomes "tht" and "thomas" becomes "tms", which do not.
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    w = w.replace("ph", "f").replace("ck", "k").replace("x", "ks").replace("q", "k")
    w = w.replace("c", "k").replace("z", "s")
    out: list[str] = []
    for i, ch in enumerate(w):
        if ch in _VOWELS and i > 0:
            continue
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def fuzzy_targets(text: str, anchors: list[str], dictionary: set[str]) -> dict[str, str]:
    """Find transcript tokens that are speech-recognition corruptions of an anchor.

    Automatic speech recognition routinely mangles surnames, so an exact-match
    blind leaves the name in plain sight under a different spelling. "Kurian"
    comes out as "Curran" or "Kurion".

    Four guards keep this from eating ordinary text:
      - The token must be capitalised where it appears. Speech recognition
        capitalises the names it mangles and leaves ordinary words lowercase,
        which separates "Curran" from "hang" even though both sound like a
        surname. This guard matters because the system word list is thin and
        does not contain every common word.
      - Tokens that are real English words are never fuzzy-matched. When a
        mangled name lands on a real word, the per-leader alias list handles
        it, because that is a human decision.
      - Tokens containing an apostrophe are skipped, since contractions are
        both very common and spelled unlike anything else.
      - The token must resemble the anchor in spelling AND in consonant
        sounds, and must not be one of the transcript's frequent words.

    Returns {token_found_in_text: anchor_it_resembles}. Every match is logged,
    so a human can see which words were treated as the name.
    """
    anchors = [a for a in anchors if len(a) >= 4]
    if not anchors:
        return {}
    skeletons = {a: consonant_skeleton(a) for a in anchors}
    hits: dict[str, str] = {}
    seen: set[str] = set()
    for raw in re.findall(r"\b[A-Za-z][A-Za-z'’-]{3,}\b", text):
        low = raw.lower()
        if low in seen:
            continue
        seen.add(low)
        if not raw[0].isupper():
            continue
        if "'" in low or "’" in low or low in dictionary:
            continue
        if len(re.findall(r"\b" + re.escape(raw) + r"\b", text, re.IGNORECASE)) > FUZZY_MAX_OCCURRENCES:
            continue
        skel = consonant_skeleton(low)
        for anchor in anchors:
            al = anchor.lower()
            if low == al or abs(len(low) - len(al)) > 3:
                continue
            if SequenceMatcher(None, low, al).ratio() < FUZZY_SPELLING:
                continue
            if SequenceMatcher(None, skel, skeletons[anchor]).ratio() < FUZZY_SOUND:
                continue
            hits[raw] = anchor
            break
    return hits


def acronyms(company: str) -> list[str]:
    """Initialisms a speaker may use for the company, e.g. Google Cloud Platform -> GCP.

    Only generated for names of two or more significant words, and only three
    characters or longer, so a two-word company does not produce a two-letter
    token that would collide with ordinary text.
    """
    parts = [p for p in re.split(r"[\s/&-]+", company.strip()) if p and p.lower() not in {"the", "and", "of"}]
    out = set()
    if len(parts) >= 3:
        out.add("".join(p[0] for p in parts).upper())
    # Also the form with a trailing generic word appended, which is how these
    # are usually said aloud: "Google Cloud" is spoken as GCP.
    if len(parts) == 2:
        for tail in ("Platform", "Services", "Systems"):
            out.add("".join(p[0] for p in parts).upper() + tail[0])
    return [a for a in out if len(a) >= 3]


def blind(text: str, name: str, company: str, dictionary: set[str],
          aliases: list[str] | None = None) -> tuple[str, dict]:
    counts: dict[str, int] = {}
    aliases = aliases or []

    name_forms = name_variants(name)
    comp_forms = company_variants(company) + acronyms(company)
    parts = [p for p in re.split(r"\s+", name.strip()) if len(p) >= 4]

    # Exact forms first, longest first so "Jensen Huang" goes before "Huang".
    for variant in name_forms + [a for a in aliases if a]:
        pattern = re.compile(r"\b" + re.escape(variant) + r"(?:'s|s')?\b", re.IGNORECASE)
        text, n = pattern.subn(SUBJECT_TOKEN, text)
        if n:
            counts[f"name:{variant}"] = n
    for variant in comp_forms:
        pattern = re.compile(r"\b" + re.escape(variant) + r"(?:'s|s')?\b", re.IGNORECASE)
        text, n = pattern.subn(COMPANY_TOKEN, text)
        if n:
            counts[f"company:{variant}"] = n

    # Then speech-recognition corruptions of those same forms.
    for token, anchor in fuzzy_targets(text, parts, dictionary).items():
        pattern = re.compile(r"\b" + re.escape(token) + r"(?:'s|s')?\b", re.IGNORECASE)
        text, n = pattern.subn(SUBJECT_TOKEN, text)
        if n:
            counts[f"name~asr:{token}->{anchor}"] = n
    comp_anchors = [c for c in comp_forms if " " not in c]
    for token, anchor in fuzzy_targets(text, comp_anchors, dictionary).items():
        pattern = re.compile(r"\b" + re.escape(token) + r"(?:'s|s')?\b", re.IGNORECASE)
        text, n = pattern.subn(COMPANY_TOKEN, text)
        if n:
            counts[f"company~asr:{token}->{anchor}"] = n

    # Collapse runs created by adjacent replacements, e.g. "[COMPANY] [COMPANY]".
    text = re.sub(r"(\[SUBJECT\]\s+){2,}", "[SUBJECT] ", text)
    text = re.sub(r"(\[COMPANY\]\s+){2,}", "[COMPANY] ", text)
    return text, counts


# A prune is only ever as trustworthy as the source directory it trusts. If a
# fetch loop leaves data/transcripts half-written, or a path argument is wrong,
# an unguarded prune deletes the whole blinded corpus and orphans every grade
# in one silent pass. So a removal that is large in BOTH senses refuses.
# Fraction alone would block a legitimate 2-of-4 prune on a tiny corpus, and a
# count alone would block a legitimate large prune on a huge one.
PRUNE_MAX_FRACTION = 0.25   # of what is already in the output directory
PRUNE_MIN_TO_GUARD = 10     # below this many files, fraction is meaningless


def prune_orphans(out_root: Path, kept: set[tuple[str, str]], mode: str,
                  grades_root: Path | None, max_fraction: float,
                  shelf: Path | None = None,
                  rejected: set[tuple[str, str]] | None = None) -> dict:
    """Withdraw derived transcripts that this run did not write, and their grades.

    A transcript leaves the corpus two ways: dedupe_transcripts.py --sweep
    retires it as a duplicate, or QA rejects it. Neither used to reach here,
    because this script only ever wrote files. The copy stayed in the output
    directory, grade.py globs that whole directory, and aggregate.py counts
    every grade it finds, so a withdrawn appearance kept scoring forever.

    Two conditions must BOTH hold before a file goes: this run did not write it,
    and its source is either off the shelf or rejected by QA. The first test
    alone was a live defect. `fetch_loop.sh` and `grade_loop.sh` both normalize
    the same directories, and each lists the corpus once at the top, so a
    transcript that arrived between one run's listing and its prune looked
    withdrawn to that run and had its grades orphaned while its source sat on
    the shelf. Re-reading the shelf here closes that window, because the second
    test is evaluated at deletion time rather than at listing time.

    Only `grade_loop.sh` passes `--grades` and prunes at all. That is belt and
    braces: this function is safe under a race, and the fleet still keeps one
    writer per directory the way the rest of the repo does.

    Grades are renamed to `.orphaned` rather than deleted, so the choice stays
    auditable, and only grades for THIS mode are touched, because the blinded
    and open passes each own one output directory and one half of the grades.
    Raw judge output under `_raw` is left alone; it is evidence, not a score.
    """
    rejected = rejected or set()
    existing = sorted(out_root.rglob("*.json"))

    def withdrawn(p: Path) -> bool:
        key = (p.parent.name, p.stem)
        if key in kept:
            return False                      # this run wrote it
        if key in rejected:
            return True                       # QA turned against it
        if shelf is None:
            return True                       # no shelf to consult; old behaviour
        return not (shelf / key[0] / f"{key[1]}.json").exists()

    stale = [p for p in existing if withdrawn(p)]
    report = {
        "mode": mode, "examined": len(existing), "pruned": len(stale),
        "pruned_ids": [f"{p.parent.name}/{p.stem}" for p in stale],
        "orphaned_grades": 0, "orphaned_grade_files": [],
        "grades_checked": str(grades_root) if grades_root else None,
    }
    if not stale:
        return report

    frac = len(stale) / len(existing)
    if len(stale) >= PRUNE_MIN_TO_GUARD and frac > max_fraction:
        # Reported, not raised. The caller writes the log first, so a refused
        # cycle leaves an accurate record instead of the previous cycle's
        # success sitting there looking current.
        report["pruned"] = 0
        report["pruned_ids"] = []
        report["refused"] = True
        report["would_have_pruned"] = len(stale)
        report["would_have_pruned_ids"] = [f"{p.parent.name}/{p.stem}" for p in stale]
        report["reason"] = (
            f"REFUSING TO PRUNE: {len(stale)} of {len(existing)} derived transcripts in "
            f"{out_root} ({frac:.0%}) are withdrawn, above the {max_fraction:.0%} ceiling. "
            f"That usually means --transcripts points at the wrong directory or the corpus "
            f"is half-written, not that {len(stale)} appearances were withdrawn at once. "
            f"Nothing has been deleted. Check the source directory, then re-run with "
            f"--prune-max-fraction to allow it.")
        return report

    for p in stale:
        p.unlink()

    if grades_root and grades_root.exists():
        drop = {(p.parent.name, p.stem) for p in stale}
        for gp in sorted(grades_root.rglob("*.json")):
            if "_raw" in gp.parts:
                continue
            parts = gp.stem.split("__")
            if len(parts) < 3 or parts[2] != mode:
                continue
            if (gp.parent.name, parts[0]) not in drop:
                continue
            gp.rename(str(gp) + ".orphaned")
            report["orphaned_grades"] += 1
            report["orphaned_grade_files"].append(gp.name)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--roster", required=True)
    ap.add_argument("--repairs", default=None,
                    help='JSON: {"leader-slug": [{"wrong":"...","right":"..."}]}')
    ap.add_argument("--aliases", default=None,
                    help='JSON: {"leader-slug": ["nickname", "known ASR misspelling", ...]} extra strings to blind.')
    ap.add_argument("--qa", default=None,
                    help="transcript_qa.json; transcripts with verdict reject are excluded.")
    ap.add_argument("--mode", choices=["blinded", "open"], default="blinded")
    ap.add_argument("--log", required=True)
    ap.add_argument("--grades", default=None,
                    help="Grades directory. Withdrawing a transcript only stops it scoring "
                         "if its grades go too, because aggregate.py reads grades and never "
                         "looks at this output directory.")
    ap.add_argument("--no-prune", action="store_true",
                    help="Leave derived transcripts this run did not write. They stay "
                         "gradeable and keep counting, so this is for debugging only.")
    ap.add_argument("--prune-max-fraction", type=float, default=PRUNE_MAX_FRACTION,
                    help="Refuse to prune more than this share of the output directory.")
    args = ap.parse_args()

    roster = json.loads(Path(args.roster).read_text())
    by_slug = {r["slug"]: r for r in roster["roster"]}
    repairs = json.loads(Path(args.repairs).read_text()) if args.repairs and Path(args.repairs).exists() else {}
    aliases = json.loads(Path(args.aliases).read_text()) if args.aliases and Path(args.aliases).exists() else {}
    dictionary = load_dictionary() if args.mode == "blinded" else set()

    rejected: set[tuple[str, str]] = set()
    if args.qa and Path(args.qa).exists():
        qa = json.loads(Path(args.qa).read_text())
        rejected = {(r["leader_slug"], r["source_id"]) for r in qa["reports"] if r["verdict"] == "reject"}

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    entries = []
    skipped = 0
    for path in sorted(Path(args.transcripts).rglob("*.json")):
        if path.name.endswith(".json.tmp"):
            continue
        rec = json.loads(path.read_text())
        if "leader_slug" not in rec or "text" not in rec:
            continue  # not a transcript record
        slug, sid = rec["leader_slug"], rec["source_id"]
        if (slug, sid) in rejected:
            skipped += 1
            continue
        person = by_slug.get(slug)
        if not person:
            raise SystemExit(f"transcript {slug}/{sid} has no roster entry; refusing to guess identity")

        text = rec["text"]
        text, loopfix = collapse_loops(text)
        original_words = len(text.split())
        text, parafix = collapse_paragraph_loops(text)
        parafix["original_word_count"] = original_words
        text, applied = apply_repairs(text, repairs.get(slug, []))
        blind_counts: dict[str, int] = {}
        if args.mode == "blinded":
            text, blind_counts = blind(text, person["name"], person["company"],
                                       dictionary, aliases.get(slug, []))

        rec_out = dict(rec)
        rec_out["text"] = text
        if parafix["tokens_removed"]:
            # The judge is told the transcript length, and the length it is
            # told must be the length it is given.
            rec_out["word_count"] = len(text.split())
        rec_out["normalization"] = {
            "mode": args.mode,
            # When this derived copy was written, in UTC, read from the clock
            # and never from a file mtime: the loops touch these files every
            # cycle. It is what lets a later step tell a grade of THIS text
            # apart from a grade of the text this replaced, which is the
            # difference between a needed re-grade and 27 wasted judge calls.
            "normalized_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "loop_collapse": loopfix,
            "paragraph_loop_collapse": parafix,
            "repairs_applied": applied,
            "repair_substitutions": sum(a["count"] for a in applied),
            "repairs_that_matched_nothing": [a["wrong"] for a in applied if a["count"] == 0],
            "blind_substitutions": blind_counts,
            "blind_total": sum(blind_counts.values()),
        }
        # The original identity is kept out of the graded payload but retained
        # here in the record for the aggregation step to join on.
        dest = out_root / slug / f"{sid}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec_out, ensure_ascii=False, indent=1))
        os.replace(tmp, dest)

        entries.append({
            "leader_slug": slug, "source_id": sid,
            "repair_substitutions": rec_out["normalization"]["repair_substitutions"],
            "loop_tokens_removed": loopfix["tokens_removed"],
            "repairs_that_matched_nothing": rec_out["normalization"]["repairs_that_matched_nothing"],
            "blind_total": rec_out["normalization"]["blind_total"],
            "word_count": rec.get("word_count"),
        })

    kept = {(e["leader_slug"], e["source_id"]) for e in entries}
    prune = ({"mode": args.mode, "examined": None, "pruned": 0, "pruned_ids": [],
              "orphaned_grades": 0, "orphaned_grade_files": [], "grades_checked": None,
              "disabled": True}
             if args.no_prune else
             prune_orphans(out_root, kept, args.mode,
                           Path(args.grades) if args.grades else None,
                           args.prune_max_fraction,
                           shelf=Path(args.transcripts), rejected=rejected))

    summary = {
        "mode": args.mode,
        "written": len(entries),
        "skipped_qa_reject": skipped,
        "prune": prune,
        "total_repair_substitutions": sum(e["repair_substitutions"] for e in entries),
        "total_loop_tokens_removed": sum(e["loop_tokens_removed"] for e in entries),
        "total_blind_substitutions": sum(e["blind_total"] for e in entries),
        "transcripts_with_zero_blind_hits": [
            f"{e['leader_slug']}/{e['source_id']}" for e in entries if args.mode == "blinded" and e["blind_total"] == 0
        ],
    }
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    Path(args.log).write_text(json.dumps({"summary": summary, "entries": entries}, indent=1))
    if prune.get("refused"):
        # The log is on disk before this returns, so the refusal is recorded
        # even though the cycle fails.
        print(prune["reason"], file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    if prune["pruned"] and not args.grades:
        print(f"WARNING: withdrew {prune['pruned']} derived transcripts but --grades was not "
              f"given, so their grades are still on disk and aggregate.py still counts them. "
              f"Pass --grades to complete the withdrawal.", file=sys.stderr)
    if prune["pruned"]:
        print(f"withdrew {prune['pruned']} derived transcripts "
              f"({', '.join(prune['pruned_ids'][:6])}"
              f"{', ...' if prune['pruned'] > 6 else ''}) and orphaned "
              f"{prune['orphaned_grades']} {args.mode} grades", file=sys.stderr)
    if summary["transcripts_with_zero_blind_hits"]:
        print(f"WARNING: {len(summary['transcripts_with_zero_blind_hits'])} transcripts had no name/company "
              f"to blind; check the roster spelling matches how the speaker is named on air.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
