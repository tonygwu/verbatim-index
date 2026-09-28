#!/usr/bin/env python3
"""Build the restatement manifest `score_predictions.py --restatements` reads.

    .venv/bin/python scripts/build_restatement_manifest.py \
        --clusters data/predictions/_experiments/<run>/clusters.json \
        --data-root data --out data/predictions/_experiments/<run>/restatements.json \
        [--resolution '{"cluster_id": "...", "run": "predictions/_experiments/<run>", "why": "..."}' \
         --run predictions/_experiments/<a> --run ...]

The input is a reviewed clusters.json (phase 1 of a restatement pass, proposal
only). Only its `clusters` become clusters. `moved_goalpost`, `uncertain` and
`judged_distinct` record decisions NOT to merge (operator decision 2, 2026-09-28:
a moved deadline or a changed threshold is not a restatement), so a cluster that
holds every id of any such group is refused rather than trusted.

Each cluster keeps its reviewed `specific_member` (operator decision 3: the
earliest member specific enough on its own). Nothing here re-derives it.

`--resolution` says a cluster's specific member was resolved afresh in `run`.
The builder then lists, as superseded, every resolution sidecar of every member
of that cluster found in the `--run` directories, except the fresh one, so no
older verdict is left to compete with it. The scorer refuses a superseded sidecar
that is not on disk, so the manifest cannot outlive the inputs it describes.

Paths in the manifest are relative to the data root, like scoring.json's.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R  # noqa: E402


def group_ids(g: dict) -> list[str]:
    if "prediction_ids" in g:
        return list(g["prediction_ids"])
    return [m["prediction_id"] for m in g["members"]]


def build(clusters_path: Path, data_root: Path, resolutions: list[dict], runs: list[str]) -> dict:
    raw = clusters_path.read_bytes()
    src = json.loads(raw)
    by_id = {}
    out = []
    for c in src["clusters"]:
        members = [m["prediction_id"] for m in c["members"]]
        if c["specific_member"] not in members:
            raise SystemExit(f"{c['cluster_id']}: specific_member {c['specific_member']} is not a member")
        entry = {"cluster_id": c["cluster_id"], "leader_slug": c["leader_slug"],
                 "specific_member": c["specific_member"], "members": members}
        if c.get("union_claim"):
            entry["note"] = c["union_claim"]
        by_id[c["cluster_id"]] = entry
        out.append(entry)
    # A no-merge group lists the ids it keeps apart. Phase 1 writes an uncertain
    # group as the outsider PLUS the members of the cluster it was compared with,
    # so a cluster holding some of a group's ids is normal. A cluster holding ALL
    # of them has merged what the group says to keep separate.
    for kind in ("moved_goalpost", "uncertain", "judged_distinct"):
        for g in src.get(kind, []):
            ids = set(group_ids(g))
            for c in out:
                if ids <= set(c["members"]):
                    raise SystemExit(f"cluster {c['cluster_id']} merges {sorted(ids)}, which clusters.json "
                                     f"records as {kind}, a decision not to merge them")
    for res in resolutions:
        if set(res) != {"cluster_id", "run", "why"}:
            raise SystemExit(f"--resolution takes exactly cluster_id, run and why; got {sorted(res)}")
        c = by_id.get(res["cluster_id"])
        if c is None:
            raise SystemExit(f"--resolution names cluster {res['cluster_id']}, which is not in {clusters_path}")
        spec = c["specific_member"]
        if spec not in R.load_sidecars(data_root / res["run"], "resolve"):
            raise SystemExit(f"--resolution says {spec}'s fresh resolution is in {res['run']}, and there is none")
        sup = []
        for run in runs:
            have = R.load_sidecars(data_root / run, "resolve")
            for pid in c["members"]:
                if pid in have and not (Path(run) == Path(res["run"]) and pid == spec):
                    sup.append({"prediction_id": pid, "run": run})
        if not sup:
            raise SystemExit(f"--resolution for {res['cluster_id']} supersedes nothing in {runs}; "
                             f"a fresh resolution that replaces nothing needs no entry")
        c["resolution"] = {"run": res["run"], "why": res["why"],
                           "supersedes": sorted(sup, key=lambda s: (s["prediction_id"], s["run"]))}
    try:
        rel = str(clusters_path.resolve().relative_to(data_root.resolve()))
    except ValueError:
        rel = str(clusters_path)
    return {"schema_version": 1,
            "derived_from": {"file": rel, "sha256": hashlib.sha256(raw).hexdigest()},
            "clusters": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clusters", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resolution", action="append", default=[], type=json.loads,
                    help='JSON {"cluster_id", "run", "why"}; repeatable')
    ap.add_argument("--run", action="append", default=[],
                    help="a scored run, relative to the data root, searched for sidecars to supersede")
    args = ap.parse_args(argv)
    if args.resolution and not args.run:
        raise SystemExit("--resolution needs the scored runs (--run) to find what it supersedes")
    doc = build(args.clusters, args.data_root, args.resolution, args.run)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    n = sum(len(c["members"]) for c in doc["clusters"])
    print(f"wrote {args.out}: {len(doc['clusters'])} clusters, {n} members, "
          f"{sum(1 for c in doc['clusters'] if 'resolution' in c)} with a fresh resolution")
    for c in doc["clusters"]:
        for s in (c.get("resolution") or {}).get("supersedes", []):
            print(f"  {c['cluster_id']}: supersedes {s['prediction_id']} in {s['run']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
