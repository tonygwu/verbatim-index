#!/usr/bin/env python3
"""With early calls on, a prior priced on another prompt still blocks publication.

FOUND 2026-10-05 (overnight review): score_predictions builds corpus.stale_sidecars from the
window check and then appends the prior-prompt check (prior_prompt_stale), but the early-call
block set corpus.stale_sidecars to the window list alone afterwards. With --early-calls on,
as production runs, a row whose prior was priced on another prompt than today's was left
out of the board as stale_sidecar:prior_prompt_changed while the deploy guard
(data_clone_workflow.scores_blockers) saw no stale sidecar and published without it: the
silent drop the guard exists to stop.

A two-record corpus whose resolutions were written under a resolution-policy release beside
priors whose prompt_sha256 is not today's prompt. Runs the real scorer with and without
--early-calls. No quota, no data checkout.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import data_clone_workflow as D  # noqa: E402
import test_restatements_scoring as T  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


with tempfile.TemporaryDirectory() as td:
    d = pathlib.Path(td)
    corpus = d / "predictions"
    (corpus / "ada").mkdir(parents=True)
    (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (T.rec("p1"), T.rec("p3"))))
    index = corpus / "index.json"
    index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
    run = d / "run-a"
    for pid in ("p1", "p3"):
        T.write(run, pid, "resolve", policy_release="resolution-2026-09-30")
        T.write(run, pid, "prior", prompt_sha256="not-todays-prompt")
    for extra in ([], ["--early-calls"]):
        out = d / f"s{len(extra)}.json"
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--predictions",
                            str(corpus), "--index", str(index), "--as-of", "2026-09-16", "--min-lead-days", "60",
                            "--run", str(run), "--policy-release", "legacy", "--policy-release",
                            "resolution-2026-09-30", "--out", str(out), *extra], capture_output=True, text=True)
        tag = "with --early-calls" if extra else "without --early-calls"
        check(f"{tag}: the scorer exits 0", p.returncode == 0, p.stderr[-400:])
        doc = json.loads(out.read_text()) if p.returncode == 0 else {}
        dropped = sorted(r["prediction_id"] for r in doc.get("predictions", [])
                         if r.get("not_scored_because") == "stale_sidecar:prior_prompt_changed")
        stale = sorted({s["prediction_id"] for s in (doc.get("corpus") or {}).get("stale_sidecars") or []})
        check(f"{tag}: both rows are left out as prior_prompt_changed", dropped == ["p1", "p3"], str(dropped))
        check(f"{tag}: corpus.stale_sidecars names every row it left out", stale == dropped, f"{stale} vs {dropped}")
        check(f"{tag}: the deploy guard refuses", bool(D.scores_blockers(doc)), str(D.scores_blockers(doc)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
