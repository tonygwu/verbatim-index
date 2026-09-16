#!/usr/bin/env python3
"""A validation filter is reported with what it cut and for which group.

The working agreement: "Any cap, truncation, or sampling is reported with what
it cut and for which group; a limit that bites one group 10x more than another
is a bias, not a detail."

FOUND by adversarial audit 2026-09-16: the 25-word evidence-quote cap rejected
12 grades across the P8a2 corpus and nothing reported who it hit. Counted by
hand from the error logs, Gemini took 10 of 12, Gemini blinded took 8 against
Gemini open 2, and one person carried 5 of the 12. None of that reached a
diagnostic, so the cap read as an even 8% tax when it was not one.

This is the measurement, not a change to the cap. The cap itself is hashed into
contract_id (RUBRIC.md and judge_output.schema.json), so moving it re-grades the
whole corpus; that decision is separate and is recorded in BACKLOG.md.

  COUNT     every rejected record is counted once, from records and logs together
  GROUPS    incidence is broken down by judge, by mode and by person
  SKEW      a group taking a disproportionate share is flagged, not just listed
  RATE      the share is against that group's attempted calls, never a bare count
  EMPTY     a corpus with no rejections reports zero rather than failing

  .venv/bin/python scripts/test_filter_incidence.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("fi", REPO / "scripts" / "filter_incidence.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    print("filter incidence")
    if not (REPO / "scripts" / "filter_incidence.py").exists():
        check("scripts/filter_incidence.py exists", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    F = load()

    # 12 rejections, deliberately lopsided: gemini 10, fable 2; blinded 9, open 3;
    # person 'p0' carries 5. Attempted: 40 calls per judge.
    rej = ([{"judge": "gemini", "mode": "blinded", "slug": "p0", "error": "quote exceeds 25 words"}] * 5
           + [{"judge": "gemini", "mode": "blinded", "slug": "p1", "error": "quote exceeds 25 words"}] * 3
           + [{"judge": "gemini", "mode": "open", "slug": "p2", "error": "quote exceeds 25 words"}] * 2
           + [{"judge": "fable", "mode": "blinded", "slug": "p3", "error": "quote exceeds 25 words"}]
           + [{"judge": "fable", "mode": "open", "slug": "p4", "error": "quote exceeds 25 words"}])
    attempted = {("gemini", "blinded"): 20, ("gemini", "open"): 20,
                 ("fable", "blinded"): 20, ("fable", "open"): 20}
    rep = F.incidence(rej, attempted)

    print("\n[COUNT]")
    check("every rejection is counted once", rep["total"] == 12, str(rep["total"]))

    print("\n[GROUPS]")
    check("broken down by judge", rep["by_judge"] == {"gemini": 10, "fable": 2}, str(rep["by_judge"]))
    check("broken down by mode", rep["by_mode"] == {"blinded": 9, "open": 3}, str(rep["by_mode"]))
    check("broken down by person", rep["by_person"]["p0"] == 5, str(rep["by_person"]))

    print("\n[RATE]")
    check("the judge rate is against that judge's attempted calls, not the corpus",
          rep["rate_by_judge"]["gemini"] == 0.25 and rep["rate_by_judge"]["fable"] == 0.05,
          str(rep["rate_by_judge"]))

    print("\n[SKEW]")
    check("a judge taking 5x another's rate is flagged",
          rep["skewed"] is True, str(rep.get("skew_note")))
    check("and the note names the two groups and the ratio",
          "gemini" in rep["skew_note"] and "fable" in rep["skew_note"], rep["skew_note"])
    even = F.incidence(
        [{"judge": j, "mode": "blinded", "slug": "p0", "error": "x"} for j in ("fable", "gemini")],
        {("fable", "blinded"): 20, ("gemini", "blinded"): 20})
    check("an even filter is not flagged", even["skewed"] is False, str(even.get("skew_note")))

    print("\n[EMPTY]")
    none = F.incidence([], attempted)
    check("no rejections reports zero rather than failing",
          none["total"] == 0 and none["skewed"] is False, str(none))

    print("\n[READ]")
    with tempfile.TemporaryDirectory(prefix="fi-") as td:
        log = Path(td) / "errors.jsonl"
        log.write_text("\n".join(json.dumps(r) for r in [
            {"judge": "gemini", "mode": "blinded", "id": "p0/s1",
             "error_type": "schema_validation_failed",
             "detail": "d2_epistemic_rigor evidence quote is 31 words, cap is 25"},
            {"judge": "fable", "mode": "open", "id": "p1/s2",
             "error_type": "auth_or_quota", "detail": "session limit"},
        ]) + "\n")
        got = F.read_rejections([log], match="cap is 25")
        check("only records matching the filter are read back",
              len(got) == 1 and got[0]["judge"] == "gemini" and got[0]["slug"] == "p0", str(got))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
