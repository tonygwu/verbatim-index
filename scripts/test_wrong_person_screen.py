#!/usr/bin/env python3
"""Guards for wrong_person_screen.py. Pure checks, no quota, no data/.

Each case here is a matching trap that produced a wrong verdict on the corpus of
2026-09-10 before it was fixed, or a rule whose evidence is recorded in
docs/CORPUS-INTEGRITY-FOLLOWUP.md.

  .venv/bin/python scripts/test_wrong_person_screen.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


spec = importlib.util.spec_from_file_location("wps", REPO / "scripts" / "wrong_person_screen.py")
wps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wps)

ROSTER = [
    {"slug": "michael-dell", "name": "Michael Dell", "company": "Dell Technologies"},
    {"slug": "clem-delangue", "name": "Clem Delangue", "company": "Hugging Face"},
    {"slug": "cc-wei", "name": "C.C. Wei", "company": "TSMC"},
    {"slug": "tim-sweeney", "name": "Tim Sweeney", "company": "Epic Games"},
    {"slug": "sam-altman", "name": "Sam Altman", "company": "OpenAI"},
    {"slug": "jeff-bezos", "name": "Jeff Bezos", "company": "Amazon / Project Prometheus"},
    {"slug": "brian-chesky", "name": "Brian Chesky", "company": "Airbnb"},
    {"slug": "marc-benioff", "name": "Marc Benioff", "company": "Salesforce"},
    {"slug": "fei-fei-li", "name": "Fei-Fei Li", "company": "World Labs"},
    {"slug": "lip-bu-tan", "name": "Lip-Bu Tan", "company": "Intel"},
]
AL = {p["slug"]: wps.leader_aliases(p) for p in ROSTER}


def cls(slug: str, guess: str) -> str:
    return wps.classify(guess, *AL[slug])[0]


# ---------------------------------------------------------------------------
# 1. classify(): the traps.
print("classify")
check("Adam Dell is SURNAME_ONLY although Dell is the company",
      cls("michael-dell", "Adam Dell: founder and CEO of Domain Money") == "SURNAME_ONLY",
      cls("michael-dell", "Adam Dell: founder and CEO of Domain Money"))
check("John Roese of Dell Technologies is not a MATCH",
      cls("michael-dell", "John Roese, Global CTO and Chief AI Officer of Dell Technologies") != "MATCH")
check("Michael Dell, founder of Dell is a MATCH",
      cls("michael-dell", "Michael Dell, founder and CEO of Dell Technologies") == "MATCH")
check("Clément Delangue matches Clem Delangue",
      cls("clem-delangue", "Clément Delangue, co-founder of Hugging Face") == "MATCH")
check("Clément Delangue matches without the company too",
      cls("clem-delangue", "Clément Delangue") == "MATCH")
check("Wei Chen is SURNAME_ONLY under C.C. Wei",
      cls("cc-wei", "Wei Chen, Wilson Cook Professor of Engineering Design") == "SURNAME_ONLY")
check("Han-Wei Shen is not a MATCH under C.C. Wei",
      cls("cc-wei", "Han-Wei Shen, a scientific-visualization professor") != "MATCH")
check("C.C. Wei of TSMC is a MATCH",
      cls("cc-wei", "C.C. Wei, chairman and CEO of TSMC") == "MATCH")
check("initials do not match a bare letter",
      cls("cc-wei", "A Bay Area DJ performing as C") != "MATCH")
check("the DJ, not the Epic Games founder, is NAMESAKE",
      cls("tim-sweeney", "Tim Sweeney, the New York DJ and host of Beats In Space "
                         "(the DJ, not the Epic Games founder of the same name)") == "NAMESAKE")
check("Tim Sweeney of Epic Games is a MATCH",
      cls("tim-sweeney", "Tim Sweeney, CEO of Epic Games") == "MATCH")
check("a company-only guess is a MATCH",
      cls("sam-altman", "The chief executive of OpenAI") == "MATCH")
check("a stranger is OTHER",
      cls("sam-altman", "Vitalik Buterin") == "OTHER")
check("'unknown' is OTHER", cls("sam-altman", "unknown") == "OTHER")
check("empty guess is OTHER", cls("sam-altman", None) == "OTHER")
check("a guess that opens with another person is not a MATCH even if it names the leader",
      cls("brian-chesky", "Chip Conley is the actual interviewee; the supplied transcript ID names Brian Chesky.") != "MATCH")
check("a 'Speaker:' label before the other person is stripped",
      cls("brian-chesky", "Speaker: Chip Conley (former head of hospitality at Airbnb, reporting to Brian Chesky)") != "MATCH")
check("a three-token leader name is not read as a stranger",
      cls("fei-fei-li", "Dr. Fei-Fei Li (Professor of Computer Science, Stanford)") == "MATCH")
check("a hyphen-less spelling of a hyphenated name still matches",
      cls("lip-bu-tan", "Lip Bu Tan (presented as CEO of Intel)") == "MATCH")
check("a guess that opens with the leader and then names the guest is a MATCH",
      cls("marc-benioff", "Marc Benioff, CEO of Salesforce, hosting Sundar Pichai on stage") == "MATCH")
check("Jeff Bezos, discussed rather than speaking, is still a MATCH by name",
      cls("jeff-bezos", "Jeff Bezos, apparently the person discussed rather than a speaker") == "MATCH")


# ---------------------------------------------------------------------------
# 2. screen(): the recording-level rules.
def grade(slug: str, sid: str, judge: str, guess: str, share: int) -> dict:
    return {"leader_slug": slug, "source_id": sid, "judge": judge, "mode": "blinded",
            "validation_errors": [],
            "grade": {"identity_guess": guess, "identity_confident": True,
                      "subject_speech_share_pct": share, "attribution_notes": "",
                      "dimensions": {}}}


G = {
    ("michael-dell", "pursuit"): [grade("michael-dell", "pursuit", j, "Adam Dell", 80) for j in ("fable", "astra", "gemini")],
    ("jeff-bezos", "hosts"): [grade("jeff-bezos", "hosts", "gemini", "Rob Glenn", 42),
                              grade("jeff-bezos", "hosts", "fable", "Jeff Bezos, discussed not speaking", 0),
                              grade("jeff-bezos", "hosts", "astra", "Jeff Bezos", 0)],
    ("jeff-bezos", "biographer"): [grade("jeff-bezos", "biographer", "gemini", "Jeff Bezos", 68),
                                   grade("jeff-bezos", "biographer", "fable", "Jeff Bezos, discussed", 0),
                                   grade("jeff-bezos", "biographer", "astra", "Jeff Bezos", 73)],
    ("jeff-bezos", "absent"): [grade("jeff-bezos", "absent", j, "Jeff Bezos", 0) for j in ("fable", "astra", "gemini")],
    ("sam-altman", "clean"): [grade("sam-altman", "clean", j, "Sam Altman, CEO of OpenAI", 60) for j in ("fable", "astra", "gemini")],
    ("sam-altman", "lone"): [grade("sam-altman", "lone", "fable", "Sam Altman", 60),
                             grade("sam-altman", "lone", "astra", "Sam Altman", 60),
                             grade("sam-altman", "lone", "gemini", "Greg Brockman", 60)],
    ("tim-sweeney", "namesake"): [grade("tim-sweeney", "namesake", "fable", "Tim Sweeney, the DJ, not the Epic Games founder", 70),
                                  grade("tim-sweeney", "namesake", "astra", "Tim Sweeney", 70),
                                  grade("tim-sweeney", "namesake", "gemini", "Tim Sweeney (DJ)", 70)],
    ("tim-sweeney", "bare"): [grade("tim-sweeney", "bare", j, "Tim Sweeney", 70) for j in ("fable", "astra", "gemini")],
}
T = {("tim-sweeney", "bare"): {"leader_slug": "tim-sweeney", "source_id": "bare", "yt_title": "Beyond the Court: Tim Sweeney"},
     ("sam-altman", "clean"): {"leader_slug": "sam-altman", "source_id": "clean", "yt_title": "Sam Altman at OpenAI DevDay"}}
rows = {(r["leader_slug"], r["source_id"]): r for r in wps.screen(G, T, ROSTER, cutoff=10)}

print("screen")
check("three judges naming Adam Dell fires R1", rows[("michael-dell", "pursuit")]["R1_identity"])
check("two judges at share 0 fire R2 although a third scored the host at 42",
      rows[("jeff-bezos", "hosts")]["R2_absent"])
check("that recording is reported as on the board (mean 14 clears 10)",
      rows[("jeff-bezos", "hosts")]["on_board"])
check("one judge at 0 with the mean above the cutoff is R5, not a flag",
      rows[("jeff-bezos", "biographer")]["R5_dissent_zero"] and not rows[("jeff-bezos", "biographer")]["flagged"])
check("all judges at 0 fires R2 and is reported as already excluded",
      rows[("jeff-bezos", "absent")]["R2_absent"] and not rows[("jeff-bezos", "absent")]["on_board"])
check("a clean recording fires nothing",
      not any(rows[("sam-altman", "clean")][k] for k in
              ("flagged", "R3_namesake_review", "R5_dissent_zero", "R6_lone_dissent")))
check("one judge naming someone else is R6, not a flag",
      rows[("sam-altman", "lone")]["R6_lone_dissent"] and not rows[("sam-altman", "lone")]["flagged"])
check("a single NAMESAKE verdict fires R1", rows[("tim-sweeney", "namesake")]["R1_identity"])
check("bare name everywhere and no company in the title is R3",
      rows[("tim-sweeney", "bare")]["R3_namesake_review"])
check("every rule column is present on every row",
      all(k in r for r in rows.values() for k in
          ("R1_identity", "R2_absent", "R3_namesake_review", "R5_dissent_zero", "R6_lone_dissent", "flagged", "on_board")))


# ---------------------------------------------------------------------------
# 3. End to end: the script runs on a directory tree and writes verdicts.
print("cli")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    for (slug, sid), gs in G.items():
        for g in gs:
            p = td / "grades" / g["judge"] / slug / f"{sid}__{g['judge']}__blinded__r0.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(g))
    for (slug, sid), r in T.items():
        p = td / "transcripts_open" / slug / f"{sid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({**r, "text": "hello"}))
    (td / "roster.json").write_text(json.dumps({"roster": ROSTER}))
    out = td / "report.json"
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "wrong_person_screen.py"),
                           "--grades", str(td / "grades"), "--transcripts", str(td / "transcripts_open"),
                           "--roster", str(td / "roster.json"), "--out", str(out), "--sample", "0"],
                          capture_output=True, text=True)
    check("exit 0", proc.returncode == 0, proc.stderr[-500:])
    check("report names the flagged count", "FLAGGED (R1 identity or R2 absent): 4" in proc.stdout, proc.stdout[:300])
    verdicts = json.loads(out.read_text()) if out.exists() else []
    check("verdict JSON has one row per recording", len(verdicts) == len(G), str(len(verdicts)))
    check("verdict rows never carry transcript text", all("text" not in r for r in verdicts))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
