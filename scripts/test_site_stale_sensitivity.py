#!/usr/bin/env python3
"""The page reads the board's runs, so a stale sidecar the scorer dropped from a
sensitivity run must not make it refuse.

FOUND 2026-10-05: re-dating bill-gates/khosla-ventures-8bosqk made the half- and
double-window sidecars of its implied record (b12ea645cff002e2), written under the old
date, stale. The scorer dropped them and listed them in
date_overrides.stale_sidecars_dropped with their runs, the implied_sensitivity runs.
build_predictions_site.stage_models passed that whole list to load_across over the
BOARD's runs only, and load_across refused: "the restatement manifest supersedes
sidecars in runs that are not being read". The deploy stopped. Stale drops belong to
the runs that are read; the sensitivity runs are read elsewhere.

A two-run fixture on disk; no network, no data.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_predictions_site as B  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def put(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    board = root / "predictions" / "_experiments" / "board"
    half = root / "predictions" / "_experiments" / "board-implied-half"
    prior = {"prediction_id": "p1", "p": 0.3,
             "telemetry": {"canonical_model": "claude-fable-5-1", "telemetry_models": ["claude-fable-5-1"]}}
    put(board / "priors" / "ada" / "p1.json", prior)
    put(board / "resolutions" / "ada" / "p1.json", {"prediction_id": "p1", "telemetry": {"served_model": "gpt-6-astra"}})
    # The stale pair: one in the board run (read, so dropped there), one in a sensitivity run (not read).
    put(board / "priors" / "ada" / "old.json", {**prior, "prediction_id": "old"})
    put(half / "resolutions" / "ada" / "old.json", {"prediction_id": "old", "telemetry": {"served_model": "gpt-6-astra"}})
    scores_path = root / "predictions" / "scores.json"
    doc = {"run_dirs": ["predictions/_experiments/board"],
           "settings": {"implied_sensitivity": {"half": ["predictions/_experiments/board-implied-half"]}},
           "date_overrides": {"stale_sidecars_dropped": [
               {"prediction_id": "old", "stage": "prior", "run": "predictions/_experiments/board"},
               {"prediction_id": "old", "stage": "resolve", "run": "predictions/_experiments/board-implied-half"}]},
           "predictions": [{"prediction_id": "p1", "scored": True, "p": 0.3}]}
    put(scores_path, doc)
    try:
        got = B.stage_models(doc, str(scores_path))
        check("a stale sidecar dropped from a sensitivity run does not stop the page", True)
        check("the scored row's models are still read from the board run",
              got["prior"] and got["resolve"] and sum(got["prior"].values()) == 1, str(got))
    except SystemExit as exc:
        check("a stale sidecar dropped from a sensitivity run does not stop the page", False, str(exc)[:200])
    # The drop in the board run itself is still applied: a scored row may not read a stale prior.
    doc2 = {**doc, "predictions": [{"prediction_id": "old", "scored": True, "p": 0.3}]}
    try:
        B.stage_models(doc2, str(scores_path))
        check("a stale sidecar in a run that IS read stays dropped", False, "the stale prior was read")
    except SystemExit as exc:
        check("a stale sidecar in a run that IS read stays dropped", "has no prior record" in str(exc), str(exc)[:200])

    # A drop in a run that is neither read nor a declared sensitivity run still refuses.
    doc3 = {**doc, "date_overrides": {"stale_sidecars_dropped": [
        {"prediction_id": "old", "stage": "resolve", "run": "predictions/_experiments/run-nowhere"}]}}
    try:
        B.stage_models(doc3, str(scores_path))
        check("a drop in an undeclared, unread run still refuses", False, "rendered")
    except SystemExit as exc:
        check("a drop in an undeclared, unread run still refuses", "not being read" in str(exc), str(exc)[:200])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
