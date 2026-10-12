#!/usr/bin/env python3
"""The archival-excluded sensitivity plan P5 asks for, checked against a real re-run.

docs/PUNDITS-PLAN.md, P5 "Sampling rules": an archival subject (Charlie Kirk, who
died in September 2025) is sampled from the 5 years before his last recording, and
"a sensitivity analysis excludes archival subjects". Excluding a person does not
just remove a row: calibration is fitted on every person's blinded grades, so it
moves everyone else's score. aggregate.archival_excluded() refits calibration
without the archival subjects and rescores every other ranked person.

The ORACLE is aggregate.py itself: the same corpus with the archival subject's
grade files deleted, aggregated end to end. Its published scores are what the
sensitivity must report, to the decimal.

  FIXTURE   six people, six blinded recordings each, Fable and Gemini, so each
            judge has 36 grades with the archival subject and 30 without (both
            above MIN_CALIBRATION_N, so calibration rescales in both runs). The
            archival subject's Fable grades sit far below everyone else's.
  ORACLE    every remaining person's score equals the re-run's published score
  MOVES     the shift is not zero: the test would be vacuous if calibration
            ignored the archival grades
  NONE      a roster with no archival subject reports computed=false, saying why
  LEADERS   aggregate never writes the key for the leaders study (v1)

No quota, no data.

  .venv/bin/python scripts/test_archival_sensitivity.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpus(tmp: Path, tps, archival: bool) -> tuple[Path, Path]:
    """The profile_scoring fixture's profile and checkout, re-populated with a bigger corpus."""
    import grading_contract as GC
    root, profiles = tps.fixture_corpus(tmp)
    shutil.rmtree(root / "grades")
    prof = json.loads((profiles / "pundits.json").read_text())
    contract = GC.contract_v2(prof)
    roster = [{"slug": f"p{i}", "name": f"Pundit {i}", "company": "Show", "role": "host", "sector": "politics",
               "archival": archival and i == 5} for i in range(6)]
    (root / "roster" / "final.json").write_text(json.dumps({"roster": roster}))
    for i, person in enumerate(roster):
        for t in range(6):
            for judge in ("fable", "gemini"):
                if judge == "fable":
                    score = 15 + t if i == 5 else 40 + 6 * i + t
                else:
                    score = 45 + 4 * i + 2 * t
                sid = f"s{t}"
                rec = {"transcript_id": f"{person['slug']}/{sid}", "leader_slug": person["slug"],
                       "source_id": sid, "judge": judge, "mode": "blinded", "run": 0,
                       "grading_contract": {"contract_id": contract["contract_id"]},
                       "identity": {"study_id": "pundits", "contract_id": contract["contract_id"],
                                    "prompt_sha256": "p", "input_sha256": "i", "mode": "blinded",
                                    "judge": judge, "requested_model": "m", "run": 0},
                       "served_model": "m", "validation_errors": [],
                       "grade": tps.pundit_grade(person["slug"], sid, judge, score, None)}
                p = root / "grades" / judge / person["slug"] / f"{sid}__{judge}__blinded__r0.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(rec))
    return root, profiles


def aggregate(root: Path, profiles: Path, out: str, study: str = "pundits") -> tuple[subprocess.CompletedProcess, dict]:
    env = {k: v for k, v in os.environ.items() if k != "STUDY"}
    env["VI_PROFILES_DIR"] = str(profiles)
    r = subprocess.run([PY, REPO / "scripts" / "aggregate.py", "--study", study, "--grades", root / "grades",
                        "--roster", root / "roster" / "final.json", "--out", root / out],
                       env=env, capture_output=True, text=True)
    return r, (json.loads((root / out).read_text()) if (root / out).exists() else {})


def main() -> int:
    print("archival-excluded sensitivity")
    tps = load("tps_arch", REPO / "scripts" / "test_profile_scoring.py")

    with tempfile.TemporaryDirectory(prefix="archival-") as td:
        tmp = Path(td).resolve()
        (tmp / "a").mkdir()
        root, profiles = corpus(tmp / "a", tps, archival=True)
        r, full = aggregate(root, profiles, "full.json")
        check("the fixture corpus aggregates", r.returncode == 0, r.stderr[-500:])
        diag = (full.get("diagnostics") or {}).get("archival_excluded") or {}
        cal = (full.get("diagnostics") or {}).get("calibration_params") or {}
        check("calibration rescales in the full run (36 grades a judge)",
              any(v.get("rescaled") for v in cal.values()), str(list(cal.values())[:1]))

        print("\n[ORACLE]")
        # The same corpus without the archival subject's grades, aggregated end to end.
        for judge in ("fable", "gemini"):
            shutil.rmtree(root / "grades" / judge / "p5")
        r2, without = aggregate(root, profiles, "without.json")
        check("the corpus without p5 aggregates", r2.returncode == 0, r2.stderr[-500:])
        expected = {p["slug"]: p["blinded"]["overall"] for p in without.get("leaders", [])}
        got = {s: e.get("without_archival") for s, e in (diag.get("by_person") or {}).items()}
        check("it ran, excluding p5 and its 6 recordings",
              diag.get("computed") is True and diag.get("excluded") == ["p5"] and diag.get("recordings_excluded") == 6,
              json.dumps(diag)[:400])
        check("every remaining person's score equals the re-run's published score",
              got == expected and len(expected) == 5, f"got={got} expected={expected}")

        print("\n[MOVES]")
        fulls = {p["slug"]: p["blinded"]["overall"] for p in full.get("leaders", [])}
        check("the full board is reported beside it",
              {s: e.get("full") for s, e in (diag.get("by_person") or {}).items()}
              == {s: v for s, v in fulls.items() if s != "p5"}, str(diag.get("by_person")))
        check("and the archival grades really moved calibration: a nonzero shift",
              isinstance(diag.get("max_abs_shift"), (int, float)) and diag["max_abs_shift"] > 0, str(diag))

        print("\n[NONE]")
        (tmp / "b").mkdir()
        root_b, profiles_b = corpus(tmp / "b", tps, archival=False)
        r3, none = aggregate(root_b, profiles_b, "none.json")
        d3 = (none.get("diagnostics") or {}).get("archival_excluded") or {}
        check("no archival subject: computed=false, with the reason",
              r3.returncode == 0 and d3.get("computed") is False and "archival" in d3.get("why", ""), str(d3))

    print("\n[LEADERS]")
    src = (REPO / "scripts" / "aggregate.py").read_text()
    call = src[src.find('diagnostics["archival_excluded"]') - 200:src.find('diagnostics["archival_excluded"]')]
    check("the key is written only under is_v2", "if is_v2:" in call, call[-200:])

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
