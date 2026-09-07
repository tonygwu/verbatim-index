#!/usr/bin/env python3
"""Guards for the venue adjustment added 2026-09-07, and for error-log timestamps.

MEASURED before writing this. Transcript scores vary by the FORMAT of the
appearance, and leaders are not evenly spread across formats: some are 100%
long-form podcast, others 0%. Reading the raw means as a format effect overstates
it, because the people who do long podcasts differ from the people who only give
keynotes. Fitting leader and venue together separates the two:

  raw spread across venue types          8.2 points
  spread with the leader held fixed      5.7 points  (podcast +3.6, tv_interview -6.1)
  leaders whose rank changes             25/40, mean 1.1 places, max 5

  .venv/bin/python scripts/test_venue_calibration.py
"""
from __future__ import annotations
import importlib.util, json, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(Path(sys.executable))
PASS, FAIL = [], []

def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")

def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_m", REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


# ---------------------------------------------------------------------------
# 1. The fit must recover an effect it was given, and must not invent one.
# ---------------------------------------------------------------------------
def test_recovers_a_known_effect():
    print("\n[1] the fit recovers a planted venue effect and separates it from the leader")
    a = load("aggregate")
    # Two leaders, genuinely 10 points apart. Two venues, genuinely 6 apart.
    # Crucially the venue MIX is unbalanced, which is the situation that makes
    # raw means lie: the strong leader mostly appears in the generous venue.
    rows = []
    for i in range(9): rows.append({"leader_slug": "strong", "venue_type": "pod", "cal_overall": 70 + 3 + (i % 3 - 1)})
    for i in range(1): rows.append({"leader_slug": "strong", "venue_type": "tv",  "cal_overall": 70 - 3})
    for i in range(1): rows.append({"leader_slug": "weak",   "venue_type": "pod", "cal_overall": 60 + 3})
    for i in range(9): rows.append({"leader_slug": "weak",   "venue_type": "tv",  "cal_overall": 60 - 3 + (i % 3 - 1)})

    eff = a.venue_effects(rows)
    check("it finds the generous venue is generous", eff["pod"] > eff["tv"], f"{eff}")
    check("the venue gap it recovers is close to the planted 6 points",
          abs((eff["pod"] - eff["tv"]) - 6.0) < 1.0, f"gap={eff['pod']-eff['tv']:.2f} {eff}")
    check("venue effects are centred, so the overall level is unchanged",
          abs(sum(eff.values())) < 1e-6, f"{eff}")

    adj = a.apply_venue_adjustment(rows, eff)
    by = {}
    for r in adj:
        by.setdefault(r["leader_slug"], []).append(r["cal_overall_venue_adj"])
    gap = sum(by["strong"]) / len(by["strong"]) - sum(by["weak"]) / len(by["weak"])
    raw = (sum(r["cal_overall"] for r in rows if r["leader_slug"] == "strong") / 10
           - sum(r["cal_overall"] for r in rows if r["leader_slug"] == "weak") / 10)
    check("the raw gap is inflated by the unbalanced venue mix", raw > 13.0, f"raw gap={raw:.1f}")
    check("the adjusted gap is close to the true 10 points",
          abs(gap - 10.0) < 1.0, f"adjusted gap={gap:.2f} (raw was {raw:.1f})")


def test_invents_nothing():
    print("\n[2] with no real venue effect it adjusts nothing")
    a = load("aggregate")
    rows = [{"leader_slug": s, "venue_type": v, "cal_overall": base + (i % 3 - 1)}
            for s, base in (("x", 70), ("y", 60)) for v in ("pod", "tv") for i in range(6)]
    eff = a.venue_effects(rows)
    check("every venue effect is near zero", all(abs(e) < 0.6 for e in eff.values()), f"{eff}")
    adj = a.apply_venue_adjustment(rows, eff)
    check("scores move by less than a tenth of a point",
          all(abs(r["cal_overall_venue_adj"] - r["cal_overall"]) < 0.1 for r in adj))


