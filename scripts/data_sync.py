#!/usr/bin/env python3
"""Check, and later push, commits to the private data repo's main from any clone.

Plan: docs/plans/shared-data-push-2026-09-27.md. Any clone may push the data
repo's main itself, and this tool is what keeps that from clobbering:

    .venv/bin/python scripts/data_sync.py check              # may HEAD be pushed?
    .venv/bin/python scripts/data_sync.py check --no-fetch   # same, against the local ref

`check` answers one question: may this checkout push the commits it holds that
origin/main does not? It refuses when

  - the checkout has no verbatim.role, or a role that does not push main;
  - a commit touches a path that ownership.json (read from origin/main, never
    from the working tree) does not give this role, including deletes and both
    ends of a rename, or a path the manifest does not list at all;
  - origin/main carries no ownership.json: a missing manifest refuses, it never
    defaults to all-owner or all-shared;
  - a derived file in the commit being pushed is behind its own inputs. That is
    read from the COMMIT, by extracting predictions/ and roster/ with
    `git archive` and listing transcripts with `git ls-tree`, so an untracked or
    unstaged file on disk cannot make a stale commit look fresh.

Roles, from `git config verbatim.role` in the data checkout:
  daemon       the clone that runs the daemons; may change every path
  contributor  any other clone pushing main; may change shared and derived paths
  experiment   pushes its own codex/* branch, never main; refused here
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_clone_workflow as D  # noqa: E402

MANIFEST = "ownership.json"
CLASSES = ("owner", "shared", "derived")
PUSH_ROLES = {"daemon": ("owner", "shared", "derived"), "contributor": ("shared", "derived")}
# The roots predictions/index.json counts; aggregate_predictions.py's defaults.
TRANSCRIPT_ROOTS = ("transcripts_open", "transcripts_web")


class Refusal(Exception):
    pass


def git(data: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(data), *args], capture_output=True, text=True)
    if p.returncode:
        raise Refusal(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def role(data: Path) -> str:
    p = subprocess.run(["git", "-C", str(data), "config", "--local", "--get", "verbatim.role"],
                       capture_output=True, text=True)
    return p.stdout.strip()


# ------------------------------------------------------------------ manifest --

def load_manifest(data: Path, ref: str) -> dict:
    p = subprocess.run(["git", "-C", str(data), "show", f"{ref}:{MANIFEST}"], capture_output=True, text=True)
    if p.returncode:
        raise Refusal(f"{ref} carries no {MANIFEST}, so no path can be classified; refusing rather than "
                      f"defaulting. The production owner commits it first (plan phase P6)")
    manifest = json.loads(p.stdout)
    for r in manifest.get("rules") or []:
        if r.get("class") not in CLASSES or not r.get("glob"):
            raise Refusal(f"{MANIFEST} rule {r} needs a glob and a class in {CLASSES}")
    if not manifest.get("rules"):
        raise Refusal(f"{MANIFEST} has no rules")
    return manifest


def glob_match(pattern: str, path: str) -> bool:
    """Segment-wise match where ** spans zero or more directories."""
    pat, parts = pattern.split("/"), path.split("/")

    def rec(i: int, j: int) -> bool:
        if i == len(pat):
            return j == len(parts)
        if pat[i] == "**":
            return any(rec(i + 1, k) for k in range(j, len(parts) + 1))
        return j < len(parts) and fnmatch.fnmatchcase(parts[j], pat[i]) and rec(i + 1, j + 1)
    return rec(0, 0)


def classify(manifest: dict, path: str) -> dict | None:
    return next((r for r in manifest["rules"] if glob_match(r["glob"], path)), None)


# ------------------------------------------------------------------- changes --

def changed_paths(data: Path, base: str, head: str) -> list[tuple[str, str]]:
    """(status, path) for every path the commits on head's side change, including
    deletes, mode changes and BOTH ends of a rename (--no-renames splits it)."""
    mb = git(data, "merge-base", base, head).strip()
    raw = git(data, "diff", "--raw", "--no-renames", "-z", mb, head)
    fields = [f for f in raw.split("\0") if f]
    out, i = [], 0
    while i < len(fields):
        meta = fields[i].split()
        out.append((meta[-1], fields[i + 1]))
        i += 2
    return out


def path_violations(manifest: dict, who: str, changes: list[tuple[str, str]]) -> list[str]:
    allowed = PUSH_ROLES[who]
    bad = []
    for status, path in changes:
        rule = classify(manifest, path)
        if rule is None:
            bad.append(f"{path} ({status}): unlisted in {MANIFEST}, so nobody may push it")
        elif rule["class"] not in allowed:
            bad.append(f"{path} ({status}): {rule['class']} path; role {who} may change only {list(allowed)}")
    return bad


# ----------------------------------------------------------------- freshness --

def tree_listing(data: Path, rev: str) -> set[tuple[str, str]]:
    names = git(data, "ls-tree", "-r", "--name-only", rev, "--", *TRANSCRIPT_ROOTS).splitlines()
    out = set()
    for n in names:
        parts = n.split("/")
        if len(parts) == 3 and parts[2].endswith(".json"):
            out.add((parts[1], parts[2][: -len(".json")]))
    return out


def extract(data: Path, rev: str, dest: Path, paths: list[str]) -> None:
    present = [p for p in paths if git(data, "ls-tree", "--name-only", rev, "--", p).strip()]
    if not present:
        return
    with tempfile.TemporaryFile() as fh:
        p = subprocess.run(["git", "-C", str(data), "archive", "--format=tar", rev, *present], stdout=fh)
        if p.returncode:
            raise Refusal(f"git archive {rev} failed")
        fh.seek(0)
        with tarfile.open(fileobj=fh) as tar:
            tar.extractall(dest, filter="data")


def derived_problems(data: Path, rev: str) -> list[str]:
    """What is stale in the COMMIT rev, read from the commit and never from disk."""
    with tempfile.TemporaryDirectory(prefix="data-sync-") as t:
        tree = Path(t)
        extract(data, rev, tree, ["predictions", "roster"])
        idx_path = tree / "predictions" / "index.json"
        problems = []
        if not (tree / "predictions").exists():
            return problems
        if not idx_path.exists():
            return [f"predictions/ exists at {rev[:12]} but predictions/index.json does not"]
        why = D.index_staleness(json.loads(idx_path.read_text()), tree / "predictions",
                                tree / "roster" / "final.json", None, listing=tree_listing(data, rev))
        if why:
            problems.append(f"predictions/index.json is stale in the commit: {why}")
        scores, config = tree / "predictions" / "scores.json", tree / "predictions" / "scoring.json"
        if scores.exists():
            if not config.exists():
                problems.append("predictions/scores.json is committed without predictions/scoring.json, so its "
                                "inputs cannot be checked")
            else:
                why = D.scores_staleness(scores, config)
                if why:
                    problems.append(f"predictions/scores.json is stale in the commit: {why}")
        return problems


# --------------------------------------------------------------------- check --

def check(data: Path, fetch: bool = True) -> tuple[int, list[str]]:
    lines: list[str] = []
    who = role(data)
    if who not in PUSH_ROLES:
        return 1, [f"REFUSING: verbatim.role is {who or 'unset'} in {data}; only {sorted(PUSH_ROLES)} push "
                   f"main (an experiment clone pushes its own codex/* branch)"]
    if fetch:
        git(data, "fetch", "-q", "origin")
    base = git(data, "rev-parse", "origin/main").strip()
    head = git(data, "rev-parse", "HEAD").strip()
    lines.append(f"origin/main {base[:12]} ({'fetched' if fetch else 'local ref, not fetched'}); "
                 f"HEAD {head[:12]}; role {who}")
    manifest = load_manifest(data, base)
    ahead = int(git(data, "rev-list", "--count", f"{base}..{head}").strip())
    if ahead == 0:
        lines.append("nothing to push: HEAD holds no commit origin/main lacks")
        return 0, lines
    changes = changed_paths(data, base, head)
    lines.append(f"{ahead} commit(s) to push, {len(changes)} path change(s)")
    bad = path_violations(manifest, who, changes)
    bad += derived_problems(data, head)
    if bad:
        lines += [f"REFUSED {b}" for b in bad]
        lines.append(f"REFUSING: {len(bad)} problem(s); nothing was pushed")
        return 1, lines
    lines.append("OK: every path is this role's to change and every derived file is fresh")
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="may this checkout push HEAD to origin/main?")
    c.add_argument("--data", type=Path, default=Path("data"))
    c.add_argument("--no-fetch", action="store_true", help="read the local origin/main ref and say so")
    args = ap.parse_args(argv)
    try:
        code, lines = check(args.data, fetch=not args.no_fetch)
    except Refusal as exc:
        code, lines = 1, [f"REFUSING: {exc}"]
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
