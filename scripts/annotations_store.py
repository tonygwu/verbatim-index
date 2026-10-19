#!/usr/bin/env python3
"""An annotation session on disk, and the store its human answers live in.

A SESSION is one directory in a data checkout. It holds the page, one transcript
sidecar per recording (in `<page stem>.transcripts/`), the private quote key, the
answers file and `manifest.json`. The manifest says what the session is:

  schema_version  2
  tool            "annotations"
  name            how `serve` lists and addresses the session
  projects        the projects its recordings belong to (`annotations_select.PROJECTS`)
  modes           which panels the page shows (`annotations_select.MODES`)
  blind           true when no sidecar carries a model suggestion
  transcript_dir  the data directory every transcript was read from
  files           page, answers, quote_key, and optional exports to compare against
  recordings      per recording key: its projects, transcript hash and token count
  legacy_from     only on a session `migrate` adopted: what it was before

The STORE is where answers are read and written. Only `FileStore` exists: the
answers file in the session, which git then carries to the private data repo. The
server talks to the `Store` interface, so a remote store could replace the file
without touching the page. The answers file keeps the shape it has always had,
`{"labels", "attribution", "spans", "corrections"}`.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable, Protocol

from annotations_page import page_data
from annotations_select import MODES, PROJECTS
from annotations_spans import sidecar_path
from atomicio import write_atomic

SCHEMA_VERSION = 2
MANIFEST = "manifest.json"
SECTIONS = ("labels", "attribution", "spans", "corrections")
#: The answers section each mode writes. `attribution` belongs to no mode: the
#: server derives it from `spans` and never accepts it from the page.
MODE_SECTION = {"checklist": "labels", "speakers": "spans", "captions": "corrections"}
REQUIRED = ("schema_version", "tool", "name", "projects", "modes", "blind", "transcript_dir", "files", "recordings")
REQUIRED_FILES = ("page", "answers", "quote_key")


def load_answers(path: Path) -> dict:
    """The answers in `path`, every section present. A malformed file stops the caller."""
    if not path.exists():
        return {s: {} for s in SECTIONS}
    raw = json.loads(path.read_text())
    if (not isinstance(raw, dict) or not {"labels", "attribution"} <= set(raw) or set(raw) - set(SECTIONS)
            or not all(isinstance(v, dict) for v in raw.values())):
        raise SystemExit(f"REFUSING: {path} is not an answers file ({{'labels': ..., 'attribution': ...}})")
    return {s: raw.get(s, {}) for s in SECTIONS}


def dump_answers(answers: dict) -> str:
    """The answers file's bytes. Every writer uses this, so the format cannot drift."""
    return json.dumps(answers, indent=1, ensure_ascii=False) + "\n"


class Store(Protocol):
    where: str

    def load(self) -> dict:
        """A copy of every answer, by section."""

    def update(self, change: Callable[[dict], dict]) -> dict:
        """Apply `change` to the current answers and persist the result atomically.

        `change` receives the current answers and returns the new ones. If it raises,
        nothing is written and the error reaches the caller. Returns what was stored.
        """


class FileStore:
    """The session's answers file, written whole and atomically under one lock."""

    def __init__(self, path: Path):
        self.path = path
        self.where = str(path)
        self._lock = threading.Lock()
        self._answers = load_answers(path)

    def load(self) -> dict:
        with self._lock:
            return {s: dict(self._answers[s]) for s in SECTIONS}

    def update(self, change: Callable[[dict], dict]) -> dict:
        with self._lock:
            updated = change({s: dict(self._answers[s]) for s in SECTIONS})
            if set(updated) != set(SECTIONS):
                raise ValueError(f"an update must keep exactly the sections {SECTIONS}")
            write_atomic(self.path, dump_answers(updated))
            self._answers = updated
            return {s: dict(updated[s]) for s in SECTIONS}


class Session:
    """A session directory and its manifest. Opening one checks the manifest whole."""

    def __init__(self, root: Path, manifest: dict):
        self.root = root
        self.manifest = manifest

    @classmethod
    def open(cls, root) -> "Session":
        root = Path(root)
        path = root / MANIFEST
        if not path.exists():
            raise SystemExit(f"REFUSING: {root} has no {MANIFEST}; build it with `annotations.py build`, "
                             "or adopt an older page with `annotations.py migrate`")
        manifest = json.loads(path.read_text())
        problems = manifest_errors(manifest)
        if problems:
            raise SystemExit(f"REFUSING: {path}: " + "; ".join(problems))
        return cls(root, manifest)

    @property
    def name(self) -> str:
        return self.manifest["name"]

    @property
    def projects(self) -> list[str]:
        return self.manifest["projects"]

    @property
    def modes(self) -> list[str]:
        return self.manifest["modes"]

    def file(self, role: str) -> Path | None:
        name = self.manifest["files"].get(role)
        return self.root / name if name else None

    @property
    def page(self) -> Path:
        return self.file("page")

    @property
    def answers(self) -> Path:
        return self.file("answers")

    def sidecar(self, key: str) -> Path:
        return sidecar_path(self.page, key)

    def data(self) -> dict:
        return page_data(self.page.read_text())

    def sections(self) -> set[str]:
        """The answers sections the page may write, from the session's modes."""
        return {MODE_SECTION[m] for m in self.modes}


def manifest_errors(manifest: dict) -> list[str]:
    """Everything wrong with a version-2 manifest; empty when it is sound."""
    if not isinstance(manifest, dict):
        return ["the manifest is not an object"]
    if manifest.get("schema_version") == 1:
        return ["this is a version-1 speaker-check manifest; adopt the session with `annotations.py migrate`"]
    errs = [f"missing `{k}`" for k in REQUIRED if k not in manifest]
    if errs:
        return errs
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["tool"] != "annotations":
        errs.append(f"schema_version {manifest['schema_version']!r} / tool {manifest['tool']!r} is not "
                    f"{SCHEMA_VERSION} / 'annotations'")
    if not manifest["projects"] or set(manifest["projects"]) - set(PROJECTS):
        errs.append(f"projects {manifest['projects']} must be a non-empty subset of {sorted(PROJECTS)}")
    if not manifest["modes"] or set(manifest["modes"]) - set(MODES):
        errs.append(f"modes {manifest['modes']} must be a non-empty subset of {list(MODES)}")
    errs += [f"files has no `{k}`" for k in REQUIRED_FILES if not manifest["files"].get(k)]
    for key, rec in manifest["recordings"].items():
        if set(rec.get("projects") or []) - set(manifest["projects"]) or not rec.get("projects"):
            errs.append(f"recording {key} has projects {rec.get('projects')} outside the session's")
            break
    return errs


def write_manifest(root: Path, manifest: dict) -> None:
    problems = manifest_errors(manifest)
    if problems:
        raise SystemExit("REFUSING to write a manifest: " + "; ".join(problems))
    write_atomic(root / MANIFEST, json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