# ---------------------------------------------------------------------------
# 3. A venue seen too few times cannot be estimated, and must not be guessed.
# ---------------------------------------------------------------------------
def test_thin_venues_are_not_estimated():
    print("\n[3] a venue with too little data gets no adjustment rather than a wild one")
    a = load("aggregate")
    rows = [{"leader_slug": "x", "venue_type": "pod", "cal_overall": 60 + (i % 3 - 1)} for i in range(30)]
    rows.append({"leader_slug": "x", "venue_type": "freak", "cal_overall": 5})
    eff = a.venue_effects(rows)
    check("the one-off venue is left at zero, not handed a -55 point effect",
          abs(eff.get("freak", 0.0)) < 1e-9, f"freak={eff.get('freak')}")
    adj = a.apply_venue_adjustment(rows, eff)
    odd = [r for r in adj if r["venue_type"] == "freak"][0]
    check("its transcript keeps its own score", odd["cal_overall_venue_adj"] == odd["cal_overall"])
    check("MIN_VENUE_N is documented on the module", isinstance(a.MIN_VENUE_N, int) and a.MIN_VENUE_N >= 5,
          f"MIN_VENUE_N={getattr(a,'MIN_VENUE_N',None)}")


def test_missing_venue_is_safe():
    print("\n[4] a transcript with no venue type is passed through untouched")
    a = load("aggregate")
    rows = [{"leader_slug": "x", "venue_type": "pod", "cal_overall": 60} for _ in range(20)]
    rows += [{"leader_slug": "x", "venue_type": None, "cal_overall": 44}]
    eff = a.venue_effects(rows)
    adj = a.apply_venue_adjustment(rows, eff)
    none_row = [r for r in adj if r["venue_type"] is None][0]
    check("it is not dropped", len(adj) == len(rows), f"{len(adj)} vs {len(rows)}")
    check("its score is unchanged", none_row["cal_overall_venue_adj"] == 44.0,
          f"{none_row['cal_overall_venue_adj']}")


# ---------------------------------------------------------------------------
# 5. The adjustment must be visible in the output, not silently applied.
# ---------------------------------------------------------------------------
def test_reported_in_diagnostics(tmp: Path):
    print("\n[5] the adjustment is reported, so a reader can see and undo it")
    src = REPO / "scripts" / "aggregate.py"
    check("aggregate.py records the venue effects it used",
          '"venue_effects"' in src.read_text(), "diagnostics do not name the adjustment")
    check("it records how many transcripts each effect was fitted on",
          '"venue_counts"' in src.read_text(), "an effect with no n behind it is not reviewable")
    check("each transcript keeps its unadjusted score alongside the adjusted one",
          'cal_overall_venue_adj' in src.read_text())


# ---------------------------------------------------------------------------
# 6. Every failure line must carry the time it happened.
#
# MEASURED 2026-09-07: data/logs/grade_errors_blind.jsonl held 75 failures and
# not one had a timestamp field, so there was no way to tell whether a Fable
# spend-limit failure was from an hour ago or two days ago without inferring it
# from something else. The repo rule is to read time out of the record.
# ---------------------------------------------------------------------------
def test_error_log_has_timestamps(tmp: Path):
    print("\n[6] every failure line carries a UTC timestamp")
    src = (REPO / "scripts" / "grade.py").read_text()
    check("grade.py stamps failure records", '"failed_at_utc"' in src,
          "no failed_at_utc anywhere in grade.py")
    g = load("grade")
    check("there is one helper that does the stamping", hasattr(g, "stamp_failure"),
          "expected a stamp_failure() so the format is in one place")
    if not hasattr(g, "stamp_failure"):
        return
    r = g.stamp_failure({"id": "x/y", "judge": "fable", "error_type": "cli_nonzero_exit"})
    check("it adds failed_at_utc", "failed_at_utc" in r, f"{r}")
    ts = r.get("failed_at_utc", "")
    check("the stamp is UTC and ISO-8601, ending in Z",
          ts.endswith("Z") and len(ts) == 20 and ts[4] == "-" and ts[10] == "T", f"ts={ts!r}")
    check("it does not clobber a stamp that is already there",
          g.stamp_failure({"failed_at_utc": "2020-01-01T00:00:00Z"})["failed_at_utc"]
          == "2020-01-01T00:00:00Z")
    check("the original fields survive", r["judge"] == "fable" and r["error_type"] == "cli_nonzero_exit")
    check("the stamp is not derived from a file mtime or the local clock",
          "fromtimestamp" not in src.split("def stamp_failure")[1][:400]
          and "st_mtime" not in src.split("def stamp_failure")[1][:400],
          "repo rule: read time from the record, never the filesystem or local clock")


