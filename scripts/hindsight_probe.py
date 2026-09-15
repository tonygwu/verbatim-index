#!/usr/bin/env python3
"""How much does knowing the outcome move the prior? Measured, not assumed.

    .venv/bin/python scripts/hindsight_probe.py --run <run> --as-of 2026-09-14 --n 20

The prior stage is blind BY CONSTRUCTION: `build_prior_prompt` reads a fixed list
of fields and cannot reach a resolution, and the harness it runs on has no working
tools. Neither of those removes what the model already knows from training, and
220 of the 225 past-due predictions fall inside its knowledge cutoff. So the
blindness of the published p is a claim that needs a number beside it.

THE PROBE. Take resolved predictions and ask the SAME model for p a second time,
with the outcome disclosed in the prompt. Compare.

HOW TO READ IT. Let d = p(told) - p(blind), signed so that a positive d means the
disclosure pushed p toward what happened.

  d LARGE   Outcome knowledge moves this model a lot, and the blind run did not
            already have it. The wall is doing work, and the published p is
            closer to ex-ante than to hindsight.
  d NEAR 0  Either the model already knew the outcome while blind, or its prior
            is insensitive to being told. These two look identical here, so a
            small d is NOT evidence of blindness, and is reported as ambiguous.

A second, cheaper reading needs no extra call: the blind p of predictions that
came true, against the blind p of those that did not. A perfectly peeking
assessor would separate them completely. Real foresight also separates them, so
this bounds the leak from above rather than measuring it.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
from grade import account_label, call_fable, extract_json  # noqa: E402
from resolve_predictions import log, select, utc_now  # noqa: E402

DISCLOSURE = """
IMPORTANT, AND DIFFERENT FROM THE USUAL TASK: you are told below what actually
happened. Use it. Give the probability you now think a well-informed observer
SHOULD have assigned on the statement date, with the benefit of knowing how it
turned out. This is a deliberate hindsight condition for a measurement.

