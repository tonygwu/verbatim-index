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
import random
from collections import Counter, defaultdict
from pathlib import Path

# scripts/ is not a package, and this module is also loaded by importlib in the
# test harness, so make the sibling import work in both cases.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402

DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]
DIM_LABEL = {"d1_clarity": "Clarity", "d2_insight": "Insight", "d3_technical_depth": "Technical depth"}
WEIGHTS = {"d1_clarity": 0.20, "d2_insight": 0.45, "d3_technical_depth": 0.35}
SUB_GROUPS = {
    "d1_clarity": ["C1", "C2", "C3", "C4"],
    "d2_insight": ["I1", "I2", "I3", "I4", "I5", "I6", "I7"],
    "d3_technical_depth": ["T1", "T2", "T3", "T4"],
}
MIN_TRANSCRIPTS_FOR_CONFIDENCE = 3
# The upper band. Named rather than typed inline, because the site explains this
# rule to a reader and the explanation must be generated from the rule itself.
# The judge count on that page was hand-typed in five places and went stale the
# day a third judge was promoted; this is the same hazard one column over.
HIGH_CONFIDENCE_TRANSCRIPTS = 5

# Below this share of the words, the subject is not really in the recording and
# the grade describes somebody else. MEASURED on 785 blinded grades: the share
# distribution is bimodal. 47 grades sit at 0-4%, a near-empty band of 3 grades
# spans 5-9%, and a continuum runs from 10% upward (16, 14, 9, 11, 26, 30, ...).
# The old value of 15 cut straight through that continuum, so 37 grades sat
# within five points of the line and small changes reshuffled who was included.
# 10 sits in the empty band, which makes the cutoff a description of the data
# rather than a round number.
MIN_SUBJECT_SHARE = 10


def filter_unscorable(grades: list[dict], cutoff: int = MIN_SUBJECT_SHARE
                      ) -> tuple[list[dict], list[dict]]:
    """Split grades into (kept, dropped) on subject speech share, per TRANSCRIPT.

    Dropped when the judges' mean share is under `cutoff`, or when any judge
    put the share at exactly 0.

    The decision is made once per recording, on the mean of whatever judges
    estimated it, and applies to all of that recording's grades. It used to be
    made per grade, so one judge saying 14% and the other 16% dropped one and
    kept the other, silently turning a two-judge transcript into a single-judge
    one. Confidence already penalises single-judge leaders, so the filter was
    quietly feeding a penalty it had nothing to do with.

    Share is a property of the recording, not of the judge, and the judges agree
    closely about it: median absolute disagreement 2 points, mean 3.6. So the
    mean is a stable statistic and a transcript is either wholly in or wholly
    out.

    A grade with no share estimate is kept. Guessing a number for it would be
    exactly the accept-and-guess this repo forbids.

    A zero from ANY judge drops the recording, whatever the mean. A judge that
    says 0 has read the recording and found the subject absent, and a mean
    cannot express that: 0, 0 and 68 average to 22.7 and pass. MEASURED
    2026-09-10 on 558 recordings: 10 were on the board with one or two judges
    at 0 and another judge at 42 to 86, and all 10 were subject-absent on
    inspection (hosts discussing Tim Cook, a biographer of Demis Hassabis, a
    devotional talk filed under Arvind Krishna). The high judge had scored the
    host, the co-guest or the biographer and said so in its own notes. Under
    this rule 0 of the 10 survive; a median rule keeps 4 of them.
    """
    by_tx: dict[tuple, list[int]] = defaultdict(list)
    for g in grades:
        v = (g.get("grade") or {}).get("subject_speech_share_pct")
        if isinstance(v, int):
            by_tx[(g["leader_slug"], g["source_id"], g["mode"])].append(v)
    out = {k: (st.mean(v) < cutoff or min(v) == 0) for k, v in by_tx.items() if v}
    kept, dropped = [], []
    for g in grades:
        key = (g["leader_slug"], g["source_id"], g["mode"])
        (dropped if out.get(key) else kept).append(g)
    return kept, dropped



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


