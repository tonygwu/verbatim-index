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
        nums = [int(x) for x in cells(total)[1:]]
        want = 6 + (3 + 1) + 3   # narrowing columns, GRADED per judge + ANY, CALLS
        check("SPLIT", len(nums) == want,
              f"TOTAL row has {len(nums)} numeric columns, expected {want}: "
              f"three judges need their own GRADED and CALLS columns")
        nums += [-1] * (want - len(nums))   # report every check, not just the first
        graded, pooled_any, calls = nums[6:9], nums[9], nums[10:13]
        check("SPLIT", graded == [1, 2, 1],
              f"per-judge GRADED should be fable 1, astra 2, nova 1; got {graded}")
        check("ANY", pooled_any == 3,
              f"ANY is the union of blinded-graded transcripts (ada t1, ada t2, "
              f"bob t5) = 3, not the sum 4; got {pooled_any}")
        check("ELIGIBLE", calls == [2, 3, 1],
              f"CALLS counts open and invalid grades too: fable 2, astra 3, "
              f"nova 1; got {calls}")

    m = re.search(r"blinded transcripts graded\s*:\s*(.+)", out)
    check("SPLIT", bool(m) and m.group(1).strip() == "fable 1, astra 2, nova 1",
          f"summary line wrong: {m.group(1).strip() if m else 'missing'!r}")

    m = re.search(r"graded by every judge\s*:\s*(\d+)/(\d+).*one-sided:\s*(.+?)\)", out)
    check("PARITY", bool(m), "no one-sided line")
    if m:
        check("PARITY", (m.group(1), m.group(2)) == ("0", "3"),
              f"no transcript has all three judges, out of 3; got {m.group(1)}/{m.group(2)}")
        check("PARITY", m.group(3).strip() == "fable 1, astra 2, nova 1",
              f"one-sided counts wrong: {m.group(3).strip()!r}")

    for f in fails:
        print(f"FAIL  {f}")
    print(f"\n{'FAILED' if fails else 'PASS'}  "
          f"{len(fails)} failure(s), script {SCRIPT}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
