#!/usr/bin/env python3
"""One tool for human transcript annotation, for every project.

A person checks a transcript in one or more MODES: `speakers` (who said which
words; a quote's result follows from them), `captions` (what was actually said)
and `checklist` (questions about the recording, from the project's spec). Each
recording carries the PROJECTS it belongs to: `insights` (the leaderboard),
`predictions` and `pundits`. See `annotations_select` for what differs per project,
and `annotations_store` for the session layout.

  build    make a session from a data checkout
  migrate  adopt a session built before this tool; writes manifest.json, nothing else
  verify   prove a session's answers are intact; a JSON report, exit 1 on any failure
  rebuild  render the page again with the current template; answers are untouched
  export   labels | quotes | spans | corrections, from the answers file
  status   what has been annotated, per project and mode
  serve    serve sessions on 127.0.0.1, all in one interface

  .venv/bin/python scripts/annotations.py build --data data --project insights --project predictions \\
      --keys sam-altman/theo-von-ayn8vk,lisa-su/all-in-podcast-9wkgne \\
      --reasons reasons.json --out data/predictions/_experiments/RUN/annotations
  .venv/bin/python scripts/annotations.py build --data data-pundits --project pundits \\
      --checklist data-pundits/logs/p6b/human_checklist.json --grades \\
      [--drafts data-pundits/logs/p6b/speaker_inference.jsonl] --out data-pundits/logs/p6b
  .venv/bin/python scripts/annotations.py serve --session DIR [--session DIR ...] [--port 5001]
  .venv/bin/python scripts/annotations.py verify --session DIR --expect-answers-sha256 HEX
  .venv/bin/python scripts/annotations.py export quotes --session DIR --out quote_results.json

A session holds transcript text, so it lives in a data checkout, never in this
repository, and is served from this machine only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_profile as SP  # noqa: E402
from annotations_corrections import export_corrections, validate_corrections  # noqa: E402
from annotations_page import (docs_from, join_quotes, load_drafts, draft_view, page_data, page_ids,  # noqa: E402
                              render_page, to_labels)
from annotations_select import (DEFAULT_CAP, LEGACY_STUDY_PROJECT, MODES, PROJECTS,  # noqa: E402
                                QUOTE_CAP_PER_RECORDING, git_revision, insights_quotes, predictions_quotes,
                                project, recording_row, sha256_file, suspect_quotes)
from annotations_spans import (build_transcript, import_spans, reconcile_quote_reviews,  # noqa: E402
                               sidecar_path, validate_annotation)
from annotations_store import (MANIFEST, SCHEMA_VERSION, Session, load_answers, write_manifest)  # noqa: E402
from annotations_text import excerpts, name_forms  # noqa: E402
from atomicio import write_atomic  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FILES = {"page": "annotations.html", "answers": "human_answers.json", "quote_key": "quote_key.json"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def toplevel(path: Path) -> Path | None:
    p = path
    while not p.exists():
        p = p.parent
    r = subprocess.run(["git", "-C", str(p if p.is_dir() else p.parent), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def refuse_public(out: Path) -> None:
    """A session carries transcript text; this public repository must never hold one."""
    if toplevel(out.resolve()) == toplevel(REPO):
        raise SystemExit(f"REFUSING: {out} is inside the public repository; write the session into a data checkout")


def session_block(manifest: dict) -> dict:
    """What the page needs to know about its session, from the manifest."""
    checklists = [PROJECTS[p]["checklist"] for p in manifest["projects"] if PROJECTS[p]["checklist"]]
    if len(checklists) > 1:
        raise SystemExit("REFUSING: more than one project in this session has a checklist")
    return {"name": manifest["name"], "projects": manifest["projects"], "modes": manifest["modes"],
            "checklist": checklists[0] if checklists and "checklist" in manifest["modes"] else None,
            "project_help": {p: PROJECTS[p]["quote_help"] for p in manifest["projects"]}}


def titles(manifest: dict) -> tuple[str, str]:
    return ("Annotations · " + " + ".join(manifest["projects"]),
            f"Modes: {', '.join(manifest['modes'])}. Each answer saves the moment you make it.")


def write_page(session_root: Path, manifest: dict, data: dict) -> str:
    title, subtitle = titles(manifest)
    page = render_page({**data, "session": session_block(manifest)}, title, subtitle)
    write_atomic(session_root / manifest["files"]["page"], page)
    return page


# ---------------------------------------------------------------- build

def grades_for(data: Path, slug: str, sid: str, inputs: dict) -> list[dict]:
    """The valid blinded run-0 grades of one recording, each input hashed."""
    out = []
    for p in sorted(data.glob(f"grades/*/{slug}/{sid}__*__blinded__r0.json")):
        if {"_obsolete", "_raw"} & set(p.parts):
            continue
        g = json.loads(p.read_text())
        if g.get("validation_errors") or not isinstance((g.get("grade") or {}).get("dimensions"), dict):
            continue
        out.append(g)
        inputs[str(p.relative_to(data))] = sha256_file(p)
    return out


def guard_answers(answers_path: Path, rows: list, quote_rows: list, transcript_index: dict,
                  allow_off_page: bool) -> None:
    """Refuse a build that would strand answers already saved in this session.

    A build rewrites the page, the sidecars and the quote key. If the new page no
    longer carries an answered recording or quote, its answers can no longer be
    changed or exported; if a recording's text changed, its saved ranges and
    corrections point at words that are no longer there. Either way the answers file
    itself is untouched, but only git could bring the session back, so the build stops
    before writing anything. `--allow-off-page` accepts the first case on purpose (a
    recording dropped from the checklist); nothing accepts the second.
    """
    if not answers_path.exists():
        return
    answers = load_answers(answers_path)
    ids = page_ids({"rows": rows, "quote_rows": quote_rows, "transcript_index": transcript_index})
    off = {s: sorted(set(answers[s]) - ids[s]) for s in answers if set(answers[s]) - ids[s]}
    moved = sorted(k for s in ("spans", "corrections") for k, v in answers[s].items()
                   if k in transcript_index and (v.get("text_sha256"), v.get("token_count"))
                   != (transcript_index[k]["text_sha256"], transcript_index[k]["token_count"]))
    if moved:
        raise SystemExit(f"REFUSING: the transcript text changed under saved annotations for {moved[:5]}; their word "
                         "offsets would point at other words. Nothing was written.")
    if off and not allow_off_page:
        raise SystemExit("REFUSING: the new page would not carry answers already saved in "
                         f"{answers_path}: {{{', '.join(f'{s}: {v[:3]}' for s, v in off.items())}}}. Build with the "
                         "same projects and flags as before (a pundits session needs --grades to keep its quotes), "
                         "or pass --allow-off-page to keep those answers in the file without a page. Nothing was written.")


def build(args) -> int:
    data, out = Path(args.data), Path(args.out)
    projects = list(dict.fromkeys(args.project))
    for p in projects:
        project(p)
    studies = {PROJECTS[p]["study"] for p in projects}
    if len(studies) != 1:
        raise SystemExit(f"REFUSING: {projects} span studies {sorted(studies)}; a session lives in one data "
                         "repository, so build one session per study and serve them together")
    study = studies.pop()
    tdirs = {PROJECTS[p]["transcript_dir"] for p in projects}
    if len(tdirs) != 1:
        raise SystemExit(f"REFUSING: {projects} read different transcript directories {sorted(tdirs)}")
    tdir = tdirs.pop()
    pundits = "pundits" in projects
    if pundits and args.cap is not None:
        raise SystemExit(f"REFUSING: pundits quotes are capped at {QUOTE_CAP_PER_RECORDING} per recording by their "
                         "selector; --cap applies to insights and predictions")
    cap = DEFAULT_CAP if args.cap is None else args.cap
    if pundits and (args.keys or not args.checklist):
        raise SystemExit("REFUSING: a pundits session takes its recordings from --checklist, not --keys")
    if not pundits and (args.checklist or args.grades or args.drafts or not args.keys):
        raise SystemExit("REFUSING: --keys names the recordings; --checklist, --grades and --drafts are pundits-only")
    SP.guard(study, data, out)
    refuse_public(out)
    roster = {p["slug"]: p for p in json.loads((data / "roster" / "final.json").read_text())["roster"]}
    previous = Session.open(out) if (out / MANIFEST).exists() else None
    files = dict(previous.manifest["files"]) if previous else dict(DEFAULT_FILES)
    name = args.name or (previous.name if previous else out.resolve().name)
    if not NAME.fullmatch(name):
        raise SystemExit(f"REFUSING: session name {name!r} must match {NAME.pattern}")
    inputs, recordings, rows, quote_rows, key_map = {}, {}, [], [], {}

    def transcript(key: str) -> dict:
        slug, sid = key.split("/", 1)
        path = data / tdir / slug / f"{sid}.json"
        inputs[str(path.relative_to(data))] = sha256_file(path)
        return json.loads(path.read_text())

    if pundits:
        checklist_path = Path(args.checklist)
        checklist = json.loads(checklist_path.read_text())
        inputs[checklist_path.name] = sha256_file(checklist_path)
        drafts = load_drafts(Path(args.drafts), checklist) if args.drafts else None
        for key, row in checklist.items():
            slug, sid = key.split("/", 1)
            person, rec = roster[slug], transcript(key)
            text = rec.get("text") or ""
            forms = name_forms(person)
            mentions = sum(len(re.findall(r"\b" + re.escape(f) + r"\b", text, re.I)) for f in forms[:1] + forms[2:])
            rows.append({
                "key": key, "slug": slug, "sid": sid, "person": person["name"], "role": person.get("role", ""),
                "title": row.get("title") or rec.get("yt_title") or "",
                "channel": row.get("channel") or rec.get("yt_channel") or "",
                "upload": row.get("upload") or rec.get("yt_upload_date") or "",
                "url": row.get("url") or rec.get("url"), "video_id": rec.get("video_id"),
                "duration": rec.get("yt_duration_sec") or rec.get("duration_sec"), "words": rec.get("word_count"),
                "hints": [h for h in row.get("hints", []) if not h.startswith("passes automatic checks")],
                "description": (rec.get("yt_description") or "")[:700], "forms": forms, "mentions": mentions,
                "excerpts": excerpts(text), "projects": ["pundits"]})
            if drafts is not None:
                rows[-1]["draft"], rows[-1]["doubt"] = draft_view(drafts.get(key))
        rows.sort(key=lambda r: (r["person"].split()[-1], r["person"], r["upload"]))
        report = {}
        if args.grades:
            quote_rows, key_map, report = suspect_quotes(data / "grades", data / tdir, roster)
            for r in quote_rows:
                r["projects"] = ["pundits"]
                for c in r["quotes"]:
                    c["project"] = "pundits"
        for key in {r["key"] for r in rows + quote_rows}:
            recordings[key] = {"projects": ["pundits"],
                               "quotes": {"pundits": sum(len(r["quotes"]) for r in quote_rows if r["key"] == key)}}
        print(f"quote scan: {report}" if args.grades else "no quote scan (--grades not given)")
    else:
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
        if not keys or len(keys) != len(set(keys)):
            raise SystemExit("REFUSING: --keys must name at least one recording, each once")
        reasons = json.loads(Path(args.reasons).read_text()) if args.reasons else {}
        if set(reasons) - set(keys):
            raise SystemExit(f"REFUSING: --reasons names recordings not in --keys: {sorted(set(reasons) - set(keys))}")
        for key in keys:
            slug, sid = key.split("/", 1)
            if slug not in roster:
                raise SystemExit(f"REFUSING: {slug} is not on the roster")
            rec = transcript(key)
            raw = rec["text"]
            duration = rec.get("yt_duration_sec") or rec.get("duration_sec")
            cards, reports, tags = [], {}, []
            for p in projects:
                if p == "insights":
                    grades = grades_for(data, slug, sid, inputs)
                    if not grades:
                        reports[p] = {"skipped": "no valid blinded grade"}
                        continue
                    got, kmap, rep = insights_quotes(key, raw, grades, name_forms(roster[slug]), cap, duration)
                else:
                    ppath = data / "predictions" / slug / f"{sid}.jsonl"
                    if not ppath.exists():
                        reports[p] = {"skipped": "no predictions file"}
                        continue
                    inputs[str(ppath.relative_to(data))] = sha256_file(ppath)
                    records = [json.loads(line) for line in ppath.read_text().splitlines() if line.strip()]
                    got, kmap, rep = predictions_quotes(key, raw, records, cap, duration)
                reports[p] = rep
                clash = set(kmap) & set(key_map)
                if clash:
                    raise SystemExit(f"REFUSING: quote ids {sorted(clash)[:3]} come from two places")
                if got:
                    tags.append(p)
                    cards += [{**c, "project": p} for c in got]
                    key_map.update(kmap)
            if not cards:
                raise SystemExit(f"REFUSING: {key} yields no quote to check for {projects} ({reports})")
            row = recording_row(key, rec, roster[slug], cards)
            row["projects"] = tags
            quote_rows.append(row)
            recordings[key] = {"projects": tags, "quotes": {p: sum(c["project"] == p for c in cards) for p in tags},
                               "reports": reports, "reason_selected": reasons.get(key)}
    transcript_index, sidecars = {}, {}
    for key in sorted(recordings):
        slug, sid = key.split("/", 1)
        raw = json.loads((data / tdir / slug / f"{sid}.json").read_text()).get("text") or ""
        graded = []
        if pundits and args.grades:
            for path in sorted((data / "grades").glob(f"*/{slug}/{sid}__*__r0.json")):
                if not {"_obsolete", "_raw"} & set(path.parts):
                    graded.append((path, json.loads(path.read_text())))
        # Insights and predictions pass no grades, so the editor shows no model
        # suggestion: a blind review. Pundits with --grades shows them: assisted.
        side = build_transcript(key, raw, graded)
        sidecars[key] = side
        transcript_index[key] = {"text_sha256": side["text_sha256"], "token_count": side["token_count"]}
        recordings[key].update(transcript_dir=tdir, **transcript_index[key],
                               suggestions=len(side["suggestions"]))
    if pundits and args.grades:
        for path in sorted((data / "grades").glob("*/*/*__r0.json")):
            if not {"_obsolete", "_raw"} & set(path.parts):
                inputs[str(path.relative_to(data))] = sha256_file(path)
    if args.drafts:
        inputs[Path(args.drafts).name] = sha256_file(Path(args.drafts))
    default_modes = [m for m in MODES if m != "checklist" or (pundits and rows)]
    modes = [m for m in MODES if m in args.mode] if args.mode else default_modes
    if "checklist" in modes and not (pundits and rows):
        raise SystemExit(f"REFUSING: the checklist mode needs a project with a checklist; {projects} has none")
    if pundits and rows and "checklist" not in modes:
        raise SystemExit("REFUSING: a pundits session built from --checklist must keep the checklist mode")
    guard_answers(out / files["answers"], rows, quote_rows, transcript_index, args.allow_off_page)
    page_path = out / files["page"]
    for key, side in sidecars.items():
        write_atomic(sidecar_path(page_path, key), json.dumps(side, ensure_ascii=False))
    manifest = {
        "schema_version": SCHEMA_VERSION, "tool": "annotations", "name": name, "projects": projects,
        "modes": modes,
        # Blind means the person saw no model output: no suggestion and no draft.
        "blind": not any(r["suggestions"] for r in recordings.values()) and not args.drafts,
        "transcript_dir": tdir, "files": files, "recordings": recordings,
        "cap_per_recording": QUOTE_CAP_PER_RECORDING if pundits else cap,
        "data_revision": git_revision(data), "code_revision": git_revision(REPO), "inputs_sha256": inputs,
        "built_with": {"checklist": bool(args.checklist), "grades": bool(args.grades), "drafts": bool(args.drafts)},
    }
    if previous and previous.manifest.get("legacy_from"):
        manifest["legacy_from"] = previous.manifest["legacy_from"]
    write_atomic(out / files["quote_key"], json.dumps(key_map, indent=1, ensure_ascii=False) + "\n")
    write_manifest(out, manifest)
    page = write_page(out, manifest, {"rows": rows, "quote_rows": quote_rows, "transcript_index": transcript_index})
    shown = sum(len(r["quotes"]) for r in quote_rows)
    print(f"wrote {out / files['page']}: {len(transcript_index)} recordings, {len(rows)} with a checklist, "
          f"{shown} quotes to attribute; projects {projects}; modes {modes}; {len(page) / 1024:.0f} KB")
    for key, rec in recordings.items():
        if rec.get("reports"):
            print(f"  {key}: {rec['projects']} {rec['reports']}")
    return 0


# ---------------------------------------------------------------- migrate

def migrate(args) -> int:
    """Adopt a session built before this tool. Writes manifest.json and nothing else."""
    root = Path(args.session)
    if toplevel(root.resolve()) is None:
        raise SystemExit(f"REFUSING: {root} is not inside a git checkout; migrate records the data revision it adopted")
    path = root / MANIFEST
    old = json.loads(path.read_text()) if path.exists() else None
    if old and old.get("schema_version") == SCHEMA_VERSION:
        Session.open(root)
        print(f"{root} is already a version-{SCHEMA_VERSION} session; nothing to do")
        return 0
    page = root / args.page
    data = page_data(page.read_text())
    keys = [n for n in ("quote_key.json", "quote_check_key.json") if (root / n).exists()]
    if len(keys) > 1:
        raise SystemExit(f"REFUSING: {root} has both {keys}; name the one this page used")
    if not keys and data.get("quote_rows"):
        raise SystemExit(f"REFUSING: {root} has quotes on its page but no quote key")
    study = old.get("study") if old else None
    if old and (old.get("schema_version") != 1 or study not in LEGACY_STUDY_PROJECT):
        raise SystemExit(f"REFUSING: {path} is not a version-1 manifest this tool knows")
    proj = LEGACY_STUDY_PROJECT.get(study) if study else args.project
    if proj is None:
        raise SystemExit("REFUSING: no version-1 manifest says what this session is; pass --project")
    if args.project and args.project != proj:
        raise SystemExit(f"REFUSING: --project {args.project} contradicts the manifest's study {study!r}")
    project(proj)
    sidecars = {}
    for key in data.get("transcript_index", {}):
        sidecars[key] = json.loads(sidecar_path(page, key).read_text())
    rows = data.get("rows", [])
    checklist = PROJECTS[proj]["checklist"]
    if rows and not checklist:
        raise SystemExit(f"REFUSING: the page has checklist rows but project {proj} has no checklist")
    if rows and data.get("venues") is not None:
        options = [o["value"] for f in checklist["fields"] if f["name"] == "venue" for o in f["options"]]
        if list(data["venues"]) != options:
            raise SystemExit(f"REFUSING: the page's venues {data['venues']} differ from the spec's {options}")
    modes = [m for m in MODES if m != "checklist" or rows]
    v1 = (old or {}).get("recordings", {})
    recordings = {}
    for key, idx in data.get("transcript_index", {}).items():
        quotes = sum(len(r.get("quotes", [])) for r in data.get("quote_rows", []) if r["key"] == key)
        recordings[key] = {**v1.get(key, {}), "projects": [proj], "transcript_dir": PROJECTS[proj]["transcript_dir"],
                           "text_sha256": idx["text_sha256"], "token_count": idx["token_count"],
                           "quotes": {proj: quotes}, "suggestions": len(sidecars[key]["suggestions"])}
    exports = {k: n for k, n in (("quotes", "quote_results.json"), ("labels", "human_labels.json"),
                                 ("corrections", "human_text_corrections.json")) if (root / n).exists()}
    manifest = {
        "schema_version": SCHEMA_VERSION, "tool": "annotations", "name": args.name or root.resolve().name,
        "projects": [proj], "modes": modes, "blind": not any(s["suggestions"] for s in sidecars.values()),
        "transcript_dir": PROJECTS[proj]["transcript_dir"],
        "files": {"page": args.page, "answers": "human_answers.json", "quote_key": keys[0] if keys else "quote_key.json",
                  "exports": exports},
        "recordings": recordings,
        "cap_per_recording": (old or {}).get("cap_per_recording"),
        "data_revision": (old or {}).get("data_revision"), "code_revision": (old or {}).get("code_revision"),
        "inputs_sha256": (old or {}).get("inputs_sha256"),
        "legacy_from": {"schema_version": (old or {}).get("schema_version"), "study": study, "page": args.page,
                        "manifest": old, "migrated_at_data_revision": git_revision(root),
                        "migrated_by_code_revision": git_revision(REPO)},
    }
    if not NAME.fullmatch(manifest["name"]):
        raise SystemExit(f"REFUSING: session name {manifest['name']!r} must match {NAME.pattern}; pass --name")
    answers_before = sha256_bytes((root / "human_answers.json").read_bytes()) if (root / "human_answers.json").exists() else None
    write_manifest(root, manifest)
    after = sha256_bytes((root / "human_answers.json").read_bytes()) if answers_before else None
    if after != answers_before:
        raise SystemExit("FAILED: the answers file changed during migrate")
    print(f"wrote {path}: project {proj}, modes {modes}, {len(recordings)} recordings, "
          f"blind={manifest['blind']}, answers sha256 {answers_before}")
    return 0


# ---------------------------------------------------------------- verify

def sidecar_digest(session: Session) -> str:
    """One hash over every sidecar file's name and bytes, to compare across a rebuild."""
    d = session.page.with_suffix(".transcripts")
    parts = sorted(f"{p.relative_to(d)} {sha256_bytes(p.read_bytes())}" for p in d.rglob("*.json"))
    return sha256_bytes("\n".join(parts).encode())


