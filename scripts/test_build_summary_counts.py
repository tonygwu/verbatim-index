#!/usr/bin/env python3
"""The build log's score lines count past-due scored predictions the way the page does (VI-49).

A prediction called early (VD-5) is scored before its deadline, so it is not past
due. The page's legend (`score_legend`) prints scored minus those early calls over
the past-due count. On 2026-10-20 the build log paired all 585 scored with the 834
past due while the live page said "546 of 834", and two ledger rows quoted the log.

  .venv/bin/python scripts/test_build_summary_counts.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build_predictions_site as B  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def row(scored: bool, early: bool = False, not_due: bool = False) -> dict:
    return {"leader_slug": "ada", "scored": scored, "early_called": early, "not_due": not_due}


def main() -> int:
    # 6 plain scored rows; 1 called early but past due by the as-of date, so it
    # counts as past due; 3 called early and still before their deadline; 1
    # called early, not scored. Scored 10, of which 7 are past due.
    preds = ([row(True)] * 6 + [row(True, early=True)] + [row(True, early=True, not_due=True)] * 3
             + [row(False, early=True, not_due=True)])
    scores_doc = {"as_of": "2026-10-20", "predictions": preds,
                  "corpus": {"scored": 10, "past_due": 20, "leaders_ranked": 2}}
    # What listed_corpus returns for the people the page lists.
    cl = {"scored": 10, "past_due": 20, "early_before": 3, "leaders_ranked": 2}

    legend = B.score_legend(cl)
    m = re.search(r"(\d+) of (\d+) past-due", legend)
    check("the legend prints scored minus early calls over past due", bool(m) and m.groups() == ("7", "20"),
          legend[:200])
    page = m.groups() if m else None

    scores_line, listed_line = B.summary_lines(scores_doc, cl, 1, 0, {"prior": {}, "resolve": {}})
    m = re.search(r"the page prints (\d+) of (\d+) past due", listed_line)
    check("the listed line's past-due scored count equals the legend's", bool(m) and m.groups() == page,
          listed_line)
    check("the listed line names the early calls apart", "3 more called early" in listed_line
          and "(10 scored in all)" in listed_line, listed_line)
    m = re.search(r"scores: (\d+) of (\d+) past due", scores_line)
    check("the scores line counts early calls over every row of scores.json the same way",
          bool(m) and m.groups() == ("7", "20"), scores_line)
    check("the scores line names the early calls apart", "3 more called early" in scores_line
          and "(10 scored in all)" in scores_line, scores_line)

    print()
    print(f"FAILED: {len(FAILED)} failing check(s)" if FAILED else "OK: 0 failing check(s)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
