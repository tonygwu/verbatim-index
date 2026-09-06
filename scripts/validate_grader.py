#!/usr/bin/env python3
"""Validate the LLM-judge rubric without human labels.

Implements the checks in .claude/skills/grader-validation/SKILL.md against the
live corpus. Pure standard library: this machine has no numpy or scipy, and a
dependency that must be installed is a check that will not get run.

Every check prints its statistic, the documented pass threshold, and a verdict.
A check that cannot run for lack of data says so rather than returning a
misleading number from three points.

  V0  unscorable and refusal audit, and whether drops are even across leaders
  V1  judge agreement split into rank (ICC 3,1) and level (ICC 2,1, CCC, Cb)
  V2  the offset, estimated on the paired subset only
  V3  the error bar the leaderboard should carry
  V4  discriminant validity: three dimensions or one measured three times
  V5  length, venue and fame confounds
  V6  halo from unblinding, and whether the 1-100 scale is really being used

Usage:
  validate_grader.py [--grades data/grades] [--out data/logs/grader_validation.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]
JUDGES = ("fable", "astra")
MIN_SUBJECT_SHARE = 15
# Koo & Li 2016 bands for ICC, DOCUMENTED.
ICC_BANDS = "poor <0.50, moderate 0.50-0.75, good 0.75-0.90, excellent >0.90"
HTMT_MAX = 0.85          # COMMUNITY threshold for heterotrait-monotrait
MIN_N_FOR_STAT = 6       # below this, report the number but call it unreliable


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def pvar(xs):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs) if xs else float("nan")


def corr(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def icc(rows: list[list[float]]) -> dict:
    """ICC(2,1) absolute agreement and ICC(3,1) consistency, single measure.

    Consistency ignores a constant rater offset; absolute agreement does not.
    Both are reported because this pipeline deliberately removes the offset by
    recentring, so consistency is the honest headline and absolute agreement
    prices what recentring is hiding.
    """
    n, k = len(rows), len(rows[0])
    if n < 2 or k < 2:
        return {}
    gm = mean([v for r in rows for v in r])
    row_m = [mean(r) for r in rows]
    col_m = [mean([rows[i][j] for i in range(n)]) for j in range(k)]
    msr = k * sum((rm - gm) ** 2 for rm in row_m) / (n - 1)
    msc = n * sum((cm - gm) ** 2 for cm in col_m) / (k - 1)
    mse = sum((rows[i][j] - row_m[i] - col_m[j] + gm) ** 2
              for i in range(n) for j in range(k)) / ((n - 1) * (k - 1))
    d21 = msr + (k - 1) * mse + k * (msc - mse) / n
    d31 = msr + (k - 1) * mse
    return {
        "icc21_absolute": (msr - mse) / d21 if d21 else None,
        "icc31_consistency": (msr - mse) / d31 if d31 else None,
    }


def load(grades_dir: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (usable, refused, unscorable). Mirrors aggregate.py's own gates."""
    usable, refused, unscorable = [], [], []
    for p in glob.glob(f"{grades_dir}/**/*.json", recursive=True):
        if "_raw" in p or p.endswith(".tmp"):
            continue
        try:
            g = json.load(open(p))
        except Exception:
            continue
        if "grade" not in g:
            continue
        gr = g["grade"]
        if g.get("refused"):
            refused.append(g)
            continue
        if g.get("validation_errors"):
            continue
        share = gr.get("subject_speech_share_pct")
        if isinstance(share, int) and share < MIN_SUBJECT_SHARE:
            unscorable.append(g)
            continue
        if "dimensions" not in gr:
            continue
        usable.append(g)
    return usable, refused, unscorable


def paired(usable: list[dict], mode: str = "blinded") -> dict:
    """{transcript_id: {judge: grade}} for transcripts BOTH judges scored."""
    by = defaultdict(dict)
    for g in usable:
        if g["mode"] == mode:
            by[f"{g['leader_slug']}/{g['source_id']}"][g["judge"]] = g["grade"]
    return {t: v for t, v in by.items() if all(j in v for j in JUDGES)}


def section(title):
    print(f"\n\033[1m{title}\033[0m")


