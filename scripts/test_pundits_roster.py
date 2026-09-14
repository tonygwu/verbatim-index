#!/usr/bin/env python3
"""The pundits roster and its private lean labels are checked in full, and fail loudly.

Pundits plan, P6. scripts/pundits_roster.py checks every field the pipeline
reads, keeps lean labels out of the roster, and requires a cited outside source
and a balanced split for the labels.

  VALID        a well-formed three-person roster with labels passes
  FIELDS       a missing string, list or archival flag is named
  COMPANY      `company` must equal `show` or `outlet`
  CHANNELS     an own channel without a verification note, or off YouTube, fails
  ARCHIVAL     an archival subject without a last recording date fails
  PRIVATE      a lean field inside a roster entry fails
  LABELS       an unlabelled person, a stray label, an unknown lean, and an
               uncited label each fail
  BALANCE      groups differing by more than max_imbalance fail
  DUPLICATE    a repeated slug fails

No quota.

  .venv/bin/python scripts/test_pundits_roster.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def person(slug: str, archival: bool = False) -> dict:
    p = {"slug": slug, "name": slug.replace("-", " ").title(), "role": "podcast host",
         "company": "The Show", "show": "The Show", "outlet": "YouTube", "handles": [],
         "own_channels": [{"url": f"https://www.youtube.com/@{slug}", "channel_name": slug,
                           "verified_by": "channel About page links the official site"}],
         "identity_tokens": ["The Show", "co-host"], "archival": archival}
    if archival:
        p["last_recording_date"] = "2025-09-09"
    return p


def fixture():
    roster = [person("a-left"), person("b-right", archival=True), person("c-het")]
    leans = {"a-left": "left", "b-right": "right", "c-het": "heterodox"}
    sources = {s: [{"url": "https://en.wikipedia.org/wiki/X", "quote": "a commentator"}] for s in leans}
    return roster, leans, sources


def has(errors: list[str], needle: str) -> bool:
    return any(needle in e for e in errors)


def main() -> int:
    print("pundits roster")
    import pundits_roster as R

    roster, leans, sources = fixture()
    print("\n[VALID]")
    errs = R.roster_errors(roster) + R.label_errors(roster, leans, sources)
    check("a well-formed roster with labels passes", errs == [], str(errs))

    print("\n[FIELDS]")
    for field in ("name", "show", "handles", "identity_tokens", "archival"):
        r = copy.deepcopy(roster)
        del r[0][field]
        check(f"a missing `{field}` is named", has(R.roster_errors(r), f"`{field}`"), str(R.roster_errors(r)))
    r = copy.deepcopy(roster)
    r[0]["identity_tokens"] = ["only one"]
    check("fewer than 2 identity tokens fails", has(R.roster_errors(r), "identity_tokens"))

    print("\n[COMPANY]")
    r = copy.deepcopy(roster)
    r[0]["company"] = "Something Else"
    check("`company` that is neither show nor outlet fails", has(R.roster_errors(r), "`company`"))

    print("\n[CHANNELS]")
    r = copy.deepcopy(roster)
    del r[0]["own_channels"][0]["verified_by"]
    check("an own channel without a verification note fails", has(R.roster_errors(r), "verified_by"))
    r = copy.deepcopy(roster)
    r[0]["own_channels"][0]["url"] = "https://www.twitch.tv/x"
    check("an own channel off YouTube fails", has(R.roster_errors(r), "youtube"))
    r = copy.deepcopy(roster)
    r[0]["own_channels"] = []
    check("an empty own-channel list is allowed and counted, not guessed", R.roster_errors(r) == [])

    print("\n[ARCHIVAL]")
    r = copy.deepcopy(roster)
    del r[1]["last_recording_date"]
    check("an archival subject without a last recording date fails", has(R.roster_errors(r), "last_recording_date"))

    print("\n[PRIVATE]")
    r = copy.deepcopy(roster)
    r[2]["lean"] = "heterodox"
    check("a lean field inside the roster fails", has(R.roster_errors(r), "private lean"))

    print("\n[LABELS]")
    l2 = dict(leans)
    del l2["c-het"]
    check("an unlabelled person fails", has(R.label_errors(roster, l2, sources), "no lean label"))
    l2 = {**leans, "ghost": "left"}
    check("a label for someone not on the roster fails", has(R.label_errors(roster, l2, {**sources, "ghost": sources["a-left"]}), "not on the roster"))
    l2 = {**leans, "c-het": "centre"}
    check("an unknown lean fails", has(R.label_errors(roster, l2, sources), "not one of"))
    s2 = {**sources, "a-left": [{"url": "https://x", "quote": ""}]}
    check("a label without a quoted source fails", has(R.label_errors(roster, leans, s2), "outside source"))

    print("\n[BALANCE]")
    big = roster + [person(f"l{i}") for i in range(3)]
    lb = {**leans, **{f"l{i}": "left" for i in range(3)}}
    sb = {**sources, **{f"l{i}": sources["a-left"] for i in range(3)}}
    check("groups 4/1/1 fail the default imbalance of 2", has(R.label_errors(big, lb, sb), "unbalanced"))
    check("the same groups pass when the allowed imbalance is 3", not has(R.label_errors(big, lb, sb, 3), "unbalanced"))

    print("\n[DUPLICATE]")
    r = copy.deepcopy(roster) + [person("a-left")]
    check("a repeated slug fails", has(R.roster_errors(r), "appears 2 times"))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
