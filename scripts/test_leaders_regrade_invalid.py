#!/usr/bin/env python3
"""Leaders (contract v1): `--regrade-invalid` grades a malformed stored record again.

WHY THIS EXISTS. A leaders grade.py job skipped any transcript whose grade file
existed, so a record that FAILED VALIDATION was a permanent hole in that judge's
column. Counted in the shared leaders data on 2026-10-11: 35 records failed
validation while still carrying an attempt at scores (26 with `dimensions`, 9
with a judge-invented shape holding `overall`). Pundits (contract v2) already
re-grades such a record by default. For leaders it is OPT-IN, because turning it
on by default would make repo-0's grading daemon spend quota re-grading those
cells and move the published board on its next code pull, a decision for the
operator and the daemon owner, not for a code change.

A refusal is never re-graded, flag or not. AGENTS.md: a refusal is retried three
times inside the call and then kept, and a refused record carries no scores.

  DEFAULT    without the flag, a malformed record is still a cache hit.
  REGRADE    with the flag, a malformed record is moved under _obsolete/ and the
             judge is called again.
  REFUSAL    with the flag, a refusal ({reason, status} or {error}) or a
             qualitative non-answer stays a cache hit and the judge is not called.
  VALID      with the flag, a valid record stays a cache hit.
  QUEUE      with the flag, a malformed record counts as pending work, so the
             queue's depth ordering and its "not yet on disk" count include it.
  CLI        --regrade-invalid exists and defaults to off.

No quota: the judge call is replaced by a stub.

  .venv/bin/python scripts/test_leaders_regrade_invalid.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []

REC = {"leader_slug": "ada-lovelace", "source_id": "s1", "text": "words " * 50, "word_count": 50}


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load_grade():
    spec = importlib.util.spec_from_file_location("grade_regrade", REPO / "scripts" / "grade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SCORED_INVALID = {"leader_slug": "ada-lovelace", "source_id": "s1", "judge": "fable", "mode": "blinded",
                  "validation_errors": ["d2_insight quote exceeds 25 words"],
                  "grade": {"dimensions": {"d1_clarity": {"score": 60}}, "overall": 60.0}}
INVENTED_SHAPE = {**SCORED_INVALID, "validation_errors": ["dimensions missing"],
                  "grade": {"D1": 60, "D2": 55, "D3": 50, "overall": 55.0}}
REFUSAL = {**SCORED_INVALID, "validation_errors": ["dimensions missing"],
           "grade": {"reason": "content policy", "status": "refused", "transcript_id": "ada-lovelace/s1"}}
ERROR = {**SCORED_INVALID, "validation_errors": ["dimensions missing"],
         "grade": {"error": "I can't score this.", "transcript_id": "ada-lovelace/s1"}}
QUALITATIVE = {**SCORED_INVALID, "validation_errors": ["dimensions missing"],
               "grade": {"limitation": "x", "qualitative_observations": "y", "schema_version": "1.0"}}
VALID = {**SCORED_INVALID, "validation_errors": [],
         "grade": {"dimensions": {"d1_clarity": {"score": 60}}, "overall": 60.0}}


def make_job(root: Path, record: dict | None, flag: bool) -> dict:
    dest = root / "grades" / "fable" / "ada-lovelace" / "s1__fable__blinded__r0.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if record is not None:
        dest.write_text(json.dumps(record))
    return {"rec": dict(REC), "judge": "fable", "mode": "blinded", "run": 0, "force": False,
            "regrade_invalid": flag, "rubric": "R", "schema": {}, "timeout": 5,
            "config_dir": None, "fable_bin": "claude", "workdir": str(root / "wd"),
            "dest": str(dest), "raw_dest": str(root / "grades" / "_raw" / "fable" / "ada-lovelace" / "s1.txt"),
            "obsolete_root": str(root / "grades" / "_obsolete")}


def main() -> int:
    print("leaders --regrade-invalid")
    G = load_grade()
    calls: list[str] = []

    def stub_fable(prompt, *a, **k):
        calls.append(prompt)
        raise RuntimeError("stub judge: no quota spent in this test")

    G.call_fable = stub_fable
    G.build_judge_prompt = lambda rec, mode, rubric, schema: "PROMPT"

    def run(record, flag):
        root = Path(tempfile.mkdtemp())
        job = make_job(root, record, flag)
        before = Path(job["dest"]).read_bytes() if record is not None else None
        n = len(calls)
        r = G.grade_one(job)
        aside = sorted(Path(job["obsolete_root"]).rglob("*.json")) if Path(job["obsolete_root"]).exists() else []
        return r, len(calls) - n, Path(job["dest"]), before, aside, job

    print("\nDEFAULT")
    r, called, dest, before, aside, _ = run(SCORED_INVALID, False)
    check("without the flag a malformed record is still a cache hit",
          r.get("status") == "cached" and called == 0 and dest.read_bytes() == before, str(r))

    print("\nREGRADE")
    for label, rec in (("a malformed record with dimensions", SCORED_INVALID),
                       ("a record in a judge-invented shape", INVENTED_SHAPE)):
        r, called, dest, before, aside, _ = run(rec, True)
        check(f"with the flag, {label} goes to the judge again", r.get("status") != "cached" and called == 1, str(r))
        check(f"and is moved under _obsolete/ first, byte for byte",
              len(aside) == 1 and aside[0].read_bytes() == before and not dest.exists(), str(aside))

    print("\nREFUSAL / VALID")
    for label, rec in (("a refusal", REFUSAL), ("an error-shaped refusal", ERROR),
                       ("a qualitative non-answer", QUALITATIVE), ("a valid record", VALID)):
        r, called, dest, before, aside, _ = run(rec, True)
        check(f"with the flag, {label} stays a cache hit",
              r.get("status") == "cached" and called == 0 and dest.read_bytes() == before and not aside, str(r))

    print("\nQUEUE")
    root = Path(tempfile.mkdtemp())
    bad = make_job(root / "a", SCORED_INVALID, True)
    good = make_job(root / "b", VALID, True)
    refused = make_job(root / "c", REFUSAL, True)
    off = make_job(root / "d", SCORED_INVALID, False)
    pending = getattr(G, "job_pending", None)
    if pending is None:
        check("grade.py exposes job_pending", False)
    else:
        check("with the flag a malformed record is pending work", pending(bad) is True)
        check("a valid record is not", pending(good) is False)
        check("a refusal is not", pending(refused) is False)
        check("without the flag a malformed record is not", pending(off) is False)
        order = G.order_breadth_first([bad, good])
        check("the queue resolves the cached record first and schedules the malformed one as work",
              order == [good, bad], str([o["dest"] for o in order]))

    print("\nCLI")
    src = (REPO / "scripts" / "grade.py").read_text()
    check("--regrade-invalid is a store_true flag, off by default",
          'add_argument("--regrade-invalid", action="store_true"' in src)
    check("grade_loop.sh does not pass it, so the daemon's behaviour is unchanged",
          "--regrade-invalid" not in (REPO / "scripts" / "grade_loop.sh").read_text())

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
