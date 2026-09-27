#!/usr/bin/env python3
"""`score_predictions.py --run` may be repeated, so two runs score as one corpus.

Why this exists: the production resolutions and priors live in one experiment run,
and a later pass over new people writes its sidecars into a run of its own, because
an experiment clone may only write under its own `_experiments/<run>/`. Scoring the
whole board then needs both runs read together, without copying sidecars from one
run into the other and blurring which pass produced them.

What this pins, end to end through the CLI:
  - sidecars from two runs are joined, so a prediction resolved in either scores;
  - the SAME prediction in two runs is refused, naming it, never silently
    resolved by whichever run was read last;
  - every run read is recorded in scores.json under `run_dirs`, and `run_dir`
    keeps its old meaning, the first run, so an existing reader is unaffected;
  - one `--run` behaves exactly as before.
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
import resolution_lib as R  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "prediction": {"target_date": "2020-12-31", "specificity": "high", "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": "c", "resolution_criteria": "crit"},
        "source": {"statement_date": "2019-01-01", "quote": "q"},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def write_pair(run: pathlib.Path, pid: str, outcome: str, p: float) -> None:
    res = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "resolve",
           "outcome": outcome, "confidence": "high", "unresolvable_reason": None, "reasoning": "r",
           "sources": [{"where": "u", "what_it_shows": "w", "date": None}], "deadline": "2020-12-31"}
    pri = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "prior",
           "p": p, "p_raw": p, "clamped": False, "reference_class": "rc", "reasoning": "r"}
    for stage, obj in (("resolve", res), ("prior", pri)):
        fp = R.sidecar_path(run, stage, "ada", pid)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(obj))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        corpus = d / "predictions"
        (corpus / "ada").mkdir(parents=True)
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(rec(p)) + "\n" for p in ("p1", "p2")))
        index = d / "index.json"
        index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        a, b, dup = d / "run-a", d / "run-b", d / "run-dup"
        write_pair(a, "p1", "occurred", 0.5)
        write_pair(b, "p2", "not_occurred", 0.5)
        write_pair(dup, "p1", "not_occurred", 0.5)

        def score(*runs, out):
            argv = [sys.executable, str(ROOT / "scripts" / "score_predictions.py"),
                    "--predictions", str(corpus), "--index", str(index), "--as-of", "2026-09-16",
                    "--out", str(out)]
            for r in runs:
                argv += ["--run", str(r)]
            return subprocess.run(argv, capture_output=True, text=True)

        one = score(a, out=d / "one.json")
        check("ONE RUN: exits 0", one.returncode == 0, one.stderr[-600:])
        doc1 = json.loads((d / "one.json").read_text()) if one.returncode == 0 else {}
        check("ONE RUN: only the prediction resolved in that run scores",
              doc1.get("corpus", {}).get("scored") == 1, str(doc1.get("corpus")))
        check("ONE RUN: run_dir is the run, as before", doc1.get("run_dir") == str(a), str(doc1.get("run_dir")))

        both = score(a, b, out=d / "both.json")
        check("TWO RUNS: exits 0", both.returncode == 0, both.stderr[-600:])
        doc2 = json.loads((d / "both.json").read_text()) if both.returncode == 0 else {}
        c = doc2.get("corpus", {})
        check("TWO RUNS: a prediction resolved in either run scores",
              c.get("scored") == 2 and c.get("resolutions_present") == 2 and c.get("priors_present") == 2, str(c))
        check("TWO RUNS: every run read is recorded, in the order given",
              doc2.get("run_dirs") == [str(a), str(b)], str(doc2.get("run_dirs")))
        check("TWO RUNS: run_dir keeps its meaning, the first run", doc2.get("run_dir") == str(a))

        clash = score(a, dup, out=d / "clash.json")
        check("DUPLICATE: the same prediction in two runs is refused",
              clash.returncode != 0 and not (d / "clash.json").exists(), f"rc={clash.returncode}")
        check("DUPLICATE: the refusal names the prediction and both runs",
              "p1" in clash.stderr and str(a) in clash.stderr and str(dup) in clash.stderr, clash.stderr[-600:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
