#!/usr/bin/env python3
"""The pundits publication path: guarded like the other two sites, and it cannot reach them.

Pundits plan, P4c. scripts/deploy_pundits.sh renders verbatim-pundits.tonygwu.com
from the explicitly named pundits production checkout and publishes through
wrangler.pundits.toml. Every real `npx` here is a tripwire that records its
arguments and exits 93, so nothing is ever published by this test.

  DRY-RUN      renders site-pundits/index.html from the registered pundits checkout
               and publishes nothing
  SOURCE       leaders data, or no data revision, is refused before rendering
  STALE        a results.json built from fewer grade files than are on disk is refused
  TARGET       a non-dry run reaches only the tripwire, and names wrangler.pundits.toml
  LEADERS      the leaders deploy.sh still refuses the pundits checkout
  CONFIG       wrangler.pundits.toml names its own Worker, directory and domain

  .venv/bin/python scripts/test_deploy_pundits.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
SCRIPTS = ("data_clone_workflow.py", "study_profile.py", "study_env.sh", "daemon_guard.sh",
           "deploy_source.sh", "deploy.sh", "deploy_pundits.sh", "build_site.py", "build_study_site.py",
           "aggregate.py", "atomicio.py", "site_theme.py", "grading_contract.py")


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def data_checkout(path: Path, origin: str, study: str | None, grade_files: int, read_n: int) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "446441+tonygwu@users.noreply.github.com")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "remote.origin.url", f"git@github.com:tonygwu/{origin}.git")
    if study:
        (path / ".study").write_text(study + "\n")
    (path / ".gitignore").write_text(".daemon-clone\n")
    (path / ".daemon-clone").write_text("repo-9\n")
    dims = [d["key"] for d in json.loads((REPO / "profiles/pundits.json").read_text())["scoring"]["dimensions"]]
    results = {"leaders": [{"rank": 1, "slug": "p1", "name": "Pat Undit", "role": "host", "status": "scored",
                            "n_transcripts": 6, "confidence": "high",
                            "blinded": {"overall": 55.0, "ci_low": 50.0, "ci_high": 60.0, **{d: 55.0 for d in dims}},
                            "open": {}, "halo": {}}],
               "unranked": [], "diagnostics": {"grades_used": grade_files, "grade_files_read": read_n}}
    (path / "results.json").write_text(json.dumps(results))
    (path / "results_audit.json").write_text("{}")
    (path / "roster").mkdir()
    (path / "roster/final.json").write_text(json.dumps({"roster": []}))
    (path / "logs").mkdir()
    (path / "logs/calibration.json").write_text("{}")
    for i in range(grade_files):
        g = path / "grades/fable/p1" / f"s{i}__fable__blinded__r0.json"
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text("{}")
    # Not grades: a moved-aside grade and a run provenance record must not count.
    for extra in ("grades/_obsolete/fable/p1/s0.old.json", "grades/_provenance/abc.json", "grades/_raw/fable/p1/s0.txt"):
        e = path / extra
        e.parent.mkdir(parents=True, exist_ok=True)
        e.write_text("{}")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return git(path, "rev-parse", "HEAD")


def public_clone(parent: Path, leaders: Path, pundits: Path) -> Path:
    pub = parent / "repo-9"
    (pub / "scripts").mkdir(parents=True)
    git(pub, "init", "-q", "-b", "main")
    for name in SCRIPTS:
        if (REPO / "scripts" / name).exists():
            shutil.copy2(REPO / "scripts" / name, pub / "scripts" / name)
    shutil.copytree(REPO / "profiles", pub / "profiles")
    for name in ("wrangler.toml", "wrangler.pundits.toml"):
        if (REPO / name).exists():
            shutil.copy2(REPO / name, pub / name)
    (pub / ".venv/bin").mkdir(parents=True)
    (pub / ".venv/bin/python").symlink_to(sys.executable)
    (pub / "data").symlink_to(leaders, target_is_directory=True)
    (pub / "data-pundits").symlink_to(pundits, target_is_directory=True)
    git(pub, "config", "verbatim.productionData", str(leaders))
    git(pub, "config", "verbatim.pundits.productionData", str(pundits))
    return pub


def run(pub: Path, script: str, *args, bin_dir: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("STUDY", "DATA", "SITE_DIR", "RUN_MARKER_DIR")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(["bash", str(pub / "scripts" / script), *map(str, args)], cwd=pub, env=env,
                          capture_output=True, text=True)


def main() -> int:
    print("pundits deploy path")
    if not (REPO / "scripts/deploy_pundits.sh").exists() or not (REPO / "wrangler.pundits.toml").exists():
        check("scripts/deploy_pundits.sh and wrangler.pundits.toml exist", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    with tempfile.TemporaryDirectory(prefix="p4c-") as td:
        tmp = Path(td).resolve()
        leaders = tmp / "leaders-data"
        rev_l = data_checkout(leaders, "verbatim-index-data", None, 1, 1)
        pundits = tmp / "pundits-data"
        rev_p = data_checkout(pundits, "verbatim-pundits-data", "pundits", 2, 2)
        stale = tmp / "pundits-stale"
        pub = public_clone(tmp, leaders, pundits)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        record = tmp / "npx-args.txt"
        (bin_dir / "npx").write_text(f'#!/bin/sh\necho "$@" > "{record}"\necho DEPLOY-TRIPWIRE >&2\nexit 93\n')
        (bin_dir / "npx").chmod(0o755)

        print("\n[DRY-RUN]")
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        page = pub / "site-pundits" / "index.html"
        check("a dry run from the registered pundits checkout succeeds", r.returncode == 0, r.stderr[-400:])
        check("it renders the pundits page", page.exists() and "Verbatim Pundits" in page.read_text())
        check("it says it published nothing, and never reached npx",
              "published nothing" in r.stdout and not record.exists(), r.stdout[-300:])
        check("the staleness count ignores _obsolete, _provenance and _raw", "covers all 2 grade files" in r.stdout,
              r.stdout[-300:])
        check("the leaders page was not written", not (pub / "site" / "index.html").exists())

        print("\n[SOURCE]")
        r = run(pub, "deploy_pundits.sh", "--production-data", leaders, "--data-revision", rev_l, "--dry-run",
                bin_dir=bin_dir)
        check("leaders data is refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--dry-run", bin_dir=bin_dir)
        check("a missing data revision is refused", r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])

        print("\n[STALE]")
        git(pub, "config", "verbatim.pundits.productionData", str(stale))
        rev_s = data_checkout(stale, "verbatim-pundits-data", "pundits", 3, 1)
        (pub / "data-pundits").unlink()
        (pub / "data-pundits").symlink_to(stale, target_is_directory=True)
        r = run(pub, "deploy_pundits.sh", "--production-data", stale, "--data-revision", rev_s, "--dry-run",
                bin_dir=bin_dir)
        check("a stale aggregate is refused", r.returncode != 0 and "stale" in (r.stdout + r.stderr).lower(),
              (r.stdout + r.stderr)[-300:])
        git(pub, "config", "verbatim.pundits.productionData", str(pundits))
        (pub / "data-pundits").unlink()
        (pub / "data-pundits").symlink_to(pundits, target_is_directory=True)

        print("\n[TARGET]")
        r = run(pub, "deploy_pundits.sh", "--production-data", pundits, "--data-revision", rev_p, bin_dir=bin_dir)
        args = record.read_text().strip() if record.exists() else ""
        check("a non-dry run reaches only the tripwire", r.returncode != 0 and "DEPLOY-TRIPWIRE" in r.stderr,
              f"rc={r.returncode} {r.stderr[-200:]}")
        check("and names wrangler.pundits.toml", args == "wrangler deploy -c wrangler.pundits.toml", args)

        print("\n[LEADERS]")
        r = run(pub, "deploy.sh", "--production-data", pundits, "--data-revision", rev_p, "--dry-run",
                bin_dir=bin_dir)
        check("the leaders deploy.sh refuses the pundits checkout",
              r.returncode != 0 and "REFUSING" in r.stderr, r.stderr[-300:])

    print("\n[CONFIG]")
    cfg = (REPO / "wrangler.pundits.toml").read_text()
    lead = (REPO / "wrangler.toml").read_text()
    check("its Worker is verbatim-pundits", 'name = "verbatim-pundits"' in cfg)
    check("its assets directory is ./site-pundits", 'directory = "./site-pundits"' in cfg)
    check("its route is verbatim-pundits.tonygwu.com", 'pattern = "verbatim-pundits.tonygwu.com"' in cfg)
    check("it shares no Worker name or route with the leaders config",
          'name = "verbatim-index"' not in cfg and "verbatim-index.tonygwu.com" not in cfg and "verbatim-pundits" not in lead)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
