#!/usr/bin/env python3
"""Check, and later push, commits to the private data repo's main from any clone.

Plan: docs/plans/shared-data-push-2026-09-27.md. Any clone may push the data
repo's main itself, and this tool is what keeps that from clobbering:

    .venv/bin/python scripts/data_sync.py check              # may HEAD be pushed?
    .venv/bin/python scripts/data_sync.py check --no-fetch   # same, against the local ref
    .venv/bin/python scripts/data_sync.py push               # merge, regenerate, check, push
    .venv/bin/python scripts/data_sync.py push --daemon      # the same, from the daemon clone
    .venv/bin/python scripts/data_sync.py pull               # take origin/main, never rebasing
    .venv/bin/python scripts/data_sync.py adopt-main [--apply]  # move an experiment clone onto main
    .venv/bin/python scripts/data_sync.py bootstrap [--study pundits]  # daemon: add the manifest, once

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

`push` (a contributor, on main, with no uncommitted tracked change) loops up to
three times: fetch; refuse if a record file changed on both sides since the
merge-base (git would merge its lines into records no run produced); MERGE
origin/main, never rebase, so every SHA a run manifest pinned stays reachable;
resolve a conflict only in a derived file, by regenerating it; regenerate the
derived files from the merged commit and commit any change; validate every
record the merge would add or change, refusing only on failures that are new;
run `check`; push. Git's push is compare-and-swap on the ref, so a push that
lost a race is rejected and the loop starts again. Any refusal restores HEAD to
where it was before the command ran, and the report counts attempts.

`push --daemon` is the same loop for the daemon clone, whose loops write
uncommitted files into its working tree. Those may stay dirty: a merge never
touches a path the incoming commits do not change, and other clones never push
daemon paths. Nothing may be STAGED, because git merge aborts on a staged
change, and the derived predictions files may not be dirty, because the tool
rewrites them. When the push carries grades or results.json, results.json's
grade_files_read must equal the grade files in the commit, so a results.json
from one cycle is never committed beside the grades of the next.

`pull` takes origin/main into any push-role checkout: a fast-forward, or a merge
commit when the checkout holds commits of its own. It never rebases and never
stashes, and when an incoming file would overwrite a dirty or untracked one it
refuses and names the path, leaving HEAD and every file as they were.

`adopt-main` moves a clone's `data` link from its experiment checkout on a
codex/* branch to a fresh checkout of origin/main at .data-clones/main, with
verbatim.role=contributor and the pre-push hook installed. It carries whole
predictions/_experiments/<run> directories that main lacks, committed or
untracked, and REPORTS every other path the old branch changed as skipped with
its reason, so nothing is dropped silently. The old checkout is left intact.
Without --apply it only prints the plan.

`bootstrap` is the one push no manifest can check, because it is the push that
adds the manifest. So it does exactly one thing: from the daemon clone, with
nothing uncommitted and nothing unpushed, it adds this repository's template
(data-repo-templates/<study>/) to a data repo that has no ownership.json, byte
for byte, commits only those files and pushes. Everything else refuses.

Roles, from `git config verbatim.role` in the data checkout:
  daemon       the clone that runs the daemons; may change every path
  contributor  any other clone pushing main; may change shared and derived paths
  experiment   pushes its own codex/* branch, never main; refused here
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import shutil
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
REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
INDEX, SCORES, SCORING = "predictions/index.json", "predictions/scores.json", "predictions/scoring.json"
DERIVED = (INDEX, SCORES)
ATTEMPTS = 3


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
            elif replacements_problem(tree, json.loads(config.read_text())):
                problems.append(replacements_problem(tree, json.loads(config.read_text())))
            else:
                why = D.scores_staleness(scores, config)
                if why:
                    problems.append(f"predictions/scores.json is stale in the commit: {why}")
        return problems


# ---------------------------------------------------------------- regenerate --

def placeholder_listing(data: Path, rev: str, dest: Path) -> None:
    """An empty file per transcript the commit lists, so aggregate_predictions
    counts the same listing without the transcripts being extracted."""
    for slug, stem in tree_listing(data, rev):
        (dest / slug).mkdir(parents=True, exist_ok=True)
        (dest / slug / f"{stem}.json").write_text("")


def run_script(*argv: str) -> None:
    p = subprocess.run([PY, str(REPO / "scripts" / argv[0]), *argv[1:]], capture_output=True, text=True, cwd=REPO)
    if p.returncode:
        raise Refusal(f"{argv[0]} failed while regenerating derived files: "
                      f"{(p.stderr.strip() or p.stdout.strip()).splitlines()[-1]}")


def override_transcripts(tree: Path, cfg: dict) -> list[str]:
    """The transcript paths, under every transcript root, of each entry in the
    override file the scoring config names. The file must be in the extracted tree."""
    rel = cfg.get("date_overrides")
    if not rel:
        return []
    if not (tree / rel).is_file():
        raise Refusal(f"{SCORING} names date_overrides {rel!r}, which is not in the commit under predictions/ "
                      f"or roster/, the only paths the scores are regenerated from")
    tids = json.loads((tree / rel).read_text()).get("overrides") or {}
    return [f"{root}/{tid}.json" for tid in sorted(tids) for root in TRANSCRIPT_ROOTS]


def replacements_problem(tree: Path, cfg: dict) -> str | None:
    """Why the replacement manifest the scoring config names cannot be read from
    the extracted tree, or None. Like override_transcripts' check: the scores are
    regenerated from predictions/ and roster/ only, so the manifest must lie under
    predictions/ and be in the commit. Named here rather than left to fail as a
    raw FileNotFoundError inside the scorer's input hash."""
    rel = cfg.get("replacements")
    if rel is None:
        return None
    why = D.replacements_path_problem(rel) if isinstance(rel, str) and rel else None
    if why:
        return f"{SCORING} names {why}"
    if not (tree / rel).is_file():
        return (f"{SCORING} names replacements {rel!r}, which is not in the commit under predictions/, the only "
                f"path the scores are regenerated from")
    return None


