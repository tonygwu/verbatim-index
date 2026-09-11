#!/usr/bin/env python3
"""grade_loop waits for EVERY transcript source, not just the first one.

WHY THIS EXISTS. grade_loop.sh decided it was done like this:

    if pgrep -f "fetch_loop.sh" > /dev/null; then
      say "  no new grades, but fetch loop is still running. waiting."

One name, written when YouTube was the only source. Happy Scribe was added
later as a deliberately independent second source, and this check never learned
about it, so grade_loop could declare COMPLETE while happyscribe_loop was still
merging transcripts into the same corpus.

OBSERVED 2026-09-11: grade_loop printed "COMPLETE: nothing left to grade" at
04:17:37Z. happyscribe_loop merged 8 transcripts at 04:49:11Z. Nothing graded
them, and nothing said so; the operator noticed only because the coverage
numbers stopped matching. The corpus sat with ungraded transcripts until the
loop was restarted by hand.

The same shape as the judge-enumeration bug: a list written out by hand goes
stale the day something is added beside it. So the sources are named in ONE
place, and the exit check iterates that list rather than testing a literal.

What is asserted here:

  NOT_ONE    the exit check no longer tests a single hardcoded fetcher name.
  KNOWS_HS   happyscribe_loop.sh is among the sources it waits for.
  LISTED     the sources live in one named list, so adding a third source is
             one edit in an obvious place rather than a grep for pgrep calls.
  MATCHES    the patterns actually match a running process of that name. A
             pattern that never matches would make the loop wait forever, or
             never wait at all, and source inspection alone cannot tell which.
  REASON     the list carries the incident that produced it.

  .venv/bin/python scripts/test_fetcher_detection.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


LOOP = (REPO / "scripts" / "grade_loop.sh").read_text()


def main() -> int:
    print("fetcher detection")

    check("grade_loop.sh is valid bash",
          subprocess.run(["bash", "-n", str(REPO / "scripts" / "grade_loop.sh")],
                         capture_output=True).returncode == 0)

    # Comments may QUOTE the old check; that history is worth keeping. Only
    # executable lines matter here.
    code = "\n".join(l for l in LOOP.splitlines() if not l.lstrip().startswith("#"))
    check("the exit check does not test one hardcoded fetcher name",
          'pgrep -f "fetch_loop.sh"' not in code,
          "still gates on fetch_loop.sh alone, so happyscribe_loop can feed an "
          "exited grader")
    # In the FETCHERS list specifically, not merely mentioned in a comment.
    check("happyscribe_loop.sh is one of the sources it waits for",
          re.search(r'FETCHERS=\([^)]*happyscribe_loop\.sh', LOOP, re.S) is not None,
          "the second transcript source is invisible to the exit check")

    m = re.search(r"^FETCHERS=\((.*?)\)", LOOP, re.M | re.S)
    check("the sources are declared in one named list", m is not None,
          "no FETCHERS list; adding a third source means hunting for pgrep calls")
    names = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    check("the list names both current sources",
          set(names) >= {"fetch_loop.sh", "happyscribe_loop.sh"}, str(names))
    check("the exit check iterates the list rather than a literal",
          re.search(r'for\s+\w+\s+in\s+"\$\{FETCHERS\[@\]\}"', LOOP) is not None,
          "the list exists but something still tests a literal")

    idx = LOOP.find("FETCHERS=(")
    preceding = LOOP[max(0, idx - 900):idx] if idx >= 0 else ""
    check("the list records why it exists",
          idx >= 0 and any(w in preceding for w in ("04:17", "COMPLETE", "second source", "Happy Scribe")),
          "no comment ties the list to the incident that produced it")

    # Source inspection cannot tell a working pattern from a dead one.
    print("\nMATCHES: the patterns match a real process")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        procs = []
        try:
            for n in (names or ["fetch_loop.sh", "happyscribe_loop.sh"]):
                p = tmp / n
                p.write_text("#!/usr/bin/env bash\nsleep 30\n")
                p.chmod(0o755)
                procs.append(subprocess.Popen(["bash", str(p)],
                                              stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL))
            time.sleep(1.5)
            for n in (names or []):
                hit = subprocess.run(["pgrep", "-f", n], capture_output=True)
                check(f"pgrep -f {n!r} finds a running process of that name",
                      hit.returncode == 0,
                      "the pattern never matches, so the loop would never wait")
        finally:
            for pr in procs:
                pr.terminate()
            for pr in procs:
                try:
                    pr.wait(timeout=5)
                except Exception:
                    pr.kill()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
