#!/usr/bin/env python3
"""P11 step 1: docs/PUNDITS.md is rendered from the P10 gate report, never typed.

docs/PUNDITS-PLAN.md, P11: "Write docs/PUNDITS.md with every gate result: estimate,
interval, n, and exclusions per judge/mode." scripts/pundits_gate_doc.py renders it
from scripts/pundits_gates.py's JSON. The report is built here from the same
synthetic checkout test_pundits_gates.py uses.

  EVERY GATE  each gate gets a row with its verdict; G-drift says it did not run
  NUMBERS     an estimate, its 90% interval and its n appear as the report has them
  EXCLUSIONS  lost cells by judge and mode, and the excluded judge, appear
  LIMITS      the relative-test limit and the few-clusters warning are printed
  WITHHELD    --withhold-lean prints no lean-split number, no lean-group table and
              no per-pair coverage verdict (beside the per-person loss table it
              would show which group holds a loss), and says why; the non-lean
              gates still print in full
  PROVENANCE  the data revision is printed; a report missing a gate is refused

No quota, no live data.

  .venv/bin/python scripts/test_pundits_gate_doc.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
REV = "0123456789abcdef0123456789abcdef01234567"


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("P11 gate document")
    try:
        import pundits_gate_doc as D
    except Exception as exc:  # noqa: BLE001 - the missing module is the failure under test
        check("scripts/pundits_gate_doc.py is importable", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    import pundits_gates as G
    import test_pundits_gates as T

    with tempfile.TemporaryDirectory(prefix="p11-") as td:
        root = Path(td) / "data"
        root.mkdir()
        T.build(root)
        rep = G.report(root, T.LEANS)
    doc = D.render(rep, data_revision=REV)
    held = D.render(rep, data_revision=REV, withhold_lean=True)

    print("\n[EVERY GATE]")
    for gate in ("fable_tool_calls", "G-search", "G-coverage", "G-judge-lean", "G-halo-lean", "G-drift"):
        check(f"{gate} has a row with its verdict", f"| {gate}" in doc and rep["gates"][gate]["verdict"] in doc)
    check("G-drift says it did not run", "did not run" in doc)
    # FOUND 2026-10-12 by review: mid-P9, with anchors scheduled and none re-graded,
    # the renderer died on a missing "why" and would have printed "0 anchors".
    mid = json.loads(json.dumps(rep))
    mid["gates"]["G-drift"] = {"verdict": "INCONCLUSIVE", "ran": False, "delta_points": 2, "anchors_scheduled": 6,
                               "by_judge_mode": {}, "why": "6 drift anchors are scheduled but none has been re-graded yet"}
    mdoc = D.render(mid, data_revision=REV)
    check("anchors scheduled, none re-graded: the row counts the scheduled anchors",
          "| G-drift | all | INCONCLUSIVE | did not run | &ndash; | 6 anchors scheduled |" in mdoc,
          mdoc[mdoc.find("| G-drift"):][:200])
    part = json.loads(json.dumps(rep))
    part["gates"]["G-drift"] = {"verdict": "INCONCLUSIVE", "ran": True, "delta_points": 2, "anchors_scheduled": 6,
                                "by_judge_mode": {"fable|blinded": {"anchors": 6, "estimate": 0.1, "ci90": [-0.5, 0.7],
                                                                    "verdict": "PASS"}},
                                "missing_cells": ["gemini|blinded"]}
    pdoc = D.render(part, data_revision=REV)
    check("a scheduled cell with no re-grade gets its own INCONCLUSIVE row",
          "| G-drift | gemini blinded | INCONCLUSIVE | not re-graded |" in pdoc, pdoc[pdoc.find("| G-drift"):][:300])

    print("\n[NUMBERS]")
    jf = rep["gates"]["G-judge-lean"]["by_judge"]["fable"]
    check("a judge-lean estimate and its interval appear as the report has them",
          f"{jf['estimate']:+.2f}" in doc and f"[{jf['ci90'][0]:+.2f}, {jf['ci90'][1]:+.2f}]" in doc, doc[:800])
    check("its n, the complete transcripts, appears", f"{rep['gates']['G-judge-lean']['transcripts']} transcripts" in doc)
    check("the identity rates appear", "93.3%" in doc and "100.0%" in doc)

    print("\n[EXCLUSIONS]")
    check("lost cells by judge and mode appear", "| gemini | blinded | 8 | 1 |" in doc, doc[doc.find("Cells"):][:400])
    check("the excluded judge and its cell count appear", "astra" in doc and "16" in doc)

    print("\n[LIMITS]")
    check("the relative-test limit is printed", "relative test" in doc)
    check("the few-clusters warning is printed", "too narrow" in doc)

    print("\n[WITHHELD]")
    check("no lean-split estimate is printed", f"{jf['estimate']:+.2f}" not in held, held[:600])
    hp = rep["gates"]["G-halo-lean"]["panel"]
    check("no halo-lean estimate is printed", f"{hp['estimate']:+.2f}" not in held)
    check("no lean-group table is printed", "| left |" not in held and "| right |" not in held)
    # Pair verdicts beside the per-person loss table would show which lean group
    # holds a loss; with one lost recording that names a person's lean.
    check("G-coverage prints only its overall verdict, no lean pair",
          "loss, left minus right" not in held and "| G-coverage | loss between lean groups |" in held,
          held[held.find("| G-coverage"):][:300])
    check("it says the figures are withheld and why", "withheld" in held.lower() and "disclosure" in held.lower())
    # FOUND 2026-10-12 by review: the halo rows printed "4 + 4 people" and the
    # few-clusters limit named every group with its size. A group size is a
    # lean-split figure too: when one person joins the board, the group that
    # grows by one names that person's lean.
    sizes = rep["lean_groups"]
    leaked = [f"{k} {n}" for k, n in sizes.items() if f"{k} {n}" in held]
    hp_people = hp.get("people") or []
    check("no lean group size is printed, by name or as an 'n + m people' pair",
          not leaked and (len(hp_people) < 2 or f"{hp_people[0]} + {hp_people[1]} people" not in held),
          f"leaked={leaked} {held[held.find('G-halo-lean'):][:200]}")
    check("the few-clusters limit is still stated, without the groups",
          "too narrow" in held and f"fewer than {G.MIN_CLUSTERS} people" in held)
    check("the non-lean gates still print in full", "| gemini | blinded | 8 | 1 |" in held and "93.3%" in held)

    print("\n[PROVENANCE]")
    check("the data revision is printed", REV[:12] in doc)
    noted = D.render(rep, data_revision=REV, title="Pilot gate results", note="A dry run on the pilot.")
    check("a title and a note can be given, so a pilot render needs no hand edit",
          noted.startswith("# Pilot gate results\n") and "A dry run on the pilot." in noted, noted[:300])
    bad = json.loads(json.dumps(rep))
    del bad["gates"]["G-halo-lean"]
    try:
        D.render(bad, data_revision=REV)
        refused = False
    except RuntimeError as exc:
        refused = "G-halo-lean" in str(exc)
    check("a report missing a gate is refused, naming it", refused)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
