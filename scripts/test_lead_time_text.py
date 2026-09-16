#!/usr/bin/env python3
"""The page must state the lead-time rule the SCORER used, never a typed number.

VP-18. The page said a prediction must "reach at least six months out" while
phase2_resolvability.MIN_LEAD_DAYS was 60 and scores.json recorded
rule.min_lead_days 60. Six months is 180 days, so the published methodology
described a rule no run has used since the operator replaced the floor on
2026-09-15.

It went stale because it was TYPED. The same two f-strings interpolate
{MIN_SCORED} four characters away, which is exactly why the rank floor followed
its constant and the lead time did not.

The number is taken from scores.json's own `rule`, not from the code constant,
because phase2_resolvability.py:380 exposes --min-lead-days: the constant is a
default, and a run may not have used it. The page describes the run it renders.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build_predictions_site as B  # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if not ok and detail else ""))
    if not ok:
        FAILED += 1


def main() -> int:
    print("lead-time text follows the scorer, not a typed number")

    # A rule that is deliberately NOT the current default, so a hardcoded 60
    # would pass this test while still being a typed number.
    rule = {"baseline_only": "points = -log2(p)", "clamp": 0.01,
            "min_lead_days": 45, "min_scored_to_rank": 3}
    corpus = {"scored": 7, "past_due": 20, "leaders_ranked": 4,
              "unresolvable_reasons": {"no_source": 2},
              "by_outcome": {"unresolvable": 3}}

    # [SITE 1] the methodology paragraph, rendered unconditionally for every reader
    info = B.score_info(corpus, rule)
    check("methodology states the run's own lead time", "45 days" in info, info[-260:])
    check("methodology does not say six months", "six months" not in info)

    # [SITE 2] the hover text, rendered on rows with nothing eligible
    why = B.score_why({"n_scored": 0, "eligible": 0, "past_due": 9, "unresolvable": 0},
                      rule["min_lead_days"])
    check("hover states the run's own lead time", "45 days" in why, why)
    check("hover does not say six months", "six months" not in why)

    # [SOURCE] no typed lead-time number survives anywhere in the renderer
    src = (REPO / "scripts" / "build_predictions_site.py").read_text()
    check("no 'six months' literal remains", "six months" not in src)
    check("no bare '60 days' literal remains", not re.search(r"\b60 days\b", src))

    # [LIVE] the real scores.json, if present, agrees with the scorer's constant
    live = REPO / "data" / "predictions" / "scores.json"
    if live.exists():
        got = json.loads(live.read_text())["rule"].get("min_lead_days")
        check("live scores.json records a lead time", isinstance(got, int), repr(got))
        rendered = B.score_info(json.loads(live.read_text())["corpus"], json.loads(live.read_text())["rule"])
        check(f"live page would say {got} days", f"{got} days" in rendered)

    print(f"\n{'FAILED' if FAILED else 'OK'}: {FAILED} failing check(s)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
