#!/usr/bin/env python3
"""`build_restatement_manifest.py` turns a reviewed clusters.json into the manifest the scorer reads.

What this pins:
  - only `clusters` become clusters; `moved_goalpost`, `uncertain` and
    `judged_distinct` never do, and a cluster that holds EVERY id of any such
    group is REFUSED, because those groups record a decision NOT to merge.
    Phase 1 writes an uncertain group as the outsider plus the members of the
    cluster it was compared with, so holding some of a group's ids is normal;
  - each manifest cluster carries its members and the reviewed `specific_member`
    exactly as clusters.json names them, and the manifest records the sha256 of
    the file it came from;
  - `--resolution` names the run holding a fresh resolution for a cluster's
    specific member, and the builder lists as superseded EVERY resolution
    sidecar of every member of that cluster in the named runs, so none is
    silently left competing; a missing fresh sidecar is refused.
"""
from __future__ import annotations

import hashlib
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
SCRIPT = ROOT / "scripts" / "build_restatement_manifest.py"


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def member(pid):
    return {"prediction_id": pid, "statement_date": "2019-01-01"}


def clusters_doc(extra_uncertain=None):
    return {
        "clusters": [
            {"cluster_id": "ada/one", "leader_slug": "ada", "specific_member": "p1",
             "members": [member("p1"), member("p2")], "union_claim": "X by 2020"},
            {"cluster_id": "ada/two", "leader_slug": "ada", "specific_member": "p4",
             "members": [member("p3"), member("p4")], "union_claim": "Y by 2020"},
        ],
        "moved_goalpost": [{"leader_slug": "ada", "members": [member("p5"), member("p6")]}],
        # The real shape: the outsider p7 listed with the cluster's own members p1, p2.
        "uncertain": [{"leader_slug": "ada", "members": [member("p7"), member("p1"), member("p2")]}]
                     + (extra_uncertain or []),
        "judged_distinct": [{"leader_slug": "ada", "prediction_ids": ["p8", "p9"]}],
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "predictions").mkdir()
        cj = d / "clusters.json"
        cj.write_text(json.dumps(clusters_doc()))
        run_a, run_f = d / "predictions" / "run-a", d / "predictions" / "run-fresh"
        for run, pid in ((run_a, "p1"), (run_a, "p2"), (run_f, "p1")):
            fp = R.sidecar_path(run, "resolve", "ada", pid)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps({"prediction_id": pid, "outcome": "occurred"}))

        def build(*extra, src=cj, out=d / "m.json"):
            return subprocess.run([sys.executable, str(SCRIPT), "--clusters", str(src), "--data-root", str(d),
                                   "--out", str(out), *extra], capture_output=True, text=True)

        p = build()
        check("BUILD: exits 0", p.returncode == 0, p.stderr[-500:])
        m = json.loads((d / "m.json").read_text()) if p.returncode == 0 else {}
        cl = {c["cluster_id"]: c for c in m.get("clusters", [])}
        check("BUILD: only the clusters become clusters, with members and specific_member as reviewed",
              sorted(cl) == ["ada/one", "ada/two"] and cl["ada/one"]["members"] == ["p1", "p2"]
              and cl["ada/two"]["specific_member"] == "p4" and cl["ada/one"]["leader_slug"] == "ada", str(cl))
        check("BUILD: no moved_goalpost, uncertain or judged_distinct id is merged",
              not {"p5", "p6", "p7", "p8", "p9"} & {x for c in cl.values() for x in c["members"]}, str(cl))
        check("BUILD: the manifest records the source file's sha256",
              m.get("derived_from", {}).get("sha256") == hashlib.sha256(cj.read_bytes()).hexdigest()
              and m.get("schema_version") == 1, str(m.get("derived_from")))

        bad = d / "bad.json"
        bad.write_text(json.dumps(clusters_doc(extra_uncertain=[{"leader_slug": "ada", "members": [member("p3"), member("p4")]}])))
        pb = build(src=bad, out=d / "bad-m.json")
        check("REFUSE: a cluster holding every id of an uncertain group, naming them",
              pb.returncode != 0 and "p3" in pb.stderr and "p4" in pb.stderr and not (d / "bad-m.json").exists(),
              pb.stderr[-400:])

        res = json.dumps({"cluster_id": "ada/one", "run": "predictions/run-fresh", "why": "the two disagree"})
        pr = build("--resolution", res, "--run", "predictions/run-a", "--run", "predictions/run-fresh", out=d / "r.json")
        check("RESOLUTION: exits 0", pr.returncode == 0, pr.stderr[-500:])
        rm = json.loads((d / "r.json").read_text()) if pr.returncode == 0 else {}
        one = {c["cluster_id"]: c for c in rm.get("clusters", [])}.get("ada/one", {})
        check("RESOLUTION: every other resolution sidecar of every member is superseded, and the fresh one is kept",
              one.get("resolution") == {"run": "predictions/run-fresh", "why": "the two disagree",
                                        "supersedes": [{"prediction_id": "p1", "run": "predictions/run-a"},
                                                       {"prediction_id": "p2", "run": "predictions/run-a"}]},
              str(one.get("resolution")))
        pm = build("--resolution", json.dumps({"cluster_id": "ada/two", "run": "predictions/run-fresh", "why": "x"}),
                   "--run", "predictions/run-a", out=d / "miss.json")
        check("RESOLUTION: a fresh run with no sidecar for the specific member is refused",
              pm.returncode != 0 and "p4" in pm.stderr, pm.stderr[-400:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
