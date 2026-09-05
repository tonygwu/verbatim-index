#!/usr/bin/env python3
"""Quality-check fetched transcripts and flag ones unfit to grade.

YouTube auto-captions are verbatim in the sense that no model rewrote them,
but automatic speech recognition still corrupts proper nouns, loops on
repeated phrases, and sometimes captions the wrong content entirely. This
script computes deterministic quality signals per transcript and assigns a
gate verdict. It never edits transcript text; repair is a separate, logged
step in normalize_transcripts.py.

Signals computed per transcript:
  oov_rate            fraction of alphabetic tokens absent from the system
                      dictionary and from the leader glossary. High values
                      mean garbled recognition.
  loop_score          longest run of an immediately repeated 5-gram, a
                      classic ASR failure mode.
  type_token_ratio    unique words / total words. Very low means looping or
                      a long repeated ad read.
  words_per_minute    words divided by video minutes. Very low means the
                      video is mostly non-speech.
  subject_name_hits   times the subject's surname appears.
  company_hits        times the subject's company appears.
  nonspeech_ratio     share of tokens inside [Music]/[Applause] style markers.

Usage:
  qa_transcripts.py --transcripts data/transcripts --roster data/roster/final.json \
      --out data/logs/transcript_qa.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

WORD_RE = re.compile(r"[a-z']+")
STAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")
NONSPEECH_RE = re.compile(r"\[(music|applause|laughter|cheering|silence)\]", re.I)

# Thresholds. Chosen to be permissive: the goal is to catch transcripts that
# are clearly unusable, not to trim borderline ones. Every rejection is
# reported with the signal that triggered it.
# A commentary show discussing someone says their name constantly. The person
# themself, being interviewed, is named at the introduction and then hardly at
# all. Measured on real transcripts: an interview runs well under 1 mention per
# 1000 words after the opening, a show about them runs many times that. This is
# the check that catches a video which passed every title filter and is still
# not the subject speaking.
MAX_NAME_PER_1K_AFTER_INTRO = 1.6
INTRO_FRACTION = 0.12   # the opening where being named repeatedly is normal

MAX_OOV = 0.18
MAX_LOOP = 6
MIN_TTR = 0.10
MIN_WPM = 60
MIN_WORDS = 700


def load_dictionary() -> set[str]:
    words = set()
    for path in ("/usr/share/dict/words", "/usr/dict/words"):
        p = Path(path)
        if p.exists():
            words.update(w.strip().lower() for w in p.read_text(errors="ignore").splitlines() if w.strip())
            break
    if not words:
        raise SystemExit("no system dictionary found at /usr/share/dict/words; cannot compute oov_rate")
    # Contractions and speech artifacts the dictionary lacks but ASR emits constantly.
    words.update({
        "ok", "okay", "um", "uh", "yeah", "gonna", "wanna", "gotta", "kinda", "sorta",
        "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't", "can't",
        "couldn't", "won't", "wouldn't", "shouldn't", "haven't", "hasn't", "hadn't",
        "i'm", "i've", "i'll", "i'd", "you're", "you've", "you'll", "you'd",
        "we're", "we've", "we'll", "we'd", "they're", "they've", "they'll", "they'd",
        "it's", "that's", "there's", "here's", "what's", "who's", "let's", "he's",
        "she's", "who've", "how's", "where's", "ai", "api", "apis", "ceo", "cto",
        "gpu", "gpus", "cpu", "cpus", "llm", "llms", "saas", "iot", "url", "urls",
    })
    return words


def longest_repeat_run(tokens: list[str], n: int = 5) -> int:
    """Longest run of the same n-gram repeating back to back."""
    if len(tokens) < n * 2:
        return 0
    grams = [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]
    best = 0
    run = 1
    for i in range(1, len(grams)):
        if grams[i] == grams[i - 1]:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def analyze(rec: dict, dictionary: set[str], glossary: set[str]) -> dict:
    raw = rec.get("text") or ""
    nonspeech_hits = len(NONSPEECH_RE.findall(raw))
    body = STAMP_RE.sub(" ", raw)
    body = NONSPEECH_RE.sub(" ", body)
    lower = body.lower()
    tokens = WORD_RE.findall(lower)
    n = len(tokens)
    if n == 0:
        return {"error": "empty_after_cleaning", "word_count": 0}

    known = dictionary | glossary
    oov = [t for t in tokens if t not in known]
    counts = Counter(tokens)
    duration_min = (rec.get("duration_sec") or 0) / 60.0

    return {
        "word_count": n,
        "oov_rate": round(len(oov) / n, 4),
        "top_oov": [w for w, _ in Counter(oov).most_common(15)],
        "loop_score": longest_repeat_run(tokens),
        "type_token_ratio": round(len(counts) / n, 4),
        "words_per_minute": round(n / duration_min, 1) if duration_min > 0 else None,
        "nonspeech_markers": nonspeech_hits,
        "duration_min": round(duration_min, 1) if duration_min else None,
        "caption_track": rec.get("caption_track"),
    }


def name_density_after_intro(text: str, surname: str) -> tuple[float, int]:
    """Surname mentions per 1000 words, ignoring the introduction.

    Returns (rate, count). A high rate means the transcript keeps referring to
    the person in the third person, which is what a show ABOUT them does.
    """
    if not surname:
        return 0.0, 0
    words = text.split()
    if len(words) < 200:
        return 0.0, 0
    body = " ".join(words[int(len(words) * INTRO_FRACTION):])
    hits = len(re.findall(r"\b" + re.escape(surname) + r"\b", body, re.I))
    return (hits / (len(body.split()) / 1000.0)), hits


def gate(sig: dict, name_hits: int, company_hits: int) -> tuple[str, list[str]]:
    """Return (verdict, reasons). Verdict is pass, review, or reject."""
    reasons: list[str] = []
    if sig.get("error"):
        return "reject", [sig["error"]]
    if sig["word_count"] < MIN_WORDS:
        reasons.append(f"word_count {sig['word_count']} < {MIN_WORDS}")
    if sig["oov_rate"] > MAX_OOV:
        reasons.append(f"oov_rate {sig['oov_rate']} > {MAX_OOV} (garbled recognition)")
    if sig["loop_score"] >= MAX_LOOP:
        reasons.append(f"loop_score {sig['loop_score']} >= {MAX_LOOP} (ASR repetition loop)")
    if sig["type_token_ratio"] < MIN_TTR:
        reasons.append(f"type_token_ratio {sig['type_token_ratio']} < {MIN_TTR}")
    wpm = sig.get("words_per_minute")
    if wpm is not None and wpm < MIN_WPM:
        reasons.append(f"words_per_minute {wpm} < {MIN_WPM} (mostly non-speech)")
    rate = sig.get("name_per_1k_after_intro")
    if rate is not None and rate > MAX_NAME_PER_1K_AFTER_INTRO:
        reasons.append(
            f"subject named {rate:.1f} times per 1000 words after the introduction "
            f"(limit {MAX_NAME_PER_1K_AFTER_INTRO}); this reads as a show ABOUT the "
            f"subject rather than the subject speaking")
    if reasons:
        return "reject", reasons

    soft: list[str] = []
    if name_hits == 0:
        soft.append("subject surname never appears in transcript")
    if company_hits == 0:
        soft.append("subject company never appears in transcript")
    if sig["oov_rate"] > MAX_OOV * 0.7:
        soft.append(f"elevated oov_rate {sig['oov_rate']}")
    if soft:
        return "review", soft
    return "pass", []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts", required=True)
    ap.add_argument("--roster", required=True)
    ap.add_argument("--glossaries", default=None,
                    help="Optional JSON mapping leader_slug -> list of proper nouns, to suppress false OOV hits.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    dictionary = load_dictionary()
    roster = json.loads(Path(args.roster).read_text())
    by_slug = {r["slug"]: r for r in roster["roster"]}

    glossaries: dict[str, list[str]] = {}
    if args.glossaries and Path(args.glossaries).exists():
        glossaries = json.loads(Path(args.glossaries).read_text())

    reports = []
    troot = Path(args.transcripts)
    for path in sorted(troot.rglob("*.json")):
        rec = json.loads(path.read_text())
        slug = rec["leader_slug"]
        person = by_slug.get(slug, {})
        gloss_terms = set()
        for term in glossaries.get(slug, []):
            gloss_terms.update(WORD_RE.findall(term.lower()))
        # The person's own name and company must never count as garble.
        for term in (person.get("name", ""), person.get("company", "")):
            gloss_terms.update(WORD_RE.findall(term.lower()))

        sig = analyze(rec, dictionary, gloss_terms)
        lower = (rec.get("text") or "").lower()
        surname = (person.get("name", "") or rec["leader_slug"].replace("-", " ")).split()[-1].lower()
        company_word = (person.get("company", "") or "").split()[0].lower()
        name_hits = lower.count(surname) if surname else 0
        company_hits = lower.count(company_word) if company_word else 0

        rate, after_intro_hits = name_density_after_intro(rec.get("text") or "", surname)
        sig["name_per_1k_after_intro"] = round(rate, 2)
        sig["name_hits_after_intro"] = after_intro_hits
        verdict, reasons = gate(sig, name_hits, company_hits)
        reports.append({
            "leader_slug": slug,
            "source_id": rec["source_id"],
            "video_id": rec["video_id"],
            "title": rec.get("yt_title") or rec.get("declared_title"),
            "channel": rec.get("yt_channel"),
            "verdict": verdict,
            "reasons": reasons,
            "subject_name_hits": name_hits,
            "company_hits": company_hits,
            **sig,
        })

    tally = Counter(r["verdict"] for r in reports)
    per_leader = Counter(r["leader_slug"] for r in reports if r["verdict"] != "reject")
    summary = {
        "transcripts_examined": len(reports),
        "verdicts": dict(tally),
        "leaders_with_usable_transcripts": len(per_leader),
        "min_usable_per_leader": min(per_leader.values()) if per_leader else 0,
        "thresholds": {
            "max_oov_rate": MAX_OOV, "max_loop_score": MAX_LOOP,
            "min_type_token_ratio": MIN_TTR, "min_words_per_minute": MIN_WPM,
            "min_words": MIN_WORDS,
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "reports": reports}, indent=1))
    print(json.dumps(summary, indent=2))
    for r in reports:
        if r["verdict"] == "reject":
            print(f"  REJECT {r['leader_slug']}/{r['source_id']}: {'; '.join(r['reasons'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
