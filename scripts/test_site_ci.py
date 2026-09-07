#!/usr/bin/env python3
"""Guards for the Overall column's bootstrap confidence interval (2026-09-07).

The board published a bare point estimate per leader. Its own tie band said gaps
under 4.3 points do not separate two people, and a bootstrap over transcripts
says it more sharply: 0 of 39 adjacent pairs separate at 95%, and the median
leader's rank range is 13 places wide. A leader on 3 transcripts carries a CI
22.3 points wide; one on 12 carries 3.6. The point estimate hides all of it.

  .venv/bin/python scripts/test_site_ci.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(Path(sys.executable))
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


def rows(n, spread=0.0, base=60.0):
    """n transcripts for one leader, scores base-spread .. base+spread."""
    out = []
    for i in range(n):
        v = base + (spread if i % 2 else -spread)
        out.append({"cal_d1_clarity": v, "cal_d2_insight": v,
                    "cal_d3_technical_depth": v, "coverage": 1.0})
    return out


# ---------------------------------------------------------------------------
# 1. The interval itself.
# ---------------------------------------------------------------------------

def test_bootstrap() -> None:
    print("\n[1] the bootstrap interval behaves like an interval")
    a = load("aggregate")
    lo, hi = a.bootstrap_ci(rows(10, spread=8), a.WEIGHTS, a.DIMS, seed=1)
    check("the interval brackets the point estimate", lo < 60.0 < hi, f"[{lo}, {hi}]")
    check("it is not degenerate on varying data", hi - lo > 1.0, f"width={hi-lo}")

    lo2, hi2 = a.bootstrap_ci(rows(10, spread=8), a.WEIGHTS, a.DIMS, seed=1)
    check("it is deterministic for a fixed seed", (lo, hi) == (lo2, hi2), f"{(lo,hi)} vs {(lo2,hi2)}")

    # More evidence must narrow the interval. This is the property the whole
    # display exists to show, so it gets a direct test rather than an eyeball.
    w_few = (lambda t: t[1] - t[0])(a.bootstrap_ci(rows(3, spread=8), a.WEIGHTS, a.DIMS, seed=1))
    w_many = (lambda t: t[1] - t[0])(a.bootstrap_ci(rows(14, spread=8), a.WEIGHTS, a.DIMS, seed=1))
    check("more transcripts give a narrower interval", w_few > w_many,
          f"n=3 width {w_few:.1f} vs n=14 width {w_many:.1f}")

    lo3, hi3 = a.bootstrap_ci(rows(6, spread=0.0), a.WEIGHTS, a.DIMS, seed=1)
    check("identical transcripts give a zero-width interval, not a crash",
          abs(hi3 - lo3) < 1e-9 and abs(lo3 - 60.0) < 1e-9, f"[{lo3}, {hi3}]")

    lo4, hi4 = a.bootstrap_ci(rows(1), a.WEIGHTS, a.DIMS, seed=1)
    check("a single transcript does not raise", lo4 is not None and hi4 is not None, f"[{lo4}, {hi4}]")
    check("an empty leader returns no interval",
          a.bootstrap_ci([], a.WEIGHTS, a.DIMS, seed=1) == (None, None))


# ---------------------------------------------------------------------------
# 2. aggregate.py must publish the interval next to the score it belongs to.
# ---------------------------------------------------------------------------

def test_aggregate_emits_ci(tmp: Path) -> None:
    print("\n[2] aggregate.py writes the interval into results.json")
    roster = tmp / "roster.json"
    roster.write_text(json.dumps({"roster": [
        {"slug": "ada", "name": "Ada", "company": "AE", "role": "CEO", "sector": "AI"},
        {"slug": "alan", "name": "Alan", "company": "BP", "role": "CTO", "sector": "AI"}]}))
    g = tmp / "grades"
    for slug, n, base in (("ada", 8, 70), ("alan", 3, 55)):
        for i in range(n):
            for judge in ("fable", "astra"):
                d = g / judge / slug
                d.mkdir(parents=True, exist_ok=True)
                v = base + (9 if i % 2 else -9)
                (d / f"s{i}__{judge}__blinded__r0.json").write_text(json.dumps({
                    "leader_slug": slug, "source_id": f"s{i}", "judge": judge,
                    "mode": "blinded", "run": 0,
                    "grading_contract": {"contract_id": "test"},
                    "grade": {"dimensions": {k: {"score": v, "reasoning": "r",
                                                 "counterevidence": "c", "evidence": []} for k in
                              ("d1_clarity", "d2_insight", "d3_technical_depth")},
                              "coverage": 1.0, "subject_speech_share_pct": 80, "overall": v}}))
    out = tmp / "results.json"
    r = subprocess.run([PY, str(REPO / "scripts" / "aggregate.py"), "--grades", str(g),
                        "--roster", str(roster), "--out", str(out)],
                       capture_output=True, text=True, cwd=REPO)
    check("aggregate.py runs", r.returncode == 0, r.stderr[-400:])
    if r.returncode != 0:
        return
    res = json.loads(out.read_text())
    led = {l["slug"]: l for l in res["leaders"] if l["status"] == "scored"}
    for s in ("ada", "alan"):
        b = led[s]["blinded"]
        check(f"{s} carries ci_low and ci_high",
              b.get("ci_low") is not None and b.get("ci_high") is not None, f"{b.keys()}")
        check(f"{s}'s interval brackets its own score",
              b["ci_low"] <= b["overall"] <= b["ci_high"],
              f"{b['ci_low']} <= {b['overall']} <= {b['ci_high']}")
    check("the leader with 3 transcripts has the wider interval",
          (led["alan"]["blinded"]["ci_high"] - led["alan"]["blinded"]["ci_low"]) >
          (led["ada"]["blinded"]["ci_high"] - led["ada"]["blinded"]["ci_low"]),
          f"alan {led['alan']['blinded']['ci_low']}-{led['alan']['blinded']['ci_high']}, "
          f"ada {led['ada']['blinded']['ci_low']}-{led['ada']['blinded']['ci_high']}")
    check("the run reports how the interval was made",
          res["diagnostics"].get("bootstrap") is not None,
          "no bootstrap block in diagnostics; the method is unstated")


# ---------------------------------------------------------------------------
# 3. The rendered table.
# ---------------------------------------------------------------------------

def test_table_layout() -> None:
    print("\n[3] the table shows Overall last, in its own colour, with two dots")
    src = (REPO / "scripts" / "build_site.py").read_text()

    heads = re.findall(r'<th data-k="(\w+)"', src)
    check("the header no longer says Composite", "Composite" not in src,
          "found the old column name")
    check('the Overall column is labelled "Overall"', re.search(r'data-k="overall"[^>]*>Overall', src) is not None)
    for k in ("d2", "d3", "d1", "overall"):
        check(f"the header still has a {k} column", k in heads, f"{heads}")
    if all(k in heads for k in ("d2", "d3", "d1", "overall")):
        check("Overall sits to the RIGHT of all three sub-dimensions",
              heads.index("overall") > max(heads.index(k) for k in ("d1", "d2", "d3")),
              f"order={heads}")

    body = re.search(r'return `<tr class=.*?</tr>`;', src, re.S)
    check("the row template was found", body is not None)
    if body:
        cells = re.findall(r'<td class="num[^"]*"[^>]*>\$\{(\w+)\(', body.group(0))
        check("the Overall cell renders the interval, not a plain meter",
              "ciCell" in body.group(0), f"cells={cells}")
        check("the sub-dimension cells still render meters",
              body.group(0).count("meter(") == 3, f"meter() calls={body.group(0).count('meter(')}")
        i_ov = body.group(0).find("ciCell")
        i_last_meter = body.group(0).rfind("meter(")
        check("the Overall cell is emitted after the three meters",
              i_ov > i_last_meter, f"ciCell@{i_ov} last meter@{i_last_meter}")

    check("Overall has its own neutral colour variable, not the Insight hue",
          "--d0" in src and "var(--d2)" not in re.search(r'function ciCell.*?\n}', src, re.S).group(0)
          if re.search(r'function ciCell.*?\n}', src, re.S) else False,
          "ciCell must not reuse --d2")
    ci = re.search(r'function ciCell.*?\n}', src, re.S)
    check("the interval endpoints are printed as small numbers",
          ci is not None and ci.group(0).count("ci-end") >= 2
          and "lo.toFixed(1)" in ci.group(0) and "hi.toFixed(1)" in ci.group(0),
          "no endpoint labels in the markup")
    check("the endpoints sit OUTSIDE the dots so narrow intervals cannot collide",
          ci is not None and ci.group(0).index("ci-end") < ci.group(0).index("ci-band")
          and ci.group(0).rindex("ci-end") > ci.group(0).rindex("dot hi"),
          "labels are not flanking the band")
    check("a narrow interval still gets a drawable band",
          "CI_MIN" in src, "no minimum band width; a 0-width CI would vanish")
    check("the point estimate is still rendered at full size",
          "td.overall .v" in src, "the large number styling is gone")
    check("the Overall header carries a (?) explaining the interval",
          'data-info="ci"' in src, "no affordance to explain the dots")
    check("and the tooltip copy for it exists, so the (?) is not empty",
          re.search(r'const INFO = \{\s*ci:', src) is not None,
          "INFO has no ci entry; clicking the (?) would show nothing")
    check("the default sort is still the Overall order",
          'let sortKey = "rank"' in src, "default sort changed")


def main() -> int:
    print("overall-column confidence interval guards")
    test_bootstrap()
    with tempfile.TemporaryDirectory() as td:
        test_aggregate_emits_ci(Path(td))
    test_table_layout()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
