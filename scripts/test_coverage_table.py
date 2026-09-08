#!/usr/bin/env python3
"""Tests for the per-judge columns in coverage_table.py.

The table pools work from judges that run on separate quota and progress at
very different rates. Before this test the table showed one GRADED and one
CALLS column, so a judge that had stalled for hours was invisible: the pooled
number kept climbing on the other judge's work and read as healthy progress.

What is asserted here:

  SPLIT       every judge present in data/grades gets its own GRADED and CALLS
              column, and the numbers are that judge's alone.
  ANY         the pooled GRADED column is the union over judges, not the sum.
  UNKNOWN     a judge not named in JUDGE_ORDER still gets a column instead of
              being dropped or folded into another judge's count.
  ELIGIBLE    only a blinded grade with no validation_errors counts as GRADED,
              while every grade file counts as a CALL.
  PARITY      the one-sided line names the transcripts that one judge has
              graded and another has not, which is the real backlog.
  PCT         FET% is FETCH/IDENT, 1J% is ANY/FETCH and NJ% is graded-by-every-
              judge over FETCH, each computed per leader and again on the
              fleet totals from summed counts rather than averaged ratios.
  PCT-EMPTY   a leader with nothing identified prints a dash, not 0%. Zero
              would read as a coverage failure instead of an absent
              measurement.
  PCT-ORPHAN  a grade whose transcript has left the corpus pushes 1J% above
              100, and the table says so by name instead of clamping. That is
              the orphaned-grade bug normalize_transcripts.py --grades fixes.

Run: .venv/bin/python scripts/test_coverage_table.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(os.environ.get("COVERAGE_TABLE_PY",
                             Path(__file__).resolve().parent / "coverage_table.py"))

ROSTER = [
    {"slug": "ada", "name": "Ada Lovelace", "company": "Analytical Engine"},
    {"slug": "bob", "name": "Bob Metcalfe", "company": "3Com"},
]

# (leader, source, judge, mode, validation_errors)
GRADES = [
    ("ada", "t1", "fable", "blinded", []),
    ("ada", "t1", "astra", "blinded", []),
    ("ada", "t2", "astra", "blinded", []),          # astra-only, the backlog
    ("ada", "t3", "astra", "open", []),             # a call, never a GRADED
    ("ada", "t4", "fable", "blinded", ["bad json"]),  # a call, never a GRADED
    ("bob", "t5", "nova", "blinded", []),           # judge outside JUDGE_ORDER
]

# Derived from the fixture above, so the expectations move with it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coverage_table import JUDGE_ORDER, SHADOW_JUDGES as SHADOW  # noqa: E402
GRADED_BY_JUDGE = {"fable": 1, "astra": 2, "nova": 1}   # blinded, validation-clean
CALLS_BY_JUDGE = {"fable": 2, "astra": 3, "nova": 1}    # every call, incl. open + invalid
EXPECTED_JUDGE_COLUMNS = list(JUDGE_ORDER) + sorted(
    {"fable", "astra", "nova"} - set(JUDGE_ORDER))

def build(root: Path) -> None:
    (root / "data/roster").mkdir(parents=True)
    (root / "data/roster/final.json").write_text(json.dumps({"roster": ROSTER}))
    for slug, src, judge, mode, errs in GRADES:
        d = root / "data/grades" / judge / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{src}__{judge}__{mode}__r0.json").write_text(json.dumps({
            "transcript_id": f"{slug}/{src}", "leader_slug": slug, "source_id": src,
            "judge": judge, "mode": mode, "validation_errors": errs,
        }))
    # A raw dump beside the grades must never be counted.
    raw = root / "data/grades/_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "junk.json").write_text(json.dumps({
        "transcript_id": "ada/t9", "leader_slug": "ada", "source_id": "t9",
        "judge": "fable", "mode": "blinded", "validation_errors": [],
    }))


def cells(line: str) -> list[str]:
    return line.split()


# --- shadow-judge scenario -------------------------------------------------
# A third independent fixture. A shadow judge is COLLECTED but not published,
# so it must get its own column while staying out of every figure that
# describes the published corpus.
SHADOW_GRADES = [
    ("ada", "t1", "fable"), ("ada", "t1", "astra"),
    ("ada", "t1", "gemini"),      # shadow: a column, but not published coverage
    ("ada", "t1", "nova"),        # published, and outside JUDGE_ORDER
]


def build_shadow(root: Path) -> None:
    (root / "data/roster").mkdir(parents=True)
    (root / "data/roster/final.json").write_text(json.dumps({"roster": [
        {"slug": "ada", "name": "Ada Lovelace", "company": "Analytical Engine"}]}))
    # Written in an order that is neither JUDGE_ORDER nor alphabetical, so a
    # passing column order can only come from JUDGE_ORDER.
    for _leader, src, judge in [SHADOW_GRADES[i] for i in (3, 2, 1, 0)]:
        d = root / "data/grades" / judge / "ada"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{src}__{judge}__blinded__r0.json").write_text(json.dumps({
            "transcript_id": f"ada/{src}", "leader_slug": "ada", "source_id": src,
            "judge": judge, "mode": "blinded", "validation_errors": []}))


def check_shadow(check) -> None:
    """A shadow judge gets a column and is kept out of the published figures.

    Both halves matter and they pull in opposite directions. Without the column
    the arm is invisible and a stalled backfill cannot be told from an absent
    one. Inside the published intersection, adding the arm would have reported
    "graded by every judge 0/491" on the day it was added, reading as a total
    loss of coverage when nothing about the published score had changed.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build_shadow(root)
        r = subprocess.run([sys.executable, str(SCRIPT)], cwd=root,
                           capture_output=True, text=True)
    if r.returncode != 0:
        check("SHADOW", False, f"coverage_table.py exited {r.returncode}: {r.stderr}")
        return
    out, lines = r.stdout, r.stdout.splitlines()
    header = next((l for l in lines if l.lstrip().startswith("#")), "")

    check("SHADOW", "GEMIN" in header,
          f"the shadow judge has no column, so a stalled backfill is invisible: {header!r}")
    # Order comes from JUDGE_ORDER, not from disk order or the alphabet.
    idx = [header.find(t) for t in ("FABLE", "ASTRA", "GEMIN", "NOVA")]
    check("SHADOW", all(a < b for a, b in zip(idx, idx[1:])) and -1 not in idx,
          f"columns must read FABLE ASTRA GEMIN NOVA; got offsets {idx} in {header!r}")

    # The published percentage counts 3 judges, not 4, and says so.
    check("SHADOW", "3J%" in header and "4J%" not in header,
          f"the coverage column must exclude the shadow judge: {header!r}")
    legend = next((l for l in lines if "FET% =" in l), "")
    check("SHADOW", "3J%" in legend and "4J%" not in legend,
          f"the legend must agree with the column it explains: {legend!r}")
    check("SHADOW", "gemini" in legend,
          f"the legend must name the judge it excluded: {legend!r}")

    m = re.search(r"graded by every published judge\s*:\s*(\d+)/(\d+).*one-sided:\s*(.+?)\)", out)
    check("SHADOW", bool(m), "no published-judge parity line")
    if m:
        check("SHADOW", "gemini" not in m.group(3),
              f"the shadow judge must not appear in published parity: {m.group(3)!r}")
    check("SHADOW", re.search(r"shadow judges\s*:\s*gemini 1/1", out) is not None,
          "the shadow line must report the arm's own backfill progress")



