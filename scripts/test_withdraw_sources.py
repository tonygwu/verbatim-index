#!/usr/bin/env python3
"""Guards for withdraw_sources.py. Pure checks on a temp tree, no data/.

  .venv/bin/python scripts/test_withdraw_sources.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


spec = importlib.util.spec_from_file_location("ws", REPO / "scripts" / "withdraw_sources.py")
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)


def tree(root: Path, owner: str) -> None:
    (root / "data").mkdir(parents=True)
    (root / "data" / ".daemon-clone").write_text(owner + "\n")
    for shelf in ("transcripts", "transcripts_hs"):
        (root / "data" / shelf / "x").mkdir(parents=True)
    (root / "data" / "transcripts" / "x" / "a.json").write_text("{}")
    (root / "data" / "transcripts" / "x" / "b.json").write_text("{}")
    (root / "data" / "transcripts_hs" / "x" / "b.json").write_text("{}")
    (root / "data" / "transcripts" / "x" / "gone.json.superseded").write_text("{}")
    for j in ("fable", "astra", "gemini"):
        d = root / "data" / "grades" / j / "x"; d.mkdir(parents=True)
        (d / f"a__{j}__blinded__r0.json").write_text("{}")
        (d / f"c__{j}__blinded__r0.json").write_text("{}")
    (root / "data" / "grades" / "_raw" / "fable" / "x").mkdir(parents=True)
    (root / "data" / "grades" / "_raw" / "fable" / "x" / "c__fable__blinded__r0.txt").write_text("raw")


MANIFEST = [
    {"leader_slug": "x", "source_id": "a", "action": "retire", "reason": "wrong person"},
    {"leader_slug": "x", "source_id": "b", "action": "retire", "reason": "wrong person, on two shelves"},
    {"leader_slug": "x", "source_id": "gone", "action": "retire", "reason": "already retired"},
    {"leader_slug": "x", "source_id": "nope", "action": "retire", "reason": "never existed"},
    {"leader_slug": "x", "source_id": "c", "action": "regrade", "reason": "looped text collapsed"},
    {"leader_slug": "x", "source_id": "zzz", "action": "regrade", "reason": "no grades"},
]

print("dry run")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "repo-0"; tree(root, "repo-0")
    t = ws.run(root, MANIFEST, apply=False)
    check("attempted/done/skipped/failed add up",
          t["attempted"] == 6 and t["done"] + t["skipped"] + t["failed"] == 6, str({k: t[k] for k in ("attempted", "done", "skipped", "failed")}))
    check("two retirements and one regrade would be done", t["done"] == 3, str(t["done"]))
    check("an already-superseded source is skipped, not failed",
          [e for e in t["entries"] if e["source_id"] == "gone"][0]["status"] == "skipped")
    check("a missing source is failed with a reason",
          [e for e in t["entries"] if e["source_id"] == "nope"][0]["status"] == "failed")
    check("a regrade with no grades is failed", [e for e in t["entries"] if e["source_id"] == "zzz"][0]["status"] == "failed")
    check("dry run changes nothing",
          (root / "data" / "transcripts" / "x" / "a.json").exists()
          and (root / "data" / "grades" / "fable" / "x" / "c__fable__blinded__r0.json").exists())

print("apply")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "repo-0"; tree(root, "repo-0")
    t = ws.run(root, MANIFEST, apply=True)
    check("retired source is renamed to .superseded",
          not (root / "data" / "transcripts" / "x" / "a.json").exists()
          and (root / "data" / "transcripts" / "x" / "a.json.superseded").exists())
    check("a source on two shelves is retired on both",
          (root / "data" / "transcripts" / "x" / "b.json.superseded").exists()
          and (root / "data" / "transcripts_hs" / "x" / "b.json.superseded").exists())
    check("regrade orphans every judge's grade for the recording",
          all((root / "data" / "grades" / j / "x" / f"c__{j}__blinded__r0.json.orphaned").exists() for j in ("fable", "astra", "gemini")))
    check("regrade leaves other recordings' grades alone",
          (root / "data" / "grades" / "fable" / "x" / "a__fable__blinded__r0.json").exists())
    check("raw judge output is untouched",
          (root / "data" / "grades" / "_raw" / "fable" / "x" / "c__fable__blinded__r0.txt").exists())
    t2 = ws.run(root, MANIFEST, apply=True)
    check("a second apply is all skipped or failed, never done again", t2["done"] == 0, str(t2["done"]))

print("a re-grade that is already satisfied is skipped, not repeated")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "repo-0"; tree(root, "repo-0")
    for mode in ("transcripts_blind", "transcripts_open"):
        d = root / "data" / mode / "x"; d.mkdir(parents=True)
        (d / "c.json").write_text(json.dumps({"leader_slug": "x", "source_id": "c", "text": "hi",
                                              "normalization": {"normalized_at_utc": "2026-09-11T05:00:00Z"}}))
    for j in ("fable", "astra", "gemini"):
        p = root / "data" / "grades" / j / "x" / f"c__{j}__blinded__r0.json"
        p.write_text(json.dumps({"graded_at_utc": "2026-09-11T06:00:00Z"}))
    r = ws.regrade(root, "x", "c", apply=False)
    check("grades newer than the normalization are left alone",
          r["status"] == "skipped" and "post-date" in r["detail"], str(r))
    for j in ("fable", "astra", "gemini"):
        p = root / "data" / "grades" / j / "x" / f"c__{j}__blinded__r0.json"
        p.write_text(json.dumps({"graded_at_utc": "2026-09-11T04:00:00Z"}))
    r = ws.regrade(root, "x", "c", apply=False)
    check("grades older than the normalization are re-graded", r["status"] == "done", str(r))
    for j in ("fable", "astra", "gemini"):
        p = root / "data" / "grades" / j / "x" / f"c__{j}__blinded__r0.json"
        p.write_text(json.dumps({"graded_at_utc": "2026-09-11T06:00:00Z"}))
    (root / "data" / "transcripts_blind" / "x" / "c.json").write_text(json.dumps(
        {"leader_slug": "x", "source_id": "c", "text": "hi", "normalization": {}}))
    (root / "data" / "transcripts_open" / "x" / "c.json").write_text(json.dumps(
        {"leader_slug": "x", "source_id": "c", "text": "hi", "normalization": {}}))
    r = ws.regrade(root, "x", "c", apply=False)
    check("a record with no normalization stamp proceeds, rather than silently refusing",
          r["status"] == "done", str(r))
    check("normalized_at reads the stamp out of the record, never a file mtime",
          "st_mtime" not in (REPO / "scripts" / "withdraw_sources.py").read_text())

print("clone guard")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "repo-3"; tree(root, "repo-0")
    m = Path(td) / "m.json"; m.write_text(json.dumps(MANIFEST))
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "withdraw_sources.py"), str(m), "--apply", "--root", str(root)],
                          capture_output=True, text=True)
    check("--apply in the wrong clone refuses", proc.returncode != 0 and "REFUSING TO APPLY" in proc.stderr, proc.stderr[-300:])
    check("and changes nothing", (root / "data" / "transcripts" / "x" / "a.json").exists())
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "withdraw_sources.py"), str(m), "--root", str(root)],
                          capture_output=True, text=True)
    check("a dry run in the wrong clone is allowed", "DRY RUN" in proc.stdout, proc.stdout[:200])
    check("dry run exits non-zero when an entry fails", proc.returncode == 1)
    (root / "data" / ".daemon-clone").unlink()
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "withdraw_sources.py"), str(m), "--apply", "--root", str(root)],
                          capture_output=True, text=True)
    check("--apply with no marker refuses", proc.returncode != 0 and "missing" in proc.stderr)

print("the shipped manifest is well formed")
man = REPO / "docs" / "withdrawals-2026-09-10.json"
if man.exists():
    entries = json.loads(man.read_text())
    keys = {(e["leader_slug"], e["source_id"]) for e in entries}
    check("every entry has slug, source, action and reason",
          all(all(k in e for k in ("leader_slug", "source_id", "action", "reason")) for e in entries))
    check("actions are known", all(e["action"] in ws.ACTIONS for e in entries))
    check("no recording is listed twice", len(keys) == len(entries))
    # 45 retirements and no re-grades. The manifest carried 9 re-grades for the
    # looped transcripts; VERIFIED 2026-09-11 that repo-0's loop had already
    # re-normalized and re-graded them, so they were removed rather than left
    # to orphan 27 fresh grades. regrade() now refuses that case on its own.
    check("45 retirements and no stale re-grades",
          sum(e["action"] == "retire" for e in entries) == 45 and sum(e["action"] == "regrade" for e in entries) == 0,
          f"retire={sum(e['action']=='retire' for e in entries)} regrade={sum(e['action']=='regrade' for e in entries)}")
else:
    check("docs/withdrawals-2026-09-10.json exists", False)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
