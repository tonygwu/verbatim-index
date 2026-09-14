#!/usr/bin/env python3
"""Study profiles: which data checkout, site and production key belong to a study.

Two studies share this engine. `leaders` is Verbatim Index, the original one.
`pundits` is Verbatim Pundits. A study must never read, prune, overwrite or
publish another study's data, and the guard for that lives here so every script
applies the same rule.

THE RULE.
  - A study's data is reached through a link in the public clone: `data` for
    leaders, `data-<study>` for every other study. The shell loops derive the
    link from the same rule (scripts/study_env.sh), and `load()` refuses a
    profile that disagrees with it, so the two sides cannot drift.
  - A checkout names its study in a committed `.study` file. The leaders
    checkouts predate the file, so a tree WITHOUT one is leaders, and only
    leaders. Every other study requires its marker, and also requires its
    checkout's origin to be the study's own private repository.
  - `check_path()` walks up from any path to the nearest directory holding a
    `.study` or `.git`, and applies the rule there. So a path that does not
    exist yet, such as an output directory, is judged by the checkout it would
    be written into.

WHY A GUARD PER PATH, NOT A GUARD PER RUN. The leaders loops pass every path
explicitly, and one wrong argument is enough to prune another corpus: a
`--grades` pointing at the other study's tree orphans its grades in one pass.
Checking the run's configuration would not see that. Checking each path does.

The study defaults to the STUDY environment variable, else `leaders`. That
default is what keeps every existing leaders command line working unchanged.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "profiles"
LEGACY_STUDY = "leaders"
REQUIRED = ("study_id", "data_link", "site_dir", "publication_site",
            "production_data_key", "data_remote_name", "study_marker_required")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def load(study: str) -> dict:
    """The profile for `study`, validated. Raises RuntimeError, never guesses."""
    if not isinstance(study, str) or not _NAME.fullmatch(study):
        raise RuntimeError(f"a study name is lowercase letters, digits and '-', got {study!r}")
    path = PROFILES / f"{study}.json"
    if not path.is_file():
        raise RuntimeError(f"unknown study {study!r}: there is no profiles/{study}.json")
    prof = json.loads(path.read_text())
    missing = [k for k in REQUIRED if k not in prof]
    if missing:
        raise RuntimeError(f"profiles/{study}.json is missing {missing}")
    if prof["study_id"] != study:
        raise RuntimeError(f"profiles/{study}.json declares study_id {prof['study_id']!r}")
    legacy = study == LEGACY_STUDY
    for key, want in (("data_link", "data" if legacy else f"data-{study}"),
                      ("site_dir", "site" if legacy else f"site-{study}")):
        if prof[key] != want:
            raise RuntimeError(f"profiles/{study}.json has {key} {prof[key]!r}, but the shell loops "
                               f"derive {want!r} for this study; the two must agree")
    if not legacy and not prof["study_marker_required"]:
        raise RuntimeError(f"profiles/{study}.json must require its .study marker; only the "
                           f"legacy study may omit it")
    if not legacy and prof["data_remote_name"] != f"verbatim-{study}-data":
        raise RuntimeError(f"profiles/{study}.json names data remote {prof['data_remote_name']!r}, but "
                           f"scripts/daemon_guard.sh requires 'verbatim-{study}-data'; the two must agree")
    return prof


def default_study() -> str:
    return os.environ.get("STUDY") or LEGACY_STUDY


def add_study_arg(ap) -> None:
    ap.add_argument("--study", default=default_study(),
                    help="Which study's data this run belongs to (profiles/<study>.json). "
                         "Defaults to $STUDY, else leaders. Every path is checked against it.")


def data_link(study: str) -> str:
    return load(study)["data_link"]


def checkout_root(path: Path) -> Path | None:
    """The nearest directory at or above `path` holding a `.study` or a `.git`."""
    p = Path(os.path.abspath(path)).resolve()
    for cand in (p, *p.parents):
        if (cand / ".study").is_file() or (cand / ".git").exists():
            return cand
    return None


def origin_name(root: Path | None) -> str | None:
    """The repository name of a checkout's origin, without host, owner or .git."""
    if root is None:
        return None
    p = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                       capture_output=True, text=True)
    url = p.stdout.strip().rstrip("/")
    if p.returncode or not url:
        return None
    name = re.split(r"[/:]", url)[-1]
    return name[:-4] if name.endswith(".git") else name


def check_path(path, study: str) -> None:
    """Raise RuntimeError if `path` belongs to a study other than `study`."""
    prof = load(study)
    root = checkout_root(Path(path))
    marker = root / ".study" if root is not None else None
    found = marker.read_text().strip() if marker is not None and marker.is_file() else None
    if found is not None and found != study:
        raise RuntimeError(f"{path} is inside {root}, whose .study names {found!r}; "
                           f"this run is the {study!r} study")
    if found is None and prof["study_marker_required"]:
        raise RuntimeError(f"{path} is not inside a checkout whose .study names {study!r} "
                           f"(nearest checkout: {root})")
    if prof["data_remote_name"]:
        name = origin_name(root)
        if name != prof["data_remote_name"]:
            raise RuntimeError(f"{root} has origin {name!r}; the {study!r} study requires "
                               f"{prof['data_remote_name']!r}")


def guard(study: str, *paths) -> None:
    """Exit naming the first path that is not this study's. None entries are skipped."""
    try:
        load(study)
        for p in paths:
            if p is not None:
                check_path(p, study)
    except RuntimeError as exc:
        raise SystemExit(f"REFUSING: {exc}") from None