# --- percentage-column scenario -------------------------------------------
# A second, independent fixture. Folding these cases into GRADES above would
# have rewritten what the parity assertions mean.
PCT_ROSTER = [
    {"slug": "ada", "name": "Ada Lovelace", "company": "Analytical Engine"},
    {"slug": "bob", "name": "Bob Metcalfe", "company": "3Com"},
    {"slug": "cyd", "name": "Cyd Charisse", "company": "Nothing Yet"},
    {"slug": "dev", "name": "Dev Orphan", "company": "Withdrawn Corp"},
]
# leader -> how many candidates discovery identified
PCT_IDENT = {"ada": 4, "bob": 4, "cyd": 0, "dev": 2}
# leader -> transcripts actually on disk
PCT_FETCHED = {"ada": ["t1", "t2"], "bob": ["t5", "t6", "t7", "t8"],
               "cyd": [], "dev": ["t9"]}
# leader -> appearances FETCHED and then retired as re-uploads of another. The
# sweep leaves <id>.json.superseded behind. MEASURED 2026-09-07: Lip-Bu Tan
# read FETCH 7 of IDENT 14, which looked like half his material failing to
# download. All 14 downloaded; 7 were duplicates of the other 7. Dividing by
# IDENT reported 50% for a leader with a perfect fetch record.
PCT_RETIRED = {"ada": ["t3", "t4"], "bob": [], "cyd": [], "dev": []}
# (leader, source, judge) blinded grades, all valid
PCT_GRADES = [
    ("ada", "t1", "fable"), ("ada", "t1", "astra"),   # t1 has both judges
    ("ada", "t2", "astra"),                           # t2 is one-sided
    ("bob", "t5", "fable"), ("bob", "t5", "astra"),
    ("dev", "t9", "fable"), ("dev", "t9", "astra"),
    ("dev", "t10", "fable"), ("dev", "t10", "astra"),  # t10 was withdrawn
]
# leader -> (FET%, 1J%, NJ%) as the table should print them
PCT_WANT = {
    # ident 4, two retired as duplicates -> uniq 2, and both are fetched, so
    # this leader has a PERFECT fetch record and must read 100, not 50.
    "Ada Lovelace": ("100", "100", "50"),
    # everything fetched, but only t5 of four reached a judge
    "Bob Metcalfe": ("100", "25", "25"),
    # nothing identified and nothing fetched: not answerable, not zero
    "Cyd Charisse": ("-", "-", "-"),
    # 1 transcript on disk, 2 transcripts still carrying grades
    "Dev Orphan": ("50", "200", "200"),
    # totals from summed counts: uniq 8 of ident 10, so 7/8, 5/7, 4/7
    "TOTAL": ("88", "71", "57"),
}


