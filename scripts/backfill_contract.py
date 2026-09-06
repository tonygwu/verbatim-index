#!/usr/bin/env python3
"""Stamp pre-versioning grades with the rubric contract that produced them.

Grades written before contract hashing existed carry no rubric fingerprint.
Backfilling one is only legitimate if the rubric provably did not change over
the grading window, so this script CHECKS that rather than assuming it:

  - `git log` must show the last commit touching RUBRIC.md or the schema is
    OLDER than the earliest grade in the corpus.
  - Both files must be clean in the working tree, so the committed text is the
    text that was read.

If either check fails the script refuses, because the honest label would then
be "unknown" and inventing a hash would destroy the audit trail it exists to
create. The evidence for the stamp is recorded inside each record.

Usage:  backfill_contract.py [--apply]     (dry run without --apply)
"""
from __future__ import annotations
import argparse, glob, json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade import grading_contract, RUBRIC_PATH, SCHEMA_PATH  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--grades", default="data/grades")
    args = ap.parse_args()

    dirty = subprocess.run(["git", "status", "--porcelain", str(RUBRIC_PATH), str(SCHEMA_PATH)],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit(f"REFUSING: rubric or schema modified but uncommitted:\n{dirty}\n"
                         "The committed text is not what was read. Commit or revert first.")

    last = subprocess.run(["git", "log", "-1", "--format=%cI", "--", str(RUBRIC_PATH), str(SCHEMA_PATH)],
                          capture_output=True, text=True).stdout.strip()
    if not last:
        raise SystemExit("REFUSING: no commit history for the rubric; cannot prove it was stable.")

    paths = [p for p in glob.glob(f"{args.grades}/**/*.json", recursive=True) if "_raw" not in p]
    recs = []
    for p in paths:
        try:
            recs.append((p, json.loads(Path(p).read_text())))
        except Exception:
            pass
    if not recs:
        raise SystemExit("no grades found")

    earliest = min(r.get("graded_at_utc", "9999") for _, r in recs)
    # Compare as UTC instants; git gives an offset-aware ISO string.
    from datetime import datetime
    last_dt = datetime.fromisoformat(last).astimezone(tz=None).utctimetuple()
    early_dt = datetime.fromisoformat(earliest.replace("Z", "+00:00")).utctimetuple()
    if last_dt >= early_dt:
        raise SystemExit(
            f"REFUSING: rubric last changed {last}, which is NOT before the earliest grade "
            f"{earliest}. Those grades may have been produced by different rubric text. "
            f"Re-grade instead of backfilling.")

    contract = grading_contract()
    stamp = dict(contract)
    stamp["backfilled"] = True
    stamp["backfill_evidence"] = (
        f"rubric and schema last committed {last}, earliest grade {earliest}; "
        f"working tree clean, so all grades in this corpus were produced by this text")

    todo = [(p, r) for p, r in recs if not r.get("grading_contract")]
    print(f"grades: {len(recs)}   already stamped: {len(recs)-len(todo)}   to backfill: {len(todo)}")
    print(f"contract: {contract['contract_id']}")
    print(f"evidence: rubric last changed {last} < earliest grade {earliest}  OK")
    if not args.apply:
        print("\ndry run. re-run with --apply to write.")
        return 0
    for p, r in todo:
        r["grading_contract"] = stamp
        tmp = Path(p).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1))
        tmp.replace(Path(p))
    print(f"stamped {len(todo)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
