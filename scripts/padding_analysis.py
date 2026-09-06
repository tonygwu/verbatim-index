#!/usr/bin/env python3
"""Analyse the P1 length-padding probe.

Question
--------
Composite score correlates +0.584 with transcript word count across 27 real
gradings. Does that reflect opportunity (a longer conversation lets more
sub-criteria be observed) or bias (the judge rewards bulk)?

Design
------
One real transcript, six padded variants that add words and no substance, one
blinded grading per judge per variant. The unpadded baseline is the mean of
the five existing repeats in data/grades_smoke.

Noise floor
-----------
Three thresholds are reported for every comparison, because they answer
slightly different questions and the reader should see the sensitivity.

  band_repo   4.3 points. The project-wide tie band quoted in the brief.
              Applies to any single comparison; the most familiar number.
  lsd_z       1.96 * SD * sqrt(1/n_pad + 1/n_base). Treats the calibration SD
              as if it were known exactly.
  lsd_t       t(0.975, df=4) * SD * sqrt(1/n_pad + 1/n_base) = 2.776 * ...
              Honest about the SD being estimated from only 5 repeats. This is
              the PRIMARY threshold. A delta is called real only if it clears
              this one.

SD comes from data/logs/calibration.json: composite SD 1.29 for Fable and 1.78
for Astra, with per-dimension SDs used for the per-dimension tests.

Slope
-----
If a bias exists it is quantified as points of composite per 1000 added words,
by ordinary least squares of the seven points (baseline delta 0 at 0 added
words, plus the six padded variants) per judge. The 95% interval uses t on
n-2 degrees of freedom.

Detection
---------
Judges are scored on whether they NOTICED the padding. Every free-text field
of the grade is searched for a padding vocabulary. The baseline gradings are
searched the same way, so what is reported is the RISE in hits over baseline,
not a raw count: the baseline already complains about "long customer-name
recitations", and counting that as detection would be wrong.

Usage
  python3 scripts/padding_analysis.py
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]
DIM_SHORT = {"d1_clarity": "clarity", "d2_insight": "insight", "d3_technical_depth": "technical"}
BAND_REPO = 4.3
T_DF4 = 2.776  # t(0.975, df=4)
Z95 = 1.96

# Words that would appear if a judge noticed the manipulation. Stems, matched
# case-insensitively against every free-text field of the grade.
DETECT_PATTERNS = {
    # Deliberately narrow. The rubric itself invites words like "repeatedly"
    # and "restate" in innocent senses ("a listener can restate his
    # positions"), so a loose stem match puts 5-10 false hits on every
    # baseline grade and drowns the signal. Every pattern below has been
    # checked against the five baseline gradings per judge, and the reported
    # number is always the RISE over that baseline floor.
    "repetition": (
        r"repetiti(?:on|ve|ous)|restatement|restating|reiterat"
        r"|restates? (?:the|his|her|its|each|every)"
        r"|repeat(?:s|ed|edly|ing)? (?:himself|herself|itself|the same|the point"
        r"|whole|entire|sentences|passages|material|content|verbatim)"
        r"|(?:says?|said|states?) the same thing"
        r"|same (?:point|sentence|claim|content|words) (?:again|twice|repeatedly|over)"
        r"|over and over|verbatim|duplicat"
    ),
    "padding": r"\bpadd(?:ed|ing)\b|\bfiller\b|\bbloat(?:ed|ing)?\b|\bwaffl(?:e|es|ing|y)\b|\bboilerplate\b",
    "verbosity": (
        r"verbos(?:e|ity)|wordy|prolix|long-?winded|rambl(?:e|es|ing)|meander"
        r"|circumlocut|\bdilut(?:e|ed|es|ing|ion)\b"
        r"|low(?:er)? (?:information|signal) (?:density|per word)"
        r"|adds? (?:nothing|little) new|no new (?:claim|information|content|substance|argument)"
        r"|signal-?to-?noise|words? per (?:idea|claim|point)|per word"
    ),
    "disfluency": r"disfluen|verbal tics?|filler words?|hedge words?|\bhalting\b|\bstumbl",
    "pleasantry": (
        r"pleasantr|niceties|small ?talk|thank(?:s|ing) the host|courtes(?:y|ies)"
        r"|filler sentences|social filler|contentless|empty (?:sentences|remarks|courtesies)"
    ),
    "offtopic": (
        r"off-?topic|digress(?:es|ion|ive|ions)?|tangent(?:ial)?|irrelevan|non-?sequitur"
        r"|unrelated aside"
    ),
}


def load_json(p: str | Path) -> dict:
    return json.loads(Path(p).read_text())


def free_text(grade: dict) -> dict[str, str]:
    """Every human-readable field of a grade, by field name."""
    out: dict[str, list[str]] = defaultdict(list)
    for d in DIMS:
        blk = grade.get("dimensions", {}).get(d, {})
        out[f"{DIM_SHORT[d]}.reasoning"].append(blk.get("reasoning", "") or "")
        out[f"{DIM_SHORT[d]}.counterevidence"].append(blk.get("counterevidence", "") or "")
        for ev in blk.get("evidence", []) or []:
            out[f"{DIM_SHORT[d]}.evidence"].append(ev.get("why_it_matters", "") or "")
    out["red_flags"].extend(grade.get("red_flags", []) or [])
    out["salient_claims"].extend(grade.get("salient_claims", []) or [])
    for k in ("venue_challenge_reason", "attribution_notes", "asr_notes",
              "confidence_reason", "identity_basis"):
        out[k].append(grade.get(k, "") or "")
    for sc in grade.get("subcriteria", []) or []:
        out["subcriteria.justification"].append(sc.get("justification", "") or "")
    return {k: "\n".join(v) for k, v in out.items()}


def detect(grade: dict) -> dict:
    fields = free_text(grade)
    hits: dict[str, list[dict]] = defaultdict(list)
    for cat, pat in DETECT_PATTERNS.items():
        rx = re.compile(pat, re.I)
        for fname, text in fields.items():
            for m in rx.finditer(text):
                lo = max(0, m.start() - 110)
                hi = min(len(text), m.end() + 110)
                hits[cat].append({"field": fname, "match": m.group(0),
                                  "context": " ".join(text[lo:hi].split())})
    return {
        "hits_by_category": {k: len(v) for k, v in hits.items()},
        "total_hits": sum(len(v) for v in hits.values()),
        "clarity_hits": sum(1 for v in hits.values() for h in v if h["field"].startswith("clarity")),
        "red_flag_hits": sum(1 for v in hits.values() for h in v if h["field"] == "red_flags"),
        "examples": {k: v[:6] for k, v in hits.items()},
    }


def mean(xs):
    return sum(xs) / len(xs)


def ols(x: list[float], y: list[float]) -> dict:
    n = len(x)
    mx, my = mean(x), mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    if sxx == 0:
        raise ValueError("no variation in x")
    b = sxy / sxx
    a = my - b * mx
    resid = [yi - (a + b * xi) for xi, yi in zip(x, y)]
    dof = n - 2
    if dof <= 0:
        return {"slope": b, "intercept": a, "se": None, "ci95": None, "dof": dof, "r2": None}
    s2 = sum(r * r for r in resid) / dof
    se = math.sqrt(s2 / sxx)
    tcrit = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365}.get(dof, 1.96)
    sst = sum((yi - my) ** 2 for yi in y)
    return {"slope": b, "intercept": a, "se": se, "dof": dof,
            "ci95": [b - tcrit * se, b + tcrit * se],
            "t": b / se if se else None,
            "r2": 1 - (sum(r * r for r in resid) / sst) if sst else None}


def collect_baseline(smoke_dir: Path, judges: list[str]) -> dict:
    base: dict[str, dict] = {}
    for judge in judges:
        recs = [load_json(p) for p in sorted(glob.glob(str(smoke_dir / judge / "*" / "*.json")))]
        recs = [r for r in recs if r["mode"] == "blinded"]
        if not recs:
            raise SystemExit(f"no baseline gradings for {judge} under {smoke_dir}")
        bad = [r for r in recs if r.get("validation_errors")]
        if bad:
            raise SystemExit(f"{judge}: {len(bad)} baseline gradings carry validation errors; "
                             f"refusing to average them")
        g = [r["grade"] for r in recs]
        base[judge] = {
            "n_repeats": len(g),
            "source_id": recs[0]["source_id"],
            "overall": {"mean": mean([x["overall"] for x in g]),
                        "sd": st.stdev([x["overall"] for x in g]),
                        "values": [x["overall"] for x in g]},
            "coverage": {"mean": mean([x["coverage"] for x in g]),
                         "sd": st.stdev([x["coverage"] for x in g]),
                         "values": [x["coverage"] for x in g]},
            "dims": {d: {"mean": mean([x["dimensions"][d]["score"] for x in g]),
                         "sd": st.stdev([x["dimensions"][d]["score"] for x in g]),
                         "values": [x["dimensions"][d]["score"] for x in g]}
                     for d in DIMS},
            "detection": [detect(x) for x in g],
        }
        rt = [(r["telemetry"].get("reasoning_output_tokens") if judge == "astra"
               else r["telemetry"].get("thinking_tokens")) for r in recs]
        rt = [x for x in rt if x is not None]
        base[judge]["reasoning_tokens"] = rt
        base[judge]["reasoning_min"] = min(rt) if rt else None
        base[judge]["detection_mean_hits"] = mean([d["total_hits"] for d in base[judge]["detection"]])
        base[judge]["detection_mean_clarity_hits"] = mean(
            [d["clarity_hits"] for d in base[judge]["detection"]])
        base[judge]["detection_mean_red_flag_hits"] = mean(
            [d["red_flag_hits"] for d in base[judge]["detection"]])
    return base


def thresholds(sd: float, n_pad: int, n_base: int) -> dict:
    se = sd * math.sqrt(1.0 / n_pad + 1.0 / n_base)
    return {"sd_calibration": sd, "se_of_difference": se,
            "lsd_t_df4": T_DF4 * se, "lsd_z": Z95 * se, "band_repo": BAND_REPO}


def verdict_for(delta: float, th: dict) -> str:
    """Name both thresholds explicitly.

    The two are not nested. For Astra the design-specific lsd_t (5.41 on a
    single variant) is LARGER than the repo's 4.3 tie band, so a ladder that
    checks one then the other reads wrong. A delta is only called real when it
    clears both.
    """
    a, b = abs(delta) >= th["lsd_t_df4"], abs(delta) >= BAND_REPO
    if a and b:
        return "beyond noise (clears lsd_t and 4.3)"
    if a:
        return f"clears lsd_t {th['lsd_t_df4']:.1f} only, inside 4.3"
    if b:
        return f"clears 4.3 only, inside lsd_t {th['lsd_t_df4']:.1f}"
    return "within noise"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/logs/padding_manifest.json")
    ap.add_argument("--probe", default="data/grades_probe")
    ap.add_argument("--baseline", default="data/grades_smoke")
    ap.add_argument("--calibration", default="data/logs/calibration.json")
    ap.add_argument("--errors", default="data/logs/probe_errors.jsonl")
    ap.add_argument("--out", default="data/logs/padding_probe.json")
    args = ap.parse_args()

    man = load_json(REPO / args.manifest)
    calib = load_json(REPO / args.calibration)
    judges = ["fable", "astra"]

    # ---- calibration SDs -------------------------------------------------
    sds = {}
    for j in judges:
        blk = calib["per_judge"][f"{j}|blinded"]
        sds[j] = {"overall": blk["overall"]["sd"],
                  **{d: blk["dimensions"][d]["sd"] for d in DIMS}}

    base = collect_baseline(REPO / args.baseline, judges)

    # ---- what was attempted / succeeded / failed -------------------------
    expected = [(j, c) for j in judges for c in man["variants"]]
    found: dict[tuple[str, str], dict] = {}
    invalid: list[dict] = []
    for p in sorted(glob.glob(str(REPO / args.probe / "*" / "*" / "*.json"))):
        r = load_json(p)
        code = r["source_id"].rsplit("-", 1)[-1]
        if code not in man["variants"]:
            continue
        if r.get("validation_errors"):
            invalid.append({"judge": r["judge"], "code": code, "path": p,
                            "validation_errors": r["validation_errors"]})
            continue
        found[(r["judge"], code)] = r

    errfile = REPO / args.errors
    logged_errors = []
    if errfile.exists():
        for line in errfile.read_text().splitlines():
            line = line.strip()
            if line:
                logged_errors.append(json.loads(line))

    missing = [{"judge": j, "code": c} for (j, c) in expected if (j, c) not in found]
    tax: dict[str, int] = defaultdict(int)
    for e in logged_errors:
        tax[e.get("error_type", "unknown")] += 1
    for _ in invalid:
        tax["schema_validation_failed_local_recheck"] += 1

    run = {
        "attempted": len(expected),
        "succeeded": len(found),
        "failed": len(missing),
        "invalid_schema": len(invalid),
        "error_taxonomy": dict(tax),
        "missing": missing,
        "invalid_detail": invalid,
        "harness_error_log": logged_errors,
    }

    # ---- per-variant deltas ---------------------------------------------
    rows = []
    for (j, code), r in sorted(found.items()):
        v = man["variants"][code]
        g = r["grade"]
        b = base[j]
        row = {
            "judge": j, "variant": code, "style": v["style"],
            "target_inflation": v["target_inflation"],
            "realised_inflation": v["realised_inflation"],
            "words_added": v["words_added"],
            "word_count": v["word_count"],
            "transcript_id": r["transcript_id"],
            "graded_at_utc": r["graded_at_utc"],
            "elapsed_sec": r["elapsed_sec"],
            "judge_model": r["telemetry"].get("judge_model") or r["telemetry"].get("requested_model"),
            # Served-effort provenance. grade.py only rejects a call whose
            # reasoning-token count is zero, so a call can pass identity and
            # still have run at far less reasoning than the baseline did. Any
            # probe call below the baseline minimum is flagged rather than
            # dropped, because dropping it would make the arms asymmetric.
            "reasoning_tokens": (r["telemetry"].get("reasoning_output_tokens")
                                 if j == "astra" else r["telemetry"].get("thinking_tokens")),
            "baseline_overall": round(b["overall"]["mean"], 2),
            "padded_overall": g["overall"],
            "delta_overall": round(g["overall"] - b["overall"]["mean"], 2),
            "coverage_baseline": b["coverage"]["mean"],
            "coverage_padded": g["coverage"],
            "coverage_delta": round(g["coverage"] - b["coverage"]["mean"], 4),
            "dims": {},
            "detection": detect(g),
            # The lexical scan is a screen, not the evidence. The full text a
            # human needs in order to judge whether the judge noticed the
            # padding is carried here verbatim.
            "qualitative": {
                "clarity_reasoning": g["dimensions"]["d1_clarity"].get("reasoning", ""),
                "clarity_counterevidence": g["dimensions"]["d1_clarity"].get("counterevidence", ""),
                "insight_counterevidence": g["dimensions"]["d2_insight"].get("counterevidence", ""),
                "technical_counterevidence":
                    g["dimensions"]["d3_technical_depth"].get("counterevidence", ""),
                "red_flags": g.get("red_flags", []),
                "confidence_reason": g.get("confidence_reason", ""),
            },
        }
        row["baseline_reasoning_tokens_min"] = b["reasoning_min"]
        row["effort_below_baseline_min"] = (
            row["reasoning_tokens"] is not None and b["reasoning_min"] is not None
            and row["reasoning_tokens"] < b["reasoning_min"])
        th = thresholds(sds[j]["overall"], 1, b["n_repeats"])
        row["thresholds_overall"] = {k: round(x, 3) for k, x in th.items()}
        row["verdict_overall"] = verdict_for(row["delta_overall"], th)
        for d in DIMS:
            dth = thresholds(sds[j][d], 1, b["n_repeats"])
            delta = g["dimensions"][d]["score"] - b["dims"][d]["mean"]
            row["dims"][DIM_SHORT[d]] = {
                "baseline": round(b["dims"][d]["mean"], 2),
                "padded": g["dimensions"][d]["score"],
                "delta": round(delta, 2),
                "lsd_t_df4": round(dth["lsd_t_df4"], 2),
                "verdict": verdict_for(delta, dth),
            }
        # Clarity carries only 20% of the composite, so a clarity penalty is
        # heavily damped before it reaches the headline number. Decompose the
        # composite delta into each dimension's weighted contribution, or a
        # flat composite can hide a real and correct clarity penalty.
        wts = {"clarity": 0.20, "insight": 0.45, "technical": 0.35}
        row["composite_decomposition"] = {
            k: round(wts[k] * row["dims"][k]["delta"], 3) for k in wts}
        row["composite_decomposition"]["sum"] = round(
            sum(wts[k] * row["dims"][k]["delta"] for k in wts), 3)
        row["detection_rise_total"] = round(
            row["detection"]["total_hits"] - base[j]["detection_mean_hits"], 2)
        row["detection_rise_clarity"] = round(
            row["detection"]["clarity_hits"] - base[j]["detection_mean_clarity_hits"], 2)
        row["detection_rise_red_flags"] = round(
            row["detection"]["red_flag_hits"] - base[j]["detection_mean_red_flag_hits"], 2)
        rows.append(row)

    # ---- pooled test and slope, per judge --------------------------------
    per_judge = {}
    for j in judges:
        jr = [r for r in rows if r["judge"] == j]
        if not jr:
            per_judge[j] = {"n_padded": 0, "note": "no successful padded gradings"}
            continue
        b = base[j]
        deltas = [r["delta_overall"] for r in jr]
        pooled_th = thresholds(sds[j]["overall"], len(jr), b["n_repeats"])
        x = [0.0] + [r["words_added"] / 1000.0 for r in jr]
        y = [0.0] + deltas
        fit = ols(x, y)
        per_style = {}
        for style in sorted({r["style"] for r in jr}):
            sr = sorted([r for r in jr if r["style"] == style], key=lambda r: r["words_added"])
            per_style[style] = {
                "points": [{"target": r["target_inflation"], "words_added": r["words_added"],
                            "delta_overall": r["delta_overall"],
                            "verdict": r["verdict_overall"],
                            "delta_clarity": r["dims"]["clarity"]["delta"],
                            "delta_insight": r["dims"]["insight"]["delta"],
                            "delta_technical": r["dims"]["technical"]["delta"]} for r in sr],
                "mean_delta_overall": round(mean([r["delta_overall"] for r in sr]), 2),
                "slope_pts_per_1k_added_words": (
                    round((sr[-1]["delta_overall"] - sr[0]["delta_overall"])
                          / ((sr[-1]["words_added"] - sr[0]["words_added"]) / 1000.0), 3)
                    if len(sr) > 1 else None),
            }
        per_judge[j] = {
            "n_padded": len(jr),
            "baseline_overall_mean": round(b["overall"]["mean"], 2),
            "baseline_overall_sd": round(b["overall"]["sd"], 3),
            "baseline_repeats": b["n_repeats"],
            "calibration_sd_used": sds[j]["overall"],
            "mean_delta_overall": round(mean(deltas), 2),
            "min_delta_overall": round(min(deltas), 2),
            "max_delta_overall": round(max(deltas), 2),
            "pooled_thresholds": {k: round(v, 3) for k, v in pooled_th.items()},
            "pooled_verdict": verdict_for(mean(deltas), pooled_th),
            "slope_pts_per_1k_added_words": round(fit["slope"], 4),
            "slope_ci95": [round(c, 4) for c in fit["ci95"]] if fit["ci95"] else None,
            "slope_se": round(fit["se"], 4) if fit["se"] else None,
            "slope_r2": round(fit["r2"], 3) if fit["r2"] is not None else None,
            "slope_excludes_zero": bool(fit["ci95"] and (fit["ci95"][0] > 0 or fit["ci95"][1] < 0)),
            "implied_bias_over_corpus_range_19k_words": round(fit["slope"] * 19, 2),
            "per_style": per_style,
            "weighted_contribution_mean": {
                k: round(mean([r["composite_decomposition"][k] for r in jr]), 3)
                for k in ("clarity", "insight", "technical")},
            "dim_summary": {
                DIM_SHORT[d]: {
                    "baseline": round(b["dims"][d]["mean"], 2),
                    "mean_delta": round(mean([r["dims"][DIM_SHORT[d]]["delta"] for r in jr]), 2),
                    "lsd_t_df4_single": round(thresholds(sds[j][d], 1, b["n_repeats"])["lsd_t_df4"], 2),
                    "lsd_t_df4_pooled": round(
                        thresholds(sds[j][d], len(jr), b["n_repeats"])["lsd_t_df4"], 2),
                    "n_beyond_noise": sum(
                        1 for r in jr
                        if r["dims"][DIM_SHORT[d]]["verdict"].startswith("beyond noise")),
                } for d in DIMS},
            "coverage": {
                "baseline_mean": b["coverage"]["mean"],
                "baseline_at_ceiling": b["coverage"]["mean"] >= 1.0,
                "padded_values": [r["coverage_padded"] for r in jr],
                "n_rose": sum(1 for r in jr if r["coverage_delta"] > 0),
                "n_fell": sum(1 for r in jr if r["coverage_delta"] < 0),
            },
            "served_effort": {
                "baseline_reasoning_tokens": b["reasoning_tokens"],
                "baseline_min": b["reasoning_min"],
                "padded_reasoning_tokens": {r["variant"]: r["reasoning_tokens"] for r in jr},
                "n_below_baseline_min": sum(1 for r in jr if r["effort_below_baseline_min"]),
                "variants_below_baseline_min": [r["variant"] for r in jr
                                                if r["effort_below_baseline_min"]],
            },
            "detection": {
                "baseline_mean_hits": round(b["detection_mean_hits"], 2),
                "baseline_mean_clarity_hits": round(b["detection_mean_clarity_hits"], 2),
                "baseline_mean_red_flag_hits": round(b["detection_mean_red_flag_hits"], 2),
                "padded_mean_hits": round(mean([r["detection"]["total_hits"] for r in jr]), 2),
                "padded_mean_clarity_hits": round(mean([r["detection"]["clarity_hits"] for r in jr]), 2),
                "padded_mean_red_flag_hits": round(mean([r["detection"]["red_flag_hits"] for r in jr]), 2),
                "n_variants_with_rise": sum(1 for r in jr if r["detection_rise_total"] > 0),
            },
        }

    out = {
        "probe": "P1_length_padding",
        "generated_from": {
            "manifest": args.manifest,
            "baseline_grades": args.baseline,
            "probe_grades": args.probe,
            "calibration": args.calibration,
        },
        "baseline_transcript": man["baseline"],
        "noise_floor_note": (
            "lsd_t_df4 is the primary threshold: t(0.975,df=4) * SD * "
            "sqrt(1/n_padded + 1/n_baseline), with SD from calibration.json (5 repeats, "
            "df=4). band_repo 4.3 is the project-wide tie band quoted in the brief. "
            "lsd_z is the same as lsd_t but with 1.96, which pretends the SD is known."),
        "run": run,
        "per_judge": per_judge,
        "variants": rows,
    }

    outp = REPO / args.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1))

    render(out)
    print(f"\nwrote {outp}")
    return 0


# --------------------------------------------------------------------------


def render(out: dict) -> None:
    r = out["run"]
    print("=" * 96)
    print("P1 LENGTH-PADDING PROBE")
    print("=" * 96)
    print(f"baseline transcript : {out['baseline_transcript']['transcript_id']}  "
          f"{out['baseline_transcript']['word_count']} words, "
          f"{out['baseline_transcript']['duration_sec']}s")
    print(f"grading calls       : attempted {r['attempted']}  succeeded {r['succeeded']}  "
          f"failed {r['failed']}  invalid_schema {r['invalid_schema']}")
    print(f"error taxonomy      : {r['error_taxonomy'] or '{} (none)'}")
    if r["missing"]:
        print(f"MISSING             : {r['missing']}")
    if r["invalid_detail"]:
        for d in r["invalid_detail"]:
            print(f"INVALID             : {d['judge']}/{d['code']} {d['validation_errors']}")

    for j, pj in out["per_judge"].items():
        if not pj.get("n_padded"):
            print(f"\n--- {j.upper()} --- no successful padded gradings")
            continue
        print()
        print("-" * 96)
        print(f"{j.upper()}   baseline composite {pj['baseline_overall_mean']} "
              f"(mean of {pj['baseline_repeats']} repeats, SD {pj['baseline_overall_sd']})")
        th = pj["pooled_thresholds"]
        single = th["sd_calibration"] * T_DF4 * math.sqrt(1 + 1 / pj["baseline_repeats"])
        print(f"       noise floor: single variant vs baseline needs |delta| > "
              f"{single:.2f} (lsd_t) ; repo band {BAND_REPO}")
        print(f"       pooled over {pj['n_padded']} variants needs |mean delta| > "
              f"{th['lsd_t_df4']:.2f}")
        print("-" * 96)
        hdr = (f"{'variant':<8}{'style':<10}{'target':>7}{'+words':>8}"
               f"{'comp':>7}{'d.comp':>8}{'d.clar':>8}{'d.insi':>8}{'d.tech':>8}"
               f"{'cov':>6}{'detect':>8}  verdict")
        print(hdr)
        for row in sorted([v for v in out["variants"] if v["judge"] == j],
                          key=lambda v: (v["style"], v["words_added"])):
            d = row["dims"]
            print(f"{row['variant']:<8}{row['style']:<10}"
                  f"{int(row['target_inflation']*100):>6}%{row['words_added']:>8}"
                  f"{row['padded_overall']:>7.1f}{row['delta_overall']:>+8.1f}"
                  f"{d['clarity']['delta']:>+8.1f}{d['insight']['delta']:>+8.1f}"
                  f"{d['technical']['delta']:>+8.1f}"
                  f"{row['coverage_padded']:>6.2f}{row['detection_rise_total']:>+8.1f}"
                  f"  {row['verdict_overall']}")
        print(f"{'':<8}{'MEAN':<10}{'':>7}{'':>8}{'':>7}{pj['mean_delta_overall']:>+8.1f}"
              f"{pj['dim_summary']['clarity']['mean_delta']:>+8.1f}"
              f"{pj['dim_summary']['insight']['mean_delta']:>+8.1f}"
              f"{pj['dim_summary']['technical']['mean_delta']:>+8.1f}"
              f"{'':>6}{'':>8}  {pj['pooled_verdict']}")
        print(f"       slope {pj['slope_pts_per_1k_added_words']:+.3f} composite points per 1000 "
              f"added words, 95% CI [{pj['slope_ci95'][0]:+.3f}, {pj['slope_ci95'][1]:+.3f}], "
              f"R2 {pj['slope_r2']}, excludes zero: {pj['slope_excludes_zero']}")
        print(f"       implied over the corpus 11k-30k range (19k words): "
              f"{pj['implied_bias_over_corpus_range_19k_words']:+.1f} composite points")
        se_ = pj["served_effort"]
        print(f"       served effort: baseline reasoning tokens {se_['baseline_reasoning_tokens']} "
              f"(min {se_['baseline_min']}); padded {se_['padded_reasoning_tokens']}; "
              f"below baseline min: {se_['variants_below_baseline_min'] or 'none'}")
        cov = pj["coverage"]
        print(f"       coverage: baseline {cov['baseline_mean']} "
              f"(at ceiling: {cov['baseline_at_ceiling']}), padded {cov['padded_values']}, "
              f"rose in {cov['n_rose']}, fell in {cov['n_fell']}")
        det = pj["detection"]
        print(f"       padding vocabulary: baseline {det['baseline_mean_hits']} hits/grade "
              f"-> padded {det['padded_mean_hits']}; clarity field "
              f"{det['baseline_mean_clarity_hits']} -> {det['padded_mean_clarity_hits']}; "
              f"red_flags {det['baseline_mean_red_flag_hits']} -> "
              f"{det['padded_mean_red_flag_hits']}; rose in "
              f"{det['n_variants_with_rise']}/{pj['n_padded']} variants")
        wc = pj["weighted_contribution_mean"]
        print(f"       composite decomposition of the mean delta: clarity {wc['clarity']:+.2f} "
              f"(20% weight) + insight {wc['insight']:+.2f} (45%) + technical "
              f"{wc['technical']:+.2f} (35%)")
        for style, sv in pj["per_style"].items():
            print(f"       {style:<9} mean delta {sv['mean_delta_overall']:+.1f}  "
                  f"within-style slope {sv['slope_pts_per_1k_added_words']} pts/1k words")


if __name__ == "__main__":
    raise SystemExit(main())
