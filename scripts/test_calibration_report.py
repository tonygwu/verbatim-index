#!/usr/bin/env python3
"""calibration_report.py compares every judge pair, not the first two by name.

The cross_judge block took `names = sorted(jd)` and then read only names[0] and
names[1]. With fable, astra and gemini present it reported astra-vs-fable and
dropped gemini with no warning. That is the same hand-typed two-judge
assumption test_judge_enumeration.py guards in aggregate.py, in a script that
fix missed. The file it writes, data/logs/calibration.json, sets the tie band
published on the site, so a judge silently left out of it is a judge the
published noise figure does not describe.

Runs a three-judge and a four-judge fixture, because there will be a fourth.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_calibration_report.py
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "calibration_report.py"
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def grade(overall: float) -> dict:
    return {
        "overall": overall,
        "dimensions": {d: {"score": overall} for d in ("d1_clarity", "d2_insight", "d3_technical_depth")},
        "coverage": 1.0, "venue_challenge": 3, "venue_type": "long_form_podcast",
        "subject_speech_share_pct": 70, "identity_confident": True, "asr_quality": "good",
        "red_flags": [], "subcriteria": [{"code": "C1", "score": 3}],
    }


def run(scores: dict[str, list[float]]) -> dict:
    return run_with_invalid(scores, None)


def run_with_invalid(scores: dict[str, list[float]], invalid: tuple[str, float] | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for judge, vals in scores.items():
            d = root / "grades" / judge / "leader"
            d.mkdir(parents=True)
            for i, v in enumerate(vals):
                (d / f"src__{judge}__blinded__r{i}.json").write_text(json.dumps(
                    {"judge": judge, "mode": "blinded", "elapsed_sec": 1.0, "grade": grade(v),
                     "validation_errors": []}))
        if invalid:
            judge, v = invalid
            (root / "grades" / judge / "leader" / f"src__{judge}__blinded__r9.json").write_text(json.dumps(
                {"judge": judge, "mode": "blinded", "elapsed_sec": 1.0, "grade": grade(v),
                 "validation_errors": ["d2_insight evidence quote is 26 words, cap is 25"]}))
        out = root / "calibration.json"
        p = subprocess.run([sys.executable, str(SCRIPT), "--grades", str(root / "grades"), "--out", str(out)],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"calibration_report.py exited {p.returncode}: {p.stderr[-800:]}")
        return json.loads(out.read_text())


def mean(v):
    return sum(v) / len(v)


def assert_panel(label: str, scores: dict[str, list[float]]) -> None:
    rep = run(scores)
    cj = rep["cross_judge"].get("blinded", {})
    names = sorted(scores)
    check(f"{label}: cross_judge names every judge", cj.get("judges") == names, f"got {cj.get('judges')}")
    for j in names:
        check(f"{label}: mean reported for {j}",
              cj.get("judge_means", {}).get(j) == round(mean(scores[j]), 2),
              f"got {cj.get('judge_means')}")
    pairs = {tuple(p.get("judges", [])): p for p in cj.get("pairs", [])}
    want = list(itertools.combinations(names, 2))
    check(f"{label}: one entry per judge pair", sorted(pairs) == want, f"got {sorted(pairs)}, want {want}")
    for a, b in want:
        p = pairs.get((a, b), {})
        gap = round(abs(mean(scores[a]) - mean(scores[b])), 2)
        check(f"{label}: gap {a}-{b}", p.get("between_judge_gap") == gap, f"got {p}, want {gap}")
    # No key may let one pair stand for the panel.
    check(f"{label}: no single-pair gap at panel level",
          "between_judge_gap" not in cj and "gap_in_units_of_noise" not in cj, f"keys {sorted(cj)}")


def main() -> int:
    three = {"fable": [59.0, 60.0, 61.0], "astra": [66.0, 67.0, 68.5], "gemini": [70.0, 72.0, 74.0]}
    assert_panel("three judges", three)
    assert_panel("four judges", {**three, "zeta": [50.0, 50.5, 51.0]})
    # Gemini's gap from fable (12.0) is the largest; the old code never saw it.
    rep = run(three)
    pairs = {tuple(p["judges"]): p for p in rep["cross_judge"].get("blinded", {}).get("pairs", [])}
    check("three judges: fable-gemini gap is 12.0",
          pairs.get(("fable", "gemini"), {}).get("between_judge_gap") == 12.0, f"got {pairs}")
    # A grade that failed validation never reaches the board (aggregate.py marks
    # it _excluded), so it may not set the published noise figure either.
    rep = run_with_invalid({"fable": [59.0, 60.0, 61.0], "gemini": [70.0, 72.0, 74.0]}, invalid=("gemini", 99.0))
    pj = rep["per_judge"].get("gemini|blinded", {})
    check("invalid grade: excluded from per_judge runs", pj.get("runs") == 3, f"got {pj.get('runs')}")
    check("invalid grade: excluded from overall mean", pj.get("overall", {}).get("mean") == 72.0,
          f"got {pj.get('overall')}")
    check("invalid grade: exclusion counted per judge", pj.get("excluded_validation_errors") == 1,
          f"got {pj.get('excluded_validation_errors')}")
    check("invalid grade: exclusion named in notes",
          any("gemini" in n and "validation" in n for n in rep.get("notes", [])), f"notes {rep.get('notes')}")
    check("valid-only judge reports zero exclusions",
          rep["per_judge"].get("fable|blinded", {}).get("excluded_validation_errors") == 0)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
