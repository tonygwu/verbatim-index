#!/usr/bin/env python3
"""A repeat grade (run > 0) never reaches a published score.

FOUND by adversarial audit 2026-09-16. `calibrate()` and `paired_halo()` both
exclude run > 0 deliberately, because a repeat is a measurement of the judge and
not extra evidence about the speaker. Three other places did not:

  the per-transcript consensus in aggregate.py, which averages the judges
  drop_partial_panels(), which decides whether a recording has a full panel
  schedule.scan_panels(), which decides what still needs grading

Plan P5 and P9b prescribe drift anchors: 6 fixed transcripts re-graded in both
modes by every judge once per block group. The first time those run, a repeated
recording would count two or three times in its person's mean. The audit
reproduced it on a temporary corpus: one injected run-1 grade moved a person
5.3 points and two ranks.

  CONSENSUS   a run-1 grade does not change any published score
  PANEL       a run-1 grade does not complete an otherwise partial panel
  SCHEDULE    scan_panels ignores repeats when deciding what is complete

  .venv/bin/python scripts/test_run_zero_isolation.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "bin" / "python")
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def main() -> int:
    print("run-zero isolation")
    A = load("agg_rz", REPO / "scripts" / "aggregate.py")
    S = load("sched_rz", REPO / "scripts" / "schedule.py")
    tps = load("tps_rz", REPO / "scripts" / "test_profile_scoring.py")

    print("\n[CONSENSUS]")
    with tempfile.TemporaryDirectory(prefix="runzero-") as td:
        tmp = Path(td).resolve()
        root, profiles = tps.fixture_corpus(tmp)
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        env["VI_PROFILES_DIR"] = str(profiles)

        def run_agg(out):
            r = subprocess.run([PY, REPO / "scripts" / "aggregate.py", "--study", "pundits",
                                "--grades", root / "grades", "--roster", root / "roster" / "final.json",
                                "--out", root / out], env=env, capture_output=True, text=True)
            return r, json.loads((root / out).read_text()) if (root / out).exists() else {}

        r0, base = run_agg("base.json")
        check("the fixture corpus aggregates", r0.returncode == 0, r0.stderr[-400:])
        scores = lambda res: {p["slug"]: p["blinded"]["overall"]
                              for p in res.get("leaders", []) + res.get("unranked", [])}

        # Inject ONE repeat: same person, same transcript, same judge and mode,
        # run 1, every dimension pinned high. If repeats leak, p0 moves up.
        src = next((root / "grades" / "fable" / "p0").glob("*__blinded__r0.json"))
        rec = json.loads(src.read_text())
        rec["run"] = 1
        rec["identity"]["run"] = 1
        for dim in rec["grade"]["dimensions"]:
            rec["grade"]["dimensions"][dim]["score"] = 99
        (src.parent / src.name.replace("__r0.json", "__r1.json")).write_text(json.dumps(rec))

        r1, after = run_agg("after.json")
        check("the corpus with a repeat still aggregates", r1.returncode == 0, r1.stderr[-400:])
        moved = {k: (scores(base).get(k), scores(after).get(k))
                 for k in scores(base) if scores(base).get(k) != scores(after).get(k)}
        check("a run-1 grade changes no published score", moved == {}, str(moved))

    print("\n[PANEL]")
    A.configure_scoring(json.loads((REPO / "profiles" / "pundits.json").read_text()))

    def pg(sid, judge, mode, run=0):
        return {"leader_slug": "p", "source_id": sid, "judge": judge, "mode": mode, "run": run,
                "telemetry": {"served_model": f"{judge}-m"},
                "grade": {"dimensions": {d: {"score": 50} for d in A.DIMS},
                          "coverage": 1.0, "subject_speech_share_pct": 80}}

    # "partial" is missing gemini/blinded at run 0 and has it only as a repeat.
    corpus = [pg("partial", j, m) for m in ("blinded", "open") for j in ("fable", "gemini")
              if not (j == "gemini" and m == "blinded")]
    corpus.append(pg("partial", "gemini", "blinded", run=1))
    kept, dropped = A.drop_partial_panels(corpus, {"fable", "gemini"})
    check("a repeat does not fill a missing panel cell",
          {(x["leader_slug"], x["source_id"]) for x in kept} == set(),
          f"kept={[(x['judge'], x['mode'], x['run']) for x in kept]}")
    check("every grade still lands in exactly one bucket", len(kept) + len(dropped) == len(corpus))

    print("\n[SCHEDULE]")
    with tempfile.TemporaryDirectory(prefix="scanrz-") as td:
        g = Path(td)

        def write(slug, sid, judge, mode, run=0):
            p = g / judge / slug
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{sid}__{judge}__{mode}__r{run}.json").write_text(json.dumps(
                {"leader_slug": slug, "source_id": sid, "judge": judge, "mode": mode, "run": run,
                 "validation_errors": [], "grade": {"dimensions": {"d1": {"score": 50}}}}))
        for j in ("fable", "gemini"):
            for m in ("blinded", "open"):
                if not (j == "gemini" and m == "open"):
                    write("a", "s0", j, m)
        write("a", "s0", "gemini", "open", run=1)
        comp, part = S.scan_panels(g, ["fable", "gemini"])
        check("scan_panels does not count a repeat as a filled cell",
              comp == set() and part == {("a", "s0")}, f"complete={comp} partial={part}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
