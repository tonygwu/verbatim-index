#!/usr/bin/env python3
"""Production jobs require an explicit verbatim.role=daemon, from one predicate.

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P4b (review item 2).
Until P4b the guards asked only "is this NOT an experiment checkout?", so a
checkout with no role at all, or a contributor's, passed. Now every production
guard asks data_clone_workflow.daemon_role_error(), and the shell guard calls
that same function, so the two cannot drift apart.

  AGREE     for every role (unset, experiment, contributor, daemon), with the
            owner marker naming this clone, the shell guard and owner_error()
            give the same verdict, and only daemon passes.
  MARKER    role=daemon does not replace the marker: a marker naming another
            clone still refuses, in both.
  USERS     publication_source(), setup() and withdraw_sources refuse a source
            without role=daemon.

  .venv/bin/python scripts/test_daemon_role.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import data_clone_workflow as D  # noqa: E402

FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def clone_dir(td: Path, name: str, role: str | None, marker: str) -> Path:
    """A fake public clone named `name` whose `data` is a git repo with that role."""
    repo = td / name
    (repo / "scripts").mkdir(parents=True)
    for f in ("data_clone_workflow.py", "study_profile.py", "daemon_guard.sh"):
        shutil.copy2(REPO / "scripts" / f, repo / "scripts" / f)
    shutil.copytree(REPO / "profiles", repo / "profiles")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
    data = repo / "data"
    data.mkdir()
    git(data, "init", "-q", "-b", "main")
    if role:
        git(data, "config", "verbatim.role", role)
    (data / ".daemon-clone").write_text(marker + "\n")
    return repo


def shell_verdict(repo: Path) -> tuple[bool, str]:
    p = subprocess.run(["bash", "-c", ". scripts/daemon_guard.sh; require_daemon_clone"], cwd=repo,
                       capture_output=True, text=True, env={**os.environ, "STUDY": "leaders"})
    return p.returncode == 0, p.stderr


def main() -> int:
    check("the predicate exists", callable(getattr(D, "daemon_role_error", None)))
    with tempfile.TemporaryDirectory() as t:
        td = Path(t).resolve()
        for role in (None, "experiment", "contributor", "daemon"):
            name = f"repo-{role or 'none'}"
            repo = clone_dir(td, name, role, marker=name)
            sh_ok, sh_err = shell_verdict(repo)
            py_err = D.owner_error(repo)
            want = role == "daemon"
            check(f"AGREE: role {role or 'unset'}: the shell guard {'passes' if want else 'refuses'}",
                  sh_ok is want, sh_err[-300:])
            check(f"AGREE: role {role or 'unset'}: owner_error {'passes' if want else 'refuses'}",
                  (py_err is None) is want, str(py_err))
            if not want:
                check(f"AGREE: role {role or 'unset'}: both refusals name the role they need",
                      "verbatim.role=daemon" in sh_err and "verbatim.role=daemon" in str(py_err),
                      sh_err[-200:] + " | " + str(py_err))

        other = clone_dir(td, "repo-other", "daemon", marker="repo-0")
        sh_ok, sh_err = shell_verdict(other)
        check("MARKER: role=daemon with a marker naming another clone refuses in the shell", not sh_ok, sh_err)
        check("MARKER: and in owner_error", D.owner_error(other) is not None)

        unset = clone_dir(td, "repo-unset2", None, marker="repo-unset2")
        git(unset / "data", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "x")
        rev = git(unset / "data", "rev-parse", "HEAD")
        subprocess.run(["git", "-C", str(unset), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(unset), "config", "verbatim.productionData", str(unset / "data")], check=True)
        why = ""
        try:
            D.publication_source(unset, unset / "data", rev)
        except RuntimeError as exc:
            why = str(exc)
        check("USERS: owner-mode publication refuses a source with no role", "verbatim.role=daemon" in why, why)
        why = ""
        (td / "repo-req").mkdir()
        subprocess.run(["git", "-C", str(td / "repo-req"), "init", "-q"], check=True)
        try:
            D.setup(td / "repo-req", unset / "data", rev, "codex/x", [], apply=False)
        except RuntimeError as exc:
            why = str(exc)
        check("USERS: setup refuses a source with no role", "verbatim.role=daemon" in why, why)
        import withdraw_sources as W
        why = W.require_daemon_clone(unset)
        check("USERS: withdraw_sources refuses a checkout with no role", "verbatim.role=daemon" in str(why), str(why))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
