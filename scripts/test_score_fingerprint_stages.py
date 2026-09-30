#!/usr/bin/env python3
"""scores.json fingerprints the early/ and lead_tests/ sidecars only when the board reads them.

`score_inputs_sha256` is the digest `data_sync.py push` and the deploy compare
against scores.json. Code from before the early and lead-test stages hashed
three sidecar directories. If the new code hashed early/ and lead_tests/ on
every board, a clone on the old code and a clone on the new code would compute
different digests for the same data as soon as one run held an early call, and
each would call the other's scores.json stale (review 2026-09-30, item 9). The
two directories therefore enter the digest only when `early_calls` or
`lead_test` is set, the way `withdrawn` does.

  LEGACY    with neither key, the digest equals the three-directory digest the
            code before these stages computed, even with early/ and lead_tests/
            sidecars on disk
  QUIET     with neither key, editing an early or lead-test sidecar leaves the
            digest alone, because the board does not read them
  EARLY     with early_calls set, editing an early sidecar changes the digest,
            so scores.json is reported stale
  LEAD      with lead_test set, editing a lead-test sidecar changes the digest
  SEPARATE  each key brings in only its own directory
  STALE     scores_staleness names the change end to end

  .venv/bin/python scripts/test_score_fingerprint_stages.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def load(name: str, alias: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(alias, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D = load("data_clone_workflow", "dcw_fp")

RUN = "predictions/_experiments/r1"
BASE = {"as_of": "2026-09-30", "trend": True, "min_lead_days": 60, "predictions": ["predictions"],
        "runs": [RUN], "index": "predictions/index.json"}


def legacy_digest(root: Path, settings: dict) -> str:
    """The digest as main computed it on 2026-09-30, before the early and lead-test
    stages: three sidecar directories, and the optional files only when named.
    Kept here verbatim as the reference an old-code clone still computes."""
    h = hashlib.sha256()
    h.update(json.dumps(settings, sort_keys=True).encode() + b"\n")
    for pd in settings["predictions"]:
        h.update(f"records {pd} {D.prediction_inputs_sha256(root / pd)}\n".encode())
    h.update(f"index {hashlib.sha256((root / settings['index']).read_bytes()).hexdigest()}\n".encode())
    for key in ("restatements", "date_overrides", "replacements"):
        if key in settings:
            h.update(f"{key} {hashlib.sha256((root / settings[key]).read_bytes()).hexdigest()}\n".encode())
    for run in settings["runs"]:
        for sub in ("resolutions", "priors", "criteria_repairs"):
            for f in sorted((root / run / sub).glob("*/*.json")):
                h.update(f"{run}/{f.relative_to(root / run)} {hashlib.sha256(f.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, sort_keys=True))


def fixture(root: Path) -> None:
    write(root / "predictions/index.json", {"people": []})
    (root / "predictions/ada").mkdir(parents=True)
    (root / "predictions/ada/s1.jsonl").write_text(json.dumps({"prediction_id": "p1"}) + "\n")
    for sub in ("resolutions", "priors", "criteria_repairs", "early", "lead_tests"):
        write(root / RUN / sub / "ada/p1.json", {"prediction_id": "p1", "sub": sub, "v": 1})


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixture(root)

        plain = dict(BASE)
        check("LEGACY: with neither key, the digest is the three-directory digest the old code computes, "
              "even with early/ and lead_tests/ sidecars on disk",
              D.score_inputs_sha256(root, plain) == legacy_digest(root, plain),
              f"new {D.score_inputs_sha256(root, plain)[:12]} old {legacy_digest(root, plain)[:12]}")

        early_on = dict(BASE, early_calls=True)
        lead_on = dict(BASE, lead_test=True)
        before = {k: D.score_inputs_sha256(root, s) for k, s in
                  (("plain", plain), ("early", early_on), ("lead", lead_on))}

        write(root / RUN / "early/ada/p1.json", {"prediction_id": "p1", "sub": "early", "v": 2})
        after_e = {k: D.score_inputs_sha256(root, s) for k, s in
                   (("plain", plain), ("early", early_on), ("lead", lead_on))}
        check("QUIET: with neither key, an edited early sidecar leaves the digest alone",
              after_e["plain"] == before["plain"])
        check("EARLY: with early_calls set, an edited early sidecar changes the digest",
              after_e["early"] != before["early"])
        check("SEPARATE: lead_test alone does not fingerprint early/",
              after_e["lead"] == before["lead"])

        write(root / RUN / "lead_tests/ada/p1.json", {"prediction_id": "p1", "sub": "lead_tests", "v": 2})
        after_l = {k: D.score_inputs_sha256(root, s) for k, s in
                   (("plain", plain), ("early", early_on), ("lead", lead_on))}
        check("QUIET: with neither key, an edited lead-test sidecar leaves the digest alone",
              after_l["plain"] == after_e["plain"])
        check("LEAD: with lead_test set, an edited lead-test sidecar changes the digest",
              after_l["lead"] != after_e["lead"])
        check("SEPARATE: early_calls alone does not fingerprint lead_tests/",
              after_l["early"] == after_e["early"])
        check("LEGACY: still equal to the old digest after both edits",
              D.score_inputs_sha256(root, plain) == legacy_digest(root, plain))

        # End to end through scores_staleness, the check push and deploy both run.
        cfg = dict(early_on, out="predictions/scores.json")
        write(root / "predictions/scoring.json", cfg)
        settings = D.settings_from_config(cfg)
        write(root / "predictions/scores.json",
              {"settings": settings, "inputs_sha256": D.score_inputs_sha256(root, settings)})
        fresh = D.scores_staleness(root / "predictions/scores.json", root / "predictions/scoring.json")
        write(root / RUN / "early/ada/p1.json", {"prediction_id": "p1", "sub": "early", "v": 3})
        stale = D.scores_staleness(root / "predictions/scores.json", root / "predictions/scoring.json")
        check("STALE: with early_calls on, scores.json is fresh, then stale once an early call changes",
              fresh is None and stale is not None and "input changed" in stale, f"fresh={fresh!r} stale={stale!r}")

    print(f"\n{'ALL PASS' if not FAILED else f'{len(FAILED)} failed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
