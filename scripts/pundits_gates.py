#!/usr/bin/env python3
"""P10 full-corpus validation for the pundits study: one report, a verdict per gate.

docs/PUNDITS-PLAN.md, P10. This reads a pundits data checkout and the private lean
labels, spends no quota, and writes one JSON report. P11 step 1 renders
docs/PUNDITS.md from it. Gates in this file so far:

  fable_tool_calls  Fable's tools are removed, so every grade must record 0
                    transcript tool calls. Nonzero is FAIL, naming the grade; a
                    grade with no count is INCONCLUSIVE, never PASS.
  identity          not a gate: the blinded identity rate, measured two ways.
                    `confident` counts identity_confident, which is what
                    aggregate.py's blinding_leakage_rate counts. `correct` also
                    requires the guess to name the subject (full name, surname of
                    4+ letters, or a roster handle). At 90% correct or more the site
                    must say blinded means name-removed, not anonymous.
  G-search          search rate by judge, mode and lean group, queries that name the
                    blinded subject, and per judge an equivalence test on left minus
                    right search rate (Delta 5 points, cluster bootstrap by person).
                    Not PASS is a disclosed limit; it does not block publication.
  G-coverage        loss tables: scheduled run-0 recordings that did not reach the
                    board, by person, lean group and venue, and lost cells by judge
                    and mode. Equivalence on every pair of lean groups' loss rates,
                    Delta 5 points. Cells of a judge that is not published (Astra,
                    dropped 2026-09-16) are reported as excluded, never as loss.
  venue_support     the plan P5 support rule's result, carried from results.json,
                    with the leave-one-venue-out summary when present.
  G-judge-lean      per judge, on complete blinded run-0 transcripts in calibrated
                    overall points: its score minus the mean of the other judges',
                    left minus right. Delta 3, cluster bootstrap by person. A relative
                    test: a bias every judge shares is invisible, and with two judges
                    the two estimates are equal and opposite.
  G-halo-lean       mean person halo, left minus right: the panel's calibrated halo
                    and each judge's raw paired halo. Delta 3.
  G-drift           drift-anchor re-grades: per judge and mode, the latest run minus
                    the earliest, in raw overall points, averaged over anchors.
                    Delta 3. With no anchors it is INCONCLUSIVE and says it did not run.

PRIVACY. Lean labels are private. The report holds lean only as group keys with
group-level counts and rates; no object in it pairs a person with a lean. The
report is refused inside the data checkout, and it belongs in a scratch or
private location until P11 publishes the group figures.

  .venv/bin/python scripts/pundits_gates.py --data data-pundits \\
      --lean-labels data-pundits/private/lean_labels.json --out /tmp/p10-gates.json

Proof: scripts/test_pundits_gates.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates  # noqa: E402
from aggregate import judge_searched, names_subject  # noqa: E402  (one definition for the page and this report)

SKIP_PARTS = {"_obsolete", "_raw", "_provenance"}
DELTA_SEARCH = 5.0      # plan P10, G-search: points of search rate, left minus right
DELTA_COVERAGE = 5.0    # plan P10, G-coverage: points of loss rate between lean groups
DISCLOSURE_AT = 0.90    # plan P10: identity rate at which the site must disclose
DELTA_JUDGE_LEAN = 3.0  # plan P10, G-judge-lean: overall points
DELTA_HALO_LEAN = 3.0   # plan P10, G-halo-lean: overall points
DELTA_DRIFT = 3.0       # plan P10, G-drift: overall points
BOOTSTRAP_N = 20000
BOOTSTRAP_SEED = 20260914


def load_grades(data: Path) -> list[dict]:
    """Every live grade record: grades/<judge>/<slug>/*.json, skipping moved-aside and raw files."""
    out = []
    for p in sorted((data / "grades").rglob("*.json")):
        if SKIP_PARTS & set(p.relative_to(data / "grades").parts):
            continue
        rec = json.loads(p.read_text())
        rec["_path"] = str(p.relative_to(data))
        out.append(rec)
    if not out:
        raise RuntimeError(f"no grade records under {data / 'grades'}")
    return out


def usable(rec: dict) -> bool:
    return not rec.get("validation_errors") and bool((rec.get("grade") or {}).get("dimensions"))


def roster(data: Path) -> dict[str, dict]:
    raw = json.loads((data / "roster/final.json").read_text())
    people = raw["roster"] if isinstance(raw, dict) else raw
    return {p["slug"]: p for p in people}


def scheduled_cells(data: Path) -> set[tuple[str, str, str, str]]:
    """Run-0 (slug, source_id, judge, mode) cells across every schedule manifest."""
    cells = set()
    files = sorted((data / "logs/schedule").glob("*.jsonl"))
    if not files:
        raise RuntimeError(f"no schedule manifests under {data / 'logs/schedule'}")
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("run", 0) == 0:
                cells.add((r["slug"], r["source_id"], r["judge"], r["mode"]))
    return cells


def verdict_for(lo: float, hi: float, delta: float) -> str:
    return gates.equivalence(lo, hi, delta)


def lean_groups(leans: dict[str, str], slugs) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for s in sorted(slugs):
        if s not in leans:
            raise RuntimeError(f"person {s} has no lean label; every scored person needs one")
        groups[leans[s]].append(s)
    return dict(groups)


def fable_tool_calls(grades: list[dict]) -> dict:
    fable = [g for g in grades if g.get("judge") == "fable"]
    nonzero = [{"transcript": g.get("transcript_id"), "mode": g.get("mode"),
                "tool_calls": (g.get("telemetry") or {}).get("transcript_tool_calls")}
               for g in fable if ((g.get("telemetry") or {}).get("transcript_tool_calls") or 0) > 0]
    missing = [g.get("transcript_id") for g in fable
               if not isinstance((g.get("telemetry") or {}).get("transcript_tool_calls"), int)]
    verdict = "FAIL" if nonzero else ("INCONCLUSIVE" if missing or not fable else "PASS")
    return {"verdict": verdict, "grades": len(fable), "nonzero": nonzero, "count_missing": missing,
            "rule": "Fable's tools are removed; any nonzero transcript tool call means the harness changed"}


def identity(grades: list[dict], people: dict[str, dict], judges: list[str], results: dict) -> dict:
    """Per grade, by judge, and per board recording. Run-0 grades only: a drift
    anchor's re-grade is the same recording again. The disclosure verdict reads the
    per-recording rate, which is what the page prints (aggregate's
    blinding_correct_rate): a board recording counts when any judge named the
    speaker."""
    grades = [g for g in grades if (g.get("run") or 0) == 0]
    by_judge = {}
    tot = conf = corr = 0
    for j in judges:
        rows = [g for g in grades if g.get("judge") == j and g.get("mode") == "blinded" and usable(g)]
        c = sum(1 for g in rows if g["grade"].get("identity_confident"))
        k = sum(1 for g in rows if g["grade"].get("identity_confident")
                and names_subject(g["grade"].get("identity_guess"), people[g["leader_slug"]]))
        by_judge[j] = {"grades": len(rows), "confident_rate": round(c / len(rows), 3) if rows else None,
                       "correct_rate": round(k / len(rows), 3) if rows else None}
        tot, conf, corr = tot + len(rows), conf + c, corr + k
    rate = round(corr / tot, 3) if tot else None
    board = {(t["leader_slug"], t["source_id"]) for t in results.get("transcripts") or [] if t.get("mode") == "blinded"}
    named = {(g["leader_slug"], g["source_id"]) for g in grades
             if g.get("judge") in judges and g.get("mode") == "blinded" and usable(g)
             and g["grade"].get("identity_confident")
             and names_subject(g["grade"].get("identity_guess"), people[g["leader_slug"]])}
    board_rate = round(len(board & named) / len(board), 3) if board else None
    return {"grades": tot, "confident_rate": round(conf / tot, 3) if tot else None, "correct_rate": rate,
            "board_recordings": len(board), "board_correct_rate": board_rate,
            "disclosure_required": board_rate is not None and board_rate >= DISCLOSURE_AT, "by_judge": by_judge,
            "rule": "correct = identity_confident AND the guess names the subject (full name, surname of 4+ "
                    "letters, or a roster handle)"}


def searched(g: dict) -> bool:
    return judge_searched(g)


def search_gate(grades: list[dict], people: dict, leans: dict, judges: list[str]) -> dict:
    # Run-0 grades only: a drift anchor's re-grade is the same recording again.
    grades = [g for g in grades if (g.get("run") or 0) == 0]
    out, naming = {}, 0
    for g in grades:
        if g.get("judge") in judges and g.get("mode") == "blinded" and usable(g):
            naming += sum(1 for q in (g.get("telemetry") or {}).get("web_search_queries") or []
                          if names_subject(q, people[g["leader_slug"]]))
    for j in judges:
        rows = [g for g in grades if g.get("judge") == j and usable(g)]
        per_person: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for g in rows:
            per_person[g["leader_slug"]][0] += searched(g)
            per_person[g["leader_slug"]][1] += 1
        groups = lean_groups(leans, per_person)
        by_mode = {}
        for mode in ("blinded", "open"):
            m = [g for g in rows if g.get("mode") == mode]
            by_mode[mode] = {"grades": len(m), "searched": sum(map(searched, m))}
        by_lean = {lean: {"people": len(s), "grades": sum(per_person[x][1] for x in s),
                          "searched": sum(per_person[x][0] for x in s)} for lean, s in sorted(groups.items())}
        entry = {"grades": len(rows), "searched": sum(map(searched, rows)), "by_mode": by_mode, "by_lean": by_lean}
        if "left" in groups and "right" in groups:
            a = [tuple(per_person[x]) for x in groups["left"]]
            b = [tuple(per_person[x]) for x in groups["right"]]
            pa = sum(e for e, _ in a) / sum(u for _, u in a)
            pb = sum(e for e, _ in b) / sum(u for _, u in b)
            lo, hi = gates.cluster_rate_diff_ci90(a, b, BOOTSTRAP_N, BOOTSTRAP_SEED)
            entry.update({"left_minus_right_points": round(100 * (pa - pb), 1),
                          "ci90": [round(lo, 2), round(hi, 2)], "verdict": verdict_for(lo, hi, DELTA_SEARCH)})
        else:
            entry["verdict"] = "INCONCLUSIVE"
            entry["why"] = "needs both a left and a right group"
        out[j] = entry
    verdicts = [e["verdict"] for e in out.values()]
    overall = "FAIL" if "FAIL" in verdicts else ("PASS" if verdicts and all(v == "PASS" for v in verdicts)
                                               else "INCONCLUSIVE")
    return {"verdict": overall, "delta_points": DELTA_SEARCH, "by_judge": out, "queries_naming_subject": naming,
            "rule": "per judge, left minus right search rate; 90% cluster bootstrap by person; not PASS is a "
                    "disclosed limit, not a block"}


def coverage_gate(data: Path, grades: list[dict], results: dict, leans: dict, judges: list[str]) -> dict:
    cells = scheduled_cells(data)
    excluded: dict[str, int] = defaultdict(int)
    for c in cells:
        if c[2] not in judges:
            excluded[c[2]] += 1
    cells = {c for c in cells if c[2] in judges}
    ok = {(g["leader_slug"], g["source_id"], g["judge"], g["mode"]) for g in grades if usable(g) and g.get("run", 0) == 0}
    by_cell: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for c in cells:
        by_cell[f"{c[2]}|{c[3]}"][0] += c not in ok
        by_cell[f"{c[2]}|{c[3]}"][1] += 1
    recordings = sorted({(c[0], c[1]) for c in cells})
    on_board = {(t["leader_slug"], t["source_id"]) for t in results.get("transcripts") or [] if t.get("mode") == "blinded"}
    # The blinded row's venue; the open row can resolve differently. A 1-1 judge tie
    # (venue_agreed False) carries an alphabetically chosen label, so it is "format disputed".
    venue = {(t["leader_slug"], t["source_id"]): ("format disputed" if t.get("venue_type") and t.get("venue_agreed")
                                                  is False else t.get("venue_type"))
             for t in results.get("transcripts") or [] if t.get("mode") == "blinded"}
    per_person: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_venue: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in recordings:
        lost = r not in on_board
        per_person[r[0]][0] += lost
        per_person[r[0]][1] += 1
        v = venue.get(r) or "unknown (never reached the board)"
        per_venue[v][0] += lost
        per_venue[v][1] += 1
    groups = lean_groups(leans, per_person)
    by_lean = {lean: {"people": len(s), "scheduled": sum(per_person[x][1] for x in s),
                      "lost": sum(per_person[x][0] for x in s)} for lean, s in sorted(groups.items())}
    for v in by_lean.values():
        v["loss_rate"] = round(v["lost"] / v["scheduled"], 3)
    pairs = {}
    for g1, g2 in combinations(sorted(groups), 2):
        a = [tuple(per_person[x]) for x in groups[g1]]
        b = [tuple(per_person[x]) for x in groups[g2]]
        lo, hi = gates.cluster_rate_diff_ci90(a, b, BOOTSTRAP_N, BOOTSTRAP_SEED)
        pairs[f"{g1} minus {g2}"] = {"points": round(100 * (by_lean[g1]["loss_rate"] - by_lean[g2]["loss_rate"]), 1),
                                     "ci90": [round(lo, 2), round(hi, 2)],
                                     "verdict": verdict_for(lo, hi, DELTA_COVERAGE)}
    verdicts = [p["verdict"] for p in pairs.values()]
    overall = ("INCONCLUSIVE" if not verdicts else "FAIL" if "FAIL" in verdicts
               else "PASS" if all(v == "PASS" for v in verdicts) else "INCONCLUSIVE")
    return {"verdict": overall, "delta_points": DELTA_COVERAGE,
            "by_person": {s: {"scheduled": u, "lost": e} for s, (e, u) in sorted(per_person.items())},
            "by_lean": by_lean, "lean_pairs": pairs,
            "by_venue": {v: {"scheduled": u, "lost": e} for v, (e, u) in sorted(per_venue.items())},
            "cells_by_judge_mode": {k: {"scheduled": u, "lost": e} for k, (e, u) in sorted(by_cell.items())},
            "excluded_judges": dict(sorted(excluded.items())),
            "rule": "a scheduled run-0 recording is lost when it has no blinded row in results.json; a cell is "
                    "lost when no usable run-0 grade exists for it. A recording can be lost with every cell graded: "
                    "aggregate.py drops it for an unsupported dimension or an incomplete panel "
                    "(results.json partial_panel_detail names which)"}


def combine(verdicts: list[str]) -> str:
    if not verdicts:
        return "INCONCLUSIVE"
    if "FAIL" in verdicts:
        return "FAIL"
    return "PASS" if all(v == "PASS" for v in verdicts) else "INCONCLUSIVE"


def weights_of(results: dict) -> dict[str, float]:
    w = (results.get("diagnostics") or {}).get("weights")
    if not w:
        raise RuntimeError("results.json diagnostics carry no weights")
    return w


def raw_overall(g: dict, weights: dict[str, float]) -> float:
    return sum(w * g["grade"]["dimensions"][d]["score"] for d, w in weights.items())


def judge_lean_gate(grades: list[dict], results: dict, leans: dict, judges: list[str]) -> dict:
    import aggregate as A
    weights = weights_of(results)
    params = {tuple(k.split("|")): v for k, v in
              ((results.get("diagnostics") or {}).get("calibration_params") or {}).items()}

    def cal_overall(g: dict) -> float:
        return sum(w * A.apply_calibration(g["grade"]["dimensions"][d]["score"],
                                           (g["judge"], A.served_model(g), "shared", d), params)
                   for d, w in weights.items())

    complete = {(t["leader_slug"], t["source_id"]) for t in results.get("transcripts") or []
                if t.get("mode") == "blinded"}
    scores: dict[tuple, dict] = defaultdict(dict)
    for g in grades:
        key = (g["leader_slug"], g["source_id"])
        if (g.get("mode") == "blinded" and g.get("run", 0) == 0 and g.get("judge") in judges and usable(g)
                and key in complete):
            scores[key][g["judge"]] = cal_overall(g)
    full = {k: v for k, v in scores.items() if set(v) == set(judges)}
    groups = lean_groups(leans, {k[0] for k in full})
    by_judge = {}
    for j in judges:
        per_person: dict[str, list[float]] = defaultdict(list)
        for (slug, _), s in full.items():
            others = [s[k] for k in judges if k != j]
            per_person[slug].append(s[j] - sum(others) / len(others))
        entry = {"by_lean_mean": {lean: round(sum(sum(per_person[x]) for x in ppl)
                                              / sum(len(per_person[x]) for x in ppl), 2)
                                  for lean, ppl in sorted(groups.items())}}
        if "left" in groups and "right" in groups:
            a = [per_person[x] for x in groups["left"]]
            b = [per_person[x] for x in groups["right"]]
            est = sum(map(sum, a)) / sum(map(len, a)) - sum(map(sum, b)) / sum(map(len, b))
            lo, hi = gates.cluster_mean_diff_ci90(a, b, BOOTSTRAP_N, BOOTSTRAP_SEED)
            entry.update({"estimate": round(est, 2), "ci90": [round(lo, 2), round(hi, 2)],
                          "verdict": gates.equivalence(lo, hi, DELTA_JUDGE_LEAN)})
        else:
            entry.update({"verdict": "INCONCLUSIVE", "why": "needs both a left and a right group"})
        by_judge[j] = entry
    limit = ("A relative test: a bias every judge shares is invisible to it. "
             + ("With two judges each judge's gap is measured against one other judge, so the two "
                "estimates are equal and opposite." if len(judges) == 2 else ""))
    return {"verdict": combine([e["verdict"] for e in by_judge.values()]), "delta_points": DELTA_JUDGE_LEAN,
            "transcripts": len(full), "by_judge": by_judge, "limit": limit.strip(),
            "rule": "score = calibrated blinded run-0 overall; per transcript, a judge's score minus the mean of "
                    "the other judges'; left minus right of its mean; 90% cluster bootstrap by person"}


def halo_lean_gate(results: dict, leans: dict, judges: list[str]) -> dict:
    people = [p for p in (results.get("leaders") or []) + (results.get("unranked") or [])
              if isinstance((p.get("halo") or {}).get("overall"), (int, float))]
    groups = lean_groups(leans, {p["slug"] for p in people})
    by_slug = {p["slug"]: p["halo"] for p in people}

    def test(value_of) -> dict:
        if "left" not in groups or "right" not in groups:
            return {"verdict": "INCONCLUSIVE", "why": "needs both a left and a right group"}
        a = [[value_of(by_slug[x])] for x in groups["left"] if value_of(by_slug[x]) is not None]
        b = [[value_of(by_slug[x])] for x in groups["right"] if value_of(by_slug[x]) is not None]
        if not a or not b:
            return {"verdict": "INCONCLUSIVE", "why": "a lean group has no halo"}
        est = sum(v[0] for v in a) / len(a) - sum(v[0] for v in b) / len(b)
        lo, hi = gates.cluster_mean_diff_ci90(a, b, BOOTSTRAP_N, BOOTSTRAP_SEED)
        return {"estimate": round(est, 2), "ci90": [round(lo, 2), round(hi, 2)], "people": [len(a), len(b)],
                "verdict": gates.equivalence(lo, hi, DELTA_HALO_LEAN)}

    panel = test(lambda h: h.get("overall"))
    per_judge = {j: test(lambda h, j=j: (h.get("by_judge_raw") or {}).get(j)) for j in judges}
    return {"verdict": combine([panel["verdict"], *[e["verdict"] for e in per_judge.values()]]),
            "delta_points": DELTA_HALO_LEAN, "panel": panel, "by_judge_raw": per_judge,
            "rule": "mean person halo (open minus blinded), left minus right; panel calibrated, judges raw"}


def drift_gate(data: Path, grades: list[dict], results: dict, judges: list[str]) -> dict:
    anchors, expected = set(), set()
    for f in sorted((data / "logs/schedule").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("run", 0) >= 1 and r["judge"] in judges:
                    anchors.add((r["slug"], r["source_id"]))
                    expected.add(f"{r['judge']}|{r['mode']}")
    if not anchors:
        return {"verdict": "INCONCLUSIVE", "ran": False, "delta_points": DELTA_DRIFT,
                "why": "no drift anchors were scheduled (plan P5: 6 fixed transcripts re-graded once per "
                       "block group); drift is unmeasured and must be reported as a limit"}
    weights = weights_of(results)
    runs: dict[tuple, dict[int, float]] = defaultdict(dict)
    for g in grades:
        if (g["leader_slug"], g["source_id"]) in anchors and g.get("judge") in judges and usable(g):
            runs[(g["judge"], g["mode"], g["leader_slug"], g["source_id"])][g.get("run", 0)] = raw_overall(g, weights)
    cells: dict[str, list[float]] = defaultdict(list)
    for (judge, mode, *_), by_run in runs.items():
        if len(by_run) >= 2:
            cells[f"{judge}|{mode}"].append(by_run[max(by_run)] - by_run[min(by_run)])
    out = {}
    for cell, diffs in sorted(cells.items()):
        lo, hi = gates.mean_ci90(diffs, BOOTSTRAP_N, BOOTSTRAP_SEED)
        out[cell] = {"anchors": len(diffs), "estimate": round(sum(diffs) / len(diffs), 2),
                     "ci90": [round(lo, 2), round(hi, 2)], "verdict": gates.equivalence(lo, hi, DELTA_DRIFT)}
    if not out:
        return {"verdict": "INCONCLUSIVE", "ran": False, "delta_points": DELTA_DRIFT,
                "anchors_scheduled": len(anchors), "by_judge_mode": {},
                "why": f"{len(anchors)} drift anchors are scheduled but none has been re-graded yet; drift is "
                       "unmeasured and must be reported as a limit"}
    # The plan tests drift per judge and mode: a scheduled cell with no re-grade
    # is unmeasured, so the gate cannot pass on the cells that happen to exist.
    missing = sorted(expected - set(out))
    verdicts = [e["verdict"] for e in out.values()] + ["INCONCLUSIVE"] * bool(missing)
    return {"verdict": combine(verdicts), "ran": True, "delta_points": DELTA_DRIFT,
            "anchors_scheduled": len(anchors), "by_judge_mode": out, "missing_cells": missing,
            "rule": "per judge and mode, raw overall of the latest run minus the earliest, averaged over anchors; "
                    "bootstrap over anchors"}


def venue_support(results: dict) -> dict:
    d = results.get("diagnostics") or {}
    if "venue_adjustment_applied" not in d:
        raise RuntimeError("results.json diagnostics carry no venue_adjustment_applied")
    # Plan P5 reports the leave-one-venue-out "in both cases", so its absence is a
    # stale results.json, not an empty section.
    if "venue_leave_one_out" not in d:
        raise RuntimeError("results.json diagnostics carry no venue_leave_one_out; re-aggregate with the current code")
    # Counted from the board's blinded rows rather than diagnostics.venue_counts, which
    # files a 1-1 judge tie under its alphabetically chosen label.
    counts: dict[str, int] = defaultdict(int)
    for t in results.get("transcripts") or []:
        if t.get("mode") == "blinded":
            counts["format disputed" if t.get("venue_type") and t.get("venue_agreed") is False
                   else t.get("venue_type") or "format not recorded"] += 1
    out = {"applied": d["venue_adjustment_applied"], "reasons": d.get("venue_support_reasons") or [],
           "venue_counts": dict(sorted(counts.items()))}
    out["leave_one_out"] = {v: {k: e[k] for k in ("people_still_ranked", "people_changing_rank",
                                                   "rank_correlation", "max_abs_shift")}
                            for v, e in d["venue_leave_one_out"]["by_venue"].items()}
    return out


MIN_CLUSTERS = 10  # below this many people in a lean group, say the interval is too narrow


def few_clusters(groups: dict[str, list[str]]) -> str | None:
    """A warning when any lean group is too small for a percentile cluster bootstrap.

    With a handful of people per group the bootstrap distribution has few distinct
    values and understates the spread, so a PASS there is weaker than it looks.
    The threshold is a rule of thumb, stated here rather than tuned."""
    small = {k: len(v) for k, v in groups.items() if len(v) < MIN_CLUSTERS}
    if not small:
        return None
    return (f"lean groups with fewer than {MIN_CLUSTERS} people ({', '.join(f'{k} {n}' for k, n in sorted(small.items()))}):"
            f" a percentile cluster bootstrap is too narrow with so few clusters, so treat its interval as optimistic")


def report(data: Path, leans: dict[str, str]) -> dict:
    data = Path(data)
    results = json.loads((data / "results.json").read_text())
    models = (results.get("diagnostics") or {}).get("judge_models")
    if not models:
        raise RuntimeError("results.json names no judge_models; the published panel cannot be derived")
    judges = sorted(models)
    people = roster(data)
    on_disk = load_grades(data)
    # The gates read grades from disk and results.json separately, so the two must
    # describe one corpus: aggregate.py records how many grade files it read.
    read_n = (results.get("diagnostics") or {}).get("grade_files_read")
    if read_n != len(on_disk):
        raise RuntimeError(f"results.json was built from grade_files_read={read_n} grade files, and {len(on_disk)} "
                           f"are on disk ({len(on_disk) - (read_n or 0)} newer); re-aggregate first")
    grades = [g for g in on_disk if g.get("leader_slug") in people]
    scored = {g["leader_slug"] for g in grades}
    groups = lean_groups(leans, scored)
    gate = {
        "fable_tool_calls": fable_tool_calls(grades),
        "G-search": search_gate(grades, people, leans, judges),
        "G-coverage": coverage_gate(data, grades, results, leans, judges),
        "venue_support": venue_support(results),
        "G-judge-lean": judge_lean_gate(grades, results, leans, judges),
        "G-halo-lean": halo_lean_gate(results, leans, judges),
        "G-drift": drift_gate(data, grades, results, judges),
    }
    warn = few_clusters(groups)
    if warn:
        for k in ("G-search", "G-coverage", "G-judge-lean", "G-halo-lean"):
            gate[k]["few_clusters"] = warn
    return {
        "published_judges": judges,
        "lean_groups": {k: len(v) for k, v in sorted(groups.items())},
        "min_clusters": MIN_CLUSTERS,
        "gates": gate,
        "identity": identity(grades, people, judges, results),
        "bootstrap": {"resamples": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED, "interval": "90%",
                      "unit": "person, resampled with replacement inside each lean group, then recordings within each person"},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, required=True, help="a pundits data checkout")
    ap.add_argument("--lean-labels", type=Path, required=True, help="the private {slug: lean} file")
    ap.add_argument("--out", type=Path, required=True, help="where the report goes; never inside --data")
    args = ap.parse_args()
    data, out = args.data.resolve(), args.out.resolve()
    if out == data or data in out.parents:
        print(f"REFUSING: {out} is inside the data checkout {data}; write the report to scratch", file=sys.stderr)
        return 1
    try:
        rep = report(data, json.loads(args.lean_labels.read_text()))
    except (RuntimeError, KeyError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1
    out.write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    g = rep["gates"]
    print(f"wrote {out}: " + ", ".join(f"{k} {v['verdict']}" for k, v in g.items() if "verdict" in v)
          + f", identity correct {rep['identity']['correct_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