# Below this many grades a model's own mean and spread are too thin to rescale
# with, so its scores pass through unchanged rather than being mapped by
# statistics estimated from a handful of points.
MIN_CALIBRATION_N = 25

# What model a judge served before grades recorded it. Only used for records
# written before served_model existed; new ones carry their own.
DEFAULT_JUDGE_MODEL = {"fable": "claude-fable-5-1", "astra": "gpt-6-astra",
                       "gemini": "gemini-3.8-flash-high"}

# Judges whose grades are COLLECTED but kept out of the published score.
#
# A new judge changes the judge MIX per leader, and an uneven mix is the one
# thing calibrate() cannot repair: it maps each judge onto the pooled
# distribution, so a leader graded more often by a harsh judge still lands lower
# than one graded more often by a lenient judge. Backfilling the whole corpus
# fixes the mix, but only once the backfill is COMPLETE. Until then the arm sits
# here, graded and reported and not published, so a half-finished backfill
# cannot quietly reshuffle the board.
#
# It is also where an arm waits until its own distribution is known to be
# usable. calibrate() only rescales a judge whose spread reaches MIN_SD, so a
# flat judge would enter unrescaled and sit systematically off. shadow_report()
# prints the spread and the agreement needed to make that call on evidence.
#
# Promoting an arm means deleting its name here, and that is deliberately a
# code change with a diff, not a flag someone can pass in a hurry.
# Empty: the Gemini arm was promoted 2026-09-08 after backfilling the corpus.
# Its coverage gap is recorded under Known limits in AGENTS.md rather than
# hidden here, because a shadow list is for an arm that is not ready, not for
# one whose weakness has been measured and accepted.
SHADOW_JUDGES: tuple[str, ...] = ()


def served_model(g: dict) -> str:
    """Which model actually produced this grade.

    A judge is an ARM of the study, not a model. Astra falls back to another
    model when it refuses repeatedly, so filing those grades under "astra" and
    pooling them into astra's distribution would rescale them by statistics that
    are not theirs. On the one transcript where both models graded, they
    differed by 3.65 points, so the distributions are not interchangeable.
    """
    t = g.get("telemetry") or {}
    return (t.get("served_model") or t.get("requested_model")
            or DEFAULT_JUDGE_MODEL.get(g.get("judge"), g.get("judge") or "unknown"))


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
            by_jmd[(g["judge"], served_model(g), g["mode"], dim)].append(v)
            by_md[(g["mode"], dim)].append(v)

    params = {}
    for key, vals in by_jmd.items():
        judge, model, mode, dim = key
        pooled = by_md[(mode, dim)]
        jm = st.mean(vals)
        jsd = st.pstdev(vals) if len(vals) > 1 else 0.0
        pm = st.mean(pooled)
        psd = st.pstdev(pooled) if len(pooled) > 1 else 0.0
        params[key] = {
            "judge_mean": round(jm, 2), "judge_sd": round(jsd, 2),
            "pooled_mean": round(pm, 2), "pooled_sd": round(psd, 2),
            "n": len(vals),
            "model": model,
            # Both conditions matter. A flat judge must not be rescaled because
            # that amplifies noise, and a model with only a few grades must not
            # be rescaled because its mean and spread are not yet estimated.
            "rescaled": jsd >= 3.0 and len(vals) >= MIN_CALIBRATION_N,
        }
    return params


def apply_calibration(raw: float, key: tuple, params: dict) -> float:
    p = params.get(key)
    if not p or not p["rescaled"]:
        return raw
    scaled = p["pooled_mean"] + (raw - p["judge_mean"]) * (p["pooled_sd"] / p["judge_sd"])
    return max(1.0, min(100.0, scaled))


# How many resamples the interval is built from. 20k puts the Monte Carlo error
# on a 95% endpoint well under 0.1 points, which is finer than the scores are
# printed, so the published interval does not wobble between runs.
BOOTSTRAP_N = 20000
BOOTSTRAP_SEED = 20260907


