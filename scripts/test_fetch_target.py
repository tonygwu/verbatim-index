#!/usr/bin/env python3
"""The fetch target counts GRADEABLE transcripts, not raw fetches.

FOUND 2026-09-09. `coverage()` counted data/transcripts, so a leader whose
fetches were rejected by QA still read as "at target". The loop then printed
COMPLETE and exited with 14 of 40 leaders short: Michael Dell had 16 raw files,
9 survived QA, and the target was 14. He is scored on the thinnest evidence on
the board as a direct result, and nothing in the pipeline said so.

Pure checks: no network, no quota.

  .venv/bin/python scripts/test_fetch_target.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOOP = (REPO / "scripts" / "fetch_loop.sh").read_text()
FETCH = (REPO / "scripts" / "fetch_transcripts.py").read_text()

PASS, FAIL = [], []
def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def test_loop_counts_gradeable():
    print("\n[1] the loop measures the target against gradeable transcripts")
    check("coverage() reads data/transcripts_blind",
          'blind = Path("data/transcripts_blind")' in LOOP,
          "it still counts raw fetches, so QA rejections are invisible to the target")
    check("coverage() still reports the raw count too",
          '"raw_transcripts"' in LOOP,
          "raw vs gradeable is the whole diagnosis; keep both visible")
    check("the fetcher is told the same basis",
          "--have-dir data/transcripts_blind" in LOOP,
          "without this the fetcher skips the leaders the loop still wants topped up")
    check("--have-dir exists in fetch_transcripts.py",
          '"--have-dir"' in FETCH)
    check("_have() honours it and ignores .tmp files",
          "have_dir = Path(args.have_dir) if args.have_dir else out_dir" in FETCH
          and 'not f.name.endswith(".tmp")' in FETCH)


def test_exhaustion_guard():
    print("\n[2] a leader whose candidates run out cannot hang the loop")
    check("a barren-pass counter exists",
          "barren=$(( barren + 1 ))" in LOOP,
          "counting gradeable means 'not at target' no longer proves work remains")
    # Locate both, rather than indexing blind: against the pre-fix script the
    # marker is absent and .index() raises, which reports as a crashed test
    # rather than a failed one. A guard that cannot fail cleanly cannot be
    # trusted to have been checked against the bug it describes.
    init = LOOP.find("\nbarren=0\n")
    loop_start = LOOP.find("while true")
    check("it is initialised OUTSIDE the while loop",
          init != -1 and loop_start != -1 and init < loop_start,
          f"barren=0 at {init}, while-loop at {loop_start}; "
          "initialising it inside the loop resets it every cycle and never fires")
    check("it resets after a productive pass",
          LOOP.count("barren=0") >= 2)
    check("the loop exits rather than spinning at MAX_SLEEP",
          "EXHAUSTED:" in LOOP and "BARREN_LIMIT" in LOOP)
    check("the exit names who is short of target",
          "Short of target:" in LOOP,
          "a shortfall that is not named is a shortfall nobody fixes")


def test_gradeable_basis_changes_the_verdict():
    """On a fixture where QA rejects half, the two bases must disagree."""
    print("\n[3] the two bases genuinely differ (the bug reproduces)")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        raw = root / "data/transcripts/dell"; raw.mkdir(parents=True)
        blind = root / "data/transcripts_blind/dell"; blind.mkdir(parents=True)
        for i in range(16):                      # 16 fetched
            (raw / f"t{i}.json").write_text("{}")
        for i in range(9):                       # 9 survive QA
            (blind / f"t{i}.json").write_text("{}")
        (blind / "partial.json.tmp").write_text("{}")   # must not be counted
        n_raw = len(list(raw.glob("*.json")))
        n_grade = len([f for f in blind.glob("*.json") if not f.name.endswith(".tmp")])
    check("raw count reaches a target of 14", n_raw >= 14, f"raw={n_raw}")
    check("gradeable count does NOT", n_grade < 14, f"gradeable={n_grade}")
    check("the .tmp file is excluded", n_grade == 9, f"got {n_grade}, expected 9")


def main() -> int:
    print("fetch target guards")
    test_loop_counts_gradeable()
    test_exhaustion_guard()
    test_gradeable_basis_changes_the_verdict()
    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
