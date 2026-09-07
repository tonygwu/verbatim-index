#!/usr/bin/env python3
"""Guards for deploy.sh's --refresh flag and its staleness line (2026-09-07).

deploy.sh renders site/index.html from data/results.json and publishes it. It
never re-ran aggregate.py, so results.json could be far behind the grades on
disk and a deploy would republish the previous cycle's numbers while reporting
success. That happened twice in one session: the board said Jeff Bezos had 5
transcripts when 8 of his had scored, and nothing in the output said so.

What is asserted here:

  ARGS      --refresh and --dry-run are both accepted, in any order and
            together, and an unknown flag is refused rather than ignored.
  GUARD     --refresh writes data/, which every clone shares, so it requires
            the daemon clone. A plain deploy must NOT require it, or the other
            clones lose the ability to publish.
  SAME      the refresh uses grade_loop.sh's own aggregate.py invocation, so a
            refreshed deploy and a loop cycle produce the same file.
  ORDER     aggregate runs BEFORE build_site, or the page is rendered from the
            file the refresh was about to replace.
  STALE     every deploy reports whether results.json covers the grades on
            disk. Silence is the failure this flag exists to prevent.

Run: .venv/bin/python scripts/test_deploy_refresh.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SH = REPO / "scripts" / "deploy.sh"
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


def main() -> int:
    src = SH.read_text()
    print("\n[1] deploy.sh --refresh")

    check("deploy.sh parses flags in a loop, not just $1",
          'for arg in "$@"' in src, "only the first argument is read")
    check("--refresh is a recognised flag", "--refresh) REFRESH=1" in src)
    check("--dry-run still works alongside it", "--dry-run) DRY=1" in src)
    check("an unknown flag is refused rather than silently ignored",
          re.search(r'\*\)\s*echo "unknown argument', src) is not None,
          "a typo like --refesh would deploy stale data and say nothing")

    check("--refresh requires the daemon clone, because it writes data/",
          "require_daemon_clone" in src and "daemon_guard.sh" in src,
          "any clone could overwrite the shared results.json")
    # index() raises when a marker is missing, which would abort the run and
    # hide every later check. A missing marker is a failure to report, not a
    # crash, so look them up defensively.
    def at(needle: str) -> int:
        return src.index(needle) if needle in src else -1

    guard, branch, build = (at("require_daemon_clone"), at('if [ "$REFRESH" -eq 1 ]'),
                            at("build_site.py"))
    check("the guard sits inside the --refresh branch only",
          -1 not in (guard, branch, build) and branch < guard < build,
          "a plain deploy must stay runnable from any clone")

    check("the refresh calls aggregate.py",
          "scripts/aggregate.py" in src, "nothing recomputes results.json")
    for flag in ("--grades data/grades", "--roster data/roster/final.json",
                 "--transcripts data/transcripts_blind", "--out data/results.json"):
        check(f"the refresh passes {flag}, as grade_loop.sh does",
              flag in src, "a refreshed deploy would differ from a loop cycle")
    agg, bs = at("scripts/aggregate.py"), at("scripts/build_site.py")
    check("aggregate runs BEFORE the page is rendered",
          -1 not in (agg, bs) and agg < bs,
          "the page would be built from the file the refresh replaces")

    check("every deploy reports staleness, refresh or not",
          "grade_files_read" in src and "STALE" in src,
          "a stale publish stays silent, which is the original bug")
    check("staleness compares grades on disk with the ones results.json used",
          'rglob("*.json")' in src and '"_raw" not in p.parts' in src,
          "raw judge dumps would be counted as grades")
    check("a results.json with no grade_files_read says so rather than passing",
          "cannot be checked" in src,
          "an older results.json would report itself current")

    # The trap this hit on the first attempt: grades_loaded is counted AFTER
    # the subject-share filter drops rows, so comparing it to a count of files
    # reports a permanent false staleness equal to the number dropped. A deploy
    # said "84 newer" immediately after a successful refresh.
    check("staleness does not compare against the post-filter grades_loaded",
          'get("grades_loaded")' not in src,
          "a fresh results.json would report itself stale forever")
    agg_src = (REPO / "scripts" / "aggregate.py").read_text()
    check("aggregate.py records the pre-filter file count",
          "grade_files_read" in agg_src, "nothing comparable to a count of files")
    a_set, a_filter = agg_src.find("grade_files_read = len(grades)"), agg_src.find(", unscorable = filter_unscorable(")
    check("it is recorded BEFORE any filter runs",
          -1 not in (a_set, a_filter) and a_set < a_filter,
          "the count would already be filtered and the comparison meaningless")
    check("and it is published in diagnostics for deploy.sh to read",
          '"grade_files_read": grade_files_read' in agg_src)

    r = subprocess.run(["bash", "-n", str(SH)], capture_output=True, text=True)
    check("deploy.sh is valid bash", r.returncode == 0, r.stderr[-300:])

    r = subprocess.run(["bash", str(SH), "--nonsense"], capture_output=True,
                       text=True, cwd=REPO)
    check("an unknown flag exits non-zero and never reaches wrangler",
          r.returncode != 0 and "unknown argument" in r.stderr,
          f"rc={r.returncode} stderr={r.stderr[-200:]}")

    for f in FAIL:
        print(f"FAIL  {f}")
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
