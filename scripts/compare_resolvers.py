#!/usr/bin/env python3
"""Pick board rows by a stated rule, then report two resolvers' agreement on them, row by row.

    .venv/bin/python scripts/compare_resolvers.py select --data data --out <experiment> --exclude id,id
    .venv/bin/python scripts/compare_resolvers.py report --selection <experiment>/selection.json \
        --astra <experiment>/astra --gemini <experiment>/gemini --out <experiment>/comparison

Built for VI-47, the Gemini 4 Argon resolver measured beside Astra; reads nothing
model-specific beyond the `harness` field, so any two resolve runs compare.

SELECT. The pool is every board row (`predictions/scores.json`) that is eligible
and resolved, whose board resolution is an Astra resolve sidecar, minus the rows
named in --exclude. A row's board resolution is found among the runs
`scoring.json` names as the one sidecar whose reasoning equals the reasoning
scores.json shows for it; none, or several, leaves the row out by that reason.
This never re-implements the scorer's choice of run. Then, for each outcome
(smallest pool first), rows are taken in sha256("<salt>:<prediction_id>") order:
first up to --already-public rows whose board resolution sets already_public, then
rows that do not, until --per-outcome rows, never taking a leader's row once
--per-leader rows of that leader are in. A short stratum is reported, never padded.

REPORT. For each selected row: the board's outcome, each arm's outcome, and
whether each set already_public. Agreement is stated as "agree of n" over the rows
both sides answered, for outcome and for whether already_public is set, between
Gemini and the fresh Astra run, and between each arm and the board. Every
disagreement carries both arms' sources and reasoning. A pair whose prompt_sha256
differs is listed, because then the two arms did not read the same prompt.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R  # noqa: E402

OUTCOMES = ("occurred", "not_occurred", "unresolvable")


def _key(salt: str, pid: str) -> str:
    return hashlib.sha256(f"{salt}:{pid}".encode()).hexdigest()


def board_resolutions(scores_rows: list[dict], runs: list[Path], exclude: set[str]
                      ) -> tuple[dict[str, dict], collections.Counter]:
    """{prediction_id: {"sidecar", "run"}} for every row in the pool, and the left-out rows by reason."""
    found: dict[str, list[tuple[Path, dict]]] = collections.defaultdict(list)
    seen: set[Path] = set()
    for run in runs:
        if Path(run).resolve() in seen:
            continue
        seen.add(Path(run).resolve())
        for pid, obj in R.load_sidecars(Path(run), "resolve").items():
            found[pid].append((Path(run), obj))
    out, left = {}, collections.Counter()
    for row in scores_rows:
        pid = row["prediction_id"]
        if pid in exclude:
            left["adjudicated"] += 1
            continue
        if row.get("outcome") not in OUTCOMES or not row.get("resolution_reasoning"):
            left["not_resolved"] += 1
            continue
        if not (row.get("flags") or {}).get("eligible"):
            left["not_eligible"] += 1
            continue
        match = [(run, obj) for run, obj in found.get(pid, [])
                 if obj.get("reasoning") == row["resolution_reasoning"] and obj.get("outcome") == row["outcome"]]
        if not match:
            left["no_matching_sidecar"] += 1
            continue
        if len(match) > 1:
            left["several_matching_sidecars"] += 1
            continue
        run, obj = match[0]
        if obj.get("harness") != "astra" or obj.get("stage") != "resolve":
            left["not_astra"] += 1
            continue
        out[pid] = {"sidecar": obj, "run": run}
    return out, left


def select(scores_rows: list[dict], runs: list[Path], *, exclude: set[str], per_outcome: int, already_public: int,
           per_leader: int, salt: str) -> dict:
    pool, left = board_resolutions(scores_rows, runs, exclude)
    strata: dict[str, list[dict]] = collections.defaultdict(list)
    for pid, b in pool.items():
        obj = b["sidecar"]
        strata[obj["outcome"]].append({
            "prediction_id": pid, "leader_slug": obj["leader_slug"], "board_outcome": obj["outcome"],
            "board_already_public": obj.get("already_public"), "board_run": str(b["run"]),
            "board_policy_release": obj.get("policy_release"), "board_as_of": obj.get("as_of"),
            "board_prompt_sha256": obj.get("prompt_sha256"), "order_key": _key(salt, pid)})
    for rows in strata.values():
        rows.sort(key=lambda r: r["order_key"])
    chosen, per_lead, short = [], collections.Counter(), {}
    for outcome in sorted(OUTCOMES, key=lambda o: (len(strata.get(o, [])), o)):
        rows = strata.get(outcome, [])
        took = []
        for want_ap, cap in ((True, already_public), (False, per_outcome)):
            for r in rows:
                if len(took) >= per_outcome or (want_ap and len(took) >= cap):
                    break
                if bool(r["board_already_public"]) != want_ap or per_lead[r["leader_slug"]] >= per_leader:
                    continue
                took.append(r)
                per_lead[r["leader_slug"]] += 1
        if len(took) < per_outcome:
            short[outcome] = per_outcome - len(took)
        chosen += took
    pool_counts = {f"{o}/{'already_public' if ap else 'none'}": sum(1 for r in strata.get(o, [])
                   if bool(r["board_already_public"]) == ap) for o in OUTCOMES for ap in (True, False)}
    rule = (f"Pool: board rows (scores.json) that are eligible and resolved, whose board resolution is the one Astra "
            f"resolve sidecar, among the scored runs, carrying the reasoning scores.json shows; minus {sorted(exclude)}. "
            f"For each outcome, smallest pool first, rows in sha256(\"{salt}:<prediction_id>\") order: first up to "
            f"{already_public} with already_public set, then rows without it, to {per_outcome} rows; a leader's row is "
            f"skipped once per_leader={per_leader} rows of that leader are in. A short stratum is reported, not padded.")
    return {"rule": rule, "salt": salt, "per_outcome": per_outcome, "already_public": already_public,
            "per_leader": per_leader, "exclude": sorted(exclude), "pool": pool_counts, "excluded": dict(left),
            "short": short, "rows": chosen}


def _arm(run: Path, pid: str, slug: str) -> "dict | None":
    f = R.sidecar_path(run, "resolve", slug, pid)
    return json.loads(f.read_text()) if f.exists() else None


def _pair(rows: list[dict], a: str, b: str) -> dict:
    both = [r for r in rows if r[a] is not None and r[b] is not None]
    return {"outcome": {"agree": sum(r[a]["outcome"] == r[b]["outcome"] for r in both), "of": len(both)},
            "already_public_set": {"agree": sum(bool(r[a]["already_public"]) == bool(r[b]["already_public"])
                                                for r in both), "of": len(both)}}


def _brief(obj: "dict | None") -> "dict | None":
    if obj is None:
        return None
    tel = obj.get("telemetry") or {}
    return {"outcome": obj["outcome"], "confidence": obj.get("confidence"),
            "unresolvable_reason": obj.get("unresolvable_reason"), "already_public": obj.get("already_public"),
            "sources": obj.get("sources"), "reasoning": obj.get("reasoning"), "harness": obj.get("harness"),
            "policy_release": obj.get("policy_release"), "prompt_sha256": obj.get("prompt_sha256"),
            "searches": len(((tel.get("web_search") or {}).get("queries")) or []),
            "own_site_mentions": tel.get("own_site_mentions")}


def report(selection: dict, astra_run: Path, gemini_run: Path) -> dict:
    if Path(astra_run).resolve() == Path(gemini_run).resolve():
        raise SystemExit("--astra and --gemini name the same run; a comparison needs two")
    rows = []
    for s in selection["rows"]:
        pid, slug = s["prediction_id"], s["leader_slug"]
        board = json.loads(R.sidecar_path(Path(s["board_run"]), "resolve", slug, pid).read_text())
        rows.append({"prediction_id": pid, "leader_slug": slug, "board": _brief(board),
                     "astra_new": _brief(_arm(Path(astra_run), pid, slug)),
                     "gemini": _brief(_arm(Path(gemini_run), pid, slug))})
    agreement = {"gemini_vs_astra_new": _pair(rows, "gemini", "astra_new"),
                 "gemini_vs_board": _pair(rows, "gemini", "board"),
                 "astra_new_vs_board": _pair(rows, "astra_new", "board")}
    confusion = collections.Counter((r["astra_new"]["outcome"], r["gemini"]["outcome"]) for r in rows
                                    if r["astra_new"] and r["gemini"])
    disagreements = [{"prediction_id": r["prediction_id"], "leader_slug": r["leader_slug"],
                      "board": r["board"], "astra_new": r["astra_new"], "gemini": r["gemini"]}
                     for r in rows if r["astra_new"] and r["gemini"]
                     and (r["astra_new"]["outcome"] != r["gemini"]["outcome"]
                          or bool(r["astra_new"]["already_public"]) != bool(r["gemini"]["already_public"]))]
    mismatch = [r["prediction_id"] for r in rows if r["astra_new"] and r["gemini"]
                and (r["astra_new"]["prompt_sha256"], r["astra_new"]["policy_release"])
                != (r["gemini"]["prompt_sha256"], r["gemini"]["policy_release"])]
    return {"astra_run": str(astra_run), "gemini_run": str(gemini_run), "n_selected": len(rows),
            "missing": {arm: [r["prediction_id"] for r in rows if r[arm] is None] for arm in ("astra_new", "gemini")},
            "agreement": agreement,
            "confusion_astra_new_by_gemini": [{"astra_new": a, "gemini": g, "n": n}
                                              for (a, g), n in sorted(confusion.items())],
            "prompt_mismatch": mismatch, "rows": rows, "disagreements": disagreements}


def _ap(obj: "dict | None") -> str:
    if obj is None:
        return "-"
    ap = obj.get("already_public")
    return (ap.get("date") or "set") if isinstance(ap, dict) else "no"


def render_markdown(rep: dict) -> str:
    def rate(x):
        return f"{x['agree']} of {x['of']}" + (f" ({100 * x['agree'] / x['of']:.0f}%)" if x["of"] else "")
    lines = [f"# Resolver comparison", "", f"Astra run: `{rep['astra_run']}`  ", f"Gemini run: `{rep['gemini_run']}`",
             "", f"{rep['n_selected']} rows selected. Missing answers: Astra {len(rep['missing']['astra_new'])} "
             f"{rep['missing']['astra_new']}, Gemini {len(rep['missing']['gemini'])} {rep['missing']['gemini']}.", "",
             "| pair | outcome agrees | already_public set agrees |", "|---|---|---|"]
    for name, a in rep["agreement"].items():
        lines.append(f"| {name.replace('_', ' ')} | {rate(a['outcome'])} | {rate(a['already_public_set'])} |")
    lines += ["", "| prediction | leader | board | Astra now | Gemini | already_public (board / Astra / Gemini) "
              "| Gemini searches | own-site output |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        b, a, g = r["board"], r["astra_new"], r["gemini"]
        lines.append(f"| {r['prediction_id']} | {r['leader_slug']} | {b['outcome']} | {a['outcome'] if a else '-'} "
                     f"| {g['outcome'] if g else '-'} | {_ap(b)} / {_ap(a)} / {_ap(g)} | {g['searches'] if g else '-'} "
                     f"| {g['own_site_mentions'] if g else '-'} |")
    if rep["prompt_mismatch"]:
        lines += ["", f"Pairs whose prompt or release differ: {rep['prompt_mismatch']}"]
    lines += ["", "## Disagreements", ""]
    for d in rep["disagreements"]:
        lines.append(f"### {d['prediction_id']} ({d['leader_slug']}): Astra {d['astra_new']['outcome']}, "
                     f"Gemini {d['gemini']['outcome']}, board {d['board']['outcome']}")
        for arm in ("astra_new", "gemini"):
            x = d[arm]
            lines.append(f"- **{arm.replace('_', ' ')}** ({x['confidence']}; already_public {_ap(x)}): {x['reasoning']}")
            for src in x.get("sources") or []:
                lines.append(f"  - {src.get('date')} {src.get('where')}: {src.get('what_it_shows')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: "list[str] | None" = None) -> int:
    from data_clone_workflow import load_scoring_config
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--data", type=Path, required=True, help="the data checkout (holds predictions/scoring.json)")
    s.add_argument("--out", type=Path, required=True, help="the experiment folder; gets selection.json and ids.txt")
    s.add_argument("--exclude", default="", help="comma-separated prediction ids to leave out")
    s.add_argument("--per-outcome", type=int, default=8)
    s.add_argument("--already-public", type=int, default=3)
    s.add_argument("--per-leader", type=int, default=2)
    s.add_argument("--salt", required=True, help="fixes the order; name it in the experiment's README")
    r = sub.add_parser("report")
    r.add_argument("--selection", type=Path, required=True)
    r.add_argument("--astra", type=Path, required=True)
    r.add_argument("--gemini", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True, help="writes <out>.json and <out>.md")
    args = ap.parse_args(argv)
    if args.cmd == "select":
        cfg_root, cfg = load_scoring_config(args.data / "predictions" / "scoring.json")
        scores = json.loads((cfg_root / cfg["out"]).read_text())["predictions"]
        exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
        sel = select(scores, [cfg_root / run for run in cfg["runs"]], exclude=exclude, per_outcome=args.per_outcome,
                     already_public=args.already_public, per_leader=args.per_leader, salt=args.salt)
        sel["scores_sha256"] = hashlib.sha256((cfg_root / cfg["out"]).read_bytes()).hexdigest()
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "selection.json").write_text(json.dumps(sel, indent=1, sort_keys=True) + "\n")
        (args.out / "ids.txt").write_text("".join(f"{x['prediction_id']}\n" for x in sel["rows"]))
        print(f"selected {len(sel['rows'])}; pool {sel['pool']}; excluded {sel['excluded']}; short {sel['short']}")
        return 0
    rep = report(json.loads(args.selection.read_text()), args.astra, args.gemini)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{args.out}.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    Path(f"{args.out}.md").write_text(render_markdown(rep))
    print(json.dumps(rep["agreement"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
