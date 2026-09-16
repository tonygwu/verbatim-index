#!/usr/bin/env python3
"""An underscore-prefixed directory is not a leader.

Every stage writes its error log as JSONL under `_runs/`, and those files glob
identically to prediction records under `<pred_dir>/*/*.jsonl`. The loaders were
reading them. It has never changed a published number, because an error line
carries no `accepted` key and the accepted-filter drops it by accident. That is
luck, not a guard: an error log that ever gained that field, or a loader that
ever stopped filtering on `accepted`, would put log lines into the corpus with
nothing to say so.

FOUND 2026-09-16 while comparing two verdict sets over repo-1's supplemental
corpus: the record count came back 456 against 217 real records, because 239
error-log lines were being counted. `deploy_predictions.sh` already applies this
rule when it counts records; the loaders now do too.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import criteria_agreement as C  # noqa: E402
import phase2_resolvability as P2  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def record(pid, slug="ada"):
    return {
        "accepted": True, "leader_slug": slug, "prediction_id": pid,
        "transcript_id": f"{slug}/t1", "schema_version": 1, "status": "pending",
        "source": {"quote": "we will ship it", "statement_date": "2019-01-01"},
        "prediction": {"target_date": "2020", "specificity": "high",
                       "resolution_criteria": "By 2020-12-31 it will have shipped.",
                       "subject_control": "own", "category": "company_business",
                       "horizon": "explicit", "target_date_text": "in 2020",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": "It ships."},
        "verification": {"verifier_resolution_criteria": "By 2020-12-31 it will have shipped."},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "ada").mkdir()
        (d / "ada" / "t1.jsonl").write_text(
            "".join(json.dumps(record(f"{i:016x}")) + "\n" for i in range(3)))

        # Every stage writes one of these. It is JSONL and it globs like a record.
        (d / "_runs").mkdir()
        (d / "_runs" / "20260916T000000Z-both-abc_errors.jsonl").write_text(
            json.dumps({"id": "ada/t1", "stage": "extract", "status": "failed",
                        "error_type": "cli_nonzero_exit", "detail": "boom"}) + "\n")
        (d / "_raw").mkdir()
        (d / "_raw" / "x.jsonl").write_text(json.dumps({"whatever": 1}) + "\n")

        check("GLOB: the funnel reads 3 records, not the error log beside them",
              len(P2.load(d)) == 3, f"got {len(P2.load(d))}")
        check("GLOB: the criteria screen reads 3 records",
              len(C.load(d)) == 3, f"got {len(C.load(d))}")

        # The dangerous shape: an error log that happens to carry `accepted`.
        # Before the fix this entered the corpus as a prediction.
        (d / "_runs" / "poisoned_errors.jsonl").write_text(
            json.dumps({"id": "ada/t1", "stage": "verify", "accepted": True,
                        "leader_slug": "ada", "prediction_id": "deadbeefdeadbeef"}) + "\n")
        check("GLOB: an error line carrying `accepted` STILL does not enter the corpus",
              len(P2.load(d)) == 3,
              f"got {len(P2.load(d))}; the accepted-filter was the only thing holding this back")

        # And a real leader whose name merely starts with a letter is unaffected.
        (d / "_hidden").mkdir()
        (d / "_hidden" / "t.jsonl").write_text(json.dumps(record("ffffffffffffffff", "_hidden")) + "\n")
        check("GLOB: any underscore directory is skipped, not just _runs",
              len(P2.load(d)) == 3, f"got {len(P2.load(d))}")

    live = ROOT / "data" / "predictions"
    if live.exists():
        allf = sorted(live.glob("*/*.jsonl"))
        real = [f for f in allf if not f.parent.name.startswith("_")]
        check("LIVE: the real corpus does carry such files, so this is not hypothetical",
              len(allf) > len(real),
              f"{len(allf)} globbed, {len(real)} real; if equal, the _runs logs were moved")

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
