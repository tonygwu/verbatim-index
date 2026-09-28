#!/usr/bin/env python3
"""`data_sync.py bootstrap`: the one push no manifest can check, made narrow.

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P6. Every push is checked
against ownership.json on origin/main, so the push that ADDS it cannot be. Rather
than leave that to a hand-typed `git push`, bootstrap does exactly one thing: the
daemon clone adds this repo's template manifest (and, for leaders, its
.gitattributes) to a data repo that has none, byte for byte, and nothing else.

  DAEMON    the daemon clone bootstraps; origin/main then carries the template
            bytes, and data_sync.py check works against it.
  REFUSE    a contributor may not bootstrap; a repo that already has a manifest
            refuses; a checkout with any other uncommitted or unpushed change
            refuses, so nothing rides along.
  STUDY     --study pundits installs the all-owner pundits manifest.

  .venv/bin/python scripts/test_data_sync_bootstrap.py
"""
from __future__ import annotations

import importlib.util
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


spec = importlib.util.spec_from_file_location("tdsc_boot", REPO / "scripts" / "test_data_sync_check.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def boot(data: Path, *extra: str):
    return subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "bootstrap", "--data", str(data), *extra],
                          capture_output=True, text=True, cwd=REPO)


def main() -> int:
    L, A, T = C.load("predictions_lib"), C.load("aggregate_predictions"), C.load("test_predictions_aggregate")
    tpl = REPO / "data-repo-templates"
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        (td / "leaders").mkdir()
        remote = C.seed_remote(td / "leaders", L, A, T, manifest=None)

        contrib = C.clone(td, remote, "contrib", "contributor")
        p = boot(contrib)
        check("REFUSE: a contributor may not bootstrap", p.returncode != 0 and "daemon" in p.stdout, p.stdout + p.stderr[-300:])

        d = C.clone(td, remote, "daemon", "daemon")
        (d / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (d / "predictions" / "_experiments" / "x.json").write_text("{}")
        C.commit(d, "an unrelated unpushed commit")
        p = boot(d)
        check("REFUSE: an unpushed commit refuses, so nothing rides along",
              p.returncode != 0 and "unpushed" in p.stdout, p.stdout + p.stderr[-300:])
        C.git(d, "reset", "-q", "--hard", "origin/main")
        (d / "roster" / "final.json").write_text((d / "roster" / "final.json").read_text() + " ")
        p = boot(d)
        check("REFUSE: an uncommitted tracked change refuses", p.returncode != 0 and "uncommitted" in p.stdout,
              p.stdout + p.stderr[-300:])
        C.git(d, "checkout", "-q", "--", "roster/final.json")

        p = boot(d)
        check("DAEMON: the daemon clone bootstraps the leaders manifest", p.returncode == 0, p.stdout + p.stderr[-400:])
        v = C.clone(td, remote, "verify", "contributor")
        check("DAEMON: origin/main carries the template bytes exactly",
              (v / "ownership.json").read_bytes() == (tpl / "leaders" / "ownership.json").read_bytes()
              and (v / ".gitattributes").read_bytes() == (tpl / "leaders" / ".gitattributes").read_bytes())
        changed = C.git(v, "show", "--name-only", "--format=", "HEAD").split()
        check("DAEMON: the bootstrap commit changes exactly those two files",
              sorted(changed) == [".gitattributes", "ownership.json"], str(changed))
        (v / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (v / "predictions" / "_experiments" / "y.json").write_text("{}")
        C.commit(v, "a shared path")
        p = C.sync(v)
        check("DAEMON: check now works against the pushed manifest", p.returncode == 0, p.stdout + p.stderr[-300:])

        p = boot(d)
        check("REFUSE: a repo that already has a manifest refuses", p.returncode != 0 and "already" in p.stdout,
              p.stdout + p.stderr[-300:])

        (td / "pund").mkdir()
        premote = C.seed_remote(td / "pund", L, A, T, manifest=None)
        pd = C.clone(td, premote, "pund-daemon", "daemon")
        p = boot(pd, "--study", "pundits")
        pv = C.clone(td, premote, "pund-verify", "contributor")
        check("STUDY: --study pundits installs the all-owner manifest and no .gitattributes",
              p.returncode == 0 and (pv / "ownership.json").read_bytes() == (tpl / "pundits" / "ownership.json").read_bytes()
              and C.git(pv, "show", "--name-only", "--format=", "HEAD").split() == ["ownership.json"],
              p.stdout + p.stderr[-300:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
