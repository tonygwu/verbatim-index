#!/usr/bin/env python3
"""A published pilot says it is a pilot, in figures derived from the run.

DECIDED by the operator 2026-09-16, as the condition for publishing the pundits
board. The page explained its rubric and its judges well and never said how much
evidence stood behind the scores. A reader met a ranked list of ten named people
and had no way to learn that the roster holds 39, that one person is scored on
five recordings, that blinding was MEASURED to fail on every recording, or that
the format correction was fitted and then withheld.

Every figure in the banner is DERIVED from results.json. None may be typed into
the copy file, for the same reason `_TYPED_PERCENT` already rejects a typed
percentage there: the corpus grows, and a typed number goes stale silently. This
repo has paid for that twice, once when the judge panel grew to three and the
copy still said two, and once when the review page still claimed five recordings
each after the top-up doubled several people.

  REQUIRED   the banner keys are required, so the notice cannot silently vanish
  COUNTS     ranked people and roster size come from the results, not the copy
  EVIDENCE   the range of recordings per person is stated
  LEAKAGE    the measured blinding leakage rate is stated
  WITHHELD   the format adjustment is named as withheld only when it is
  PLACED     the banner renders before the board, not after it
  UNTYPED    a typed percentage in the copy is still refused

  .venv/bin/python scripts/test_pundits_site_banner.py
"""
from __future__ import annotations

import copy as copymod
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def fake_results(n_leaders=3, n_unscored=6, leakage=1.0, venue_applied=False, ns=(5, 9, 12)):
    dims = ["d1_steelmanning", "d2_epistemic_rigor", "d3_good_faith"]
    leaders = []
    for i in range(n_leaders):
        b = {d: 50.0 for d in dims}
        b.update({"overall": 50.0, "ci_low": 45.0, "ci_high": 55.0})
        leaders.append({"slug": f"p{i}", "name": f"Person {i}", "role": "commentator",
                        "rank": i + 1, "n_transcripts": ns[i % len(ns)],
                        "confidence": "high", "blinded": b,
                        "open": dict(b), "halo": {"overall": 0.1}})
    return {"leaders": leaders, "unranked": [], "unscored": [{"slug": f"u{i}"} for i in range(n_unscored)],
            "transcripts": [],
            "diagnostics": {"grades_used": 100, "blinding_leakage_rate": leakage,
                            "venue_adjustment_applied": venue_applied,
                            "min_transcripts_to_rank": 5}}


def banner(page: str) -> str:
    """The banner's own text, so a digit elsewhere on the page cannot pass a check."""
    m = re.search(r'<p class="status"[^>]*>(.*?)</p>', page, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def main() -> int:
    print("pundits site pilot banner")
    import build_study_site as B

    profile = json.loads((REPO / "profiles" / "pundits.json").read_text())
    site_copy = json.loads((REPO / profile["site_copy"]).read_text())

    print("\n[REQUIRED]")
    check("status_label and status_note are required copy keys",
          {"status_label", "status_note"} <= set(B.REQUIRED_COPY), str(B.REQUIRED_COPY))
    stripped = {k: v for k, v in site_copy.items() if k != "status_note"}
    try:
        B.validate_copy(profile, stripped)
        check("copy missing status_note is refused", False, "it rendered anyway")
    except RuntimeError as exc:
        check("copy missing status_note is refused", "status_note" in str(exc), str(exc))

    page = B.render(fake_results(), profile, site_copy, rundate="17 September 2026")
    bn = banner(page)
    check("the page renders a banner at all", bool(bn), "no <p class=\"status\"> in the page")

    print("\n[COUNTS]")
    check("the banner states the ranked count and the roster size", "3 of 9" in bn, bn)
    bigger = banner(B.render(fake_results(n_leaders=3, n_unscored=20), profile, site_copy, rundate="x"))
    check("and both follow the data rather than the copy", "3 of 23" in bigger, bigger)

    print("\n[EVIDENCE]")
    check("the banner states the range of recordings per person", "5 to 12" in bn, bn)
    same = banner(B.render(fake_results(ns=(7, 7, 7)), profile, site_copy, rundate="x"))
    check("a corpus where everyone has the same count reports one number, not a range",
          "7 recordings" in same and " to " not in same, same)

    print("\n[LEAKAGE]")
    check("the banner states the measured leakage rate", "100%" in bn, bn)
    half = banner(B.render(fake_results(leakage=0.5), profile, site_copy, rundate="x"))
    check("and it follows the measurement", "50%" in half, half)

    print("\n[WITHHELD]")
    check("the banner names the withheld format adjustment", "withheld" in bn.lower(), bn)
    applied = banner(B.render(fake_results(venue_applied=True), profile, site_copy, rundate="x"))
    check("and does NOT name it when the adjustment was applied",
          "withheld" not in applied.lower(), applied)

    print("\n[PLACED]")
    check("the banner comes before the board table",
          'class="status"' in page and page.index('class="status"') < page.index('id="board"'),
          "banner must be above the scores a reader sees first")

    print("\n[UNTYPED]")
    typed = copymod.deepcopy(site_copy)
    typed["status_note"] = "This covers 10% of the roster."
    try:
        B.validate_copy(profile, typed)
        check("a typed percentage in the banner copy is refused", False, "it was accepted")
    except RuntimeError as exc:
        check("a typed percentage in the banner copy is refused", True, str(exc))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
