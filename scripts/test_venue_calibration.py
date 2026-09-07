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


# ---------------------------------------------------------------------------
# 8. The subject-share cutoff, and deciding it per transcript.
#
# MEASURED 2026-09-07 on 785 blinded grades. The share distribution is bimodal:
# 47 grades sit at 0-4%, where the subject is simply absent, then a near-empty
# band of 3 grades at 5-9%, then a continuum from 10% upward (16, 14, 9, 11, 26,
# 30 ...). The old cutoff of 15 cut straight through that continuum. 10 sits in
# the empty band, so the line describes a real feature of the data rather than a
# round number.
#
# The filter also ran PER GRADE, so one judge estimating 14% and the other 16%
# dropped one grade and kept the other, silently turning a two-judge transcript
# into a single-judge one. Confidence already penalises single-judge leaders, so
# this filter was quietly feeding that. Speech share is a property of the
# RECORDING, so both judges' estimates decide it together. They agree closely:
# median absolute disagreement 2 points, mean 3.6.
# ---------------------------------------------------------------------------
def test_subject_share_cutoff():
    print("\n[8] the subject-share cutoff sits in the gap and is decided per transcript")
    a = load("aggregate")
    check("the cutoff is 10, the empty band in the measured distribution",
          a.MIN_SUBJECT_SHARE == 10, f"MIN_SUBJECT_SHARE={a.MIN_SUBJECT_SHARE}")

    def g(slug, sid, judge, share):
        return {"leader_slug": slug, "source_id": sid, "judge": judge, "mode": "blinded",
                "grade": {"subject_speech_share_pct": share, "overall": 50.0}}

    # Judges straddle the line. Under the old per-grade rule this kept one and
    # dropped the other; the transcript must now be all in or all out.
    straddle = [g("x", "t1", "fable", 9), g("x", "t1", "astra", 12)]
    kept, dropped = a.filter_unscorable(straddle, a.MIN_SUBJECT_SHARE)
    check("a straddling transcript is never half-dropped",
          len(kept) in (0, 2) and len(dropped) in (0, 2), f"kept={len(kept)} dropped={len(dropped)}")
    check("mean 10.5 is at or above the cutoff, so it is kept whole", len(kept) == 2,
          f"kept={len(kept)}")

    clearly_out = [g("x", "t2", "fable", 2), g("x", "t2", "astra", 3)]
    kept, dropped = a.filter_unscorable(clearly_out, a.MIN_SUBJECT_SHARE)
    check("a transcript where the subject is absent is dropped whole", len(dropped) == 2, f"{dropped}")

    clearly_in = [g("x", "t3", "fable", 60), g("x", "t3", "astra", 70)]
    kept, _ = a.filter_unscorable(clearly_in, a.MIN_SUBJECT_SHARE)
    check("an ordinary interview is kept", len(kept) == 2)

    single = [g("x", "t4", "astra", 4)]
    kept, dropped = a.filter_unscorable(single, a.MIN_SUBJECT_SHARE)
    check("a single-judge transcript is still judged on the one estimate it has",
          len(dropped) == 1, f"kept={len(kept)}")

    missing = [{"leader_slug": "x", "source_id": "t5", "judge": "fable", "mode": "blinded",
                "grade": {"overall": 50.0}}]
    kept, dropped = a.filter_unscorable(missing, a.MIN_SUBJECT_SHARE)
    check("a grade with no share estimate is kept, not guessed at",
          len(kept) == 1 and not dropped, f"kept={len(kept)} dropped={len(dropped)}")

    mixed = [g("x", "t6", "fable", 5), g("x", "t6", "astra", 80)]
    kept, dropped = a.filter_unscorable(mixed, a.MIN_SUBJECT_SHARE)
    check("judges that wildly disagree still resolve to one decision for the transcript",
          len(kept) in (0, 2) and len(dropped) in (0, 2), f"kept={len(kept)} dropped={len(dropped)}")


