#!/usr/bin/env python3
"""Tests for identity blinding.

Blinding runs on every transcript before grading, so a false positive here
silently corrupts the input to every score. Two failure modes matter:

  MISS      a real mention of the subject or company survives, so the judge
            can recognise them and a reputation halo enters the score.
  OVEREACH  an ordinary word is replaced with [SUBJECT], which damages the
            transcript the judge is asked to reason about.

The overeach cases below are drawn from a real failure: matching the surname
"Thomas" loosely enough to catch the speech-recognition variant "Kurion" also
caught the contraction "that's", 34 times in one transcript.

Run: .venv/bin/python scripts/test_blinding.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize_transcripts import blind, load_dictionary  # noqa: E402

DICT = load_dictionary()

# (label, text, name, company, aliases, must_be_hidden, must_survive)
CASES = [
    (
        "kurian: asr variants of the surname must go",
        "Today we're joined by Thomas Curran. Kurion runs Google Cloud, and GCP is growing. "
        "Kurian said that's the thing that matters. Google is currently the current leader. "
        "Every cloud provider competes and the curtain is drawn.",
        "Thomas Kurian", "Google Cloud", [],
        ["Curran", "Kurion", "Kurian", "Thomas", "Google", "GCP"],
        ["that's", "current", "currently", "cloud provider", "curtain"],
    ),
    (
        "nadella: mangled surname and possessives",
        "Satya Nadella joined us. Nadela and Adela are how the captions render it. "
        "Microsoft is huge. Satya's view is clear. The saga continues and the data is sad.",
        "Satya Nadella", "Microsoft", ["Adela"],
        ["Nadella", "Nadela", "Satya", "Microsoft"],
        ["saga", "data", "sad", "continues"],
    ),
    (
        "huang: short surname must not eat common words",
        "Jensen Huang spoke. Hwang and Wang appear in captions. NVIDIA sells chips. "
        "They hang around and the thing was long and young people came.",
        "Jensen Huang", "NVIDIA", ["Hwang"],
        ["Jensen", "Huang", "Hwang", "NVIDIA"],
        ["long", "young", "thing", "around", "hang around"],
    ),
    (
        "altman: company alias and ordinary vocabulary",
        "Sam Altman leads OpenAI. Open AI and Altmann also appear. "
        "The salmon was old and the man was calm. Almost all of it.",
        "Sam Altman", "OpenAI", ["Open AI", "Altmann"],
        ["Altman", "Altmann", "OpenAI", "Open AI"],
        ["salmon", "calm", "Almost", "old"],
    ),
    (
        "pichai: frequent contractions must survive",
        "Sundar Pichai runs Google. Pichai says it's fine. That's what they'd say. "
        "It's picking up and the pitch is high.",
        "Sundar Pichai", "Google", [],
        ["Sundar", "Pichai", "Google"],
        ["it's", "That's", "pitch", "picking"],
    ),
]


def run() -> int:
    failures: list[str] = []
    for label, text, name, company, aliases, must_hide, must_keep in CASES:
        out, counts = blind(text, name, company, DICT, aliases)
        low = out.lower()
        for term in must_hide:
            if term.lower() in low:
                failures.append(f"MISS     [{label}] {term!r} survived blinding")
        for term in must_keep:
            if term.lower() not in low:
                failures.append(f"OVEREACH [{label}] {term!r} was destroyed by blinding")
        print(f"  {label}\n    -> {out}\n    -> {counts}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} problem(s)")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"PASSED: {len(CASES)} cases, no misses and no overeach")
    return 0


if __name__ == "__main__":
    sys.exit(run())