def export_result(session: Session, kind: str, project_name: str | None = None, source: Path | None = None) -> dict:
    """What `export <kind>` writes, computed in memory."""
    data = session.data()
    if kind == "labels":
        block = session_block(session.manifest)
        if not block["checklist"]:
            raise SystemExit(f"REFUSING: session {session.name} has no checklist mode")
        raw = json.loads(source.read_text()) if source else load_answers(session.answers)
        return to_labels(docs_from(raw, "labels"), {r["key"] for r in data.get("rows", [])}, block["checklist"])
    if kind == "quotes":
        full = json.loads(session.file("quote_key").read_text())
        key_map = full
        if project_name and project_name not in session.projects:
            raise SystemExit(f"REFUSING: session {session.name} has projects {session.projects}, not {project_name!r}")
        if project_name:
            single = session.projects[0] if len(session.projects) == 1 else None

            def owner(entry):
                return entry.get("project") or LEGACY_STUDY_PROJECT.get(entry.get("board")) or single
            key_map = {q: e for q, e in full.items() if owner(e) == project_name}
        elif len({e.get("project") for e in full.values()} - {None}) > 1:
            raise SystemExit("REFUSING: this session's quotes belong to several projects; pass --project")
        raw = json.loads(source.read_text()) if source else load_answers(session.answers)
        if isinstance(raw, dict) and raw.get("spans"):
            raw = reconcile_quote_reviews(raw, session.page, data.get("quote_rows", []))
        docs = [d for d in docs_from(raw, "attribution") if d.get("qid") in key_map or d.get("qid") not in full]
        return join_quotes(docs, key_map)
    raise SystemExit(f"REFUSING: unknown export {kind!r}")