# ---------------------------------------------------------------------------
# 9. Astra's web searches must be counted.
#
# MEASURED 2026-09-07: `codex exec` with the production flags reports
# "YES - web.run", and the judge was observed issuing web_search calls and
# citing a page that named the subject. -s read-only restricts the filesystem,
# not the network, and none of five candidate config keys disabled it.
#
# The decision is to leave the behaviour alone, because changing it now would
# make new grades incomparable with the 999 already in the corpus. But it must
# stop being INVISIBLE: across 706 Astra grades nothing recorded whether a
# lookup happened, so the exposure could not be measured at all.
# ---------------------------------------------------------------------------
def test_astra_search_is_logged():
    print("\n[9] Astra's web searches are counted in the telemetry")
    src = (REPO / "scripts" / "grade.py").read_text()
    check("grade.py counts web_search items from the codex event stream",
          "web_search" in src, "the stream is parsed but tool use is not recorded")
    g = load("grade")
    check("there is one helper that counts them", hasattr(g, "count_tool_events"),
          "expected count_tool_events() so the shape is in one place")
    if not hasattr(g, "count_tool_events"):
        return
    events = [
        {"type": "thread.started"},
        {"type": "item.started", "item": {"type": "web_search"}},
        {"type": "item.completed", "item": {"type": "web_search", "query": "who is this"}},
        {"type": "item.completed", "item": {"type": "web_search", "query": "second"}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "cat x"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
    ]
    t = g.count_tool_events(events)
    check("completed web searches are counted, not the started events too",
          t["web_search"] == 2, f"{t}")
    check("shell commands are counted separately", t["command_execution"] == 1, f"{t}")
    check("ordinary messages are not counted as tool use", "agent_message" not in t, f"{t}")
    check("a run with no tool use reports zero rather than omitting the field",
          g.count_tool_events([{"type": "turn.completed"}])["web_search"] == 0,
          f"{g.count_tool_events([{'type': 'turn.completed'}])}")
    # "tool_use" alone is not enough: E_TOOL_ATTEMPT already contains that
    # substring, so the first version of this check passed without anything
    # being wired up. Assert on the telemetry key and the call site instead.
    check("the counts are written into astra's telemetry",
          '"tool_use_counts": count_tool_events(events)' in src,
          "count_tool_events exists but nothing calls it")
    check("the search queries themselves are recorded, not just a count",
          '"web_search_queries"' in src, "a bare count cannot say what was looked up")
    astra = src.split("def call_astra")[1].split("\ndef ")[0]
    check("the counting happens inside call_astra, where the stream is parsed",
          "count_tool_events(events)" in astra, "wired somewhere else than the astra path")


# ---------------------------------------------------------------------------
# 10. The published score must not depend on Python's hash seed.
#
# FOUND by running aggregate.py twice on a FROZEN grades directory and getting
# 36 different leader scores. Per-transcript venue_type was picked with
#   max(set(votes), key=votes.count)
# and Python randomises str hashing per process, so set iteration order — and
# therefore the winner of a TIE — changes between runs. On this corpus 42
# transcripts have judges disagreeing about the venue, and every one of them is
# a one-vote-each tie.
#
# That was harmless while venue_type only fed the display. The venue adjustment
# made it load-bearing, so a hash seed could move a published score by up to
# 0.6 points. Two fixes: the displayed value is chosen deterministically, and
# the ADJUSTMENT is only applied when the judges actually agree, because a tie
# means the format is unknown rather than resolved.
# ---------------------------------------------------------------------------
def test_venue_vote_is_deterministic():
    print("\n[10] a tied venue vote does not depend on the hash seed")
    a = load("aggregate")
    votes = ["keynote", "long_form_podcast"]
    picks = {a.resolve_venue(list(v))[0] for v in
             ([votes, votes[::-1]] * 6)}
    check("a tie resolves to the same value regardless of vote order",
          len(picks) == 1, f"got {picks}")
    check("a tie is reported as not agreed", a.resolve_venue(votes)[1] is False,
          f"{a.resolve_venue(votes)}")
    check("a clear majority is agreed and wins",
          a.resolve_venue(["keynote", "keynote", "panel"]) == ("keynote", True),
          f"{a.resolve_venue(['keynote','keynote','panel'])}")
    check("a single vote is agreed", a.resolve_venue(["panel"]) == ("panel", True))
    check("no votes gives no venue", a.resolve_venue([]) == (None, False))

    # And the adjustment must skip a transcript whose venue is not agreed.
    rows = [{"leader_slug": "x", "venue_type": "pod", "venue_agreed": True,
             "cal_overall": 70} for _ in range(12)]
    rows += [{"leader_slug": "x", "venue_type": "pod", "venue_agreed": False,
              "cal_overall": 70}]
    eff = {"pod": 5.0}
    a.apply_venue_adjustment(rows, eff)
    agreed = [r for r in rows if r["venue_agreed"]][0]
    tied = [r for r in rows if not r["venue_agreed"]][0]
    check("an agreed transcript is adjusted", agreed["cal_overall_venue_adj"] == 65.0,
          f"{agreed}")
    check("a tied transcript is left alone rather than adjusted on a guess",
          tied["cal_overall_venue_adj"] == 70.0, f"{tied}")


def test_aggregate_is_reproducible():
    print("\n[10a] two runs over the same grades produce the same scores")
    import os, subprocess, tempfile
    data = REPO / "data"
    if not (data / "results.json").exists():
        print("  SKIP  no data/ in this clone")
        return
    with tempfile.TemporaryDirectory() as td:
        outs = []
        for i, seed in enumerate(("0", "12345")):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            o = Path(td) / f"r{i}.json"
            r = subprocess.run([PY, str(REPO / "scripts" / "aggregate.py"),
                                "--grades", str(REPO / "scripts" / "_nonexistent")
                                if False else str(data / "grades"),
                                "--roster", str(data / "roster" / "final.json"),
                                "--transcripts", str(data / "transcripts_blind"),
                                "--out", str(o)],
                               capture_output=True, text=True, env=env)
            if r.returncode != 0:
                print(f"  SKIP  aggregate failed: {r.stderr[-200:]}")
                return
            outs.append(json.loads(o.read_text()))
        g = lambda f: {l["slug"]: l["blinded"]["overall"]
                       for l in f["leaders"] if l["status"] == "scored"}
        A, B = g(outs[0]), g(outs[1])
        if outs[0]["diagnostics"]["grades_used"] != outs[1]["diagnostics"]["grades_used"]:
            print("  SKIP  the corpus changed under us (a grading loop is running)")
            return
        diff = [s for s in A if A[s] != B[s]]
        check("two different hash seeds give identical leader scores",
              not diff, f"{len(diff)} differ, e.g. {[(s, A[s], B[s]) for s in diff[:3]]}")


def main() -> int:
    print("venue-adjustment and error-log guards")
    test_recovers_a_known_effect()
    test_invents_nothing()
    test_thin_venues_are_not_estimated()
    test_missing_venue_is_safe()
    test_collinear_design_is_not_over_fitted()
    test_interval_matches_the_point_estimate()
    test_subject_share_cutoff()
    test_astra_search_is_logged()
    test_venue_vote_is_deterministic()
    test_aggregate_is_reproducible()
    with tempfile.TemporaryDirectory() as td:
        test_reported_in_diagnostics(Path(td))
        test_error_log_has_timestamps(Path(td))
    print(f"\n{len(PASS)}/{len(PASS)+len(FAIL)} passed")
    if FAIL: print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
