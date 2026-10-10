#!/usr/bin/env python3
"""A router refusal in the verify stage is reported as router_no_account, not as a crash.

FOUND 2026-10-05 in the VD-13 (b) verify run (data predictions/_experiments/
redate-vd13b-20261005/verify.log): every Fable account the run could use was out of
quota, Router.pick raised RouterUnavailable, and verify_one's except branch passed the
unassigned local `route` to _verify_failed. The job died with
"UnboundLocalError: cannot access local variable 'route'", filed as cli_nonzero_exit,
so the taxonomy hid a quota stop behind a code error.

Drives the real script: --stage verify --verifier fable --force with every Claude
account in --router-exclude, so Router.pick refuses before any network call. The input
is a copy, in a temporary --out, of one production record that Astra extracted under the
current EXTRACTION CONTRACT (found at run time; the data link must be present). No quota.
Release predictions-2.4 (2026-10-09) changed only a header line that no existing record uses,
so the copy's release label is set to today's release; the verify stage then reaches the
router, which is what this test is about. The production record is never written.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import predictions_lib as L  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


data = L.data_root()
rel = L.load_policy_release(REPO / ".claude" / "skills" / "prediction-extractor")
release, contract = rel["release"], rel["contracts"]["extract"]
pick = None
for meta_path in sorted((data / "predictions").glob("*/*.meta.json")):
    m = json.loads(meta_path.read_text())
    ex = m.get("extract") or {}
    if ex.get("harness") != "astra" or ex.get("status") != "ok" or ex.get("contract_id") != contract:
        continue
    jl = meta_path.with_name(meta_path.name[:-len(".meta.json")] + ".jsonl")
    if not any(json.loads(x)["extraction"]["qualifies"] for x in jl.read_text().split("\n") if x.strip()):
        continue
    slug, sid = meta_path.parent.name, meta_path.name[:-len(".meta.json")]
    src = [data / d / slug / f"{sid}.json" for d in L.TRANSCRIPT_DIRS if (data / d / slug / f"{sid}.json").is_file()]
    if src:
        pick = (slug, sid, meta_path, jl, src[0])
        break
if pick is None:
    print(f"  FAIL  no production record extracted by Astra under extraction contract {contract} was found under {data}")
    sys.exit(1)

slug, sid, meta_path, jl, transcript = pick
claude_ids = []
from quota_router.config import load_config  # noqa: E402
claude_ids = [a.id for a in load_config().enabled_accounts() if a.provider == "claude"]
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "out"
    (out / slug).mkdir(parents=True)
    m = json.loads(meta_path.read_text())
    m["extract"]["audit"]["policy_release"] = release
    (out / slug / meta_path.name).write_text(json.dumps(m))
    recs = [json.loads(x) for x in jl.read_text().split("\n") if x.strip()]
    for r in recs:
        r["extraction"]["telemetry"]["prediction_audit"]["policy_release"] = release
    (out / slug / jl.name).write_text("".join(json.dumps(r) + "\n" for r in recs))
    lst = Path(td) / "list.txt"
    lst.write_text(f"{transcript}\n")
    errors = Path(td) / "errors.jsonl"
    p = subprocess.run([sys.executable, str(REPO / "scripts" / "extract_predictions.py"), "--stage", "verify",
                        "--verifier", "fable", "--force", "--list", str(lst), "--out", str(out), "--workers", "1",
                        "--router-exclude", ",".join(claude_ids + ["antigravity_claude"]), "--errors", str(errors)],
                       capture_output=True, text=True, cwd=REPO)
    # The driver logs each job to stderr, cut at 400 characters, so read the two fields by pattern.
    import re
    rows = [x for x in p.stderr.split("\n") if x.startswith("{") and '"stage": "verify", "run"' in x]
    row = {}
    if rows:
        for k in ("status", "error_type"):
            m = re.search(rf'"{k}": "([a-z_]+)"', rows[0])
            row[k] = m.group(1) if m else None
    check(f"the verify job on {slug}/{sid} fails as router_no_account",
          row.get("status") == "failed" and row.get("error_type") == L.E_ROUTER, json.dumps(row)[:300] or p.stderr[-300:])
    check("the failure is not a code error", "UnboundLocalError" not in p.stdout + p.stderr,
          (p.stdout + p.stderr)[-300:])
    meta = json.loads((out / slug / meta_path.name).read_text())
    check("the meta records the verify stage as failed with the router's label",
          (meta.get("verify") or {}).get("status") == "failed"
          and L.E_ROUTER in json.dumps(meta.get("verify")), json.dumps(meta.get("verify"))[:300])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
