#!/usr/bin/env python3
"""Repair the criteria a resolver could not act on, against the quote.

    .venv/bin/python scripts/repair_criteria.py --out data/predictions/_experiments/<run>

`docs/PREDICTIONS-CRITERIA-AGREEMENT.md` found two defects that a resolver cannot
survive. 18 records state no direction to test, so both answers satisfy them. 8
state the opposite of what the speaker said, so resolving them scores the speaker
backwards. The specification that produced both was repaired in `cfec9e6`, which
governs future extractions; these records already exist and are repaired here.

WHAT THIS SELECTS, and why it is wider than 26. The mechanical screen flags 18
undirected and 21 polarity records, and only 8 of those 21 are real inversions.
The screen cannot tell an inversion from a verifier rider that negates by design.
So all 39 are sent, and the model returns "already_correct" for the ones that are
fine. Letting the model clear a false positive is honest; hand-picking 8 of 21
before the call would be me deciding the answer the screen could not.

The repair is an overlay under the run directory. Records are never edited: this
clone may only write under `data/predictions/_experiments/`, and a record edited
in place would contradict the extraction contract hash it carries.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import criteria_agreement as C  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
from grade import E_CLI, E_TIMEOUT, account_label, call_fable, extract_json  # noqa: E402
from resolve_predictions import E_NOJSON, E_RULES, E_SCHEMA, classify, log, utc_now  # noqa: E402

# The two flags that make a criterion unusable. `threshold_dropped` and the
# deadline flags are disagreements between two models about the SAME claim, which
# is a different problem: the record is still resolvable, just less precisely.
REPAIR_FLAGS = ("undirected_criterion", "polarity")


def select(pred_dir: Path) -> list[dict]:
    rows = C.load(pred_dir)
    P2.attach_deadlines(rows, derive=True)
    out = []
    for r in rows:
        e = (r["prediction"] or {}).get("resolution_criteria") or ""
        v = ((r.get("verification") or {}).get("verifier_resolution_criteria")) or ""
        flags = [f for f in C.compare(e, v) if f in REPAIR_FLAGS]
        if not flags:
            continue
        r["_flags_repair"] = flags
        r["_verifier_criterion"] = v
        out.append(r)
    out.sort(key=lambda r: (r["leader_slug"], r["prediction_id"]))
    return out


def run_one(job: dict) -> dict:
    rec, args = job["rec"], job["args"]
    pid, slug = rec["prediction_id"], rec["leader_slug"]
    # A record with no readable deadline is still repairable: the criterion carries
    # its own date. The prompt says the date is missing rather than showing a
    # placeholder, which a model would read as a real deadline.
    deadline = rec.get("_deadline")
    base = {"prediction_id": pid, "leader_slug": slug, "stage": "repair"}
    t0 = time.time()
    raw_dir = Path(args.out) / "_raw" / "repair" / slug
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        prompt = R.build_repair_prompt(rec, deadline, rec["_verifier_criterion"], rec["_flags_repair"])
        workdir = Path(args.workdir) / f"repair-{pid}"
        workdir.mkdir(parents=True, exist_ok=True)
        text, tel = call_fable(prompt, job["account"], args.timeout, binary=args.fable_bin,
                               workdir=str(workdir), raw_response_path=raw_dir / f"{pid}.txt")
        try:
            obj = extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{E_NOJSON}: {exc}") from exc
        errs = L.check_schema(obj, R.REPAIR_SCHEMA)
        if errs:
            raise RuntimeError(f"{E_SCHEMA}: {'; '.join(errs[:4])}")
        errs = R.validate_repair(obj, pid)
        if errs:
            raise RuntimeError(f"{E_RULES}: {'; '.join(errs[:4])}")

        out = {
            "prediction_id": pid, "leader_slug": slug, "transcript_id": rec["transcript_id"],
            "stage": "repair", "screen_flags": rec["_flags_repair"],
            "criterion_original": rec["prediction"]["resolution_criteria"],
            "criterion_verifier": rec["_verifier_criterion"],
            "verdict": obj["verdict"], "criterion": obj["criterion"], "reasoning": obj["reasoning"],
            "repaired_at_utc": utc_now(), "run_id": args.run_id, "harness": "fable",
            "account": account_label(job["account"]), "telemetry": tel,
        }
        dest = Path(args.out) / "criteria_repairs" / slug / f"{pid}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        return {**base, "ok": True, "summary": obj["verdict"], "seconds": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {**base, "ok": False, "error_type": E_TIMEOUT, "detail": f"no answer in {args.timeout}s",
                "seconds": round(time.time() - t0, 1)}
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)[:500]
        return {**base, "ok": False, "error_type": classify(detail), "detail": detail,
                "seconds": round(time.time() - t0, 1)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", type=Path, default=Path("data/predictions"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--fable-accounts", default="default")
    ap.add_argument("--fable-bin", default="claude")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--dry-run", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("refusing --fable-bin cl: it injects --dangerously-skip-permissions (see CLAUDE.md)")
    rows = select(args.predictions)
    counts: dict[str, int] = {}
    for r in rows:
        for f in r["_flags_repair"]:
            counts[f] = counts.get(f, 0) + 1
    done = set(R.load_repairs(Path(args.out))) if not args.redo else set()
    todo = [r for r in rows if r["prediction_id"] not in done]
    if args.limit is not None:
        todo = todo[:args.limit]
    log(f"flagged={len(rows)} {json.dumps(counts, sort_keys=True)}  done={len(done)}  to run={len(todo)}")

    if args.dry_run:
        if todo:
            r = todo[0]
            print(R.build_repair_prompt(r, r.get("_deadline"), r["_verifier_criterion"],
                                        r["_flags_repair"]))
        return 0
    if not todo:
        log("nothing to do")
        return 0

    args.run_id = f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-repair"
    args.workdir = args.workdir or str(Path(os.environ.get("TMPDIR", "/tmp")) / "prediction-resolve")
    Path(args.workdir).mkdir(parents=True, exist_ok=True)
    accounts = []
    for name in args.fable_accounts.split(","):
        name = name.strip()
        if name:
            accounts.append("__DEFAULT__" if name == "default" else str(Path.home() / name))
    if not accounts:
        raise SystemExit("--fable-accounts named nothing")
    log(f"run_id={args.run_id}  accounts={[account_label(a) for a in accounts]}")

    jobs = [{"rec": r, "args": args, "account": accounts[i % len(accounts)]} for i, r in enumerate(todo)]
    results = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, res in enumerate(ex.map(run_one, jobs), 1):
            results.append(res)
            log(f"[{i}/{len(jobs)}] {res['leader_slug']}/{res['prediction_id']} "
                f"{'ok' if res['ok'] else res['error_type']} "
                f"{res.get('summary', res.get('detail', ''))!s:.80} ({res['seconds']}s)")

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    tax: dict[str, int] = {}
    for r in bad:
        tax[r["error_type"]] = tax.get(r["error_type"], 0) + 1
    verdicts: dict[str, int] = {}
    for r in ok:
        verdicts[r["summary"]] = verdicts.get(r["summary"], 0) + 1
    log(f"\nattempted {len(results)}  succeeded {len(ok)}  failed {len(bad)}")
    log(f"verdicts: {json.dumps(verdicts, sort_keys=True)}")
    log(f"error_taxonomy: {json.dumps(tax, sort_keys=True) if tax else '{}'}")

    sp = Path(args.out) / "_runs" / f"{args.run_id}.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"run_id": args.run_id, "stage": "repair", "flagged": len(rows),
                              "screen_counts": counts, "attempted": len(results), "succeeded": len(ok),
                              "failed": len(bad), "verdicts": verdicts, "error_taxonomy": tax,
                              "finished_at_utc": utc_now()}, indent=1, sort_keys=True) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
