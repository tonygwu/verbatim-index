#!/usr/bin/env python3
"""A restated member's stale sidecar does not block publication; a scored row's still does.

FOUND 2026-10-05: the predictions deploy refused ("1 stale sidecar(s) ... b8f04a549fee4c48")
on a prior of a restated, non-specific cluster member. A restated member is never scored on
its own (join gives it `restated:<specific member>` whatever its sidecars say), so a stale
sidecar of one drops no row, yet corpus.stale_sidecars listed it and
data_clone_workflow.scores_blockers refused the board. The overnight run had to move the
sidecar out of the read path by hand. The scorer now reports a restated member's stale
sidecars apart, under corpus.restated_stale_sidecars, which blocks nothing.

Builds a tiny corpus with a restatement cluster: the specific member p1 and the member p2
each carry a resolution written under a resolution-policy release beside a prior whose
prompt_sha256 is not today's prompt (score_predictions.prior_prompt_stale). Runs the real
scorer twice and reads its output. No quota, no data checkout.
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
    (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
        T.rec("p1"), T.rec("p2", said="2019-06-01"), T.rec("p3"))))
    index = corpus / "index.json"
    index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
    run = d / "run-a"
    for pid in ("p1", "p2", "p3"):
        T.write(run, pid, "resolve", policy_release="resolution-2026-09-30")
        T.write(run, pid, "prior", prompt_sha256="not-todays-prompt")
    m = T.manifest(d / "m.json", [T.cluster("ada/c1", "p1", ["p1", "p2"])])

    def score(*extra, out):
        argv = [sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--predictions", str(corpus),
                "--index", str(index), "--as-of", "2026-09-16", "--min-lead-days", "60", "--out", str(out),
                "--run", str(run), "--policy-release", "legacy", "--policy-release", "resolution-2026-09-30"]
        return subprocess.run(argv + list(extra), capture_output=True, text=True)

    p = score("--restatements", str(m), out=d / "s.json")
    check("the scorer exits 0", p.returncode == 0, p.stderr[-600:])
    doc = json.loads((d / "s.json").read_text()) if p.returncode == 0 else {}
    stale = {s["prediction_id"] for s in (doc.get("corpus") or {}).get("stale_sidecars") or []}
    ignored = {s["prediction_id"] for s in (doc.get("corpus") or {}).get("restated_stale_sidecars") or []}
    check("the fixture really makes stale sidecars (the scored rows p1, p3)", {"p1", "p3"} <= stale, str(stale))
    check("a restated member's stale sidecar is not among the blocking ones", "p2" not in stale, str(stale))
    check("it is reported apart, so it is not hidden", "p2" in ignored, str(ignored))
    blockers = D.scores_blockers(doc)
    check("the blockers still name the scored rows' stale sidecars and not the restated member's",
          blockers and "p1" in blockers[0] and "p2" not in blockers[0], str(blockers))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
