#!/usr/bin/env python3
"""The published scoring as-of date may not lag the newest predictions data.

Operator rule, 2026-09-27: whenever new predictions are added, the scoring
as-of date moves up to the date they were added, without asking. The as-of
date decides which predictions count as past due, so a board scored at an old
as-of silently leaves out every prediction that fell due since.

`scores_asof_lag()` compares `scoring.json`'s `as_of` with the UTC date of the
newest data commit that touched `predictions/`, ignoring commits that touch
only `scores.json` or `scoring.json` (re-scoring is not adding predictions).
`deploy_predictions.sh` refuses when it returns a reason.

Every check runs against a real temporary git repository with pinned commit
dates, because the date must come from the commit, never from a file mtime or
the local clock.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

passed = failed = 0


def check(label: str, got, want) -> None:
    global passed, failed
    if got == want:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label}: got {got!r}, want {want!r}")


def git(repo: Path, *args: str, when: str | None = None) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def commit(repo: Path, rel: str, body: str, when: str) -> str:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", f"touch {rel}", when=when)
    return git(repo, "rev-parse", "HEAD")


try:
    from data_clone_workflow import scores_asof_lag
except ImportError as e:
    check("data_clone_workflow exports scores_asof_lag", repr(e), "importable")
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(1)

with tempfile.TemporaryDirectory() as td:
    repo = Path(td) / "data"
    repo.mkdir()
    git(repo, "init", "-q")
    # Predictions added late on 09-27 UTC. 23:30Z is 16:30 in California, so a
    # local-clock reading would call it the same day either way; the 01:30Z commit
    # below is the one a local-time reading gets wrong (still 09-27 in California).
    r1 = commit(repo, "predictions/alex/a.jsonl", "{}\n", "2026-09-27T23:30:00Z")
    check("as-of before the newest predictions commit is refused",
          scores_asof_lag(repo, r1, "2026-09-16") is not None, True)
    check("the reason names both dates",
          all(d in (scores_asof_lag(repo, r1, "2026-09-16") or "") for d in ("2026-09-16", "2026-09-27")), True)
    check("as-of equal to the newest predictions commit date passes", scores_asof_lag(repo, r1, "2026-09-27"), None)
    check("as-of after it passes", scores_asof_lag(repo, r1, "2026-09-28"), None)

    # Re-scoring only: scores.json and scoring.json on a later day are not new predictions.
    commit(repo, "predictions/scoring.json", json.dumps({"as_of": "2026-09-27"}), "2026-09-29T10:00:00Z")
    r2 = commit(repo, "predictions/scores.json", "{}", "2026-09-29T10:05:00Z")
    check("a later commit touching only scores.json/scoring.json does not move the bar",
          scores_asof_lag(repo, r2, "2026-09-27"), None)

    # The year-square labels are display text generated FROM predictions, not
    # predictions. FOUND 2026-09-29: committing them moved the bar a day and
    # would have refused the deploy that publishes them.
    r2b = commit(repo, "predictions/year_summaries.json", "{}", "2026-09-29T11:00:00Z")
    check("a later commit touching only year_summaries.json does not move the bar",
          scores_asof_lag(repo, r2b, "2026-09-27"), None)

    # Data outside predictions/ (the leaders board) does not move it either.
    r3 = commit(repo, "grades/x.json", "{}", "2026-09-30T10:00:00Z")
    check("a later commit outside predictions/ does not move the bar", scores_asof_lag(repo, r3, "2026-09-27"), None)

    # A new prediction at 01:30Z on 10-01 is 10-01 in UTC, 09-30 in California.
    r4 = commit(repo, "predictions/alex/b.jsonl", "{}\n", "2026-10-01T01:30:00Z")
    check("the commit date is read in UTC", scores_asof_lag(repo, r4, "2026-09-30") is not None, True)
    check("UTC date itself passes", scores_asof_lag(repo, r4, "2026-10-01"), None)

    # The revision passed in is honoured: an older revision is judged by its own history.
    check("an older revision is judged on its own history", scores_asof_lag(repo, r1, "2026-09-27"), None)

    try:
        scores_asof_lag(repo, r4, "Sept 2026")
        raised = False
    except ValueError:
        raised = True
    check("a malformed as-of raises, never passes", raised, True)

deploy = (HERE / "deploy_predictions.sh").read_text()
check("deploy_predictions.sh calls scores_asof_lag and refuses on it",
      "scores_asof_lag(" in deploy and "REFUSING: scores as-of" in deploy, True)

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
