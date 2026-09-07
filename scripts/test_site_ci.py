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
    print("\n[3] the table shows Overall last, in its own colour, on one shared scale")
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
        row = body.group(0)
        check("the Overall cell renders the interval, not a plain meter",
              "ciPlot" in row, "no ciPlot call in the row")
        check("the sub-dimension cells still render meters",
              row.count("meter(") == 3, f"meter() calls={row.count('meter(')}")
        check("the Overall cell is emitted after the three meters",
              row.find("ciPlot") > row.rfind("meter("), "ciPlot precedes a meter")

    # ---- the score is its own cell, left-aligned -------------------------
    # It used to share a cell with the band, so the digits drifted sideways
    # from row to row and never formed a column.
    if body:
        row = body.group(0)
        check("the score has a cell of its own, separate from the interval",
              'class="overall oscore"' in row and 'class="overall oci"' in row,
              "score and interval are still one cell")
        check("the score cell is emitted before the interval cell",
              "oscore" in row and "oci" in row and row.index("oscore") < row.index("oci"),
              "one of the two Overall cells is missing")
    check("the score cell is left-aligned",
          re.search(r'td\.oscore\{[^}]*text-align:left', src) is not None,
          "td.oscore does not set text-align:left")
    check("the score is still rendered at full size",
          re.search(r'td\.oscore \.v\{[^}]*font-size:18px', src) is not None,
          "the large number styling is gone")
    check("both Overall cells still share the column shading",
          re.search(r'td\.overall\{[^}]*background:var\(--surface-2\)', src) is not None,
          "the shaded band behind Overall is gone")

    # ---- one scale shared by every row ----------------------------------
    # This is the whole point of the redraw. A per-row scale made a high score
    # and a low score draw the same picture, so rows could not be compared.
    check("the domain comes from the whole table, not from one row",
          re.search(r'const CI_DOM = \(\(\) => \{.*?DATA\.map\(r => r\.ci_low\).*?DATA\.map\(r => r\.ci_high\)',
                    src, re.S) is not None,
          "CI_DOM is not derived from every row's endpoints")
    check("the old per-row pixels-per-point scale is gone",
          "CI_PPP" not in src and "CI_MIN" not in src,
          "a per-row scale constant survives; rows would not be comparable")
    plot = re.search(r'function ciPlot\(.*?\n}', src, re.S)
    check("the plot function was found", plot is not None)
    if plot:
        f = plot.group(0)
        check("low, high and the point estimate all use the shared mapping",
              f.count("ciPct(") == 3, f"ciPct() calls={f.count('ciPct(')}")
        check("the plot positions marks in percent of the shared domain",
              f.count("%") >= 4 and "px" not in f,
              "marks are placed in pixels, which breaks the shared scale")
        check("Overall keeps its own neutral colour, not the Insight hue",
              "--d0" in src and "var(--d2)" not in f, "ciPlot must not reuse --d2")
        check("the exact endpoints stay reachable, in the cell's tooltip",
              "title=" in f and "lo.toFixed(1)" in f and "hi.toFixed(1)" in f,
              "the endpoint numbers are not recoverable anywhere")
    # ---- the scale is read from numbers, not from a ruler ----------------
    # The axis and the gridlines behind each row were removed on request: the
    # column read as a chart of vertical bars. Each row now prints its own two
    # endpoints, so the scale is still readable without any furniture.
    check("the header axis is gone, leaving the label and the (?) alone",
          'id="ciaxis"' not in src and "ciAxis" not in src
          and "ci-axis" not in src,
          "an axis survives; the header should be '95% interval ?' only")
    check("the vertical gridlines behind the rows are gone",
          "CI_GRID" not in src and "ci-grid" not in src and "CI_TICKS" not in src,
          "the per-row vertical rules survive")
    if plot:
        f = plot.group(0)
        check("each endpoint is printed beside its own dot",
              'class="lab lab-lo"' in f and 'class="lab lab-hi"' in f,
              "the endpoint numbers are not drawn in the cell")
        check("the two endpoint labels grow outward so they cannot collide",
              "translateX(-100%)" in src and ".lab-hi{padding-left" in src,
              "labels are centred on their dots and will run together")
        check("a label sits at the same coordinate as the dot it belongs to",
              f.count('style="left:${a.toFixed(3)}%"') == 2
              and f.count('style="left:${b.toFixed(3)}%"') == 2,
              "a label and its dot are placed independently and can drift apart")
        check("the printed endpoints carry one decimal, like every other score",
              f.count("lo.toFixed(1)") >= 2 and f.count("hi.toFixed(1)") >= 2,
              "endpoint labels are not formatted like the rest of the table")
        check("the labels are hidden from screen readers, which get the tooltip",
              f.count('aria-hidden="true"') == 2,
              "the numbers would be read out twice")
    check("the cell reserves room for a label that hangs outside the band",
          re.search(r'td\.oci\{[^}]*padding-left:(\d+)px', src) is not None
          and int(re.search(r'td\.oci\{[^}]*padding-left:(\d+)px', src).group(1)) >= 30,
          "a full-width interval would clip its own endpoint labels")

    # ---- the table must fit its container -------------------------------
    # It used to be 73px wider than the card, so the last column was reachable
    # only by scrolling sideways.
    check("the table has a fixed layout with an explicit colgroup",
          "table-layout:fixed" in src and "<colgroup>" in src,
          "column widths are left to content, which overflowed the card")
    cols = re.findall(r'<col(?: style="width:(\d+)px")?>', src)
    n_th = len(re.findall(r'<th[ >]', src))
    check("there is one <col> per header cell",
          len(cols) == n_th, f"{len(cols)} cols vs {n_th} headers")
    check("exactly one column is flexible, so the scale absorbs the slack",
          cols.count("") == 1, f"flexible columns={cols.count('')}")
    fixed = sum(int(c) for c in cols if c)
    check("the fixed columns leave room for the scale inside .wrap",
          fixed + 140 <= 1170, f"fixed widths total {fixed}px of 1170px")

    span = re.search(r'colspan="(\d+)"', src)
    check("the drawer spans every column",
          span is not None and span.group(1) == str(n_th),
          f"colspan={span.group(1) if span else None} vs {n_th} headers")

    # ---- headers ---------------------------------------------------------
    check("every column header is centred",
          re.search(r'thead th\{[^}]*text-align:center', src) is not None
          and "thead th.num{text-align:right}" not in src,
          "a header is still left- or right-aligned")
    check("the interval header does not pretend to sort",
          'class="nosort ocih"' in src and "th && th.dataset.k" in src,
          "clicking the axis header would sort by undefined")

    check("the Overall interval keeps a (?) explaining it",
          'data-info="ci"' in src, "no affordance to explain the dots")
    check("and the tooltip copy for it exists, so the (?) is not empty",
          re.search(r'const INFO = \{\s*ci:', src) is not None,
          "INFO has no ci entry; clicking the (?) would show nothing")
    check("the tooltip says the scale is shared",
          re.search(r'ci: `.*?same\*?\*? ?scale|ci: `.*?<b>same</b> scale', src, re.S) is not None
          or "same</b> scale" in src,
          "the tooltip never explains that rows share one scale")
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
