#!/usr/bin/env python3
"""The per-grade stderr log is not committed.

WHY THIS EXISTS. data/logs/grade_loop.err was tracked and reached 50.1 MB, which
was 95% of all 53.0 MB of tracked bytes under data/logs. It had been committed in
four recent commits, so roughly 200 MB of history existed for one log file, and
it grows every cycle without bound.

MEASURED before the change: 616,169 of about 673,000 lines were "CACHED
<judge>/<mode>/r0 <leader>/<source>" notices, re-emitted for every transcript
times every judge on every cycle. 92% of the file is a restatement of the cache
working correctly.

Nothing unique was lost. All 26,302 REJECT reasons are also written to
data/logs/transcript_qa.json, which stays tracked at 0.7 MB; the judge failure
taxonomy is in results.json diagnostics; and per-grade errors are in
data/logs/grade_errors_blind.jsonl, also tracked. The file stays on disk in the
daemon clone, so a human can still read the last run's stderr.

What is asserted here:

  IGNORED   data/.gitignore names the file, with a reason next to it.
  UNTRACKED the ignore is ACTUALLY in force. Adding a path to .gitignore does
            nothing to a file git already tracks, which is the usual way this
            change gets made and silently fails.
  KEPT      the smaller structured logs that carry the same information are
            still tracked, so this is a bloat fix and not a loss of evidence.
  ON_DISK   the file is still written, because the fix is "do not commit it",
            not "stop recording it".

Pure checks: reads data/.gitignore and git's index. No network, no quota.

  .venv/bin/python scripts/test_log_bloat.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
BLOATED = "logs/grade_loop.err"
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(DATA), *args], capture_output=True, text=True)


def main() -> int:
    print("log bloat")
    if not (DATA / ".git").exists():
        print("  SKIP  data/ is not a checkout here")
        return 0

    ignore = (DATA / ".gitignore").read_text()
    check("data/.gitignore names the per-grade stderr log",
          BLOATED in ignore, "the 50 MB log is not ignored")
    # A bare path with no reason is how the next person deletes the line.
    idx = ignore.find(BLOATED)
    preceding = ignore[max(0, idx - 500):idx] if idx >= 0 else ""
    check("the ignore carries a reason, not just a path",
          any(w in preceding.lower() for w in ("mb", "cached", "bloat", "grow")),
          "no explanatory comment precedes the entry")

    # The real failure mode: .gitignore is edited and the file stays tracked,
    # so every commit keeps carrying it and the change looks done.
    tracked = git("ls-files", "--error-unmatch", BLOATED).returncode == 0
    check("the ignore is in force: git no longer tracks the file",
          not tracked,
          "still tracked; .gitignore does not apply to already-tracked paths, "
          "so `git rm --cached` is required")

    check("git check-ignore agrees the path is ignored",
          git("check-ignore", "-q", BLOATED).returncode == 0,
          "check-ignore says the path is not ignored")

    # Same information, smaller artefacts. If these stop being tracked, the
    # bloat fix has quietly become a loss of evidence.
    for keep in ("logs/transcript_qa.json", "logs/grade_errors_blind.jsonl"):
        check(f"{keep} is still tracked",
              git("ls-files", "--error-unmatch", keep).returncode == 0,
              f"{keep} carries the reasons that used to be read out of the stderr log")

    # Not recording it at all would be a different and worse change.
    check("the log is still written to disk",
          (DATA / BLOATED).exists(),
          "the fix is to stop COMMITTING it, not to stop recording it")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
