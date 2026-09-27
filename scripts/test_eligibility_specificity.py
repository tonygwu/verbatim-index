#!/usr/bin/env python3
"""Which specificity levels may be scored, read through the scorer's own selection.

The operator widened the rule on 2026-09-27: a MEDIUM-specificity prediction is
eligible, as a high one always was. LOW stays out. The rule lives in one constant,
`phase2_resolvability.ELIGIBLE_SPECIFICITY`, and both the funnel and
`resolve_predictions.select()` read it, so the published eligibility and the
funnel's count cannot drift apart.

This runs `select()` on a real fixture corpus rather than inspecting source,
because the flag that gates a published score is what matters, not the text that
computes it. Each record differs from a scorable one in exactly one field.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import phase2_resolvability as P2  # noqa: E402
from resolve_predictions import select  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, *, spec="high", target="2020-12-31", said="2019-01-01"):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "prediction": {"target_date": target, "specificity": spec, "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": "c", "resolution_criteria": "crit"},
        "source": {"statement_date": said, "quote": "q"},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def main() -> int:
    check("RULE: the constant names high and medium, and nothing else",
          tuple(getattr(P2, "ELIGIBLE_SPECIFICITY", ())) == ("high", "medium"),
          repr(getattr(P2, "ELIGIBLE_SPECIFICITY", None)))

    rows = [
        rec("high"),
        rec("medium", spec="medium"),
        rec("low", spec="low"),
        rec("missing", spec=None),
        rec("medium-short-lead", spec="medium", target="2019-02-01"),       # 31 days
        rec("medium-before-said", spec="medium", target="2018-12-31", said="2019-01-01"),
    ]
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "ada").mkdir()
        (d / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        got = {r["prediction_id"]: r["_flags"] for r in select([d], dt.date(2026, 9, 16), P2.MIN_LEAD_DAYS)}

    elig = {pid: f["eligible"] for pid, f in got.items()}
    check("SELECT: every past-due fixture record is selected", set(got) == {r["prediction_id"] for r in rows},
          sorted(got))
    check("ELIGIBLE: high specificity is eligible", elig.get("high") is True, str(elig))
    check("ELIGIBLE: medium specificity is now eligible", elig.get("medium") is True, str(elig))
    check("INELIGIBLE: low specificity stays out", elig.get("low") is False, str(elig))
    check("INELIGIBLE: a missing specificity is not read as medium", elig.get("missing") is False, str(elig))
    check("INELIGIBLE: medium does not bypass the lead-time floor",
          elig.get("medium-short-lead") is False, str(elig))
    check("INELIGIBLE: medium does not bypass the deadline-before-statement check",
          elig.get("medium-before-said") is False, str(elig))
    check("FLAG: specificity_ok is recorded beside specificity_high, and they differ on medium",
          got.get("medium", {}).get("specificity_ok") is True
          and got.get("medium", {}).get("specificity_high") is False, str(got.get("medium")))

    print(f"\n{'ALL PASS' if not FAILED else f'{len(FAILED)} FAILED'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
