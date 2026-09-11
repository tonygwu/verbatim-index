#!/usr/bin/env python3
"""Every run-level judge diagnostic covers every judge that graded.

Three diagnostics were hand-typed to the original pair, fable and astra. Gemini
was promoted out of SHADOW_JUDGES on 2026-09-08 and contributed 514 blinded
grades to the published scores, and all three diagnostics went on reporting two
judges. The leaderboard numbers were right and the evidence for them was not:
a reader auditing whether the promotion took effect saw two judges and would
conclude the arm was still shadowed.

This is the hazard already named at aggregate.py's HIGH_CONFIDENCE_TRANSCRIPTS
comment, one column over: a judge count typed by hand rather than derived goes
stale the day a judge is added. So these checks assert the diagnostics are
DERIVED from the grades present, and they run a four-judge fixture as well as a
three-judge one, because there will be a fourth.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_judge_enumeration.py
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import re
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


ri = load("test_render_integrity")  # a_grade(), run_aggregate()

# Enough transcripts per leader to clear MIN_TRANSCRIPTS_TO_RANK, and enough
# score spread that a correlation is defined rather than degenerate.
LEADERS = ["alpha", "beta", "gamma"]
N_SRC = 6


def build(root: Path, judges: tuple[str, ...]) -> tuple[Path, Path]:
    """One fixture, graded by every judge in `judges`, scores varied per judge.

    Each judge gets its own offset and slope so the raw means differ, which is
    what makes a per-judge mean worth reporting at all.
    """
    grades = root / "grades"
    roster = {"roster": [{"rank": i + 1, "slug": s, "name": s.title(),
                          "company": f"C{i}", "sector": "AI"}
                         for i, s in enumerate(LEADERS)]}
    (root / "roster.json").write_text(json.dumps(roster))
    for li, leader in enumerate(LEADERS):
        for t in range(N_SRC):
            for ji, judge in enumerate(judges):
                score = 50 + li * 7 + t * 3 + ji * 4
                rec = ri.a_grade(leader, f"src{t}", judge, 60, score)
                d = grades / judge / leader
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(json.dumps(rec))
    return grades, root / "roster.json"


def aggregate_with(judges: tuple[str, ...]) -> dict:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        grades, roster = build(tmp, judges)
        out = tmp / "results.json"
        proc = ri.run_aggregate(REPO / "scripts" / "aggregate.py", grades, roster, out)
        if proc.returncode != 0 or not out.exists():
            check(f"aggregate runs on a {len(judges)}-judge fixture", False, proc.stderr[-800:])
            return {}
        check(f"aggregate runs on a {len(judges)}-judge fixture", True)
        return json.loads(out.read_text())


SRC = (REPO / "scripts" / "aggregate.py").read_text()

# ---------------------------------------------------------------------------
# 1. RED PROOF. Rebuild the pre-fix expression from today's source and show it
#    drops a real judge. Without this the rest of the file proves only that
#    today's code runs, not that it fixed anything.
# ---------------------------------------------------------------------------
print("the bug this file exists for")
OLD = '{"fable_blinded": len(fable), "astra_blinded": len(astra)}'
old_present = OLD in SRC
check("the hand-typed pair is gone from aggregate.py", not old_present,
      "aggregate.py:808 still enumerates only fable and astra")

# The old expression, evaluated against a three-judge grade set, names two.
fake = {"fable": 18, "astra": 18, "gemini": 18}
old_result = {"fable_blinded": fake["fable"], "astra_blinded": fake["astra"]}
check("the OLD expression omits a judge that graded (this is the defect)",
      set(old_result) != {f"{j}_blinded" for j in fake},
      "the pre-fix expression would have reported every judge, so the fixture "
      "does not reproduce the bug and the checks below prove nothing")

# ---------------------------------------------------------------------------
# 2. The diagnostics themselves, on three judges and on four.
# ---------------------------------------------------------------------------
for judges in (("fable", "astra", "gemini"), ("fable", "astra", "gemini", "delta")):
    n = len(judges)
    print(f"\n{n} judges: {', '.join(judges)}")
    r = aggregate_with(judges)
    if not r:
        continue
    d = r["diagnostics"]
    expected_n = len(LEADERS) * N_SRC

    counts = d.get("judge_call_counts") or {}
    check("judge_call_counts names every judge that graded",
          set(counts) == {f"{j}_blinded" for j in judges}, str(sorted(counts)))
    check("judge_call_counts counts each judge correctly",
          all(counts.get(f"{j}_blinded") == expected_n for j in judges), str(counts))

    raw = d.get("judge_raw_means_blinded") or {}
    check("judge_raw_means_blinded names every judge that graded",
          set(raw) == set(judges), str(sorted(raw)))
    check("every judge's means cover every dimension",
          all(set(raw.get(j, {})) == set(ri.__dict__.get("DIMS", []) or
              ["d1_clarity", "d2_insight", "d3_technical_depth"]) for j in judges),
          str({j: sorted(raw.get(j, {})) for j in judges}))
    check("the judges' raw means actually differ, so reporting each is not redundant",
          len({raw.get(j, {}).get("d2_insight") for j in judges}) == n,
          str({j: raw.get(j, {}).get("d2_insight") for j in judges}))

    pairs = d.get("judge_pair_agreement") or {}
    want = {"|".join(sorted(p)) for p in itertools.combinations(judges, 2)}
    check("judge_pair_agreement covers every pair, not one of them",
          set(pairs) == want, f"got {sorted(pairs)}\n        want {sorted(want)}")
    check("every pair reports its own n, so a thin pair is visible",
          bool(pairs) and all(isinstance(v.get("n"), int) and v["n"] == expected_n
                              for v in pairs.values()),
          str({k: v.get("n") for k, v in pairs.items()}))
    check("every pair reports a correlation and a mean absolute gap",
          bool(pairs) and all(v.get("correlation_overall") is not None
                              and v.get("mean_abs_gap_overall") is not None
                              for v in pairs.values()),
          str(pairs))

    check("no diagnostic still calls a single pair 'overall'",
          "inter_judge_correlation_overall" not in d and "mean_abs_judge_gap_overall" not in d,
          str([k for k in d if k.endswith("_overall")]))
    check("a panel-level summary is derived from all pairs",
          isinstance(d.get("mean_pairwise_correlation"), float),
          str(d.get("mean_pairwise_correlation")))

# ---------------------------------------------------------------------------
# 3. Nothing downstream may hand-type a judge name for a computed figure.
# ---------------------------------------------------------------------------
print("\nno hand-typed judge names on computed figures")
site = (REPO / "scripts" / "build_site.py").read_text()
check("the header stat is not labelled with a hardcoded pair",
      "Fable vs Astra" not in site,
      "build_site.py:404 labels a computed correlation with a typed pair")
check("the agreement callout does not read judge means by literal name",
      not re.search(r"raw\.get\(\s*['\"](fable|astra|gemini)['\"]", site),
      "build_site.py reads raw.get('fable') / raw.get('astra') directly")
check("build_site no longer reads the removed single-pair keys",
      "inter_judge_correlation_overall" not in site and "mean_abs_judge_gap_overall" not in site)
check("the stale-panel disclaimer is gone, because the figures now cover every pair",
      "not been recomputed across every pair" not in site)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
