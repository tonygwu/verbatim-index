#!/usr/bin/env python3
"""Scoring follows the study profile: leaders keeps its three dimensions, pundits gets its own.

Pundits plan, P4a. aggregate.py hardcoded DIMS, DIM_LABEL, WEIGHTS and
SUB_GROUPS for the leaders rubric, so a pundits corpus reached calibrate() and
died with KeyError: 'd1_clarity'. The profile now carries the scoring
definition for both studies, and aggregate.py takes it from the study it runs.

  LEADERS-PINNED   profiles/leaders.json scoring equals grade.py's SUBCRITERIA and
                   WEIGHTS and aggregate.py's defaults, so leaders cannot drift
  CONFIGURE        configure_scoring(pundits) rebinds all four names to the pundits
                   dimensions; configure_scoring(leaders) restores the defaults
  REAL-RUN         a real aggregate.py run on a pundits fixture corpus writes
                   results keyed by the pundits dimensions, not a KeyError
  UNSUPPORTED      a grade with an unsupported dimension (null score) is excluded
                   from scoring and counted in diagnostics, never averaged as 0

No quota and no live data: fixtures only.

  .venv/bin/python scripts/test_profile_scoring.py
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


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_p4a", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def profile(study: str) -> dict:
    return json.loads((REPO / "profiles" / f"{study}.json").read_text())


def pundit_grade(slug: str, sid: str, judge: str, score: int, unsupported: str | None = None) -> dict:
    scoring = profile("pundits")["scoring"]
    dims, subs = {}, []
    for d in scoring["dimensions"]:
        off = d["key"] == unsupported
        dims[d["key"]] = {"dimension_status": "unsupported" if off else "supported",
                          "score": None if off else score, "reasoning": "word " * 25,
                          "evidence": [{"quote": "a short quote", "timestamp": "unmarked", "speaker": "subject",
                                        "why_it_matters": "x"}] * 2,
                          "counterevidence": "none"}
        subs += [{"code": c, "score": 0 if off else 3, "justification": "x"} for c in d["subcriteria"]]
    overall = None if unsupported else float(score)
    return {"transcript_id": f"{slug}/{sid}", "venue_type": "conversation", "venue_challenge": 3,
            "subject_speech_share_pct": 60, "identity_guess": "unknown", "identity_confident": False,
            "subcriteria": subs, "dimensions": dims, "overall": overall, "coverage": 1.0,
            "confidence": "medium", "salient_claims": [], "red_flags": []}


def fixture_corpus(tmp: Path) -> tuple[Path, Path]:
    """A pundits data checkout and a fixture profile dir whose skill files exist."""
    import grading_contract as GC
    sd = tmp / "skill"
    sd.mkdir()
    (sd / "RUBRIC.md").write_text("fixture rubric\n")
    (sd / "judge_output.schema.json").write_text('{"type": "object"}\n')
    (sd / "PROMPT.md").write_text("<<<BLINDED>>>\nb\n<<<END>>>\n<<<OPEN>>>\n{{speaker_name}}\n<<<END>>>\n{{transcript}}\n")
    prof = profile("pundits")
    prof["skill_dir"] = str(sd)
    profiles = tmp / "profiles"
    profiles.mkdir()
    (profiles / "pundits.json").write_text(json.dumps(prof))
    shutil.copy2(REPO / "profiles" / "leaders.json", profiles / "leaders.json")
    contract = GC.contract_v2(prof)

    root = tmp / "pundits-data"
    root.mkdir()
    for args in (("init", "-q", "-b", "main"),
                 ("config", "remote.origin.url", "git@github.com:tonygwu/verbatim-pundits-data.git")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / ".study").write_text("pundits\n")
    roster = [{"slug": f"p{i}", "name": f"Pundit {i}", "company": "Show", "role": "host", "sector": "politics"}
              for i in range(3)]
    (root / "roster").mkdir()
    (root / "roster" / "final.json").write_text(json.dumps({"roster": roster}))
    n = 0
    for i, person in enumerate(roster):
        for t in range(6):
            for j, judge in enumerate(("fable", "astra", "gemini")):
                sid = f"s{t}"
                unsupported = "d1_steelmanning" if (i == 0 and t == 0 and judge == "fable") else None
                g = pundit_grade(person["slug"], sid, judge, 40 + 5 * i + t + j, unsupported)
                rec = {"transcript_id": f"{person['slug']}/{sid}", "leader_slug": person["slug"],
                       "source_id": sid, "judge": judge, "mode": "blinded", "run": 0,
                       "grading_contract": {"contract_id": contract["contract_id"]},
                       "identity": {"study_id": "pundits", "contract_id": contract["contract_id"],
                                    "prompt_sha256": "p", "input_sha256": "i", "mode": "blinded",
                                    "judge": judge, "requested_model": "m", "run": 0},
                       "served_model": "m", "validation_errors": [], "grade": g}
                p = root / "grades" / judge / person["slug"] / f"{sid}__{judge}__blinded__r0.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(rec))
                n += 1
    return root, profiles


def main() -> int:
    print("profile-driven scoring")
    A = load("aggregate")
    G = load("grade")
    lead, pund = profile("leaders").get("scoring"), profile("pundits")["scoring"]

    print("\n[LEADERS-PINNED]")
    check("profiles/leaders.json carries a scoring block", isinstance(lead, dict))
    if isinstance(lead, dict):
        keys = [d["key"] for d in lead["dimensions"]]
        check("its dimension keys equal aggregate.DIMS", keys == A.DIMS, f"{keys} vs {A.DIMS}")
        check("its weights equal aggregate.WEIGHTS and grade.WEIGHTS",
              {d["key"]: d["weight"] for d in lead["dimensions"]} == A.WEIGHTS == G.WEIGHTS)
        check("its sub-criteria equal aggregate.SUB_GROUPS and grade.SUBCRITERIA",
              {d["key"]: d["subcriteria"] for d in lead["dimensions"]} == A.SUB_GROUPS
              and [c for d in lead["dimensions"] for c in d["subcriteria"]] == G.SUBCRITERIA)
        check("its labels equal aggregate.DIM_LABEL", {d["key"]: d["label"] for d in lead["dimensions"]} == A.DIM_LABEL)

    print("\n[CONFIGURE]")
    if not hasattr(A, "configure_scoring"):
        check("aggregate.py exposes configure_scoring", False)
    else:
        A.configure_scoring(profile("pundits"))
        check("pundits dimensions replace DIMS", A.DIMS == [d["key"] for d in pund["dimensions"]], str(A.DIMS))
        check("and WEIGHTS, SUB_GROUPS and DIM_LABEL with them",
              A.WEIGHTS == {d["key"]: d["weight"] for d in pund["dimensions"]}
              and A.SUB_GROUPS == {d["key"]: d["subcriteria"] for d in pund["dimensions"]}
              and A.DIM_LABEL == {d["key"]: d["label"] for d in pund["dimensions"]})
        A.configure_scoring(profile("leaders"))
        check("leaders restores the defaults", A.DIMS == ["d1_clarity", "d2_insight", "d3_technical_depth"])
        try:
            A.configure_scoring({"study_id": "x"})
            refused = False
        except (RuntimeError, SystemExit, KeyError) as exc:
            refused = "scoring" in str(exc)
        check("a profile without scoring is refused, not defaulted", refused)

    print("\n[REAL-RUN / UNSUPPORTED]")
    with tempfile.TemporaryDirectory(prefix="p4a-") as td:
        tmp = Path(td).resolve()
        root, profiles = fixture_corpus(tmp)
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        env["VI_PROFILES_DIR"] = str(profiles)
        r = subprocess.run([PY, REPO / "scripts" / "aggregate.py", "--study", "pundits",
                            "--grades", root / "grades", "--roster", root / "roster" / "final.json",
                            "--out", root / "results.json"], env=env, capture_output=True, text=True)
        check("aggregate.py completes on a pundits corpus", r.returncode == 0, r.stderr[-600:])
        res = json.loads((root / "results.json").read_text()) if (root / "results.json").exists() else {}
        people = res.get("leaders", []) + res.get("unranked", [])
        blinded = [p.get("blinded") or {} for p in people]
        want = {d["key"] for d in pund["dimensions"]}
        check("results are keyed by the pundits dimensions",
              bool(blinded) and all(want <= set(b) for b in blinded), str([sorted(b) for b in blinded][:1]))
        check("no leaders dimension appears in the results", "d1_clarity" not in json.dumps(res))
        diag = res.get("diagnostics", {})
        check("diagnostics report the pundits weights", diag.get("weights") == {d["key"]: d["weight"] for d in pund["dimensions"]},
              str(diag.get("weights")))
        check("the unsupported-dimension grade is excluded and counted",
              diag.get("grades_excluded_unsupported_dimension") == 1, str(diag.get("grades_excluded_unsupported_dimension")))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
