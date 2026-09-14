#!/usr/bin/env python3
"""P0 leaders baseline: run the quota-free pipeline stages on a private copy of a
frozen data snapshot, then write a sha256 manifest of every output the
byte-identity test will compare.

usage: baseline.py --code CODE_DIR --snapshot SNAPSHOT --run-dir NEW_DIR --python PY

Stops on the first stage that exits nonzero. Never touches the snapshot, which
is copied first, and never spends quota: no stage calls a judge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STAGES = [
    ("qa", ["scripts/qa_transcripts.py", "--transcripts", "data/transcripts",
            "--roster", "data/roster/final.json", "--glossaries", "data/sources/aliases.json",
            "--out", "data/logs/transcript_qa.json"]),
    *[(f"normalize_{m}", ["scripts/normalize_transcripts.py", "--mode", m,
                          "--transcripts", "data/transcripts",
                          "--out", "data/transcripts_blind" if m == "blinded" else "data/transcripts_open",
                          "--roster", "data/roster/final.json", "--repairs", "data/sources/repairs.json",
                          "--aliases", "data/sources/aliases.json", "--qa", "data/logs/transcript_qa.json",
                          "--grades", "data/grades", "--log", f"data/logs/normalize_{m}.json"])
      for m in ("blinded", "open")],
    ("aggregate", ["scripts/aggregate.py", "--grades", "data/grades", "--roster", "data/roster/final.json",
                   "--transcripts", "data/transcripts_blind", "--out", "data/results.json"]),
    ("build_site", ["scripts/build_site.py", "--results", "data/results.json",
                    "--audit", "data/results_audit.json", "--roster", "data/roster/final.json",
                    "--calibration", "data/logs/calibration.json",
                    "--sources", "data/sources/discovered.json", "--out", "site/index.html"]),
    ("coverage_table", ["scripts/coverage_table.py"]),
]

PROMPTS = r'''
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
import grade
rubric, schema = grade.RUBRIC_PATH.read_text(), grade.SCHEMA_PATH.read_text()
roster = {r["slug"]: r for r in json.loads(Path("data/roster/final.json").read_text())["roster"]}
out = {}
for mode, d in (("blinded", "data/transcripts_blind"), ("open", "data/transcripts_open")):
    for p in sorted(Path(d).rglob("*.json")):
        rec = json.loads(p.read_text())
        person = roster.get(rec["leader_slug"], {})
        rec["_speaker_name"] = person.get("name", rec["leader_slug"].replace("-", " ").title())
        rec["_speaker_role"] = person.get("role", "technology executive")
        text = grade.build_judge_prompt(rec, mode, rubric, schema)
        out[f"{mode}/{p.relative_to(d)}"] = hashlib.sha256(text.encode()).hexdigest()
print(json.dumps({"n": len(out), "contract": grade.grading_contract(), "prompts": out}, sort_keys=True))
'''

FINGERPRINT = r'''
import sys; sys.path.insert(0, "scripts")
from pathlib import Path
import data_clone_workflow as D
print(D.fingerprint(Path("data").resolve(), "leaderboard"))
'''


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", type=Path, required=True)
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--python", required=True)
    a = ap.parse_args()
    if a.run_dir.exists():
        raise SystemExit(f"refusing: {a.run_dir} exists; a run always starts from a fresh copy")
    # Not "<run-dir>/data": production_path() falls back to <code parent>/data
    # when git config is unset, and guard_aggregate would then treat the copy as
    # the live production checkout and refuse it for lacking a .daemon-clone.
    code, data = a.run_dir / "code", a.run_dir / "data-copy"
    shutil.copytree(a.code, code, symlinks=True)
    shutil.copytree(a.snapshot, data, symlinks=True)
    subprocess.run(["chmod", "-R", "u+w", str(data)], check=True)
    (code / "data").symlink_to(data, target_is_directory=True)
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    grades_before = tree(data / "grades")
    logs = a.run_dir / "stage_logs"
    logs.mkdir()
    outputs: dict[str, object] = {}
    for name, argv in STAGES:
        p = subprocess.run([a.python, *argv], cwd=code, env=env, capture_output=True, text=True)
        (logs / f"{name}.out").write_text(p.stdout)
        (logs / f"{name}.err").write_text(p.stderr)
        print(f"stage {name}: exit {p.returncode}", flush=True)
        if p.returncode:
            print(p.stderr[-2000:], file=sys.stderr)
            return 1
        if name == "coverage_table":
            outputs["coverage_table.stdout"] = hashlib.sha256(p.stdout.encode()).hexdigest()
    for name, script in (("prompts", PROMPTS), ("fingerprint", FINGERPRINT)):
        p = subprocess.run([a.python, "-c", script], cwd=code, env=env, capture_output=True, text=True)
        (logs / f"{name}.err").write_text(p.stderr)
        print(f"stage {name}: exit {p.returncode}", flush=True)
        if p.returncode:
            print(p.stderr[-2000:], file=sys.stderr)
            return 1
        (a.run_dir / f"{name}.out").write_text(p.stdout)
        outputs[name] = json.loads(p.stdout) if name == "prompts" else p.stdout.strip()
    outputs["transcripts_blind"] = tree(data / "transcripts_blind")
    outputs["transcripts_open"] = tree(data / "transcripts_open")
    for f in ("logs/transcript_qa.json", "logs/normalize_blinded.json", "logs/normalize_open.json",
              "results.json", "results_audit.json", "logs/calibration.json"):
        outputs[f] = sha(data / f) if (data / f).is_file() else "MISSING"
    outputs["site/index.html"] = sha(code / "site" / "index.html")
    grades_after = tree(data / "grades")
    outputs["grades_changed_by_pipeline"] = sorted(
        k for k in set(grades_before) | set(grades_after) if grades_before.get(k) != grades_after.get(k))
    (a.run_dir / "manifest.json").write_text(json.dumps(outputs, indent=1, sort_keys=True))
    print(f"manifest written: {a.run_dir / 'manifest.json'}; "
          f"{outputs['prompts']['n']} prompts, "
          f"{len(outputs['transcripts_blind'])} blind files, "
          f"{len(outputs['grades_changed_by_pipeline'])} grade files changed by the pipeline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
