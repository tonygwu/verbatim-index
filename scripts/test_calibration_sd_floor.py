#!/usr/bin/env python3
"""calibrate() and the shadow-judge readiness report use ONE spread floor.

WHY THIS EXISTS. calibrate() rescales a judge only when its spread reaches a
floor, and shadow_report() tells the operator whether a candidate judge "would
be rescaled" against "the two thresholds calibrate() applies". The floor was the
literal 3.0, typed in both places (aggregate.py, 2026-10-11: three copies). A
change to one copy would leave the readiness report predicting rescaling under
a floor calibrate() no longer uses, which is the stale-literal defect this repo
keeps paying for. It is now MIN_CALIBRATION_SD, beside MIN_CALIBRATION_N.

  ONE   raising MIN_CALIBRATION_SD changes calibrate()'s verdict AND the
        readiness report's, together.
  SAME  at the shipped value, a judge with spread above it is rescaled and
        reported as rescalable.

  .venv/bin/python scripts/test_calibration_sd_floor.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import test_render_integrity as RI  # noqa: E402  (grade fixture only; its main() is guarded)

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("aggregate_sdfloor", REPO / "scripts" / "aggregate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpus() -> list[dict]:
    """30 grades per judge, scores spread 40..69, so every judge's sd is about 8.7."""
    out = []
    for judge in ("fable", "astra"):
        for i in range(30):
            out.append(RI.a_grade("leader-0", f"s{i}", judge, 60, 40 + i))
    return out


def verdicts(A) -> tuple[set, set]:
    grades = corpus()
    params = A.calibrate(grades)
    rescaled = {v["rescaled"] for k, v in params.items() if isinstance(v, dict) and "rescaled" in v}
    ready = A.shadow_report([g for g in grades if g["judge"] == "astra"], grades, None)["calibration_readiness"]
    would = {d["would_be_rescaled"] for d in ready.values()} | {d["spread_sufficient"] for d in ready.values()}
    return rescaled, would


def main() -> int:
    print("one calibration spread floor")
    A = load()
    A.configure_scoring(json.loads((REPO / "profiles" / "leaders.json").read_text()))
    check("aggregate.py names the floor MIN_CALIBRATION_SD", hasattr(A, "MIN_CALIBRATION_SD"))

    rescaled, would = verdicts(A)
    check("at the shipped floor a judge with sd ~8.7 is rescaled", rescaled == {True}, str(rescaled))
    check("and the readiness report agrees", would == {True}, str(would))

    A.MIN_CALIBRATION_SD = 100.0
    rescaled, would = verdicts(A)
    check("raising the floor stops calibrate() rescaling", rescaled == {False}, str(rescaled))
    check("and the readiness report follows it", would == {False}, str(would))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