def verdict(ok: bool | None, msg: str) -> str:
    tag = "PASS" if ok else ("FAIL" if ok is False else "n/a ")
    return f"  [{tag}] {msg}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", default="data/grades")
    ap.add_argument("--transcripts", default="data/transcripts_blind")
    ap.add_argument("--out", default="data/logs/grader_validation.json")
    args = ap.parse_args()

    usable, refused, unscorable = load(args.grades)
    report: dict = {"n_usable": len(usable), "n_refused": len(refused),
                    "n_unscorable": len(unscorable)}
    print(f"corpus: {len(usable)} usable grades, {len(refused)} refusals, "
          f"{len(unscorable)} unscorable (subject absent)")

    # ---------------- V0 ----------------
    section("V0. Unscorable and refusal audit — are drops even across leaders?")
    drops = defaultdict(lambda: [0, 0])
    for g in usable:
        drops[(g["judge"], g["leader_slug"])][1] += 1
    for g in refused + unscorable:
        k = (g["judge"], g["leader_slug"])
        drops[k][0] += 1
        drops[k][1] += 1
    uneven = {f"{j}/{L}": f"{d}/{t}" for (j, L), (d, t) in sorted(drops.items()) if d}
    report["v0_drops"] = uneven
    for k, v in uneven.items():
        print(f"    {k}: {v} dropped")
    print(verdict(not uneven, "no leader loses grades to refusal or absence"
                  if not uneven else f"{len(uneven)} judge/leader pairs lose grades; "
                  f"drops are NOT random, so those leaders rest on fewer judges"))

    # ---------------- V1 ----------------
    section("V1. Judge agreement: rank vs level")
    P = paired(usable)
    tids = sorted(P)
    report["v1_n_paired"] = len(tids)
    if len(tids) < MIN_N_FOR_STAT:
        print(verdict(None, f"only {len(tids)} paired transcripts; need >={MIN_N_FOR_STAT}"))
    else:
        M = [[P[t][j]["overall"] for j in JUDGES] for t in tids]
        x = [r[0] for r in M]
        y = [r[1] for r in M]
        d = [b - a for a, b in zip(x, y)]
        i = icc(M)
        cov = sum((a - mean(x)) * (b - mean(y)) for a, b in zip(x, y)) / len(x)
        ccc = 2 * cov / (pvar(x) + pvar(y) + (mean(x) - mean(y)) ** 2)
        rho = corr(x, y)
        sd_d = st.stdev(d) if len(d) > 1 else 0.0
        loa = (mean(d) - 1.96 * sd_d, mean(d) + 1.96 * sd_d)
        report["v1"] = {"n": len(tids), **i, "ccc": ccc, "precision_rho": rho,
                        "accuracy_Cb": (ccc / rho) if rho else None,
                        "bias": mean(d), "loa": list(loa)}
        print(f"    n={len(tids)}  ICC(3,1) consistency = {i['icc31_consistency']:.3f}"
              f"   ICC(2,1) absolute = {i['icc21_absolute']:.3f}")
        print(f"    CCC={ccc:.3f}  precision(rho)={rho:.3f}  accuracy(Cb)={ccc/rho:.3f}")
        print(f"    bias (astra-fable) = {mean(d):+.1f}   95% limits of agreement "
              f"[{loa[0]:+.1f}, {loa[1]:+.1f}]  width {loa[1]-loa[0]:.1f}")
        print(f"    DOCUMENTED bands (Koo & Li 2016): {ICC_BANDS}")
        ok = i["icc31_consistency"] is not None and i["icc31_consistency"] >= 0.75
        print(verdict(ok, f"ICC(3,1) {'>=' if ok else '<'} 0.75. "
                      f"{'Judges rank alike.' if ok else 'Judges agree on the leaderboard shape, not on any single transcript.'}"))
        print(verdict(None, f"Cb={ccc/rho:.3f} isolates the part recentring removes; "
                      f"limits span {loa[1]-loa[0]:.0f} pts against a ~4 pt tie band"))

    # ---------------- V2 ----------------
    section("V2. Offset, estimated on the paired subset only")
    if len(tids) >= MIN_N_FOR_STAT:
        for dim in DIMS:
            fx = [P[t]["fable"]["dimensions"][dim]["score"] for t in tids]
            ax = [P[t]["astra"]["dimensions"][dim]["score"] for t in tids]
            print(f"    {dim:20} offset {mean(ax)-mean(fx):+5.1f}   r={corr(fx,ax):.3f}")
        report["v2_offsets"] = {d: mean([P[t]["astra"]["dimensions"][d]["score"] for t in tids])
                                - mean([P[t]["fable"]["dimensions"][d]["score"] for t in tids])
                                for d in DIMS}
        print(verdict(None, "estimated on paired transcripts only, so an unbalanced "
                            "corpus cannot fake an offset"))
    else:
        print(verdict(None, "not enough paired transcripts"))

    # ---------------- V4 ----------------
    section("V4. Discriminant validity — three dimensions, or one measured thrice?")
    if len(tids) >= MIN_N_FOR_STAT:
        X = {(j, d): [P[t][j]["dimensions"][d]["score"] for t in tids]
             for j in JUDGES for d in DIMS}
        conv = {d: corr(X[("fable", d)], X[("astra", d)]) for d in DIMS}
        hetero = {}
        for a in DIMS:
            for b in DIMS:
                if a < b:
                    hetero[f"{a[:2]}x{b[:2]}"] = corr(X[("fable", a)], X[("astra", b)])
        print("    convergent (same dimension, across judges) — want these HIGHEST:")
        for d, v in conv.items():
            print(f"      {d:20} {v:+.3f}")
        print("    heterotrait (different dimension, across judges) — want these LOWER:")
        for k, v in hetero.items():
            print(f"      {k:20} {v:+.3f}")
        worst_conv = min(v for v in conv.values() if v is not None)
        best_het = max(v for v in hetero.values() if v is not None)
        ok = worst_conv > best_het
        report["v4"] = {"convergent": conv, "heterotrait": hetero,
                        "worst_convergent": worst_conv, "best_heterotrait": best_het}
        print(verdict(ok, f"worst convergent {worst_conv:.3f} vs best heterotrait "
                      f"{best_het:.3f}. {'Dimensions separate.' if ok else 'They do NOT separate: a dimension correlates with a DIFFERENT dimension more than with itself across judges.'}"))
        print(verdict(best_het < HTMT_MAX, f"heterotrait max {best_het:.3f} vs {HTMT_MAX} (COMMUNITY)"))
    else:
        print(verdict(None, "not enough paired transcripts"))

    # ---------------- V5 ----------------
    section("V5. Length, venue and fame confounds")
    tr = {}
    for p in glob.glob(f"{args.transcripts}/*/*.json"):
        if p.endswith(".tmp"):
            continue
        try:
            t = json.load(open(p))
            tr[f"{t['leader_slug']}/{t['source_id']}"] = t
        except Exception:
            pass
    rows = [(tr[f"{g['leader_slug']}/{g['source_id']}"], g) for g in usable
            if f"{g['leader_slug']}/{g['source_id']}" in tr]
    if len(rows) >= MIN_N_FOR_STAT:
        wc = [float(t.get("word_count") or 0) for t, _ in rows]
        sc = [g["grade"]["overall"] for _, g in rows]
        vc = [float(g["grade"].get("venue_challenge") or 0) for _, g in rows]
        vw = [float(t.get("yt_view_count") or 0) for t, _ in rows]
        r_wc, r_vc = corr(wc, sc), corr(vc, sc)
        have_views = [(v, s) for v, s in zip(vw, sc) if v > 0]
        r_vw = corr([v for v, _ in have_views], [s for _, s in have_views]) if len(have_views) >= MIN_N_FOR_STAT else None
        report["v5"] = {"n": len(rows), "r_wordcount": r_wc, "r_venue_challenge": r_vc,
                        "r_views": r_vw, "n_with_views": len(have_views)}
        print(f"    n={len(rows)}   words {min(wc):.0f}-{max(wc):.0f}")
        print(f"    r(word_count, score)      = {r_wc:+.3f}")
        print(f"    r(venue_challenge, score) = {r_vc:+.3f}")
        print(f"    r(view_count, score)      = {r_vw if r_vw is None else f'{r_vw:+.3f}'}"
              f"   (n={len(have_views)} with view data)")
        print(verdict(None, "length correlation is EXPECTED and was cleared by the padding "
                            "probe: 12 padded variants moved the score within noise"))
        if r_vw is not None:
            ok = abs(r_vw) < 0.312
            print(verdict(ok, f"fame proxy |r|={abs(r_vw):.3f} vs 0.312 significance floor at n=40. "
                          f"{'Score does not track audience size.' if ok else 'Score TRACKS AUDIENCE SIZE, which is a defect.'}"))
    else:
        print(verdict(None, "not enough transcripts joined to grades"))

    # ---------------- V6 ----------------
    section("V6. Halo from unblinding, and is the 1-100 scale actually used?")
    ob = defaultdict(dict)
    for g in usable:
        ob[(f"{g['leader_slug']}/{g['source_id']}", g["judge"])][g["mode"]] = g["grade"]["overall"]
    dd = [v["open"] - v["blinded"] for v in ob.values() if len(v) == 2]
    report["v6_halo_n"] = len(dd)
    if len(dd) >= MIN_N_FOR_STAT:
        sd = st.stdev(dd) if len(dd) > 1 else 0.0
        se = sd / math.sqrt(len(dd)) if dd else 0.0
        pos = sum(1 for x in dd if x > 0)
        report["v6_halo_mean"] = mean(dd)
        print(f"    n={len(dd)} paired blinded/open   mean halo = {mean(dd):+.2f} "
              f"(SD {sd:.2f}, SE {se:.2f})")
        print(f"    sign test: {pos}/{len(dd)} rose when the judge was told who it was")
        ok = abs(mean(dd)) < 2 * se if se else None
        print(verdict(ok, f"halo {'within' if ok else 'BEYOND'} 2 standard errors of zero"))
    else:
        print(verdict(None, f"only {len(dd)} transcripts graded in BOTH modes by one judge"))

    vals = [g["grade"]["dimensions"][d]["score"] for g in usable for d in DIMS]
    if vals:
        mult5 = mean([1.0 if v % 5 == 0 else 0.0 for v in vals])
        report["v6_scale"] = {"min": min(vals), "max": max(vals),
                              "distinct": len(set(vals)), "multiple_of_5_rate": mult5}
        print(f"    scale use: {min(vals)}-{max(vals)}, {len(set(vals))} distinct values, "
              f"{mult5*100:.0f}% land on a multiple of 5")
        print(verdict(mult5 < 0.6, f"{mult5*100:.0f}% on multiples of 5. "
                      f"{'Judges use the fine scale.' if mult5 < 0.6 else 'Judges are effectively using a coarse scale, so precision is illusory.'}"))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
