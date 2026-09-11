#!/usr/bin/env python3
"""HappyScribe discovery must follow the roster, not just the file's existence.

WHY THIS EXISTS. happyscribe_loop.sh ran discovery only when the candidate file
was missing or empty:

    if [ ! -s "$CANDS" ]; then

So the pool was built once against the 40-name roster and never revisited. The
roster grew to 50 on 2026-09-10 and eleven leaders were never searched, while
C.C. Wei stayed in the pool after being removed from the roster. The loop kept
running and reporting COMPLETE because every candidate it knew about had been
fetched, which is true and useless: it had nothing to ask for on behalf of the
eleven. Nine of the twelve leaders short of target had no HappyScribe entry at
all, and the operator found this by asking, not from any log line.

A derived artifact has to track its source. The pool is derived from the roster.

What is asserted here:

  UNSEARCHED  unsearched_leaders() names roster slugs absent from the pool, and
              also names pool keys no longer on the roster, because a leader
              removed from the study should not keep feeding it transcripts.
  EMPTY       a leader present with an empty candidate list counts as SEARCHED.
              Larry Ellison, Michael Dell and Sergey Brin were searched and
              genuinely have no podcast appearances; re-searching them every
              cycle would be a permanent no-op that hides the real gap.
  MISSING     an absent or empty pool file reports every roster slug, rather
              than raising or reporting nothing.
  WIRED       happyscribe_loop.sh consults it and re-runs discovery when it is
              non-empty, instead of testing only for an empty file.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_hs_discovery_follows_roster.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import fetch_happyscribe as hs  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


def roster_file(tmp: Path, slugs: list[str]) -> Path:
    p = tmp / "roster.json"
    p.write_text(json.dumps({"roster": [{"slug": s, "name": s.replace("-", " ").title()}
                                        for s in slugs]}))
    return p


def pool_file(tmp: Path, pool: dict | None) -> Path:
    p = tmp / "pool.json"
    if pool is not None:
        p.write_text(json.dumps(pool))
    return p


def test_unsearched() -> None:
    print("UNSEARCHED: the helper compares pool against roster")
    fn = getattr(hs, "unsearched_leaders", None)
    check("fetch_happyscribe exposes unsearched_leaders()", callable(fn),
          "nothing can tell the loop that the roster moved")
    if not callable(fn):
        return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = roster_file(tmp, ["alpha", "beta", "gamma"])
        p = pool_file(tmp, {"alpha": [{"url": "u"}], "delta": [{"url": "u"}]})
        missing, stale = fn(r, p)
        check("a roster slug absent from the pool is unsearched",
              sorted(missing) == ["beta", "gamma"], str(sorted(missing)))
        check("a pool key no longer on the roster is reported as stale",
              sorted(stale) == ["delta"], str(sorted(stale)))


def test_empty_counts_as_searched() -> None:
    print("\nEMPTY: searched-and-found-nothing is not unsearched")
    fn = getattr(hs, "unsearched_leaders", None)
    if not callable(fn):
        check("searched-with-zero-results counts as searched", False, "helper absent")
        return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = roster_file(tmp, ["alpha", "beta"])
        p = pool_file(tmp, {"alpha": [], "beta": [{"url": "u"}]})
        missing, _ = fn(r, p)
        check("a leader with an empty list is NOT re-searched every cycle",
              list(missing) == [], str(list(missing)))


def test_missing_pool() -> None:
    print("\nMISSING: no pool file means nobody has been searched")
    fn = getattr(hs, "unsearched_leaders", None)
    if not callable(fn):
        check("an absent pool reports every roster slug", False, "helper absent")
        return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = roster_file(tmp, ["alpha", "beta"])
        missing, stale = fn(r, tmp / "does-not-exist.json")
        check("an absent pool reports every roster slug",
              sorted(missing) == ["alpha", "beta"], str(sorted(missing)))
        check("an absent pool reports no stale keys", list(stale) == [], str(list(stale)))
        p = tmp / "empty.json"
        p.write_text("")
        missing2, _ = fn(r, p)
        check("an empty pool file behaves like an absent one",
              sorted(missing2) == ["alpha", "beta"], str(sorted(missing2)))


def test_wired() -> None:
    print("\nWIRED: the loop acts on it")
    loop = (REPO / "scripts" / "happyscribe_loop.sh").read_text()
    check("the loop no longer gates discovery on an empty file alone",
          not re.search(r'if \[ ! -s "\$CANDS" \]; then\s*\n\s*say "no candidate file', loop),
          "discovery still runs only when the pool file is missing")
    check("the loop asks which leaders are unsearched",
          "unsearched" in loop, "nothing in the loop consults the helper")
    check("the loop re-runs discovery when the roster has unsearched leaders",
          re.search(r"unsearched[\s\S]{0,400}--discover", loop) is not None,
          "the answer is computed and not acted on")
    check("the loop says who it is re-searching, not just that it is",
          re.search(r'say\s+"[^"]*unsearched|say\s+"[^"]*\$\{?unsearched', loop) is not None,
          "a silent re-discovery is how the first gap went unnoticed")


def main() -> int:
    print("happyscribe discovery follows the roster")
    test_unsearched()
    test_empty_counts_as_searched()
    test_missing_pool()
    test_wired()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