def regenerate(data: Path, rev: str) -> dict[str, bytes]:
    """The derived files as the commit rev's own inputs make them, computed in a
    scratch tree extracted from the commit, never from the working tree."""
    with tempfile.TemporaryDirectory(prefix="data-sync-regen-") as t:
        tree = Path(t)
        extract(data, rev, tree, ["predictions", "roster"])
        if not (tree / "predictions").exists():
            return {}
        placeholder_listing(data, rev, tree / "listing")
        (tree / "listing").mkdir(exist_ok=True)
        run_script("aggregate_predictions.py", "--predictions", str(tree / "predictions"),
                   "--roster", str(tree / "roster" / "final.json"), "--transcripts", str(tree / "listing"),
                   "--out", str(tree / INDEX))
        out = {INDEX: (tree / INDEX).read_bytes()}
        if (tree / SCORING).exists():
            cfg = json.loads((tree / SCORING).read_text())
            if cfg.get("out") != SCORES:
                raise Refusal(f"{SCORING} writes {cfg.get('out')!r}; the derived file is {SCORES}")
            why = replacements_problem(tree, cfg)
            if why:
                raise Refusal(why)
            # The scorer checks each statement-date override against its transcript,
            # so the transcripts the override file names must be in the scratch tree.
            extract(data, rev, tree, override_transcripts(tree, cfg))
            run_script("score_predictions.py", "--config", str(tree / SCORING))
            out[SCORES] = (tree / SCORES).read_bytes()
        return out


# ---------------------------------------------------------------- validation --

def validation_failures(data: Path, rev: str) -> set[tuple[str, str, str]]:
    """Every validate_predictions failure in the commit rev, as (file, invariant,
    detail) with scratch paths removed, so two commits' sets can be compared.
    The transcript roots are merged, because a record's transcript may live in
    either and validate_predictions reads one root."""
    import predictions_lib as L
    import validate_predictions as V
    with tempfile.TemporaryDirectory(prefix="data-sync-val-") as t:
        tree = Path(t)
        extract(data, rev, tree, ["predictions", *TRANSCRIPT_ROOTS])
        merged = tree / "merged-transcripts"
        merged.mkdir()
        for root in TRANSCRIPT_ROOTS:
            for f in sorted((tree / root).glob("*/*.json")) if (tree / root).exists() else []:
                (merged / f.parent.name).mkdir(exist_ok=True)
                shutil.move(str(f), merged / f.parent.name / f.name)
        pred = tree / "predictions"
        if not pred.exists():
            return set()
        failures, _ = V.validate_tree(pred, merged, L.load_exclusions(str(REPO / "scripts" / "predictions_exclusions.json")),
                                      L.load_record_schema(L.SKILL), V.known_contract_ids(pred))
        strip = lambda text: str(text).replace(str(pred) + "/", "predictions/").replace(str(tree) + "/", "")  # noqa: E731
        return {(strip(f["file"]), f["invariant"], strip(f["detail"])) for f in failures}


