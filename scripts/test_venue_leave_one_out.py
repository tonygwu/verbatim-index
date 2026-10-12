#!/usr/bin/env python3
"""The leave-one-venue-out sensitivity that plan P5 requires, in both cases.

docs/PUNDITS-PLAN.md, P5 "Venue adjustment, only if the data support it": "In both
cases a leave-one-venue-out sensitivity is reported." Until 2026-10-12 nothing
computed it. aggregate.venue_leave_one_out() drops each format in turn, rescores
every ranked person with the board's own arithmetic, and reports what moved.

  FIXTURE     three people, six to seven blinded recordings each, rank floor 5:
                A  5 conversation at 60, 1 debate at 100   -> 66.7, rank 1
                B  6 reaction at 64                       -> 64.0, rank 2
                C  5 conversation at 50, 2 reaction at 74  -> 56.9, rank 3
  DEBATE      A falls to 60.0 and below B: two ranks change, Spearman 0.5,
              largest shift 6.7 points (A)
  REACTION    B has nothing left and drops below the floor; C falls to 50.0;
              two people remain, too few for a rank correlation
  CONVERSATION A and C fall below the floor; B alone remains, unmoved
  ABSENT      a venue no recording carries gets no entry
  OPEN ROWS   open-mode rows are ignored: the board ranks by the blinded score
  CONSISTENCY a person whose published score the rescoring cannot reproduce is
              refused, because the sensitivity would then measure the wrong board

No quota, no data.

  .venv/bin/python scripts/test_venue_leave_one_out.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def rows(A) -> list[dict]:
    spec = {"a": [("conversation", 60)] * 5 + [("debate", 100)],
            "b": [("reaction", 64)] * 6,
            "c": [("conversation", 50)] * 5 + [("reaction", 74)] * 2}
    out = []
    for slug, recs in spec.items():
        for i, (venue, v) in enumerate(recs):
            for mode in ("blinded", "open"):
                # Open rows carry a wildly different value, so counting them would show.
                val = v if mode == "blinded" else 5
                out.append({"leader_slug": slug, "source_id": f"{slug}-{i}", "mode": mode, "venue_type": venue,
                            "coverage": 1.0, **{f"cal_{d}": val for d in A.DIMS}})
    return out


def ranked() -> list[dict]:
    return [{"slug": "a", "rank": 1, "blinded": {"overall": 66.7}},
            {"slug": "b", "rank": 2, "blinded": {"overall": 64.0}},
            {"slug": "c", "rank": 3, "blinded": {"overall": 56.9}}]


def main() -> int:
    print("leave-one-venue-out sensitivity")
    try:
        import aggregate as A
        fn = A.venue_leave_one_out
    except Exception as exc:  # noqa: BLE001 - the missing function is the failure under test
        check("aggregate.venue_leave_one_out exists", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    out = fn(rows(A), ranked(), min_rank=5)
    by = out.get("by_venue", {})

    print("\n[DEBATE]")
    d = by.get("debate", {})
    check("1 recording dropped, from 1 person", d.get("recordings_dropped") == 1 and d.get("people_with_venue") == 1,
          str(d))
    check("all 3 people stay ranked", d.get("people_still_ranked") == 3 and d.get("people_below_floor") == [], str(d))
    check("A and B swap: 2 people change rank", d.get("people_changing_rank") == 2, str(d))
    check("Spearman against the full board is 0.5", d.get("rank_correlation") == 0.5, str(d))
    check("the largest shift is A's 6.7 points", d.get("max_abs_shift") == 6.7 and d.get("max_shift_slug") == "a",
          str(d))
    check("the mean absolute shift is 2.23", d.get("mean_abs_shift") == 2.23, str(d))

    print("\n[REACTION]")
    r = by.get("reaction", {})
    check("8 recordings dropped, from 2 people", r.get("recordings_dropped") == 8 and r.get("people_with_venue") == 2,
          str(r))
    check("B drops below the floor", r.get("people_below_floor") == ["b"] and r.get("people_still_ranked") == 2,
          str(r))
    check("two people are too few for a rank correlation", r.get("rank_correlation") is None, str(r))
    check("C's fall to 50.0 is the largest shift", r.get("max_abs_shift") == 6.9 and r.get("max_shift_slug") == "c",
          str(r))

    print("\n[CONVERSATION]")
    c = by.get("conversation", {})
    check("A and C fall below the floor", c.get("people_below_floor") == ["a", "c"], str(c))
    check("B alone remains, unmoved", c.get("people_still_ranked") == 1 and c.get("max_abs_shift") == 0.0, str(c))

    print("\n[ABSENT]")
    check("no entry for a venue no recording carries", "solo" not in by and sorted(by) == [
        "conversation", "debate", "reaction"], str(sorted(by)))

    print("\n[OPEN ROWS]")
    check("open rows did not enter: the full scores reproduce the blinded board", out.get("full_board_reproduced"),
          str(out.get("full_board_reproduced")))

    print("\n[CONSISTENCY]")
    bad = ranked()
    bad[2]["blinded"]["overall"] = 58.0
    try:
        fn(rows(A), bad, min_rank=5)
        refused = False
    except RuntimeError as exc:
        refused = "c" in str(exc) and "58.0" in str(exc)
    check("a score the rescoring cannot reproduce is refused, naming the person and the score", refused)

    print("\n[TIES]")
    # FOUND 2026-10-12 by review: with two judges a venue disagreement is a 1-1 tie,
    # and resolve_venue() then returns the alphabetically first label with
    # venue_agreed=False. That format is unknown, so the recording must not be
    # dropped as a recording of the label it happens to carry; it stays in every
    # run, like a recording with no venue, and is counted.
    #   A: 5 conversation at 60 and 1 disputed recording labelled "reaction" at 90 -> 65.0
    #   B: 6 reaction at 64 -> 64.0
    #   C: 5 conversation at 50 and 1 disputed recording labelled "debate" at 80 -> 55.0
    spec = {"a": [("conversation", True, 60)] * 5 + [("reaction", False, 90)],
            "b": [("reaction", True, 64)] * 6,
            "c": [("conversation", True, 50)] * 5 + [("debate", False, 80)]}
    tie_rows = []
    for slug, recs in spec.items():
        for i, (venue, agreed, v) in enumerate(recs):
            for mode in ("blinded", "open"):
                tie_rows.append({"leader_slug": slug, "source_id": f"{slug}-{i}", "mode": mode, "coverage": 1.0,
                                 "venue_type": venue, "venue_agreed": agreed, **{f"cal_{d}": v for d in A.DIMS}})
    tied = fn(tie_rows, [{"slug": "a", "rank": 1, "blinded": {"overall": 65.0}},
                         {"slug": "b", "rank": 2, "blinded": {"overall": 64.0}},
                         {"slug": "c", "rank": 3, "blinded": {"overall": 55.0}}], min_rank=5)
    check("a venue held only by a disputed recording gets no entry",
          sorted(tied.get("by_venue", {})) == ["conversation", "reaction"], str(sorted(tied.get("by_venue", {}))))
    check("the disputed recordings are counted", tied.get("recordings_venue_disputed") == 2, str(tied)[:300])
    r = tied.get("by_venue", {}).get("reaction", {})
    check("and stay in every run: dropping reaction removes B and leaves A at 65.0, unmoved",
          r.get("recordings_dropped") == 6 and r.get("people_below_floor") == ["b"]
          and r.get("max_abs_shift") == 0.0, str(r))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
