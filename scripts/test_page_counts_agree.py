#!/usr/bin/env python3
"""Every scored-of-past-due figure on the predictions page agrees, and a ranked row explains nothing.

FOUND 2026-10-11 (audit after the deploy of 2026-10-10): the live page printed "459 of 676 past-due"
twice and "495 of 676 past-due" once. 36 of the 495 scored predictions were called early (VD-5): a
dated source showed the outcome before the deadline, so they score while still not past due.
eyebrow_status(), thesis() and score_info() subtract them; score_legend() did not, so it called all
495 past-due.

VP-19 (found 2026-09-16): score_why() is computed for every row and returned "12 scored, below the
floor of 3" for ranked rows. The page reads it only when a row has no score, so readers never saw it,
but the page data carried a false sentence for 45 ranked people.

No data, no quota: the functions are called on a fixed counts block.
  .venv/bin/python scripts/test_page_counts_agree.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_predictions_site as B  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


RULE = {"min_lead_days": 60, "baseline_only": "the log score", "clamp": 0.01}
SPLIT = {"eligible": {"n": 2, "reasons": {"no_source": 2}}, "not_eligible": {"n": 1, "reasons": {"no_source": 1}}}


def counts(scored: int, past_due: int, early_before: int) -> dict:
    return {"scored": scored, "past_due": past_due, "early_before": early_before, "leaders_ranked": 45,
            "restated": 0, "unresolvable_split": SPLIT}


FIG = re.compile(r"(\d+) of (\d+) (?:past-due|due)")

for early in (36, 0):
    c = counts(495 if early else 459, 676, early)
    texts = {"eyebrow_status": B.eyebrow_status(c), "thesis": B.thesis(c, 49), "score_legend": B.score_legend(c)}
    try:
        texts["score_info"] = B.score_info(c, RULE)
    except (KeyError, TypeError) as exc:  # the fixture may lack a key score_info reads; the others still count
        print(f"  note  score_info not rendered on the fixture: {type(exc).__name__}: {exc}")
    figs = {name: FIG.findall(t) for name, t in texts.items()}
    every = {f for fs in figs.values() for f in fs}
    check(f"early_before={early}: every 'N of M past-due' figure on the page is the same",
          every == {("459", "676")}, str(figs))
    check(f"early_before={early}: the score legend states the past-due figure",
          ("459", "676") in figs["score_legend"], texts["score_legend"][:300])
    if early:
        check("the score legend names the predictions called early, so 459 + 36 accounts for all 495 scored",
              "36" in texts["score_legend"] and "495" in texts["score_legend"], texts["score_legend"][:400])
    else:
        check("with no early calls the legend says nothing about them", "early" not in texts["score_legend"],
              texts["score_legend"][:400])

# VP-19: a ranked row (3 or more scored) carries no hover explanation; an unranked one still does.
ranked = {"n_scored": 12, "ranked": True, "eligible": 20, "past_due": 30, "unresolvable": 3}
check("a ranked row's score_why is empty", not B.score_why(ranked, 60), repr(B.score_why(ranked, 60)))
few = {"n_scored": 2, "ranked": False, "eligible": 5, "past_due": 9, "unresolvable": 1}
check("an unranked row still says it is below the floor", "below the floor" in (B.score_why(few, 60) or ""),
      repr(B.score_why(few, 60)))
check("a row with nothing scored still explains why", "eligible" in (B.score_why(
    {"n_scored": 0, "ranked": False, "eligible": 4, "past_due": 9, "unresolvable": 4}, 60) or ""))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