def new_validation_failures(data: Path, base: str, head: str) -> list[str]:
    before, after = validation_failures(data, base), validation_failures(data, head)
    return [f"{f}: {inv}: {detail}" for f, inv, detail in sorted(after - before)]


# ---------------------------------------------------------------------- push --

def is_record(path: str) -> bool:
    return path.startswith("predictions/") and (path.endswith(".jsonl") or path.endswith(".meta.json"))


def changed_set(data: Path, a: str, b: str) -> set[str]:
    return {path for _, path in changed_paths(data, a, b)}


def tracked_dirty(data: Path) -> bool:
    return bool(git(data, "status", "--porcelain", "--untracked-files=no").strip())


def restore(data: Path, sha: str) -> None:
    """Undo only the commits this command made; --keep refuses to touch local edits."""
    if git(data, "rev-parse", "HEAD").strip() != sha:
        subprocess.run(["git", "-C", str(data), "merge", "--abort"], capture_output=True)
        git(data, "reset", "-q", "--keep", sha)


def merge_origin(data: Path, base: str, lines: list[str]) -> None:
    head = git(data, "rev-parse", "HEAD").strip()
    if subprocess.run(["git", "-C", str(data), "merge-base", "--is-ancestor", base, head]).returncode == 0:
        return
    mb = git(data, "merge-base", base, head).strip()
    both = changed_set(data, mb, head) & changed_set(data, mb, base)
    records = sorted(p for p in both if is_record(p))
    if records:
        raise Refusal("a record file changed on both sides since the merge-base, and a line-level merge would "
                      "produce records no run wrote: " + ", ".join(records) + ". Pull origin/main, redo your "
                      "change on top of it, then push")
    p = subprocess.run(["git", "-C", str(data), "merge", "--no-edit", "-m", f"Merge origin/main {base[:12]}", base],
                       capture_output=True, text=True)
    if p.returncode:
        conflicted = git(data, "diff", "--name-only", "--diff-filter=U").split()
        if not conflicted or any(c not in DERIVED for c in conflicted):
            raise Refusal(f"merging origin/main {base[:12]} conflicts outside the derived files: "
                          + ", ".join(c for c in conflicted if c not in DERIVED) or p.stderr.strip())
        git(data, "checkout", "--ours", "--", *conflicted)  # either side; both are regenerated next
        git(data, "add", "--", *conflicted)
        git(data, "commit", "-q", "--no-edit")
        lines.append(f"  merged origin/main {base[:12]}; derived conflict in {', '.join(conflicted)} "
                     f"resolved by regenerating")
    else:
        lines.append(f"  merged origin/main {base[:12]}")


def regenerate_and_commit(data: Path, lines: list[str]) -> None:
    fresh = regenerate(data, "HEAD")
    changed = [rel for rel, blob in fresh.items()
               if not (data / rel).exists() or (data / rel).read_bytes() != blob]
    if not changed:
        lines.append("  derived files already fresh")
        return
    for rel in changed:
        (data / rel).write_bytes(fresh[rel])
    git(data, "add", "--", *changed)
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git(data, "commit", "-q", "-m", f"Regenerate derived files ({when})",
        "-m", "Written by scripts/data_sync.py push: " + ", ".join(changed))
    lines.append(f"  regenerated {', '.join(changed)}")


