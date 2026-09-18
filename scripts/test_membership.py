#!/usr/bin/env python3
"""Membership is explicit, and an unknown slug is an ERROR rather than an empty board.

Three boards publish from one engine and nobody is a member of anything today:
grade.py scores every file it finds, and aggregate_predictions.py unions the
roster with any slug that has records. membership.json makes the answer explicit
and scripts/membership.py is the only reader of it.

WHY THE LOOKUP SHAPE IS TESTED BEHAVIOURALLY. The two obvious idioms,
`data.get(slug, [])` and `data.get(slug) or []`, both turn an unknown slug into
an empty board, which is exactly the silent answer this module exists to refuse.
Neither idiom fails any test that only checks a known slug, so the
discriminating case is a fixture holding BOTH an unknown slug and a deliberately
empty one: the empty one must return [], the unknown one must raise. `cc-wei` is
that empty entry in the shipped file, so the two cases are not hypothetical.

WHY A BOARD-NAME WHITELIST. A typo such as "leader" for "leaders" is valid JSON
with no unknown slug. Unwhitelisted it would grade nobody, render zero leaders
and publish, because deploy.sh prints the leader count and applies no floor. The
whitelist catches it at source and needs no counts. The count-based guards are
P2's, in aggregate.py and deploy.sh, where the counts actually are.

WHY THE DEFAULT PATH IS RESOLVED FROM membership.py's OWN __file__.
test_render_integrity.py writes a modified copy of aggregate.py into a temporary
directory and runs it there. A default resolved from the CALLER's file or from
the working directory would resolve into that temporary directory and fail, so
one check below runs load() from a temporary working directory.

THE SLUG-SET ASSERTION IS ONE-WAY, AND THE BOARD ASSERTION IS WRITTEN TO SURVIVE
P3. Roster slugs must be a subset of membership slugs, never equal to them: the
seven are declared here from P1 onward, because membership gates no writer, so
their blinded copies would land before P3 adds their roster entries and an
unknown-slug raise would fire on the first cycle. Equality between the two sets
would therefore be red across P1 and P2, which is how an operator learns to
ignore a red suite. The leaders BOARD is pinned exactly, as the roster minus the
seven, which holds today (the seven are not on the roster yet, so it is the 50)
and still holds after P3 appends them (roster 57, minus seven, still the 50).

Fixtures are temporary files. Nothing under data/ is read or written. No quota,
no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SEVEN = ("cathie-wood", "marc-andreessen", "chamath-palihapitiya", "david-sacks",
         "bill-gurley", "vinod-khosla", "tom-lee")

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


def raises(label: str, fn, *, naming: str = "") -> None:
    """The call must raise, and the message must name `naming`."""
    try:
        got = fn()
    except Exception as exc:  # noqa: BLE001 - the point is that SOMETHING refuses
        msg = str(exc)
        if not check(label, True):
            return
        if naming:
            check(f"    ... and says so, naming {naming!r}", naming in msg,
                  f"message was {msg!r}")
    else:
        check(label, False, f"returned {got!r} instead of raising")


def write(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.write_text(text)
    return p


def main() -> int:
    import membership as M

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("[1] the file itself is refused when it cannot be trusted")
        raises("a missing file raises", lambda: M.load(tmp / "nope.json"),
               naming="nope.json")
        bad = write(tmp, "bad.json", "{ this is not json")
        raises("malformed JSON raises", lambda: M.load(bad), naming="bad.json")
        notobj = write(tmp, "list.json", '["cathie-wood"]')
        raises("a top level that is not an object raises", lambda: M.load(notobj))
        notlist = write(tmp, "notlist.json", '{"sam-altman": "leaders"}')
        raises("a slug whose boards are not a list raises", lambda: M.load(notlist),
               naming="sam-altman")
        notstr = write(tmp, "notstr.json", '{"sam-altman": ["leaders", 7]}')
        raises("a board entry that is not a string raises", lambda: M.load(notstr),
               naming="sam-altman")
        empty_slug = write(tmp, "emptyslug.json", '{"": ["leaders"]}')
        raises("an empty slug raises", lambda: M.load(empty_slug))

        print("\n[2] a board name outside the whitelist raises, which is the typo case")
        typo = write(tmp, "typo.json", '{"sam-altman": ["leader"]}')
        raises("the 'leader'-for-'leaders' typo raises", lambda: M.load(typo),
               naming="leader")
        raises("... and the message names the slug it came from",
               lambda: M.load(typo), naming="sam-altman")
        dupe = write(tmp, "dupe.json", '{"sam-altman": ["leaders", "leaders"]}')
        raises("a board repeated for one slug raises", lambda: M.load(dupe),
               naming="sam-altman")

        print("\n[3] an unknown slug RAISES where an empty board RETURNS EMPTY")
        fx = write(tmp, "fixture.json", json.dumps({
            "sam-altman": ["leaders"],
            "cathie-wood": ["predictions"],
            "cc-wei": [],
        }))
        data = M.load(fx)
        check("the fixture loads", set(data) == {"sam-altman", "cathie-wood", "cc-wei"},
              f"got {sorted(data)}")
        raises("boards_for on an unknown slug raises",
               lambda: M.boards_for(data, "who-is-this"), naming="who-is-this")
        raises("on_board on an unknown slug raises",
               lambda: M.on_board(data, "who-is-this", "leaders"), naming="who-is-this")
        check("boards_for on the EMPTY entry returns []",
              M.boards_for(data, "cc-wei") == [],
              f"got {M.boards_for(data, 'cc-wei')!r}")
        check("on_board on the EMPTY entry is False, not an error",
              M.on_board(data, "cc-wei", "leaders") is False)
        check("a known slug reports its own board",
              M.on_board(data, "sam-altman", "leaders") is True)
        check("... and not another board",
              M.on_board(data, "sam-altman", "predictions") is False)
        check("the predictions-only entry is off leaders",
              M.on_board(data, "cathie-wood", "leaders") is False
              and M.on_board(data, "cathie-wood", "predictions") is True)

        print("\n[4] an unknown BOARD name raises at the call site too")
        raises("on_board with 'leader' raises",
               lambda: M.on_board(data, "sam-altman", "leader"), naming="leader")
        raises("slugs_on with 'leader' raises",
               lambda: M.slugs_on(data, "leader"), naming="leader")
        check("slugs_on returns the members of a board",
              M.slugs_on(data, "leaders") == ["sam-altman"],
              f"got {M.slugs_on(data, 'leaders')!r}")
        check("... and excludes the empty entry",
              "cc-wei" not in M.slugs_on(data, "predictions"))

        print("\n[5] the shipped membership.json")
        shipped = M.load()
        check("it loads with no argument", isinstance(shipped, dict))
        check("it holds 58 entries", len(shipped) == 58, f"got {len(shipped)}")
        check("DEFAULT_PATH is the repo root file",
              M.DEFAULT_PATH == ROOT / "membership.json", f"got {M.DEFAULT_PATH}")

        roster = json.loads((ROOT / "data" / "roster" / "final.json").read_text())
        roster_slugs = [p["slug"] for p in roster["roster"]]
        missing = [s for s in roster_slugs if s not in shipped]
        check("CONTAINMENT: every roster slug is a membership slug", not missing,
              f"missing {missing}")
        extra = [s for s in M.slugs_on(shipped, "leaders") if s not in roster_slugs]
        check("NOBODY is on the leaders board who is not on the roster", not extra,
              f"extra {extra}; verbatim-index must not move")
        want_leaders = [s for s in roster_slugs if s not in SEVEN]
        check("the leaders board is exactly the roster MINUS the seven",
              M.slugs_on(shipped, "leaders") == want_leaders,
              f"symmetric difference {set(M.slugs_on(shipped, 'leaders')) ^ set(want_leaders)}; "
              "a roster entry added or withdrawn is edited here in the same commit")

        for s in SEVEN:
            check(f"{s} is a membership slug", s in shipped)
            if s in shipped:
                check(f"  {s} is on predictions", M.on_board(shipped, s, "predictions"))
                check(f"  {s} is NOT on leaders",
                      M.on_board(shipped, s, "leaders") is False,
                      "verbatim-index must not move")
        check("cc-wei is present and empty", M.boards_for(shipped, "cc-wei") == [],
              f"got {M.boards_for(shipped, 'cc-wei')!r}")
        check("the shipped file is exactly roster + seven + cc-wei",
              set(shipped) == set(roster_slugs) | set(SEVEN) | {"cc-wei"},
              f"symmetric difference "
              f"{set(shipped) ^ (set(roster_slugs) | set(SEVEN) | {'cc-wei'})}")

        print("\n[6] the same assertions survive P3, simulated rather than argued")
        p3_roster = roster_slugs + [s for s in SEVEN if s not in roster_slugs]
        check("P3: the roster reaches 57", len(p3_roster) == 57, f"got {len(p3_roster)}")
        check("P3: containment still holds",
              not [s for s in p3_roster if s not in shipped])
        check("P3: nobody new reaches the leaders board",
              not [s for s in M.slugs_on(shipped, "leaders") if s not in p3_roster])
        check("P3: the leaders board is still the roster minus the seven",
              M.slugs_on(shipped, "leaders") == [s for s in p3_roster if s not in SEVEN])
        check("P3: and it is still the 50", len(M.slugs_on(shipped, "leaders")) == 50,
              f"got {len(M.slugs_on(shipped, 'leaders'))}")

        print("\n[7] the default path is membership.py's own, not the caller's")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import membership, json; print(len(membership.load()))"],
            cwd=td, env={"PYTHONPATH": str(ROOT / "scripts"),
                         "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True)
        check("load() from an unrelated working directory finds the real file",
              proc.returncode == 0 and proc.stdout.strip() == "58",
              f"rc={proc.returncode} out={proc.stdout.strip()!r} err={proc.stderr.strip()[-300:]!r}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
