#!/usr/bin/env python3
"""`data_sync.py check`: may this clone push these commits to the data repo's main?

Plan: docs/plans/shared-data-push-2026-09-27.md, phase P1. Every check here runs
real git against a bare remote in a temp directory, never a source inspection.

  PATHS     every path a commit touches is classified by ownership.json: a
            contributor may change shared and derived paths, never owner ones;
            deletes and renames count; an unlisted path is refused; the pundits
            manifest refuses a contributor everywhere.
  ROLE      a daemon may change owner paths; a checkout with no role refuses.
  TREE      freshness is read from the commit being pushed, never from disk, so
            an untracked or unstaged file cannot make a stale index look fresh.
  STALE     a commit whose derived index is behind its own records refuses.
  MANIFEST  origin/main without ownership.json refuses; it never defaults.
  REF       the report names the origin/main SHA it read, and whether it fetched.
  ATTRS     the .gitattributes template marks every record file merge=binary,
            however deep, counted against git ls-tree.

  .venv/bin/python scripts/test_data_sync_check.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
TEMPLATES = REPO / "data-repo-templates"
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def load(name: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(f"{name}_ds", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr}")
    return p.stdout.strip()


def sync(data: Path, *args: str):
    return subprocess.run([PY, str(REPO / "scripts" / "data_sync.py"), "check", "--data", str(data), *args],
                          capture_output=True, text=True, cwd=REPO)


def seed_remote(td: Path, L, A, T, manifest: str | None = "leaders") -> Path:
    """A bare remote whose main holds a fresh index over a small fixture corpus."""
    remote = td / "remote.git"
    git(td, "init", "-q", "--bare", "-b", "main", str(remote))
    seed = td / "seed"
    git(td, "clone", "-q", str(remote), str(seed))
    for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
        git(seed, "config", k, v)
    build_root = td / "build"
    build_root.mkdir()
    pr = T.build(build_root, L)
    shutil.copytree(pr, seed / "predictions")
    (seed / "roster").mkdir()
    shutil.copy(build_root / "roster.json", seed / "roster" / "final.json")
    shutil.copytree(build_root / "tx", seed / "transcripts_open")
    (seed / "transcripts_web").mkdir()
    (seed / "transcripts_web" / ".keep").write_text("")
    write_index(seed, L, A)
    if manifest:
        shutil.copy(TEMPLATES / manifest / "ownership.json", seed / "ownership.json")
        if (TEMPLATES / manifest / ".gitattributes").exists():
            shutil.copy(TEMPLATES / manifest / ".gitattributes", seed / ".gitattributes")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", "origin", "main")
    return remote


def write_index(root: Path, L, A) -> None:
    roster = {r["slug"]: r for r in json.loads((root / "roster" / "final.json").read_text())["roster"]}
    idx = A.build_index(root / "predictions", roster, [root / "transcripts_open", root / "transcripts_web"],
                        root / "roster" / "final.json")
    (root / "predictions" / "index.json").write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n")


def clone(td: Path, remote: Path, name: str, role: str | None) -> Path:
    c = td / name
    git(td, "clone", "-q", str(remote), str(c))
    for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
        git(c, "config", k, v)
    if role:
        git(c, "config", "verbatim.role", role)
    return c


def commit(c: Path, msg: str) -> None:
    git(c, "add", "-A")
    git(c, "commit", "-q", "-m", msg)


def main() -> int:
    L, A, T = load("predictions_lib"), load("aggregate_predictions"), load("test_predictions_aggregate")
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote = seed_remote(td, L, A, T)

        # ------------------------------------------------------------ PATHS --
        c = clone(td, remote, "contrib", "contributor")
        run = c / "predictions" / "_experiments" / "run-1" / "notes.json"
        run.parent.mkdir(parents=True)
        run.write_text("{}")
        commit(c, "a shared path")
        p = sync(c)
        check("PATHS: a contributor may push a shared path", p.returncode == 0, p.stdout + p.stderr[-400:])
        check("REF: the report names the origin/main SHA it read and that it fetched",
              git(c, "rev-parse", "origin/main")[:12] in p.stdout and "fetched" in p.stdout, p.stdout)

        (c / "roster" / "final.json").write_text((c / "roster" / "final.json").read_text().replace("Admiral", "Adm."))
        commit(c, "an owner path")
        p = sync(c)
        check("PATHS: a contributor may not change an owner path, and the path is named",
              p.returncode != 0 and "roster/final.json" in p.stdout + p.stderr, p.stdout + p.stderr[-400:])
        git(c, "reset", "-q", "--hard", "HEAD~1")

        git(c, "rm", "-q", "transcripts_open/ada/t0.json")
        git(c, "commit", "-q", "-m", "a delete")
        p = sync(c)
        check("PATHS: deleting an owner path is refused like changing it",
              p.returncode != 0 and "transcripts_open/ada/t0.json" in p.stdout + p.stderr, p.stdout + p.stderr[-400:])
        git(c, "reset", "-q", "--hard", "HEAD~1")

        git(c, "mv", "transcripts_open/ada/t1.json", "transcripts_web/t1.json")
        git(c, "commit", "-q", "-m", "a rename out of an owner path")
        p = sync(c)
        check("PATHS: a rename is checked at BOTH ends, so moving a file out of an owner path refuses",
              p.returncode != 0 and "transcripts_open/ada/t1.json" in p.stdout + p.stderr, p.stdout + p.stderr[-400:])
        git(c, "reset", "-q", "--hard", "HEAD~1")

        (c / "mystery").mkdir()
        (c / "mystery" / "x.txt").write_text("x")
        commit(c, "an unlisted path")
        p = sync(c)
        check("PATHS: an unlisted path is refused, not defaulted", p.returncode != 0 and "mystery/x.txt" in
              p.stdout + p.stderr and "unlisted" in p.stdout + p.stderr, p.stdout + p.stderr[-400:])
        git(c, "reset", "-q", "--hard", "HEAD~1")

        # ------------------------------------------------------------- ROLE --
        d = clone(td, remote, "daemon", "daemon")
        (d / "roster" / "final.json").write_text((d / "roster" / "final.json").read_text().replace("Admiral", "Adm."))
        write_index(d, L, A)
        commit(d, "roster change by the owner, with its index")
        p = sync(d)
        check("ROLE: the daemon owner may change an owner path", p.returncode == 0, p.stdout + p.stderr[-400:])

        n = clone(td, remote, "norole", None)
        (n / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (n / "predictions" / "_experiments" / "x.json").write_text("{}")
        commit(n, "no role")
        p = sync(n)
        check("ROLE: a checkout with no verbatim.role refuses", p.returncode != 0 and "verbatim.role" in
              p.stdout + p.stderr, p.stdout + p.stderr[-400:])

        # ------------------------------------------------------------ STALE --
        rec = sorted((c / "predictions" / "ada").glob("*.jsonl"))[0]
        rec.write_text(rec.read_text().replace("most code", "most CODE", 1))
        commit(c, "a record edit without regenerating the index")
        p = sync(c)
        check("STALE: a commit whose index is behind its records refuses, naming the index",
              p.returncode != 0 and "predictions/index.json is stale in the commit" in p.stdout, p.stdout + p.stderr[-400:])
        write_index(c, L, A)
        commit(c, "regenerate the index")
        p = sync(c)
        check("STALE: regenerating the index in the commit makes it pass", p.returncode == 0, p.stdout + p.stderr[-400:])

        # ------------------------------------------------------------- TREE --
        # Stage the index back to stale in the COMMIT but leave a fresh copy on
        # disk: the check must read the commit.
        fresh = (c / "predictions" / "index.json").read_text()
        rec.write_text(rec.read_text().replace("most CODE", "most Code", 1))
        commit(c, "another record edit, index not regenerated")
        (c / "predictions" / "index.json").write_text(fresh)  # unrelated disk state, uncommitted
        write_index(c, L, A)  # disk index is now FRESH for the disk records, but not committed
        p = sync(c)
        check("TREE: a fresh index on disk does not rescue a stale index in the commit",
              p.returncode != 0 and "predictions/index.json is stale in the commit" in p.stdout,
              p.stdout + p.stderr[-400:])
        git(c, "checkout", "-q", "--", "predictions/index.json")

        # --------------------------------------------------------- MANIFEST --
        bare = seed_remote(td / "nomanifest", L, A, T, manifest=None) if (td / "nomanifest").mkdir() is None else None
        m = clone(td, bare, "nomanifest-clone", "contributor")
        (m / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (m / "predictions" / "_experiments" / "x.json").write_text("{}")
        commit(m, "push into a repo with no manifest")
        p = sync(m)
        check("MANIFEST: origin/main without ownership.json refuses, and says so",
              p.returncode != 0 and "ownership.json" in p.stdout + p.stderr, p.stdout + p.stderr[-400:])

        # --------------------------------------------------------- PUNDITS --
        pund = seed_remote(td / "pund", L, A, T, manifest="pundits") if (td / "pund").mkdir() is None else None
        q = clone(td, pund, "pund-clone", "contributor")
        (q / "predictions" / "_experiments").mkdir(parents=True, exist_ok=True)
        (q / "predictions" / "_experiments" / "x.json").write_text("{}")
        commit(q, "contributor into pundits")
        p = sync(q)
        check("PATHS: the pundits manifest refuses a contributor even on a predictions path",
              p.returncode != 0 and "owner path" in p.stdout and "predictions/_experiments/x.json" in p.stdout,
              p.stdout + p.stderr[-400:])

        p = sync(c, "--no-fetch")
        check("REF: --no-fetch says it read the local ref without fetching",
              "not fetched" in p.stdout, p.stdout)

        # ------------------------------------------------------------ ATTRS --
        a = clone(td, remote, "attrs", "contributor")
        deep = a / "predictions" / "_experiments" / "run-x" / "results" / "ada" / "s9.jsonl"
        deep.parent.mkdir(parents=True)
        deep.write_text("{}\n")
        (deep.parent / "s9.meta.json").write_text("{}")
        commit(a, "deep records")
        files = [f for f in git(a, "ls-tree", "-r", "--name-only", "HEAD", "--", "predictions").splitlines()
                 if f.endswith(".jsonl") or f.endswith(".meta.json")]
        attrs = subprocess.run(["git", "check-attr", "merge", "--stdin"], cwd=a, input="\n".join(files) + "\n",
                               capture_output=True, text=True).stdout.splitlines()
        binary = [l for l in attrs if l.endswith(": merge: binary")]
        check("ATTRS: every record and meta file, at any depth, is merge=binary",
              len(files) > 0 and len(binary) == len(files) and any("_experiments/run-x/results" in l for l in binary),
              f"{len(binary)} of {len(files)} marked")
        for derived in ("predictions/index.json", "predictions/scores.json", "predictions/scoring.json"):
            out = git(a, "check-attr", "merge", derived)
            check(f"ATTRS: {derived} is merge=binary", out.endswith("merge: binary"), out)

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
