#!/usr/bin/env python3
"""Happy Scribe discovery must merge into the candidate pool, not replace it.

fetch_happyscribe.py --discover walked the whole roster and then wrote the pool
wholesale:

    Path(args.candidates).write_text(json.dumps(found, indent=1))

happyscribe_loop.sh:93 runs --discover whenever the roster carries a leader the
pool has never been searched for. So appending seven people to the roster
re-derives the pool for all 57 and REPLACES it. Any candidate a fresh crawl does
not return is gone, and the loop then reports those leaders as searched, which
is the exact shape of the 2026-09-10 bug this file's `unsearched_leaders` was
written to fix.

A fresh crawl legitimately returns less than the pool holds. discover() walks
`children[:max_sitemaps]`, capped at 40, and skips any child sitemap that does
not answer 200. A transient failure therefore silently shrinks the pool.

MEASURED 2026-09-16: the live pool holds 50 slugs and 92 candidates, 26 of them
with an empty list, and it is exactly in sync with the roster, so nothing is
unsearched today. The trap fires the moment P3 appends the seven.

--only scopes discovery to named slugs so adding seven people does not re-derive
the other fifty at all. It does NOT save the sitemap walk, which is the same
cost whatever is matched against; it scopes what gets WRITTEN.

These checks call the merge and selection helpers directly. No network, no
sitemaps, no quota.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
HS = ROOT / "scripts" / "fetch_happyscribe.py"

import fetch_happyscribe as F  # noqa: E402

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def cand(sid: str) -> dict:
    return {"source_id": sid, "url": f"https://example.invalid/{sid}", "title": sid}


def main() -> int:
    print("happy scribe discovery must merge, and must be scopable\n")

    print("[1] the helpers exist")
    check("merge_pool is importable", hasattr(F, "merge_pool"),
          "fetch_happyscribe.merge_pool is missing")
    check("select_roster is importable", hasattr(F, "select_roster"),
          "fetch_happyscribe.select_roster is missing")
    if not (hasattr(F, "merge_pool") and hasattr(F, "select_roster")):
        print(f"\n{passed} passed, {failed} failed")
        return 1

    print("\n[2] THE BUG: a thinner crawl must not shrink the pool")
    existing = {"leader-a": [cand("a1"), cand("a2")], "leader-b": [cand("b1")]}
    # A crawl that hit a transient failure and found only one of leader-a's two.
    found = {"leader-a": [cand("a1")], "leader-b": []}
    pool, rep = F.merge_pool(existing, found, replace=False)
    check("leader-a keeps both candidates",
          [c["source_id"] for c in pool["leader-a"]] == ["a1", "a2"],
          f"got {[c['source_id'] for c in pool['leader-a']]}; a candidate was "
          "dropped by a crawl that simply did not return it")
    check("leader-b keeps its candidate",
          [c["source_id"] for c in pool["leader-b"]] == ["b1"],
          f"got {pool['leader-b']}")
    check("kept candidates are reported, never silent",
          rep.get("candidates_kept_from_pool") == 2,
          f"got {rep.get('candidates_kept_from_pool')!r}")

    print("\n[3] genuinely new candidates are added")
    pool, rep = F.merge_pool(existing, {"leader-a": [cand("a3")]}, replace=False)
    check("the new candidate is appended",
          [c["source_id"] for c in pool["leader-a"]] == ["a1", "a2", "a3"],
          f"got {[c['source_id'] for c in pool['leader-a']]}")
    check("added candidates are counted", rep.get("candidates_added") == 1,
          f"got {rep.get('candidates_added')!r}")

    print("\n[4] a new leader is searched and recorded, empty list included")
    pool, _ = F.merge_pool(existing, {"cathie-wood": []}, replace=False)
    check("the new slug is present, so it counts as searched",
          "cathie-wood" in pool and pool["cathie-wood"] == [],
          f"got {pool.get('cathie-wood')!r}; an absent slug makes the loop "
          "re-run discovery every cycle for ever")
    check("the fifty are untouched", set(pool) == {"leader-a", "leader-b", "cathie-wood"})

    print("\n[5] --only scopes what is written, so fifty are not re-derived")
    roster = [{"slug": "leader-a", "name": "Leader A"},
              {"slug": "leader-b", "name": "Leader B"},
              {"slug": "cathie-wood", "name": "Cathie Wood"}]
    sel = F.select_roster(roster, ["cathie-wood"])
    check("only the named slug is selected",
          [p["slug"] for p in sel] == ["cathie-wood"], f"got {[p['slug'] for p in sel]}")
    check("no --only means the whole roster",
          [p["slug"] for p in F.select_roster(roster, None)] ==
          ["leader-a", "leader-b", "cathie-wood"])

    print("\n[6] an --only slug that is not on the roster fails loud")
    try:
        F.select_roster(roster, ["not-a-leader"])
        check("unknown slug raises", False, "it returned instead of raising; a typo "
              "would silently discover nothing and mark nothing searched")
    except SystemExit as e:
        check("unknown slug raises", True)
        check("the message names the slug", "not-a-leader" in str(e), f"got {e}")

    print("\n[7] replacing is possible, but explicit and it names what it drops")
    pool, rep = F.merge_pool(existing, {"leader-a": [cand("a1")]}, replace=True)
    check("the pool is exactly the crawl",
          [c["source_id"] for c in pool["leader-a"]] == ["a1"], f"got {pool}")
    dropped = rep.get("candidates_dropped_by_replace") or {}
    check("the dropped candidates are named, not counted",
          dropped.get("leader-a") == ["a2"], f"got {dropped!r}")
    # Replace must mean "replace what was crawled", not "replace the pool".
    # Otherwise `--replace-candidates --only cathie-wood` wipes the other fifty.
    check("a leader this crawl did not cover is NOT dropped",
          [c["source_id"] for c in pool["leader-b"]] == ["b1"]
          and "leader-b" not in dropped,
          f"got pool[leader-b]={pool.get('leader-b')} dropped={dropped!r}")

    print("\n[8] the CLI exposes --only and --replace-candidates")
    r = subprocess.run([sys.executable, str(HS), "--help"], capture_output=True, text=True)
    check("--only is a flag", "--only" in r.stdout, r.stdout[-400:])
    check("--replace-candidates is a flag", "--replace-candidates" in r.stdout,
          r.stdout[-400:])

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