def bootstrap_ci(rows: list[dict], weights: dict, dims: list[str],
                 n: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED,
                 alpha: float = 0.05) -> tuple[float | None, float | None]:
    """A 95% interval for a leader's score, resampling their transcripts.

    The score is a coverage-weighted mean over the transcripts that were
    collected, and those are a SAMPLE of what the person said in public. So the
    number carries sampling error, and a leader on 3 transcripts carries far
    more of it than one on 14. The point estimate alone hides that difference
    completely, which is what this exists to fix.

    The resample is over transcripts, with replacement, because the transcript
    is the unit that varies. Calibration is deliberately held fixed: it is
    fitted on the whole corpus, its own uncertainty is small next to per-leader
    sampling, and refitting it inside every resample would mix two different
    questions into one interval.

    Seeded, so the published endpoints are reproducible rather than drifting by
    a tenth of a point every time the loop re-aggregates.
    """
    if not rows:
        return (None, None)
    rng = random.Random(seed)
    k = len(rows)
    draws = []
    for _ in range(n):
        pick = [rows[rng.randrange(k)] for _ in range(k)]
        total = 0.0
        for dim in dims:
            # The venue adjustment writes cal_<dim>_venue_adj and the leader
            # score uses it, so the interval must use it too. Otherwise the
            # published dot sits on the adjusted score while the whiskers come
            # from the unadjusted one, and the point can fall outside its own bar.
            key = f"cal_{dim}_venue_adj" if f"cal_{dim}_venue_adj" in pick[0] else f"cal_{dim}"
            num = sum(r[key] * max(r["coverage"], 0.05) for r in pick)
            den = sum(max(r["coverage"], 0.05) for r in pick)
            total += weights[dim] * (num / den)
        draws.append(total)
    draws.sort()
    lo = draws[int((alpha / 2) * n)]
    hi = draws[min(int((1 - alpha / 2) * n), n - 1)]
    return (round(lo, 1), round(hi, 1))


# A venue effect is only estimable if the venue was seen often enough. Below
# this the "effect" is one or two transcripts' noise, and subtracting it would
# move a real score by a made-up amount. Measured on this corpus: internal_talk
# appears once and tv_interview five times, against 197 long-form podcasts.
MIN_VENUE_N = 8


def resolve_venue(votes: list[str]) -> tuple[str | None, bool]:
    """The judges' venue verdict, and whether they actually agreed.

    FOUND 2026-09-07 by running aggregate.py twice over a frozen grades
    directory and getting 36 different leader scores. The old line was

        max(set(votes), key=votes.count)

    and Python randomises string hashing per process, so set iteration order,
    and therefore the winner of a TIE, changed between runs. On this corpus 42
    transcripts have the two judges disagreeing about the venue and every one is
    a one-vote-each tie.

    Harmless while venue_type only fed the display. The venue adjustment made it
    load-bearing, so the hash seed could move a published score.

    Sorting before the max makes the displayed value stable. The second return
    value says whether there was a real majority, and the adjustment uses only
    that: a tie means the format is unknown, not resolved, so nothing is
    subtracted rather than subtracting a coin flip.
    """
    if not votes:
        return None, False
    counts = Counter(votes)
    top = max(sorted(counts), key=lambda v: counts[v])
    agreed = sum(1 for c in counts.values() if c == counts[top]) == 1
    return top, agreed


