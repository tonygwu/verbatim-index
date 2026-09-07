#!/usr/bin/env python3
"""Guards for the shared-data fleet layout adopted 2026-09-07.

Every clone's `data/` is now a symlink to one checkout at
`~/Code/misc/verbatim-index/data`, so all four clones read and write the same
bytes and any clone can deploy a current leaderboard. Three things had to
change with it, and each is guarded here.

  .venv/bin/python scripts/test_shared_data.py
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
PY = str(Path(sys.executable))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. results.json must never be readable in a half-written state.
#
# FOUND BY REVIEW of the shared-data plan. aggregate.py and build_site.py wrote
# several megabytes with Path.write_text, which truncates the file first. That
# was nearly harmless while only repo-0 read results.json, immediately after
# writing it in the same script. Sharing data/ breaks that: repo-1 can deploy
# at any moment, so it will sometimes read the file mid-rewrite. json.load
# raises on truncated input, so it fails loudly rather than publishing a wrong
# page, but an intermittently failing deploy is a bad thing to debug later.
# ---------------------------------------------------------------------------

def test_atomic_writes(tmp: Path) -> None:
    print("\n[1] a reader never sees a half-written results.json")
    a = load("atomicio")
    dest = tmp / "results.json"
    dest.write_text('{"generation": 1}')

    a.write_atomic(dest, '{"generation": 2}')
    check("a normal write replaces the file", json.loads(dest.read_text())["generation"] == 2)
    check("it leaves no temporary file behind",
          [p.name for p in tmp.iterdir()] == ["results.json"],
          f"{[p.name for p in tmp.iterdir()]}")

    # A write that dies before the rename must leave the old file untouched,
    # which is the whole point: truncate-then-write cannot offer this.
    real_replace = os.replace
    try:
        os.replace = lambda *a_, **k: (_ for _ in ()).throw(RuntimeError("crash mid-write"))
        try:
            a.write_atomic(dest, '{"generation": 3}')
        except RuntimeError:
            pass
    finally:
        os.replace = real_replace
    check("a write that fails before the rename leaves the previous version intact",
          json.loads(dest.read_text())["generation"] == 2, dest.read_text()[:80])
    check("and cleans up its temporary file",
          [p.name for p in tmp.iterdir()] == ["results.json"],
          f"{[p.name for p in tmp.iterdir()]}")

    for script, n in (("aggregate", 2), ("build_site", 1)):
        src = (REPO / "scripts" / f"{script}.py").read_text()
        check(f"{script}.py writes its outputs atomically",
              src.count("write_atomic(") >= n and "args.out).write_text(" not in src,
              "found a bare write_text on an output path")


# ---------------------------------------------------------------------------
# 2. A daemon started in the wrong clone would write to the live corpus.
#
# Before the share, a loop started in repo-1 wrote to repo-1's own copy and
# harmed nothing. Now every clone points at the one checkout, so the rule that
# only repo-0 runs daemons has to be a failing precondition rather than a line
# in CLAUDE.md.
# ---------------------------------------------------------------------------

def run_guard(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c",
                           f'cd "{root}" && . scripts/daemon_guard.sh && require_daemon_clone'],
                          capture_output=True, text=True)


def test_daemon_guard(tmp: Path) -> None:
    print("\n[2] a daemon refuses to start outside the clone that owns data/")
    guard = (REPO / "scripts" / "daemon_guard.sh").read_text()
    for name in ("repo-0", "repo-1"):
        root = tmp / name
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "daemon_guard.sh").write_text(guard)
        (root / "data").mkdir()

    r = run_guard(tmp / "repo-0")
    check("with no marker at all it refuses", r.returncode != 0, f"rc={r.returncode}")
    check("and says which file is missing", ".daemon-clone" in r.stderr, r.stderr[-200:])

    for name in ("repo-0", "repo-1"):
        (tmp / name / "data" / ".daemon-clone").write_text("repo-0\n")

    r = run_guard(tmp / "repo-0")
    check("in the clone the marker names, it allows the start", r.returncode == 0,
          f"rc={r.returncode} {r.stderr[-200:]}")

    r = run_guard(tmp / "repo-1")
    check("in any other clone it refuses", r.returncode != 0, f"rc={r.returncode}")
    check("and names both the clone it is in and the one that owns the daemons",
          "repo-1" in r.stderr and "repo-0" in r.stderr, r.stderr[-300:])

    for name in ("fetch_loop.sh", "happyscribe_loop.sh", "grade_loop.sh"):
        text = (REPO / "scripts" / name).read_text()
        check(f"{name} calls the guard", "require_daemon_clone" in text,
              "loop can start anywhere")
        i_guard = text.find("require_daemon_clone")
        i_work = min([i for i in (text.find("while true"), text.find("$PY ")) if i > 0] or [10**9])
        check(f"{name} calls it before doing any work", 0 <= i_guard < i_work,
              f"guard@{i_guard} work@{i_work}")


# ---------------------------------------------------------------------------
# 3. Deploying from any clone must publish current numbers.
#
# site/index.html is a per-clone build artifact. If deploy just shipped whatever
# was on disk, a clone that had never rendered would publish nothing and a stale
# one would publish old numbers. So the deploy renders first, every time.
# ---------------------------------------------------------------------------

def commands(path: Path) -> list[str]:
    joined, buf = [], ""
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        buf += " " + s
        if s.endswith("\\"):
            buf = buf[:-1]
            continue
        if buf.strip():
            joined.append(" ".join(buf.split()))
        buf = ""
    return joined


def test_deploy_renders_first() -> None:
    print("\n[3] a deploy renders the site before publishing it")
    d = REPO / "scripts" / "deploy.sh"
    check("scripts/deploy.sh exists", d.exists(), "no deploy script")
    if not d.exists():
        return
    check("it is executable", os.access(d, os.X_OK), "chmod +x scripts/deploy.sh")
    cmds = commands(d)
    i_build = [i for i, c in enumerate(cmds) if "build_site.py" in c]
    i_dep = [i for i, c in enumerate(cmds) if "wrangler deploy" in c]
    check("it renders the site", bool(i_build), f"{cmds}")
    check("it publishes the site", bool(i_dep), f"{cmds}")
    check("it renders before it publishes",
          bool(i_build) and bool(i_dep) and min(i_build) < min(i_dep),
          f"build@{i_build} deploy@{i_dep}")
    check("it renders from the shared results.json, not a stale artifact",
          any("data/results.json" in c for c in cmds), f"{cmds}")

    # Ordering alone is not enough. The first version of this script was missing
    # --calibration and --sources, so it parsed fine, ordered fine, and would
    # have died on the real invocation. So run it.
    loop = [c for c in commands(REPO / "scripts" / "grade_loop.sh") if "build_site.py" in c]
    mine = [c for c in cmds if "build_site.py" in c]
    def flags(c):
        # grade_loop.sh chains aggregate and build_site with &&, so slice from
        # the renderer onward or the comparison picks up aggregate's flags.
        tail = c.split("build_site.py", 1)[1]
        tail = tail.split("&&")[0].split("|")[0].split(">")[0]
        return {t for t in tail.split() if t.startswith("--")}
    check("it passes exactly the flags grade_loop.sh passes",
          bool(loop) and bool(mine) and flags(mine[0]) == flags(loop[0]),
          f"deploy={flags(mine[0]) if mine else None} loop={flags(loop[0]) if loop else None}")

    if not (REPO / "data" / "results.json").exists():
        print("  SKIP  no data/results.json in this clone; cannot run the render")
        return
    r = subprocess.run(["bash", str(d), "--dry-run"], capture_output=True, text=True, cwd=REPO)
    check("a dry run renders without error and publishes nothing", r.returncode == 0,
          (r.stderr or r.stdout)[-500:])
    check("the dry run reports what it would publish",
          "about to publish" in r.stdout and "leaders" in r.stdout, r.stdout[-300:])
    check("it never reaches wrangler on a dry run", "wrangler" not in r.stdout.lower(),
          r.stdout[-200:])
    check("it produced a site to publish", (REPO / "site" / "index.html").exists())


# ---------------------------------------------------------------------------
# 4. The public repo must not track the data symlink.
#
# `data/` with a trailing slash means "directory only", and git treats a symlink
# as a file. Verified: 'data/' does NOT ignore a symlink named data, so the
# first `git add -A` in any clone would commit it into the public repo.
# ---------------------------------------------------------------------------

def test_gitignore_covers_a_symlink(tmp: Path) -> None:
    print("\n[4] the public repo ignores data whether it is a directory or a symlink")
    subprocess.run(["git", "-C", str(tmp), "init", "-q"], check=True)
    (tmp / ".gitignore").write_text((REPO / ".gitignore").read_text())
    (tmp / "target").mkdir()
    (tmp / "target" / "f.txt").write_text("x")
    os.symlink("target", tmp / "data")
    r = subprocess.run(["git", "-C", str(tmp), "check-ignore", "-q", "data"])
    check("a data SYMLINK is ignored", r.returncode == 0,
          "git add -A would commit the symlink into the public repo")
    (tmp / "data").unlink()
    (tmp / "data").mkdir()
    r = subprocess.run(["git", "-C", str(tmp), "check-ignore", "-q", "data"])
    check("a data DIRECTORY is still ignored", r.returncode == 0,
          "the old layout would start tracking transcripts")


def main() -> int:
    print("shared-data fleet guards")
    for fn in (test_atomic_writes, test_daemon_guard, test_gitignore_covers_a_symlink):
        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))
    test_deploy_renders_first()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
