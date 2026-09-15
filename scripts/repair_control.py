#!/usr/bin/env python3
"""Negative control for the criterion repair stage.

Every one of the 39 flagged records came back "already_correct". That is either
the truth or a rubber stamp, and the two look identical in the output. This
plants BOTH defects into real records, sends them through the same prompt, and
reports whether the stage catches them.

A stage that cannot fail its own control is not evidence of anything.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import criteria_agreement as C  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
from grade import call_fable, extract_json  # noqa: E402


NEGATED = (" will not ", " will never ", " will no longer ")


def undirect(crit: str) -> str:
    """Turn an asserted criterion into one that states no direction."""
    for neg in NEGATED:
        if neg in crit:
            return crit.replace(neg, " will / will not ", 1)
    for verb in (" will have ", " will be ", " will "):
        if verb in crit:
            return crit.replace(verb, verb.replace(" will ", " will / will not "), 1)
    return crit + " -- or will not."


def invert(crit: str) -> str:
    """State the falsification instead of the speaker's claim.

    A criterion that ALREADY carries the speaker's negation is inverted by
    REMOVING it. Adding a second "not" restores the original meaning, so the
    naive mutator would plant nothing and the control would score a false catch.
    """
    for neg in NEGATED:
        if neg in crit:
            return crit.replace(neg, " will ", 1)
    for verb in (" will have ", " will be ", " will "):
        if verb in crit:
            return crit.replace(verb, verb.rstrip() + " not ", 1)
    return "It is not the case that " + crit[0].lower() + crit[1:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", type=Path, default=Path("data/predictions"))
    ap.add_argument("--n", type=int, default=3, help="records to plant each defect into")
    ap.add_argument("--fable-accounts", default="default")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = C.load(args.predictions)
    P2.attach_deadlines(rows, derive=True)
    # Records with a readable deadline and a criterion the mutators can bite on,
    # so the control tests the stage rather than the mutator.
    pool = [r for r in rows
            if r["_deadline"] and " will " in (r["prediction"].get("resolution_criteria") or "")]
    pool.sort(key=lambda r: r["prediction_id"])
    picks = pool[:args.n]
    if len(picks) < args.n:
        raise SystemExit(f"only {len(picks)} usable records; need {args.n}")

    accounts = ["__DEFAULT__" if n.strip() == "default" else str(Path.home() / n.strip())
                for n in args.fable_accounts.split(",") if n.strip()]
    workdir = Path(os.environ.get("TMPDIR", "/tmp")) / "prediction-resolve"
    workdir.mkdir(parents=True, exist_ok=True)

    cases = []
    for i, r in enumerate(picks):
        orig = r["prediction"]["resolution_criteria"]
        for defect, fn in (("undirected", undirect), ("inverted", invert)):
            mutated = fn(orig)
            if mutated == orig:
                print(f"SKIP {r['prediction_id']} {defect}: the mutator changed nothing")
                continue
            cases.append({"rec": r, "defect": defect, "original": orig, "mutated": mutated,
                          "account": accounts[i % len(accounts)]})

    results = []
    for k, case in enumerate(cases, 1):
        r = dict(case["rec"])
        r["prediction"] = dict(r["prediction"], resolution_criteria=case["mutated"])
        prompt = R.build_repair_prompt(r, r["_deadline"], case["rec"]["_verifier_criterion"]
                                       if "_verifier_criterion" in case["rec"] else "", [case["defect"]])
        if args.dry_run:
            print(f"--- case {k}: {case['defect']}\n  was: {case['original']}\n  now: {case['mutated']}")
            continue
        text, _tel = call_fable(prompt, case["account"], args.timeout,
                                workdir=str(workdir / f"control-{k}"))
        obj = extract_json(text)
        errs = L.check_schema(obj, R.REPAIR_SCHEMA) + R.validate_repair(obj, r["prediction_id"])
        caught = obj["verdict"] in ("repaired", "cannot_repair")
        results.append({"defect": case["defect"], "prediction_id": r["prediction_id"],
                        "planted": case["mutated"], "verdict": obj["verdict"],
                        "criterion": obj["criterion"], "reasoning": obj["reasoning"],
                        "schema_errors": errs, "caught": caught})
        print(f"[{k}/{len(cases)}] {case['defect']:10} -> {obj['verdict']:16} "
              f"{'CAUGHT' if caught else 'MISSED'}")
        print(f"          planted: {case['mutated'][:110]}")
        print(f"          returned: {(obj['criterion'] or '(null)')[:110]}")

    if args.dry_run:
        return 0
    by = {}
    for r in results:
        by.setdefault(r["defect"], [0, 0])
        by[r["defect"]][1] += 1
        by[r["defect"]][0] += 1 if r["caught"] else 0
    print("\ncaught / planted, by defect:")
    for d, (c, n) in sorted(by.items()):
        print(f"  {d:12} {c}/{n}")
    missed = [r for r in results if not r["caught"]]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "caught_by_defect": {d: {"caught": c, "planted": n} for d, (c, n) in by.items()},
             "cases": results}, indent=1) + "\n")
        print(f"wrote {args.out}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
