#!/usr/bin/env python3
"""Run Phase 2 stage 1 (resolve) or stage 2 (prior) over the past-due corpus.

    .venv/bin/python scripts/resolve_predictions.py --stage resolve \
        --as-of 2026-09-15 --out data/predictions/_experiments/<run>

WHY THE TWO STAGES RUN ON DIFFERENT HARNESSES
---------------------------------------------
This is a deliberate choice and it decides what the numbers can mean.

The RESOLVER runs on Astra, through `codex exec`, because that harness has live
web search. A resolution has to cite something, and a harness that can only
recall cannot cite. `docs/PREDICTIONS-SCORING.md` records that the pilot's
outcomes came from recall with no source, which is the defect this stage exists
to close.

The PRIOR assessor runs on Fable, through `claude` with `--permission-prompts
none`, because that harness is measured to have NO working tools: it is offered
web search, tries it, and is denied, with `web_search_requests: 0`. A prior
assessor that can search would look up what happened, and its answer would stop
being a prior. This does not remove what the model already knows from training.
It removes the ability to go and check, which is the part we can control.

Neither stage writes into a prediction record. `prediction_record.schema.json`
pins `resolution` to exactly `{"status": "not_started"}`, and this clone is an
experiment clone that may only write under `data/predictions/_experiments/`.
Both stages write sidecars under the run directory instead.

EVERY FAILURE GETS A TAXONOMY ENTRY, never a bare count.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import resolution_lib as R  # noqa: E402
from grade import (  # noqa: E402
    E_CLI, E_TIMEOUT, account_label, call_astra, call_fable, extract_json,
)

_log_lock = threading.Lock()

E_NOJSON = "no_json_in_response"
E_SCHEMA = "schema_violation"
E_RULES = "rule_violation"
E_LEAK = "prior_prompt_leak"
ERROR_TYPES = (E_CLI, E_TIMEOUT, E_NOJSON, E_SCHEMA, E_RULES, E_LEAK, "auth_or_quota", "other")


def log(msg: str) -> None:
    with _log_lock:
        print(msg, file=sys.stderr, flush=True)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Selection: exactly the funnel's past-due set, computed by the funnel's own code
# ---------------------------------------------------------------------------

def select(pred_dir: Path, cutoff: dt.date, min_lead: int) -> list[dict]:
    """Past-due accepted predictions, each carrying the funnel's deadline and flags.

    The deadline comes from `phase2_resolvability`, never from a second parser
    here. A partial `target_date` expands to its LAST day, and a resolver told
    "2020" rather than "2020-12-31" would resolve a year-long claim against
    New Year's Day.
    """
    rows = P2.load(pred_dir)
    P2.attach_deadlines(rows, derive=True)
    out = []
    for r in rows:
        if not r["_deadline"] or r["_deadline"] > cutoff:
            continue
        said = P2.iso((r.get("source") or {}).get("statement_date"))
        lead = P2.lead_days(r)
        r["_flags"] = {
            "basis": r["_basis"],
            "deadline_before_statement": bool(said and r["_deadline"] < said),
            "specificity_high": r["prediction"].get("specificity") == "high",
            "lead_days": lead,
            "lead_ok": lead is not None and lead >= min_lead,
        }
        # The three together are the operator's eligibility rule: a real forecast
        # is specific, reaches at least six months out, and has a coherent window.
        r["_flags"]["eligible"] = (r["_flags"]["specificity_high"] and r["_flags"]["lead_ok"]
                                   and not r["_flags"]["deadline_before_statement"])
        out.append(r)
    out.sort(key=lambda r: (r["leader_slug"], r["prediction_id"]))
    return out


# ---------------------------------------------------------------------------
# One job
# ---------------------------------------------------------------------------

def classify(detail: str) -> str:
    d = detail.lower()
    if "timeout" in d or "timed out" in d:
        return E_TIMEOUT
    if any(k in d for k in ("401", "quota", "rate limit", "usage limit", "not logged in", "auth")):
        return "auth_or_quota"
    for e in (E_NOJSON, E_SCHEMA, E_RULES, E_LEAK, E_CLI):
        if detail.startswith(e):
            return e
    return "other"


def run_one(job: dict) -> dict:
    rec, args, stage = job["rec"], job["args"], job["stage"]
    pid, slug = rec["prediction_id"], rec["leader_slug"]
    deadline = rec["_deadline"]
    base = {"prediction_id": pid, "leader_slug": slug, "stage": stage}
    t0 = time.time()

    raw_dir = Path(args.out) / "_raw" / stage / slug
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{pid}.txt"

    try:
        if stage == "resolve":
            prompt = R.build_resolver_prompt(rec, deadline, args.as_of)
            leaks = []
            workdir = Path(args.workdir) / f"astra-{pid}"
            workdir.mkdir(parents=True, exist_ok=True)
            env_home = job["account"]
            # CODEX_HOME is set on the CHILD through `env`, never on this process.
            # An earlier version mutated os.environ under a lock so concurrent jobs
            # could not race it, which serialised the whole stage: five workers ran
            # one call at a time and the run was on course to take twelve hours.
            # A per-process variable needs no lock and no shared state.
            wrapper = ["/usr/bin/env", f"CODEX_HOME={env_home}"] if env_home else None
            text, tel = call_astra(prompt, args.timeout, workdir, model=args.astra_model,
                                   raw_response_path=raw_path, wrapper=wrapper)
            harness, account = "astra", account_label(env_home or "__DEFAULT__")
        else:
            prompt = R.build_prior_prompt(rec, deadline)
            # Masked with the record's own quoted text, so only the authored part
            # of the prompt is screened. See prior_prompt_leaks.
            leaks = R.prior_prompt_leaks(prompt, R.prompt_facts(rec, deadline))
            if leaks:
                # The quote and this repo's own claim text are not under our
                # control, so a leak is refused per record rather than assumed away.
                raise RuntimeError(f"{E_LEAK}: prior prompt carries outcome vocabulary {leaks}")
            workdir = Path(args.workdir) / f"fable-{pid}"
            workdir.mkdir(parents=True, exist_ok=True)
            text, tel = call_fable(prompt, job["account"], args.timeout, binary=args.fable_bin,
                                   workdir=str(workdir), raw_response_path=raw_path)
            harness, account = "fable", account_label(job["account"])

        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
        try:
            obj = extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{E_NOJSON}: {exc}") from exc

        schema = R.RESOLUTION_SCHEMA if stage == "resolve" else R.PRIOR_SCHEMA
        errs = L.check_schema(obj, schema)
        if errs:
            raise RuntimeError(f"{E_SCHEMA}: {'; '.join(errs[:4])}")
        errs = (R.validate_resolution(obj, pid) if stage == "resolve" else R.validate_prior(obj, pid))
        if errs:
            raise RuntimeError(f"{E_RULES}: {'; '.join(errs[:4])}")

        if stage == "resolve":
            out = R.resolution_record(rec, deadline, obj, run_id=args.run_id, harness=harness,
                                      account=account, telemetry=tel, resolved_at=utc_now(),
                                      as_of=args.as_of)
        else:
            out = R.prior_record(rec, deadline, obj, run_id=args.run_id, harness=harness,
                                 account=account, telemetry=tel, assessed_at=utc_now(),
                                 prompt_sha=prompt_sha, leaks=leaks)
        out["funnel_flags"] = rec["_flags"]
        dest = R.sidecar_path(Path(args.out), stage, slug, pid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        base.update(ok=True, seconds=round(time.time() - t0, 1),
                    summary=(obj["outcome"] if stage == "resolve" else obj["p"]))
        return base

    except subprocess.TimeoutExpired:
        return {**base, "ok": False, "error_type": E_TIMEOUT,
                "detail": f"no answer in {args.timeout}s", "seconds": round(time.time() - t0, 1)}
    except Exception as exc:  # noqa: BLE001 - every failure is classified, never swallowed
        detail = str(exc)[:500]
        return {**base, "ok": False, "error_type": classify(detail), "detail": detail,
                "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["resolve", "prior"], required=True)
    ap.add_argument("--predictions", type=Path, default=Path("data/predictions"))
    ap.add_argument("--out", type=Path, required=True, help="the experiment run directory")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD; what counts as past due, never the clock")
    ap.add_argument("--min-lead-days", type=int, default=P2.MIN_LEAD_DAYS)
    ap.add_argument("--eligible-only", action="store_true",
                    help="only the records that clear specificity, lead time and a coherent window")
    ap.add_argument("--slug", action="append", default=None, help="restrict to these leaders")
    ap.add_argument("--limit", type=int, default=None, help="first N jobs, for a pilot")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--redo", action="store_true", help="re-run records that already have a sidecar")
    ap.add_argument("--fable-accounts", default="default",
                    help="comma-separated CLAUDE_CONFIG_DIR names with measured Fable headroom")
    ap.add_argument("--codex-homes", default="",
                    help="comma-separated CODEX_HOME paths; empty uses the ambient one")
    ap.add_argument("--fable-bin", default="claude")
    ap.add_argument("--astra-model", default="gpt-6-astra")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--errors", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true", help="print the selection and one prompt, spend nothing")
    return ap


def accounts_for(args) -> list[str]:
    if args.stage == "prior":
        out = []
        for name in args.fable_accounts.split(","):
            name = name.strip()
            if not name:
                continue
            out.append("__DEFAULT__" if name == "default" else str(Path.home() / name))
        if not out:
            raise SystemExit("--fable-accounts named nothing")
        for a in out:
            if a != "__DEFAULT__" and not Path(a).is_dir():
                raise SystemExit(f"no such Claude config dir: {a}")
        return out
    homes = [h.strip() for h in args.codex_homes.split(",") if h.strip()]
    for h in homes:
        if not Path(h).expanduser().is_dir():
            raise SystemExit(f"no such CODEX_HOME: {h}")
    return [str(Path(h).expanduser()) for h in homes] or [""]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("refusing --fable-bin cl: it injects --dangerously-skip-permissions (see CLAUDE.md)")
    try:
        cutoff = dt.date.fromisoformat(args.as_of)
    except ValueError:
        raise SystemExit(f"--as-of {args.as_of!r} is not a YYYY-MM-DD date")

    rows = select(args.predictions, cutoff, args.min_lead_days)
    if args.slug:
        rows = [r for r in rows if r["leader_slug"] in set(args.slug)]
    if args.eligible_only:
        rows = [r for r in rows if r["_flags"]["eligible"]]

    out_root = Path(args.out)
    done = set(R.load_sidecars(out_root, args.stage)) if not args.redo else set()
    todo = [r for r in rows if r["prediction_id"] not in done]
    if args.limit is not None:
        todo = todo[:args.limit]

    n_elig = sum(1 for r in rows if r["_flags"]["eligible"])
    log(f"stage={args.stage}  as-of={args.as_of}  selected={len(rows)} "
        f"({n_elig} eligible)  already done={len(done)}  to run={len(todo)}")

    if args.dry_run:
        if todo:
            r = todo[0]
            p = (R.build_resolver_prompt(r, r["_deadline"], args.as_of) if args.stage == "resolve"
                 else R.build_prior_prompt(r, r["_deadline"]))
            print(p)
            print(f"--- prompt chars: {len(p)}  leak words: "
                  f"{R.prior_prompt_leaks(p, R.prompt_facts(r, r['_deadline']))}", file=sys.stderr)
        return 0
    if not todo:
        log("nothing to do")
        return 0

    args.run_id = f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{args.stage}"
    args.workdir = args.workdir or str(Path(os.environ.get("TMPDIR", "/tmp")) / "prediction-resolve")
    Path(args.workdir).mkdir(parents=True, exist_ok=True)
    accounts = accounts_for(args)
    log(f"run_id={args.run_id}  accounts={[account_label(a) if a else 'ambient' for a in accounts]}")

    jobs = [{"rec": r, "args": args, "stage": args.stage,
             "account": accounts[i % len(accounts)]} for i, r in enumerate(todo)]

    results = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, res in enumerate(ex.map(run_one, jobs), 1):
            results.append(res)
            mark = "ok" if res["ok"] else res["error_type"]
            log(f"[{i}/{len(jobs)}] {res['leader_slug']}/{res['prediction_id']} "
                f"{mark} {res.get('summary', res.get('detail', ''))!s:.90} ({res['seconds']}s)")

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    tax = {}
    for r in bad:
        tax[r["error_type"]] = tax.get(r["error_type"], 0) + 1
    log(f"\nattempted {len(results)}  succeeded {len(ok)}  failed {len(bad)}")
    log(f"error_taxonomy: {json.dumps(tax, sort_keys=True) if tax else '{}'}")

    if args.errors and bad:
        args.errors.parent.mkdir(parents=True, exist_ok=True)
        with args.errors.open("a") as fh:
            for r in bad:
                fh.write(json.dumps({**r, "run_id": args.run_id, "at": utc_now()}) + "\n")

    summary = {"run_id": args.run_id, "stage": args.stage, "as_of": args.as_of,
               "selected": len(rows), "eligible": n_elig, "attempted": len(results),
               "succeeded": len(ok), "failed": len(bad), "error_taxonomy": tax,
               "finished_at_utc": utc_now()}
    sp = out_root / "_runs" / f"{args.run_id}.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