WHAT ACTUALLY HAPPENED: the prediction {verdict}.
"""


def build_told_prompt(rec, deadline, outcome: str) -> str:
    """The blind prompt with the answer appended. Identical up to the disclosure,
    so the difference between the two runs is the disclosure and nothing else."""
    base = R.build_prior_prompt(rec, deadline)
    verdict = "CAME TRUE" if outcome == "occurred" else "DID NOT COME TRUE"
    return base + DISCLOSURE.format(verdict=verdict) + "\nAnswer with the JSON object now.\n"


def one(job):
    rec, args = job["rec"], job["args"]
    pid = rec["prediction_id"]
    try:
        prompt = build_told_prompt(rec, rec["_deadline"], job["outcome"])
        workdir = Path(args.workdir) / f"hind-{pid}"
        workdir.mkdir(parents=True, exist_ok=True)
        text, _tel = call_fable(prompt, job["account"], args.timeout, workdir=str(workdir))
        obj = extract_json(text)
        errs = L.check_schema(obj, R.PRIOR_SCHEMA) + R.validate_prior(obj, pid)
        if errs:
            return {"prediction_id": pid, "ok": False, "detail": "; ".join(errs[:3])}
        return {"prediction_id": pid, "ok": True, "p_told": float(obj["p"]),
                "reasoning": obj["reasoning"]}
    except Exception as exc:  # noqa: BLE001
        return {"prediction_id": pid, "ok": False, "detail": str(exc)[:300]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, default=Path("data/predictions"))
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--fable-accounts", default="default")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    args.workdir = args.workdir or str(Path(os.environ.get("TMPDIR", "/tmp")) / "prediction-resolve")

    rows = {r["prediction_id"]: r for r in select(args.predictions, dt.date.fromisoformat(args.as_of), 180)}
    resolutions = R.load_sidecars(args.run, "resolve")
    priors = R.load_sidecars(args.run, "prior")

    pairs = [(pid, resolutions[pid], priors[pid]) for pid in sorted(resolutions)
             if pid in priors and resolutions[pid]["outcome"] in ("occurred", "not_occurred")]
    if not pairs:
        raise SystemExit("no prediction has both a resolution and a prior yet")

    # The free reading first: it costs nothing and is computed over EVERY pair,
    # not just the sampled ones.
    occ = [pr["p"] for _p, rs, pr in pairs if rs["outcome"] == "occurred"]
    nocc = [pr["p"] for _p, rs, pr in pairs if rs["outcome"] == "not_occurred"]
    print(f"blind priors over all {len(pairs)} resolved pairs:")
    print(f"  came true      n={len(occ):3}  mean p {statistics.mean(occ):.3f}" if occ else "  came true      n=0")
    print(f"  did not        n={len(nocc):3}  mean p {statistics.mean(nocc):.3f}" if nocc else "  did not        n=0")
    gap = (statistics.mean(occ) - statistics.mean(nocc)) if occ and nocc else None
    if gap is not None:
        print(f"  separation     {gap:+.3f}   (an upper bound on leakage: real foresight separates these too)")

    sample = pairs[:args.n]
    accounts = ["__DEFAULT__" if n.strip() == "default" else str(Path.home() / n.strip())
                for n in args.fable_accounts.split(",") if n.strip()]
    jobs = [{"rec": rows[pid], "args": args, "outcome": rs["outcome"],
             "account": accounts[i % len(accounts)]}
            for i, (pid, rs, _pr) in enumerate(sample)]
    log(f"\nasking again WITH the outcome disclosed, on {len(jobs)} of them")

    told = {}
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, res in enumerate(ex.map(one, jobs), 1):
            if res["ok"]:
                told[res["prediction_id"]] = res["p_told"]
            log(f"[{i}/{len(jobs)}] {res['prediction_id']} "
                f"{res.get('p_told', res.get('detail', ''))!s:.70}")

    cases = []
    for pid, rs, pr in sample:
        if pid not in told:
            continue
        # Signed so a positive d means the disclosure pushed p TOWARD what happened.
        raw = told[pid] - pr["p"]
        cases.append({"prediction_id": pid, "leader_slug": rs["leader_slug"],
                      "outcome": rs["outcome"], "p_blind": pr["p"], "p_told": told[pid],
                      "d_raw": round(raw, 4),
                      "d_toward": round(raw if rs["outcome"] == "occurred" else -raw, 4)})
    if not cases:
        raise SystemExit("every disclosed call failed; nothing to compare")

    d = [c["d_toward"] for c in cases]
    mean_d, n = statistics.mean(d), len(d)
    sd = statistics.stdev(d) if n > 1 else 0.0
    se = sd / (n ** 0.5) if n > 1 else 0.0
    print(f"\nd = p(told) - p(blind), signed toward what happened, n={n}")
    print(f"  mean {mean_d:+.3f}   sd {sd:.3f}   se {se:.3f}   95% CI [{mean_d - 1.96 * se:+.3f}, {mean_d + 1.96 * se:+.3f}]")
    print(f"  moved toward the outcome in {sum(1 for x in d if x > 0.001)} of {n}, "
          f"away in {sum(1 for x in d if x < -0.001)}, unchanged in {sum(1 for x in d if abs(x) <= 0.001)}")
    verdict = ("the disclosure moves p substantially, so the blind run was not already using the outcome"
               if mean_d - 1.96 * se > 0.05 else
               "AMBIGUOUS: a small shift cannot tell 'already knew' from 'insensitive to being told'")
    print(f"  reading: {verdict}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "generated_at_utc": utc_now(), "as_of": args.as_of, "n_pairs_available": len(pairs),
            "blind_mean_p_occurred": statistics.mean(occ) if occ else None,
            "blind_mean_p_not_occurred": statistics.mean(nocc) if nocc else None,
            "blind_separation": gap, "n_disclosed": n, "mean_d_toward": mean_d, "sd": sd, "se": se,
            "ci95": [mean_d - 1.96 * se, mean_d + 1.96 * se], "reading": verdict, "cases": cases,
        }, indent=1) + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
