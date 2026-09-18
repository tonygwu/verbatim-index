#!/usr/bin/env python3
"""The numbers AGENTS.md states about the CURRENT state must match the data.

WHY THIS EXISTS. Four documents went stale inside one day on 2026-09-18, and one
of them was the working agreement itself: it said "The roster is 50 people" for
hours after P3 made it 57, in the file every agent in this fleet reads first.
`membership.json` went from "NOTHING READS IT YET" to being read by four scripts
without the sentence changing. Both were written in the same session as the
change that invalidated them.

WHAT IS CHECKED, AND WHAT IS DELIBERATELY NOT. AGENTS.md carries two KINDS of
number and they need opposite treatment:

  a MEASUREMENT      "46 of 50 leaders moving", "0 of 39 adjacent pairs separate"
                     A record of something measured on a board that no longer
                     exists. The file says so explicitly: "Any figure in this
                     file that says 'of 40' is a record of a measurement taken on
                     the smaller board and is left alone." Re-running it today
                     would give a different number and that is not an error.

  a CURRENT-STATE    "the roster holds 57", "the leaders board holds 50",
  CLAIM              "58 entries"
                     These describe what is true now, and they are wrong the
                     moment the data moves.

Only the second kind is checked, and each claim is matched by a phrase specific
enough that a measurement cannot be mistaken for it. A test that could not tell
the two apart would either fail constantly or be deleted, and both outcomes are
worse than no test.

The claims are located by regex and the expected values come from the live files,
so adding a person to the roster fails this until the sentence is updated.

No network, no quota, no writes.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    return ok


def main() -> int:
    import membership as MB

    agents = (REPO / "AGENTS.md").read_text()
    roster = json.loads((REPO / "data" / "roster" / "final.json").read_text())["roster"]
    board = MB.load()

    live = {
        "roster entries": len(roster),
        "leaders board": len(MB.slugs_on(board, "leaders")),
        "membership entries": len(board),
    }
    print("live data:", live)

    # (what it is, pattern, expected). Each pattern is anchored on wording that a
    # historical measurement does not use: "the roster holds N", not "of N".
    claims = [
        ("the roster size", r"[Tt]he roster (?:holds|is) (\d+)", live["roster entries"]),
        ("the leaders board size", r"leaders board (?:is|holds) (\d+)", live["leaders board"]),
        ("the membership file size", r"(\d+) entries: the \d+ on the roster",
         live["membership entries"]),
    ]

    print("\n[1] every current-state claim matches the data")
    for what, pat, want in claims:
        found = [int(m) for m in re.findall(pat, agents)]
        check(f"AGENTS.md states {what} at all", bool(found),
              f"pattern {pat!r} matched nothing; if the wording changed this check "
              f"silently stops testing, which is why this arm exists")
        wrong = [n for n in found if n != want]
        check(f"  every statement of {what} says {want}", not wrong,
              f"found {found}, live value is {want}")

    print("\n[2] historical measurements are NOT touched by this test")
    # The file's own rule. These must still be present and must NOT be required
    # to equal anything current: they were measured on a 40-name and a 50-name
    # board and re-running them today would give different numbers.
    for phrase in ("of 40", "46 of 50"):
        check(f"a measurement phrased {phrase!r} survives", phrase in agents,
              "if these vanish, someone has 'corrected' history")
    check("the rule that protects them is still stated",
          "is a record of a\n  measurement taken on the smaller board and is left alone" in agents
          or "left alone" in agents,
          "AGENTS.md says old measurements are left alone; that rule is what "
          "makes this test's narrow scope correct")

    print("\n[3] the membership entry describes what is actually wired")
    # It claimed "NOTHING READS IT YET" for hours after P2 wired three readers.
    check("it no longer claims nothing reads membership",
          "NOTHING READS IT YET" not in agents)
    for reader in ("grade.py", "aggregate.py", "build_site.py"):
        seg = agents[agents.index("- Board membership:"):]
        seg = seg[:seg.index("\n- ")]
        check(f"  the entry names {reader} as a reader", reader in seg,
              "a reader that is wired and undocumented is how the last one got "
              "out of date")
    src = (REPO / "scripts" / "aggregate.py").read_text()
    check("  and aggregate.py really does read it", "MB.for_study" in src,
          "if this fails the documentation is ahead of the code instead of behind")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
