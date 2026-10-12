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
        # P9 schedules from two reports: the pilot's (logs/pilot) and the rest of
        # the roster's (logs/p6b). FOUND 2026-10-12: --verified took one file, so
        # the full run could only have scheduled one of the two verified sets.
        with tempfile.TemporaryDirectory(prefix="ver3-") as td:
            r1, r2 = Path(td) / "pilot.json", Path(td) / "p6b.json"
            r1.write_text(json.dumps({"people": {"a": {"selected_keys": ["a/s0"]}}}))
            r2.write_text(json.dumps({"people": {"c": {"selected_keys": ["c/s4", "c/s5"]}}}))
            union = getattr(S, "verified_union", None)
            check("several reports are read as the union of their verified sets",
                  union is not None and union([r1, r2]) == {("a", "s0"), ("c", "s4"), ("c", "s5")},
                  "verified_union missing" if union is None else str(union([r1, r2])))
            import subprocess
            h = subprocess.run([sys.executable, Path(__file__).resolve().parent / "schedule.py", "build", "--help"],
                               capture_output=True, text=True).stdout
            check("the CLI's --verified takes more than one report", "--verified VERIFIED [VERIFIED ...]" in h,
                  h[h.find("--verified"):][:120])

    print("\n[ANCHORS IN A TOP-UP]")
    # P9 is a top-up: the pilot's complete recordings are reused, and the drift
    # anchors are, by design, fixed recordings that are already graded. FOUND
    # 2026-10-12 in a dry run of the P9 command: build_schedule refused every
    # anchor as "not in the schedule's transcripts", because the top-up had
    # (correctly) left complete recordings out. So P9 could not schedule anchors.
    leans = {"a": "left", "b": "right"}
    new_items = [("a", "s5"), ("b", "s6")]
    try:
        e = S.build_schedule(new_items, leans, ["fable", "gemini"], block_size=1, seed=1,
                             anchors=[("a", "s0")], anchor_every=1, anchor_pool={("a", "s0")})
        runs = sorted({x["run"] for x in e if (x["slug"], x["source_id"]) == ("a", "s0")})
        check("an already-complete recording can be a drift anchor in a top-up", runs == [1, 2], str(runs))
        check("and it is re-graded only, never re-scheduled at run 0",
              not any(x["run"] == 0 and (x["slug"], x["source_id"]) == ("a", "s0") for x in e))
    except TypeError as exc:
        check("build_schedule takes an anchor_pool", False, repr(exc))
    for pool, label in ((None, "with no pool, an anchor outside the schedule is still refused (typo guard)"),
                        ({("b", "s9")}, "an anchor neither scheduled nor in the pool is refused")):
        try:
            S.build_schedule(new_items, leans, ["fable"], block_size=1, seed=1, anchors=[("a", "s0")],
                             anchor_every=1, **({} if pool is None else {"anchor_pool": pool}))
            refused = False
        except RuntimeError:
            refused = True
        except TypeError:
            refused = False
        check(label, refused)

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