# ---------------------------------------------------------------------------
# 7. The interval and the point estimate must be computed on the same numbers.
#
# The bootstrap added in b5f0a6c reads cal_<dim>. The venue adjustment writes
# cal_<dim>_venue_adj and the leader score now uses that. If the bootstrap is
# not moved too, the published dot sits on the adjusted score while the whiskers
# come from the unadjusted one, and a leader in a generous venue can have their
# point estimate fall OUTSIDE their own interval on the deployed page.
# ---------------------------------------------------------------------------
def test_collinear_design_is_not_over_fitted():
    print("\n[7a] a leader seen in only one venue cannot identify a venue effect")
    a = load("aggregate")
    rows = ([{"leader_slug": "x", "venue_type": "pod", "cal_overall": 80 + (i % 3 - 1)} for i in range(12)]
            + [{"leader_slug": "y", "venue_type": "tv", "cal_overall": 50 + (i % 3 - 1)} for i in range(12)])
    eff = a.venue_effects(rows)
    check("it does not read a 30-point leader gap as a venue effect",
          all(abs(e) < 1.0 for e in eff.values()),
          f"{eff} — a collinear design must attribute the gap to the leader, not the format")


def test_interval_matches_the_point_estimate():
    print("\n[7] the interval is computed on the same values as the score")
    a = load("aggregate")
    # A leader whose venue mix is lopsided enough that the adjustment bites.
    # Every leader must appear in more than one venue or the model is
    # collinear: with x only ever on pod and y only ever on tv there is no way
    # to tell a generous venue from a strong speaker, and the fit correctly
    # attributes everything to the leader. Overlap is what identifies it.
    rows = []
    def add(slug, venue, base, n):
        for i in range(n):
            v = base + (i % 3 - 1)
            rows.append({"leader_slug": slug, "venue_type": venue, "coverage": 1.0,
                         "cal_d1_clarity": v, "cal_d2_insight": v, "cal_d3_technical_depth": v})
    # A large venue effect and a lopsided mix, so the adjusted and unadjusted
    # means are far apart and the check cannot pass by luck.
    add("x", "pod", 90, 13); add("x", "tv", 70, 3)
    add("y", "pod", 60, 3);  add("y", "tv", 40, 13)
    for d in a.DIMS:
        eff = a.venue_effects(rows, field=f"cal_{d}")
        a.apply_venue_adjustment(rows, eff, field=f"cal_{d}")
    check("the adjustment actually moved these rows",
          any(r[f"cal_{a.DIMS[0]}_venue_adj"] != r[f"cal_{a.DIMS[0]}"] for r in rows))

    mine = [r for r in rows if r["leader_slug"] == "x"]
    lo, hi = a.bootstrap_ci(mine, a.WEIGHTS, a.DIMS)
    pt = sum(a.WEIGHTS[d] * (sum(r[f"cal_{d}_venue_adj"] for r in mine) / len(mine)) for d in a.DIMS)
    check("the point estimate lies inside its own interval",
          lo <= pt <= hi, f"point={pt:.2f} interval=[{lo:.2f}, {hi:.2f}]")
    raw = sum(a.WEIGHTS[d] * (sum(r[f"cal_{d}"] for r in mine) / len(mine)) for d in a.DIMS)
    mid = (lo + hi) / 2
    check("the adjusted and raw means are far enough apart to tell them apart",
          abs(raw - pt) > 2.0, f"raw={raw:.2f} adjusted={pt:.2f}")
    check("the interval is centred on the ADJUSTED mean, not the raw one",
          abs(mid - pt) < abs(mid - raw), f"midpoint={mid:.2f} adjusted={pt:.2f} raw={raw:.2f}")


def main() -> int:
    print("venue-adjustment and error-log guards")
    test_recovers_a_known_effect()
    test_invents_nothing()
    test_thin_venues_are_not_estimated()
    test_missing_venue_is_safe()
    test_collinear_design_is_not_over_fitted()
    test_interval_matches_the_point_estimate()
    with tempfile.TemporaryDirectory() as td:
        test_reported_in_diagnostics(Path(td))
        test_error_log_has_timestamps(Path(td))
    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} passed")
    if FAIL: print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
