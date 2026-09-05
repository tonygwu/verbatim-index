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
import re
import sys
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
        text, applied = apply_repairs(text, repairs.get(slug, []))
        blind_counts: dict[str, int] = {}
        if args.mode == "blinded":
            text, blind_counts = blind(text, person["name"], person["company"],
                                       dictionary, aliases.get(slug, []))

        rec_out = dict(rec)
        rec_out["text"] = text
        rec_out["normalization"] = {
            "mode": args.mode,
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
        dest.write_text(json.dumps(rec_out, ensure_ascii=False, indent=1))

        entries.append({
            "leader_slug": slug, "source_id": sid,
            "repair_substitutions": rec_out["normalization"]["repair_substitutions"],
            "repairs_that_matched_nothing": rec_out["normalization"]["repairs_that_matched_nothing"],
            "blind_total": rec_out["normalization"]["blind_total"],
            "word_count": rec.get("word_count"),
        })

    summary = {
        "mode": args.mode,
        "written": len(entries),
        "skipped_qa_reject": skipped,
        "total_repair_substitutions": sum(e["repair_substitutions"] for e in entries),
        "total_blind_substitutions": sum(e["blind_total"] for e in entries),
        "transcripts_with_zero_blind_hits": [
            f"{e['leader_slug']}/{e['source_id']}" for e in entries if args.mode == "blinded" and e["blind_total"] == 0
        ],
    }
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    Path(args.log).write_text(json.dumps({"summary": summary, "entries": entries}, indent=1))
    print(json.dumps(summary, indent=2))
    if summary["transcripts_with_zero_blind_hits"]:
        print(f"WARNING: {len(summary['transcripts_with_zero_blind_hits'])} transcripts had no name/company "
              f"to blind; check the roster spelling matches how the speaker is named on air.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
