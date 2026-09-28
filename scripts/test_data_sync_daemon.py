#!/usr/bin/env python3
"""Daemon mode: repo-0 takes other clones' pushes while its loops keep writing.

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P3. The daemons write
transcripts, grades and results.json into repo-0's working tree without
committing. Other clones never push those paths, so repo-0 can take their work
with a fast-forward or a merge commit. It must never rebase or autostash, which
would put a running loop's files back to HEAD for the length of the operation.

  PULL      `pull` fast-forwards over a contributor's push while tracked daemon
            files are modified and new ones are untracked; afterwards every
            dirty file is byte-identical.
  COLLIDE   an incoming file at a path the daemon holds untracked refuses,
            naming it, with HEAD and the untracked file unchanged.
  DAEMON    `push --daemon` lands the daemon's own commit on a main that moved,
            with a merge commit (both parents kept), and its dirty files are
            byte-identical afterwards and not in what was pushed.
  RESULTS   a results.json whose grade_files_read differs from the grade files
            in the commit refuses; a matching one passes.
  STAGED    a staged-but-uncommitted change refuses, because git merge would
            abort on it anyway and the report should say why first.

  .venv/bin/python scripts/test_data_sync_daemon.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


spec = importlib.util.spec_from_file_location("tdsp", REPO / "scripts" / "test_data_sync_push.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
git, clone, commit = P.git, P.clone, P.commit


def sync(c: Path, *args: str):
    return subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), *args, "--data", str(c)],
                          capture_output=True, text=True, cwd=REPO)


def results_for(c: Path, n: int) -> None:
    (c / "results.json").write_text(json.dumps({"leaders": [], "diagnostics": {"grade_files_read": n}}) + "\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote, _ = P.seed(td)

        # The daemon clone, with one committed grade and results.json to match.
        d = clone(td, remote, "daemon", role="daemon")
        (d / "grades" / "fable" / "ada").mkdir(parents=True)
        (d / "grades" / "fable" / "ada" / "s1.json").write_text('{"g": 1}')
        results_for(d, 1)
        commit(d, "daemon: first grade and its results")
        p = sync(d, "push", "--daemon")
        check("DAEMON: the daemon pushes its own grade and results", p.returncode == 0, p.stdout + p.stderr[-600:])

        # The loops keep writing: a tracked grade modified, a new one untracked.
        (d / "grades" / "fable" / "ada" / "s1.json").write_text('{"g": 2, "rewritten": true}')
        (d / "grades" / "fable" / "ada" / "s9.json").write_text('{"g": 9}')
        dirty = {"grades/fable/ada/s1.json": (d / "grades/fable/ada/s1.json").read_bytes(),
                 "grades/fable/ada/s9.json": (d / "grades/fable/ada/s9.json").read_bytes()}

        # ------------------------------------------------------------- PULL --
        c = clone(td, remote, "contrib")
        P.add_transcript(c, "transcripts_web", "alan", "w1", [P.Q[2]])
        commit(c, "contributor work")
        p = sync(c, "push")
        check("PULL: setup, a contributor pushes", p.returncode == 0, p.stdout + p.stderr[-600:])
        p = sync(d, "pull")
        check("PULL: the daemon takes it with dirty daemon files present", p.returncode == 0,
              p.stdout + p.stderr[-600:])
        check("PULL: its HEAD is now origin/main", git(d, "rev-parse", "HEAD") == git(d, "rev-parse", "origin/main"))
        check("PULL: every dirty daemon file is byte-identical afterwards",
              all((d / k).read_bytes() == v for k, v in dirty.items()))

        # ---------------------------------------------------------- COLLIDE --
        c2 = clone(td, remote, "contrib2")
        (c2 / "transcripts_web" / "clash.json").write_text('{"from": "contributor"}')
        commit(c2, "a new shared file")
        p = sync(c2, "push")
        check("COLLIDE: setup, the contributor's file lands", p.returncode == 0, p.stdout + p.stderr[-600:])
        (d / "transcripts_web" / "clash.json").write_text('{"from": "daemon, untracked"}')
        before = git(d, "rev-parse", "HEAD")
        p = sync(d, "pull")
        check("COLLIDE: an incoming file over an untracked daemon file refuses, naming it",
              p.returncode != 0 and "transcripts_web/clash.json" in p.stdout, p.stdout + p.stderr[-600:])
        check("COLLIDE: HEAD and the untracked file are unchanged",
              git(d, "rev-parse", "HEAD") == before
              and (d / "transcripts_web" / "clash.json").read_text() == '{"from": "daemon, untracked"}')
        (d / "transcripts_web" / "clash.json").unlink()
        p = sync(d, "pull")
        check("COLLIDE: once the file is moved aside the pull succeeds", p.returncode == 0, p.stdout + p.stderr[-600:])

        # ----------------------------------------------------------- DAEMON --
        c3 = clone(td, remote, "contrib3")
        (c3 / "predictions" / "_experiments" / "c3.txt").parent.mkdir(parents=True, exist_ok=True)
        (c3 / "predictions" / "_experiments" / "c3.txt").write_text("c3")
        commit(c3, "main moves under the daemon")
        check("DAEMON: setup, main moves", sync(c3, "push").returncode == 0)
        (d / "grades" / "astra" / "ada").mkdir(parents=True)
        (d / "grades" / "astra" / "ada" / "s1.json").write_text('{"g": "astra"}')
        results_for(d, 2)
        git(d, "add", "grades/astra/ada/s1.json", "results.json")
        git(d, "commit", "-q", "-m", "daemon: an astra grade and results")
        own = git(d, "rev-parse", "HEAD")
        p = sync(d, "push", "--daemon")
        check("DAEMON: the daemon's commit lands on a main that moved", p.returncode == 0, p.stdout + p.stderr[-600:])
        v = clone(td, remote, "v")
        tip = git(v, "rev-parse", "origin/main")
        parents = git(v, "rev-list", "--parents", "-n", "1", tip).split()[1:]
        reachable = subprocess.run(["git", "merge-base", "--is-ancestor", own, tip], cwd=v).returncode == 0
        check("DAEMON: by a merge, not a rebase: the daemon's own commit SHA is on main", reachable,
              f"parents {parents}")
        check("DAEMON: the dirty daemon files are byte-identical after the push",
              all((d / k).read_bytes() == v2 for k, v2 in dirty.items()))
        pushed = json.loads(git(v, "show", f"{tip}:grades/fable/ada/s1.json"))
        check("DAEMON: the dirty, uncommitted grade was NOT pushed", pushed == {"g": 1}, str(pushed))

        # ---------------------------------------------------------- RESULTS --
        (d / "grades" / "astra" / "ada" / "s2.json").write_text('{"g": "astra 2"}')
        results_for(d, 2)  # there are now 3 committed grade files, results says 2
        git(d, "add", "grades/astra/ada/s2.json", "results.json")
        git(d, "commit", "-q", "-m", "daemon: a grade committed with a stale results.json")
        before = git(d, "rev-parse", "HEAD")
        p = sync(d, "push", "--daemon")
        check("RESULTS: results.json that does not count the committed grades refuses, with both numbers",
              p.returncode != 0 and "grade_files_read 2" in p.stdout and "3 grade files" in p.stdout,
              p.stdout + p.stderr[-600:])
        check("RESULTS: and HEAD is where it was", git(d, "rev-parse", "HEAD") == before)
        results_for(d, 3)
        git(d, "add", "results.json")
        git(d, "commit", "-q", "-m", "daemon: results.json that counts them")
        p = sync(d, "push", "--daemon")
        check("RESULTS: a matching results.json passes", p.returncode == 0, p.stdout + p.stderr[-600:])

        # ----------------------------------------------------------- STAGED --
        (d / "logs").mkdir(exist_ok=True)
        (d / "logs" / "x.jsonl").write_text("{}\n")
        git(d, "add", "logs/x.jsonl")
        p = sync(d, "push", "--daemon")
        check("STAGED: a staged-but-uncommitted change refuses, saying so",
              p.returncode != 0 and "staged" in p.stdout, p.stdout + p.stderr[-600:])
        p = sync(d, "pull")
        check("STAGED: pull refuses it too", p.returncode != 0 and "staged" in p.stdout, p.stdout + p.stderr[-600:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
