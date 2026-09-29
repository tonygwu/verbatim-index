#!/usr/bin/env python3
"""The join from two independent stages to one published number.

What this pins, each of which would change a person's published score silently:
  - "unresolvable" is EXCLUDED, never scored as a miss, because a claim nobody can
    settle says nothing about the speaker;
  - a prediction with no prior, or no resolution, is counted and named rather than
    dropped, so the four buckets always add up to the corpus;
  - the eligibility rule is the operator's: specific, six months of lead, a window
    that does not close before it opens;
  - eligibility is checked FIRST, so an ineligible row reads
    `not_eligible:<reason>` whether or not it was resolved, never `no_resolution`;
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


def rec(pid, slug="ada", *, eligible=True, q=None, spec="high", lead=400, before=False):
    # The flags resolve_predictions.select() writes, every key of them, because the
    # scorer names WHY a row is ineligible from these and refuses flags it cannot read.
    return {
        "prediction_id": pid, "leader_slug": slug, "transcript_id": f"{slug}/t1",
        "_deadline": dt.date(2020, 12, 31),
        "_flags": {"basis": "stated", "deadline_before_statement": before,
                   "specificity_high": spec == "high", "specificity_ok": spec in ("high", "medium"),
                   "lead_days": lead, "lead_ok": lead is not None and lead >= 60, "eligible": eligible},
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
    rows = [rec("a"), rec("b"), rec("c"), rec("d"), rec("e", eligible=False, spec="low"),
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
    check("GATE: an ineligible prediction is resolved and still not scored, with the reason named",
          not by["e"]["scored"] and by["e"]["not_scored_because"] == "not_eligible:specificity"
          and by["e"]["outcome"] == "occurred", str(by["e"]["not_scored_because"]))
    check("MISSING: a prediction with no resolution is named, never dropped",
          not by["f"]["scored"] and by["f"]["not_scored_because"] == "no_resolution")

    check("BUCKETS: every past-due prediction lands in exactly one bucket, and they add up",
          sum(why.values()) == len(rows) == len(joined), f"{dict(why)} over {len(rows)}")

    # ---- eligibility is checked FIRST (design 3.5, test S6) ----------------
    # An ineligible record is never resolved, so naming it "no_resolution" read as
    # "awaiting a check" and the page needed a workaround to call it not testable.
    # The reason is the first funnel stage that drops it.
    gate = [rec("lead", eligible=False, lead=30), rec("undated", eligible=False, lead=None),
            rec("back", eligible=False, lead=-20, before=True), rec("low", eligible=False, spec="low", lead=None),
            rec("unres", eligible=False, lead=30)]
    gj, gwhy = S.join(gate, {"unres": res("unres", "unresolvable", "no_public_evidence")},
                      {"unres": pri("unres", 0.5)})
    gb = {r["prediction_id"]: r for r in gj}
    want = {"lead": "not_eligible:lead_under_floor", "undated": "not_eligible:undated",
            "back": "not_eligible:deadline_before_statement", "low": "not_eligible:specificity",
            "unres": "not_eligible:lead_under_floor"}
    for pid, reason in want.items():
        check(f"S6: {pid} is not scored because {reason}",
              gb[pid]["not_scored_because"] == reason and not gb[pid]["scored"], str(gb[pid]["not_scored_because"]))
    check("S6: a resolved ineligible row keeps its outcome for audit, with the eligibility reason",
          gb["unres"]["outcome"] == "unresolvable" and gb["unres"]["unresolvable_reason"] == "no_public_evidence")
    check("S6: the reasons are counted apart, and still add up",
          gwhy == {"not_eligible:lead_under_floor": 2, "not_eligible:undated": 1,
                   "not_eligible:deadline_before_statement": 1, "not_eligible:specificity": 1}, str(dict(gwhy)))
    for label, bad in (("flags marked ineligible that name no reason", rec("x", eligible=False)),
                       ("flags missing a key the rule reads",
                        dict(rec("y", eligible=False, lead=30), _flags={"eligible": False, "basis": "stated"}))):
        try:
            S.join([bad], {}, {})
            got = "accepted"
        except SystemExit as exc:
            got = f"REFUSED {exc}"
        except Exception as exc:  # noqa: BLE001 - a crash is not a named refusal
            got = f"CRASH {type(exc).__name__}: {exc}"
        check(f"S6: REFUSE {label}, naming the prediction",
              got.startswith("REFUSED") and bad["prediction_id"] in got, got)

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
    # The floor is a constant the operator moves; it went 5 -> 3 on 2026-09-16.
    # These read it rather than hard-coding a number, so the case survives a move.
    below = [rec(f"b{i}") for i in range(S.MIN_SCORED_TO_RANK - 1)]
    bj, _ = S.join(below, {f"b{i}": res(f"b{i}", "occurred") for i in range(len(below))},
                   {f"b{i}": pri(f"b{i}", 0.5) for i in range(len(below))})
    b = S.per_leader(bj, {"ada": "Ada L"})[0]
    check("FLOOR: one short of the floor is not ranked, and KEEPS its number in the file",
          b["ranked"] is False and b["mean_points"] is not None,
          f"floor {S.MIN_SCORED_TO_RANK}, n {b['n_scored']}")

    many = [rec(f"x{i}") for i in range(S.MIN_SCORED_TO_RANK)]
    lj, _ = S.join(many, {f"x{i}": res(f"x{i}", "occurred") for i in range(len(many))},
                   {f"x{i}": pri(f"x{i}", 0.5) for i in range(len(many))})
    check("FLOOR: exactly the floor clears it",
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

    corpus_split_and_trend_rule()

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


def corpus_split_and_trend_rule() -> None:
    """Two blocks of scores.json the page reads, through the real CLI.

    Eligibility first (design 3.5) relabels an ineligible row the resolver
    answered "unresolvable" as not_eligible:<reason>, so corpus.by_outcome and
    corpus.unresolvable_reasons, which count outcomes, no longer equal the
    unresolvable:* rows. On production that is 118 against 93: 25 ineligible
    rows answered anyway (review 1 item 5). `unresolvable_by_eligibility` splits
    them. The trend rule decides which undated directional claims are judged at
    all, so `rule.trend` states it for the page instead of the page restating it
    (page review 0 item 3)."""
    import phase2_resolvability as P2
    print("scores.json splits unresolvable by eligibility and states the trend rule")

    def record(pid, said, target="2020-12-31"):
        return {"accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
                "prediction": {"target_date": target, "specificity": "high", "subject_control": "external",
                               "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                               "horizon_years_inferred": None, "prediction_type": "binary_event",
                               "normalized_claim": f"claim {pid}", "resolution_criteria": "crit"},
                "source": {"statement_date": said, "quote": f"quote {pid}"},
                "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None}}

    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        corpus = d / "predictions"
        (corpus / "ada").mkdir(parents=True)
        recs = [record("ok-unres", "2019-01-01"), record("ok-hit", "2019-01-01"),
                record("lead-unres", "2020-12-01"), record("back-unres", "2021-06-01")]
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        run = d / "run"
        outcomes = {"ok-unres": ("unresolvable", "no_public_evidence"), "ok-hit": ("occurred", None),
                    "lead-unres": ("unresolvable", "criterion_ambiguous"),
                    "back-unres": ("unresolvable", "deadline_incoherent")}
        for pid, (o, why) in outcomes.items():
            for stage, obj in (("resolve", {**res(pid, o, why), "deadline": "2020-12-31"}),
                               ("prior", {**pri(pid, 0.5), "deadline": "2020-12-31"})):
                fp = R.sidecar_path(run, stage, "ada", pid)
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps({**obj, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": stage}))
        docs = {}
        for trend in (True, False):
            out = d / f"scores-{trend}.json"
            argv = [sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--predictions", str(corpus),
                    "--index", str(corpus / "index.json"), "--run", str(run), "--as-of", "2026-09-28",
                    "--out", str(out)] + (["--trend"] if trend else [])
            p = subprocess.run(argv, capture_output=True, text=True)
            docs[trend] = json.loads(out.read_text()) if p.returncode == 0 else {"stderr": p.stderr[-400:]}
        c = docs[True].get("corpus", {})
        split = c.get("unresolvable_by_eligibility")
        check("SPLIT: unresolvable outcomes are split into eligible and not eligible, each with its reasons",
              split == {"eligible": {"n": 1, "reasons": {"no_public_evidence": 1}},
                        "not_eligible": {"n": 2, "reasons": {"criterion_ambiguous": 1, "deadline_incoherent": 1}}},
              str(split if split is not None else docs[True].get("corpus", docs[True])))
        rows = docs[True].get("predictions", [])
        check("SPLIT: the eligible half is exactly the rows that read unresolvable:<reason>",
              split is not None and split["eligible"]["n"]
              == sum(1 for r in rows if str(r["not_scored_because"]).startswith("unresolvable:")))
        check("SPLIT: the two halves add up to the outcome count, which is unchanged",
              split is not None and split["eligible"]["n"] + split["not_eligible"]["n"]
              == c.get("by_outcome", {}).get("unresolvable") == 3, str(c.get("by_outcome")))
        for trend in (True, False):
            got = docs[trend].get("rule", {}).get("trend")
            check(f"RULE: the trend rule is stated, enabled={trend}, with its minimum years",
                  got == {"enabled": trend, "min_years": P2.MIN_TREND_YEARS}, str(got))


if __name__ == "__main__":
    sys.exit(main())
