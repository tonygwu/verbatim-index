#!/usr/bin/env python3
"""Blinding is measured by whether a judge NAMED the speaker, not whether it felt sure.

FOUND 2026-10-12. aggregate.py's blinding_leakage_rate counts a blinded recording
as recognised when any judge set identity_confident, which is the judge's own
claim. The pundits page then said the judges "identified" the speaker on that
share of recordings. A confident wrong guess is not an identification.
aggregate.blinding_correct_rate (contract-v2 studies) counts a blinded recording
only when a judge was confident AND its guess names the subject.

  NAMES     names_subject() accepts the full name, a surname of 4+ letters or a
            roster handle, case-insensitive and on word boundaries; it rejects
            another person's name and a longer word that merely contains the surname
  RATE      on a corpus where one person's guesses are right and another's are
            confidently wrong, the correct rate counts only the first, while the
            leakage rate counts both
  LEADERS   the key is written only for a contract-v2 study

No quota, no data.

  .venv/bin/python scripts/test_blinding_correct_rate.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def enclosing_line(src: str, needle: str) -> str:
    """The statement that opens the block holding the first line with `needle`."""
    lines = src.splitlines()
    i = next((k for k, ln in enumerate(lines) if needle in ln), None)
    if i is None:
        return ""
    depth = len(lines[i]) - len(lines[i].lstrip())
    for ln in reversed(lines[:i]):
        if ln.strip() and len(ln) - len(ln.lstrip()) < depth:
            return ln.strip()
    return ""


def main() -> int:
    print("blinding: correct identification")
    import aggregate as A
    fn = getattr(A, "names_subject", None)

    print("\n[NAMES]")
    if fn is None:
        check("aggregate.names_subject exists", False)
    else:
        walsh = {"name": "Matt Walsh", "handles": []}
        bonnell = {"name": "Steven Bonnell", "handles": ["Destiny", "TheOmniLiberal"]}
        hoyt = {"name": "Zack Hoyt", "handles": ["Asmongold"]}
        check("the full name counts", fn("Matt Walsh", walsh))
        check("a surname of 4+ letters counts, in any case", fn("walsh", walsh))
        check("a handle counts", fn("Asmongold", hoyt) and fn("Steven Bonnell II (Destiny)", bonnell))
        check("another person's name does not", not fn("Tim Walz", walsh))
        check("a longer word containing the surname does not", not fn("Walshire", walsh))
        check("an empty or missing guess does not", not fn("", walsh) and not fn(None, walsh))
        # FOUND 2026-10-12 by review: a bare surname token matched another person who
        # shares it. Mehdi Hasan and Hasan Piker are both on the roster, and the
        # hyphen in Bet-David made "David" a surname.
        mehdi = {"name": "Mehdi Hasan", "handles": []}
        bret = {"name": "Bret Weinstein", "handles": []}
        pbd = {"name": "Patrick Bet-David", "handles": []}
        megyn = {"name": "Megyn Kelly", "handles": []}
        piker = {"name": "Hasan Piker", "handles": ["HasanAbi"]}
        roster = [mehdi, piker, walsh, bonnell, hoyt]
        check("another roster person whose FIRST name is the surname does not: Hasan Piker is not Mehdi Hasan",
              not fn("Hasan Piker", mehdi, roster) and not fn("Hasan Piker (HasanAbi)", mehdi, roster))
        # FOUND 2026-10-12 by the second review: the first fix rejected ANY capitalised
        # neighbour, so real namings and search queries stopped counting.
        shapiro = {"name": "Ben Shapiro", "handles": []}
        check("a surname followed by other capitalised words still counts (a search query)",
              fn("Shapiro Daily Wire", shapiro, roster) and fn("Weinstein Bret", bret, roster))
        check("a hedge or a possessive before the surname still counts",
              fn("Likely Walsh", walsh, roster) and fn("Daily Wire's Walsh", walsh, roster)
              and fn("Possibly Weinstein, the biologist", bret, roster))
        check("another person with the same surname does not: Eric Weinstein, Jesse Kelly",
              not fn("Eric Weinstein", bret) and not fn("Jesse Kelly", megyn))
        check("a hyphenated surname is one word: Larry David and David Pakman are not Patrick Bet-David",
              not fn("Larry David", pbd) and not fn("David Pakman", pbd))
        check("and still counts whole", fn("Bet-David", pbd) and fn("Patrick Bet-David (PBD Podcast)", pbd))
        check("a bare surname, a titled one or an initial still counts",
              fn("Weinstein", bret) and fn("Dr. Weinstein", bret) and fn("B. Weinstein", bret)
              and fn("probably Walsh", walsh))
        check("a longer form of the first name still counts, and a suffix after the surname is fine",
              fn("Matthew Walsh", walsh) and fn("Weinstein Jr.", bret))
        check("every guess form seen on the pilot still counts",
              fn("Destiny (Steven Bonnell)", bonnell) and fn("Asmongold (Zack)", hoyt)
              and fn("Sam Seder, host of The Majority Report", {"name": "Sam Seder", "handles": []}))

    print("\n[RATE]")
    tps = load("tps_bcr", REPO / "scripts" / "test_profile_scoring.py")
    with tempfile.TemporaryDirectory(prefix="bcr-") as td:
        root, profiles = tps.fixture_corpus(Path(td).resolve())
        # p0: every judge confidently names Pundit 0. p1: every judge confidently
        # names someone else. p2: no judge is confident.
        for f in (root / "grades").rglob("*.json"):
            rec = json.loads(f.read_text())
            if rec["leader_slug"] == "p0":
                rec["grade"].update(identity_guess="Pundit 0", identity_confident=True)
            elif rec["leader_slug"] == "p1":
                rec["grade"].update(identity_guess="Somebody Else", identity_confident=True)
            f.write_text(json.dumps(rec))
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        env["VI_PROFILES_DIR"] = str(profiles)
        r = subprocess.run([PY, REPO / "scripts" / "aggregate.py", "--study", "pundits",
                            "--grades", root / "grades", "--roster", root / "roster" / "final.json",
                            "--out", root / "out.json"], env=env, capture_output=True, text=True)
        check("the fixture corpus aggregates", r.returncode == 0, r.stderr[-400:])
        res = json.loads((root / "out.json").read_text()) if (root / "out.json").exists() else {}
        d = res.get("diagnostics") or {}
        rows = [t for t in res.get("transcripts", []) if t["mode"] == "blinded"]
        n0 = sum(1 for t in rows if t["leader_slug"] == "p0")
        n1 = sum(1 for t in rows if t["leader_slug"] == "p1")
        check("the leakage rate counts both confident people",
              d.get("blinding_leakage_rate") == round((n0 + n1) / len(rows), 3), str(d.get("blinding_leakage_rate")))
        check("results.json binds itself to the exact grade bytes it read (grade_files_sha256)",
              d.get("grade_files_sha256") == A.grade_files_digest(A.load_grades(root / "grades"))
              and len(d.get("grade_files_sha256") or "") == 64, str(d.get("grade_files_sha256")))
        check("the correct rate counts only the person named correctly",
              d.get("blinding_correct_rate") == round(n0 / len(rows), 3),
              f"{d.get('blinding_correct_rate')} vs {round(n0 / len(rows), 3)}")

    print("\n[LEADERS]")
    opener = enclosing_line((REPO / "scripts" / "aggregate.py").read_text(), 'diagnostics["blinding_correct_rate"]')
    check("the key is written only under is_v2", opener == "if is_v2:", opener)
    opener = enclosing_line((REPO / "scripts" / "aggregate.py").read_text(), 'diagnostics["grade_files_sha256"]')
    check("and so is grade_files_sha256", opener == "if is_v2:", opener)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
