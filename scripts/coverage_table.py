#!/usr/bin/env python3
"""Per-leader coverage across every pipeline stage.

One row per leader, showing how many appearances survive each narrowing:
identified as candidates, fetched as transcripts, passed the quality gate,
and graded by the judges. Reading it left to right shows exactly where a
leader is losing material.

Usage:
  coverage_table.py                 # text table
  coverage_table.py --csv out.csv   # also write CSV
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

TARGET = 5

# Column order for the per-judge columns. Any judge found in the data that is
# not listed here is appended rather than dropped, so a third judge shows up as
# a new column instead of vanishing into a total.
JUDGE_ORDER = ("fable", "astra")
JW = 5  # width of one per-judge column
PW = 5  # width of one percentage column


def pct(num: int, den: int) -> float | None:
    """Percentage, or None when there is no denominator to divide by.

    None means "not answerable yet" and prints as a dash. Returning 0.0 for a
    leader with nothing identified would read as a coverage failure instead of
    an absent measurement. The value is NOT clamped to 100: a grade whose
    transcript has left the corpus pushes the ratio above 100, and that is the
    orphaned-grade bug this table exists to make visible.
    """
    if den <= 0:
        return None
    return 100.0 * num / den


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    roster = json.loads(Path("data/roster/final.json").read_text())["roster"]

    # 1. identified: ranked candidates the discovery step produced
    identified: Counter = Counter()
    mf = Path("data/sources/all.jsonl")
    if mf.exists():
        for line in mf.read_text().splitlines():
            if line.strip():
                identified[json.loads(line)["leader_slug"]] += 1
    # Happy Scribe candidates are part of the pool too. Counting only YouTube
    # made IDENT look like a ceiling it is not, and would eventually show a
    # leader with FETCH above IDENT, which reads as a bug rather than a
    # second source.
    hsf = Path("data/sources/happyscribe_candidates.json")
    if hsf.exists():
        hs = json.loads(hsf.read_text())
        if isinstance(hs, dict):
            for slug, rows in hs.items():
                if isinstance(rows, list):
                    identified[slug] += len(rows)

    # 2. fetched: transcript files actually on disk, plus the ones that were
    # fetched and then retired as duplicates. The sweep renames a retired
    # source to <id>.json.superseded, so those are appearances we DID obtain
    # and then found to be re-uploads of another appearance.
    retired: Counter = Counter()
    tdir0 = Path("data/transcripts")
    if tdir0.exists():
        for p in tdir0.rglob("*.superseded"):
            retired[p.parent.name] += 1

    fetched: Counter = Counter()
    from_yt: Counter = Counter()
    from_hs: Counter = Counter()
    tdir = Path("data/transcripts")
    if tdir.exists():
        for p in tdir.rglob("*.json"):
            if p.name.endswith(".tmp"):
                continue
            fetched[p.parent.name] += 1
            try:
                method = json.loads(p.read_text()).get("fetch_method") or "happyscribe"
            except Exception:
                method = "happyscribe"
            (from_yt if method == "youtube_transcript_api" else from_hs)[p.parent.name] += 1

    # 3. gated: QA verdict of pass or review; reject does not reach a judge
    gated: Counter = Counter()
    rejected: Counter = Counter()
    qf = Path("data/logs/transcript_qa.json")
    if qf.exists():
        for r in json.loads(qf.read_text())["reports"]:
            if r["verdict"] == "reject":
                rejected[r["leader_slug"]] += 1
            else:
                gated[r["leader_slug"]] += 1

    # 4. graded: distinct transcripts with a blinded grade, plus total judge
    # calls. Both are kept per judge as well as pooled: the judges run off
    # separate quota and one can stall for hours while the pooled number keeps
    # climbing, which reads as healthy progress when it is not.
    graded_tx: dict[str, set] = defaultdict(set)
    graded_by_judge: dict[tuple[str, str], set] = defaultdict(set)
    by_judge_tx: dict[str, set] = defaultdict(set)
    calls: Counter = Counter()
    calls_by_judge: Counter = Counter()
    seen_judges: set[str] = set()
    gdir = Path("data/grades")
    if gdir.exists():
        for d in gdir.iterdir():
            if d.is_dir() and d.name != "_raw":
                seen_judges.add(d.name)
        for p in gdir.rglob("*.json"):
            if "_raw" in p.parts or p.name.endswith(".tmp"):
                continue
            try:
                g = json.loads(p.read_text())
            except Exception:
                continue
            slug = g.get("leader_slug")
            if not slug:
                continue
            judge = g.get("judge") or "?"
            seen_judges.add(judge)
            calls[slug] += 1
            calls_by_judge[(slug, judge)] += 1
            if g.get("mode") == "blinded" and not g.get("validation_errors"):
                graded_tx[slug].add(g["source_id"])
                graded_by_judge[(slug, judge)].add(g["source_id"])
                by_judge_tx[judge].add(g["transcript_id"])

    judges = [j for j in JUDGE_ORDER if j in seen_judges]
    judges += sorted(j for j in seen_judges if j not in JUDGE_ORDER)
    if not judges:                      # no grades on disk yet
        judges = list(JUDGE_ORDER)

    # Scores, where they exist yet
    scores: dict[str, dict] = {}
    rf = Path("data/results.json")
    if rf.exists():
        for l in json.loads(rf.read_text())["leaders"]:
            if l.get("blinded"):
                scores[l["slug"]] = l["blinded"]

    rows = []
    for p in roster:
        s = p["slug"]
        rows.append({
            "leader": p["name"],
            "company": p["company"],
            "identified": identified.get(s, 0),
            "duplicates": retired.get(s, 0),
            # Distinct appearances discovery found: every candidate, less the
            # ones we obtained and then retired as re-uploads of each other.
            "unique": max(0, identified.get(s, 0) - retired.get(s, 0)),
            "fetched": fetched.get(s, 0),
            "yt": from_yt.get(s, 0),
            "hs": from_hs.get(s, 0),
            "gated": gated.get(s, 0),
            "rejected": rejected.get(s, 0),
        })
        for j in judges:
            rows[-1][f"graded_{j}"] = len(graded_by_judge.get((s, j), ()))
        rows[-1]["graded"] = len(graded_tx.get(s, ()))
        # Transcripts this leader has from EVERY judge. Intersecting the
        # per-judge source_id sets, not min() of the counts: two judges can
        # each hold five grades and overlap on three.
        all_judges = [set(graded_by_judge.get((s, j), ())) for j in judges]
        rows[-1]["graded_all"] = len(set.intersection(*all_judges)) if all_judges else 0
        for j in judges:
            rows[-1][f"calls_{j}"] = calls_by_judge.get((s, j), 0)
        rows[-1]["judge_calls"] = calls.get(s, 0)
        rows[-1]["overall"] = scores.get(s, {}).get("overall")
        rows[-1]["pct_fetched"] = pct(rows[-1]["fetched"], rows[-1]["unique"])
        rows[-1]["pct_graded_any"] = pct(rows[-1]["graded"], rows[-1]["fetched"])
        rows[-1]["pct_graded_all"] = pct(rows[-1]["graded_all"], rows[-1]["fetched"])
    rows.sort(key=lambda r: (-r["graded"], -r["fetched"], r["leader"]))

    w = max(len(r["leader"]) for r in rows)
    c = min(24, max(len(r["company"]) for r in rows))

    def label(j: str) -> str:
        return j[:JW].upper()

    def group(cells: list[str]) -> str:
        return " ".join(cells)

    def band(title: str, width: int) -> str:
        # Truncate rather than overflow: a long judge-group title must not
        # shift the columns underneath it out of alignment.
        return title[:width].center(width)

    def left(i, leader, company, r) -> str:
        return (f"{i:>3}  {leader:<{w}}  {company[:c]:<{c}}  "
                f"{r['identified']:>5} {r['unique']:>5} {r['fetched']:>5} {r['yt']:>3} {r['hs']:>3} "
                f"{r['gated']:>5} {r['rejected']:>4}")

    head_left = (f"{'#':>3}  {'LEADER':<{w}}  {'ORGANISATION':<{c}}  "
                 f"{'IDENT':>5} {'UNIQ':>5} {'FETCH':>5} {'YT':>3} {'HS':>3} {'GATED':>5} {'REJ':>4}")
    gh = group([f"{label(j):>{JW}}" for j in judges] + [f"{'ANY':>{JW}}"])
    ch = group([f"{label(j):>{JW}}" for j in judges])
    # "graded by both judges" generalises to "by all judges", so the label
    # carries the judge count rather than a hardcoded 2.
    pct_labels = ("FET%", "1J%", f"{len(judges)}J%")
    ph = group([f"{t:>{PW}}" for t in pct_labels])
    rule = (f"{'-'*3}  {'-'*w}  {'-'*c}  {'-'*5} {'-'*5} {'-'*5} {'-'*3} {'-'*3} {'-'*5} {'-'*4}"
            f"   {group(['-'*JW] * (len(judges) + 1))}"
            f"   {group(['-'*JW] * len(judges))}"
            f"   {group(['-'*PW] * len(pct_labels))}   {'-'*5}")

    def cells_pct(r: dict) -> str:
        out = []
        for k in ("pct_fetched", "pct_graded_any", "pct_graded_all"):
            v = r[k]
            out.append(f"{'-' if v is None else f'{v:.0f}':>{PW}}")
        return group(out)

    # GRADED is distinct transcripts with a valid blinded grade; ANY is the
    # union across judges, so it is not the sum of the columns to its left.
    # CALLS counts every grade file, blinded and open alike.
    print(f"{' ' * len(head_left)}   {band('BLINDED GRADED', len(gh))}"
          f"   {band('JUDGE CALLS', len(ch))}   {band('COVERAGE %', len(ph))}   {'':>5}")
    print(f"{head_left}   {gh}   {ch}   {ph}   {'SCORE':>5}")
    print(rule)
    for i, r in enumerate(rows, 1):
        sc = f"{r['overall']:.1f}" if r["overall"] is not None else "-"
        g = group([f"{r[f'graded_{j}']:>{JW}}" for j in judges] + [f"{r['graded']:>{JW}}"])
        k = group([f"{r[f'calls_{j}']:>{JW}}" for j in judges])
        print(f"{left(i, r['leader'], r['company'], r)}   {g}   {k}   {cells_pct(r)}   {sc:>5}")

    keys = (["identified", "unique", "duplicates", "fetched", "yt", "hs", "gated", "rejected", "graded",
             "graded_all", "judge_calls"]
            + [f"graded_{j}" for j in judges] + [f"calls_{j}" for j in judges])
    tot = {k: sum(r[k] for r in rows) for k in keys}
    # Fleet percentages come from the summed counts, not from averaging the
    # per-leader percentages. An average of ratios would weight a leader with
    # 7 appearances the same as one with 57.
    tot["pct_fetched"] = pct(tot["fetched"], tot["unique"])
    tot["pct_graded_any"] = pct(tot["graded"], tot["fetched"])
    tot["pct_graded_all"] = pct(tot["graded_all"], tot["fetched"])
    print(rule)
    gt = group([f"{tot[f'graded_{j}']:>{JW}}" for j in judges] + [f"{tot['graded']:>{JW}}"])
    kt = group([f"{tot[f'calls_{j}']:>{JW}}" for j in judges])
    print(f"{'':>3}  {'TOTAL':<{w}}  {'':<{c}}  {tot['identified']:>5} {tot['unique']:>5} {tot['fetched']:>5} "
          f"{tot['yt']:>3} {tot['hs']:>3} {tot['gated']:>5} {tot['rejected']:>4}"
          f"   {gt}   {kt}   {cells_pct(tot)}   {'':>5}")
    print(f"{'':>3}  UNIQ = IDENT minus {tot['duplicates']} appearances fetched then retired as "
          f"re-uploads of another.")
    print(f"{'':>3}  FET% = FETCH/UNIQ.  1J% = ANY/FETCH.  "
          f"{len(judges)}J% = graded by all {len(judges)} judges / FETCH.")
    if tot["duplicates"] == 0 and tot["fetched"] > 0:
        print(f"{'':>3}  NOTE: no retired duplicates found on disk, so UNIQ equals IDENT. "
              f"The .superseded\n{'':>8}markers are gitignored, so a clone that did not run "
              f"the sweep cannot see them.")
    over = [r["leader"] for r in rows
            if (r["pct_graded_any"] or 0) > 100 or (r["pct_fetched"] or 0) > 100]
    if over:
        print(f"{'':>3}  OVER 100%: {', '.join(over)} — grades outlive their "
              f"withdrawn transcripts. Run normalize_transcripts.py --grades.")

    started = sum(1 for r in rows if r["fetched"] > 0)
    print()
    print(f"  leaders with any transcript : {started}/{len(rows)}")
    print(f"  leaders at target ({TARGET})       : {sum(1 for r in rows if r['fetched'] >= TARGET)}/{len(rows)}")
    print(f"  leaders with any grade      : {sum(1 for r in rows if r['graded'] > 0)}/{len(rows)}")
    print(f"  remaining to fetch          : {max(0, len(rows) * TARGET - tot['fetched'])} transcripts")
    sets = [by_judge_tx.get(j, set()) for j in judges]
    both = set.intersection(*sets) if sets else set()
    union = set.union(*sets) if sets else set()
    # Two different "remaining" numbers, and they answer different questions.
    # The first is the fetch-side target of TARGET transcripts per leader. The
    # second is the gap that actually blocks publication: a transcript graded
    # by only one judge cannot enter the blinded score, so once the target is
    # met the first number reads ~0 while real work remains.
    to_target = max(0, len(rows) * TARGET * len(judges) - tot["judge_calls"])
    to_parity = sum(len(union - s) for s in sets)
    print(f"  blinded transcripts graded  : "
          + ", ".join(f"{j} {len(s)}" for j, s in zip(judges, sets)))
    print(f"  graded by every judge       : {len(both)}/{len(union)} transcripts"
          f"  (one-sided: "
          + ", ".join(f"{j} {len(s - both)}" for j, s in zip(judges, sets)) + ")")
    print(f"  remaining judge calls       : ~{to_target} to reach {TARGET}/leader; "
          f"~{to_parity} to give every graded transcript all {len(judges)} judges")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        print(f"\n  csv written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
