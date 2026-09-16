#!/usr/bin/env python3
"""The venue adjustment runs only when the plan's support rule passes, and then on BOTH modes.

FOUND by adversarial audit 2026-09-16, two defects in one place.

docs/PUNDITS-PLAN.md, "Venue adjustment, only if the data support it": it "needs
every venue type to have n >= MIN_VENUE_N and to appear for at least 3 people,
and 80% of people to have at least 2 venue types. Otherwise the board publishes
unadjusted scores and says why." That rule was written in the plan and
implemented nowhere. On the P8a2 board two of its three conditions failed and
the adjustment was applied anyway.

Separately, the adjustment was fitted AND applied to blinded rows only, so
`leaders[].blinded` carried it and `leaders[].open` did not. Subtracting the two
published columns then mostly recovered the format effect: Ezra Klein's five
recordings are all conversations and his open-minus-blinded read +4.8 on good
faith, which is the conversation effect (4.822) to the digit, where the true
difference is 0.0. Two people had the sign reversed.

Fitting on open would be noise, which is why the fit stays blinded-only. APPLYING
the blinded-fitted effect to open rows is what makes the two comparable, and it
cancels in the halo because both sides of a matched pair move together.

  GATE-N       a venue below MIN_VENUE_N fails the rule
  GATE-PEOPLE  a venue carried by fewer than 3 people fails the rule
  GATE-MIX     fewer than 80% of people with 2+ venue types fails the rule
  GATE-PASS    a corpus meeting all three passes
  BOTH-MODES   when it passes, blinded and open are adjusted with the same effects
  HALO-SAFE    the adjustment cancels in a matched pair, so halo does not move

  .venv/bin/python scripts/test_venue_support_rule.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("agg_vsr", REPO / "scripts" / "aggregate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rows(spec: dict[str, list[str]]) -> list[dict]:
    """spec: {person: [venue per recording]} -> transcript rows."""
    out = []
    for person, venues in spec.items():
        for i, v in enumerate(venues):
            out.append({"leader_slug": person, "source_id": f"{person}-s{i}",
                        "venue_type": v, "venue_agreed": True, "cal_x": 50.0})
    return out


def main() -> int:
    print("venue support rule")
    A = load()
    if not hasattr(A, "venue_support"):
        check("aggregate.py exposes venue_support", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    # Four people, two venues, 8 of each, everyone mixed: the rule passes.
    good = {f"p{i}": ["conversation"] * 2 + ["reaction"] * 2 for i in range(4)}

    print("\n[GATE-PASS]")
    ok, why = A.venue_support(rows(good), min_n=8)
    check("a corpus meeting all three conditions passes", ok, str(why))

    print("\n[GATE-N]")
    thin = dict(good); thin["p0"] = ["conversation"] * 2 + ["reaction"] * 2 + ["debate"] * 3
    ok, why = A.venue_support(rows(thin), min_n=8)
    check("a venue below MIN_VENUE_N fails the rule", not ok, str(why))
    check("and the reason names the venue and the count",
          any("debate" in r for r in why), str(why))

    print("\n[GATE-PEOPLE]")
    # 'debate' reaches 8 rows but sits on only 2 people.
    few = {f"p{i}": ["conversation"] * 2 + ["reaction"] * 2 for i in range(4)}
    few["p0"] = few["p0"] + ["debate"] * 4
    few["p1"] = few["p1"] + ["debate"] * 4
    ok, why = A.venue_support(rows(few), min_n=8)
    check("a venue carried by fewer than 3 people fails the rule", not ok, str(why))
    check("and the reason says how many people carry it",
          any("debate" in r and "people" in r for r in why), str(why))

    print("\n[GATE-MIX]")
    # 8 people, 6 of them single-venue: 25% mixed, below the 80% requirement.
    lop = {f"c{i}": ["conversation"] * 4 for i in range(3)}
    lop.update({f"r{i}": ["reaction"] * 4 for i in range(3)})
    lop.update({f"m{i}": ["conversation"] * 2 + ["reaction"] * 2 for i in range(2)})
    ok, why = A.venue_support(rows(lop), min_n=8)
    check("fewer than 80% of people with two venue types fails the rule", not ok, str(why))
    check("and the reason gives the share", any("%" in r for r in why), str(why))

    print("\n[BOTH-MODES]")
    # A fitted effect must be applied to open rows as well as blinded ones.
    blinded = [dict(r, mode="blinded", cal_x=60.0) for r in rows(good)]
    open_ = [dict(r, mode="open", cal_x=60.0) for r in rows(good)]
    fit = {"conversation": 3.0, "reaction": -3.0}
    A.apply_venue_adjustment(blinded, fit, field="cal_x")
    A.apply_venue_adjustment(open_, fit, field="cal_x")
    conv_b = [r["cal_x_venue_adj"] for r in blinded if r["venue_type"] == "conversation"][0]
    conv_o = [r["cal_x_venue_adj"] for r in open_ if r["venue_type"] == "conversation"][0]
    check("the same effect applies to a blinded and an open row of the same format",
          conv_b == conv_o == 57.0, f"blinded={conv_b} open={conv_o}")

    print("\n[HALO-SAFE]")
    # open minus blinded on a matched pair is unchanged by the adjustment.
    pairs_before = 62.0 - 60.0
    b = dict(rows(good)[0], mode="blinded", cal_x=60.0)
    o = dict(rows(good)[0], mode="open", cal_x=62.0)
    A.apply_venue_adjustment([b], fit, field="cal_x")
    A.apply_venue_adjustment([o], fit, field="cal_x")
    check("the format adjustment cancels in a matched pair",
          round(o["cal_x_venue_adj"] - b["cal_x_venue_adj"], 6) == pairs_before,
          f"{o['cal_x_venue_adj']} - {b['cal_x_venue_adj']}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