def verify(args) -> int:
    session = Session.open(args.session)
    raw_bytes = session.answers.read_bytes() if session.answers.exists() else b""
    before = sha256_bytes(raw_bytes)
    checks, report = [], {"session": session.name, "projects": session.projects, "modes": session.modes,
                          "answers_sha256": before}

    def check(name, ok, detail=None):
        checks.append({"check": name, "ok": bool(ok), **({"detail": detail} if detail is not None and not ok else {})})

    if args.expect_answers_sha256:
        check("the answers file has the expected sha256", before == args.expect_answers_sha256,
              f"{before} != {args.expect_answers_sha256}")
    answers = load_answers(session.answers)
    data = session.data()
    ids = page_ids(data)
    spans = answers["spans"]
    report["counts"] = {
        "labels": len(answers["labels"]), "attribution": len(answers["attribution"]),
        "attribution_by_method": _count(a.get("review_method", "legacy_quote_check") for a in answers["attribution"].values()),
        "spans_recordings": len(spans), "spans_ranges": sum(len(v["ranges"]) for v in spans.values()),
        "ranges_by_speaker": _count(r["speaker"] for v in spans.values() for r in v["ranges"]),
        "ranges_by_origin": _count(r["origin"] for v in spans.values() for r in v["ranges"]),
        "corrections_recordings": len(answers["corrections"]),
        "correction_edits": sum(len(v["edits"]) for v in answers["corrections"].values()),
        "correction_revisions": {k: v["revision"] for k, v in answers["corrections"].items()},
        "page_recordings": len(ids["spans"]), "page_checklist_rows": len(ids["labels"]),
        "page_quotes": len(ids["attribution"]),
    }
    off_page = {s: sorted(set(answers[s]) - ids[s]) for s in answers}
    check("every saved answer names an id the page carries", not any(off_page.values()),
          {s: v[:5] for s, v in off_page.items() if v})
    bad_side, sidecars = [], {}
    for key, idx in data.get("transcript_index", {}).items():
        try:
            side = json.loads(session.sidecar(key).read_text())
        except (OSError, ValueError) as exc:
            bad_side.append(f"{key}: {exc}")
            continue
        sidecars[key] = side
        if (side["text_sha256"], side["token_count"]) != (idx["text_sha256"], idx["token_count"]) \
                or side["token_count"] != len(side["tokens"]):
            bad_side.append(f"{key}: sidecar hash or token count differs from the page")
    check("every recording's sidecar matches the page's transcript hash and token count", not bad_side, bad_side[:5])
    mrec = session.manifest["recordings"]
    check("the manifest lists exactly the page's recordings, with the same hashes",
          set(mrec) == set(data.get("transcript_index", {})) and all(
              mrec[k]["text_sha256"] == v["text_sha256"] for k, v in data.get("transcript_index", {}).items()),
          sorted(set(mrec) ^ set(data.get("transcript_index", {})))[:5])
    bad = []
    for key, value in spans.items():
        try:
            validate_annotation(value, sidecars[key])
        except (KeyError, ValueError) as exc:
            bad.append(f"{key}: {exc}")
    check("every speaker annotation validates against its transcript", not bad, bad[:5])
    bad = []
    for key, value in answers["corrections"].items():
        try:
            validate_corrections(value, sidecars[key])
        except (KeyError, ValueError) as exc:
            bad.append(f"{key}: {exc}")
    check("every caption correction validates against its transcript", not bad, bad[:5])
    reviewed = reconcile_quote_reviews(answers, session.page, data.get("quote_rows", []))
    check("a read returns the answers file unchanged (quote results already follow the ranges)",
          reviewed == answers, sorted(q for q in reviewed["attribution"]
                                      if reviewed["attribution"][q] != answers["attribution"].get(q))[:5])
    for kind, name in (session.manifest["files"].get("exports") or {}).items():
        disk = json.loads((session.root / name).read_text())
        try:
            got = export_result(session, kind) if kind != "corrections" else _corrections_in_memory(session)
        except (SystemExit, ValueError) as exc:
            # An export that refuses is a failed check, not a missing report.
            check(f"export {kind} reproduces {name}", False, f"the export refused: {exc}")
            continue
        if kind == "labels":
            got = got["labels"]
        check(f"export {kind} reproduces {name}", got == disk,
              "differs" if got != disk else None)
    if args.data:
        root = Path(args.data)
        mism = []
        for key, side in sidecars.items():
            rec = root / mrec[key]["transcript_dir"] / f"{key}.json"
            text = json.loads(rec.read_text()).get("text") or "" if rec.exists() else None
            if text is None or sha256_bytes(text.encode()) != side["text_sha256"]:
                mism.append(key)
        check(f"every sidecar is the text now in {root}", not mism, mism[:5])
    report["live_serve"] = _serve_probe(session, reviewed, check)
    after = sha256_bytes(session.answers.read_bytes()) if session.answers.exists() else sha256_bytes(b"")
    check("the answers file is byte-identical after verify", after == before, f"{before} -> {after}")
    report["sidecars_sha256"] = sidecar_digest(session)
    report["page_sha256"] = sha256_bytes(session.page.read_bytes())
    report["checks"] = checks
    report["ok"] = all(c["ok"] for c in checks)
    text = json.dumps(report, indent=1, ensure_ascii=False)
    print(text)
    if args.out:
        write_atomic(Path(args.out), text + "\n")
    return 0 if report["ok"] else 1


