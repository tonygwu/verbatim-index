#!/usr/bin/env python3
"""The join from two independent stages to one published number.

What this pins, each of which would change a person's published score silently:
  - "unresolvable" is EXCLUDED, never scored as a miss, because a claim nobody can
    settle says nothing about the speaker;
  - a prediction with no prior, or no resolution, is counted and named rather than
    dropped, so the four buckets always add up to the corpus;
  - the eligibility rule is the operator's: specific, six months of lead, a window
    that does not close before it opens;
  - the published figure is a MEAN, so volume earns nothing;
  - a person below the rank floor keeps their number in the file and loses it on
    the page, which is how MIN_TRANSCRIPTS_TO_RANK already works;
  - the speaker's own q is used when they stated one, and only then.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import resolution_lib as R  # noqa: E402
import score_predictions as S  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, slug="ada", *, eligible=True, q=None, spec="high", lead=400):
    return {
        "prediction_id": pid, "leader_slug": slug, "transcript_id": f"{slug}/t1",
        "_deadline": dt.date(2020, 12, 31),
        "_flags": {"basis": "stated", "deadline_before_statement": False,
                   "specificity_high": spec == "high", "lead_days": lead,
                   "lead_ok": lead >= 180, "eligible": eligible},
        "prediction": {"normalized_claim": "c", "resolution_criteria": "crit"},
        "source": {"quote": "q", "statement_date": "2019-06-25"},
        "confidence": {"probability": q},
    }


def res(pid, outcome, reason=None):
    return {"prediction_id": pid, "outcome": outcome, "confidence": "high",
            "sources": [] if outcome == "unresolvable" else [{"where": "u", "what_it_shows": "w", "date": None}],
            "unresolvable_reason": reason, "reasoning": "r"}


def pri(pid, p):
    return {"prediction_id": pid, "p": p, "p_raw": p, "clamped": False,
            "reference_class": "rc", "reasoning": "r"}


def main() -> int:
    rows = [rec("a"), rec("b"), rec("c"), rec("d"), rec("e", eligible=False, spec="medium"),
            rec("f"), rec("g", q=0.75)]
    resolutions = {"a": res("a", "occurred"), "b": res("b", "not_occurred"),
                   "c": res("c", "unresolvable", "no_public_evidence"),
                   "d": res("d", "occurred"), "e": res("e", "occurred"),
                   "g": res("g", "occurred")}
    priors = {"a": pri("a", 0.1), "b": pri("b", 0.5), "c": pri("c", 0.5),
              "d": pri("d", 0.5), "e": pri("e", 0.5), "g": pri("g", 0.2)}
    joined, why = S.join(rows, resolutions, priors)
    by = {r["prediction_id"]: r for r in joined}

    check("SCORED: a long shot that landed is worth -log2(p)",
          by["a"]["scored"] and abs(by["a"]["points"] - 3.3219) < 1e-3, str(by["a"]["points"]))
    check("SCORED: a coin flip that missed costs exactly 1 point",
          abs(by["b"]["points"] + 1.0) < 1e-6, str(by["b"]["points"]))

    check("DECLINE: unresolvable is EXCLUDED, not scored as a miss",
          not by["c"]["scored"] and by["c"]["not_scored_because"] == "unresolvable:no_public_evidence"
          and by["c"]["points"] is None, str(by["c"]["not_scored_because"]))
    check("GATE: an ineligible prediction is resolved and still not scored, with the reason kept",
          not by["e"]["scored"] and by["e"]["not_scored_because"] == "not_eligible"
          and by["e"]["outcome"] == "occurred", str(by["e"]["not_scored_because"]))
    check("MISSING: a prediction with no resolution is named, never dropped",
          not by["f"]["scored"] and by["f"]["not_scored_because"] == "no_resolution")

    check("BUCKETS: every past-due prediction lands in exactly one bucket, and they add up",
          sum(why.values()) == len(rows) == len(joined), f"{dict(why)} over {len(rows)}")

    check("Q: a speaker who stated their own probability is scored by the two-probability rule",
          by["g"]["rule"] == "speaker_probability" and by["g"]["q"] == 0.75
          # join() rounds to 4 decimals, so the tolerance is the rounding, not the rule
          and abs(by["g"]["points"] - math.log2(0.75 / 0.2)) < 5e-5, str(by["g"]))
    check("Q: a speaker who stated none is scored by the baseline rule",
          by["a"]["rule"] == "baseline_only" and by["a"]["q"] is None)

    # ---- per leader -------------------------------------------------------
    leaders = S.per_leader(joined, {"ada": "Ada L"})
    ada = leaders[0]
    scored_pts = [by[k]["points"] for k in ("a", "b", "d", "g")]
    check("MEAN: the figure is the MEAN over scored predictions, so volume earns nothing",
          ada["n_scored"] == 4 and abs(ada["mean_points"] - sum(scored_pts) / 4) < 1e-4,
          f"{ada['n_scored']} {ada['mean_points']} vs {sum(scored_pts) / 4}")
    check("COUNTS: the unresolvable and the ineligible are reported beside the number",
          ada["past_due"] == 7 and ada["unresolvable"] == 1 and ada["eligible"] == 6
          and ada["resolved"] == 5, str({k: ada[k] for k in ("past_due", "eligible", "resolved", "unresolvable")}))
    check("FLOOR: four scored is below the floor of five, so the person is not ranked",
          S.MIN_SCORED_TO_RANK == 5 and ada["ranked"] is False and ada["mean_points"] is not None,
          "the number is kept in the file and withheld from the page")

    many = [rec(f"x{i}") for i in range(5)]
    lj, _ = S.join(many, {f"x{i}": res(f"x{i}", "occurred") for i in range(5)},
                   {f"x{i}": pri(f"x{i}", 0.5) for i in range(5)})
    check("FLOOR: five scored clears it",
          S.per_leader(lj, {"ada": "Ada L"})[0]["ranked"] is True)
    check("RATE: hit rate and mean p are reported so a mean can be read against them",
          S.per_leader(lj, {})[0]["hit_rate"] == 1.0 and S.per_leader(lj, {})[0]["mean_p"] == 0.5)

    # ---- the speaker's q is only read when it is a number ------------------
    for bad in (None, True, "0.7"):
        check(f"Q: {bad!r} is not a stated probability",
              S.speaker_q({"confidence": {"probability": bad}}) is None)
    check("Q: a real number is read", S.speaker_q({"confidence": {"probability": 0.4}}) == 0.4)

    # ---- ordering ---------------------------------------------------------
    two = S.per_leader(
        [dict(r, leader_slug=("hi" if i < 5 else "lo")) for i, r in enumerate(
            [{"prediction_id": str(i), "leader_slug": "x", "scored": True,
              "points": (2.0 if i < 5 else -2.0), "outcome": "occurred", "p": 0.5,
              "flags": {"eligible": True}} for i in range(10)])],
        {"hi": "High", "lo": "Low"})
    check("ORDER: leaders sort by mean, best first, and an unranked leader never leads",
          [l["slug"] for l in two] == ["hi", "lo"], str([(l["slug"], l["mean_points"]) for l in two]))

    # ---- end to end through the CLI, over real code paths -----------------
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td) / "run"
        for pid, o in resolutions.items():
            fp = R.sidecar_path(run, "resolve", "ada", pid)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps({**o, "leader_slug": "ada", "transcript_id": "ada/t1",
                                      "stage": "resolve", "deadline": "2020-12-31"}))
        loaded = R.load_sidecars(run, "resolve")
        check("IO: sidecars round-trip through the loader the scorer uses",
              set(loaded) == set(resolutions))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
