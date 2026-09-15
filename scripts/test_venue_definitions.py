#!/usr/bin/env python3
"""Judges and human labellers get the SAME venue definitions, decided by who is talking.

Pundits plan, P5 and P7. The rubric named the nine venues without defining them,
so a guest on a four-person Piers Morgan split screen or on Bill Maher's
Overtime could be read as `panel_show`, `tv_segment` or `guest_interview`.
Judge-versus-human agreement on venue would then measure vague wording. The
rule, agreed with the operator on 2026-09-15: count the other live voices,
not the host or the platform.

  RUBRIC     RUBRIC.md defines every venue in the schema enum, one table row each
  GUIDE      the labelling guide defines every venue, one table row each
  SAME       each venue's definition text is identical in both files
  RULE       both files state the other-live-voices rule and resolve the
             panel-guest case to panel_show

No quota.

  .venv/bin/python scripts/test_venue_definitions.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude" / "skills" / "pundit-transcript-grader"
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def definitions(text: str) -> dict[str, str]:
    """`| `venue` | definition |` rows."""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\|\s*`([a-z_]+)`\s*\|\s*(.+?)\s*\|\s*$", text, re.M)}


def main() -> int:
    print("venue definitions")
    enum = json.loads((SKILL / "judge_output.schema.json").read_text())["properties"]["venue_type"]["enum"]
    rubric = (SKILL / "RUBRIC.md").read_text()
    guide = (REPO / "docs" / "PUNDITS-LABELLING-GUIDE.md").read_text()
    r, g = definitions(rubric), definitions(guide)

    print("\n[RUBRIC]")
    check("RUBRIC.md defines every venue in the schema", set(enum) <= set(r), f"missing {sorted(set(enum) - set(r))}")
    print("\n[GUIDE]")
    check("the labelling guide defines every venue in the schema", set(enum) <= set(g), f"missing {sorted(set(enum) - set(g))}")
    print("\n[SAME]")
    differ = [v for v in enum if v in r and v in g and r[v] != g[v]]
    check("each venue's definition is identical in both files", not differ, str(differ))
    print("\n[RULE]")
    for name, text in (("RUBRIC.md", rubric), ("guide", guide)):
        check(f"{name} states the other-live-voices rule", "other live voices" in text.lower())
        check(f"{name} resolves a guest on a multi-person panel to panel_show",
              bool(re.search(r"panel_show[^\n]*(whoever hosts|regardless of who hosts)", text)) or
              "whoever hosts" in r.get("panel_show", "") + g.get("panel_show", ""))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
