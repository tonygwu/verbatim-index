#!/usr/bin/env python3
"""Guards on the shared code the prediction pipeline depends on.

Written 2026-09-10 BEFORE extract_predictions.py existed, so that a change to
grade.py, atomicio.py, the transcript record shape or the roster that would
break the new pipeline is caught by name rather than by a failed corpus run.
Every check runs against the real modules with no model call and no quota.

  IMPORT     grade.py can be imported without parsing argv or touching a model
  SIGNATURE  the three harness callables keep the parameter names the driver passes
  JSON       extract_json handles fences, braces inside strings and trailing prose
  ATOMIC     write_atomic creates parents and leaves no .tmp behind a crash
  RECORD     a real transcripts_open record carries the fields the extractor reads
  ROSTER     the roster loads and every entry has slug, name, role, company
  ROUTER     fable_accounts_from_router maps the default dir to __DEFAULT__

  .venv/bin/python scripts/test_predictions_shared.py
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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


def test_import(g) -> None:
    check("IMPORT: no argparse parser at module level",
          not any(isinstance(v, __import__("argparse").ArgumentParser) for v in vars(g).values()))
    check("IMPORT: main is a function, not run at import", callable(getattr(g, "main", None)))
    for name in ("call_fable", "call_astra", "call_gemini", "extract_json", "stamp_failure",
                 "classify_exception_detail", "ALL_ERROR_TYPES", "E_AUTH", "E_TRANSIENT",
                 "E_BADJSON", "E_SCHEMA", "E_NOJSON", "E_EMPTY", "E_CLI", "E_TIMEOUT",
                 "E_MODEL_MISMATCH", "fable_accounts_from_router", "agy_profiles",
                 "pick_gemini_profile", "account_label", "utcnow"):
        check(f"IMPORT: grade.{name} exists", hasattr(g, name))


def test_signatures(g) -> None:
    want = {
        "call_fable": ["prompt", "config_dir", "timeout", "binary", "workdir"],
        "call_astra": ["prompt", "timeout", "workdir", "model"],
        "call_gemini": ["prompt", "profile_home", "timeout", "workdir", "model", "binary"],
    }
    for fn, params in want.items():
        got = list(inspect.signature(getattr(g, fn)).parameters)
        check(f"SIGNATURE: {fn}({', '.join(params)})", got == params, f"got {got}")
    check("SIGNATURE: fable_command hardcodes the Fable model id, so the driver need not pass one",
          '"--model", "claude-fable-5-1"' in inspect.getsource(g.fable_command))


def test_extract_json(g) -> None:
    check("JSON: bare object", g.extract_json('{"a": 1}') == {"a": 1})
    check("JSON: fenced object", g.extract_json('```json\n{"a": 1}\n```') == {"a": 1})
    check("JSON: braces inside strings",
          g.extract_json('{"q": "he said {wait} and }"}') == {"q": "he said {wait} and }"})
    check("JSON: leading and trailing prose",
          g.extract_json('Sure, here it is:\n{"a": [1, 2]}\nHope that helps.') == {"a": [1, 2]})
    try:
        g.extract_json("no json here")
        check("JSON: no brace raises", False, "returned instead of raising")
    except ValueError as exc:
        check("JSON: no brace raises", "no opening brace" in str(exc), str(exc))


def test_atomic(a) -> None:
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "deep" / "er" / "file.json"
        a.write_atomic(target, "{}")
        check("ATOMIC: parents created and content written",
              target.read_text() == "{}" and not list(target.parent.glob("*.tmp")))
        # A crash during the write must not leave a partial file or a tmp file.
        try:
            a.write_atomic(Path(td) / "x.json", None)  # type: ignore[arg-type]
        except Exception:
            pass
        check("ATOMIC: a failed write leaves neither the file nor a .tmp",
              not (Path(td) / "x.json").exists() and not list(Path(td).glob("*.tmp")))


def test_record() -> None:
    root = REPO / "data" / "transcripts_open"
    files = sorted(root.glob("*/*.json"))
    if not files:
        check("RECORD: data/transcripts_open has records", False, "no files; is data/ linked?")
        return
    rec = json.loads(files[0].read_text())
    need = ["leader_slug", "source_id", "text", "word_count", "url", "declared_title",
            "declared_venue", "declared_kind", "fetched_at_utc", "fetch_method"]
    missing = [k for k in need if k not in rec]
    check("RECORD: required keys present", not missing, f"missing {missing} in {files[0]}")
    check("RECORD: path matches leader_slug/source_id inside the record",
          files[0].parent.name == rec["leader_slug"] and files[0].stem == rec["source_id"])
    check("RECORD: text carries [hh:mm:ss] marks", bool(re.search(r"\[\d{2}:\d{2}:\d{2}\]", rec["text"])))
    # yt_upload_date, when present, is YYYYMMDD. HappyScribe records have none.
    dated = [f for f in files[:200] if json.loads(f.read_text()).get("yt_upload_date")]
    ok = all(re.fullmatch(r"\d{8}", json.loads(f.read_text())["yt_upload_date"]) for f in dated)
    check("RECORD: yt_upload_date is YYYYMMDD wherever present", ok and bool(dated))


def test_roster() -> None:
    roster = json.loads((REPO / "data" / "roster" / "final.json").read_text())["roster"]
    check("ROSTER: at least 40 entries", len(roster) >= 40, str(len(roster)))
    bad = [r.get("slug") for r in roster if not all(r.get(k) for k in ("slug", "name", "role", "company"))]
    check("ROSTER: every entry has slug, name, role, company", not bad, str(bad))
    check("ROSTER: slugs unique", len({r["slug"] for r in roster}) == len(roster))


def test_router(g) -> None:
    accounts = [("claude", "claude", "/Users/x/.claude", True),
                ("claude_b", "claude", "/Users/x/.claude-b", False),
                ("codex", "codex", None, False)]
    rows = [{"account": "claude", "remaining": 0.5}, {"account": "claude_b", "remaining": 0.9}]
    dirs, headroom = g.fable_accounts_from_router(accounts, rows)
    check("ROUTER: default Claude dir maps to __DEFAULT__", "__DEFAULT__" in dirs, str(dirs))
    check("ROUTER: codex is not a Fable account", all("codex" not in d for d in dirs), str(dirs))
    check("ROUTER: headroom keyed by the mapped dir", headroom.get("__DEFAULT__") == 0.5, str(headroom))


def main() -> int:
    g = load("grade")
    a = load("atomicio")
    test_import(g)
    test_signatures(g)
    test_extract_json(g)
    test_atomic(a)
    test_record()
    test_roster()
    test_router(g)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
