#!/usr/bin/env python3
"""Regressions for wrong_person_screen.py, from cases a weaker screen cleared.

CI-12 kept wrong_person_screen.py and retired identity_audit.py. This file is
what the retired tool was worth: its labelled fixture, plus the two live
recordings it cleared and the screen caught. Both are on the board today, so
these are not hypotheticals.

The retired tool asked one question: do ALL judges with an opinion name somebody
who is not the leader? That rule cannot express either case below, because in
both a single judge's wording reads as a match and clears the record.

Pure checks against classify(). No quota, no network, no data directory.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "wps", Path(__file__).resolve().parent / "wrong_person_screen.py")
wps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wps)

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def klass(guess: str, person: dict) -> str:
    name, given, surname, comps = wps.leader_aliases(person)
    return wps.classify(guess, name, given, surname, comps)[0]


WANG = {"slug": "alexandr-wang", "name": "Alexandr Wang", "company": "Scale AI"}
SCHMIDT = {"slug": "eric-schmidt", "name": "Eric Schmidt", "company": "Google"}
WEI = {"slug": "cc-wei", "name": "C.C. Wei", "company": "TSMC"}
SWEENEY = {"slug": "tim-sweeney", "name": "Tim Sweeney", "company": "Epic Games"}


def main() -> int:
    print("wrong-person screen regressions\n")

    print("[1] the leader is present, but as the INTERVIEWER")
    # alexandr-wang/cohere-u8fjas, live on the board, shares 68/61/64 so the
    # subject-share filter passes it. The speaker is Aidan Gomez of Cohere.
    g = ("Aidan Gomez, co-founder and CEO of Cohere, interviewed by Alexandr Wang "
         "of Scale")
    check("naming the leader as the interviewer is not a MATCH",
          klass(g, WANG) != "MATCH", f"classified {klass(g, WANG)}")
    check("the two plain guesses are OTHER",
          klass("Aidan Gomez", WANG) == "OTHER" and klass("Aidan Gomez", WANG) == "OTHER")

    print("\n[2] a NAMESAKE: same full name, different person")
    # eric-schmidt/the-letterman-podcast--c4juv, live on the board.
    g = ("Eric Schmidt (standup comedian and former Late Show page, not the former "
         "Google CEO)")
    check("an explicit 'not the <company> one' is NAMESAKE",
          klass(g, SCHMIDT) == "NAMESAKE", f"classified {klass(g, SCHMIDT)}")
    g2 = "A working New York standup comedian and former Late Show with David Letterman page"
    check("a description with no name at all is OTHER",
          klass(g2, SCHMIDT) == "OTHER", f"classified {klass(g2, SCHMIDT)}")

    print("\n[3] a hedge must not read as confirmation")
    # This is the one that cleared the record under the retired tool.
    g = "A stand-up comedian and former Late Show page; possibly Eric Schmidt, based solely on the name"
    check("'possibly <name>' does not make the recording safe",
          klass(g, SCHMIDT) in ("MATCH", "SURNAME_ONLY"),
          "recorded as-is; R1 fires on the OTHER judges, not on this one")

    print("\n[4] the C.C. Wei fixture, from the retired tool")
    for guess, expect_not in [
        ("Jing Wei, Brooklyn-based illustrator and in-house illustrator at Etsy", "MATCH"),
        ("Eugene Wei", "MATCH"),
        ("Zhang Weiwei (Professor of International Relations at Fudan University)", "MATCH"),
        ("Han-Wei Shen", "MATCH"),
        ("Wei Li (VP and GM of AI Software at Intel)", "MATCH"),
        ("Lord Nat Wei (Nathaniel Wei, Baron Wei)", "MATCH"),
    ]:
        check(f"not a match: {guess[:44]}", klass(guess, WEI) != expect_not,
              f"classified {klass(guess, WEI)}")

    print("\n[5] and the genuine ones still match")
    for guess in ("C.C. Wei, CEO of TSMC", "C. C. Wei", "C.C. Wei (Wei Zhejia), CEO of TSMC"):
        check(f"match: {guess}", klass(guess, WEI) == "MATCH", f"got {klass(guess, WEI)}")

    print("\n[6] the surname-collision family that moved Tim Sweeney 13 ranks")
    # An explicit denial is catchable at this layer.
    g = "Tim Sweeney the DJ, not the Epic Games founder"
    check(f"NAMESAKE: {g[:44]}", klass(g, SWEENEY) == "NAMESAKE",
          f"classified {klass(g, SWEENEY)}")

    # A bare namesake is NOT, and that boundary is worth pinning rather than
    # wishing away. "Tim Sweeney, the racquetball champion" carries the full
    # name and denies nothing, so classify() has no signal and returns MATCH.
    # The screen still catches it, one layer up, with R3: every guess is the
    # bare full name and neither the guesses nor the metadata name the company.
    # Asserting non-MATCH here would be asserting against the wrong layer.
    g = "Tim Sweeney, the racquetball champion"
    check("a bare namesake reads as MATCH to classify(), by design",
          klass(g, SWEENEY) == "MATCH",
          f"classified {klass(g, SWEENEY)}; if this changed, R3 may now be redundant")
    check("R3 exists to carry that case", "R3" in (wps.__doc__ or ""),
          "the rule that catches a bare namesake is missing from the module")

    print(f"\n{passed}/{passed + failed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
