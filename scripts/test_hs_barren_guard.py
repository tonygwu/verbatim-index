#!/usr/bin/env python3
"""happyscribe_loop stops when it stops making progress, like its sibling does.

WHY THIS EXISTS. happyscribe_loop.sh exits on exactly one condition:

    if [ "${hs:-0}" -ge "${cand:-0}" ]; then
      say "COMPLETE: every discovered candidate has been fetched"

That is a count of fetched files against a count of candidates, so it assumes
every candidate is eventually fetchable. MEASURED 2026-09-11: 59 of 92
candidates were fetched and the remaining 33 kept failing, so the condition
could never be met and the loop would sleep and retry them every 30 minutes
forever.

fetch_loop.sh already solved this with BARREN_LIMIT: three consecutive passes
with no new transcripts and it exits EXHAUSTED, naming who is still short.
happyscribe_loop.sh is its sibling, added later, and never got the guard.

This became load-bearing on 2026-09-11. grade_loop.sh was fixed the same day to
wait for EVERY transcript source rather than only fetch_loop, which is correct.
But a source that never exits means a grader that never exits either, so the
missing guard here turned into two loops spinning indefinitely over a corpus
neither could change.

What is asserted here:

  COUNTER   the loop counts consecutive cycles that added no transcripts, and
            resets that count when a cycle adds one.
  EXITS     it stops after a named limit rather than sleeping forever.
  NAMES     the exit says what is still unfetched, so "it stopped" and "it
            finished" are distinguishable. fetch_loop names the short leaders;
            an exit that only says EXHAUSTED is not actionable.
  TUNABLE   the limit is an env-overridable variable, matching fetch_loop, so a
            long-running fetch can raise it without editing the script.
  KEEPS_COMPLETE the existing all-candidates-fetched exit still exists. The new
            guard is a second way to stop, not a replacement for finishing.

  .venv/bin/python scripts/test_hs_barren_guard.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


LOOP = (REPO / "scripts" / "happyscribe_loop.sh").read_text()
SIB = (REPO / "scripts" / "fetch_loop.sh").read_text()


def main() -> int:
    print("happyscribe barren guard")

    check("happyscribe_loop.sh is valid bash",
          subprocess.run(["bash", "-n", str(REPO / "scripts" / "happyscribe_loop.sh")],
                         capture_output=True).returncode == 0)

    check("a barren-pass limit is declared and env-overridable",
          re.search(r'^BARREN_LIMIT="\$\{BARREN_LIMIT:-\d+\}"', LOOP, re.M) is not None,
          "no BARREN_LIMIT; the loop can only stop by fetching every candidate")
    check("the counter is initialised",
          re.search(r"^barren=0", LOOP, re.M) is not None)
    check("a productive cycle resets the counter",
          re.search(r"barren=0", LOOP[LOOP.find("corpus \\${before}"):] or LOOP) is not None
          or LOOP.count("barren=0") >= 2,
          "the counter only ever climbs, so one barren cycle eventually exits")
    check("a barren cycle increments it",
          re.search(r"barren=\$\(\(\s*barren \+ 1\s*\)\)", LOOP) is not None)
    check("it exits once the limit is reached",
          re.search(r'\[ "\$barren" -ge "\$BARREN_LIMIT" \]', LOOP) is not None,
          "the counter exists but nothing acts on it")

    m = re.search(r'say "EXHAUSTED[^"]*"', LOOP)
    check("the exhausted exit names what is still unfetched",
          m is not None and ("${unfetched}" in m.group(0) or "$unfetched" in m.group(0)
                             or "${hs}" in m.group(0)),
          f"exit line is {m.group(0) if m else 'absent'}; "
          f"'it stopped' must be distinguishable from 'it finished'")

    check("the all-candidates-fetched exit still exists",
          "COMPLETE: every discovered candidate has been fetched" in LOOP,
          "the guard replaced the success path instead of adding to it")

    # The two loops must agree, since they feed one corpus and one grader.
    a = re.search(r'^BARREN_LIMIT="\$\{BARREN_LIMIT:-(\d+)\}"', LOOP, re.M)
    b = re.search(r'^BARREN_LIMIT="\$\{BARREN_LIMIT:-(\d+)\}"', SIB, re.M)
    check("both transcript sources use the same default limit",
          a is not None and b is not None and a.group(1) == b.group(1),
          f"happyscribe={a.group(1) if a else None}, fetch={b.group(1) if b else None}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