def _count(values) -> dict:
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: str(kv[0])))


def _corrections_in_memory(session: Session) -> dict:
    """`export corrections`, computed into a scratch file and read back."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        return export_corrections(session.answers, session.page, Path(td) / "c.json")


def _serve_probe(session: Session, reviewed: dict, check) -> dict:
    """Start the real server on a free port, read the page and the answers, stop it."""
    from annotations_serve import build_server
    httpd = build_server([session], 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/s/{session.name}/"
    try:
        with urllib.request.urlopen(base, timeout=30) as r:
            page = r.read()
        with urllib.request.urlopen(base + "api/answers", timeout=30) as r:
            got = json.loads(r.read())
    finally:
        httpd.shutdown()
        httpd.server_close()
    check("the server serves the session's page byte for byte", page == session.page.read_bytes())
    check("the server's answers equal the file's, with quote results derived", got == reviewed)
    return {"page_bytes": len(page), "answers_sections": {s: len(v) for s, v in got.items()}}


# ---------------------------------------------------------------- rebuild, export, status, serve

def rebuild(args) -> int:
    session = Session.open(args.session)
    old = session.data()
    before = sha256_bytes(session.answers.read_bytes()) if session.answers.exists() else None
    keep = {k: v for k, v in old.items() if k != "session"}
    write_page(session.root, session.manifest, keep)
    new = session.data()
    for k in ("rows", "quote_rows", "transcript_index"):
        if new.get(k) != old.get(k):
            raise SystemExit(f"FAILED: rebuild changed the page's {k}")
    after = sha256_bytes(session.answers.read_bytes()) if session.answers.exists() else None
    if after != before:
        raise SystemExit("FAILED: the answers file changed during rebuild")
    print(f"rebuilt {session.page}: {len(new.get('transcript_index', {}))} recordings; answers untouched ({before})")
    return 0


def export(args) -> int:
    session = Session.open(args.session)
    out = Path(args.out)
    if args.source and args.kind in ("spans", "corrections"):
        raise SystemExit(f"REFUSING: export {args.kind} reads the session's own answers file; --source applies to "
                         "labels and quotes only")
    if args.project and args.kind != "quotes":
        raise SystemExit("REFUSING: --project applies to export quotes only")
    if args.kind == "spans":
        res = import_spans(session.answers, session.page, out)
        print(f"wrote {out}: {len(res['recordings'])} recordings with human word ranges")
        return 0
    if args.kind == "corrections":
        res = export_corrections(session.answers, session.page, out)
        print(f"wrote {out}: corrections for {len(res['recordings'])} recordings")
        return 0
    res = export_result(session, args.kind, args.project, Path(args.source) if args.source else None)
    if args.kind == "labels":
        write_atomic(out, json.dumps(res["labels"], indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {out}: {len(res['labels'])} complete labels; {len(res['partial'])} partly labelled "
              f"(left out); {len(res['unlabelled'])} not yet labelled")
    else:
        write_atomic(out, json.dumps(res, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {out}: {sum(res['tally'].values())} answered of {sum(res['tally'].values()) + len(res['unanswered'])}"
              f" quotes; {res['tally']}; {len(res['invalid'])} invalid")
    return 0


def status(args) -> int:
    for d in args.session:
        session = Session.open(d)
        data, answers = session.data(), load_answers(session.answers)
        reviewed = reconcile_quote_reviews(answers, session.page, data.get("quote_rows", []))
        print(f"{session.name}  projects {', '.join(session.projects)}  modes {', '.join(session.modes)}  "
              f"blind={session.manifest['blind']}")
        for p in session.projects:
            keys = [k for k, r in session.manifest["recordings"].items() if p in r["projects"]]
            qids = [c["qid"] for r in data.get("quote_rows", []) for c in r["quotes"]
                    if (c.get("project") or session.projects[0]) == p]
            done = sum(1 for q in qids if (reviewed["attribution"].get(q) or {}).get("answer"))
            print(f"  {p}: {len(keys)} recordings, {done} of {len(qids)} quotes answered, "
                  f"{sum(1 for k in keys if k in answers['spans'])} with speaker marks, "
                  f"{sum(1 for k in keys if k in answers['corrections'])} with caption corrections")
        if "checklist" in session.modes:
            print(f"  checklist: {len(answers['labels'])} of {len(data.get('rows', []))} recordings answered")
        marked_blind = sum(1 for v in answers["spans"].values() if v.get("assisted") and session.manifest["blind"])
        if marked_blind:
            print(f"  note: {marked_blind} speaker annotations say assisted on a blind session. A page built "
                  "before 2026-10-18 marks every save assisted until `rebuild` renders it again; the manifest's "
                  "`blind` is the truth")
    return 0


def serve(args) -> int:
    from annotations_serve import HOST, build_server
    sessions = [Session.open(d) for d in args.session]
    httpd = build_server(sessions, args.port)
    port = httpd.server_address[1]
    for s in sessions:
        print(f"{s.name}: http://{HOST}:{port}/s/{s.name}/  ({', '.join(s.projects)}; answers -> {s.answers})")
    print(f"serving {len(sessions)} session(s) on http://{HOST}:{port}/ (loopback only). Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="make a session from a data checkout")
    b.add_argument("--data", required=True, help="the data checkout to read, e.g. data or data-pundits")
    b.add_argument("--project", required=True, action="append", choices=sorted(PROJECTS))
    b.add_argument("--out", required=True, help="the session directory, inside a data checkout")
    b.add_argument("--name", help="the session's name in `serve` (default: the directory's name)")
    b.add_argument("--keys", help="insights/predictions: comma-separated slug/source_id recordings")
    b.add_argument("--reasons", help="insights/predictions: JSON {key: why it was chosen}, kept in the manifest")
    b.add_argument("--cap", type=int, default=None,
                   help=f"insights/predictions: quotes per recording and project (default {DEFAULT_CAP})")
    b.add_argument("--mode", action="append", choices=MODES,
                   help="the modes the page shows (repeat; default: speakers and captions, plus checklist for pundits)")
    b.add_argument("--allow-off-page", action="store_true",
                   help="build even when answers already saved name recordings or quotes the new page drops")
    b.add_argument("--checklist", help="pundits: the checklist of recordings (human_checklist.json)")
    b.add_argument("--grades", action="store_true", help="pundits: flag suspect judge quotes and show the judges' "
                   "located evidence as suggestions (assisted, not blind)")
    b.add_argument("--drafts", help="pundits: speaker_inference.jsonl; show each recording's model draft")
    m = sub.add_parser("migrate", help="adopt a session built before this tool")
    m.add_argument("--session", required=True)
    m.add_argument("--page", default="speaker_check.html")
    m.add_argument("--project", choices=sorted(PROJECTS), help="required when the session has no version-1 manifest")
    m.add_argument("--name")
    v = sub.add_parser("verify", help="prove a session's answers are intact")
    v.add_argument("--session", required=True)
    v.add_argument("--expect-answers-sha256")
    v.add_argument("--data", help="also check every sidecar against the transcript now in this data checkout")
    v.add_argument("--out", help="also write the report here")
    r = sub.add_parser("rebuild", help="render the page again with the current template")
    r.add_argument("--session", required=True)
    e = sub.add_parser("export", help="labels, quotes, spans or corrections, from the answers file")
    e.add_argument("kind", choices=("labels", "quotes", "spans", "corrections"))
    e.add_argument("--session", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--project", choices=sorted(PROJECTS), help="quotes: only this project's")
    e.add_argument("--source", help="labels, quotes: read this answers file or Artifact db export instead")
    s = sub.add_parser("status", help="what has been annotated")
    s.add_argument("--session", required=True, action="append")
    sv = sub.add_parser("serve", help="serve sessions on 127.0.0.1")
    sv.add_argument("--session", required=True, action="append")
    sv.add_argument("--port", type=int, default=5001)
    args = ap.parse_args(argv)
    return {"build": build, "migrate": migrate, "verify": verify, "rebuild": rebuild, "export": export,
            "status": status, "serve": serve}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
