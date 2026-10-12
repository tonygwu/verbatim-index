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
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates  # noqa: E402

SKIP_PARTS = {"_obsolete", "_raw", "_provenance"}
DELTA_SEARCH = 5.0      # plan P10, G-search: points of search rate, left minus right
DELTA_COVERAGE = 5.0    # plan P10, G-coverage: points of loss rate between lean groups
DISCLOSURE_AT = 0.90    # plan P10: identity rate at which the site must disclose
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


def name_tokens(person: dict) -> list[str]:
    """What counts as naming the person: full name, a surname of 4+ letters, a handle."""
    name = person["name"].lower()
    toks = [name] + [h.lower() for h in person.get("handles") or []]
    parts = re.findall(r"[a-z']+", name)
    if parts and len(parts[-1]) >= 4:
        toks.append(parts[-1])
    return toks


def names_subject(text: str, person: dict) -> bool:
    low = (text or "").lower()
    return any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low) for t in name_tokens(person))


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


def identity(grades: list[dict], people: dict[str, dict], judges: list[str]) -> dict:
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
    return {"grades": tot, "confident_rate": round(conf / tot, 3) if tot else None, "correct_rate": rate,
            "disclosure_required": rate is not None and rate >= DISCLOSURE_AT, "by_judge": by_judge,
            "rule": "correct = identity_confident AND the guess names the subject (full name, surname of 4+ "
                    "letters, or a roster handle)"}


def searched(g: dict) -> bool:
    return bool((g.get("telemetry") or {}).get("web_search_queries"))


def search_gate(grades: list[dict], people: dict, leans: dict, judges: list[str]) -> dict:
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
    venue = {(t["leader_slug"], t["source_id"]): t.get("venue_type") for t in results.get("transcripts") or []}
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
                    "lost when no usable run-0 grade exists for it"}


def venue_support(results: dict) -> dict:
    d = results.get("diagnostics") or {}
    if "venue_adjustment_applied" not in d:
        raise RuntimeError("results.json diagnostics carry no venue_adjustment_applied")
    out = {"applied": d["venue_adjustment_applied"], "reasons": d.get("venue_support_reasons") or [],
           "venue_counts": d.get("venue_counts") or {}}
    lovo = d.get("venue_leave_one_out")
    if lovo:
        out["leave_one_out"] = {v: {k: e[k] for k in ("people_still_ranked", "people_changing_rank",
                                                       "rank_correlation", "max_abs_shift")}
                                for v, e in lovo["by_venue"].items()}
    return out


def report(data: Path, leans: dict[str, str]) -> dict:
    data = Path(data)
    results = json.loads((data / "results.json").read_text())
    models = (results.get("diagnostics") or {}).get("judge_models")
    if not models:
        raise RuntimeError("results.json names no judge_models; the published panel cannot be derived")
    judges = sorted(models)
    people = roster(data)
    grades = [g for g in load_grades(data) if g.get("leader_slug") in people]
    scored = {g["leader_slug"] for g in grades}
    groups = lean_groups(leans, scored)
    return {
        "published_judges": judges,
        "lean_groups": {k: len(v) for k, v in sorted(groups.items())},
        "gates": {
            "fable_tool_calls": fable_tool_calls(grades),
            "G-search": search_gate(grades, people, leans, judges),
            "G-coverage": coverage_gate(data, grades, results, leans, judges),
            "venue_support": venue_support(results),
        },
        "identity": identity(grades, people, judges),
        "bootstrap": {"resamples": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED, "interval": "90%",
                      "unit": "person, resampled with replacement inside each lean group"},
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
    print(f"wrote {out}: tool calls {g['fable_tool_calls']['verdict']}, G-search {g['G-search']['verdict']}, "
          f"G-coverage {g['G-coverage']['verdict']}, identity correct {rep['identity']['correct_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
