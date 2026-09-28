#!/usr/bin/env python3
"""R7 in wrong_person_screen.py: one judge's subject share far from the others.

The shape this guards, seen on the published board on 2026-09-27: a fireside
chat where the leader is the HOST. Two judges graded the host and put his share
at 12 and 13. The third graded the guest, who does most of the talking, and put
the share at 89. The mean is 38, so the recording clears the 10% cutoff, and no
judge said 0, so the zero rules (R2, R5, and aggregate's any-zero drop) stay
silent. R6 caught it only because that judge also happened to NAME the guest in
its identity guess. A judge that names the leader and still scores the guest
passes every other rule, which is case [2] below.

Every fixture here is synthetic: invented names, invented notes, no transcript
text. Pure checks, no quota, no data directory.

  .venv/bin/python scripts/test_share_dissent.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("wps", REPO / "scripts" / "wrong_person_screen.py")
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


LEADER = {"slug": "pat-example", "name": "Pat Example", "company": "Examplecorp"}
ROSTER = [LEADER]
HOST = "Pat Example, CEO of Examplecorp, hosting the session"
GUEST = "Jordan Guest, a musician"


def grade(sid: str, judge: str, share: int | None, guess: str = HOST, notes: str = "") -> dict:
    return {"leader_slug": LEADER["slug"], "source_id": sid, "judge": judge, "mode": "blinded",
            "validation_errors": [],
            "grade": {"identity_guess": guess, "identity_confident": True,
                      "subject_speech_share_pct": share, "attribution_notes": notes,
                      "dimensions": {}}}


def rec(sid: str, shares: dict[str, int | None], guesses: dict[str, str] | None = None) -> list[dict]:
    guesses = guesses or {}
    return [grade(sid, j, s, guesses.get(j, HOST)) for j, s in shares.items()]


G = {
    # [1] the production shape: the dissenter graded the guest AND named him.
    "host-guest-named": rec("host-guest-named", {"gemini": 89, "fable": 12, "astra": 13},
                            {"gemini": GUEST}),
    # [2] the same shares, but every judge names the leader. Nothing about the
    # identity guess is wrong here, so only the share can catch it.
    "host-guest-silent": rec("host-guest-silent", {"gemini": 89, "fable": 12, "astra": 13}),
    # [3] the other direction: two judges graded the guest, the lone low judge
    # graded the host. The dissenter is the one that got it RIGHT, which is
    # why R7 is a review list and names a disagreement, not a culprit.
    "two-graded-guest": rec("two-graded-guest", {"gemini": 58, "fable": 32, "astra": 58}),
    # [4] four judges, one far out.
    "four-judges": rec("four-judges", {"gemini": 89, "fable": 12, "astra": 13, "delta": 15}),
    # ---- near misses: none of these may fire R7 ----
    "wide-spread": rec("wide-spread", {"gemini": 45, "fable": 38, "astra": 52}),
    "noise-tail": rec("noise-tail", {"gemini": 58, "fable": 76, "astra": 74}),
    "two-judges": rec("two-judges", {"gemini": 89, "fable": 12}),
    "below-cutoff": rec("below-cutoff", {"gemini": 26, "fable": 1, "astra": 2}),
    "three-way": rec("three-way", {"gemini": 80, "fable": 40, "astra": 10}),
    "lone-zero": rec("lone-zero", {"gemini": 86, "fable": 0, "astra": 78}),
    "two-zeros": rec("two-zeros", {"gemini": 70, "fable": 0, "astra": 0}),
    "one-missing": rec("one-missing", {"gemini": 89, "fable": 12, "astra": None}),
    "clean": rec("clean", {"gemini": 60, "fable": 62, "astra": 58}),
}
GRADES = {(LEADER["slug"], sid): gs for sid, gs in G.items()}
rows = {r["source_id"]: r for r in wps.screen(GRADES, {}, ROSTER, cutoff=10)}


def r7(sid: str) -> bool:
    return bool(rows[sid].get("R7_share_dissent"))


def who(sid: str):
    return (rows[sid].get("share_dissent") or {}).get("judge")


print("R7 share dissent\n")

print("[1] the host-vs-guest shape fires, and names the judge")
check("89/12/13 fires R7", r7("host-guest-named"), json.dumps(rows["host-guest-named"].get("share_dissent")))
check("the dissenter is gemini", who("host-guest-named") == "gemini", f"got {who('host-guest-named')!r}")
check("it is on the board (mean 38 clears 10)", rows["host-guest-named"]["on_board"])
check("R7 is a review list, not a flag", not rows["host-guest-named"]["flagged"])
check("R6 still fires on the named guest, as before",
      rows["host-guest-named"]["R6_lone_dissent"])

print("\n[2] the same shares with every guess naming the leader")
check("fires R7 although no identity rule can see it", r7("host-guest-silent"))
check("no other rule fires on it",
      not any(rows["host-guest-silent"][k] for k in
              ("flagged", "R1_identity", "R2_absent", "R5_dissent_zero", "R6_lone_dissent")),
      str({k: rows["host-guest-silent"][k] for k in ("R1_identity", "R2_absent", "R5_dissent_zero", "R6_lone_dissent")}))

print("\n[3] the dissenter may be the judge that got it right")
check("58/32/58 fires R7", r7("two-graded-guest"))
check("the low judge is named", who("two-graded-guest") == "fable", f"got {who('two-graded-guest')!r}")

print("\n[4] more than three judges")
check("89/12/13/15 fires R7 on gemini", r7("four-judges") and who("four-judges") == "gemini",
      f"R7={r7('four-judges')} who={who('four-judges')!r}")

print("\n[5] near misses do not fire")
for sid, why in [("wide-spread", "45/38/52 is ordinary disagreement"),
                 ("noise-tail", "58/76/74, the largest gap in the live corpus that is noise"),
                 ("two-judges", "two judges cannot say which one dissents"),
                 ("below-cutoff", "26/1/2 has mean 9.7 and is already off the board"),
                 ("three-way", "80/40/10 has no agreeing pair to dissent from"),
                 ("lone-zero", "a zero belongs to R5 and aggregate's any-zero drop"),
                 ("two-zeros", "two zeros belong to R2"),
                 ("one-missing", "one missing estimate leaves two judges"),
                 ("clean", "60/62/58")]:
    check(f"{sid}: {why}", not r7(sid), json.dumps(rows[sid].get("share_dissent")))

print("\n[6] the thresholds sit in the band the corpus left empty")
gap = getattr(wps, "SHARE_DISSENT_GAP", None)
agree = getattr(wps, "SHARE_DISSENT_AGREE", None)
# MEASURED 2026-09-27 (live corpus, 614 three-judge recordings) and on the
# pre-withdrawal snapshot of 2026-09-10 (643): the largest gap that was noise is
# 17.0, and the smallest gap on a recording later withdrawn is 26.0.
check("SHARE_DISSENT_GAP is above the noise ceiling 17 and at most 26",
      isinstance(gap, (int, float)) and 17 < gap <= 26, f"got {gap!r}")
# The closest pair of judges was never more than 10 apart in either corpus.
check("SHARE_DISSENT_AGREE admits every agreeing pair seen (max 10)",
      isinstance(agree, (int, float)) and agree >= 10, f"got {agree!r}")
# If both of two judges could be 'the dissenter', the verdict is arbitrary.
check("the agree window is tight enough that the dissenter is unique (1.5*agree < gap)",
      isinstance(gap, (int, float)) and isinstance(agree, (int, float)) and 1.5 * agree < gap,
      f"gap={gap!r} agree={agree!r}")

print("\n[7] the other rules keep their verdicts")
for sid, want in [("lone-zero", {"R5_dissent_zero": True, "flagged": False}),
                  ("two-zeros", {"R2_absent": True, "flagged": True}),
                  ("clean", {"flagged": False, "R6_lone_dissent": False, "R5_dissent_zero": False})]:
    got = {k: rows[sid][k] for k in want}
    check(f"{sid}: {want}", got == want, f"got {got}")

print("\n[8] the CLI prints an R7 section and writes the column")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    for (slug, sid), gs in GRADES.items():
        for g in gs:
            p = td / "grades" / g["judge"] / slug / f"{sid}__{g['judge']}__blinded__r0.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(g))
    (td / "transcripts_open").mkdir()
    (td / "roster.json").write_text(json.dumps({"roster": ROSTER}))
    out = td / "report.json"
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "wrong_person_screen.py"),
                           "--grades", str(td / "grades"), "--transcripts", str(td / "transcripts_open"),
                           "--roster", str(td / "roster.json"), "--out", str(out), "--sample", "0"],
                          capture_output=True, text=True)
    check("exit 0", proc.returncode == 0, proc.stderr[-400:])
    header = [ln for ln in proc.stdout.splitlines() if ln.startswith("==== REVIEW R7")]
    check("an R7 review section lists 4 recordings",
          len(header) == 1 and header[0].endswith(": 4 ===="), str(header))
    verdicts = json.loads(out.read_text()) if out.exists() else []
    check("every verdict row carries R7_share_dissent",
          bool(verdicts) and all("R7_share_dissent" in r for r in verdicts))

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
