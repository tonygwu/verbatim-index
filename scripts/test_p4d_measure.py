#!/usr/bin/env python3
"""The P4d measurement's arithmetic and labels, checked before any quota is spent.

  INTERVAL   clopper_pearson matches known exact values and its edge cases
  CLASSIFY   an answer is labelled valid, schema_invalid or no_json; a tool
             attempt is its own label; quota, auth and timeout are infra
  FAKE-TOOL  an answer that writes a tool call as text is flagged
  SUMMARY    infra failures are excluded from the unusable-answer denominator

No quota: grade.validate and the classifier run on canned text.

  .venv/bin/python scripts/test_p4d_measure.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_t", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("P4d measurement helpers")
    M = load("p4d_fable_tools_off")
    G = load("grade")

    print("\n[INTERVAL]")
    lo, hi = M.clopper_pearson(0, 12)
    check("0 of 12 gives [0, 0.2646]", lo == 0.0 and abs(hi - 0.2646) < 0.0005, f"{lo}, {hi}")
    lo, hi = M.clopper_pearson(12, 12)
    check("12 of 12 gives [0.7354, 1]", abs(lo - 0.7354) < 0.0005 and hi == 1.0, f"{lo}, {hi}")
    lo, hi = M.clopper_pearson(3, 12)
    check("3 of 12 gives [0.0549, 0.5719]", abs(lo - 0.0549) < 0.0005 and abs(hi - 0.5719) < 0.0005, f"{lo}, {hi}")
    try:
        M.clopper_pearson(13, 12)
        refused = False
    except ValueError:
        refused = True
    check("k above n is refused", refused)

    print("\n[CLASSIFY]")
    check("no JSON in the answer is no_json", M.classify(G, "I cannot grade this.", None, "x/y")["outcome"] == "no_json")
    check("JSON that fails validation is schema_invalid",
          M.classify(G, json.dumps({"transcript_id": "x/y"}), None, "x/y")["outcome"] == "schema_invalid")
    check("a tool attempt is its own outcome",
          M.classify(G, None, f"{G.E_TOOL_ATTEMPT}: Fable made 1 tool call(s)", "x/y")["outcome"] == "tool_attempt")
    check("a quota stop is infra, not an unusable answer",
          M.classify(G, None, f"{G.E_AUTH}: out of quota", "x/y")["outcome"] == "infra")
    check("a missing transcript audit is infra",
          M.classify(G, None, f"{G.E_NO_TRANSCRIPT}: no session transcript", "x/y")["outcome"] == "infra")

    print("\n[FAKE-TOOL]")
    fake = '<invoke name="Read">\n<parameter name="file_path">/x</parameter>\n</invoke>'
    r = M.classify(G, fake, None, "x/y")
    check("a tool call written as text is flagged and counted as no_json",
          r["outcome"] == "no_json" and r["fake_tool_text"] is True, str(r))

    print("\n[SUMMARY]")
    records = ([{"outcome": "valid"}] * 8 + [{"outcome": "no_json", "fake_tool_text": True}]
               + [{"outcome": "schema_invalid"}] + [{"outcome": "infra", "error_type": G.E_AUTH}] * 2)
    s = M.summarize(records)
    check("attempted counts every call", s["attempted"] == 12)
    check("the denominator excludes infra", s["answered"] == 10 and s["unusable"] == 2, str(s))
    check("the rate and its interval come from 2 of 10",
          s["rate"] == 0.2 and s["ci95"] == [round(x, 4) for x in M.clopper_pearson(2, 10)], str(s))
    check("infra failures keep their taxonomy", s["infra_taxonomy"] == {G.E_AUTH: 2}, str(s["infra_taxonomy"]))
    check("fake tool text is counted", s["fake_tool_text"] == 1)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
