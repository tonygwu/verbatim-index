#!/usr/bin/env python3
"""`data_sync.py` regenerates scores.json from a commit whose scoring.json names a
statement-date override file.

The regeneration runs in a scratch tree extracted from the commit. The scorer
checks every override entry against its transcript, so the scratch tree must hold
the transcripts the override file names; with only predictions/ and roster/ the
scorer refused "unknown transcript" and `push` could never land an override
(found 2026-09-28, integrating the Andreessen override).

  REGEN     a commit with an override regenerates, and scores.json names the file
  FRESH     the regenerated scores are fresh against the commit (check agrees)

  .venv/bin/python scripts/test_data_sync_date_overrides.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def load(name: str, alias: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(alias, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = load("test_data_sync_push", "tdsp_for_overrides")   # its seed(): a real remote with records and a transcript
S = T.S
L = T.L

OVERRIDE = {"statement_date": "2018-06-01", "basis": "conference programme", "source_url": "https://example.com/p",
            "verbatim_evidence": "Ada spoke on 1 June 2018", "confirmed_by": "operator",
            "confirmed_at_utc": "2026-09-28T00:00:00Z"}


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote, _ = T.seed(td)
        c = T.clone(td, remote, "a")
        # A second, web transcript carries the override, so ada/s1's records stay live
        # and the override's own records are superseded (extracted under the old date).
        T.add_transcript(c, "transcripts_web", "ada", "s2", T.Q[2:])
        rel = str(L.DATE_OVERRIDES_FILE)
        (c / rel).write_text(json.dumps({"schema_version": 1, "overrides": {"ada/s2": OVERRIDE}}, indent=1) + "\n")
        cfg_path = c / "predictions" / "scoring.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["date_overrides"] = rel
        cfg_path.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")
        T.commit(c, "add a statement-date override")

        print("REGEN: the scratch tree holds the transcripts the override names")
        try:
            fresh, err = S.regenerate(c, "HEAD"), None
        except S.Refusal as e:
            fresh, err = {}, str(e)
        check("REGEN: a commit whose scoring.json names date_overrides regenerates", err is None, err or "")
        doc = json.loads(fresh.get("predictions/scores.json", b"{}"))
        check("REGEN: scores.json records the override file it read",
              doc.get("settings", {}).get("date_overrides") == rel and
              (doc.get("date_overrides") or {}).get("entries") == ["ada/s2"], str(doc.get("date_overrides"))[:300])

        print("FRESH: the regenerated files are fresh against the commit")
        for k, v in fresh.items():
            (c / k).write_bytes(v)
        if fresh:
            T.commit(c, "regenerate")
        problems = S.derived_problems(c, "HEAD")
        check("FRESH: derived_problems finds nothing stale", bool(fresh) and problems == [],
              "nothing was regenerated" if not fresh else "; ".join(problems))

    print("\n" + ("all passed" if not FAILED else f"{len(FAILED)} failed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
