#!/usr/bin/env python3
"""Repair an extract status that says failed over records that plainly succeeded.

    .venv/bin/python scripts/repair_stale_extract_meta.py --out <records-dir> [--apply]

WHY THIS EXISTS. `extract_predictions.py --stage verify` skips any transcript
whose meta says the extract stage did not finish (line 436 at 5bb9ef5). That is
right in general: verifying candidates from a half-written extraction would
verify nothing coherent.

It is wrong for one specific shape. repo-1's supplemental run was resumed with
`--force`, which re-runs a stage that had already succeeded; the resumed run then
hit a Fable quota wall, and the failure was written over metas whose records were
already complete. repo-1 documented this in their own commit: "resume without
--force, which is what marked completed extractions failed at the wall."

THE EVIDENCE, and this is the whole safety argument. A record carries its own
`extraction` block with the contract id that produced it. If every record in a
file carries one at the expected contract, then extraction DID finish for that
transcript, whatever the meta says, and the meta is stale rather than truthful.
Where that does not hold, this refuses and says so. It never invents a status
from the absence of evidence.

DRY RUN BY DEFAULT. Nothing is written without --apply.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import predictions_lib as L  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=pathlib.Path, required=True,
                    help="the records directory whose metas may be stale")
    ap.add_argument("--expect-contract", required=True,
                    help="the extraction contract id these records should carry")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    repaired, refused, untouched = [], [], 0
    for meta_path in sorted(args.out.glob("*/*.meta.json")):
        if meta_path.parent.name.startswith("_"):
            continue
        meta = json.loads(meta_path.read_text())
        # A meta needs repair if the stage says it failed OR if it says ok but has
        # lost the audit block the verify stage compares against. The second shape
        # exists because an earlier version of this script repaired the status
        # alone, which is not the field the check reads.
        status = (meta.get("extract") or {}).get("status")
        has_audit = bool((meta.get("extract") or {}).get("audit"))
        if status == "ok" and has_audit:
            untouched += 1
            continue
        jsonl = meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl"))
        tid = f"{meta_path.parent.name}/{jsonl.stem}"
        if not jsonl.exists():
            refused.append((tid, status, "no records file at all"))
            continue
        recs = L.parse_lines(jsonl.read_text(), str(jsonl))
        if not recs:
            refused.append((tid, status, "records file is empty"))
            continue
        cids = {((r.get("extraction") or {}).get("contract_id")) for r in recs}
        if cids != {args.expect_contract}:
            refused.append((tid, status, f"extraction contracts {sorted(c for c in cids if c)}"
                                         f" != expected {args.expect_contract}"))
            continue
        # STATUS IS NOT ENOUGH. The verify stage also compares meta.extract.audit
        # against every record's extraction.telemetry.prediction_audit, and the
        # --force resume overwrote the meta with a bare failure, destroying the
        # audit. The records still carry it, so the audit is recovered from them
        # and only when every record agrees on it byte for byte.
        audits = {json.dumps(((r["extraction"].get("telemetry") or {}).get("prediction_audit") or {}),
                             sort_keys=True) for r in recs}
        if len(audits) != 1 or audits == {"{}"}:
            refused.append((tid, status, f"{len(audits)} distinct prediction_audit blocks across "
                                         f"{len(recs)} records; cannot reconstruct one"))
            continue
        audit = json.loads(next(iter(audits)))
        harnesses = {r["extraction"].get("harness") for r in recs}
        if len(harnesses) != 1:
            refused.append((tid, status, f"records disagree about the extraction harness: {harnesses}"))
            continue
        repaired.append((tid, status, len(recs)))
        if args.apply:
            meta["extract"] = dict(meta["extract"], status="ok",
                                   contract_id=args.expect_contract,
                                   harness=next(iter(harnesses)),
                                   audit=audit,
                                   repaired_from=status,
                                   repaired_because=("every record carries an identical extraction "
                                                     f"block and audit at {args.expect_contract}; a "
                                                     "--force resume hit a quota wall after "
                                                     "extraction had finished and overwrote the meta "
                                                     "with a bare failure, destroying the audit"))
            meta_path.write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")

    print(f"{untouched} metas already ok")
    print(f"\n{len(repaired)} stale, repairable from the records themselves:")
    for tid, st, n in repaired:
        print(f"  {tid}   was {st!r}, {n} records all at {args.expect_contract}")
    print(f"\n{len(refused)} refused, evidence does not support a repair:")
    for tid, st, why in refused:
        print(f"  {tid}   was {st!r}: {why}")
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN, nothing written. Pass --apply.'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
