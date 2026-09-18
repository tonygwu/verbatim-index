#!/usr/bin/env python3
"""A script that names another script must name one that exists.

WHY THIS FILE EXISTS. On 2026-09-18 three references went stale inside one day,
each failing loudly but only when its own test happened to run:

  deploy.sh gained a call to publication_floor.py, and test_data_clone_workflow's
  synthetic clone copies a TYPED LIST of filenames, so it died on
  "can't open file ... publication_floor.py"

  the same fixture needed membership.json for the same reason

  test_deploy_pundits.py carries its own typed SCRIPTS tuple, and adding a
  module-level import to build_site.py would have broken it

This repo has paid for typed lists twice before, in the hand-written judge list
in aggregate.py and the single fetcher name in grade_loop.sh, and AGENTS.md says
so. The lists are not going away, because deriving them is worse. What was
missing is something that notices when one goes stale.

WHAT IS CHECKED.

  1. Every `scripts/<name>` reference in a committed script names a file that
     exists. That is the plain dangling-reference check.
  2. The two synthetic-clone fixtures carry every script the entry point they run
     actually invokes, which is the specific failure above.

WHAT IS NOT CHECKED, deliberately: whether a reference is REACHABLE. A name
inside a comment, a docstring or a dead branch still has to exist, and pretending
to know which is which would need a parser and would be wrong more often than the
check is.

No network, no quota, no writes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

#: json BEFORE js. Alternation is ordered, so "js" matches inside "json" and the
#: first version of this check reported a dangling `blind_wordlist.js` which is
#: really `blind_wordlist.json`. The prefix is left off that name on purpose:
#: written in full it would be a dangling reference in this very file, and arm
#: [1] found exactly that on the first run.
REF = re.compile(r"scripts/([A-Za-z0-9_]+\.(?:json|py|sh|js))")

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


def references() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(SCRIPTS.iterdir()):
        if not f.is_file() or f.suffix not in (".py", ".sh"):
            continue
        for m in REF.finditer(f.read_text(errors="ignore")):
            out.setdefault(m.group(1), set()).add(f.name)
    return out


def main() -> int:
    print("[1] every scripts/<name> reference names a file that exists")
    refs = references()
    check("the scan found references at all", len(refs) > 50, f"found {len(refs)}")
    missing = {k: sorted(v) for k, v in refs.items() if not (SCRIPTS / k).exists()}
    check(f"none of the {len(refs)} distinct references dangles", not missing,
          f"missing: {missing}")

    print("\n[2] the regex does not invent a missing file out of an extension")
    got = REF.findall("run scripts/blind_wordlist.json and scripts/deploy.sh")
    check("a .json reference is read as .json, not .js",
          got == ["blind_wordlist.json", "deploy.sh"], str(got))

    print("\n[3] the synthetic-clone fixtures carry what their entry points call")
    # test_data_clone_workflow builds a clone and runs deploy.sh and
    # deploy_predictions.sh inside it. test_deploy_pundits builds one and runs
    # deploy_pundits.sh. Both copy a typed list. Derive what those entry points
    # invoke and assert the list covers it.
    fixtures = [
        ("test_data_clone_workflow.py", ("deploy.sh", "deploy_predictions.sh")),
        ("test_deploy_pundits.py", ("deploy_pundits.sh",)),
    ]
    for fixture_name, entry_points in fixtures:
        fixture = (SCRIPTS / fixture_name).read_text()
        for entry in entry_points:
            body = (SCRIPTS / entry).read_text()
            # The --refresh path needs the daemon clone and no fixture takes it.
            body = re.sub(r'if \[ "\$REFRESH" -eq 1 \]; then.*?\nfi\n', "", body,
                          flags=re.S)
            called = {m.group(1) for m in REF.finditer(body)} - {entry}
            check(f"{fixture_name} knows what {entry} calls", bool(called),
                  "if this is empty the derivation broke and the checks below "
                  "prove nothing")
            for name in sorted(called):
                check(f"  {fixture_name} carries {name}", f"'{name}'" in fixture
                      or f'"{name}"' in fixture,
                      f"{entry} calls {name}; the fixture's typed list does not "
                      f"copy it, so that test dies on a missing file the moment "
                      f"the call is added")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
