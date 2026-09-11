#!/usr/bin/env python3
"""fetcher_running() counts a running script, not a mention of its name.

WHY THIS EXISTS. `pgrep -f X` matches any process whose FULL COMMAND LINE
contains X, which includes every shell wrapper, editor, grep and agent command
that merely names the script. grade_loop.sh uses it to decide whether a
transcript source is still feeding the corpus, and a false positive there makes
the grader wait forever for a source that is not running.

This is a documented house rule, learned the hard way: six poll loops once kept
spinning because their pgrep pattern matched their own command line. It is not
hypothetical here either. On 2026-09-11 `pgrep -f grade_loop.sh` returned two
pids, one of which was a `/bin/zsh -c ...` wrapper that merely contained the
string. Only the other was running the loop.

The discriminator is the third field of `ps -Ao comm=,args=`: a shell running a
SCRIPT has the script path there, while a shell running a command STRING has
`-c`. So a `-c` payload that mentions the script is excluded, and an actual
`bash scripts/happyscribe_loop.sh` is kept.

What is asserted here:

  REAL    a genuine `bash <path>/happyscribe_loop.sh` is detected.
  WRAPPER a `zsh -c '... happyscribe_loop.sh ...'` that is NOT running the loop
          is NOT detected. This is the case that hangs the grader.
  NONE    with neither running, nothing is detected. A check that always says
          yes fails in the direction that looks healthy.
  NAIVE   plain `pgrep -f` is shown to get the WRAPPER case wrong, so this file
          proves the hardening does something rather than restating pgrep.

  .venv/bin/python scripts/test_fetcher_false_positive.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOOP = (REPO / "scripts" / "grade_loop.sh").read_text()
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


def extract_fn() -> str:
    """Pull fetcher_running() plus its FETCHERS list out of the live script."""
    i = LOOP.find("FETCHERS=(")
    j = LOOP.find("\n}", LOOP.find("fetcher_running()"))
    if i < 0 or j < 0:
        return ""
    return LOOP[i:j + 2]


def ask(fn_src: str, name: str) -> bool:
    """Run the real function against the real process table."""
    script = f'{fn_src}\nFETCHERS=("{name}")\nif fetcher_running; then exit 0; else exit 1; fi\n'
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(script)
        p = f.name
    try:
        return subprocess.run(["bash", p], capture_output=True).returncode == 0
    finally:
        Path(p).unlink(missing_ok=True)


def main() -> int:
    print("fetcher false positive")
    fn = extract_fn()
    check("fetcher_running() and its list can be extracted from grade_loop.sh", bool(fn))
    if not fn:
        print("\n0 passed, 1 failed")
        return 1

    name = "zz_fake_source_loop.sh"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        real = tmp / name
        real.write_text("#!/usr/bin/env bash\nsleep 25\n")
        real.chmod(0o755)

        print("\nNONE: neither running")
        check("nothing is detected when no such process exists", not ask(fn, name),
              "the check says a source is running when none is")

        print("\nWRAPPER: a shell whose -c payload merely names the script")
        # TWO commands on purpose. A shell given a single command execs it and
        # rewrites its own argv, so the script name disappears and the wrapper
        # case silently stops reproducing.
        wrapper = subprocess.Popen(
            ["bash", "-c", f": mentions {name}; sleep 25"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.2)
            naive = subprocess.run(["pgrep", "-f", name], capture_output=True).returncode == 0
            check("plain `pgrep -f` DOES match the wrapper (the bug being fixed)", naive,
                  "the wrapper did not reproduce, so the next check proves nothing")
            check("fetcher_running() does NOT match it", not ask(fn, name),
                  "a mention of the script name hangs the grader forever")
        finally:
            wrapper.terminate()
            wrapper.wait(timeout=5)

        print("\nREAL: an actual shell running the script")
        proc = subprocess.Popen(["bash", str(real)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.2)
            check("fetcher_running() detects a genuine run", ask(fn, name),
                  "hardening went too far and now never sees a live source, so "
                  "the grader would exit out from under it again")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
