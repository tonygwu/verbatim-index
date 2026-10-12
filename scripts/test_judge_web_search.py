#!/usr/bin/env python3
"""The web search the page says is "measured and disclosed" is measured, and disclosed.

FOUND 2026-10-12. The pundits blinding note says one judge "can search the web,
which is measured and disclosed rather than blocked", yet results.json carried no
search count and the page showed none. Plan P10 G-search also asks for the rate.

  SEARCHED  aggregate.judge_searched() reads every harness's telemetry: agy's
            web_search_queries, codex's web_search.search_actions, and a
            web_search tool count; a grade with none of them did not search
  COUNTS    diagnostics.judge_web_search counts usable run-0 grades and searched
            ones per judge, on a fixture corpus where one person's Gemini grades
            searched
  PAGE      the page states each judge's count, derived; with no counts it
            states nothing rather than an invented zero
  LEADERS   the key is written only for a contract-v2 study

No quota, no data.

  .venv/bin/python scripts/test_judge_web_search.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def enclosing_line(src: str, needle: str) -> str:
    lines = src.splitlines()
    i = next((k for k, ln in enumerate(lines) if needle in ln), None)
    if i is None:
        return ""
    depth = len(lines[i]) - len(lines[i].lstrip())
    for ln in reversed(lines[:i]):
        if ln.strip() and len(ln) - len(ln.lstrip()) < depth:
            return ln.strip()
    return ""


def main() -> int:
    print("judge web search: measured and disclosed")
    import aggregate as A
    fn = getattr(A, "judge_searched", None)

    print("\n[SEARCHED]")
    if fn is None:
        check("aggregate.judge_searched exists", False)
    else:
        check("agy queries count", fn({"telemetry": {"web_search_queries": ["q"]}}))
        check("codex search actions count", fn({"telemetry": {"web_search": {"search_actions": 2, "queries": []}}}))
        check("a web_search tool count counts", fn({"telemetry": {"tool_use_counts": {"web_search": 1}}}))
        check("empty telemetry is no search", not fn({"telemetry": {"web_search_queries": [], "tool_use_counts": {}}})
              and not fn({}))

    print("\n[COUNTS]")
    tps = load("tps_jws", REPO / "scripts" / "test_profile_scoring.py")
    with tempfile.TemporaryDirectory(prefix="jws-") as td:
        root, profiles = tps.fixture_corpus(Path(td).resolve())
        for f in (root / "grades" / "gemini" / "p1").glob("*.json"):
            rec = json.loads(f.read_text())
            rec["telemetry"] = {"web_search_queries": ["who hosts this show"]}
            f.write_text(json.dumps(rec))
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        env["VI_PROFILES_DIR"] = str(profiles)
        r = subprocess.run([PY, REPO / "scripts" / "aggregate.py", "--study", "pundits", "--grades", root / "grades",
                            "--roster", root / "roster" / "final.json", "--out", root / "out.json"],
                           env=env, capture_output=True, text=True)
        check("the fixture corpus aggregates", r.returncode == 0, r.stderr[-400:])
        res = json.loads((root / "out.json").read_text()) if (root / "out.json").exists() else {}
        ws = (res.get("diagnostics") or {}).get("judge_web_search") or {}
        gem_rows = [t for t in res.get("transcripts", []) if "gemini" in t["judges"]]
        p1 = [t for t in gem_rows if t["leader_slug"] == "p1"]
        check("Gemini: every usable grade counted, p1's searched",
              ws.get("gemini", {}).get("grades") == len(gem_rows) and ws.get("gemini", {}).get("searched") == len(p1),
              f"{ws.get('gemini')} vs grades {len(gem_rows)}, searched {len(p1)}")
        check("Fable searched in none", ws.get("fable", {}).get("searched") == 0, str(ws.get("fable")))

    print("\n[PAGE]")
    import build_study_site as B
    import test_study_site as T
    base = T.results()
    base["diagnostics"]["judge_web_search"] = {"fable": {"grades": 40, "searched": 0},
                                               "gemini": {"grades": 38, "searched": 3}}
    page = B.render(base, T.profile(), T.copy(), rundate="x")
    check("the page states each judge's measured count",
          "Fable searched the web in 0 of 40 grades" in page and "Gemini in 3 of 38" in page,
          page[page.find("searched"):][:200])
    plain = B.render(T.results(), T.profile(), T.copy(), rundate="x")
    check("with no counts it states none", "searched the web in" not in plain)

    print("\n[LEADERS]")
    opener = enclosing_line((REPO / "scripts" / "aggregate.py").read_text(), 'diagnostics["judge_web_search"]')
    check("the key is written only under is_v2", opener == "if is_v2:", opener)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
