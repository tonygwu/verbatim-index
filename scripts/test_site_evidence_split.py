#!/usr/bin/env python3
"""The evidence is published beside the page, and the page stays small enough to unfurl.

Found 2026-09-17. Every judge's reasoning, every cited quote and every red flag
was inlined into site/index.html as `const AUDIT = {...}`. On the 50-leader
board that made the published document 16,044,532 bytes, and Twitter's card
validator answered:

    ERROR: Fetching the page failed because the response is too large.

The og:image, og:title and twitter:card tags were all present and correct. The
crawler never got far enough to read them, so a posted link showed no card at
all. The page also made every visitor download 15 MB of evidence for 50 leaders
to look at one.

The evidence now goes to <site>/audit/<slug>.json, fetched when a row is
opened. These checks are behavioural: they render a fixture corpus carrying a
canary string and follow where that string comes out.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_site_evidence_split.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
PASS, FAIL = [], []

# Distinctive enough that finding it anywhere is proof of where it came from.
CANARY_REASONING = "CANARY-REASONING-a41f9c"
CANARY_QUOTE = "CANARY-QUOTE-7d20e3"
LEADERS = ("alpha", "beta", "gamma")


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ri = load("test_render_integrity")  # a_grade(), run_aggregate()


def build_inputs(root: Path, bump: int = 0) -> dict[str, Path]:
    """A production-shaped data directory. bump changes one score, nothing else."""
    grades = root / "grades"
    for li, leader in enumerate(LEADERS):
        for t in range(6):
            for judge in ("fable", "astra"):
                rec = ri.a_grade(leader, f"src{t}", judge, 60 + t, 50 + li * 5 + t + bump)
                # The canary rides on exactly one grade, in the two places the
                # drawer renders free text from.
                if leader == "alpha" and t == 0 and judge == "fable":
                    dims = rec["grade"]["dimensions"]
                    dims["d1_clarity"]["reasoning"] = CANARY_REASONING
                    dims["d1_clarity"]["evidence"] = [{"quote": CANARY_QUOTE, "why": "w"}]
                d = grades / judge / leader
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(json.dumps(rec))

    roster = {"roster": [{"rank": i + 1, "slug": s, "name": s.title(), "role": "CEO",
                          "company": f"C{i}", "sector": "AI"}
                         for i, s in enumerate(LEADERS)],
              "dropped_for_no_transcripts": []}
    (root / "roster.json").write_text(json.dumps(roster))

    blind = root / "transcripts_blind"
    for leader in LEADERS:
        d = blind / leader
        d.mkdir(parents=True, exist_ok=True)
        for t in range(6):
            (d / f"src{t}.json").write_text(json.dumps({"word_count": 1000}))

    (root / "calibration.json").write_text(json.dumps({"headline": {}}))
    (root / "sources.json").write_text(json.dumps({}))
    results = root / "results.json"
    proc = ri.run_aggregate(REPO / "scripts" / "aggregate.py", grades, root / "roster.json", results)
    if proc.returncode != 0 or not results.exists():
        sys.exit(f"REFUSING: fixture aggregate failed: {proc.stderr[-600:]}")
    return {"results": results, "audit": results.with_name("results_audit.json"),
            "roster": root / "roster.json", "calibration": root / "calibration.json",
            "sources": root / "sources.json"}


def render(paths: dict[str, Path], out: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(REPO / "scripts" / "build_site.py"),
         "--results", str(paths["results"]), "--audit", str(paths["audit"]),
         "--roster", str(paths["roster"]), "--calibration", str(paths["calibration"]),
         "--sources", str(paths["sources"]), "--out", str(out)],
        capture_output=True, text=True, cwd=REPO, env={**os.environ, **(env or {})})


print("== the evidence leaves the document and lands beside it ==")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    paths = build_inputs(root)
    site = root / "site"
    out = site / "index.html"
    r = render(paths, out)
    check("render succeeds", r.returncode == 0, f"stderr={r.stderr[-400:]}")
    page = out.read_text() if out.exists() else ""
    audit_dir = site / "audit"
    files = sorted(audit_dir.glob("*.json")) if audit_dir.is_dir() else []

    check("one evidence file per leader on the board",
          [f.stem for f in files] == sorted(LEADERS), f"{[f.name for f in files]}")

    joined = "\n".join(f.read_text() for f in files)
    check("the judge's reasoning is in the evidence files",
          CANARY_REASONING in joined)
    check("the cited quote is in the evidence files", CANARY_QUOTE in joined)
    check("the judge's reasoning is NOT in the page",
          CANARY_REASONING not in page,
          "the page still carries the evidence inline; that is the 16 MB defect")
    check("the cited quote is NOT in the page", CANARY_QUOTE not in page)

    for f in files:
        body = json.loads(f.read_text())
        check(f"{f.name} is a list of grades",
              isinstance(body, list) and bool(body) and all("dimensions" in g for g in body))
        check(f"{f.name} carries only blinded grades",
              all(g.get("mode") == "blinded" for g in body))

    # The page's own table data has no such key, so finding one means a whole
    # grade object was serialised into the document again.
    check("no grade object is serialised into the page",
          '"dimensions":' not in page and '"evidence":' not in page,
          f"page {len(page.encode())} bytes and carries grade objects")

    print("\n== the page fetches each leader's file, versioned ==")
    m = re.search(r'const AUDIT_VERSION = "([0-9a-f]+)"', page)
    check("the page carries an evidence version", bool(m), "no AUDIT_VERSION")
    version_a = m.group(1) if m else ""
    check("the fetch url is per leader and carries that version",
          "audit/${encodeURIComponent(slug)}.json?v=${AUDIT_VERSION}" in page)
    slugs = re.search(r"const AUDIT_SLUGS = (\[[^\]]*\])", page)
    check("the page names the leaders that have evidence",
          bool(slugs) and sorted(json.loads(slugs.group(1))) == sorted(LEADERS),
          slugs.group(1) if slugs else "no AUDIT_SLUGS")

    print("\n== a file from an earlier render does not survive on the site ==")
    stale = audit_dir / "withdrawn-leader.json"
    stale.write_text(json.dumps([{"mode": "blinded"}]))
    r2 = render(paths, out)
    check("re-render succeeds", r2.returncode == 0, f"stderr={r2.stderr[-300:]}")
    check("the withdrawn leader's evidence is deleted", not stale.exists())
    check("the render says which file it removed",
          "withdrawn-leader.json" in (r2.stdout + r2.stderr), r2.stdout[-300:])
    check("the leaders on the board keep their evidence",
          sorted(f.stem for f in audit_dir.glob("*.json")) == sorted(LEADERS))
    check("an unchanged corpus keeps the same version",
          re.search(r'const AUDIT_VERSION = "([0-9a-f]+)"', out.read_text()).group(1) == version_a)

print("\n== changed evidence changes the version, so no browser serves a stale mix ==")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    site = root / "site"
    out = site / "index.html"
    render(build_inputs(root / "a"), out)
    version_a = re.search(r'const AUDIT_VERSION = "([0-9a-f]+)"', out.read_text()).group(1)
    render(build_inputs(root / "b", bump=3), out)
    version_b = re.search(r'const AUDIT_VERSION = "([0-9a-f]+)"', out.read_text()).group(1)
    check("a changed grade gives a different version", version_a != version_b,
          f"both {version_a}")

print("\n== a page over the crawler budget is refused, not published ==")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    paths = build_inputs(root)
    site = root / "site"
    out = site / "index.html"
    r = render(paths, out, env={"VI_MAX_PAGE_BYTES": "1000"})
    check("render refuses an oversized page", r.returncode != 0, f"exit {r.returncode}")
    check("the refusal gives both numbers",
          "1,000" in (r.stderr + r.stdout) and "bytes" in (r.stderr + r.stdout),
          f"stderr={r.stderr[-300:]}")
    check("nothing is published on refusal", not out.exists())
    check("and no evidence file is left behind either, pointing at a page that does not exist",
          not (site / "audit").exists() or not list((site / "audit").glob("*.json")))

    bs = load("build_site")
    check("the shipped budget is well under a megabyte-scale page",
          bs.MAX_PAGE_BYTES == 2_000_000, f"MAX_PAGE_BYTES={bs.MAX_PAGE_BYTES}")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
raise SystemExit(1 if FAIL else 0)
