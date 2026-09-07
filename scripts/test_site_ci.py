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
    print("\n[3] the table leads with Overall, in its own colour, on one shared scale")
    src = (REPO / "scripts" / "build_site.py").read_text()

    heads = re.findall(r'<th data-k="(\w+)"', src)
    check("the header no longer says Composite", "Composite" not in src,
          "found the old column name")
    check('the Overall column is labelled "Overall"', re.search(r'data-k="overall"[^>]*>Overall', src) is not None)
    for k in ("d2", "d3", "d1", "overall"):
        check(f"the header still has a {k} column", k in heads, f"{heads}")
    if all(k in heads for k in ("d2", "d3", "d1", "overall")):
        # Operator decision 2026-09-07, reversing the earlier "a summary reads
        # better after its parts": Overall and its interval are the headline
        # and now sit LEFT of the three dimensions that feed them, right after
        # Organisation, so the ranking reads before the breakdown.
        check("Overall sits to the LEFT of all three sub-dimensions",
              heads.index("overall") < min(heads.index(k) for k in ("d1", "d2", "d3")),
              f"order={heads}")
        check("Overall follows Organisation, with nothing between them",
              heads.index("overall") == heads.index("company") + 1,
              f"order={heads}")

    body = re.search(r'return `<tr class=.*?</tr>`;', src, re.S)
    check("the row template was found", body is not None)
    if body:
        row = body.group(0)
        check("the Overall cell renders the interval, not a plain meter",
              "ciPlot" in row, "no ciPlot call in the row")
        check("the sub-dimension cells still render meters",
              row.count("meter(") == 3, f"meter() calls={row.count('meter(')}")
        check("the Overall cell is emitted before the three meters",
              row.find("ciPlot") < row.find("meter("), "a meter precedes ciPlot")
        check("the interval cell sits immediately after the Overall number",
              row.find("oscore") < row.find("oci") < row.find("meter("),
              "the score and its interval are not adjacent")

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
    # .wrap is 1272px with 24px padding each side, so the table has 1224px.
    # The floor is 200px rather than 140: the scale now prints an endpoint
    # number outside each dot, and 176px packed the digits against the
    # circles. 1224 - 994 of fixed columns leaves 230px, 1.3x the old width.
    check("the fixed columns leave room for the widened scale inside .wrap",
          fixed + 200 <= 1224, f"fixed widths total {fixed}px of 1224px")

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


# ---------------------------------------------------------------------------
# The "What is being scored" prose must match the rubric it describes.
#
# The dimension is called "Technical and industry depth" in RUBRIC.md, and only
# one of its four sub-criteria is technical in the engineering sense: the other
# three are numeracy, operational and industry knowledge, and the ability to
# move between layers. Calling it "Technical depth" on the page told readers to
# expect an engineering test, which is the opposite of what the rubric rewards:
# it explicitly refuses to credit jargon density or spec-reciting.
# ---------------------------------------------------------------------------

def test_scoring_prose_matches_the_rubric() -> None:
    print("\n[prose] the scoring explanation matches RUBRIC.md")
    src = (REPO / "scripts" / "build_site.py").read_text()
    rubric = (REPO / ".claude" / "skills" / "leader-transcript-grader" / "RUBRIC.md").read_text()

    check("the rubric still calls D3 'Technical and industry depth'",
          "Technical and industry depth" in rubric,
          "the rubric was renamed; this test and the page must follow")
    check("the page uses the rubric's own name for the dimension",
          "Technical and industry depth (35%)" in src,
          "page says 'Technical depth', which promises an engineering test")
    check("no bare 'Technical depth (35%)' label survives",
          "<b>Technical depth (35%)</b>" not in src)

    # The four sub-criteria, in words a reader can act on. Matched
    # case-insensitively: this checks that the idea is explained, not how a
    # heading happens to be capitalised.
    low = src.lower()
    for term in ("how the thing works", "numbers", "how the industry actually works",
                 "moving between layers"):
        check(f"the explanation covers {term!r}", term in low, "sub-criterion not explained")

    # Industry depth is the least obvious one, so it must be shown, not asserted.
    check("industry depth is illustrated with concrete examples",
          "supply chain" in low and "regulat" in low,
          "a reader cannot tell what 'industry specificity' means without examples")
    check("the page says detail must change the conclusion, which is the actual hinge",
          "changes the conclusion" in low,
          "without this a reader thinks more detail is always better")
    check("the page repeats the rubric's anti-patterns",
          "jargon" in low and ("name-drop" in low or "reciting" in low),
          "readers should know what is NOT rewarded")
    check("it says a non-engineer can score well here",
          "non-engineer" in low, "the commonest misreading is that this is a coding test")
    check("it says why depth is weighted second, not just what it is",
          "load-bearing" in low, "the weighting rationale is the reason the dimension exists")

    # The short label and the long one must not drift apart. The table column
    # and the Overall formula have to stay short, so they keep "Technical"; the
    # explanatory bullet has room for the rubric's full name. What must never
    # happen is three different names for one dimension.
    check("the table column header and the Overall formula use the same short label",
          '<th data-k="d3">Technical' in src and "&times;Technical +" in src,
          "the column and the formula disagree about what D3 is called")


