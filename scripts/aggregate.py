#!/usr/bin/env python3
"""Aggregate per-transcript grades into per-leader scores.

Turns a pile of individual judgements into one leaderboard, and makes the
judgement calls in that turning explicit rather than burying them.

The four decisions this script makes, and why:

1. JUDGE CALIBRATION. Two judges rate the same transcripts, and one may be
   systematically harsher than the other. Averaging raw scores would then let
   whichever judge happened to grade more of a leader's transcripts move that
   leader. Each judge's scores are therefore centred and rescaled to the pooled
   mean and spread across everything that judge graded, so only DISAGREEMENT
   between judges moves a result, not a constant offset. Raw means are reported
   alongside, so the effect of this step is visible.

2. COVERAGE WEIGHTING. A transcript where the judge could only score 6 of 15
   sub-criteria carries less information than one where 14 were scored. Each
   transcript contributes with weight equal to its coverage.

3. NO VENUE ADJUSTMENT. A leader who only ever does soft interviews will score
   lower on insight, and that is left uncorrected. Correcting it would mean
   inventing a score for a conversation that never happened. The venue mix is
   reported instead, so a reader can see whose profile rests on easy rooms.

4. BLINDED IS THE PUBLISHED SCORE. Unblinded grades are computed too, and the
   difference between them is reported per leader as the reputation halo. It
   is never mixed into the published number.

Usage:
  aggregate.py --grades data/grades --roster data/roster/final.json \
      --transcripts data/transcripts_clean --out data/results.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]
DIM_LABEL = {"d1_clarity": "Clarity", "d2_insight": "Insight", "d3_technical_depth": "Technical depth"}
WEIGHTS = {"d1_clarity": 0.20, "d2_insight": 0.45, "d3_technical_depth": 0.35}
SUB_GROUPS = {
    "d1_clarity": ["C1", "C2", "C3", "C4"],
    "d2_insight": ["I1", "I2", "I3", "I4", "I5", "I6", "I7"],
    "d3_technical_depth": ["T1", "T2", "T3", "T4"],
}
MIN_TRANSCRIPTS_FOR_CONFIDENCE = 3


def load_grades(root: Path) -> list[dict]:
    out = []
    for path in root.rglob("*.json"):
        if "_raw" in path.parts:
            continue
        rec = json.loads(path.read_text())
        if "grade" not in rec:
            continue
        if rec.get("validation_errors"):
            # A grade that failed validation is excluded, and the exclusion is
            # counted in the run report rather than passed off as missing data.
            rec["_excluded"] = "validation_errors"
        out.append(rec)
    return out


def calibrate(grades: list[dict]) -> dict:
    """Map each judge's score distribution onto the pooled one, per dimension.

    Returns {(judge, mode, dim): (mean, sd)} plus the pooled targets, so a raw
    score can be converted with  pooled_mean + (raw - judge_mean) * (pooled_sd / judge_sd).
    A judge with near-zero spread is left untouched, since rescaling it would
    amplify noise.
    """
    by_jmd: dict[tuple, list[float]] = defaultdict(list)
    by_md: dict[tuple, list[float]] = defaultdict(list)
    for g in grades:
        if g.get("_excluded"):
            continue
        for dim in DIMS:
            v = g["grade"]["dimensions"][dim]["score"]
            by_jmd[(g["judge"], g["mode"], dim)].append(v)
            by_md[(g["mode"], dim)].append(v)

    params = {}
    for key, vals in by_jmd.items():
        judge, mode, dim = key
        pooled = by_md[(mode, dim)]
        jm = st.mean(vals)
        jsd = st.pstdev(vals) if len(vals) > 1 else 0.0
        pm = st.mean(pooled)
        psd = st.pstdev(pooled) if len(pooled) > 1 else 0.0
        params[key] = {
            "judge_mean": round(jm, 2), "judge_sd": round(jsd, 2),
            "pooled_mean": round(pm, 2), "pooled_sd": round(psd, 2),
            "n": len(vals),
            "rescaled": jsd >= 3.0,
        }
    return params


def apply_calibration(raw: float, key: tuple, params: dict) -> float:
    p = params.get(key)
    if not p or not p["rescaled"]:
        return raw
    scaled = p["pooled_mean"] + (raw - p["judge_mean"]) * (p["pooled_sd"] / p["judge_sd"])
    return max(1.0, min(100.0, scaled))


def weighted(pairs: list[tuple[float, float]]) -> float | None:
    """pairs of (value, weight)."""
    num = sum(v * w for v, w in pairs)
    den = sum(w for _, w in pairs)
    return num / den if den > 0 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", required=True)
    ap.add_argument("--roster", required=True)
    ap.add_argument("--transcripts", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-mixed-rubric", action="store_true",
                    help="Pool grades made under different rubric versions. Off by default, "
                         "because averaging scores from different rubrics is a silent "
                         "correctness failure rather than a loud one.")
    args = ap.parse_args()

    roster = json.loads(Path(args.roster).read_text())
    by_slug = {r["slug"]: r for r in roster["roster"]}
    grades = load_grades(Path(args.grades))
    if not grades:
        raise SystemExit("no grades found")

    excluded = [g for g in grades if g.get("_excluded")]
    usable = [g for g in grades if not g.get("_excluded")]

    # Pooling scores produced by different rubrics is a silent correctness
    # failure: the numbers still average, they just no longer mean the same
    # thing. Every grade carries the hash of the rubric and schema that made
    # it, so a mixed corpus is detected here and refused rather than averaged.
    contracts: dict[str, int] = defaultdict(int)
    for g in usable:
        contracts[(g.get("grading_contract") or {}).get("contract_id") or "unversioned"] += 1
    known = {k: v for k, v in contracts.items() if k != "unversioned"}
    if len(known) > 1:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(contracts.items()))
        msg = (f"REFUSING TO POOL: grades span {len(known)} different rubric versions ({detail}). "
               f"Scores from different rubrics are not comparable. Re-grade the older ones with "
               f"--force, or pass --allow-mixed-rubric to pool anyway and have the split reported "
               f"in the diagnostics.")
        if not args.allow_mixed_rubric:
            raise SystemExit(msg)
        print("WARNING: " + msg, file=sys.stderr)
    if contracts:
        print(f"grading contracts in corpus: {dict(contracts)}", file=sys.stderr)

    params = calibrate(usable)

    # Per (leader, transcript, mode): consensus of the judges that graded it.
    per_transcript: dict[tuple, dict] = defaultdict(lambda: defaultdict(list))
    for g in usable:
        key = (g["leader_slug"], g["source_id"], g["mode"])
        gr = g["grade"]
        cov = gr.get("coverage") or 0.0
        entry = per_transcript[key]
        for dim in DIMS:
            raw = gr["dimensions"][dim]["score"]
            cal = apply_calibration(raw, (g["judge"], g["mode"], dim), params)
            entry[f"raw_{dim}"].append(raw)
            entry[f"cal_{dim}"].append(cal)
        entry["coverage"].append(cov)
        entry["judges"].append(g["judge"])
        entry["venue_challenge"].append(gr.get("venue_challenge"))
        entry["identity_confident"].append(bool(gr.get("identity_confident")))
        entry["venue_type"].append(gr.get("venue_type"))

    transcripts_out = []
    for (slug, sid, mode), e in per_transcript.items():
        row = {"leader_slug": slug, "source_id": sid, "mode": mode,
               "judges": sorted(set(e["judges"])), "n_judges": len(e["judges"]),
               "coverage": round(st.mean(e["coverage"]), 3),
               "venue_challenge": round(st.mean([v for v in e["venue_challenge"] if v is not None]), 2)
               if any(v is not None for v in e["venue_challenge"]) else None,
               "venue_type": max(set(e["venue_type"]), key=e["venue_type"].count) if e["venue_type"] else None,
               "identity_recognised": any(e["identity_confident"])}
        for dim in DIMS:
            row[f"raw_{dim}"] = round(st.mean(e[f"raw_{dim}"]), 2)
            row[f"cal_{dim}"] = round(st.mean(e[f"cal_{dim}"]), 2)
            row[f"spread_{dim}"] = round(max(e[f"raw_{dim}"]) - min(e[f"raw_{dim}"]), 2) if len(e[f"raw_{dim}"]) > 1 else None
        row["cal_overall"] = round(sum(WEIGHTS[d] * row[f"cal_{d}"] for d in DIMS), 2)
        row["raw_overall"] = round(sum(WEIGHTS[d] * row[f"raw_{d}"] for d in DIMS), 2)
        transcripts_out.append(row)

    # Per leader, per mode.
    leaders_out = []
    by_leader_mode: dict[tuple, list[dict]] = defaultdict(list)
    for t in transcripts_out:
        by_leader_mode[(t["leader_slug"], t["mode"])].append(t)

    for slug, person in by_slug.items():
        blinded = by_leader_mode.get((slug, "blinded"), [])
        openm = by_leader_mode.get((slug, "open"), [])
        if not blinded and not openm:
            leaders_out.append({**person, "status": "no_grades", "n_transcripts": 0})
            continue

        def agg(rows: list[dict]) -> dict:
            if not rows:
                return {}
            out = {}
            for dim in DIMS:
                out[dim] = round(weighted([(r[f"cal_{dim}"], max(r["coverage"], 0.05)) for r in rows]), 1)
                out[f"{dim}_sd"] = round(st.pstdev([r[f"cal_{dim}"] for r in rows]), 1) if len(rows) > 1 else 0.0
            out["overall"] = round(sum(WEIGHTS[d] * out[d] for d in DIMS), 1)
            out["n_transcripts"] = len(rows)
            out["mean_coverage"] = round(st.mean([r["coverage"] for r in rows]), 3)
            vc = [r["venue_challenge"] for r in rows if r["venue_challenge"] is not None]
            out["mean_venue_challenge"] = round(st.mean(vc), 2) if vc else None
            out["venue_types"] = sorted({r["venue_type"] for r in rows if r["venue_type"]})
            out["identity_recognised_rate"] = round(
                sum(1 for r in rows if r["identity_recognised"]) / len(rows), 2)
            return out

        b, o = agg(blinded), agg(openm)
        halo = {}
        if b and o:
            for dim in DIMS:
                halo[dim] = round(o[dim] - b[dim], 1)
            halo["overall"] = round(o["overall"] - b["overall"], 1)

        n = b.get("n_transcripts", 0)
        judge_spread = [t[f"spread_{d}"] for t in blinded for d in DIMS if t.get(f"spread_{d}") is not None]
        leaders_out.append({
            **person,
            "status": "scored",
            "blinded": b,
            "open": o,
            "halo": halo,
            "n_transcripts": n,
            "confidence": "high" if n >= 5 else ("medium" if n >= MIN_TRANSCRIPTS_FOR_CONFIDENCE else "low"),
            "mean_judge_disagreement": round(st.mean(judge_spread), 1) if judge_spread else None,
        })

    scored = [l for l in leaders_out if l["status"] == "scored"]
    scored.sort(key=lambda l: l["blinded"].get("overall", 0), reverse=True)
    for i, l in enumerate(scored, 1):
        l["rank"] = i

    # Run-level diagnostics.
    all_b = [t for t in transcripts_out if t["mode"] == "blinded"]
    fable = [g for g in usable if g["judge"] == "fable" and g["mode"] == "blinded"]
    astra = [g for g in usable if g["judge"] == "astra" and g["mode"] == "blinded"]
    paired = defaultdict(dict)
    for g in usable:
        if g["mode"] == "blinded":
            paired[(g["leader_slug"], g["source_id"])][g["judge"]] = g["grade"]["overall"]
    both = [(v["fable"], v["astra"]) for v in paired.values() if "fable" in v and "astra" in v]
    corr = None
    if len(both) > 2:
        xs, ys = zip(*both)
        mx, my = st.mean(xs), st.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in both)
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        corr = round(num / den, 3) if den else None

    diagnostics = {
        "grading_contracts": dict(contracts),
        "rubric_versions_pooled": len(known),
        "grades_loaded": len(grades),
        "grades_used": len(usable),
        "grades_excluded_validation": len(excluded),
        "transcripts_with_blinded_consensus": len(all_b),
        "judge_call_counts": {"fable_blinded": len(fable), "astra_blinded": len(astra)},
        "judge_raw_means_blinded": {
            "fable": {d: round(st.mean([g["grade"]["dimensions"][d]["score"] for g in fable]), 1) for d in DIMS} if fable else {},
            "astra": {d: round(st.mean([g["grade"]["dimensions"][d]["score"] for g in astra]), 1) for d in DIMS} if astra else {},
        },
        "inter_judge_correlation_overall": corr,
        "mean_abs_judge_gap_overall": round(st.mean([abs(a - b) for a, b in both]), 1) if both else None,
        "blinding_leakage_rate": round(
            sum(1 for t in all_b if t["identity_recognised"]) / len(all_b), 3) if all_b else None,
        "leaders_below_min_transcripts": [l["slug"] for l in scored if l["n_transcripts"] < MIN_TRANSCRIPTS_FOR_CONFIDENCE],
        "calibration_params": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in params.items()},
        "weights": WEIGHTS,
    }

    # Audit payload: everything a human needs to agree or disagree with a score.
    audit: dict[str, list] = defaultdict(list)
    for g in usable:
        gr = g["grade"]
        audit[g["leader_slug"]].append({
            "source_id": g["source_id"],
            "judge": g["judge"],
            "mode": g["mode"],
            "venue_type": gr.get("venue_type"),
            "venue_challenge": gr.get("venue_challenge"),
            "subject_share_pct": gr.get("subject_speech_share_pct"),
            "coverage": gr.get("coverage"),
            "confidence": gr.get("confidence"),
            "asr_quality": gr.get("asr_quality"),
            "identity_guess": gr.get("identity_guess"),
            "identity_confident": gr.get("identity_confident"),
            "overall": gr.get("overall"),
            "salient_claims": gr.get("salient_claims", []),
            "red_flags": gr.get("red_flags", []),
            "dimensions": {
                d: {
                    "score": gr["dimensions"][d]["score"],
                    "reasoning": gr["dimensions"][d]["reasoning"],
                    "counterevidence": gr["dimensions"][d]["counterevidence"],
                    "evidence": gr["dimensions"][d].get("evidence", [])[:3],
                } for d in DIMS
            },
            "subcriteria": {s["code"]: {"score": s["score"], "justification": s["justification"]}
                            for s in gr.get("subcriteria", [])},
        })
    audit_path = Path(args.out).with_name(Path(args.out).stem + "_audit.json")
    audit_path.write_text(json.dumps(audit, indent=1))
    print(f"audit detail written to {audit_path}", file=sys.stderr)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({
        "diagnostics": diagnostics,
        "leaders": scored,
        "unscored": [l for l in leaders_out if l["status"] != "scored"],
        "transcripts": transcripts_out,
    }, indent=1))
    print(json.dumps(diagnostics, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