def build_pct(root: Path) -> None:
    (root / "data/roster").mkdir(parents=True)
    (root / "data/roster/final.json").write_text(json.dumps({"roster": PCT_ROSTER}))
    src = root / "data/sources"
    src.mkdir(parents=True)
    (src / "all.jsonl").write_text("".join(
        json.dumps({"leader_slug": slug}) + "\n"
        for slug, n in PCT_IDENT.items() for _ in range(n)))
    for slug, ids in PCT_FETCHED.items():
        if not ids:
            continue
        d = root / "data/transcripts" / slug
        d.mkdir(parents=True)
        for sid in ids:
            (d / f"{sid}.json").write_text(json.dumps(
                {"fetch_method": "youtube_transcript_api"}))
    for slug, ids in PCT_RETIRED.items():
        if not ids:
            continue
        d = root / "data/transcripts" / slug
        d.mkdir(parents=True, exist_ok=True)
        for sid in ids:
            (d / f"{sid}.json.superseded").write_text("{}")
    for slug, sid, judge in PCT_GRADES:
        d = root / "data/grades" / judge / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}__{judge}__blinded__r0.json").write_text(json.dumps({
            "transcript_id": f"{slug}/{sid}", "leader_slug": slug, "source_id": sid,
            "judge": judge, "mode": "blinded", "validation_errors": [],
        }))


