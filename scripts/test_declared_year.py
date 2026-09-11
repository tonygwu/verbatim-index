#!/usr/bin/env python3
"""The year a judge is told must come from the recording, never from a default.

FOUND 2026-09-10 (docs/CORPUS-INTEGRITY-2026-09-10.md, section 1). Every
manifest row carried `year: 2024`, so every judge on every grade read
"Approximate year: 2024" while the real uploads span 2009 to 2026. The
constant was born in sources_to_manifest.py, which turned a missing year into
2024 with `or 2024`, and the fetcher copied it into every record even though
the same record already carried `yt_upload_date` from YouTube. Happyscribe
records carried 0, which the prompt printed as "Approximate year: 0".

Pure checks: no network, no quota.

  .venv/bin/python scripts/test_declared_year.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("\n[1] the manifest does not invent a year")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    (td / "discovered.json").write_text(json.dumps({"leaders": [{
        "leader_slug": "x", "aliases": [], "repairs": [],
        "sources": [{"source_id": "a", "video_id": "abcdefghijk", "title": "t", "venue": "v", "kind": "interview"},
                    {"source_id": "b", "video_id": "abcdefghijl", "title": "t", "venue": "v", "kind": "interview", "year": 2019}]}]}))
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "sources_to_manifest.py"),
                           "--sources", str(td / "discovered.json"), "--manifest", str(td / "all.jsonl"),
                           "--aliases", str(td / "aliases.json"), "--repairs", str(td / "repairs.json"),
                           "--report", str(td / "report.json")], capture_output=True, text=True)
    check("sources_to_manifest runs", proc.returncode == 0, proc.stderr[-400:])
    rows = {json.loads(l)["source_id"]: json.loads(l) for l in (td / "all.jsonl").read_text().splitlines() if l.strip()}
    check("a source with no year gets 0, not 2024", rows.get("a", {}).get("year") == 0, str(rows.get("a")))
    check("a source with a year keeps it", rows.get("b", {}).get("year") == 2019, str(rows.get("b")))

print("\n[2] the fetcher takes the year from YouTube's upload date")
ft = load("fetch_transcripts")
check("declared_year() exists", hasattr(ft, "declared_year"))
if hasattr(ft, "declared_year"):
    check("upload date wins over the manifest",
          ft.declared_year({"year": 2024}, {"yt_upload_date": "20110315"}) == 2011)
    check("a manifest year is used when there is no upload date",
          ft.declared_year({"year": 2019}, {}) == 2019)
    check("no upload date and no manifest year is 0, never a default",
          ft.declared_year({"year": 0}, {"_meta_error": "timeout"}) == 0)
    check("a malformed upload date falls through to the manifest year",
          ft.declared_year({"year": 2019}, {"yt_upload_date": "2011"}) == 2019)
    check("a missing manifest key is 0", ft.declared_year({}, {}) == 0)
src = (REPO / "scripts" / "fetch_transcripts.py").read_text()
check("the record is built from declared_year(), not src['year']",
      '"declared_year": declared_year(src, meta)' in src and '"declared_year": src["year"]' not in src)

print("\n[3] the judge is told 'unknown', never 0")
g = load("grade")
rubric, schema = "RUBRIC", "SCHEMA"
base = {"leader_slug": "x", "source_id": "s", "text": "hello", "declared_kind": "interview",
        "duration_sec": 600, "word_count": 1, "_speaker_name": "X", "_speaker_role": "CEO",
        "declared_venue": "v", "yt_title": "t"}
for mode in ("blinded", "open"):
    p0 = g.build_judge_prompt({**base, "declared_year": 0}, mode, rubric, schema)
    check(f"{mode}: year 0 reads as unknown", "Approximate year: unknown" in p0 and "Approximate year: 0" not in p0)
    pn = g.build_judge_prompt({**base}, mode, rubric, schema)
    check(f"{mode}: missing year reads as unknown", "Approximate year: unknown" in pn and "Approximate year: None" not in pn)
    p1 = g.build_judge_prompt({**base, "declared_year": 2011}, mode, rubric, schema)
    check(f"{mode}: a real year is passed through", "Approximate year: 2011" in p1)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
