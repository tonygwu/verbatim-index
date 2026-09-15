#!/usr/bin/env python3
"""What the supplemental sources actually added, per leader and per source kind.

Read-only. Spends no quota and writes nothing unless --out is given.

Answers three questions, in the order they matter:

  1. Does each thin leader now clear MIN_TRANSCRIPTS_TO_RANK?
  2. Which KIND of source produced the accepted predictions? This is the
     transferable finding. If earnings calls carry the yield and podcasts do
     not, the next discovery run should not look for podcasts.
  3. Where do the rejected candidates die? The whole premise of the run was that
     the falsifiable gate kills most of them, and that is measured here rather
     than assumed.

`--as-of` is REQUIRED for the past-due column, not defaulted, because "past due"
depends on the day the reader asks and this repo has twice paid for logical time
taken from the local clock.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import predictions_lib as L  # noqa: E402

MIN_TO_RANK = 5


def load(root: Path) -> list[dict]:
    recs = []
    for f in sorted(root.glob("*/*.jsonl")):
        if f.parent.name.startswith("_"):
            continue
        for r in L.parse_lines(f.read_text(), str(f)):
            r["_slug"] = f.parent.name
            r["_sid"] = f.stem
            recs.append(r)
    return recs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline", default="data/predictions",
                    help="the existing corpus, for the before-and-after column")
    ap.add_argument("--as-of", required=True, metavar="YYYY-MM-DD",
                    help="required; the day 'past due' is judged against")
    ap.add_argument("--out", help="write the table as JSON here")
    args = ap.parse_args(argv)

    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError:
        print(f"--as-of {args.as_of!r} is not YYYY-MM-DD", file=sys.stderr)
        return 2

    run = Path(args.run).resolve()
    new = load(run / "results")
    base = load(Path(args.baseline).resolve())

    # Source kind comes from the transcript record, not the prediction record.
    kind_of, words_of = {}, {}
    for t in (run / "transcripts").rglob("*.json"):
        rec = json.loads(t.read_text())
        kind_of[(rec["leader_slug"], rec["source_id"])] = rec.get("declared_kind") or "unknown"
        words_of[(rec["leader_slug"], rec["source_id"])] = rec.get("word_count", 0)

    base_acc = collections.Counter(r["_slug"] for r in base if r.get("accepted"))
    new_acc = collections.Counter(r["_slug"] for r in new if r.get("accepted"))
    new_cand = collections.Counter(r["_slug"] for r in new)

    slugs = sorted(set(new_cand) | set(new_acc))
    rows = []
    print(f"{'leader':18} {'was':>4} {'new':>4} {'now':>4} {'cand':>5} {'keep':>5}  rank?")
    for s in slugs:
        was, add = base_acc.get(s, 0), new_acc.get(s, 0)
        now, cand = was + add, new_cand.get(s, 0)
        keep = f"{100 * add / cand:.0f}%" if cand else "-"
        crossed = ("YES" if now >= MIN_TO_RANK and was < MIN_TO_RANK
                   else ("already" if was >= MIN_TO_RANK else "still under"))
        print(f"{s:18} {was:>4} {add:>4} {now:>4} {cand:>5} {keep:>5}  {crossed}")
        rows.append({"slug": s, "before": was, "added": add, "after": now,
                     "candidates": cand, "crossed_floor": crossed})

    crossed = sum(1 for r in rows if r["crossed_floor"] == "YES")
    under = sum(1 for r in rows if r["crossed_floor"] == "still under")
    print(f"\n{len(new)} candidates -> {sum(new_acc.values())} accepted "
          f"({100 * sum(new_acc.values()) / len(new):.0f}%) across {len(slugs)} leaders")
    print(f"crossed the floor of {MIN_TO_RANK}: {crossed}   still under: {under}")

    # --- where the rejected ones die ---------------------------------------
    gates: collections.Counter = collections.Counter()
    stage = collections.Counter()
    for r in new:
        if r.get("accepted"):
            continue
        e, v = r.get("extraction") or {}, r.get("verification") or {}
        stage[(e.get("qualifies"), v.get("qualifies"))] += 1
        for g, val in (v.get("gates") or {}).items():
            if val is False:
                gates[g] += 1
    print(f"\nrejected by (extract_qualifies, verify_qualifies): {dict(stage)}")
    print(f"verifier gate failures: {gates.most_common()}")

    # --- which source kinds pay ---------------------------------------------
    # The DENOMINATOR is words actually extracted, read from each source's own
    # meta file, not every word fetched. During a partial run the two differ
    # enormously: an unprocessed earnings call contributes its words and none of
    # its predictions, which reported earnings calls at 0.00 per 10k words while
    # they were simply still in the queue. A rate whose denominator includes
    # unprocessed material is not a rate.
    extracted: set[tuple[str, str]] = set()
    for meta in (run / "results").glob("*/*.meta.json"):
        if meta.parent.name.startswith("_"):
            continue
        m = json.loads(meta.read_text())
        if (m.get("extract") or {}).get("status") == "ok":
            extracted.add((meta.parent.name, meta.name[:-len(".meta.json")]))

    # A source whose RECORDS are on disk counts in both the numerator and the
    # denominator, or in neither. `--force` can mark a meta `extract: failed`
    # after a quota stop while the verified records from an earlier successful
    # run survive, and taking the numerator from records and the denominator
    # from meta put Collison's 15 accepted over one letter's 1.3k words and
    # reported 115.74 per 10k. Same defect as the pending-sources denominator
    # above, arriving from the other side.
    with_records = {(r["_slug"], r["_sid"]) for r in new}
    counted = extracted | with_records

    by_kind_acc: collections.Counter = collections.Counter()
    by_kind_words: dict[str, int] = collections.defaultdict(int)
    by_kind_srcs: collections.Counter = collections.Counter()
    for r in new:
        if r.get("accepted"):
            by_kind_acc[kind_of.get((r["_slug"], r["_sid"]), "unknown")] += 1
    for key in counted:
        k = kind_of.get(key, "unknown")
        by_kind_words[k] += words_of.get(key, 0)
        by_kind_srcs[k] += 1
    extracted = counted

    pending = len(kind_of) - len(extracted)
    print(f"\nyield by source kind, over the {len(extracted)} sources extracted so far"
          + (f" ({pending} still pending)" if pending else ""))
    print(f"{'source kind':24} {'srcs':>5} {'accepted':>8} {'kwords':>8} {'per 10k words':>14}")
    for k in sorted(by_kind_words, key=lambda x: -(by_kind_acc.get(x, 0) / max(by_kind_words[x], 1))):
        w = by_kind_words[k]
        rate = f"{by_kind_acc.get(k, 0) / (w / 10000):.2f}" if w else "-"
        print(f"{k:24} {by_kind_srcs[k]:>5} {by_kind_acc.get(k, 0):>8} "
              f"{w / 1000:>8.1f} {rate:>14}")
    tw = sum(by_kind_words.values())
    if tw:
        print(f"{'ALL':24} {len(extracted):>5} {sum(by_kind_acc.values()):>8} "
              f"{tw / 1000:>8.1f} {sum(by_kind_acc.values()) / (tw / 10000):>14.2f}")
        print("   for comparison, the existing YouTube corpus runs 0.54 per 10k words")

    # --- Phase 2 relevance ---------------------------------------------------
    def is_past_due(p: dict) -> bool:
        """True when the target date has fully elapsed by --as-of.

        A partial date is read at its LAST instant, so "2027" is past due only
        after 2027-12-31 and never during it. Reading it at the first instant
        would mark a whole year past due on its first day.
        """
        td = p.get("target_date")
        if not td or not L.target_date_valid(td):
            return False
        end = {10: td, 7: f"{td}-28", 4: f"{td}-12-31"}.get(len(td))
        if end is None:
            return False
        try:
            return date.fromisoformat(end) < as_of
        except ValueError:
            return False

    accepted = [r for r in new if r.get("accepted")]
    preds = [r.get("prediction") or {} for r in accepted]
    own = sum(1 for p in preds if p.get("subject_control") == "own")
    dated = sum(1 for p in preds if p.get("target_date") and L.target_date_valid(p["target_date"]))
    past = sum(1 for p in preds if is_past_due(p))
    scorable = sum(1 for p in preds
                   if is_past_due(p) and p.get("subject_control") != "own")
    print(f"\nPhase 2 shape of the {len(accepted)} new accepted, as of {as_of}:")
    print(f"  own-control (a delivery rate, not foresight): {own}")
    print(f"  carrying a valid target date:                 {dated}")
    print(f"  past due:                                     {past}")
    print(f"  past due AND not own-control (scorable):      {scorable}")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"as_of": str(as_of), "rows": rows, "gate_failures": dict(gates),
             "by_kind_accepted": dict(by_kind_acc),
             "by_kind_words": dict(by_kind_words)},
            indent=1, sort_keys=True) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
