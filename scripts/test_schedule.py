#!/usr/bin/env python3
"""The grading schedule: seeded blocks, leans mixed, modes interleaved, anchors for drift.

Pundits plan, P5. grade.py builds its queue from a sorted product and orders it
breadth-first, which is right for leaders but leaves two confounds the pundits
plan forbids: a quota stop or a judge's drift can line up with lean if people
are graded lean by lean, and with mode if every blinded call runs before every
open one. scripts/schedule.py writes a seeded manifest and `grade.py --schedule`
runs jobs in exactly that order.

  SEEDED       the same seed rebuilds the same manifest; a different seed differs
  INTERLEAVED  each (transcript, judge) runs both modes back to back, inside one
               block, and which mode goes first is a coin, roughly even overall
  BLOCKS       a block holds at most block_size transcripts, and every block of
               a balanced corpus contains every lean
  PRIVATE      no manifest entry carries a lean label
  UNLABELLED   a person with no lean label is refused, never guessed
  ANCHORS      each anchor transcript is re-graded in both modes by every judge
               once per block group, as run 1, 2, ...
  GRADE-ORDER  grade.order_by_schedule returns jobs in manifest order and refuses
               an entry with no job or a duplicated entry
  MANIFEST     read_manifest refuses a duplicate entry or a missing field

No quota.

  .venv/bin/python scripts/test_schedule.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
JUDGES = ["fable", "astra", "gemini"]


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def corpus() -> tuple[list[tuple[str, str]], dict[str, str]]:
    leans = {}
    items = []
    for lean in ("left", "right", "heterodox"):
        for p in range(4):
            slug = f"{lean}-{p}"
            leans[slug] = lean
            items += [(slug, f"s{t}") for t in range(5)]
    return items, leans


def refuses(fn, *exc) -> bool:
    try:
        fn()
    except exc or (RuntimeError, ValueError, SystemExit):
        return True
    return False


def main() -> int:
    print("grading schedule")
    try:
        import schedule as S
    except Exception as exc:
        check("schedule is importable", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    items, leans = corpus()

    print("\n[SEEDED]")
    a = S.build_schedule(items, leans, JUDGES, block_size=20, seed=1)
    b = S.build_schedule(items, leans, JUDGES, block_size=20, seed=1)
    c = S.build_schedule(items, leans, JUDGES, block_size=20, seed=2)
    check("the same seed rebuilds the same manifest", a == b)
    check("a different seed gives a different order", a != c)
    check("every transcript x judge x mode appears exactly once",
          len(a) == len(items) * len(JUDGES) * 2
          and len({(e["slug"], e["source_id"], e["judge"], e["mode"], e["run"]) for e in a}) == len(a))

    print("\n[INTERLEAVED]")
    adjacent = all(a[i]["slug"] == a[i + 1]["slug"] and a[i]["source_id"] == a[i + 1]["source_id"]
                   and a[i]["judge"] == a[i + 1]["judge"] and a[i]["block"] == a[i + 1]["block"]
                   and {a[i]["mode"], a[i + 1]["mode"]} == {"blinded", "open"}
                   for i in range(0, len(a), 2))
    check("each (transcript, judge) runs both modes back to back in one block", adjacent)
    firsts = Counter(a[i]["mode"] for i in range(0, len(a), 2))
    share = firsts["blinded"] / sum(firsts.values())
    check("which mode goes first is roughly even (35-65% blinded-first)", 0.35 <= share <= 0.65, str(firsts))
    check("the blinded pass does not all come first", any(a[i]["mode"] == "open" for i in range(0, len(a) // 2, 2)))

    print("\n[BLOCKS]")
    per_block = defaultdict(set)
    per_block_lean = defaultdict(set)
    for e in a:
        per_block[e["block"]].add((e["slug"], e["source_id"]))
        per_block_lean[e["block"]].add(leans[e["slug"]])
    check("no block holds more than block_size transcripts", max(len(v) for v in per_block.values()) <= 20,
          str({k: len(v) for k, v in per_block.items()}))
    full = [k for k, v in per_block.items() if len(v) == 20]
    check("every full block contains every lean", bool(full) and all(per_block_lean[k] == {"left", "right", "heterodox"}
                                                                     for k in full), str(dict(per_block_lean)))

    print("\n[PRIVATE]")
    check("no entry carries a lean label", all("lean" not in e and set(leans.values()).isdisjoint(set(map(str, e.values())))
                                               for e in a))

    print("\n[UNLABELLED]")
    check("a person with no lean label is refused",
          refuses(lambda: S.build_schedule(items + [("nobody", "s0")], leans, JUDGES, block_size=20, seed=1),
                  RuntimeError, ValueError, SystemExit))

    print("\n[ANCHORS]")
    anchors = [("left-0", "s0"), ("right-1", "s2")]
    d = S.build_schedule(items, leans, JUDGES, block_size=20, seed=1, anchors=anchors, anchor_every=1)
    groups = max(e["block"] for e in d if e["run"] == 0) + 1
    anchor_entries = [e for e in d if e["run"] > 0]
    check("each anchor is re-graded once per block group, in both modes, by every judge",
          len(anchor_entries) == len(anchors) * groups * len(JUDGES) * 2, f"{len(anchor_entries)} vs groups {groups}")
    runs = {(e["slug"], e["source_id"], e["run"]) for e in anchor_entries}
    check("anchor runs are numbered 1..groups", {r for _, _, r in runs} == set(range(1, groups + 1)), str(sorted(runs)))
    check("anchors never collide with a run-0 job",
          len({(e["slug"], e["source_id"], e["judge"], e["mode"], e["run"]) for e in d}) == len(d))

    print("\n[MANIFEST]")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "m.jsonl"
        S.write_manifest(path, a)
        check("a written manifest reads back identically", S.read_manifest(path) == a)
        path.write_text(path.read_text() + json.dumps(a[0]) + "\n")
        check("a duplicate entry is refused", refuses(lambda: S.read_manifest(path), RuntimeError, ValueError, SystemExit))
        bad = dict(a[0])
        del bad["judge"]
        path.write_text(json.dumps(bad) + "\n")
        check("an entry with a missing field is refused", refuses(lambda: S.read_manifest(path), RuntimeError, ValueError, SystemExit))

    print("\n[GRADE-ORDER]")
    spec = importlib.util.spec_from_file_location("grade_sched", REPO / "scripts" / "grade.py")
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    if not hasattr(G, "order_by_schedule"):
        check("grade.py exposes order_by_schedule", False)
    else:
        jobs = [{"rec": {"leader_slug": e["slug"], "source_id": e["source_id"]}, "judge": e["judge"],
                 "mode": e["mode"], "run": e["run"]} for e in reversed(a)]
        ordered = G.order_by_schedule(jobs, a)
        check("jobs come back in manifest order",
              [(j["rec"]["leader_slug"], j["rec"]["source_id"], j["judge"], j["mode"]) for j in ordered]
              == [(e["slug"], e["source_id"], e["judge"], e["mode"]) for e in a])
        extra = a + [{**a[0], "source_id": "missing-transcript"}]
        check("an entry with no matching job is refused",
              refuses(lambda: G.order_by_schedule(jobs, extra), RuntimeError, ValueError, SystemExit))
        check("a job the manifest does not name is refused, not run unscheduled",
              refuses(lambda: G.order_by_schedule(jobs, a[:-1]), RuntimeError, ValueError, SystemExit))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
