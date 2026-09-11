#!/usr/bin/env python3
"""Guards on grade_loop.sh's opt-in publish step.

The loop rebuilds site/index.html every cycle and, before 2026-09-11, never
published it. The live page only moved when a person ran deploy.sh, which left
a 13-hour stale board on 2026-09-09 and recurred three more times in two days.

PUBLISH_ON_COMPLETE=1 closes that. These are the properties that make it safe
to hand an unattended loop a key to a public site:

  - off unless explicitly set, so existing invocations do not change behaviour
  - it publishes ONCE, at the exit, not on every cycle
  - it cannot run after a failed render, because that path exits first
  - a failed publish is loud and exits non-zero rather than reading as COMPLETE

Pure checks over the shell source. No quota, no network, no data directory.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


LOOP = repo_root() / "scripts" / "grade_loop.sh"
SRC = LOOP.read_text()

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def line_of(pattern: str) -> int:
    """1-indexed line number of the first match, or -1."""
    for i, line in enumerate(SRC.splitlines(), 1):
        if re.search(pattern, line):
            return i
    return -1


def main() -> int:
    print("publish-on-complete guards\n")

    print("[1] the script is still valid bash")
    r = subprocess.run(["bash", "-n", str(LOOP)], capture_output=True, text=True)
    check("bash -n accepts grade_loop.sh", r.returncode == 0, r.stderr.strip())

    print("\n[2] off by default")
    check("PUBLISH_ON_COMPLETE defaults to 0",
          re.search(r'PUBLISH_ON_COMPLETE="\$\{PUBLISH_ON_COMPLETE:-0\}"', SRC) is not None)
    check("the guard tests for exactly \"1\", so a typo does not publish",
          re.search(r'\[ "\$PUBLISH_ON_COMPLETE" = "1" \]', SRC) is not None)

    print("\n[3] it publishes once, at the exit, not per cycle")
    deploys = re.findall(r"^\s*(?:if )?bash scripts/deploy\.sh", SRC, re.M)
    check("exactly one deploy invocation in the loop", len(deploys) == 1,
          f"found {len(deploys)}")
    guard = line_of(r'\[ "\$PUBLISH_ON_COMPLETE" = "1" \]')
    idle_exit = line_of(r'\[ "\$idle" -ge "\$IDLE_EXIT" \]')
    check("the publish sits inside the IDLE_EXIT branch, not the cycle body",
          idle_exit != -1 and guard > idle_exit, f"idle_exit line {idle_exit}, guard line {guard}")

    print("\n[4] it never publishes a stale board")
    stale_exit = line_of(r"STOPPING ON A STALE LEADERBOARD")
    check("the stale-board exit is checked BEFORE the publish",
          stale_exit != -1 and stale_exit < guard,
          f"stale exit line {stale_exit}, publish guard line {guard}")

    print("\n[5] plain deploy.sh, not --refresh")
    # Only INVOCATIONS count. The stale-board message tells a human to run
    # `deploy.sh --refresh` by hand, and that string is advice, not a command,
    # so a naive search over the whole file fails on the loop's own help text.
    invocations = [ln.strip() for ln in SRC.splitlines()
                   if re.match(r"^\s*(?:if\s+)?bash scripts/deploy\.sh\b", ln)]
    check("the loop invokes deploy.sh exactly once", len(invocations) == 1,
          f"found {len(invocations)}: {invocations}")
    check("that invocation does not pass --refresh",
          all("--refresh" not in ln for ln in invocations),
          "--refresh re-aggregates and carries the daemon-clone precondition")

    print("\n[6] a failed publish is loud and non-zero")
    check("failure is named in the loop's own log",
          "PUBLISH FAILED" in SRC)
    check("it says the live site is unchanged",
          re.search(r"LIVE site is unchanged", SRC) is not None)
    check("it prints the last line of the error log",
          SRC.count("last line of data/logs/grade_loop.err") >= 3)
    fail_exit = line_of(r"retry by hand: bash scripts/deploy\.sh")
    complete = line_of(r"COMPLETE: nothing left to grade")
    check("the failure path exits before the COMPLETE line",
          fail_exit != -1 and complete != -1 and fail_exit < complete,
          f"failure line {fail_exit}, COMPLETE line {complete}")
    tail = SRC[SRC.index("PUBLISH FAILED"):]
    check("the failure path exits non-zero",
          re.search(r"exit 1", tail.split("COMPLETE: nothing left")[0]) is not None)

    print("\n[7] success still reaches COMPLETE")
    check("a successful publish says so", "published. live site now matches this build" in SRC)
    check("COMPLETE and exit 0 remain after the publish block",
          complete > guard and re.search(r"COMPLETE: nothing left to grade.*\n\s*exit 0", SRC) is not None)

    print(f"\n{passed}/{passed + failed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