# ---------------------------------------------------------------------------
# The Technical column needs the same (?) affordance as Halo and 95% interval.
#
# "Technical" alone promises an engineering test. The full name is "Technical
# and industry depth" and three of its four sub-criteria are not engineering.
# The column has no room for the full name, so the explanation goes where the
# other two ambiguous columns already put theirs.
# ---------------------------------------------------------------------------

def test_technical_column_has_an_info_button() -> None:
    print("\n[info] the Technical column explains itself like Halo does")
    src = (REPO / "scripts" / "build_site.py").read_text()

    check("the Technical header carries an info button",
          'data-k="d3">Technical<button class="info"' in src,
          "no (?) on the column whose name is the most misleading")
    # ---- every (?) must have copy, and every dimension must have a (?) ----
    # One-off checks per key drift: d3 got a button and copy while Insight and
    # Clarity, which carry 45% and 20% of the score, had neither. Assert the
    # invariant instead of the instances.
    keys = set(re.findall(r'data-info="(\w+)"', src))
    bodies = set(re.findall(r'^  (\w+): `', src, re.M))
    check("every (?) button has a body in INFO",
          keys <= bodies, f"buttons with no copy: {sorted(keys - bodies)}")
    check("every INFO body is reachable from some (?) button",
          bodies <= keys, f"copy no button opens: {sorted(bodies - keys)}")
    for k, label in (("d1", "Clarity"), ("d2", "Insight"), ("d3", "Technical")):
        check(f"the {label} column carries a (?)", k in keys,
              f"{label} is a scored dimension with no explanation")
    check("the interval copy does not describe the axis and gridlines removed on 2026-09-07",
          "faint rules behind the dots" not in src and "numbers above" not in src,
          "the tooltip points the reader at furniture that is no longer drawn")

    check("it uses the same data-info mechanism as halo and ci",
          'data-info="d3"' in src, "a one-off tooltip would drift from the others")
    check("every info button has an aria-label, so all three are reachable",
          src.count('class="info"') == src.count('aria-label="What'),
          f"{src.count('class=\"info\"')} info buttons but "
          f"{src.count('aria-label=\"What')} labels")
    check("there is a matching INFO entry, or the button opens nothing",
          "\n  d3: `" in src, "data-info=\"d3\" has no body in INFO")

    body = src.split("\n  d3: `", 1)[1].split("`,", 1)[0] if "\n  d3: `" in src else ""
    plain = body.replace("&amp;", "&")
    check("the panel gives the dimension its full name",
          "Technical & industry depth" in plain or "Technical and industry depth" in plain,
          f"body={body[:120]!r}")
    check("it says plainly that this is not an engineering test",
          "not an engineering test" in body.lower() or "non-engineer" in body.lower(),
          "the misreading the button exists to fix is not addressed")
    check("it names all four sub-criteria",
          all(t in body.lower() for t in ("works", "numbers", "industry", "layers")),
          f"body={body[:200]!r}")
    check("it states the hinge: detail must change the conclusion",
          "changes the conclusion" in body.lower(),
          "without this a reader thinks more jargon scores higher")
    check("it gives a concrete industry example rather than asserting the idea",
          "supplier" in body.lower() or "regulator" in body.lower(),
          "abstract wording is what made the old label unclear")
    check("the column label itself stays short",
          '<th data-k="d3">Technical<' in src,
          "the header must stay one word; the panel carries the rest")

    # Everywhere with room for the longer name should use it. Three places have
    # room (legend, per-leader dimension heading, prose) and two do not (the
    # sortable column header, the Overall formula).
    check("the legend under the table uses the fuller name",
          "Technical &amp; industry depth &mdash; 35%" in src,
          "legend still says 'Technical depth'")
    check("the per-leader dimension heading uses it too",
          '"Technical &amp; industry depth"' in src,
          "the expanded row still labels the dimension 'Technical depth'")
    check("no 'Technical depth' label survives anywhere on the page",
          "Technical depth" not in src,
          "one dimension must not have two long names")


def main() -> int:
    print("overall-column confidence interval guards")
    test_bootstrap()
    with tempfile.TemporaryDirectory() as td:
        test_aggregate_emits_ci(Path(td))
    test_table_layout()
    test_scoring_prose_matches_the_rubric()
    test_technical_column_has_an_info_button()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