def check_pct(check) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build_pct(root)
        r = subprocess.run([sys.executable, str(SCRIPT)], cwd=root,
                           capture_output=True, text=True)
    if r.returncode != 0:
        check("PCT", False, f"coverage_table.py exited {r.returncode}: {r.stderr}")
        return
    lines = r.stdout.splitlines()

    header = next((l for l in lines if l.lstrip().startswith("#")), "")
    check("PCT", all(t in header for t in ("FET%", "1J%", "2J%")),
          f"header is missing a percentage column: {header!r}")
    check("UNIQ", "UNIQ" in header and "IDENT" in header,
          f"UNIQ must sit beside IDENT, not replace it: {header!r}")
    ada = next((l for l in lines if "  Ada Lovelace  " in l), "")
    # Take the trailing run of numeric cells rather than a fixed count.
    # It used to slice [-16:], spelled out as "7 narrowing + 3 graded + 2 calls
    # + 3 pct + 1 score", which silently encodes the NUMBER OF JUDGES twice.
    # Adding a third judge makes it 18 and every index below shifts, so the
    # guard failed on a table that was correct. Counting the block survives any
    # judge count; names and companies containing spaces still cannot reach it
    # because they are not numeric.
    def numeric_tail(row: str) -> list[str]:
        out = []
        for tok in reversed(row.split()):
            if re.fullmatch(r"-|\d+(?:\.\d+)?", tok):
                out.append(tok)
            else:
                break
        return list(reversed(out))
    tail = numeric_tail(ada)
    check("UNIQ", tail[0:3] == ["4", "2", "2"],
          f"Ada should read IDENT 4, UNIQ 2, FETCH 2; got {tail[0:3]}")
    check("UNIQ", "retired as" in r.stdout and "re-uploads" in r.stdout,
          "the footnote must say what UNIQ subtracts, or the column is unexplained")
    check("UNIQ", "FET% = FETCH/UNIQ" in r.stdout,
          "the footnote still claims FET% divides by IDENT")

    for name, want in PCT_WANT.items():
        is_total = name == "TOTAL"
        row = next((l for l in lines if f"  {name}  " in l
                    and (is_total or l.split()[:1] != ["TOTAL"])), None)
        if row is None:
            check("PCT", False, f"no row for {name}")
            continue
        # A leader row ends FET% 1J% NJ% SCORE; the TOTAL row leaves SCORE
        # blank, so split() drops it. Indexing from the right survives leader
        # names that contain spaces.
        got = tuple(cells(row)[-3:] if is_total else cells(row)[-4:-1])
        label = "PCT-EMPTY" if name.startswith("Cyd") else (
            "PCT-ORPHAN" if name.startswith("Dev") else "PCT")
        check(label, got == want,
              f"{name}: FET%/1J%/NJ% should be {want}, got {got}")

    over = next((l for l in lines if "OVER 100%" in l), None)
    check("PCT-ORPHAN", over is not None and "Dev Orphan" in over,
          "the table must name the leader whose grades outlive their "
          f"transcripts, not silently clamp: {over!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        r = subprocess.run([sys.executable, str(SCRIPT)], cwd=root,
                           capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL  coverage_table.py exited {r.returncode}\n{r.stderr}")
        return 1
    out = r.stdout
    lines = out.splitlines()

    fails: list[str] = []

    def check(label: str, cond: bool, detail: str) -> None:
        if not cond:
            fails.append(f"{label}: {detail}")

    header = next((l for l in lines if l.lstrip().startswith("#")), "")
    check("SPLIT", header.count("FABLE") == 2 and header.count("ASTRA") == 2,
          f"expected FABLE and ASTRA twice each (GRADED and CALLS), got {header!r}")
    check("UNKNOWN", header.count("NOVA") == 2,
          f"judge 'nova' is absent from the header, so its work is hidden: {header!r}")

    total = next((l for l in lines if l.split()[:1] == ["TOTAL"]), None)
    check("TOTAL", total is not None, "no TOTAL row")
    if total:
        # TOTAL <ident> <fetch> <yt> <hs> <gated> <rej> | f a n any | f a n
        # | FET% 1J% NJ%.  This fixture has no sources and no transcripts, so
        # the three percentages are dashes; they get their own scenario below.
        # Derive the expected shape from the judge set instead of hardcoding a
        # count. Every judge in JUDGE_ORDER gets a column whether or not the
        # fixture gave it grades, plus any judge the fixture invented. Writing
        # "three judges" as a literal made this guard fail the moment a third
        # arm was configured, on a table that was correct.
        cols = EXPECTED_JUDGE_COLUMNS
        nums = [int(x) for x in cells(total)[1:-3]]
        want = 7 + (len(cols) + 1) + len(cols)
        check("SPLIT", len(nums) == want,
              f"TOTAL row has {len(nums)} numeric columns, expected {want}: "
              f"{len(cols)} judges ({', '.join(cols)}) each need a GRADED and a CALLS column")
        nums += [-1] * (want - len(nums))   # report every check, not just the first
        n = len(cols)
        graded, pooled_any, calls = nums[7:7 + n], nums[7 + n], nums[8 + n:8 + 2 * n]
        graded_want = [GRADED_BY_JUDGE.get(j, 0) for j in cols]
        calls_want = [CALLS_BY_JUDGE.get(j, 0) for j in cols]
        check("SPLIT", graded == graded_want,
              f"per-judge GRADED should be "
              f"{', '.join(f'{j} {v}' for j, v in zip(cols, graded_want))}; got {graded}")
        check("ANY", pooled_any == 3,
              f"ANY is the union of blinded-graded transcripts (ada t1, ada t2, "
              f"bob t5) = 3, not the sum 4; got {pooled_any}")
        check("ELIGIBLE", calls == calls_want,
              f"CALLS counts open and invalid grades too: "
              f"{', '.join(f'{j} {v}' for j, v in zip(cols, calls_want))}; got {calls}")

    want_summary = ", ".join(f"{j} {GRADED_BY_JUDGE.get(j, 0)}"
                             for j in EXPECTED_JUDGE_COLUMNS)
    m = re.search(r"blinded transcripts graded\s*:\s*(.+)", out)
    check("SPLIT", bool(m) and m.group(1).strip() == want_summary,
          f"summary line wrong: got {m.group(1).strip() if m else 'missing'!r}, "
          f"want {want_summary!r}")

    # The label gains "published" once a shadow arm exists, because the
    # intersection then covers only the judges that reach the leaderboard.
    # Accept either wording: which one appears is a function of configuration,
    # not of the behaviour under test.
    m = re.search(r"graded by every (?:published )?judge\s*:\s*(\d+)/(\d+)"
                  r".*one-sided:\s*(.+?)\)", out)
    check("PARITY", bool(m), "no one-sided line")
    if m:
        check("PARITY", (m.group(1), m.group(2)) == ("0", "3"),
              f"no transcript has all three judges, out of 3; got {m.group(1)}/{m.group(2)}")
        # The one-sided tally covers PUBLISHED judges only. A shadow arm at
        # zero must not appear here, or adding one reads as every transcript
        # having gone one-sided overnight.
        want_sided = ", ".join(f"{j} {GRADED_BY_JUDGE.get(j, 0)}"
                               for j in EXPECTED_JUDGE_COLUMNS if j not in SHADOW)
        check("PARITY", m.group(3).strip() == want_sided,
              f"one-sided counts wrong: got {m.group(3).strip()!r}, want {want_sided!r}")

    check_pct(check)
    check_shadow(check)

    for f in fails:
        print(f"FAIL  {f}")
    print(f"\n{'FAILED' if fails else 'PASS'}  "
          f"{len(fails)} failure(s), script {SCRIPT}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
