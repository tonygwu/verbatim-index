#!/usr/bin/env python3
"""The blinder must not delete ordinary English out of the transcript.

`aliases_for()` in discover_sources.py splits a multi-word company name and
adds every part as its own alias, so "Advanced Machine Intelligence Labs" puts
bare "Machine" and "Intelligence" on Yann LeCun's list. `blind()` then applied
every alias unconditionally, case-insensitively, through the NAME path. Two
consequences, both live on the published board:

  - the judge read "the history of artificial [SUBJECT]", losing exactly the
    domain vocabulary the rubric asks it to grade
  - a company reference was stamped [SUBJECT], which tells the judge the
    company IS the person being graded

MEASURED 2026-09-12 over data/transcripts_open: 2,796 ordinary words replaced
across 152 transcripts and 16 leaders, 89% of them concentrated in six people,
two of whom are ranked 1 and 3.

The corrected behaviour is OPT-IN via the `wordlist` argument, because changing
blinding makes new grades incomparable with the ~2,260 already collected. These
checks pin BOTH paths: that the default still reproduces the bug byte for byte,
and that passing the frozen wordlist fixes it without weakening the redaction.

No quota, no network, no data directory.
Run: .venv/bin/python scripts/test_blind_common_words.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize_transcripts import (  # noqa: E402
    alias_is_company, blind, load_blind_wordlist, load_dictionary)

DICT = load_dictionary()
WL = load_blind_wordlist()

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


LECUN = ("Yann LeCun", "Advanced Machine Intelligence Labs",
         ["AMIL", "Advanced", "Advanced Machine Intelligence Labs", "Intelligence",
          "Labs", "LeCun", "Machine", "Yann", "Yann LeCun"])
SWEENEY = ("Tim Sweeney", "Epic Games",
           ["Epic", "Epic Games", "Games", "Sweeney", "Tim", "Tim Sweeney"])
KURIAN = ("Thomas Kurian", "Google Cloud",
          ["Alphabet", "Cloud", "Google", "Google Cloud", "Kurian", "Thomas",
           "Thomas Kurian"])
DARA = ("Dara Khosrowshahi", "Uber",
        ["Dara", "Dara Khosrowshahi", "Khosrowshahi", "Uber"])


def v1(text, who):
    return blind(text, who[0], who[1], DICT, who[2])[0]


def v2(text, who):
    return blind(text, who[0], who[1], DICT, who[2], wordlist=WL)[0]


def main() -> int:
    print("blinding must spare ordinary English\n")

    print("[1] the bug, still reproduced by the default path")
    t = "The history of artificial intelligence is a machine learning story."
    check("v1 destroys 'intelligence' and 'machine'",
          "[SUBJECT] is a [SUBJECT] learning" in v1(t, LECUN),
          f"got {v1(t, LECUN)!r}")
    t2 = "The experience of creating video games is why games matter."
    check("v1 destroys 'games'", "video [SUBJECT]" in v1(t2, SWEENEY),
          f"got {v1(t2, SWEENEY)!r}")

    print("\n[2] the fix returns the ordinary words")
    check("v2 keeps 'artificial intelligence'", "artificial intelligence" in v2(t, LECUN),
          f"got {v2(t, LECUN)!r}")
    check("v2 keeps 'machine learning'", "machine learning" in v2(t, LECUN),
          f"got {v2(t, LECUN)!r}")
    check("v2 keeps 'video games'", "video games" in v2(t2, SWEENEY),
          f"got {v2(t2, SWEENEY)!r}")
    t3 = "Every cloud provider competes, and the world is watching."
    check("v2 keeps 'cloud provider'", "cloud provider" in v2(t3, KURIAN),
          f"got {v2(t3, KURIAN)!r}")

    print("\n[3] but the company itself is still hidden")
    for text, who, gone in [
        ("I run Google Cloud and we compete hard.", KURIAN, "Google Cloud"),
        ("Cloud is our business.", KURIAN, "Cloud"),
        ("I founded Epic Games in 1991.", SWEENEY, "Epic Games"),
        ("Games is what we called it.", SWEENEY, "Games"),
        ("We built Advanced Machine Intelligence Labs.", LECUN,
         "Advanced Machine Intelligence Labs"),
    ]:
        out = v2(text, who)
        check(f"v2 hides {gone!r}", gone.lower() not in out.lower(), f"got {out!r}")

    print("\n[4] a company word that is NOT ordinary English stays fully hidden")
    t4 = "I joined uber in 2017 and Uber grew fast."
    out = v2(t4, DARA)
    check("v2 hides lowercase 'uber' too", "uber" not in out.lower(), f"got {out!r}")
    t5 = "we use google every day"
    check("v2 hides lowercase 'google' too", "google" not in v2(t5, KURIAN).lower(),
          f"got {v2(t5, KURIAN)!r}")

    print("\n[5] a company reference is [COMPANY], never [SUBJECT]")
    _, c = blind("Cloud and Google Cloud and Alphabet.", KURIAN[0], KURIAN[1],
                 DICT, KURIAN[2], wordlist=WL)
    check("no company token is filed under name:",
          not any(k.startswith("name:") for k in c), f"counts {c}")
    out = v2("I am proud of Google Cloud.", KURIAN)
    check("the company reads [COMPANY]", "[COMPANY]" in out and "[SUBJECT]" not in out,
          f"got {out!r}")
    _, c1 = blind("I am proud of Google Cloud.", KURIAN[0], KURIAN[1], DICT, KURIAN[2])
    check("v1 filed that same company alias under name: (the defect)",
          any(k.startswith("name:") for k in c1), f"counts {c1}")

    print("\n[6] the person is still redacted, by name and by alias")
    out = v2("Thomas Kurian said so, and Kurian repeated it.", KURIAN)
    check("the name is gone", "kurian" not in out.lower() and "[SUBJECT]" in out,
          f"got {out!r}")
    out = v2("Yann LeCun and LeCun.", LECUN)
    check("name aliases still map to [SUBJECT]", "[SUBJECT]" in out
          and "lecun" not in out.lower(), f"got {out!r}")

    print("\n[7] alias_is_company classifies the flat alias list")
    for alias, name, want in [
        ("Machine", "Yann LeCun", True), ("AMIL", "Yann LeCun", True),
        ("LeCun", "Yann LeCun", False), ("Yann LeCun", "Yann LeCun", False),
        ("Fei-Fei", "Fei-Fei Li", False), ("World", "Fei-Fei Li", True),
        ("Games", "Tim Sweeney", True), ("Tim", "Tim Sweeney", False),
    ]:
        got = alias_is_company(alias, name)
        check(f"{alias!r} of {name!r} -> {'company' if want else 'name'}", got == want,
              f"got {'company' if got else 'name'}")

    print("\n[8] the frozen wordlist covers the measured offenders")
    for w in ("world", "games", "machine", "intelligence", "face", "cloud"):
        check(f"{w!r} is listed ordinary", w in WL)
    for w in ("uber", "google", "hugging", "mistral", "palantir"):
        check(f"{w!r} is NOT listed ordinary", w not in WL,
              "freeing this token would weaken the redaction")

    print("\n[9] the wordlist is frozen with its evidence, not computed at runtime")
    doc = json.loads((Path(__file__).resolve().parent / "blind_wordlist.json").read_text())
    check("it records the threshold", isinstance(doc.get("spread_threshold"), float))
    check("it records the occurrence floor", isinstance(doc.get("min_occurrences"), int))
    check("it records what it measured over", doc.get("transcripts_measured", 0) > 100)
    check("every ordinary token carries its evidence",
          all(any(e["token"].lower() == t and e["ordinary"] for e in doc["evidence"])
              for t in doc["ordinary"]))

    print(f"\n{passed}/{passed + failed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
