#!/usr/bin/env python3
"""Roles, the pre-push hook, and moving an experiment clone onto main.

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P4.

  GUARD     a contributor clone may write its own predictions/ but never into the
            daemon's live checkout.
  HOOK      with core.hooksPath set, a RAW `git push` to main runs the same check
            as data_sync.py: an owner path is rejected, a shared one lands, and a
            push to any other branch is not checked.
  ADOPT     adopt-main makes a fresh checkout at origin/main with role
            contributor and the hook installed, carries whole experiment runs
            that main lacks (committed or untracked), and REPORTS every other
            path it left behind with a reason, including an owner-path commit.
            The dry run changes nothing; the old checkout is left intact.

  .venv/bin/python scripts/test_data_sync_roles.py
"""
from __future__ import annotations

import importlib.util
import json
import os
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


spec = importlib.util.spec_from_file_location("tdsp_roles", REPO / "scripts" / "test_data_sync_push.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
git, clone, commit = P.git, P.clone, P.commit
sys.path.insert(0, str(REPO / "scripts"))
import data_clone_workflow as D  # noqa: E402

HOOKS = REPO / "scripts" / "git-hooks" / "data"


def raw_push(c: Path, refspec: str):
    return subprocess.run(["git", "-C", str(c), "push", "origin", refspec], capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote, _ = P.seed(td)

        # ------------------------------------------------------------ GUARD --
        live = clone(td, remote, "live", role="daemon")
        pub = td / "pub"
        pub.mkdir()
        own = clone(td, remote, "own")
        subprocess.run(["git", "init", "-q", str(pub)], check=True)
        subprocess.run(["git", "-C", str(pub), "config", "verbatim.productionData", str(live)], check=True)
        refused = ""
        try:
            D.guard_prediction_write(pub, live / "predictions" / "ada" / "x.jsonl", own)
        except RuntimeError as exc:
            refused = str(exc)
        check("GUARD: a contributor cannot write into the daemon's live checkout", "contributor" in refused, refused)
        try:
            D.guard_prediction_write(pub, own / "predictions" / "ada" / "x.jsonl", own)
            ok = True
        except RuntimeError as exc:
            ok, refused = False, str(exc)
        check("GUARD: a contributor may write its own predictions/", ok, refused if not ok else "")

        # ------------------------------------------------------------- HOOK --
        h = clone(td, remote, "hooked")
        git(h, "config", "core.hooksPath", str(HOOKS))
        (h / "roster" / "final.json").write_text((h / "roster" / "final.json").read_text().replace("Lab", "Lab2"))
        commit(h, "an owner path, pushed raw")
        p = raw_push(h, "HEAD:main")
        check("HOOK: a raw push of an owner path to main is rejected by the hook, naming it",
              p.returncode != 0 and "roster/final.json" in p.stdout + p.stderr, p.stdout + p.stderr[-500:])
        p = raw_push(h, "HEAD:refs/heads/side-branch")
        check("HOOK: a push to another branch is not checked", p.returncode == 0, p.stdout + p.stderr[-500:])
        git(h, "reset", "-q", "--hard", "origin/main")
        (h / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (h / "predictions" / "_experiments" / "hooked.txt").write_text("x")
        commit(h, "a shared path, pushed raw")
        p = raw_push(h, "HEAD:main")
        check("HOOK: a raw push of a shared path lands", p.returncode == 0, p.stdout + p.stderr[-500:])

        # ------------------------------------------------------------ ADOPT --
        repo = td / "repo-9"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".gitignore").write_text("data\n.data-clones/\n")
        old = repo / ".data-clones" / "experiment"
        old.parent.mkdir()
        subprocess.run(["git", "clone", "-q", "--no-local", str(remote), str(old)], check=True)
        for k, v in (("user.email", "t@example.com"), ("user.name", "T"), ("verbatim.role", "experiment")):
            git(old, "config", k, v)
        git(old, "switch", "-q", "-c", "codex/repo-9-data")
        (old / "predictions" / "_experiments" / "run-a").mkdir(parents=True)
        (old / "predictions" / "_experiments" / "run-a" / "r.json").write_text('{"a": 1}')
        commit(old, "an experiment run")
        (old / "roster" / "final.json").write_text((old / "roster" / "final.json").read_text().replace("Lab", "Lab3"))
        commit(old, "a roster fix on the experiment branch")
        (old / "predictions" / "_experiments" / "run-u").mkdir(parents=True)
        (old / "predictions" / "_experiments" / "run-u" / "u.json").write_text('{"u": 1}')  # untracked
        (repo / "data").symlink_to(old, target_is_directory=True)

        p = subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "adopt-main", "--repo", str(repo)],
                           capture_output=True, text=True, cwd=REPO)
        check("ADOPT: the dry run exits 0 and changes nothing",
              p.returncode == 0 and (repo / "data").resolve() == old.resolve()
              and not (repo / ".data-clones" / "main").exists(), p.stdout + p.stderr[-500:])
        check("ADOPT: the dry run lists the runs it would carry",
              "predictions/_experiments/run-a" in p.stdout and "predictions/_experiments/run-u" in p.stdout, p.stdout)
        check("ADOPT: the dry run reports the owner-path commit as skipped, with its reason",
              "roster/final.json" in p.stdout and "skipped" in p.stdout and "owner" in p.stdout, p.stdout)

        p = subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "adopt-main", "--repo", str(repo), "--apply"],
                           capture_output=True, text=True, cwd=REPO)
        new = repo / ".data-clones" / "main"
        check("ADOPT: --apply switches data to a fresh checkout on main",
              p.returncode == 0 and (repo / "data").resolve() == new.resolve()
              and git(new, "rev-parse", "--abbrev-ref", "HEAD") == "main"
              and git(new, "rev-parse", "HEAD") == git(new, "rev-parse", "origin/main"), p.stdout + p.stderr[-500:])
        check("ADOPT: the new checkout is a contributor with the hook installed",
              git(new, "config", "--local", "verbatim.role") == "contributor"
              and Path(git(new, "config", "--local", "core.hooksPath")).resolve() == HOOKS.resolve())
        check("ADOPT: whole experiment runs are carried, committed and untracked alike",
              (new / "predictions/_experiments/run-a/r.json").read_text() == '{"a": 1}'
              and (new / "predictions/_experiments/run-u/u.json").read_text() == '{"u": 1}')
        check("ADOPT: the owner-path change is NOT carried", "Lab3" not in (new / "roster/final.json").read_text())
        check("ADOPT: the old checkout is left intact on its branch",
              git(old, "rev-parse", "--abbrev-ref", "HEAD") == "codex/repo-9-data"
              and (old / "predictions/_experiments/run-u/u.json").exists())
        report = new / ".git" / "verbatim-adopt-main.json"
        rep = json.loads(report.read_text()) if report.exists() else {}
        check("ADOPT: the report is kept in the new checkout, naming every skipped path",
              any(s.get("path") == "roster/final.json" for s in rep.get("skipped", [])), str(rep)[:300])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
