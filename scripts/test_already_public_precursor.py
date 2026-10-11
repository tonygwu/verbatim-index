#!/usr/bin/env python3
"""already_public counts the predicted event itself, never a precursor (ledger VP-32; release resolution-2026-10-11).

FOUND 2026-10-05 and re-read 2026-10-11 (data predictions/_experiments/already-public-20261011/): of the 81
rows the board left out as already public, 11 cite a report that is not the predicted event but an earlier stage
of it, a smaller instance, a different measure or someone's forecast. Bill Gates's "a malaria vaccine will be
invented" (b12ea645) was excluded on a 1997 report of an EXPERIMENTAL vaccine; Sam Altman's "programs that can
think will do assembly-line work by 2031" on the 2012 Baxter robot; Matthew Prince's opt-out from AI Overviews on
Google's 2016 nosnippet control; Bill Gurley's several unicorn failures on ONE fire sale; Dario Amodei's $1 billion
training runs on his own earlier forecast. The resolver's rule 8 named "the event itself, or a credible report
that it had been agreed, decided or scheduled" and never said what does NOT count, and the early-call prompt's
rule 7 did not even say that a forecast is not enough. 7 of those rows were early calls, so the wrong exclusion
was also what kept a wrong "occurred" from scoring.

The fix is text in both prompts, so it is a new resolution-policy release. Measured live before any production
re-resolution on the gold set predictions/_eval/cases-20261011-already-public (the 11 precursor rows must come back
null, the announced-plan rows must stay present). Offline here:
  RULE      both prompts carry the same precursor sentence, in the already-public rule
  RELEASE   the release is resolution-2026-10-11, and the old one stays known so its sidecars still load
  PRIOR     the prior prompt is byte-identical to the one every existing prior was priced with, so no prior
            turns stale (score_predictions.prior_prompt_stale compares prompt hashes)

  .venv/bin/python scripts/test_already_public_precursor.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R  # noqa: E402

FAILED = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


# The prior prompt for the policy fixture, hashed on 2026-10-11 under release resolution-2026-09-30.
PRIOR_PROMPT_SHA_BEFORE = "4d1435e9dc22eb9795a046cf1176229d026466fbea9c24f8f1767ed0c8aa28c5"

rule = getattr(R, "ALREADY_PUBLIC_NOT_A_PRECURSOR", None)
check("the precursor rule exists as one constant", isinstance(rule, str) and len(rule) > 200, repr(rule)[:200])
if isinstance(rule, str):
    for name in ("RESOLVER_TASK", "EARLY_TASK"):
        text = getattr(R, name)
        at = text.find("ALREADY PUBLIC BEFORE IT WAS SAID")
        check(f"{name} carries the rule inside its already-public section", at >= 0 and rule in text[at:at + 3000],
              text[at:at + 600])
    for words in ("earlier stage", "prototype", "experiment", "one case where it needs several",
                  "different product", "speaker's own company announcing the plan", "reports no decision, agreement or schedule"):
        check(f"the rule names {words!r}", words in " ".join(rule.split()), rule)   # the prompt wraps lines
check("the early-call prompt says a forecast is not enough, as the resolver's does",
      "another person's forecast, is not" in R.EARLY_TASK, R.EARLY_TASK[R.EARLY_TASK.find("ALREADY PUBLIC"):][:500])

check("the release is resolution-2026-10-11", R.POLICY_RELEASE[0] == "resolution-2026-10-11", str(R.POLICY_RELEASE))
check("the release hash matches the texts", R.policy_release()[1] == R.POLICY_RELEASE[1],
      f"{R.policy_release()[1]} vs {R.POLICY_RELEASE[1]}")
check("the 2026-09-30 release stays known, so its sidecars still load",
      R.KNOWN_RELEASES == ("resolution-2026-09-30", "resolution-2026-10-11"), str(R.KNOWN_RELEASES))

prior = R.build_prior_prompt(R._policy_fixture(), dt.date(2020, 12, 31))
check("the prior prompt is unchanged, so no existing prior turns stale",
      hashlib.sha256(prior.encode()).hexdigest() == PRIOR_PROMPT_SHA_BEFORE,
      hashlib.sha256(prior.encode()).hexdigest())

print(f"\n{'OK' if not FAILED else 'FAILED'}: {len(FAILED)} failing check(s)")
sys.exit(1 if FAILED else 0)
