#!/usr/bin/env python3
"""Render the P10 gate report as Markdown: P11 step 1, docs/PUNDITS.md.

docs/PUNDITS-PLAN.md, P11: "Write docs/PUNDITS.md with every gate result: estimate,
interval, n, and exclusions per judge/mode." Every figure comes from the JSON that
scripts/pundits_gates.py writes; nothing is typed, so the document cannot drift
from the report it claims to show.

--withhold-lean prints every verdict but no lean-split estimate, interval or table.
Lean labels are private, and with few people a lean-split figure next to public
per-person facts (the page publishes each person's halo) can reveal who is in which
group. Until the operator sets a disclosure rule, a document headed for the public
repository is rendered with it.

  .venv/bin/python scripts/pundits_gate_doc.py --report /tmp/p10-gates.json \\
      --data-revision "$(git -C data-pundits rev-parse HEAD)" --out docs/PUNDITS.md --withhold-lean

Proof: scripts/test_pundits_gate_doc.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = ("fable_tool_calls", "G-search", "G-coverage", "G-judge-lean", "G-halo-lean", "G-drift", "venue_support")
WITHHELD = "withheld"


def pct(x) -> str:
    return "&ndash;" if x is None else f"{100 * x:.1f}%"


def signed(x) -> str:
    return "&ndash;" if x is None else f"{x:+.2f}"


def ci(pair) -> str:
    return "&ndash;" if not pair else f"[{pair[0]:+.2f}, {pair[1]:+.2f}]"


def verdict_rows(g: dict, hold: bool) -> list[str]:
    rows = []
    t = g["fable_tool_calls"]
    rows.append(f"| fable_tool_calls | Fable | {t['verdict']} | {len(t['nonzero'])} nonzero, "
                f"{len(t['count_missing'])} missing | &ndash; | {t['grades']} grades | must be 0 |")
    s = g["G-search"]
    for j, e in s["by_judge"].items():
        est = WITHHELD if hold else (signed(e.get("left_minus_right_points")) + " points"
                                     if "left_minus_right_points" in e else "&ndash;")
        rows.append(f"| G-search | {j}, left minus right | {e['verdict']} | {est} | "
                    f"{WITHHELD if hold else ci(e.get('ci90'))} | {e['grades']} grades | &plusmn;{s['delta_points']:g} |")
    c = g["G-coverage"]
    n_rec = sum(p["scheduled"] for p in c["by_person"].values())
    if hold:
        # One row: a verdict per lean PAIR, beside the per-person loss table,
        # would show which group holds a loss.
        rows.append(f"| G-coverage | loss between lean groups | {c['verdict']} | {WITHHELD} | {WITHHELD} | "
                    f"{n_rec} recordings | &plusmn;{c['delta_points']:g} |")
    for pair, e in ({} if hold else c["lean_pairs"]).items():
        rows.append(f"| G-coverage | loss, {pair} | {e['verdict']} | "
                    f"{WITHHELD if hold else signed(e['points']) + ' points'} | {WITHHELD if hold else ci(e['ci90'])} | "
                    f"{n_rec} recordings | &plusmn;{c['delta_points']:g} |")
    jl = g["G-judge-lean"]
    for j, e in jl["by_judge"].items():
        rows.append(f"| G-judge-lean | {j} | {e['verdict']} | {WITHHELD if hold else signed(e.get('estimate'))} | "
                    f"{WITHHELD if hold else ci(e.get('ci90'))} | {jl['transcripts']} transcripts | "
                    f"&plusmn;{jl['delta_points']:g} |")
    hl = g["G-halo-lean"]
    for part, e in [("panel", hl["panel"]), *[(f"{j} (raw)", v) for j, v in hl["by_judge_raw"].items()]]:
        # A group size is a lean-split figure too, so it is withheld with the estimates.
        n = (WITHHELD if hold else f"{e['people'][0]} + {e['people'][1]} people") if e.get("people") else "&ndash;"
        rows.append(f"| G-halo-lean | {part} | {e['verdict']} | {WITHHELD if hold else signed(e.get('estimate'))} | "
                    f"{WITHHELD if hold else ci(e.get('ci90'))} | {n} | &plusmn;{hl['delta_points']:g} |")
    d = g["G-drift"]
    if not d.get("ran"):
        rows.append(f"| G-drift | all | {d['verdict']} | did not run | &ndash; | "
                    f"{d.get('anchors_scheduled', 0)} anchors scheduled | &plusmn;{d['delta_points']:g} |")
    for cell, e in (d.get("by_judge_mode") or {}).items():
        rows.append(f"| G-drift | {cell.replace('|', ' ')} | {e['verdict']} | {signed(e['estimate'])} | "
                    f"{ci(e['ci90'])} | {e['anchors']} anchors | &plusmn;{d['delta_points']:g} |")
    for cell in d.get("missing_cells") or []:
        rows.append(f"| G-drift | {cell.replace('|', ' ')} | INCONCLUSIVE | not re-graded | &ndash; | 0 anchors | "
                    f"&plusmn;{d['delta_points']:g} |")
    return rows


def render(rep: dict, data_revision: str, withhold_lean: bool = False,
           title: str = "Verbatim Pundits: gate results (P10)", note: str | None = None) -> str:
    g = rep.get("gates") or {}
    missing = [k for k in REQUIRED if k not in g]
    if missing or "identity" not in rep:
        raise RuntimeError(f"the gate report is missing {missing or ['identity']}; re-run pundits_gates.py")
    if not re.fullmatch(r"[0-9a-f]{40}", data_revision or ""):
        raise RuntimeError(f"data revision {data_revision!r} is not a full 40-hex SHA")
    out = [f"# {title}", "",
           f"Rendered by `scripts/pundits_gate_doc.py` from the report of `scripts/pundits_gates.py`, at pundits "
           f"data revision `{data_revision[:12]}`. Do not edit it by hand: re-run both scripts. The gates and their "
           f"bounds are defined in [PUNDITS-PLAN.md](PUNDITS-PLAN.md), P10. Published judges: "
           f"{', '.join(rep['published_judges'])}.", ""]
    if note:
        out += [note, ""]
    if withhold_lean:
        out += ["**Lean-split figures are withheld.** Every verdict is printed, but no estimate, interval or "
                "table split by lean. Lean labels are private, and with few people a lean-split figure next to "
                "public per-person facts can reveal who is in which group. They will be printed once the "
                "operator sets a disclosure rule for them.", ""]
    out += ["## Verdicts", "", "| Gate | Part | Verdict | Estimate | 90% interval | n | Bound |",
            "|---|---|---|---|---|---|---|", *verdict_rows(g, withhold_lean), ""]

    i = rep["identity"]
    out += ["## Blinding: how often a judge named the speaker", "",
            "`Confident` counts the judge's own `identity_confident`. `Correct` also requires the guess to name the "
            "subject.", "", "| Judge | Blinded grades | Confident | Correct |", "|---|---|---|---|"]
    out += [f"| {j} | {e['grades']} | {pct(e['confident_rate'])} | {pct(e['correct_rate'])} |"
            for j, e in i["by_judge"].items()]
    out += [f"| all | {i['grades']} | {pct(i['confident_rate'])} | {pct(i['correct_rate'])} |", "",
            ("At 90% correct or more the site must say that blinded means the name is removed, not that the "
             "speaker is anonymous. " + ("That applies." if i["disclosure_required"] else "That does not apply.")),
            ""]

    c = g["G-coverage"]
    out += ["## Losses (G-coverage)", "", c["rule"].capitalize() + ".", "", "### Cells by judge and mode", "",
            "| Judge | Mode | Scheduled | Lost |", "|---|---|---|---|"]
    for k, e in c["cells_by_judge_mode"].items():
        j, m = k.split("|")
        out.append(f"| {j} | {m} | {e['scheduled']} | {e['lost']} |")
    if c["excluded_judges"]:
        out += ["", "Excluded, not lost: " + "; ".join(f"{j}, {n} scheduled cells, is not a published judge"
                                                       for j, n in c["excluded_judges"].items()) + "."]
    out += ["", "### By venue", "", "| Venue | Scheduled | Lost |", "|---|---|---|"]
    out += [f"| {v} | {e['scheduled']} | {e['lost']} |" for v, e in c["by_venue"].items()]
    out += ["", "### By person", "", "| Person | Scheduled | Lost |", "|---|---|---|"]
    out += [f"| {s} | {e['scheduled']} | {e['lost']} |" for s, e in c["by_person"].items()]
    if not withhold_lean:
        out += ["", "### By lean group", "", "| Lean | People | Scheduled | Lost | Loss rate |", "|---|---|---|---|---|"]
        out += [f"| {k} | {e['people']} | {e['scheduled']} | {e['lost']} | {pct(e['loss_rate'])} |"
                for k, e in c["by_lean"].items()]
    out.append("")

    s = g["G-search"]
    out += ["## Search (G-search)", "", f"Queries that name the blinded subject: {s['queries_naming_subject']}.", "",
            "| Judge | Mode | Grades | Searched |", "|---|---|---|---|"]
    for j, e in s["by_judge"].items():
        out += [f"| {j} | {m} | {v['grades']} | {v['searched']} |" for m, v in e["by_mode"].items()]
    out.append("")

    v = g["venue_support"]
    out += ["## Venue support", "", f"Format adjustment applied: {'yes' if v['applied'] else 'no'}."
            + (f" Why not: {'; '.join(v['reasons'])}." if v["reasons"] else ""), "",
            "Recordings by venue: " + ", ".join(f"{k} {n}" for k, n in v["venue_counts"].items()) + "."]
    if v.get("leave_one_out"):
        out += ["", "Leave one venue out, rescoring every ranked person:", "",
                "| Venue dropped | Still ranked | Ranks changed | Spearman | Largest shift |", "|---|---|---|---|---|"]
        out += [f"| {k} | {e['people_still_ranked']} | {e['people_changing_rank']} | "
                f"{'&ndash;' if e['rank_correlation'] is None else e['rank_correlation']} | "
                f"{'&ndash;' if e['max_abs_shift'] is None else e['max_abs_shift']} |"
                for k, e in v["leave_one_out"].items()]
    out.append("")

    limits = [g["G-judge-lean"]["limit"]]
    warn = next((g[k]["few_clusters"] for k in ("G-judge-lean", "G-halo-lean", "G-search", "G-coverage")
                 if g[k].get("few_clusters")), None)
    if warn and withhold_lean:
        # The warning names every group with its size; state the limit without them.
        limits.append(f"Some lean groups have fewer than {rep['min_clusters']} people: a percentile cluster bootstrap "
                      "is too narrow with so few clusters, so treat its intervals as optimistic.")
    elif warn:
        limits.append(warn[0].upper() + warn[1:] + ".")
    if not g["G-drift"].get("ran"):
        limits.append(g["G-drift"]["why"][0].upper() + g["G-drift"]["why"][1:] + ".")
    out += ["## Limits", "", *[f"- {x}" for x in limits], ""]
    b = rep["bootstrap"]
    out += [f"Intervals: {b['interval']}, {b['resamples']} resamples, seed {b['seed']}, unit {b['unit']}.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--data-revision", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--withhold-lean", action="store_true")
    ap.add_argument("--title", default="Verbatim Pundits: gate results (P10)")
    ap.add_argument("--note", default=None, help="a paragraph printed under the provenance line")
    args = ap.parse_args()
    try:
        doc = render(json.loads(args.report.read_text()), args.data_revision, args.withhold_lean,
                     title=args.title, note=args.note)
    except (RuntimeError, KeyError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1
    args.out.write_text(doc)
    print(f"wrote {args.out}" + (" (lean-split figures withheld)" if args.withhold_lean else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
