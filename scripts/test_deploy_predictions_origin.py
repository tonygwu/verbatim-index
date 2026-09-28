#!/usr/bin/env python3
"""Any clone may deploy the predictions site, but only exactly origin/main.

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P5. Runs the real
deploy_predictions.sh in a throwaway public clone with its own remote, against a
real data remote, with a stub renderer and a stub npx that records the deploy.

  ORIGIN    a contributor clone at origin/main, clean, deploys; the page's
            revision.json names the data and public revisions it was built from.
  DIRTY     an uncommitted or untracked file in a published path refuses.
  AHEAD     a data HEAD that is not origin/main refuses.
  PUBLIC    public code that is not public origin/main refuses.
  MOVED     origin/main moving while the page renders refuses before npx runs.
  LIVE      the live revision must be an ancestor of ours: a live page built from
            a commit we do not descend from refuses; an unreadable one refuses
            unless --first-revision-deploy is passed.
  STALE     a pushed index that is behind its records refuses, whether the counts
            drifted or a record was rewritten in place with the counts equal; an
            index that predates a fingerprint refuses as unprovable.
  REFRESH   --refresh is gone and says to use data_sync.py push.
  OWNER     deploy.sh (the leaderboard) still refuses a contributor's checkout.

  .venv/bin/python scripts/test_deploy_predictions_origin.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
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


spec = importlib.util.spec_from_file_location("tdsp_deploy", REPO / "scripts" / "test_data_sync_push.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
git, clone, commit = P.git, P.clone, P.commit

RENDERER = """import os, pathlib, subprocess, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index('--out') + 1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text('rendered')
race = os.environ.get('RACE_CMD')
if race:
    subprocess.run(race, shell=True, check=True)
