#!/usr/bin/env python3
"""The idle guard must not mistake the invoking agent's own keep-awake for a consumer.

FOUND 2026-09-27 running `data_sync.py adopt-main --apply` from Claude Code in
repo-2: it refused with `active consumers ... "caffeinate -i -t 300"`. Claude Code
spawns caffeinate as a CHILD of its own process, with the clone as its working
directory. active_consumers() already skipped the invoking process's ancestors,
but this is a sibling, so every agent migrating from inside Claude Code would be
refused. The refusal also escaped as a Python traceback rather than a REFUSING
line.

  HARNESS   a caffeinate whose parent is one of our ancestors is ignored.
  FOREIGN   a caffeinate that is NOT our ancestors' child still blocks, and so
            does any other process of ours sitting in the clone.
  CLEAN     a refusal from adopt-main is one REFUSING line, never a traceback.

  .venv/bin/python scripts/test_idle_guard_harness.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(REPO / "scripts"))
import data_clone_workflow as D  # noqa: E402

FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def pids(consumers: list[dict]) -> set[int]:
    return {c["pid"] for c in consumers}


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t).resolve() / "repo-9"
        repo.mkdir()

        ours = subprocess.Popen(["caffeinate", "-i", "-t", "60"], cwd=repo)
        time.sleep(0.5)
        try:
            found = pids(D.active_consumers(repo))
            check("HARNESS: our own child caffeinate in the clone is not a consumer", ours.pid not in found, str(found))
        finally:
            ours.kill()

        job = subprocess.Popen(["sleep", "60"], cwd=repo)
        time.sleep(0.5)
        try:
            check("FOREIGN: any other process of ours in the clone still blocks",
                  job.pid in pids(D.active_consumers(repo)))
        finally:
            job.kill()

        # Detached: the shell exits at once, so caffeinate is reparented away from us.
        subprocess.run(["bash", "-c", f"cd '{repo}' && (caffeinate -i -t 60 >/dev/null 2>&1 &)"], check=True)
        time.sleep(0.8)
        stray = [c for c in D.active_consumers(repo) if c["command"].startswith("caffeinate")]
        check("FOREIGN: a caffeinate that is not our ancestors' child still blocks", bool(stray), str(stray))
        for c in stray:
            os.kill(c["pid"], 9)

        spec = importlib.util.spec_from_file_location("tdsp_idle", REPO / "scripts" / "test_data_sync_push.py")
        P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(P)
        remote, _ = P.seed(Path(t))
        old = repo / ".data-clones" / "experiment"
        old.parent.mkdir()
        subprocess.run(["git", "clone", "-q", "--no-local", str(remote), str(old)], check=True)
        subprocess.run(["git", "-C", str(old), "config", "verbatim.role", "experiment"], check=True)
        (repo / "data").symlink_to(old, target_is_directory=True)
        blocker = subprocess.Popen(["sleep", "60"], cwd=repo)
        time.sleep(0.5)
        try:
            p = subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "adopt-main", "--repo", str(repo), "--apply"],
                               capture_output=True, text=True, cwd=REPO)
            check("CLEAN: a busy clone refuses adopt-main with one REFUSING line and no traceback",
                  p.returncode == 1 and p.stdout.startswith("REFUSING") and "Traceback" not in p.stderr,
                  p.stdout[-300:] + p.stderr[-300:])
            check("CLEAN: and nothing was switched", (repo / "data").resolve() == old.resolve()
                  and not (repo / ".data-clones" / "main").exists())
        finally:
            blocker.kill()

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
