#!/usr/bin/env python3
"""On a TREND window, the prior must price the same question the resolver answers.

FOUND 2026-09-27 while scoring the seven investors. A trend record has no date the
speaker gave; the pipeline judges it over the window since the statement. The
resolver's rule 7 says that on such a window the question is whether the claimed
DIRECTION held. The prior prompt had no such rule. It showed the deadline line's
"THIS IS A TREND WINDOW ... See rule 7" pointer to a rule it never defined, and
priced the literal endpoint in the criterion.

The case: Cathie Wood, 2021, "the cost of sequencing a whole human genome will fall
to 10 cents". The prior priced $0.10 inside the window at p = 0.02. The resolver,
under rule 7, found costs fell about 87% and answered occurred. The two stages
scored different events, and the record paid +5.64 points, enough on its own to
put her first on the board.

What this pins:
  - a trend record's prior prompt carries a trend rule that prices the direction;
  - a NON-trend prior prompt is byte-identical to the one every existing prior was
    priced with, so the change reaches only trend records;
  - the new text adds no word that would tell the assessor what happened.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import resolution_lib as R  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(basis):
    return {
        "prediction_id": "g1", "leader_slug": "ada", "transcript_id": "ada/t1", "_basis": basis,
        "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical", "slug": "ada"},
        "source": {"statement_date": "2021-02-01", "venue": "podcast", "title": "A Talk",
                   "quote": "sequencing will fall to ten cents", "context_before": "b", "context_after": "a"},
        "prediction": {"normalized_claim": "Sequencing a genome will cost 10 cents.",
                       "resolution_criteria": "At an unspecified date, sequencing will cost 10 cents.",
                       "target_date": None, "target_date_text": "", "category": "technology_product"},
        "resolution": {"status": "not_started"},
    }


def legacy_prior_prompt(r, deadline):
    """The prompt every existing prior was priced with, rebuilt from its parts."""
    f = R.prompt_facts(r, deadline)
    return (f"{R.PRIOR_TASK}\n{'=' * 70}\n{R._block(f)}{'=' * 70}\n\n"
            f"Stand on {f['statement_date']}. Answer with the JSON object now.\n")


def main() -> int:
    d = dt.date(2026, 9, 16)
    trend = rec("trend: trend over 5.6y since the statement")
    stated = rec("stated")

    tp = R.build_prior_prompt(trend, d)
    check("TREND: the prompt says what to price on a trend window",
          "TREND WINDOW" in tp and "PRICE THE DIRECTION" in tp, tp[-1500:])
    check("TREND: the rule matches the resolver's: direction over the elapsed window, not the endpoint",
          "not the literal endpoint" in tp.lower() or "not whether the literal" in tp.lower(), tp[-1500:])
    check("TREND: the new text leaks nothing", R.prior_prompt_leaks(tp, R.prompt_facts(trend, d)) == [],
          str(R.prior_prompt_leaks(tp, R.prompt_facts(trend, d))))

    sp = R.build_prior_prompt(stated, d)
    check("STATED: a non-trend prompt is byte-identical to the one existing priors used",
          sp == legacy_prior_prompt(stated, d))
    check("STATED: a non-trend prompt carries no trend rule", "PRICE THE DIRECTION" not in sp)

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
