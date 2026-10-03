#!/usr/bin/env python3
"""A restated member with an early call is a restated row, not a crash.

FOUND 2026-10-03 in the rebuild run: the early pass (VD-5) checks every eligible
record not yet due, including a restatement cluster member that is not its
cluster's specific member. When that member's early call is decided, it lands in
`early_used`; join() had already set the row's resolution to None because the
member is restated, and then read the early call off None:
`AttributeError: 'NoneType' object has no attribute 'get'`. A restated row carries
no outcome of its own, so it carries no early call either, and it must still read
`restated:<specific member>`.

Runs score_predictions.join on hand-built rows. No data, no network.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_predictions as S  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def row(pid: str) -> dict:
    return {"prediction_id": pid, "leader_slug": "ada", "transcript_id": f"ada/{pid}",
            "prediction": {"normalized_claim": "It ships.", "resolution_criteria": "By 2030, it ships."},
            "source": {"quote": "we will ship it", "statement_date": "2026-01-01",
                       "statement_date_basis": "stated_in_page"},
            "_deadline": dt.date(2030, 1, 1),
            "_flags": {"eligible": True, "specificity_ok": True, "lead_ok": True, "lead_days": 1461, "deadline_before_statement": False,
                       "basis": "stated"}}


early = {"outcome": "occurred", "confidence": "high", "as_of": "2026-10-03", "not_occurred_basis": None,
         "run_id": "r-early", "sources": [], "reasoning": "it shipped early", "deadline": "2030-01-01"}
prior = {"p": 0.3, "p_raw": 0.3, "clamped": False, "reasoning": "r", "reference_class": "c", "deadline": "2030-01-01"}
rows = [row("spec"), row("member")]
try:
    out, why = S.join(rows, {"spec": early, "member": early}, {"spec": prior, "member": prior},
                      {"member": "spec"}, early_used={"spec": {"not_due": True}, "member": {"not_due": True}})
    by = {r["prediction_id"]: r for r in out}
    check("join() does not crash on a restated member that has an early call", True)
    check("the restated member reads restated:<specific member>",
          by["member"]["not_scored_because"] == "restated:spec", str(by["member"].get("not_scored_because")))
    check("the restated member carries no early call of its own",
          "early" not in by["member"] and not by["member"].get("early_called"), str(by["member"]))
    check("the specific member still scores on its early call and says so",
          by["spec"]["scored"] and by["spec"].get("early_called") and by["spec"].get("not_due"), str(by["spec"]))
except AttributeError as exc:
    check("join() does not crash on a restated member that has an early call", False, repr(exc))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
