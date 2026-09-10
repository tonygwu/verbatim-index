#!/usr/bin/env python3
"""A leader with too few graded transcripts is kept, scored, and NOT ranked.

Asked for on 2026-09-10: a leader under the floor keeps every grade and every
transcript, and keeps a blinded score in results.json, but does not appear in
the published ranking at all. C.C. Wei on 2 real transcripts after the
wrong-person withdrawal (docs/CORPUS-INTEGRITY-FOLLOWUP.md) is a placeholder,
not a score, and the board should not carry it as one.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_rank_floor.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ri = load("test_render_integrity")  # a_grade(), run_aggregate()
agg = load("aggregate")

# Three leaders: comfortably above the floor, exactly at it, and one under it.
COUNTS = {"alpha": 7, "beta": None, "gamma": None}


def build(root: Path, floor: int) -> tuple[Path, Path]:
    grades = root / "grades"
    roster = {"roster": [{"rank": i + 1, "slug": s, "name": s.title(), "company": f"C{i}", "sector": "AI"}
                         for i, s in enumerate(COUNTS)]}
    (root / "roster.json").write_text(json.dumps(roster))
    counts = {"alpha": 7, "beta": floor, "gamma": floor - 1}
    for li, (leader, n) in enumerate(counts.items()):
        for t in range(n):
            for judge in ("fable", "astra"):
                rec = ri.a_grade(leader, f"src{t}", judge, 60 + t, 50 + li * 5 + t)
                d = grades / judge / leader
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(json.dumps(rec))
    return grades, root / "roster.json"


print("rank floor")
check("MIN_TRANSCRIPTS_TO_RANK exists", hasattr(agg, "MIN_TRANSCRIPTS_TO_RANK"))
floor = getattr(agg, "MIN_TRANSCRIPTS_TO_RANK", 5)
check("the floor is the high-confidence band, 5", floor == agg.HIGH_CONFIDENCE_TRANSCRIPTS == 5, str(floor))

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    grades, roster = build(tmp, floor)
    out = tmp / "results.json"
    proc = ri.run_aggregate(REPO / "scripts" / "aggregate.py", grades, roster, out)
    check("aggregate runs", proc.returncode == 0, proc.stderr[-600:])
    r = json.loads(out.read_text()) if out.exists() else {"leaders": [], "diagnostics": {}}
    ranked = {l["slug"]: l for l in r["leaders"]}
    check("a leader under the floor is not in leaders", "gamma" not in ranked, str(sorted(ranked)))
    check("a leader exactly at the floor is ranked", "beta" in ranked)
    check("ranks are contiguous from 1 over the ranked leaders only",
          sorted(l["rank"] for l in r["leaders"]) == list(range(1, len(r["leaders"]) + 1)),
          str([(l["slug"], l["rank"]) for l in r["leaders"]]))
    unranked = {l["slug"]: l for l in r.get("unranked", [])}
    check("the leader is kept under 'unranked' with its blinded score",
          "gamma" in unranked and (unranked["gamma"].get("blinded") or {}).get("overall") is not None,
          str(list(unranked)))
    check("its status says why", unranked.get("gamma", {}).get("status") == "unranked"
          and "n_transcripts" in unranked.get("gamma", {}), str(unranked.get("gamma", {}).get("status")))
    check("it carries no rank", "rank" not in unranked.get("gamma", {}))
    check("its grades still count: grades_used is unchanged by the floor",
          r["diagnostics"].get("grades_used") == 2 * (7 + floor + floor - 1), str(r["diagnostics"].get("grades_used")))
    check("diagnostics name the floor and who fell under it",
          r["diagnostics"].get("min_transcripts_to_rank") == floor
          and r["diagnostics"].get("leaders_unranked") == ["gamma"],
          str({k: r["diagnostics"].get(k) for k in ("min_transcripts_to_rank", "leaders_unranked")}))
    check("leaders with no grades stay under 'unscored', not 'unranked'",
          all(l["status"] != "unranked" for l in r.get("unscored", [])))

site = (REPO / "scripts" / "build_site.py").read_text()
check("the site explains the floor from the constant, not a typed number",
      "__RANK_FLOOR__" in site and "MIN_TRANSCRIPTS_TO_RANK" in site
      and 'replace("__RANK_FLOOR__", str(MIN_TRANSCRIPTS_TO_RANK))' in site)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