def test_hook(attempt: int) -> None:
    """TEST SEAM ONLY: run a command between the fetch and the push, so the race
    that git's compare-and-swap resolves can be reproduced. Unset in real use."""
    cmd = os.environ.get("DATA_SYNC_TEST_BEFORE_PUSH")
    if cmd and attempt <= int(os.environ.get("DATA_SYNC_TEST_BEFORE_PUSH_TIMES", "0")):
        subprocess.run([cmd], env={**os.environ, "DATA_SYNC_ATTEMPT": str(attempt)}, check=True,
                       capture_output=True)


def staged(data: Path) -> bool:
    return subprocess.run(["git", "-C", str(data), "diff", "--cached", "--quiet"]).returncode != 0


def precondition(data: Path, want: str) -> str | None:
    who = role(data)
    if who != want:
        return f"this mode is for verbatim.role={want}; this checkout is {who or 'unset'}"
    branch = git(data, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch != "main":
        return f"on branch {branch}; pushes to origin/main go from main"
    if staged(data):
        return "staged but uncommitted changes; commit or unstage them (git merge would abort on them)"
    if want == "contributor" and tracked_dirty(data):
        return "uncommitted changes to tracked files; commit or discard them first"
    dirty_derived = [f for f in DERIVED if f in git(data, "status", "--porcelain", "--", f)]
    if dirty_derived:
        return f"{', '.join(dirty_derived)} modified in the working tree; the tool regenerates it, so discard it"
    return None


def push(data: Path, attempts: int = ATTEMPTS, daemon: bool = False) -> tuple[int, list[str]]:
    lines: list[str] = []
    why = precondition(data, "daemon" if daemon else "contributor")
    if why:
        return 1, [f"REFUSING: {why}"]
    start = git(data, "rev-parse", "HEAD").strip()
    taxonomy: dict[str, int] = {}
    for attempt in range(1, attempts + 1):
        lines.append(f"attempt {attempt}")
        try:
            git(data, "fetch", "-q", "origin")
            base = git(data, "rev-parse", "origin/main").strip()
            merge_origin(data, base, lines)
            regenerate_and_commit(data, lines)
            new = new_validation_failures(data, base, "HEAD")
            if new:
                raise Refusal(f"{len(new)} new validation failure(s): " + "; ".join(new[:10]))
            code, report = check(data, fetch=False)
            lines += [f"  {r}" for r in report]
            if code:
                raise Refusal("check refused the merged commit")
            test_hook(attempt)
            p = subprocess.run(["git", "-C", str(data), "push", "origin", "HEAD:main"], capture_output=True, text=True)
        except Refusal as exc:
            restore(data, start)
            lines.append(f"REFUSING: {exc}")
            lines.append(f"HEAD restored to {start[:12]}; nothing was pushed")
            return 1, lines
        if p.returncode == 0:
            lines.append(f"  pushed {git(data, 'rev-parse', 'HEAD').strip()[:12]} to origin/main")
            lines.append(f"attempted {attempt}, succeeded 1, failed {attempt - 1}"
                         + (f" {json.dumps(taxonomy, sort_keys=True)}" if taxonomy else ""))
            return 0, lines
        kind = "non_fast_forward" if ("fetch first" in p.stderr or "non-fast-forward" in p.stderr) else "push_error"
        taxonomy[kind] = taxonomy.get(kind, 0) + 1
        lines.append(f"  push rejected: {kind}")
        if kind != "non_fast_forward":
            restore(data, start)
            lines.append(f"REFUSING: {p.stderr.strip()}")
            return 1, lines
    restore(data, start)
    lines.append(f"attempted {attempts}, succeeded 0, failed {attempts} {json.dumps(taxonomy, sort_keys=True)}")
    lines.append(f"REFUSING: origin/main kept moving; HEAD restored to {start[:12]}; try again")
    return 1, lines


# ------------------------------------------------------------------- results --

# The deploys skip these when they count grade files, and the gate counts the same
# way: deploy.sh skips _raw and _obsolete, and deploy_pundits.sh also skips
# _provenance, which the pundits contract writes. Leaders has no _provenance, so
# one set serves both.
GRADE_SKIP = {"_raw", "_obsolete", "_provenance"}


def results_problems(data: Path, rev: str) -> list[str]:
    """results.json in the commit must describe exactly the grades in the commit."""
    p = subprocess.run(["git", "-C", str(data), "show", f"{rev}:results.json"], capture_output=True, text=True)
    if p.returncode:
        return []
    names = git(data, "ls-tree", "-r", "--name-only", rev, "--", "grades").splitlines()
    n = sum(1 for f in names if f.endswith(".json") and not GRADE_SKIP & set(f.split("/")))
    read = (json.loads(p.stdout).get("diagnostics") or {}).get("grade_files_read")
    if read is None:
        return ["results.json lacks diagnostics.grade_files_read, so it cannot be matched to the grades"]
    if read != n:
        return [f"results.json says grade_files_read {read} but the commit holds {n} grade files; commit "
                f"results.json from the same aggregate cycle as the grades"]
    return []


# ---------------------------------------------------------------------- pull --

def overwritten_paths(stderr: str) -> list[str]:
    """git lists the files a merge would overwrite on tab-indented lines."""
    return [l.strip() for l in stderr.splitlines() if l.startswith("\t")]


def pull(data: Path) -> tuple[int, list[str]]:
    who = role(data)
    if who not in PUSH_ROLES:
        return 1, [f"REFUSING: verbatim.role is {who or 'unset'}; pull is for {sorted(PUSH_ROLES)}"]
    if staged(data):
        return 1, ["REFUSING: staged but uncommitted changes; commit or unstage them (git merge would abort on them)"]
    git(data, "fetch", "-q", "origin")
    base = git(data, "rev-parse", "origin/main").strip()
    head = git(data, "rev-parse", "HEAD").strip()
    ancestor = lambda a, b: subprocess.run(["git", "-C", str(data), "merge-base", "--is-ancestor", a, b]).returncode == 0  # noqa: E731
    if ancestor(base, head):
        return 0, [f"up to date: HEAD {head[:12]} already contains origin/main {base[:12]}"]
    args = ["merge", "--ff-only", base] if ancestor(head, base) else \
        ["merge", "--no-edit", "-m", f"Merge origin/main {base[:12]}", base]
    p = subprocess.run(["git", "-C", str(data), *args], capture_output=True, text=True)
    if p.returncode:
        subprocess.run(["git", "-C", str(data), "merge", "--abort"], capture_output=True)
        if git(data, "rev-parse", "HEAD").strip() != head:
            git(data, "reset", "-q", "--keep", head)
        paths = overwritten_paths(p.stderr)
        return 1, [f"REFUSING: taking origin/main {base[:12]} would overwrite local files: "
                   + (", ".join(paths) if paths else p.stderr.strip()),
                   f"HEAD left at {head[:12]}; move those files aside, then pull again"]
    how = "fast-forwarded" if args[1] == "--ff-only" else "merged"
    return 0, [f"{how} to origin/main {base[:12]}; HEAD {git(data, 'rev-parse', 'HEAD').strip()[:12]}"]


# ---------------------------------------------------------------- adopt-main --

ADOPT_REPORT = "verbatim-adopt-main.json"
HOOKS = REPO / "scripts" / "git-hooks" / "data"


def run_of(path: str) -> str | None:
    parts = path.split("/")
    return "/".join(parts[:3]) if len(parts) >= 4 and parts[:2] == ["predictions", "_experiments"] else None


def uncommitted(data: Path) -> list[tuple[str, str]]:
    raw = git(data, "status", "--porcelain", "-z", "--untracked-files=all")
    return [(e[:2], e[3:]) for e in raw.split("\0") if len(e) > 3]


def adopt_plan(old: Path) -> dict:
    git(old, "fetch", "-q", "origin")
    base = git(old, "rev-parse", "origin/main").strip()
    head = git(old, "rev-parse", "HEAD").strip()
    manifest = load_manifest(old, base)
    seen: dict[str, str] = {}
    for status, path in changed_paths(old, base, head):
        seen[path] = "deleted on the branch" if status == "D" else "committed on the branch"
    for xy, path in uncommitted(old):
        seen[path] = "deleted, uncommitted" if "D" in xy else "uncommitted"
    carry, skipped = set(), []
    for path, where in sorted(seen.items()):
        run = run_of(path)
        if where.startswith("deleted"):
            skipped.append({"path": path, "source": where, "reason": "a deletion; deletions are not carried"})
        elif run is None:
            rule = classify(manifest, path)
            cls = rule["class"] if rule else "unlisted"
            skipped.append({"path": path, "source": where,
                            "reason": f"{cls} path outside an experiment run; only whole "
                                      f"predictions/_experiments/<run> directories are carried"})
        elif git(old, "ls-tree", "--name-only", base, "--", run).strip():
            skipped.append({"path": path, "source": where,
                            "reason": f"{run} already exists on origin/main; reconcile it by hand"})
        else:
            carry.add(run)
    return {"old_checkout": str(old), "old_branch": git(old, "rev-parse", "--abbrev-ref", "HEAD").strip(),
            "old_head": head, "origin_main": base, "carry": sorted(carry), "skipped": skipped}


def adopt_main(repo: Path, apply: bool = False) -> tuple[int, list[str]]:
    repo = repo.resolve()
    link, dest = repo / "data", repo / ".data-clones" / "main"
    if not link.is_symlink():
        return 1, [f"REFUSING: {link} is not a symlink to an experiment checkout"]
    old = link.resolve()
    if old == dest.resolve() and role(old) == "contributor":
        return 0, [f"already adopted: {link} -> {dest}"]
    if role(old) != "experiment":
        return 1, [f"REFUSING: adopt-main moves an experiment checkout; {old} has role {role(old) or 'unset'}"]
    if dest.exists():
        return 1, [f"REFUSING: {dest} exists; preserved, not reset. Inspect it, then move it aside"]
    plan = adopt_plan(old)
    lines = [f"{'APPLY' if apply else 'dry run'}: {link} -> {dest} at origin/main {plan['origin_main'][:12]}",
             f"old checkout {old} on {plan['old_branch']} at {plan['old_head'][:12]} is left intact"]
    lines += [f"  carry {run}" for run in plan["carry"]] or ["  carry nothing"]
    lines += [f"  skipped {s['path']} ({s['source']}): {s['reason']}" for s in plan["skipped"]]
    if not apply:
        lines.append("dry run: nothing changed; rerun with --apply")
        return 0, lines
    D.assert_idle(repo)
    origin = git(old, "remote", "get-url", "origin").strip()
    subprocess.run(["git", "clone", "-q", "--no-local", origin, str(dest)], check=True)
    git(dest, "checkout", "-q", "-B", "main", plan["origin_main"])
    git(dest, "branch", "-q", "--set-upstream-to=origin/main", "main")
    for key, value in (("verbatim.role", "contributor"), ("verbatim.owner", str(repo)),
                       ("user.email", git(old, "config", "user.email").strip()),
                       ("user.name", git(old, "config", "user.name").strip()),
                       ("core.hooksPath", str(HOOKS))):
        git(dest, "config", key, value)
    hashes = D.copy_owned(old, dest, plan["carry"])
    git(dest, "fsck", "--connectivity-only")
    D.write_state(dest / ".git" / ADOPT_REPORT, {**plan, "copied_sha256": hashes})
    D.assert_idle(repo)
    temp = repo / ".data-clones" / f"link-{os.getpid()}"
    temp.symlink_to(dest, target_is_directory=True)
    os.replace(temp, link)
    lines.append(f"adopted: {link} -> {dest}; carried runs are uncommitted there, so review them and "
                 f"push with scripts/data_sync.py push; report in {dest / '.git' / ADOPT_REPORT}")
    return 0, lines


# ----------------------------------------------------------------- bootstrap --

TEMPLATES = REPO / "data-repo-templates"


def bootstrap(data: Path, study: str = "leaders") -> tuple[int, list[str]]:
    tpl = TEMPLATES / study
    files = sorted(f.name for f in tpl.iterdir() if f.is_file()) if tpl.is_dir() else []
    if MANIFEST not in files:
        return 1, [f"REFUSING: no template manifest at {tpl / MANIFEST}"]
    if role(data) != "daemon":
        return 1, [f"REFUSING: bootstrap is for the daemon clone (verbatim.role=daemon); this checkout is "
                   f"{role(data) or 'unset'}"]
    if git(data, "rev-parse", "--abbrev-ref", "HEAD").strip() != "main":
        return 1, ["REFUSING: bootstrap runs on main"]
    git(data, "fetch", "-q", "origin")
    base = git(data, "rev-parse", "origin/main").strip()
    if subprocess.run(["git", "-C", str(data), "cat-file", "-e", f"{base}:{MANIFEST}"],
                      capture_output=True).returncode == 0:
        return 1, [f"REFUSING: origin/main {base[:12]} already carries {MANIFEST}; change it with an owner push"]
    if git(data, "rev-parse", "HEAD").strip() != base:
        return 1, ["REFUSING: HEAD holds unpushed commits or is behind origin/main; bootstrap must push the "
                   "manifest alone, so pull or push those first"]
    if tracked_dirty(data) or staged(data):
        return 1, ["REFUSING: uncommitted tracked changes; bootstrap must commit the manifest alone"]
    for name in files:
        if (data / name).exists():
            return 1, [f"REFUSING: {name} already exists, untracked, in {data}; move it aside"]
    for name in files:
        shutil.copyfile(tpl / name, data / name)
    git(data, "add", "--", *files)
    git(data, "commit", "-q", "-m", f"Add the {study} ownership manifest",
        "-m", f"Copied byte for byte from data-repo-templates/{study}/ by scripts/data_sync.py bootstrap. "
              f"Plan: docs/plans/shared-data-push-2026-09-27.md, phase P6.")
    p = subprocess.run(["git", "-C", str(data), "push", "origin", "HEAD:main"], capture_output=True, text=True)
    if p.returncode:
        git(data, "reset", "-q", "--hard", base)
        return 1, [f"REFUSING: push failed, local commit undone: {p.stderr.strip()}"]
    return 0, [f"bootstrapped {', '.join(files)} onto origin/main {git(data, 'rev-parse', 'HEAD').strip()[:12]}"]


# --------------------------------------------------------------------- check --

def check(data: Path, fetch: bool = True, head_rev: str = "HEAD") -> tuple[int, list[str]]:
    lines: list[str] = []
    who = role(data)
    if who not in PUSH_ROLES:
        return 1, [f"REFUSING: verbatim.role is {who or 'unset'} in {data}; only {sorted(PUSH_ROLES)} push "
                   f"main (an experiment clone pushes its own codex/* branch)"]
    if fetch:
        git(data, "fetch", "-q", "origin")
    base = git(data, "rev-parse", "origin/main").strip()
    head = git(data, "rev-parse", head_rev).strip()
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
    if any(path == "results.json" or path.startswith("grades/") for _, path in changes):
        bad += results_problems(data, head)
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
    c.add_argument("--head", default="HEAD", help="the commit to check; the pre-push hook passes the pushed SHA")
    u = sub.add_parser("push", help="merge origin/main, regenerate, check and push")
    u.add_argument("--data", type=Path, default=Path("data"))
    u.add_argument("--daemon", action="store_true", help="the daemon clone: dirty daemon files may stay")
    g = sub.add_parser("pull", help="take origin/main by fast-forward or merge, never rebase")
    g.add_argument("--data", type=Path, default=Path("data"))
    b = sub.add_parser("bootstrap", help="daemon clone: add the ownership manifest to a repo that has none")
    b.add_argument("--data", type=Path, default=Path("data"))
    b.add_argument("--study", default="leaders", choices=["leaders", "pundits"])
    a = sub.add_parser("adopt-main", help="move this clone's data link onto a fresh checkout of main")
    a.add_argument("--repo", type=Path, default=REPO)
    a.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            code, lines = check(args.data, fetch=not args.no_fetch, head_rev=args.head)
        elif args.cmd == "bootstrap":
            code, lines = bootstrap(args.data, args.study)
        elif args.cmd == "adopt-main":
            code, lines = adopt_main(args.repo, apply=args.apply)
        elif args.cmd == "pull":
            code, lines = pull(args.data)
        else:
            code, lines = push(args.data, daemon=args.daemon)
    except (Refusal, RuntimeError) as exc:  # RuntimeError: data_clone_workflow's guards
        code, lines = 1, [f"REFUSING: {exc}"]
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