def venue_effects(rows: list[dict], field: str = "cal_overall",
                  min_n: int = MIN_VENUE_N) -> dict[str, float]:
    """How many points a FORMAT adds or removes, with the speaker held fixed.

    Transcript scores vary by venue type, but leaders are not spread evenly
    across venues: some appear only on long podcasts, others only at keynotes.
    So the raw mean per venue confounds the format with the people who choose
    it, and reading it as a format effect overstates it. Measured here: the raw
    spread across venue types is 8.2 points and the spread with the leader held
    fixed is 5.7.

    This is the same move `calibrate()` makes for judges. Estimate the nuisance
    effect, then subtract it, rather than assuming it is zero.

    The fit is an additive two-way model, leader plus venue, solved by
    alternating means. Each pass sets the leader effects from the residuals of
    the venue effects and then the reverse, which converges to the least-squares
    fit of that model. Venue effects are centred to sum to zero so the overall
    level of the leaderboard does not move.

    A venue seen fewer than `min_n` times gets an effect of exactly zero, and a
    transcript with no venue type at all is left alone. Both are reported rather
    than silently skipped.
    """
    usable = [r for r in rows if r.get("venue_type") and r.get("venue_agreed", True)]
    counts: dict[str, int] = defaultdict(int)
    for r in usable:
        counts[r["venue_type"]] += 1
    fittable = {v for v, n in counts.items() if n >= min_n}
    usable = [r for r in usable if r["venue_type"] in fittable]
    if not usable or len(fittable) < 2:
        return {v: 0.0 for v in counts}

    eff: dict[str, float] = {v: 0.0 for v in fittable}
    for _ in range(200):
        by_leader: dict[str, list[float]] = defaultdict(list)
        for r in usable:
            by_leader[r["leader_slug"]].append(r[field] - eff[r["venue_type"]])
        lead = {s: st.mean(v) for s, v in by_leader.items()}
        by_venue: dict[str, list[float]] = defaultdict(list)
        for r in usable:
            by_venue[r["venue_type"]].append(r[field] - lead[r["leader_slug"]])
        eff = {v: st.mean(x) for v, x in by_venue.items()}
        centre = st.mean(list(eff.values()))
        eff = {v: e - centre for v, e in eff.items()}
    out = {v: 0.0 for v in counts}
    out.update({v: round(e, 3) for v, e in eff.items()})
    return out


def apply_venue_adjustment(rows: list[dict], effects: dict[str, float],
                           field: str = "cal_overall") -> list[dict]:
    """Write `cal_overall_venue_adj` alongside `cal_overall`, never replacing it.

    Keeping both means a reader can see exactly what the adjustment did and undo
    it, which an adjustment that overwrites its input does not allow.
    """
    for r in rows:
        # Only adjust when the judges agreed what the venue was. A tie means the
        # format is unknown, and subtracting an effect for a coin flip would put
        # the hash seed into the published score.
        e = (effects.get(r.get("venue_type") or "", 0.0)
             if r.get("venue_agreed", True) else 0.0)
        r[field + "_venue_adj"] = round(r[field] - e, 2)
    return rows


def weighted(pairs: list[tuple[float, float]]) -> float | None:
    """pairs of (value, weight)."""
    num = sum(v * w for v, w in pairs)
    den = sum(w for _, w in pairs)
    return num / den if den > 0 else None


