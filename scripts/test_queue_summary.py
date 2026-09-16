#!/usr/bin/env python3
"""The queued-calls line describes the QUEUE, not the directory it was drawn from.

FOUND 2026-09-16 on the P8a2 top-up run, which printed:

    128 grading calls queued (114 transcripts x 2 judges x 2 modes x 1 repeats)

128 is right and the factorisation is not: 114 x 2 x 2 x 1 is 456. The schedule
narrowed the run to 32 transcripts and the line kept reporting how many files
sat in --transcripts. A reader checking the arithmetic concludes the queue is
wrong, or worse, believes 114 recordings are about to be graded. This is the
repo's own rule arriving in a log line: derive the number from what is present,
never restate a count taken somewhere else.

  MULTIPLIES   the factors multiply out to the call count
  NARROWED     a schedule that selects a subset reports the subset
  DERIVED      the transcript count comes from the jobs, not from a passed-in list

  .venv/bin/python scripts/test_queue_summary.py
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
    spec = importlib.util.spec_from_file_location("grade_qs", REPO / "scripts" / "grade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def job(slug: str, sid: str, judge: str, mode: str, run: int = 0) -> dict:
    return {"rec": {"leader_slug": slug, "source_id": sid}, "judge": judge, "mode": mode, "run": run}


def main() -> int:
    print("queue summary")
    G = load()
    if not hasattr(G, "queue_summary"):
        check("grade.py exposes queue_summary", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    # 3 transcripts x 2 judges x 2 modes x 1 run = 12 calls.
    jobs = [job(f"p{i}", f"s{i}", j, m)
            for i in range(3) for j in ("fable", "gemini") for m in ("blinded", "open")]

    print("\n[MULTIPLIES]")
    line = G.queue_summary(jobs)
    check("the line reports the real call count", line.startswith("12 grading calls queued"), line)
    for token, want in (("3 transcripts", True), ("2 judges", True), ("2 modes", True), ("1 run", True)):
        check(f"the line names {token}", (token in line) is want, line)

    print("\n[NARROWED]")
    # A schedule picked 2 of the 3; the line must say 2, whatever sits on disk.
    narrowed = [j for j in jobs if j["rec"]["leader_slug"] != "p2"]
    line2 = G.queue_summary(narrowed)
    check("a narrowed queue reports its own transcript count, not the directory's",
          line2.startswith("8 grading calls queued") and "2 transcripts" in line2, line2)

    print("\n[DERIVED]")
    # An uneven queue cannot be written as a clean product, and must not pretend.
    uneven = jobs + [job("p9", "s9", "fable", "blinded")]
    line3 = G.queue_summary(uneven)
    check("an uneven queue reports the count without inventing a factorisation",
          line3.startswith("13 grading calls queued") and "x" not in line3.split("(")[-1],
          line3)
    check("and it still names how many transcripts and judges are involved",
          "4 transcripts" in line3 and "fable" in line3, line3)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
