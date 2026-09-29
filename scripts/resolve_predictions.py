#!/usr/bin/env python3
"""Run Phase 2 stage 1 (resolve) or stage 2 (prior) over the past-due corpus.

    .venv/bin/python scripts/resolve_predictions.py --stage resolve \
        --as-of 2026-09-15 --out data/predictions/_experiments/<run>

Only ELIGIBLE records run by default; `--include-ineligible` opts out, and every
record left out is counted by its reason. `--ids FILE` runs only the named
records, for re-running them into a new run, and refuses any the stage would not
run. A re-run's sidecars then need an entry in the scorer's replacement manifest
(score_predictions.read_replacements), or the scorer refuses the duplicate.

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
import collections
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
from data_clone_workflow import load_scoring_config  # noqa: E402
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

def select(pred_dir, cutoff: dt.date, min_lead: int, trend: bool = False,
           resolutions: dict | None = None,
           date_overrides: "dict | None" = None, superseded: "list | None" = None,
           window_conflicts: "dict[str, list[str]] | None" = None) -> list[dict]:
    """Past-due accepted predictions, each carrying the funnel's deadline and flags.

    The deadline comes from `phase2_resolvability`, never from a second parser
    here. A partial `target_date` expands to its LAST day, and a resolver told
    "2020" rather than "2020-12-31" would resolve a year-long claim against
    New Year's Day.

    `resolutions` (sidecars by prediction_id) freezes each RESOLVED trend
    record's window at the `deadline` its resolution judged (operator decision,
    2026-09-27). A later cutoff does not move it, so no stage prices, re-resolves
    or scores it over a window that grew. An unresolved trend record still runs
    to `cutoff`, and a dated record is untouched.

    `window_conflicts` names predictions whose resolution sidecars record more
    than one window, each entry "<deadline> in <run>". A TREND record among them
    is refused before the cutoff is applied, so a grown window can neither be
    judged nor drop the record silently: nothing here picks which window came
    first. A dated record's deadline comes from its own words, not a sidecar, so
    it is unaffected. The resolver fills this from every run it reads
    (resolutions_across), the scorer from the sidecars a replacement manifest
    replaces.
    """
    rows = P2.load(pred_dir, date_overrides=date_overrides, superseded=superseded)
    # The trend window is opt-in and dated by the caller's cutoff, never the clock.
    P2.attach_deadlines(rows, derive=True, trend_cutoff=(cutoff if trend else None))
    for r in rows:
        if not str(r.get("_basis") or "").startswith("trend"):
            continue
        clash = (window_conflicts or {}).get(r["prediction_id"])
        if clash:
            raise SystemExit(f"trend prediction {r['prediction_id']}'s window froze at its first resolution, and "
                             f"its resolution sidecars record different windows: {'; '.join(clash)}. A re-run of "
                             f"a resolved trend record judges that same window (operator decision, 2026-09-27); "
                             f"re-run it over the first window, or remove the sidecar that judged another")
        res = (resolutions or {}).get(r["prediction_id"])
        if res is None:
            continue
        try:
            frozen = dt.date.fromisoformat(str(res.get("deadline")))
        except ValueError:
            raise SystemExit(f"trend prediction {r['prediction_id']} has a resolution with no usable "
                             f"deadline ({res.get('deadline')!r}); its window cannot be frozen, and the "
                             f"as-of is never substituted for it") from None
        d, why = P2.trend_window(r, frozen)
        if d is None:
            raise SystemExit(f"trend prediction {r['prediction_id']} was resolved over a window to "
                             f"{frozen} that is not a trend window today ({why})")
        r["_deadline"], r["_basis"] = frozen, f"trend: {why}, frozen at its first resolution"
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
            "specificity_ok": r["prediction"].get("specificity") in P2.ELIGIBLE_SPECIFICITY,
            "lead_days": lead,
            "lead_ok": lead is not None and lead >= min_lead,
        }
        # The three together are the operator's eligibility rule: a real forecast
        # is specific enough (P2.ELIGIBLE_SPECIFICITY, high or medium since
        # 2026-09-27), reaches at least min_lead days out, and has a coherent window.
        is_trend = str(r.get("_basis") or "").startswith("trend")
        r["_flags"]["trend"] = is_trend
        # A trend window IS the elapsed time, so the lead-time floor is already
        # satisfied by construction and specificity is not what makes it testable.
        r["_flags"]["eligible"] = (is_trend or
                                   (r["_flags"]["specificity_ok"] and r["_flags"]["lead_ok"]
                                    and not r["_flags"]["deadline_before_statement"]))
        out.append(r)
    out.sort(key=lambda r: (r["leader_slug"], r["prediction_id"]))
    return out


SCORING_CONFIG_FILE = Path("predictions") / "scoring.json"


def scoring_runs_for(arg: "Path | None", predictions: list[Path]) -> "tuple[Path | None, list[Path]]":
    """(config path, runs) of the scoring config, whose resolutions freeze trend windows.

    A trend record's window freezes at its FIRST resolution, in whichever run
    wrote it (operator decision, 2026-09-27). The first version read only --out,
    so --ids into a new run judged a record resolved in an older run up to the
    new as-of. The runs are the scoring config's, which are every run the
    published scores read. Found like date_overrides_for: an explicit file must
    exist, and the production default, <data>/predictions/scoring.json beside
    the first --predictions, is read whenever it exists. A run it names that is
    not on disk is refused, because its windows cannot be read.
    """
    root = Path(predictions[0]).resolve().parent
    path = Path(arg) if arg is not None else root / SCORING_CONFIG_FILE
    if not path.exists():
        if arg is not None:
            raise SystemExit(f"--scoring-config {arg} does not exist")
        return None, []
    cfg_root, cfg = load_scoring_config(path)
    runs = [cfg_root / r for r in cfg["runs"]]
    gone = [str(r) for r in runs if not r.is_dir()]
    if gone:
        raise SystemExit(f"{path} names runs that do not exist: {gone}; their resolutions freeze trend "
                         f"windows, so they must be read")
    return path, runs


def resolutions_across(runs: list[Path]) -> "tuple[dict[str, dict], dict[str, list[str]]]":
    """(one resolution per prediction, predictions whose runs record different windows).

    A prediction resolved in several runs is kept once. When the runs record
    different deadlines it is also named in the second dict, each deadline with
    its run, and select() refuses it if it is a trend record. Nothing here picks
    which run came first. A run named twice is read once.
    """
    first: dict[str, dict] = {}
    where: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    seen: set[Path] = set()
    for run in runs:
        if Path(run).resolve() in seen:
            continue
        seen.add(Path(run).resolve())
        for pid, obj in R.load_sidecars(Path(run), "resolve").items():
            first.setdefault(pid, obj)
            where[pid].append((str(obj.get("deadline")), str(run)))
    clash = {pid: [f"{d} in {run}" for d, run in ws] for pid, ws in where.items() if len({d for d, _ in ws}) > 1}
    return first, clash


def read_ids(path: Path) -> list[str]:
    """The prediction ids in an --ids file, one per line, in file order.

    A blank line is skipped. A line holding anything but one id, a repeated id,
    and a file naming nothing are refused: each usually means the list is not
    the one the operator meant to pass.
    """
    if not Path(path).is_file():
        raise SystemExit(f"--ids {path} does not exist")
    ids: list[str] = []
    for n, line in enumerate(Path(path).read_text().split("\n"), 1):
        s = line.strip()
        if not s:
            continue
        if len(s.split()) != 1:
            raise SystemExit(f"--ids {path} line {n} holds {s!r}; one prediction id per line")
        if s in ids:
            raise SystemExit(f"--ids {path} names {s} twice")
        ids.append(s)
    if not ids:
        raise SystemExit(f"--ids {path} names no prediction id")
    return ids


def narrow(rows: list[dict], slugs: "list[str] | None", include_ineligible: bool,
           ids: "list[str] | None") -> tuple[list[dict], collections.Counter]:
    """The rows a stage runs over, and the ineligible rows it left out, by reason.

    Ineligible records are left out unless `include_ineligible`: the scorer never
    scores them, so resolving or pricing them spends calls on nothing. Each one
    left out is counted by its reason and the count is printed.

    With `ids`, only the named records run, and every named record MUST run: one
    that is not past due, belongs to another --slug, or is ineligible without
    the opt-out is refused with its reason rather than skipped.
    """
    named = set(ids) if ids is not None else None
    wanted = set(slugs) if slugs else None
    out, left_out, why_not = [], collections.Counter(), {}
    for r in rows:
        pid = r["prediction_id"]
        if named is not None and pid not in named:
            continue
        if wanted is not None and r["leader_slug"] not in wanted:
            why_not[pid] = f"is {r['leader_slug']}'s, outside --slug {sorted(wanted)}"
            continue
        # The one rule and order the scorer and the page also read
        # (phase2_resolvability.INELIGIBLE_REASONS).
        reason = P2.ineligible_reason(pid, r["_flags"])
        if reason is not None and not include_ineligible:
            left_out[reason] += 1
            why_not[pid] = f"is not eligible ({reason}); pass --include-ineligible to run it anyway"
            continue
        out.append(r)
    if named is not None:
        kept = {r["prediction_id"] for r in out}
        refused = [f"{pid} {why_not.get(pid, 'is no accepted record past due at --as-of')}"
                   for pid in ids if pid not in kept]
        if refused:
            raise SystemExit(f"--ids names {len(refused)} prediction(s) this stage will not run: "
                             + "; ".join(refused))
    return out, left_out


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
    ap.add_argument("--predictions", type=Path, action="append", default=None,
                    help="a corpus directory; repeat it to score several corpora together")
    ap.add_argument("--out", type=Path, required=True, help="the experiment run directory")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD; what counts as past due, never the clock")
    ap.add_argument("--min-lead-days", type=int, default=P2.MIN_LEAD_DAYS)
    ap.add_argument("--trend", action="store_true",
                    help="also score undated DIRECTIONAL claims at least "
                         "MIN_TREND_YEARS old, over the elapsed window")
    # Eligible only is the DEFAULT (design 3.5, rescue round 4): phase2-scoring-20260915
    # spent resolution calls on records the scorer can never score. --eligible-only
    # still parses, so a written-down command keeps working, and means the default.
    ap.add_argument("--eligible-only", action="store_true",
                    help="the default: only the records that clear specificity, lead time and a "
                         "coherent window")
    ap.add_argument("--include-ineligible", action="store_true",
                    help="also run records the scorer will not score; they are left out by default")
    ap.add_argument("--ids", type=Path, default=None,
                    help="a file of prediction ids, one per line; run only those, and refuse any the "
                         "stage would not run. For re-running named records into a new run")
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
    ap.add_argument("--date-overrides", type=Path, default=None,
                    help=f"reviewed statement-date override file; default <data>/{L.DATE_OVERRIDES_FILE} "
                         f"beside the first --predictions when it exists")
    ap.add_argument("--scoring-config", type=Path, default=None,
                    help=f"the scoring config whose runs, with --out, freeze every resolved trend record's "
                         f"window at its first resolution; default <data>/{SCORING_CONFIG_FILE} beside the "
                         f"first --predictions when it exists")
    return ap


def date_overrides_for(arg: "Path | None", predictions: list[Path]) -> "tuple[Path | None, dict]":
    """(path, overrides) for the corpus at `predictions`. Shared by resolve and score.

    The data root is the parent of the first predictions directory. An explicit
    file must exist; the production default is read whenever it exists, so a
    committed override is never silently ignored.
    """
    root = Path(predictions[0]).resolve().parent
    path = arg if arg is not None else root / L.DATE_OVERRIDES_FILE
    if not Path(path).exists():
        if arg is not None:
            raise SystemExit(f"--date-overrides {arg} does not exist")
        return None, {}
    return Path(path), L.load_statement_date_overrides(path, [root / d for d in L.TRANSCRIPT_DIRS])


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
    args.predictions = args.predictions or [Path("data/predictions")]
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("refusing --fable-bin cl: it injects --dangerously-skip-permissions (see CLAUDE.md)")
    if args.eligible_only and args.include_ineligible:
        raise SystemExit("--eligible-only and --include-ineligible contradict each other; pass one")
    try:
        cutoff = dt.date.fromisoformat(args.as_of)
    except ValueError:
        raise SystemExit(f"--as-of {args.as_of!r} is not a YYYY-MM-DD date")
    ids = read_ids(args.ids) if args.ids is not None else None
    # Hashed when read, not when the run ends hours later, so it names the list that ran.
    ids_sha = hashlib.sha256(Path(args.ids).read_bytes()).hexdigest() if args.ids is not None else None

    out_root = Path(args.out)
    ov_path, date_overrides = date_overrides_for(args.date_overrides, args.predictions)
    log(f"date overrides: {ov_path or 'none'} ({len(date_overrides)} entries)")
    # Trend windows freeze from the resolutions in EVERY run the scores read, not
    # only --out, so --ids into a new run judges a resolved record's first window.
    cfg_path, freeze_runs = scoring_runs_for(args.scoring_config, args.predictions)
    resolutions, clash = resolutions_across(freeze_runs + [out_root])
    log(f"trend windows: frozen from {len(resolutions)} resolutions in {len(freeze_runs)} run(s) of "
        f"{cfg_path or 'no scoring config'} and in --out")
    rows = select(args.predictions, cutoff, args.min_lead_days, trend=args.trend,
                  resolutions=resolutions, window_conflicts=clash,
                  date_overrides=date_overrides if ov_path else None)
    rows, left_out = narrow(rows, args.slug, args.include_ineligible, ids)
    if left_out:
        log(f"left out {sum(left_out.values())} ineligible, by reason {json.dumps(dict(sorted(left_out.items())))}; "
            f"pass --include-ineligible to run them")

    done = set(R.load_sidecars(out_root, args.stage)) if not args.redo else set()
    if ids is not None and done & set(ids):
        # Named, and still skipped because this run already holds a result for them.
        log(f"--ids: {sorted(done & set(ids))} already have a {args.stage} result in {out_root}; "
            f"pass --redo to run them again")
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
               # What the run was restricted to and what it left out, which stderr
               # alone used to carry. Written even when empty or absent, so a
               # reader can tell "none" from a summary that predates the field.
               "include_ineligible": args.include_ineligible,
               "left_out_ineligible": dict(sorted(left_out.items())),
               "ids_file": str(args.ids) if args.ids is not None else None,
               "ids_sha256": ids_sha,
               "finished_at_utc": utc_now()}
    sp = out_root / "_runs" / f"{args.run_id}.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
