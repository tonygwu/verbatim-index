#!/usr/bin/env python3
"""compare_resolvers.py picks rows by a stated rule and reports two resolvers' agreement row by row.

`select` finds each board row's resolution among the scored runs by matching the
reasoning text scores.json carries, so it never re-implements the scorer's
choice. Then it takes, for each outcome, the rows first in sha256("<salt>:<id>")
order, at most `already_public` rows with that field set, at most `per_leader`
rows of one leader overall. `report` reads two experiment runs and states each
agreement with its count. Synthetic runs in a temp folder; no model call.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_resolvers as C  # noqa: E402
import resolution_lib as R  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def raises(fn) -> "str | None":
    try:
        fn()
    except (SystemExit, ValueError) as exc:
        return str(exc)
    return None


def sidecar(run: Path, pid: str, slug: str, outcome: str, *, ap=None, harness="astra", reasoning=None,
            release="resolution-2026-10-11", sources=None, prompt="p") -> dict:
    obj = {"prediction_id": pid, "leader_slug": slug, "stage": "resolve", "outcome": outcome, "harness": harness,
           "reasoning": reasoning or f"why {pid}", "already_public": ap, "policy_release": release,
           "as_of": "2026-10-11", "prompt_sha256": prompt, "sources": sources or [{"what_it_shows": f"s {pid}",
           "where": f"https://e.com/{pid}", "date": "2025-01-01"}], "confidence": "high", "searched": ["a", "b", "c"],
           "unresolvable_reason": "no_public_evidence" if outcome == "unresolvable" else None,
           "telemetry": {"web_search": {"queries": ["a", "b", "c"]}}}
    if harness == "gemini":
        # Only the Gemini harness records it (gemini_resolver.call); Astra's is read from its raw answer.
        obj["telemetry"]["own_site_mentions"] = 0
    dest = R.sidecar_path(run, "resolve", slug, pid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(obj))
    return obj


AP = {"date": "2024-01-01", "where": "w", "what_it_shows": "x"}
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    r1, r2 = td / "run1", td / "run2"
    scores = []

    def board(pid, slug, outcome, run=r1, eligible=True, **kw):
        obj = sidecar(run, pid, slug, outcome, **kw)
        scores.append({"prediction_id": pid, "leader_slug": slug, "outcome": outcome,
                       "resolution_reasoning": obj["reasoning"], "flags": {"eligible": eligible}})
        return obj

    # 6 leaders x 3 outcomes, two of each outcome with already_public set
    for i in range(18):
        outcome = ("occurred", "not_occurred", "unresolvable")[i % 3]
        board(f"p{i:02d}", f"lead{i % 6}", outcome, ap=AP if i < 6 else None)
    board("gem", "lead0", "occurred", harness="gemini")                       # not an Astra resolution
    board("inel", "lead1", "occurred", eligible=False)                        # ineligible
    board("adj", "lead2", "occurred")                                         # operator-adjudicated
    scores.append({"prediction_id": "open", "leader_slug": "lead3", "outcome": None,
                   "resolution_reasoning": None, "flags": {"eligible": True}})  # not resolved
    scores.append({"prediction_id": "lost", "leader_slug": "lead3", "outcome": "occurred",
                   "resolution_reasoning": "no sidecar says this", "flags": {"eligible": True}})
    early = {"prediction_id": "early1", "leader_slug": "lead5", "stage": "early", "outcome": "occurred",
             "harness": "astra", "reasoning": "settled before its deadline", "already_public": None}
    ef = R.sidecar_path(r1, "early", "lead5", "early1")
    ef.parent.mkdir(parents=True, exist_ok=True)
    ef.write_text(json.dumps(early))
    scores.append({"prediction_id": "early1", "leader_slug": "lead5", "outcome": "occurred",
                   "resolution_reasoning": early["reasoning"], "flags": {"eligible": True}})
    o = board("dup", "lead4", "occurred")
    sidecar(r2, "dup", "lead4", "occurred", reasoning=o["reasoning"])         # matched in two runs
    sidecar(r2, "p00", "lead0", "not_occurred", reasoning="an older run's answer")  # not the board's

    sel = C.select(scores, [r1, r2], exclude={"adj"}, per_outcome=2, already_public=1, per_leader=1, salt="T",
                   root=td)
    chosen = sel["rows"]
    ids = [r["prediction_id"] for r in chosen]
    check("the board's resolution is the sidecar whose reasoning scores.json carries, not another run's",
          next((r for r in chosen if r["prediction_id"] == "p00"), {"board_run": "run1"})["board_run"] == "run1",
          str(chosen))
    check("a board run is recorded relative to the data root, so the selection reads on any machine",
          all(not Path(r["board_run"]).is_absolute() for r in chosen), str([r["board_run"] for r in chosen]))
    ex = sel["excluded"]
    check("each left-out row is counted by its reason",
          ex == {"adjudicated": 1, "not_astra": 1, "not_eligible": 1, "not_resolved": 1, "no_matching_sidecar": 1,
                 "several_matching_sidecars": 1, "early_stage": 1}, str(ex))
    check("the rule names the early-stage exclusion", "early" in sel["rule"], sel["rule"])
    check("per_outcome rows of each outcome, when the pool allows", sorted(r["board_outcome"] for r in chosen)
          == ["not_occurred"] * 2 + ["occurred"] * 2 + ["unresolvable"] * 2, str(chosen))
    check("at most already_public rows with already_public set per outcome",
          all(sum(1 for r in chosen if r["board_outcome"] == o and r["board_already_public"]) <= 1
              for o in ("occurred", "not_occurred", "unresolvable")), str(chosen))
    check("an already_public row is taken first when one exists", all(any(
        r["board_outcome"] == o and r["board_already_public"] for r in chosen)
        for o in ("occurred", "not_occurred", "unresolvable")), str(chosen))
    check("at most per_leader rows of one leader", max(
        sum(1 for r in chosen if r["leader_slug"] == s) for s in {r["leader_slug"] for r in chosen}) <= 1, str(chosen))
    key = {r["prediction_id"]: hashlib.sha256(f"T:{r['prediction_id']}".encode()).hexdigest() for r in chosen}
    check("each row records its order key", all(r["order_key"] == key[r["prediction_id"]] for r in chosen), "")
    again = C.select(list(reversed(scores)), [r1, r2], exclude={"adj"}, per_outcome=2, already_public=1,
                     per_leader=1, salt="T")
    check("the rule, not the input order, decides the rows", [r["prediction_id"] for r in again["rows"]] == ids,
          f"{ids} vs {[r['prediction_id'] for r in again['rows']]}")
    other = C.select(scores, [r1, r2], exclude={"adj"}, per_outcome=2, already_public=1, per_leader=1, salt="U")
    check("another salt draws another sample from the same pool", [r["prediction_id"] for r in other["rows"]] != ids, "")
    check("the pool is counted by stratum", sel["pool"] == {"occurred/already_public": 2, "occurred/none": 4,
          "not_occurred/already_public": 2, "not_occurred/none": 4, "unresolvable/already_public": 2,
          "unresolvable/none": 4}, str(sel["pool"]))
    short = C.select(scores, [r1, r2], exclude={"adj"}, per_outcome=9, already_public=1, per_leader=9, salt="T")
    # already_public is a cap: the second already_public row of an outcome is not used to fill it.
    check("a stratum the pool cannot fill is reported short, never padded",
          short["short"] == {"occurred": 4, "not_occurred": 4, "unresolvable": 4}, str(short["short"]))
    check("the rule is written into the selection in words", "sha256" in sel["rule"] and "per_leader" in sel["rule"],
          sel["rule"])

    # ---- report -------------------------------------------------------------
    sel2 = C.select(scores, [r1, r2], exclude={"adj"}, per_outcome=2, already_public=1, per_leader=2, salt="T",
                    root=td)
    rows = sel2["rows"]
    a_run, g_run = td / "astra-new", td / "gemini"
    flip = rows[0]["prediction_id"]
    for r in rows:
        pid, slug, out = r["prediction_id"], r["leader_slug"], r["board_outcome"]
        sidecar(a_run, pid, slug, out, ap=AP if r["board_already_public"] else None,
                release="resolution-2026-10-19", prompt=f"P{pid}")
        g_out = ("not_occurred" if out == "occurred" else "occurred") if pid == flip else out
        if pid != rows[-1]["prediction_id"]:                                   # Gemini failed on the last row
            sidecar(g_run, pid, slug, g_out, ap=None, harness="gemini", release="resolution-2026-10-19",
                    prompt=f"P{pid}", sources=[{"what_it_shows": "gem src", "where": "https://g.com", "date": None}])
    # One row each arm saw the project's own site in: Astra in its raw answer, Gemini in its transcript count.
    exp_a, exp_g = rows[1]["prediction_id"], rows[2]["prediction_id"]
    raw = a_run / "_raw" / "resolve" / rows[1]["leader_slug"] / f"{exp_a}.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({"stdout": '{"type": "open_page", "url": "https://VERBATIM-PREDICTIONS.TONYGWU.COM/p"}'}))
    gf = R.sidecar_path(g_run, "resolve", rows[2]["leader_slug"], exp_g)
    gobj = json.loads(gf.read_text())
    gobj["telemetry"]["own_site_mentions"] = 2
    gf.write_text(json.dumps(gobj))
    rep = C.report(sel2, a_run, g_run, root=td)
    n = len(rows)
    by = {x["prediction_id"]: x for x in rep["rows"]}
    check("every selected row appears once in the report", sorted(by) == sorted(r["prediction_id"] for r in rows), "")
    check("a row an arm did not answer is marked missing, never dropped", by[rows[-1]["prediction_id"]]["gemini"]
          is None, str(by[rows[-1]["prediction_id"]]))
    g_vs_a = rep["agreement"]["gemini_vs_astra_new"]["outcome"]
    check("outcome agreement counts only rows both arms answered",
          g_vs_a == {"agree": n - 2, "of": n - 1}, str(g_vs_a))
    ap_presence = rep["agreement"]["gemini_vs_astra_new"]["already_public_set"]
    n_ap = sum(1 for r in rows[:-1] if r["board_already_public"])
    check("already_public agreement compares whether each arm set it", ap_presence == {"agree": n - 1 - n_ap,
          "of": n - 1}, str(ap_presence))
    check("Astra's re-run is compared with the board's Astra too",
          rep["agreement"]["astra_new_vs_board"]["outcome"] == {"agree": n, "of": n}, str(rep["agreement"]))
    dis = [d for d in rep["disagreements"] if d["prediction_id"] == flip]
    check("a disagreement carries each arm's sources and reasoning", dis and dis[0]["gemini"]["sources"][0]["where"]
          == "https://g.com" and dis[0]["astra_new"]["sources"] and dis[0]["gemini"]["reasoning"], str(dis))
    check("a pair whose prompts differ is flagged", rep["prompt_mismatch"] == [], str(rep["prompt_mismatch"]))
    md = C.render_markdown(rep)
    check("the markdown table has one line per row", sum(1 for ln in md.splitlines() if ln.startswith("| ")
          and any(r["prediction_id"] in ln for r in rows)) == n, md[:500])
    by = {x["prediction_id"]: x for x in rep["rows"]}
    check("Astra's exposure is read from its raw answer", by[exp_a]["astra_new"]["own_site_mentions"] == 1,
          str(by[exp_a]["astra_new"]))
    check("Gemini's exposure is read from its telemetry", by[exp_g]["gemini"]["own_site_mentions"] == 2,
          str(by[exp_g]["gemini"]))
    un = rep["agreement_without_own_site"]["gemini_vs_astra_new"]["outcome"]
    check("agreement is also given without the rows either new arm saw the site in", un["of"] == n - 3, str(un))
    check("and those rows are named", sorted(rep["own_site_rows"]) == sorted([exp_a, exp_g]), str(rep["own_site_rows"]))
    msg = raises(lambda: C.report(sel2, a_run, a_run, root=td))
    check("the two arms must be two different runs", msg is not None, str(msg))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
