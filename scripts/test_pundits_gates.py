#!/usr/bin/env python3
"""The P10 gate report: each gate a verdict, every lean figure at group level only.

docs/PUNDITS-PLAN.md, P10 "Full-corpus validation (no quota)". scripts/pundits_gates.py
reads a pundits data checkout and the private lean labels and writes one JSON report.
This file builds a synthetic checkout of four people, two left and two right, and
checks each gate against figures worked out by hand.

  TOOLS       Fable's transcript_tool_calls: all zero is PASS; any nonzero is FAIL,
              naming the grade; a missing count is INCONCLUSIVE, never PASS
  IDENTITY    the confident rate counts identity_confident; the correct rate also
              requires the guess to name the subject, so a confident wrong guess
              shows the gap between the two
  SEARCH      search rate by judge and mode; a query that names the blinded
              subject is counted; Fable at 0 vs 0 PASSES, Gemini's 0% vs 33% on two
              people per side is INCONCLUSIVE, not PASS
  COVERAGE    loss is scheduled recordings that did not reach the board: left 0 of
              4, right 1 of 4; cells lost by judge and mode; a dropped judge's cells
              are reported as excluded, not counted as loss
  VENUE       the support rule's result is carried from results.json
  JUDGE-LEAN  per judge, (its score minus the other judges') left minus right, on
              complete blinded transcripts, calibrated: Fable 6 points higher on
              the right gives Fable -6 and Gemini +6, both FAIL; no bias PASSES
  HALO-LEAN   mean person halo, left minus right, for the panel and per judge raw:
              panel +2 PASSES, Gemini's raw +6 FAILS
  DRIFT       no anchor re-grades is INCONCLUSIVE and says the gate did not run; an
              anchor re-graded 8 points higher FAILS
  PRIVACY     no object in the report holds both a person's slug and a lean label,
              and the report is written nowhere inside the data checkout
  CLI         --data and --lean-labels are required; the report goes to --out

No quota, no live data.

  .venv/bin/python scripts/test_pundits_gates.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
LEANS = {"p1": "left", "p2": "left", "p3": "right", "p4": "right"}
NAMES = {"p1": "Alice Leftwood", "p2": "Bob Lefter", "p3": "Carol Righton", "p4": "Dan Rightley"}


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def grade(slug: str, sid: str, judge: str, mode: str, *, tool_calls=0, queries=(), guess=None,
          confident=True, venue="conversation", score=50, run=0) -> dict:
    dims = {d: {"score": score, "reasoning": "", "counterevidence": "", "evidence": []}
            for d in ("d1_steelmanning", "d2_epistemic_rigor", "d3_good_faith")}
    tel = {"transcript_tool_calls": tool_calls} if judge == "fable" else {"web_search_queries": list(queries)}
    if tool_calls is None:
        tel = {}
    return {"transcript_id": f"{slug}/{sid}", "leader_slug": slug, "source_id": sid, "judge": judge,
            "mode": mode, "run": run, "study_id": "pundits", "validation_errors": [], "telemetry": tel,
            "grade": {"identity_guess": NAMES[slug] if guess is None else guess,
                      "identity_confident": confident, "venue_type": venue, "dimensions": dims}}


HALOS = {"p1": (2.0, 1.0, 5.0), "p2": (2.0, 1.0, 5.0), "p3": (0.0, 1.0, -1.0), "p4": (0.0, 1.0, -1.0)}


def build(root: Path, *, fable_calls_p1=0, fable_right_bias=6, anchor_drift=None,
          anchor_cells=(("fable", "blinded"),), regraded=None, lovo=True) -> None:
    """Four people, two recordings each, fable + gemini, both modes; astra scheduled but dropped.

    p4's second recording never reaches the board (both its gemini cells failed).
    p3's two blinded gemini grades searched, one query naming Carol Righton.
    p2's first blinded fable grade guessed the wrong person, confidently.
    """
    (root / ".study").write_text("pundits\n")
    (root / "roster").mkdir(parents=True)
    (root / "roster/final.json").write_text(json.dumps({"roster": [
        {"slug": s, "name": n, "handles": [], "archival": False} for s, n in NAMES.items()]}))
    sched, transcripts = [], []
    for slug in NAMES:
        for i in (0, 1):
            sid = f"{slug}-r{i}"
            for judge in ("fable", "gemini", "astra"):
                for mode in ("blinded", "open"):
                    sched.append({"block": 0, "judge": judge, "mode": mode, "run": 0, "slug": slug, "source_id": sid})
                    if judge == "astra" or (slug == "p4" and i == 1 and judge == "gemini"):
                        continue
                    kw = {}
                    if judge == "fable" and slug == "p1" and i == 0 and mode == "blinded":
                        kw["tool_calls"] = fable_calls_p1
                    if judge == "gemini" and slug == "p3" and mode == "blinded":
                        kw["queries"] = ["Carol Righton podcast"] if i == 0 else ["minimum wage study"]
                    if judge == "fable" and slug == "p2" and i == 0 and mode == "blinded":
                        kw["guess"] = "Someone Else"
                    if judge == "fable" and LEANS[slug] == "right":
                        kw["score"] = 50 + fable_right_bias
                    g = grade(slug, sid, judge, mode, **kw)
                    p = root / "grades" / judge / slug / f"{sid}__{judge}__{mode}__r0.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(g))
            if not (slug == "p4" and i == 1):
                for mode in ("blinded", "open"):
                    # The open row can resolve a different venue; the board counts the blinded one.
                    venue = "debate" if (slug, i, mode) == ("p1", 0, "open") else "conversation"
                    transcripts.append({"leader_slug": slug, "source_id": sid, "mode": mode, "venue_type": venue})
    if anchor_drift is not None:
        # p1-r0 is a drift anchor: scheduled as run 1 in a later block for each of
        # `anchor_cells`, and re-graded in each of `regraded` (default: all of them).
        for judge, mode in anchor_cells:
            sched.append({"block": 4, "judge": judge, "mode": mode, "run": 1, "slug": "p1", "source_id": "p1-r0"})
            if (judge, mode) in (anchor_cells if regraded is None else regraded):
                a = grade("p1", "p1-r0", judge, mode, score=50 + anchor_drift, run=1)
                (root / f"grades/{judge}/p1/p1-r0__{judge}__{mode}__r1.json").write_text(json.dumps(a))
    (root / "logs/schedule").mkdir(parents=True)
    (root / "logs/schedule/s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sched))
    leaders = [{"slug": s, "rank": k + 1, "halo": {"overall": h[0], "by_judge_raw": {"fable": h[1], "gemini": h[2]}}}
               for k, (s, h) in enumerate(HALOS.items())]
    n_files = sum(1 for _ in (root / "grades").rglob("*.json"))
    (root / "results.json").write_text(json.dumps({
        "leaders": leaders, "unranked": [], "transcripts": transcripts,
        "diagnostics": {"judge_models": {"fable": {"claude-fable-5-1": 8}, "gemini": {"gemini-3.8-flash-high": 7}},
                        "venue_adjustment_applied": False,
                        "venue_support_reasons": ["venue 'debate' seen 0 times, under the minimum of 8"],
                        "venue_counts": {"conversation": 7}, "grade_files_read": n_files,
                        **({"venue_leave_one_out": {"by_venue": {"conversation": {
                            "people_still_ranked": 0, "people_changing_rank": 0, "rank_correlation": None,
                            "max_abs_shift": None}}}} if lovo else {}),
                        "weights": {"d1_steelmanning": 0.35, "d2_epistemic_rigor": 0.35, "d3_good_faith": 0.3},
                        "calibration_params": {}}}))


def holds_slug_and_lean(obj) -> list:
    """Every dict or list in `obj` whose own scalar values include both a slug and a lean."""
    hits = []
    if isinstance(obj, dict):
        vals = [*obj.keys(), *[v for v in obj.values() if isinstance(v, str)]]
        if any(v in LEANS for v in vals) and any(v in set(LEANS.values()) for v in vals):
            hits.append(obj)
        for v in obj.values():
            hits += holds_slug_and_lean(v)
    elif isinstance(obj, list):
        if any(v in LEANS for v in obj if isinstance(v, str)) and any(
                v in set(LEANS.values()) for v in obj if isinstance(v, str)):
            hits.append(obj)
        for v in obj:
            hits += holds_slug_and_lean(v)
    return hits


def main() -> int:
    print("P10 gate report")
    try:
        import pundits_gates as G
    except Exception as exc:  # noqa: BLE001 - the missing module is the failure under test
        check("scripts/pundits_gates.py is importable", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    with tempfile.TemporaryDirectory(prefix="p10-") as td:
        tmp = Path(td)
        root = tmp / "data"
        root.mkdir()
        build(root)
        leans = tmp / "leans.json"
        leans.write_text(json.dumps(LEANS))
        rep = G.report(root, json.loads(leans.read_text()))
        gates = rep.get("gates", {})

        print("\n[TOOLS]")
        t = gates.get("fable_tool_calls", {})
        check("all-zero Fable tool calls PASS", t.get("verdict") == "PASS" and t.get("grades") == 16, str(t))
        root2 = tmp / "data2"
        root2.mkdir()
        build(root2, fable_calls_p1=2)
        t2 = G.report(root2, LEANS)["gates"]["fable_tool_calls"]
        check("one nonzero count FAILS and names the grade",
              t2.get("verdict") == "FAIL" and "p1/p1-r0" in json.dumps(t2), str(t2))
        root3 = tmp / "data3"
        root3.mkdir()
        build(root3, fable_calls_p1=None)
        t3 = G.report(root3, LEANS)["gates"]["fable_tool_calls"]
        check("a missing count is INCONCLUSIVE, never PASS", t3.get("verdict") == "INCONCLUSIVE", str(t3))

        print("\n[IDENTITY]")
        i = rep.get("identity", {})
        f = i.get("by_judge", {}).get("fable", {})
        check("Fable's blinded grades: 8, all confident", f.get("grades") == 8 and f.get("confident_rate") == 1.0, str(f))
        check("but 7 of 8 name the right person", f.get("correct_rate") == 0.875, str(f))
        check("the per-grade rate over both judges", i.get("correct_rate") == round(14 / 15, 3), str(i))
        # FOUND 2026-10-12 by review: the disclosure verdict read the per-grade rate
        # while the page prints the per-recording one (a board recording counts when
        # any judge named the speaker). The verdict now reads what the page prints.
        board = json.loads((root / "results.json").read_text())
        n_board = sum(1 for t in board["transcripts"] if t["mode"] == "blinded")
        check("the per-recording rate over the board's recordings, as the page counts it",
              i.get("board_recordings") == n_board and isinstance(i.get("board_correct_rate"), float), str(i))
        check("the disclosure verdict follows the per-recording rate (>= 90% correct)",
              i.get("disclosure_required") is (i.get("board_correct_rate", 0) >= G.DISCLOSURE_AT), str(i))

        print("\n[SEARCH]")
        s = gates.get("G-search", {})
        gem = s.get("by_judge", {}).get("gemini", {})
        check("Gemini searched in 2 of its 14 grades", gem.get("searched") == 2 and gem.get("grades") == 14, str(gem))
        check("one query names the blinded subject", s.get("queries_naming_subject") == 1, str(s))
        check("Fable, whose tools are removed, PASSES at 0 vs 0",
              s.get("by_judge", {}).get("fable", {}).get("verdict") == "PASS", str(s.get("by_judge", {}).get("fable")))
        check("Gemini at 0% vs 33% on two people a side is INCONCLUSIVE, not PASS",
              gem.get("verdict") == "INCONCLUSIVE", str(gem))
        check("the left-minus-right point estimate is in percentage points",
              gem.get("left_minus_right_points") == round(0 - 100 * 2 / 6, 1), str(gem))

        print("\n[COVERAGE]")
        c = gates.get("G-coverage", {})
        bl = c.get("by_lean", {})
        check("left loses 0 of 4 scheduled recordings", bl.get("left", {}).get("lost") == 0
              and bl.get("left", {}).get("scheduled") == 4, str(bl))
        check("right loses 1 of 4", bl.get("right", {}).get("lost") == 1 and bl.get("right", {}).get("scheduled") == 4,
              str(bl))
        check("the by-person table names p4's loss without its lean",
              c.get("by_person", {}).get("p4", {}).get("lost") == 1, str(c.get("by_person")))
        cells = c.get("cells_by_judge_mode", {})
        check("cells lost by judge and mode: gemini blinded 1 of 8",
              cells.get("gemini|blinded", {}).get("lost") == 1 and cells.get("gemini|blinded", {}).get("scheduled") == 8,
              str(cells))
        check("venue comes from the blinded row, as the board counts it",
              c.get("by_venue", {}).get("conversation", {}).get("scheduled") == 7 and "debate" not in c.get("by_venue", {}),
              str(c.get("by_venue")))
        check("the dropped judge's cells are excluded, not lost",
              c.get("excluded_judges") == {"astra": 16} and "astra|blinded" not in cells, str(c.get("excluded_judges")))
        check("25 points of loss on two people a side is INCONCLUSIVE", c.get("verdict") == "INCONCLUSIVE", str(c))

        print("\n[VENUE]")
        v = gates.get("venue_support", {})
        check("the support rule's result is carried, with its reason",
              v.get("applied") is False and "debate" in json.dumps(v.get("reasons")), str(v))

        print("\n[JUDGE-LEAN]")
        jl = gates.get("G-judge-lean", {})
        jf, jg = jl.get("by_judge", {}).get("fable", {}), jl.get("by_judge", {}).get("gemini", {})
        check("Fable 6 points higher on the right: Fable's left-minus-right gap is -6, Gemini's +6",
              jf.get("estimate") == -6.0 and jg.get("estimate") == 6.0, str(jl))
        check("a 6-point judge-by-lean gap FAILS for both judges", jf.get("verdict") == "FAIL"
              and jg.get("verdict") == "FAIL" and jl.get("verdict") == "FAIL", str(jl))
        check("it counts complete blinded transcripts: 7 (p4's second never reached the board)",
              jl.get("transcripts") == 7, str(jl.get("transcripts")))
        check("with two judges the report says the test is against one other judge",
              "one other judge" in jl.get("limit", ""), jl.get("limit", ""))
        root5 = tmp / "data5"
        root5.mkdir()
        build(root5, fable_right_bias=0)
        check("with no bias it PASSES", G.report(root5, LEANS)["gates"]["G-judge-lean"].get("verdict") == "PASS")

        print("\n[HALO-LEAN]")
        hl = gates.get("G-halo-lean", {})
        check("the panel halo, left minus right, is +2.0 and PASSES",
              hl.get("panel", {}).get("estimate") == 2.0 and hl.get("panel", {}).get("verdict") == "PASS", str(hl))
        check("Fable's raw halo gap is 0 and PASSES", hl.get("by_judge_raw", {}).get("fable", {}).get("verdict") == "PASS",
              str(hl))
        check("Gemini's raw halo gap is +6 and FAILS",
              hl.get("by_judge_raw", {}).get("gemini", {}).get("estimate") == 6.0
              and hl.get("by_judge_raw", {}).get("gemini", {}).get("verdict") == "FAIL", str(hl))

        check("two people a side carries the few-clusters warning on every lean test",
              all("few_clusters" in rep["gates"][k] for k in ("G-search", "G-coverage", "G-judge-lean", "G-halo-lean")),
              str({k: rep["gates"][k].get("few_clusters") for k in ("G-search", "G-coverage", "G-judge-lean",
                                                                     "G-halo-lean")}))

        print("\n[DRIFT]")
        dr = gates.get("G-drift", {})
        check("no anchor re-grades: INCONCLUSIVE, and it says the gate did not run",
              dr.get("verdict") == "INCONCLUSIVE" and dr.get("ran") is False, str(dr))
        root4 = tmp / "data4"
        root4.mkdir()
        build(root4, anchor_drift=8)
        rep4 = G.report(root4, LEANS)
        d4 = rep4["gates"]["G-drift"]
        # FOUND 2026-10-12 by review: drift-anchor re-grades (run 1) counted again in
        # the identity and search rates, so every anchor counted twice.
        check("a drift re-grade does not count again in identity or search",
              rep4["identity"]["by_judge"]["fable"]["grades"] == 8
              and rep4["gates"]["G-search"]["by_judge"]["fable"]["by_mode"]["blinded"]["grades"]
              == rep["gates"]["G-search"]["by_judge"]["fable"]["by_mode"]["blinded"]["grades"],
              f'{rep4["identity"]["by_judge"]["fable"]} {rep4["gates"]["G-search"]["by_judge"]["fable"]["by_mode"]}')
        cell = d4.get("by_judge_mode", {}).get("fable|blinded", {})
        check("an anchor re-graded 8 points higher: last minus first is +8.0 and FAILS",
              d4.get("ran") is True and cell.get("estimate") == 8.0 and cell.get("verdict") == "FAIL", str(d4))
        # FOUND 2026-10-12 by review: anchors in the manifest with no re-grade yet
        # (mid-P9) returned ran=False with no reason, and the document renderer died
        # on the missing key.
        root8 = tmp / "data8"
        root8.mkdir()
        build(root8, anchor_drift=0, regraded=())
        d5 = G.report(root8, LEANS)["gates"]["G-drift"]
        check("anchors scheduled but none re-graded yet: INCONCLUSIVE, did not run, and it says why",
              d5.get("verdict") == "INCONCLUSIVE" and d5.get("ran") is False
              and "none has been re-graded" in d5.get("why", ""), str(d5))
        # FOUND 2026-10-12 by review: the plan tests drift per judge and mode, and a
        # cell with no re-grade at all (every Gemini re-grade refused) let the gate
        # PASS on Fable alone.
        root6 = tmp / "data6"
        root6.mkdir()
        build(root6, anchor_drift=0, anchor_cells=(("fable", "blinded"), ("gemini", "blinded")),
              regraded=(("fable", "blinded"),))
        d6 = G.report(root6, LEANS)["gates"]["G-drift"]
        check("a scheduled judge-mode cell with no re-grade: INCONCLUSIVE, naming the cell",
              d6.get("verdict") == "INCONCLUSIVE" and d6.get("missing_cells") == ["gemini|blinded"]
              and d6.get("by_judge_mode", {}).get("fable|blinded", {}).get("verdict") == "PASS", str(d6))

        print("\n[VENUE SENSITIVITY]")
        # FOUND 2026-10-12 by review: plan P5 requires the leave-one-venue-out "in
        # both cases", and a results.json without it rendered no table and no word.
        root7 = tmp / "data7"
        root7.mkdir()
        build(root7, lovo=False)
        try:
            G.report(root7, LEANS)
            refused = ""
        except RuntimeError as exc:
            refused = str(exc)
        check("a results.json without venue_leave_one_out is refused, naming it",
              "venue_leave_one_out" in refused, refused or "no refusal")

        print("\n[DISPUTED VENUE]")
        # A 1-1 judge tie keeps an alphabetically chosen label with venue_agreed=False;
        # the loss table must not file that recording under the label.
        root10 = tmp / "data10"
        root10.mkdir()
        build(root10)
        res = json.loads((root10 / "results.json").read_text())
        n_disputed = 0
        for t in res["transcripts"]:
            if t["mode"] == "blinded" and t["leader_slug"] == "p2":
                t["venue_agreed"] = False
                n_disputed += 1
        (root10 / "results.json").write_text(json.dumps(res))
        bv = G.report(root10, LEANS)["gates"]["G-coverage"]["by_venue"]
        check("a disputed format is counted as disputed in the loss table",
              bv.get("format disputed", {}).get("scheduled") == n_disputed > 0, str(bv))
        vc = G.report(root10, LEANS)["gates"]["venue_support"]["venue_counts"]
        check("and in the recordings-by-venue count, which matches the board's blinded rows",
              vc.get("format disputed") == n_disputed and sum(vc.values()) == sum(
                  1 for t in res["transcripts"] if t["mode"] == "blinded"), str(vc))

        print("\n[STALE]")
        # FOUND 2026-10-12 by review: the report read grades from disk and
        # results.json separately, so a results.json older than the grades turned
        # every newer recording into a "loss" in G-coverage.
        root9 = tmp / "data9"
        root9.mkdir()
        build(root9)
        extra = root9 / "grades/fable/p1/late__fable__blinded__r0.json"
        extra.write_text((root9 / "grades/fable/p1/p1-r0__fable__blinded__r0.json").read_text())
        try:
            G.report(root9, LEANS)
            stale = ""
        except RuntimeError as exc:
            stale = str(exc)
        check("a grade file newer than results.json is refused, with both counts",
              "grade_files_read" in stale and "1 newer" in stale, stale or "no refusal")

        print("\n[PRIVACY]")
        hits = holds_slug_and_lean(rep)
        check("no object pairs a slug with a lean label", not hits, json.dumps(hits)[:400])
        check("the lean groups are counted, not listed",
              rep.get("lean_groups") == {"left": 2, "right": 2}, str(rep.get("lean_groups")))

        print("\n[CLI]")
        out = tmp / "report.json"
        r = subprocess.run([sys.executable, REPO / "scripts/pundits_gates.py", "--data", root,
                            "--lean-labels", leans, "--out", out], capture_output=True, text=True)
        check("the CLI writes the report to --out", r.returncode == 0 and out.exists()
              and json.loads(out.read_text()).get("gates"), r.stderr[-300:])
        r = subprocess.run([sys.executable, REPO / "scripts/pundits_gates.py", "--data", root,
                            "--lean-labels", leans, "--out", root / "gates.json"], capture_output=True, text=True)
        check("a report path inside the data checkout is refused",
              r.returncode != 0 and not (root / "gates.json").exists(), r.stderr[-300:])
        r = subprocess.run([sys.executable, REPO / "scripts/pundits_gates.py", "--data", root, "--out", out],
                           capture_output=True, text=True)
        check("--lean-labels is required", r.returncode != 0, r.stderr[-200:])

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
