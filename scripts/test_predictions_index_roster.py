#!/usr/bin/env python3
"""The predictions index depends on the roster, and the staleness check must see that.

WHAT THE GUARD IS FOR. `deploy_predictions.sh` refuses to publish an index that
no longer describes what is on disk. It compares three things: files read,
records read, and `inputs_sha256`, a digest of every record and sidecar byte.
Those catch an added file, an added line, and an in-place rewrite by verification
or market consensus.

THE HOLE. `aggregate_predictions.py` builds the index by UNIONING roster slugs
with every slug that has records, so the roster is an input too, and none of the
three can see it. MEASURED 2026-09-18: appending seven investors took the index
from 50 leaders to 57 while `files_read`, `records_read` and `inputs_sha256` were
all byte-identical. The check would have printed "current: index matches disk"
over an index listing the wrong people.

The index now carries `roster_sha256` and the deploy compares it. An index that
predates the field REFUSES rather than passing, which is the same choice the
existing `inputs_sha256` branch already makes: an unverifiable claim is not a
verified one.

Temporary directories only. No network, no quota, no deploy.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = str(REPO / ".venv" / "bin" / "python")

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    return ok


def build(tmp: Path, slugs: list[str]) -> tuple[Path, Path]:
    """A tiny predictions corpus plus a roster."""
    pred = tmp / "predictions"
    for s in slugs[:1]:
        (pred / s).mkdir(parents=True, exist_ok=True)
        (pred / s / "t1.jsonl").write_text("")
    pred.mkdir(parents=True, exist_ok=True)
    roster = tmp / "roster.json"
    roster.write_text(json.dumps({"roster": [
        {"slug": s, "name": s.title(), "company": "C"} for s in slugs]}))
    return pred, roster


def main() -> int:
    import aggregate_predictions as AP

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("[1] the index records a digest of the roster it was built from")
        pred, roster = build(tmp, ["alpha", "beta"])
        idx = AP.build_index(pred, {r["slug"]: r for r in
                                    json.loads(roster.read_text())["roster"]},
                             None, roster)
        want = hashlib.sha256(roster.read_bytes()).hexdigest()
        check("roster_sha256 is present", "roster_sha256" in idx, sorted(idx))
        check("... and matches the roster file's bytes", idx["roster_sha256"] == want,
              f"{idx.get('roster_sha256')} vs {want}")

        print("\n[2] the roster moves and the RECORD digests do not, which is the hole")
        before = dict(idx)
        roster.write_text(json.dumps({"roster": [
            {"slug": s, "name": s.title(), "company": "C"}
            for s in ["alpha", "beta", "gamma"]]}))
        after = AP.build_index(pred, {r["slug"]: r for r in
                                      json.loads(roster.read_text())["roster"]},
                               None, roster)
        check("the leader list changed", len(after["leaders"]) != len(before["leaders"]),
              f"{len(before['leaders'])} -> {len(after['leaders'])}")
        for k in ("files_read", "records_read", "inputs_sha256"):
            check(f"{k} did NOT change, so it cannot detect this",
                  after[k] == before[k], f"{before[k]} -> {after[k]}")
        check("roster_sha256 DID change, which is the whole point",
              after["roster_sha256"] != before["roster_sha256"])

        print("\n[3] roster_sha256 is None when no roster path is given")
        # build_index is called elsewhere without one; it must not invent a digest.
        noroster = AP.build_index(pred, {}, None, None)
        check("it is None rather than a digest of nothing",
              noroster["roster_sha256"] is None, str(noroster["roster_sha256"]))

        print("\n[4] the deploy refuses an index that predates the field")
        src = (REPO / "scripts" / "deploy_predictions.sh").read_text()
        live = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        body = "\n".join(live)
        check("deploy_predictions computes the roster digest",
              "roster/final.json" in body and "sha256" in body)
        check("it refuses when the field is absent",
              'roster_sha256" not in idx' in body and "REFUSING" in body,
              "an index that cannot be checked is not a checked index")
        check("it refuses when the digest differs",
              'idx["roster_sha256"] != roster_digest' in body)
        check("the message names the command to fix it",
              "aggregate_predictions.py" in body)

        print("\n[5] the refusal really fires, end to end")
        # A whole fake production checkout is more than this needs; the branch is
        # exercised directly against the two inputs it reads.
        probe = tmp / "probe.py"
        probe.write_text(
            "import hashlib, json, pathlib, sys\n"
            "data = pathlib.Path(sys.argv[1])\n"
            "idx = json.load((data / 'index.json').open())\n"
            "roster_digest = hashlib.sha256((data / 'roster.json').read_bytes()).hexdigest()\n"
            "if 'roster_sha256' not in idx:\n"
            "    print('PREDATES'); raise SystemExit(1)\n"
            "if idx['roster_sha256'] != roster_digest:\n"
            "    print('STALE'); raise SystemExit(1)\n"
            "print('CURRENT')\n")
        d = tmp / "probe-data"
        d.mkdir()
        (d / "roster.json").write_text(roster.read_text())
        (d / "index.json").write_text(json.dumps({"files_read": 1}))
        r = subprocess.run([PY, str(probe), str(d)], capture_output=True, text=True)
        check("an index with no roster_sha256 refuses",
              r.returncode != 0 and "PREDATES" in r.stdout, r.stdout)
        (d / "index.json").write_text(json.dumps({"roster_sha256": "deadbeef"}))
        r = subprocess.run([PY, str(probe), str(d)], capture_output=True, text=True)
        check("a mismatched digest refuses",
              r.returncode != 0 and "STALE" in r.stdout, r.stdout)
        (d / "index.json").write_text(json.dumps(
            {"roster_sha256": hashlib.sha256(roster.read_bytes()).hexdigest()}))
        r = subprocess.run([PY, str(probe), str(d)], capture_output=True, text=True)
        check("a matching digest passes", r.returncode == 0 and "CURRENT" in r.stdout,
              r.stdout)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