"""


def public_clone(td: Path) -> Path:
    remote = td / "public.git"
    git(td, "init", "-q", "--bare", "-b", "main", str(remote))
    pub = td / "pub" / "repo-7"
    pub.mkdir(parents=True)
    git(pub, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
        git(pub, "config", k, v)
    (pub / "scripts").mkdir()
    for name in ("data_clone_workflow.py", "study_profile.py", "daemon_guard.sh", "deploy_source.sh",
                 "deploy_predictions.sh", "deploy.sh", "publication_floor.py"):
        shutil.copy2(REPO / "scripts" / name, pub / "scripts" / name)
    (pub / "scripts" / "build_predictions_site.py").write_text(RENDERER)
    (pub / "scripts" / "build_site.py").write_text(RENDERER)
    shutil.copytree(REPO / "profiles", pub / "profiles")
    shutil.copy2(REPO / "membership.json", pub / "membership.json")
    shutil.copy2(REPO / "wrangler.predictions.toml", pub / "wrangler.predictions.toml")
    (pub / "site-predictions").mkdir()
    shutil.copy2(REPO / "site-predictions" / "_headers", pub / "site-predictions" / "_headers")
    (pub / ".gitignore").write_text(".venv\ndata\nsite-predictions/index.html\nsite-predictions/revision.json\n")
    git(pub, "add", "-A")
    git(pub, "commit", "-q", "-m", "public fixture")
    git(pub, "remote", "add", "origin", str(remote))
    git(pub, "push", "-q", "-u", "origin", "main")
    (pub / ".venv" / "bin").mkdir(parents=True)
    (pub / ".venv" / "bin" / "python").symlink_to(sys.executable)
    return pub


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t).resolve()
        remote, _ = P.seed(td)
        c = clone(td, remote, "contrib")
        first = git(c, "rev-list", "--max-parents=0", "HEAD")
        pub = public_clone(td)
        (pub / "data").symlink_to(c, target_is_directory=True)

        bin_dir = td / "bin"
        bin_dir.mkdir()
        deployed = td / "npx-called"
        (bin_dir / "npx").write_text(f"#!/bin/sh\necho \"$@\" >> {deployed}\nexit 0\n")
        (bin_dir / "npx").chmod(0o755)
        live = td / "live-revision.json"
        live.write_text(json.dumps({"data_revision": first}))
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               "VI_LIVE_REVISION_URL": live.as_uri()}

        def deploy(*extra: str, extra_env: dict | None = None, script: str = "deploy_predictions.sh"):
            if deployed.exists():
                deployed.unlink()
            return subprocess.run(["bash", str(pub / "scripts" / script), "--production-data", str(c),
                                   "--data-revision", git(c, "rev-parse", "HEAD"), *extra],
                                  capture_output=True, text=True, cwd=pub, env={**env, **(extra_env or {})})

        # ----------------------------------------------------------- ORIGIN --
        p = deploy("--dry-run")
        check("ORIGIN: a contributor's dry run at origin/main passes", p.returncode == 0 and "published nothing" in p.stdout,
              p.stdout[-400:] + p.stderr[-600:])
        p = deploy()
        check("ORIGIN: a contributor deploys, and npx runs", p.returncode == 0 and deployed.exists(),
              p.stdout[-400:] + p.stderr[-600:])
        rev = json.loads((pub / "site-predictions" / "revision.json").read_text()) \
            if (pub / "site-predictions" / "revision.json").exists() else {}
        check("ORIGIN: revision.json names the data and public revisions it was built from",
              rev.get("data_revision") == git(c, "rev-parse", "HEAD") and rev.get("public_revision") == git(pub, "rev-parse", "HEAD"),
              str(rev))

        # ------------------------------------------------------------ DIRTY --
        (c / "predictions" / "scoring.json").write_text((c / "predictions" / "scoring.json").read_text() + " ")
        p = deploy("--dry-run")
        check("DIRTY: an uncommitted published file refuses, naming it",
              p.returncode != 0 and "predictions/scoring.json" in p.stderr, p.stderr[-500:])
        git(c, "checkout", "-q", "--", "predictions/scoring.json")
        (c / "predictions" / "stray.json").write_text("{}")
        p = deploy("--dry-run")
        check("DIRTY: an untracked published file refuses, naming it",
              p.returncode != 0 and "predictions/stray.json" in p.stderr, p.stderr[-500:])
        (c / "predictions" / "stray.json").unlink()

        # ------------------------------------------------------------ AHEAD --
        (c / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (c / "predictions" / "_experiments" / "local.txt").write_text("x")
        commit(c, "an unpushed local commit")
        p = deploy("--dry-run")
        check("AHEAD: a data HEAD that is not origin/main refuses", p.returncode != 0 and "origin/main" in p.stderr,
              p.stderr[-500:])
        git(c, "reset", "-q", "--hard", "origin/main")

        # ----------------------------------------------------------- PUBLIC --
        (pub / "notes.txt").write_text("local")
        git(pub, "add", "notes.txt")
        git(pub, "commit", "-q", "-m", "unpushed public change")
        p = deploy("--dry-run")
        check("PUBLIC: public code that is not public origin/main refuses", p.returncode != 0 and "public" in p.stderr,
              p.stderr[-500:])
        git(pub, "reset", "-q", "--hard", "origin/main")

        # ------------------------------------------------------------ MOVED --
        racer = clone(td, remote, "racer")
        (racer / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        race = (f"cd {racer} && echo r > predictions/_experiments/race.txt && git add -A && "
                f"git commit -q -m race && git push -q origin main")
        p = deploy(extra_env={"RACE_CMD": race})
        check("MOVED: origin/main moving during the render refuses before npx",
              p.returncode != 0 and "moved" in p.stderr and not deployed.exists(), p.stderr[-500:])
        git(c, "pull", "-q", "--ff-only")

        # ------------------------------------------------------------- LIVE --
        side = clone(td, remote, "side")
        git(side, "switch", "-q", "-c", "elsewhere")
        (side / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (side / "predictions" / "_experiments" / "side.txt").write_text("s")
        not_ancestor = commit(side, "a commit main does not contain")
        git(side, "push", "-q", "origin", "elsewhere")
        live.write_text(json.dumps({"data_revision": not_ancestor}))
        p = deploy()
        check("LIVE: a live page built from a commit we do not descend from refuses",
              p.returncode != 0 and "ancestor" in p.stderr and not deployed.exists(), p.stderr[-500:])
        live.unlink()
        p = deploy()
        check("LIVE: an unreadable live revision refuses", p.returncode != 0 and "live revision" in p.stderr
              and not deployed.exists(), p.stderr[-500:])
        p = deploy("--first-revision-deploy")
        check("LIVE: --first-revision-deploy allows it once", p.returncode == 0 and deployed.exists(), p.stderr[-500:])

        # ------------------------------------------------------------ STALE --
        # Pushed raw, with no hook installed, to put a stale index on main the
        # way a hand-typed git push could.
        def raw_push_to_main(msg: str) -> None:
            commit(c, msg)
            git(c, "push", "-q", "origin", "HEAD:main")

        def restore_fresh() -> None:
            q = subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "push", "--data", str(c)],
                               capture_output=True, text=True, cwd=REPO)
            assert q.returncode == 0, q.stdout + q.stderr

        live.write_text(json.dumps({"data_revision": first}))
        recs = P.read_records(c, "ada", "s1")
        recs[0]["prediction"]["normalized_claim"] = "rewritten in place, same counts"
        P.write_records(c, "ada", "s1", recs)
        raw_push_to_main("a record rewritten in place, index not regenerated")
        p = deploy("--dry-run")
        check("STALE: a record rewritten in place with the counts equal refuses",
              p.returncode != 0 and "stale production index" in p.stderr and "in place" in p.stdout,
              p.stdout[-300:] + p.stderr[-300:])
        restore_fresh()
        P.add_transcript(c, "transcripts_web", "alan", "w9", [P.Q[1]])
        raw_push_to_main("a new record file, index not regenerated")
        p = deploy("--dry-run")
        check("STALE: records added without regenerating the index refuse on the counts",
              p.returncode != 0 and "stale production index" in p.stderr and "counts changed" in p.stdout,
              p.stdout[-300:] + p.stderr[-300:])
        restore_fresh()
        idx = json.loads((c / "predictions" / "index.json").read_text())
        del idx["transcripts_listing_sha256"]
        (c / "predictions" / "index.json").write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n")
        raw_push_to_main("an index from before the listing fingerprint")
        p = deploy("--dry-run")
        check("STALE: an index that predates a fingerprint refuses as unprovable",
              p.returncode != 0 and "refresh the production index" in p.stderr, p.stdout[-300:] + p.stderr[-300:])
        restore_fresh()
        p = deploy("--dry-run")
        check("STALE: after data_sync.py push regenerates it, the deploy passes again", p.returncode == 0,
              p.stdout[-300:] + p.stderr[-300:])

        # ---------------------------------------------------------- REFRESH --
        p = deploy("--refresh", "--dry-run")
        check("REFRESH: --refresh refuses and points at data_sync.py push",
              p.returncode != 0 and "data_sync.py push" in p.stderr, p.stderr[-500:])

        # ------------------------------------------------------------ OWNER --
        p = deploy("--dry-run", script="deploy.sh")
        check("OWNER: the leaderboard deploy still refuses a contributor's checkout",
              p.returncode != 0 and "production source" in p.stderr, p.stderr[-500:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