def shadow_report(shadow: list[dict], published: list[dict], corpus_n: int | None) -> dict:
    """What a shadow judge would contribute, without letting it contribute.

    Answers the three questions that decide whether the arm can be promoted,
    and answers each with a number rather than an impression.

    1. IS THE BACKFILL COMPLETE? An uneven judge mix is what calibration cannot
       fix, so an arm may only be promoted once it has graded the same corpus
       the published judges did. `blinded_coverage` is that fraction.
    2. CAN IT BE CALIBRATED? calibrate() rescales a judge only when its spread
       reaches 3.0 and it has at least MIN_CALIBRATION_N grades. Below either,
       the arm would enter the pool unrescaled and sit systematically off. Both
       thresholds are reported per dimension, with the verdict.
    3. DOES IT AGREE? `vs_<judge>` gives the mean absolute difference on the
       overall score across transcripts BOTH graded, which is the paired
       comparison; an unpaired difference of means would confound the judge with
       whichever transcripts it happened to get.

    Nothing here feeds a published number. It exists so promotion is a decision
    made on evidence, not on the arm having run without crashing.
    """
    out: dict = {"n_grades": len(shadow)}
    if not shadow:
        return out

    blinded = [g for g in shadow if g["mode"] == "blinded" and not g.get("_excluded")]
    out["n_blinded"] = len(blinded)
    out["judges"] = sorted({g["judge"] for g in shadow})
    out["served_models"] = dict(Counter(served_model(g) for g in shadow))
    out["refusals"] = sum(1 for g in shadow if g.get("refused"))
    out["excluded_validation"] = sum(1 for g in shadow if g.get("_excluded"))

    # 1. Backfill progress against the corpus the published judges cover.
    seen = {(g["leader_slug"], g["source_id"]) for g in blinded}
    out["blinded_transcripts_graded"] = len(seen)
    if corpus_n:
        out["blinded_coverage"] = round(len(seen) / corpus_n, 3)
        out["backfill_complete"] = len(seen) >= corpus_n

    # 2. Spread, per dimension, against the two thresholds calibrate() applies.
    spread = {}
    for dim in DIMS:
        vals = [g["grade"]["dimensions"][dim]["score"] for g in blinded
                if isinstance(g["grade"]["dimensions"].get(dim, {}).get("score"), int)]
        sd = round(st.pstdev(vals), 2) if len(vals) > 1 else 0.0
        spread[dim] = {
            "n": len(vals),
            "mean": round(st.mean(vals), 2) if vals else None,
            "sd": sd,
            # Both conditions, stated separately, because they fail for
            # different reasons and need different remedies: too few grades
            # means grade more, too flat means this judge cannot be rescaled
            # at all and pooling it would be a choice, not a calculation.
            "enough_grades": len(vals) >= MIN_CALIBRATION_N,
            "spread_sufficient": sd >= 3.0,
            "would_be_rescaled": sd >= 3.0 and len(vals) >= MIN_CALIBRATION_N,
        }
    out["calibration_readiness"] = spread

    # 3. Paired agreement with each published judge.
    by_key: dict[tuple, dict] = defaultdict(dict)
    for g in published:
        if g["mode"] == "blinded" and not g.get("_excluded"):
            by_key[(g["leader_slug"], g["source_id"])][g["judge"]] = g["grade"]["overall"]
    for g in blinded:
        by_key[(g["leader_slug"], g["source_id"])].setdefault("_shadow", g["grade"]["overall"])

    for other in sorted({g["judge"] for g in published if g["mode"] == "blinded"}):
        pairs = [(v["_shadow"], v[other]) for v in by_key.values()
                 if "_shadow" in v and other in v]
        if len(pairs) < 3:
            out[f"vs_{other}"] = {"n_paired": len(pairs), "note": "too few pairs to compare"}
            continue
        diffs = [a - b for a, b in pairs]
        out[f"vs_{other}"] = {
            "n_paired": len(pairs),
            # Signed, so a systematic offset is visible. Calibration removes a
            # constant offset; it does not remove disagreement.
            "mean_signed_diff": round(st.mean(diffs), 2),
            "mean_abs_diff": round(st.mean([abs(d) for d in diffs]), 2),
            "median_abs_diff": round(st.median([abs(d) for d in diffs]), 2),
        }

    # The exposure this arm carries, same as the Astra arm: live web search that
    # cannot be switched off. Recorded so it is measurable rather than assumed.
    searched = [g for g in shadow
                if sum(((g.get("telemetry") or {}).get("tool_use_counts") or {}).values())]
    out["grades_where_a_tool_ran"] = len(searched)
    out["web_search_queries_sample"] = [
        q for g in searched[:20]
        for q in ((g.get("telemetry") or {}).get("web_search_queries") or [])
    ][:10]
    return out


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

    # Split the shadow arms out FIRST, before filter_unscorable and before
    # calibrate(), so a shadow judge cannot move a published number by any
    # route: not through the pooled mean, not through a leader's coverage, and
    # not through the bootstrap. It is reported in diagnostics instead.
    shadow = [g for g in grades if g.get("judge") in SHADOW_JUDGES]
    grades = [g for g in grades if g.get("judge") not in SHADOW_JUDGES]
    if not grades:
        raise SystemExit(f"every grade found belongs to a shadow judge {list(SHADOW_JUDGES)}; "
                         f"there is nothing to publish. Promote the arm or grade with another judge.")

    # A judge that declines to score one subject silently halves that leader's
    # evidence while everyone else keeps two judges. Count it per leader and per
    # judge so a one-judge score is never mistaken for a two-judge one.
    # A judge that read the transcript is a better detector of "the subject is
    # not in this recording" than any keyword heuristic run over the text.
    #
    # MEASURED: andy-jassy/tech-news-weekly-qpvhgj is a multi-topic news roundup
    # where Jassy is discussed and never speaks. The name-density gate passed it
    # at 0.24 mentions per 1000 words, because a show covering three unrelated
    # stories does not repeat his name. Astra reported subject_speech_share_pct
    # of 0 and scored it 1 out of 100.
    #
    # Excluding it from the leaderboard is the small part. The damage is that a
    # score of 1 also entered calibrate(), dragging that judge's mean down and
    # inflating its spread, which shifts the calibrated score of EVERY leader.
    # So this filter must run BEFORE calibration, not at presentation time.
    # Recorded before any filter runs, so a reader can tell a stale results.json
    # from a filtered one. grades_loaded below is counted AFTER the unscorable
    # drop, so comparing THAT to the files on disk reports a permanent false
    # staleness equal to the number of dropped rows. deploy.sh compares against
    # this figure instead.
    grade_files_read = len(grades)

    # A record that failed schema validation is not a grade, so it leaves HERE,
    # before any filter reads a field out of it.
    #
    # It used to leave after filter_unscorable, and that cost 13 hours of
    # leaderboard on 2026-09-09. Astra refused
    # tim-cook/the-bulwark-and-the-prof-zi07-f and wrote a record whose "grade"
    # object held one key, "error". Fable scored the same recording with a
    # subject share of 0, so the recording fell under the cutoff and ALL of its
    # grades went to the unscorable list, the refusal record among them. The
    # report below then read subject_speech_share_pct off a record that has no
    # dimensions, no overall and no share, and aggregate.py died with KeyError
    # on every cycle from then on. The loop kept grading and still exited
    # "COMPLETE", so the site served the last good build for 58 cycles.
    #
    # Reading anything at all off an invalid record is the defect; dropping it
    # earlier is the fix. MEASURED on the corpus of 2026-09-09, 1906 records,
    # 14 of them invalid: 6 invalid records carry a subject share and all 6 sit
    # far above the cutoff, so 0 transcripts change their in-or-out verdict.
    # No published number moves. The reorder is still the right semantics
    # rather than a lucky one: a record that failed the schema should not get a
    # vote on whether a recording is scorable.
    excluded = [g for g in grades if g.get("_excluded")]
    grades = [g for g in grades if not g.get("_excluded")]

    grades, unscorable = filter_unscorable(grades, MIN_SUBJECT_SHARE)
    # Every record here has passed schema validation, so it HAS a share. The
    # subscript stays a subscript on purpose: a missing key means a record that
    # is not a grade has reached this far again, and that must stop the run
    # rather than be smoothed over with a default. It only names the record it
    # tripped on, because a bare KeyError does not say which file to look at.
    for g in unscorable:
        if "subject_speech_share_pct" not in (g.get("grade") or {}):
            raise SystemExit(
                f"NOT A GRADE: {g['judge']}/{g['leader_slug']}/{g['source_id']} carries no "
                f"subject_speech_share_pct, so it is not a scorable record, yet it reached the "
                f"unscorable report. validation_errors={g.get('validation_errors')!r}. "
                f"Records that fail validation must be split out before filter_unscorable.")
    unscorable_report = [{
        "leader_slug": g["leader_slug"], "source_id": g["source_id"], "judge": g["judge"],
        "mode": g["mode"], "subject_share_pct": g["grade"]["subject_speech_share_pct"],
        "score_it_would_have_contributed": g["grade"].get("overall"),
    } for g in unscorable]

    refusals = [g for g in grades if g.get("refused")]
    grades = [g for g in grades if not g.get("refused")]
    refusal_breakdown: dict[str, dict] = {}
    for g in refusals:
        e = refusal_breakdown.setdefault(g["leader_slug"], {"count": 0, "judges": set(), "reason": ""})
        e["count"] += 1
        e["judges"].add(g["judge"])
        e["reason"] = e["reason"] or (g.get("refusal_reason") or "")[:200]
    for e in refusal_breakdown.values():
        e["judges"] = sorted(e["judges"])

    # Already split out above, before the share filter could read a field off
    # one. Everything still here passed validation.
    usable = grades

    # Every record read is now in exactly one bucket, and the four add up to the
    # files read. If that stops being true a record is being dropped silently,
    # which is how a leader loses evidence without anything saying so.
    accounted = len(excluded) + len(unscorable) + len(refusals) + len(usable)
    if accounted != grade_files_read:
        raise SystemExit(
            f"records do not add up: read {grade_files_read}, accounted {accounted} "
            f"(excluded {len(excluded)}, unscorable {len(unscorable)}, "
            f"refused {len(refusals)}, usable {len(usable)}). A record is being "
            f"dropped or double-counted between load_grades and here.")

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

    judge_models: dict[str, Counter] = defaultdict(Counter)
    for g in usable:
        judge_models[g["judge"]][served_model(g)] += 1
    for j, models in sorted(judge_models.items()):
        if len(models) > 1:
            print(f"WARNING: judge {j!r} served more than one model: {dict(models)}. "
                  f"Each is calibrated on its own distribution, and any with fewer than "
                  f"{MIN_CALIBRATION_N} grades is not rescaled at all, so its scores enter "
                  f"unadjusted. Check that this is intended.", file=sys.stderr)

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
            cal = apply_calibration(raw, (g["judge"], served_model(g), g["mode"], dim), params)
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
               **dict(zip(("venue_type", "venue_agreed"),
                          resolve_venue([v for v in e["venue_type"] if v]))),
               "identity_recognised": any(e["identity_confident"])}
        for dim in DIMS:
            row[f"raw_{dim}"] = round(st.mean(e[f"raw_{dim}"]), 2)
            row[f"cal_{dim}"] = round(st.mean(e[f"cal_{dim}"]), 2)
            row[f"spread_{dim}"] = round(max(e[f"raw_{dim}"]) - min(e[f"raw_{dim}"]), 2) if len(e[f"raw_{dim}"]) > 1 else None
        row["cal_overall"] = round(sum(WEIGHTS[d] * row[f"cal_{d}"] for d in DIMS), 2)
        row["raw_overall"] = round(sum(WEIGHTS[d] * row[f"raw_{d}"] for d in DIMS), 2)
        transcripts_out.append(row)

    # Venue adjustment. The score is a weighted sum of the three dimensions, so
    # the effect is fitted and removed on EACH dimension. Fitting the composite
    # alone would leave the dimensions, the leader score and the confidence
    # interval disagreeing with each other.
    #
    # Blinded only. The open pass is a small control sample and fitting a venue
    # effect on it would be noise.
    blinded_rows = [t for t in transcripts_out if t["mode"] == "blinded"]
    venue_fit = {d: venue_effects(blinded_rows, field=f"cal_{d}") for d in DIMS}
    for d in DIMS:
        apply_venue_adjustment(blinded_rows, venue_fit[d], field=f"cal_{d}")
    for t in blinded_rows:
        t["cal_overall_venue_adj"] = round(
            sum(WEIGHTS[d] * t[f"cal_{d}_venue_adj"] for d in DIMS), 2)
    venue_counts: dict[str, int] = defaultdict(int)
    for t in blinded_rows:
        if t.get("venue_type"):
            venue_counts[t["venue_type"]] += 1

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
                key = f"cal_{dim}_venue_adj" if f"cal_{dim}_venue_adj" in rows[0] else f"cal_{dim}"
                out[dim] = round(weighted([(r[key], max(r["coverage"], 0.05)) for r in rows]), 1)
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
        # The interval belongs beside the score it qualifies, so it is written
        # into the same block rather than a parallel structure the renderer has
        # to join back up.
        if b:
            b["ci_low"], b["ci_high"] = bootstrap_ci(blinded, WEIGHTS, DIMS)
        halo = {}
        if b and o:
            for dim in DIMS:
                halo[dim] = round(o[dim] - b[dim], 1)
            halo["overall"] = round(o["overall"] - b["overall"], 1)

        judges_seen = sorted({g["judge"] for g in usable
                              if g["leader_slug"] == slug and g["mode"] == "blinded"})
        n = b.get("n_transcripts", 0)
        judge_spread = [t[f"spread_{d}"] for t in blinded for d in DIMS if t.get(f"spread_{d}") is not None]
        leaders_out.append({
            **person,
            "status": "scored",
            "blinded": b,
            "open": o,
            "halo": halo,
            "n_transcripts": n,
            "judges_used": judges_seen,
            "single_judge": len(judges_seen) < 2,
            "refusals": refusal_breakdown.get(slug),
            # A leader scored by one judge is less trustworthy than the transcript
            # count alone suggests, so the confidence label says so.
            "confidence": ("low" if len(judges_seen) < 2 else
                           ("high" if n >= HIGH_CONFIDENCE_TRANSCRIPTS else
                            ("medium" if n >= MIN_TRANSCRIPTS_FOR_CONFIDENCE else "low"))),
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
        "grade_files_read": grade_files_read,
        "grades_loaded": len(grades),
        "grades_used": len(usable),
        "grades_excluded_validation": len(excluded),
        "transcripts_with_blinded_consensus": len(all_b),
        "judge_call_counts": {"fable_blinded": len(fable), "astra_blinded": len(astra)},
        # Collected, reported, and deliberately NOT in any number above.
        # See SHADOW_JUDGES for why an arm waits here.
        "shadow_judges": shadow_report(shadow, usable, len(all_b) or None),
        "judge_raw_means_blinded": {
            "fable": {d: round(st.mean([g["grade"]["dimensions"][d]["score"] for g in fable]), 1) for d in DIMS} if fable else {},
            "astra": {d: round(st.mean([g["grade"]["dimensions"][d]["score"] for g in astra]), 1) for d in DIMS} if astra else {},
        },
        "inter_judge_correlation_overall": corr,
        "mean_abs_judge_gap_overall": round(st.mean([abs(a - b) for a, b in both]), 1) if both else None,
        "blinding_leakage_rate": round(
            sum(1 for t in all_b if t["identity_recognised"]) / len(all_b), 3) if all_b else None,
        "unscorable_subject_absent": len(unscorable),
        "unscorable_detail": unscorable_report,
        "bootstrap": {
            "resamples": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED, "interval": "95%",
            "unit": "transcript, resampled with replacement",
            "calibration": "held fixed; not refitted inside the resample",
        },
        # The venue adjustment, reported so a reader can see what it did and
        # reverse it. Each transcript keeps cal_<dim> next to cal_<dim>_venue_adj.
        "venue_effects": {d: venue_fit[d] for d in DIMS},
        "venue_counts": dict(venue_counts),
        "venue_min_n": MIN_VENUE_N,
        "venue_note": ("Points a FORMAT adds or removes with the speaker held fixed, fitted "
                       "as an additive leader+venue model and subtracted from each dimension. "
                       "Venues seen fewer than venue_min_n times get exactly zero."),
        # Which models actually answered for each judge. A judge is an ARM, not a
        # model, so a mid-corpus model bump would otherwise pool two different
        # distributions under one name. Calibration already keys on the model;
        # this makes the situation visible rather than merely handled.
        "judge_models": {j: dict(m) for j, m in sorted(judge_models.items())},
        "min_subject_share_pct": MIN_SUBJECT_SHARE,
        "judge_refusals": len(refusals),
        "judge_refusals_by_leader": refusal_breakdown,
        "leaders_below_min_transcripts": [l["slug"] for l in scored if l["n_transcripts"] < MIN_TRANSCRIPTS_FOR_CONFIDENCE],
        # judge|model|mode|dim. The model is part of the key because a judge is
        # an arm, not a model, and the Astra arm can fall back to another one.
        "calibration_params": {"|".join(str(x) for x in k): v for k, v in params.items()},
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
    write_atomic(audit_path, json.dumps(audit, indent=1))
    print(f"audit detail written to {audit_path}", file=sys.stderr)

    # Atomic, because every clone now shares one data/ checkout and any of them
    # may be reading results.json to deploy while this runs.
    write_atomic(args.out, json.dumps({
        "diagnostics": diagnostics,
        "leaders": scored,
        "unscored": [l for l in leaders_out if l["status"] != "scored"],
        "transcripts": transcripts_out,
    }, indent=1))
    print(json.dumps(diagnostics, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
