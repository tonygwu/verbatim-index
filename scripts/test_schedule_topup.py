#!/usr/bin/env python3
"""A top-up schedule brings each person to a target count, and repairs before it adds.

Pundits plan, P8a -> P8a2. The first pilot graded 2 recordings per person, and
the rank floor MIN_TRANSCRIPTS_TO_RANK is 5, so nobody could be ranked. The
second batch has to ask a different question from the first: not "grade N more"
but "bring each person UP TO N complete recordings". Those are not the same
instruction, and the difference is exactly one recording per person, which is
the difference between a ranked board and another unranked one.

Two recordings also sit at a PARTIAL panel, each missing one cell that failed
the 25-word quote cap. Repairing a partial is nearly free, because the other
three cells of that recording are already scored and reuse their cache, so a
partial is always worth more than a new recording and is scheduled first.

  TARGET      each person is scheduled up to `target` complete recordings, no more
  REPAIR      a partial recording is scheduled before any new one
  COMPLETE    a recording with every cell already scored is never rescheduled
  SHORTFALL   a person without enough material is reported, never silently short
  SEEDED      the same seed picks the same recordings

  .venv/bin/python scripts/test_schedule_topup.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("sched_topup", REPO / "scripts" / "schedule.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("schedule top-up")
    S = load()
    if not hasattr(S, "select_topup"):
        check("schedule.py exposes select_topup", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    # Six recordings each for two people; "a" has 2 complete, "b" has 1 complete
    # and 1 partial. Target 5.
    items = [(p, f"s{i}") for p in ("a", "b") for i in range(6)]
    complete = {("a", "s0"), ("a", "s1"), ("b", "s0")}
    partial = {("b", "s1")}

    print("\n[TARGET]")
    picked, short = S.select_topup(items, complete, partial, target=5, seed=7)
    by = {p: [sid for slug, sid in picked if slug == p] for p in ("a", "b")}
    check("a person at 2 complete is scheduled 3 more, reaching the target of 5",
          len(by["a"]) == 3, f"a got {by['a']}")
    check("a person at 1 complete plus 1 partial is scheduled 4, also reaching 5",
          len(by["b"]) == 4, f"b got {by['b']}")
    check("no shortfall is reported when there is enough material", short == {}, str(short))

    print("\n[REPAIR]")
    check("the partial recording is scheduled",
          ("b", "s1") in picked, str(sorted(picked)))
    check("the partial is scheduled FIRST for its person, before any new recording",
          by["b"][0] == "s1", f"b order {by['b']}")

    print("\n[COMPLETE]")
    check("a recording whose every cell is already scored is never rescheduled",
          not (set(picked) & complete), str(sorted(set(picked) & complete)))

    print("\n[SHORTFALL]")
    # "c" has only 3 recordings in total and none graded, against a target of 5.
    thin = [("c", f"s{i}") for i in range(3)]
    picked2, short2 = S.select_topup(thin, set(), set(), target=5, seed=7)
    check("a person short of material gets everything available",
          len(picked2) == 3, str(picked2))
    check("and the shortfall is REPORTED rather than passing as a full top-up",
          short2 == {"c": 2}, str(short2))

    print("\n[SEEDED]")
    again, _ = S.select_topup(items, complete, partial, target=5, seed=7)
    other, _ = S.select_topup(items, complete, partial, target=5, seed=8)
    check("the same seed picks the same recordings", picked == again)
    check("a different seed picks a different set, so the choice is really random",
          set(picked) != set(other), f"{sorted(picked)} vs {sorted(other)}")

    print("\n[VERIFIED]")
    # data-pundits/transcripts_blind holds 114 recordings and only 89 are
    # speaker-verified, so a scheduler that reads the DIRECTORY schedules 25
    # recordings no person ever checked. That is the wrong-person class the
    # leaders board paid 44 recordings for, arriving through a new door.
    if not hasattr(S, "verified_keys"):
        check("schedule.py exposes verified_keys", False)
    else:
        import json
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ver-") as td:
            rp = Path(td) / "report.json"
            rp.write_text(json.dumps({"people": {
                "a": {"selected_keys": ["a/s0", "a/s2"]},
                "b": {"selected_keys": ["b/s1"]}}}))
            keys = S.verified_keys(rp)
            check("the verified set is read as (slug, source_id) pairs",
                  keys == {("a", "s0"), ("a", "s2"), ("b", "s1")}, str(sorted(keys)))
            check("a recording absent from the report is not verified",
                  ("a", "s1") not in keys)
    if hasattr(S, "verified_keys"):
        import json
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ver2-") as td:
            rp = Path(td) / "empty.json"
            rp.write_text(json.dumps({"people": {"a": {"selected_keys": []}}}))
            try:
                S.verified_keys(rp)
                refused = False
            except RuntimeError as exc:
                refused = "verified" in str(exc).lower()
            check("a report naming no verified recording is refused, not read as 'allow nothing'",
                  refused)

    print("\n[SCAN]")
    if not hasattr(S, "scan_panels"):
        check("schedule.py exposes scan_panels", False)
    else:
        import json
        import tempfile
        with tempfile.TemporaryDirectory(prefix="topup-") as td:
            g = Path(td)
            def write(slug, sid, judge, mode, errors=None, dims=True):
                rec = {"leader_slug": slug, "source_id": sid, "judge": judge, "mode": mode,
                       "validation_errors": errors or [],
                       "grade": {"dimensions": {"d1": {"score": 50}}} if dims else {}}
                p = g / judge / slug
                p.mkdir(parents=True, exist_ok=True)
                (p / f"{sid}__{judge}__{mode}__r0.json").write_text(json.dumps(rec))
            for j in ("fable", "gemini"):
                for m in ("blinded", "open"):
                    write("a", "s0", j, m)
            write("b", "s1", "fable", "blinded")
            write("b", "s1", "fable", "open")
            write("b", "s1", "gemini", "open")
            write("b", "s1", "gemini", "blinded", errors=["quote exceeds 25 words"])
            comp, part = S.scan_panels(g, ["fable", "gemini"])
            check("a recording with every cell scored reads as complete",
                  comp == {("a", "s0")}, str(comp))
            check("a recording whose only gap is an INVALID record reads as partial, not complete",
                  part == {("b", "s1")}, str(part))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
