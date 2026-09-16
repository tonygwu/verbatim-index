#!/usr/bin/env python3
"""Join resolutions and priors into points, and aggregate them per person.

    .venv/bin/python scripts/score_predictions.py --run data/predictions/_experiments/<run> \
        --as-of 2026-09-14 --out data/predictions/_experiments/<run>/scores.json

Spends no model calls. Everything here is arithmetic over what the two stages
already wrote, so it can be re-run freely and its numbers re-derived.

THE RULE, from `scripts/prediction_score.py`:
  a speaker who states no probability scores  -log2(p)  when right and
  (p/(1-p))*log2(p) when wrong, which is zero in expectation at every p. A
  speaker who states their own q scores log2(q/p) or log2((1-q)/(1-p)).
So a mean above zero is foresight and a mean below zero is worse than the base
rate. Volume earns nothing on its own, which is why the published figure is a
MEAN and not a sum.

WHAT COUNTS TOWARD THE PUBLISHED FIGURE
  - resolved to occurred or not_occurred, so "unresolvable" is excluded rather
    than scored as a miss,
  - carries a prior,
  - clears the eligibility rule: specificity high, at least six months of lead
    time, and a deadline that does not precede the statement.
Everything else is loaded, counted and reported, never silently dropped. A
person below `MIN_SCORED_TO_RANK` keeps their number in this file and does not
get a published one, which is how `MIN_TRANSCRIPTS_TO_RANK` already works on the
leaderboard.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2_resolvability as P2  # noqa: E402
import prediction_score as PS  # noqa: E402
import resolution_lib as R  # noqa: E402
from resolve_predictions import select  # noqa: E402

# Five, the same floor and for the same reason as MIN_TRANSCRIPTS_TO_RANK: below
# it a number is a placeholder, and the board should not carry one as a score.
MIN_SCORED_TO_RANK = 5


def speaker_q(rec: dict) -> float | None:
    """The speaker's OWN probability, when they stated one.

    Only 5 records in 475 carry one and three of those state q = 1.0, so this
    branch is rare. It is kept because the rule the operator specified has two
    halves and dropping the rarer half would silently change the rule.
    """
    conf = rec.get("confidence") or {}
    p = conf.get("probability")
    if p is None or isinstance(p, bool) or not isinstance(p, (int, float)):
        return None
    return float(p)


def join(rows: list[dict], resolutions: dict, priors: dict) -> tuple[list[dict], collections.Counter]:
    """One row per past-due prediction, with its points where all the parts exist."""
    out, why = [], collections.Counter()
    for r in rows:
        pid = r["prediction_id"]
        res, pri = resolutions.get(pid), priors.get(pid)
        row = {
            "prediction_id": pid,
            "leader_slug": r["leader_slug"],
            "transcript_id": r["transcript_id"],
            "claim": r["prediction"].get("normalized_claim"),
            "criterion": r["prediction"].get("resolution_criteria"),
            "criterion_repaired": "resolution_criteria_original" in r["prediction"],
            "quote": (r.get("source") or {}).get("quote"),
            "statement_date": (r.get("source") or {}).get("statement_date"),
            "deadline": r["_deadline"].isoformat(),
            "flags": r["_flags"],
            "outcome": res["outcome"] if res else None,
            "resolution_confidence": res["confidence"] if res else None,
            "unresolvable_reason": (res or {}).get("unresolvable_reason"),
            "sources": (res or {}).get("sources") or [],
            "resolution_reasoning": (res or {}).get("reasoning"),
            "p": pri["p"] if pri else None,
            "p_raw": pri["p_raw"] if pri else None,
            "p_clamped": pri["clamped"] if pri else None,
            "reference_class": (pri or {}).get("reference_class"),
            "prior_reasoning": (pri or {}).get("reasoning"),
            "q": speaker_q(r),
            "points": None, "rule": None, "scored": False, "not_scored_because": None,
        }
        if res is None:
            row["not_scored_because"] = "no_resolution"
        elif res["outcome"] == "unresolvable":
            row["not_scored_because"] = f"unresolvable:{res['unresolvable_reason']}"
        elif pri is None:
            row["not_scored_because"] = "no_prior"
        elif not r["_flags"]["eligible"]:
            row["not_scored_because"] = "not_eligible"
        else:
            s = PS.score(res["outcome"] == "occurred", pri["p"], row["q"])
            row.update(points=round(s["points"], 4), rule=s["rule"], scored=True,
                       score_clamped=s["clamped"])
        why[row["not_scored_because"] or "scored"] += 1
        out.append(row)
    return out, why


def per_leader(rows: list[dict], names: dict[str, str]) -> list[dict]:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["leader_slug"]].append(r)
    out = []
    for slug, rs in sorted(by.items()):
        scored = [r for r in rs if r["scored"]]
        pts = [r["points"] for r in scored]
        outcomes = collections.Counter(r["outcome"] for r in rs if r["outcome"])
        out.append({
            "slug": slug,
            "name": names.get(slug, slug),
            "past_due": len(rs),
            "eligible": sum(1 for r in rs if r["flags"]["eligible"]),
            "resolved": sum(1 for r in rs if r["outcome"] in ("occurred", "not_occurred")),
            "unresolvable": outcomes.get("unresolvable", 0),
            "occurred": outcomes.get("occurred", 0),
            "not_occurred": outcomes.get("not_occurred", 0),
            "n_scored": len(scored),
            "mean_points": round(sum(pts) / len(pts), 4) if pts else None,
            "sum_points": round(sum(pts), 4) if pts else None,
            "hit_rate": round(sum(1 for r in scored if r["outcome"] == "occurred") / len(scored), 4) if scored else None,
            "mean_p": round(sum(r["p"] for r in scored) / len(scored), 4) if scored else None,
            "ranked": len(scored) >= MIN_SCORED_TO_RANK,
        })
    out.sort(key=lambda l: (-(l["mean_points"] if l["ranked"] and l["mean_points"] is not None else -99),
                            l["name"]))
    return out


# Ten-point bins. Wider bins hide a bias that turns on only at the top of the
# range, which is exactly where this corpus sits.
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def calibration(rows: list[dict]) -> dict:
    """Is the prior assessor right on average? A reliability table, computed free.

    THIS IS THE DIAGNOSTIC THAT DECIDES WHETHER THE BOARD MEANS ANYTHING. The
    score rule has expected value zero at every p ONLY IF p is the real
    probability. If the assessor runs high, every speaker scores negative and the
    board measures the assessor rather than the speaker. So the overall mean is
    reported next to zero, and a table shows where any gap comes from.

    A gap is not automatically the assessor's fault. The resolver counts a thing
    that happened LATE as not occurring, which is the right rule for a dated
    claim and does push the hit rate down against a prior that priced the event
    rather than the deadline.
    """
    scored = [r for r in rows if r["scored"]]
    table = []
    for lo, hi in BINS:
        b = [r for r in scored if lo <= r["p"] < hi]
        if not b:
            table.append({"bin": f"{lo:.1f}-{min(hi, 1.0):.1f}", "n": 0, "mean_p": None,
                          "hit_rate": None, "gap": None, "mean_points": None})
            continue
        mp = sum(r["p"] for r in b) / len(b)
        hr = sum(1 for r in b if r["outcome"] == "occurred") / len(b)
        table.append({"bin": f"{lo:.1f}-{min(hi, 1.0):.1f}", "n": len(b),
                      "mean_p": round(mp, 4), "hit_rate": round(hr, 4),
                      "gap": round(hr - mp, 4),
                      "mean_points": round(sum(r["points"] for r in b) / len(b), 4)})
    overall_p = sum(r["p"] for r in scored) / len(scored) if scored else None
    overall_hr = (sum(1 for r in scored if r["outcome"] == "occurred") / len(scored)) if scored else None
    return {
        "n": len(scored),
        "mean_p": round(overall_p, 4) if overall_p is not None else None,
        "hit_rate": round(overall_hr, 4) if overall_hr is not None else None,
        "gap": round(overall_hr - overall_p, 4) if scored else None,
        "bins": table,
        "reading": _reading(overall_hr - overall_p if scored else 0.0, len(scored)),
    }


def _reading(gap: float, n: int) -> str:
    # A binomial standard error on the hit rate, so a small corpus does not read
    # as a bias. 0.5 is the widest sd, which keeps this conservative.
    se = (0.25 / n) ** 0.5 if n else 1.0
    if abs(gap) < 1.96 * se:
        return (f"hit rate and mean p agree within noise (gap {gap:+.3f}, 1.96 se {1.96 * se:.3f}); "
                f"the board's mean should sit near zero")
    direction = "LOWER" if gap < 0 else "HIGHER"
    return (f"the hit rate is {direction} than the priors by {abs(gap):.3f}, beyond noise "
            f"(1.96 se {1.96 * se:.3f}). Every score carries that gap, so the board measures the "
            f"assessor as well as the speakers, and the overall mean is NOT a neutral zero")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="the experiment run directory")
    ap.add_argument("--predictions", type=Path, action="append", default=None,
                    help="a corpus directory; repeat it to score several corpora together")
    ap.add_argument("--index", type=Path, default=Path("data/predictions/index.json"))
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--min-lead-days", type=int, default=P2.MIN_LEAD_DAYS)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    args.predictions = args.predictions or [Path("data/predictions")]

    try:
        cutoff = dt.date.fromisoformat(args.as_of)
    except ValueError:
        raise SystemExit(f"--as-of {args.as_of!r} is not a YYYY-MM-DD date")

    rows = select(args.predictions, cutoff, args.min_lead_days)
    repairs = R.load_repairs(args.run)
    applied, unrepairable = R.apply_repairs(rows, repairs)
    resolutions = R.load_sidecars(args.run, "resolve")
    priors = R.load_sidecars(args.run, "prior")

    joined, why = join(rows, resolutions, priors)
    index = json.loads(args.index.read_text())
    names = {l["slug"]: l["name"] for l in index["leaders"]}
    leaders = per_leader(joined, names)

    scored = [r for r in joined if r["scored"]]
    outcomes = collections.Counter(r["outcome"] for r in joined if r["outcome"])
    reasons = collections.Counter(r["unresolvable_reason"] for r in joined if r["unresolvable_reason"])
    conf = collections.Counter(r["resolution_confidence"] for r in joined if r["resolution_confidence"])
    nosrc = sum(1 for r in joined if r["outcome"] in ("occurred", "not_occurred") and not r["sources"])

    doc = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": args.as_of,
        "run_dir": str(args.run),
        "rule": {
            "clamp": PS.CLAMP,
            "min_scored_to_rank": MIN_SCORED_TO_RANK,
            "min_lead_days": args.min_lead_days,
            "baseline_only": "points = -log2(p) if it happened, else (p/(1-p))*log2(p)",
            "speaker_probability": "points = log2(q/p) if it happened, else log2((1-q)/(1-p))",
            "expected_points_at_every_p": 0.0,
        },
        "corpus": {
            "past_due": len(rows),
            "eligible": sum(1 for r in rows if r["_flags"]["eligible"]),
            "criteria_repairs_applied": applied,
            "criteria_unrepairable": unrepairable,
            "resolutions_present": len(resolutions),
            "priors_present": len(priors),
            "by_outcome": dict(outcomes),
            "unresolvable_reasons": dict(reasons),
            "resolution_confidence": dict(conf),
            "resolved_with_no_source": nosrc,
            "scored": len(scored),
            "not_scored_because": dict(why),
            "speaker_stated_q": sum(1 for r in joined if r["q"] is not None),
            "mean_points_all_scored": round(sum(r["points"] for r in scored) / len(scored), 4) if scored else None,
            "leaders_ranked": sum(1 for l in leaders if l["ranked"]),
        },
        "calibration": calibration(joined),
        "leaders": leaders,
        "predictions": joined,
    }
    out = args.out or (args.run / "scores.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")

    c = doc["corpus"]
    print(f"{c['past_due']} past due -> {c['eligible']} eligible -> {c['resolutions_present']} resolved "
          f"-> {c['scored']} scored across {c['leaders_ranked']} ranked leaders")
    print(f"outcomes: {json.dumps(c['by_outcome'], sort_keys=True)}")
    print(f"unresolvable: {json.dumps(c['unresolvable_reasons'], sort_keys=True)}")
    print(f"not scored: {json.dumps(c['not_scored_because'], sort_keys=True)}")
    print(f"criteria repaired: {applied} applied, {unrepairable} unrepairable")
    if nosrc:
        print(f"WARNING: {nosrc} decided outcomes cite no source")
    cal = doc["calibration"]
    print(f"\nIS THE PRIOR ASSESSOR CALIBRATED?  n={cal['n']}  mean p {cal['mean_p']}  "
          f"hit rate {cal['hit_rate']}  gap {cal['gap']:+.3f}" if cal["n"] else "\nno scored predictions")
    if cal["n"]:
        print(f"  {cal['reading']}")
        print(f"  {'p bin':>9} {'n':>4} {'mean p':>7} {'hit':>6} {'gap':>7} {'points':>8}")
        for b in cal["bins"]:
            if b["n"]:
                print(f"  {b['bin']:>9} {b['n']:4} {b['mean_p']:7.2f} {b['hit_rate']:6.2f} "
                      f"{b['gap']:+7.2f} {b['mean_points']:+8.3f}")
    print(f"\n{'leader':28} {'n':>4} {'mean':>7} {'hit':>6} {'mean p':>7}")
    for l in leaders:
        if l["n_scored"]:
            flag = "" if l["ranked"] else "  (unranked)"
            print(f"{l['name'][:28]:28} {l['n_scored']:4} {l['mean_points']:+7.3f} "
                  f"{l['hit_rate']:6.2f} {l['mean_p']:7.2f}{flag}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
