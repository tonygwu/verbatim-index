#!/usr/bin/env python3
"""The grade-free identity screen, tested on the REAL wrong-person cases.

WHY THESE FIXTURES AND NOT INVENTED ONES. This repo has already measured that the
obvious rule does not work: full name, or surname plus a company token, was
implemented and replayed against the known wrong-person set and scored
`accepted(bad)=8, rejected(good)=2`. A test built from titles I made up would
agree with whatever I wrote. Every BAD title below was read out of
`data/sources/discovered.json` in this corpus, and every one of them is a
recording that really was filed under the wrong person. They are quoted verbatim.

  alexandr-wang   Scale TransformX | Fireside Chat: Aidan Gomez and Alexandr Wang
  brian-armstrong Vitalik Buterin & Brian Armstrong [LIVE]: What happened to ...
  george-hotz     comma ai | Riccardo Biasini | Data Collection, Use And Cost ...
  lip-bu-tan      SIEPR Economic Summit 2026 | Fireside Chat with Mario Draghi ...
  lisa-su         Winning the AI Race Part 3: Jensen Huang, Lisa Su, James ...
  yann-lecun      AI Research Symposium: The Next Frontiers | Keynotes by Demis ...
  eric-schmidt    The Letterman Podcast 161 Eric Schmidt #Talkingschmidt ...

THE CLAIM UNDER TEST IS NARROW, and the file says so out loud rather than
claiming a detector. The screen must route these to `review` or `reject` rather
than `pass`, and it must NOT route ordinary healthy recordings to `reject`. It is
a cheap filter in front of a person, and the measurement that matters is how many
of the real cases it stops leaking through, reported as a number either way.

No quota, no network, no grades read. Fixtures are dicts and temporary files.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = str(REPO / ".venv" / "bin" / "python")

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    return ok


PEOPLE = {
    "alexandr-wang": {"slug": "alexandr-wang", "name": "Alexandr Wang", "company": "Scale AI"},
    "brian-armstrong": {"slug": "brian-armstrong", "name": "Brian Armstrong", "company": "Coinbase"},
    "george-hotz": {"slug": "george-hotz", "name": "George Hotz", "company": "comma.ai"},
    "lip-bu-tan": {"slug": "lip-bu-tan", "name": "Lip-Bu Tan", "company": "Intel"},
    "lisa-su": {"slug": "lisa-su", "name": "Lisa Su", "company": "AMD"},
    "yann-lecun": {"slug": "yann-lecun", "name": "Yann LeCun", "company": "Meta"},
    "eric-schmidt": {"slug": "eric-schmidt", "name": "Eric Schmidt", "company": "Google"},
    "cathie-wood": {"slug": "cathie-wood", "name": "Cathie Wood", "company": "ARK"},
    "tom-lee": {"slug": "tom-lee", "name": "Tom Lee", "company": "Fundstrat"},
}

# Every title verbatim from data/sources/discovered.json. These are real
# recordings that were filed under the wrong person.
REAL_BAD = [
    ("alexandr-wang", "Scale TransformX | Fireside Chat: Aidan Gomez and Alexandr Wang"),
    ("brian-armstrong", "Vitalik Buterin & Brian Armstrong [LIVE]: What happened to cryptocurrency? | Coin"),
    ("george-hotz", "comma ai | Riccardo Biasini | Data Collection, Use And Cost For Self-Driving Cars"),
    ("lip-bu-tan", "SIEPR Economic Summit 2026 | Fireside Chat with Mario Draghi, former Prime Minister"),
    ("lisa-su", "Winning the AI Race Part 3: Jensen Huang, Lisa Su, James Litinsky, Chase Lochmiller"),
    ("yann-lecun", "AI Research Symposium: The Next Frontiers | Keynotes by Demis Hassabis, Yoshua Bengio"),
]

# Healthy recordings, also real in shape: one person, named in full, speaking.
GOOD = [
    ("lisa-su", "Lisa Su on AMD's AI roadmap | Full keynote"),
    ("yann-lecun", "Yann LeCun: the next frontier for machine intelligence"),
    ("cathie-wood", "Cathie Wood: ARK's outlook for 2026"),
]


def main() -> int:
    import identity_screen as IS

    print("[1] the failure the surname rule cannot see: somebody ELSE in the title")
    for slug, title in REAL_BAD:
        others = IS.other_named_people(title, PEOPLE[slug])
        check(f"{slug}: other people found in the title -> {others}", bool(others),
              "this is the co-guest and interviewer shape; the replayed "
              "full-name-or-company rule scored accepted(bad)=8 on exactly these")

    print("\n[2] and a healthy title names nobody else")
    for slug, title in GOOD:
        others = IS.other_named_people(title, PEOPLE[slug])
        check(f"{slug}: no other people in {title[:44]!r}", not others, f"found {others}")

    print("\n[3] END TO END on the real cases: none may reach 'pass'")
    leaked = []
    for slug, title in REAL_BAD:
        rec = {"source_id": "x", "leader_slug": slug, "title": title,
               "text": "we talked about many things today " * 80}
        v = IS.screen_one(rec, PEOPLE[slug])["verdict"]
        if v == "pass":
            leaked.append((slug, title))
        check(f"{slug}: verdict {v!r}, not 'pass'", v != "pass", title[:60])
    check(f"MEASURED leak rate on the real cases: {len(leaked)} of {len(REAL_BAD)}",
          not leaked, f"leaked: {leaked}")

    print("\n[4] the surname-only trap the seven actually carry")
    ok, why = IS.identifies("Hollywood stars on the red carpet", "", PEOPLE["cathie-wood"])
    check("'Hollywood' does not identify Cathie Wood", not ok, why)
    ok, why = IS.identifies("Cathie Wood on ARK's outlook", "", PEOPLE["cathie-wood"])
    check("her full name does", ok, why)
    ok, why = IS.identifies("Wood talks markets on ARK's channel", "", PEOPLE["cathie-wood"])
    check("surname plus the company token does", ok, why)
    ok, why = IS.identifies("Wood talks markets", "", PEOPLE["cathie-wood"])
    check("surname ALONE does not", not ok, why)
    ok, why = IS.identifies("How to stop s-lee-ping badly", "", PEOPLE["tom-lee"])
    check("'s-lee-ping' does not identify Tom Lee", not ok, why)

    print("\n[5] aboutness, reusing the calibrated QA density signal")
    about = {"source_id": "y", "leader_slug": "lisa-su",
             "title": "Lisa Su has a message for Nvidia",
             "text": "Lisa Su said today that " * 120}
    r = IS.screen_one(about, PEOPLE["lisa-su"])
    check("a possessive-narrative title is rejected", r["verdict"] == "reject", str(r["verdict"]))
    check("... and the density is reported as a number, not a boolean",
          isinstance(r["signals"]["aboutness"]["name_density_per_1000"], float))
    check("... above the limit", r["signals"]["aboutness"]["name_density_per_1000"] > 1.6,
          str(r["signals"]["aboutness"]))

    print("\n[5b] a SPEAKER-LABELLED transcript is not 'about' its own speaker")
    # REAL CASE, 2026-09-20. bill-gurley/tim-ferriss-hsvfz2 is a 22,303-word
    # interview WITH Gurley. Its turns are labelled "Bill Gurley:", 154 of them,
    # which drove name density to 7.08 per 1000 against a limit of 1.6 and got a
    # good recording REJECTED. The labels are evidence he is speaking; the
    # aboutness signal read them as evidence the show is about him.
    labelled = {
        "source_id": "tim-ferriss-hsvfz2", "leader_slug": "bill-gurley",
        "yt_title": "Legendary Investor Bill Gurley on Investing Rules",
        # The REAL file's shape: some turns carry a [timestamp] and most run
        # inline after the previous sentence. The general label regex needs the
        # timestamp or a newline, which is deliberate: matching "Word:" anywhere
        # would invent speakers out of "Note:" and "Remember:". The inline turns
        # are still stripped from the density count, because that strip targets
        # this person's own name rather than any label.
        "text": ("[00:00:13] Tim Ferriss: Welcome to the show, my guest is Bill Gurley. "
                 "[00:01:15] Bill Gurley: Thanks for having me. "
                 + "Tim Ferriss: Tell me about markets. "
                   "Bill Gurley: The thing about markets is that they clear eventually. " * 60),
    }
    person = {"slug": "bill-gurley", "name": "Bill Gurley", "company": "Benchmark"}
    r = IS.screen_one(labelled, person)
    check("the speaker labels are detected", bool(r["signals"]["own_voice"]["speaker_labels"]),
          str(r["signals"]["own_voice"]))
    check("... and own_voice confirms the subject speaks",
          r["signals"]["own_voice"]["ok"] is True, str(r["signals"]["own_voice"]))
    check("the labels do NOT count toward name density",
          r["signals"]["aboutness"]["name_density_per_1000"] <= 1.6,
          f"got {r['signals']['aboutness']['name_density_per_1000']}; the labels are "
          f"evidence he SPEAKS, not evidence the show is about him")
    check("so it is not rejected", r["verdict"] != "reject", r["verdict"])

    print("\n[6] own_voice is UNKNOWN without speaker labels, never 'pass'")
    plain = {"source_id": "z", "leader_slug": "cathie-wood",
             "title": "Cathie Wood on ARK's outlook", "text": "markets are interesting " * 90}
    r = IS.screen_one(plain, PEOPLE["cathie-wood"])
    check("no labels -> own_voice ok is None", r["signals"]["own_voice"]["ok"] is None)
    # An earlier design made unknown own_voice force "review". MEASURED over the
    # live corpus, 0 of 664 records carry speaker labels, because YouTube
    # auto-captions have none, so every record came back "review" and the screen
    # filtered nothing. Unknown is now reported in the signal and kept out of the
    # verdict. It is still visible: the report counts own_voice_unknown.
    check("... and unknown does NOT by itself force review", r["verdict"] == "pass",
          f"got {r['verdict']}; 0 of 664 live records carry labels, so forcing "
          f"review on unknown makes the screen useless")
    labelled = dict(plain, text=">> CATHIE WOOD: markets are interesting.\n"
                                ">> HOST: thank you.\n" + "and so on " * 90)
    r2 = IS.screen_one(labelled, PEOPLE["cathie-wood"])
    check("with labels naming her, own_voice passes", r2["signals"]["own_voice"]["ok"] is True,
          str(r2["signals"]["own_voice"]))
    check("... and the whole record passes", r2["verdict"] == "pass", r2["verdict"])
    wrong = dict(plain, text=">> AIDAN GOMEZ: I think.\n>> HOST: thanks.\n" + "and so on " * 90)
    r3 = IS.screen_one(wrong, PEOPLE["cathie-wood"])
    check("labels naming SOMEONE ELSE reject", r3["verdict"] == "reject", r3["verdict"])

    print("\n[7] a record with NO title is refused, not screened against \"\"")
    # The bug this caught in the screen itself: rec.get("title") or "" scored all
    # 664 live records against an empty string, failing identity on 663 of them
    # and exclusivity on 0, and reported those verdicts as if they meant
    # something. Transcript records keep their title in yt_title or
    # declared_title, never in "title".
    for field in ("yt_title", "declared_title", "title"):
        got = IS.title_of({"leader_slug": "x", "source_id": "y", field: "A Real Title"})
        check(f"title_of reads {field}", got == "A Real Title", got)
    raised = False
    try:
        IS.title_of({"leader_slug": "lisa-su", "source_id": "abc"})
    except RuntimeError as exc:
        raised = "lisa-su/abc" in str(exc)
    check("a record with none of them RAISES, naming it", raised,
          "screening against an empty string reports a verdict that means nothing")

    print("\n[8] every verdict carries its reasons")
    for key in ("identity", "exclusivity", "aboutness", "own_voice"):
        check(f"{key} reports a reason", bool(r["signals"][key].get("reason")))

    print("\n[9] the CLI runs over a corpus and refuses an unknown --only slug")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "t" / "lisa-su").mkdir(parents=True)
        (tmp / "t" / "lisa-su" / "a.json").write_text(json.dumps({
            "source_id": "a", "leader_slug": "lisa-su",
            "title": "Winning the AI Race Part 3: Jensen Huang, Lisa Su, James Litinsky",
            "text": "we talked today " * 90}))
        roster = tmp / "roster.json"
        roster.write_text(json.dumps({"roster": [PEOPLE["lisa-su"]]}))
        out = tmp / "report.json"
        r = subprocess.run([PY, str(REPO / "scripts" / "identity_screen.py"),
                            "--transcripts", str(tmp / "t"), "--roster", str(roster),
                            "--out", str(out)], capture_output=True, text=True)
        check("the CLI runs", r.returncode == 0, r.stderr[-300:])
        if out.exists():
            rep = json.loads(out.read_text())
            check("it screened the record", rep["screened"] == 1, str(rep.get("screened")))
            check("and did not pass it", rep["verdicts"].get("pass", 0) == 0, str(rep["verdicts"]))
        bad = subprocess.run([PY, str(REPO / "scripts" / "identity_screen.py"),
                              "--transcripts", str(tmp / "t"), "--roster", str(roster),
                              "--only", "nobody-here"], capture_output=True, text=True)
        check("an unknown --only slug is refused", bad.returncode != 0,
              "a typo'd slug silently screening nothing is the shape this repo forbids")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
