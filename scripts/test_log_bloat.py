#!/usr/bin/env python3
"""Two reproducible caches are not committed: the per-grade stderr log, and the market cache.

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

Pure checks: reads the registered production checkout and its Git index.
An experiment data clone is not a source of production runtime evidence.
No network, no quota.

THE SECOND CASE, added 2026-09-13. predictions/_markets is the raw HTTP
response cache market_consensus.py keeps so a re-run costs no API calls.
MEASURED: 1,975 files, 292 MB on disk, of which 30 were tracked at 18.5 MB
against 307.7 MB of tracked bytes in the whole data repo. Committing the rest
would make the cache half the repo, for ever.

Nothing reads it downstream, and the provenance is in the records: all 475
accepted predictions carry consensus.status, .cutoff and .searched_at_utc, and
455 carry candidates_dropped naming every market id, platform and reason.
0 carry a market_probability, so no published number rests on a cached price.

  .venv/bin/python scripts/test_log_bloat.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Runtime logs belong to production. A frozen experiment clone intentionally
# has neither live ignored logs nor necessarily today's production ignore rules.
from data_clone_workflow import production_path
import predictions_lib as L
DATA = production_path(REPO)
BLOATED = "logs/grade_loop.err"
CACHE = "predictions/_markets"
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(DATA), *args], capture_output=True, text=True)


def main() -> int:
    print("log bloat")
    if not (DATA / ".git").exists():
        print("  SKIP  the registered production checkout is not available here")
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

    print("market cache")
    ignore_has_cache = CACHE + "/" in ignore or CACHE in ignore
    check("data/.gitignore names the market response cache",
          ignore_has_cache, "292 MB of cached HTTP bodies is not ignored")
    idx = ignore.find(CACHE + "/")
    preceding = ignore[max(0, idx - 900):idx] if idx >= 0 else ""
    check("the market-cache ignore carries a reason, not just a path",
          any(w in preceding.lower() for w in ("mb", "cache", "bloat", "history")),
          "no explanatory comment precedes the entry")

    # The same trap as above, and the one that actually bit: 30 of these files
    # were already tracked, so the .gitignore line alone would change nothing.
    still = git("ls-files", CACHE).stdout.split()
    check("the ignore is in force: git tracks no file under the market cache",
          not still,
          f"{len(still)} still tracked; `git rm -r --cached {CACHE}` is required")
    check("git check-ignore agrees the cache directory is ignored",
          git("check-ignore", "-q", CACHE + "/kalshi").returncode == 0,
          "check-ignore says the path is not ignored")

    # The records, not the cache, are where market provenance lives. If this
    # stops holding, untracking the cache HAS lost evidence.
    import json
    # jsonl_lines, never str.splitlines(). splitlines() breaks on VT, FF, FS,
    # GS, RS, NEL, U+2028 and U+2029, and JSON permits every one of those RAW
    # inside a string, so a record carrying one is cut in half and both halves
    # fail to parse. predictions_lib.parse_lines was fixed for this on
    # 2026-09-14 and this reader was missed.
    #
    # It stopped being hypothetical the moment the web-sourced records were
    # placed in the production corpus: exactly one of them,
    # web-assets-ctfassets-net-cbb20aaa.jsonl, carries a single U+2028 in a
    # Stripe letter and took this whole suite down with
    # `Unterminated string starting at: line 1 column 5435`, which names a
    # column and not the character responsible.
    seen = missing = 0
    for f in sorted((DATA / "predictions").glob("*/*.jsonl")):
        for line in L.jsonl_lines(f.read_text()):
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("accepted"):
                continue
            seen += 1
            c = r.get("consensus") or {}
            if not (c.get("status") and c.get("searched_at_utc") and c.get("cutoff")):
                missing += 1
    check("every accepted prediction carries its own market provenance",
          seen > 0 and missing == 0,
          f"{missing} of {seen} accepted records lack consensus status, cutoff or searched_at_utc")

    # Same rule as the log: stop committing it, do not stop keeping it.
    check("the cache is still on disk, so a re-run still costs no API calls",
          (DATA / CACHE).is_dir() and any((DATA / CACHE).iterdir()),
          "the fix is to stop COMMITTING the cache, not to delete it")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
