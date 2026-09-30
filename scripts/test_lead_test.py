#!/usr/bin/env python3
"""The forecast-versus-announcement test under the 60-day lead floor (VD-7 (c), operator 2026-09-29).

A record said less than MIN_LEAD_DAYS before its own deadline was excluded as an
announcement. Under VD-7 (c) such a record is scorable when it is a FORECAST:
about the world, or about the speaker's own organisation's RESULTS, numbers it
does not directly control. An announcement of the speaker's own plans or
schedule, and a relay of someone else's published schedule, stay excluded.
Records at or over the floor are unchanged.

The label is OUTCOME-BLIND: a pinned prompt on Fable with no tools, like the
prior stage, reading only prompt_facts, never a resolution. It is recorded on a
sidecar with its reason and prompt hash, and the scorer reads the label, behind
the optional scoring.json key `lead_test`. AlphaGo (ba64a6fd0016c9ea, DeepMind
announcing its own publishing plan, 4 days out) stays unscored.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
import resolve_predictions as RP  # noqa: E402

FAILED = []
REL = R.POLICY_RELEASE[0]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, *, said="2017-05-27", target="2017-05-31", spec="high", ctrl="own", cat="company_business",
        claim=None, quote=None):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical"},
        "prediction": {"target_date": target, "target_date_text": "x", "horizon_years_inferred": None,
                       "specificity": spec, "subject_control": ctrl, "category": cat, "prediction_type": "milestone",
                       "horizon": "explicit", "normalized_claim": claim or f"claim {pid}",
                       "resolution_criteria": f"By {target}, it will have happened."},
        "source": {"statement_date": said, "quote": quote or f"quote {pid}", "venue": "", "title": "t",
                   "context_before": "", "context_after": ""},
        "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None},
    }


def with_deadline(r):
    rows = [json.loads(json.dumps(r))]
    P2.attach_deadlines(rows, derive=True)
    return rows[0]


def write(run, pid, stage, deadline, **kw):
    base = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "deadline": deadline}
    if stage == "resolve":
        base.update(stage="resolve", outcome="not_occurred", confidence="high", unresolvable_reason=None,
                    reasoning="r", sources=[{"where": "u", "what_it_shows": "w", "date": None}])
    elif stage == "prior":
        base.update(stage="prior", p=0.9, p_raw=0.9, clamped=False, reference_class="rc", reasoning="r")
    else:
        base.update(stage="lead_test", label="world_forecast", reason="r", policy_release=REL, prompt_sha256="x")
    base.update(kw)
    fp = R.sidecar_path(run, stage, "ada", pid)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(base))


def main() -> int:
    print("the prompt: outcome-blind, pinned, four kinds")
    alphago = rec("ba64a6fd0016c9ea", claim="DeepMind will publish another ten AlphaGo self-play games each day "
                                            "until all 50 are released.",
                  quote="we'll publish another ten each day until all 50 have been released")
    r = with_deadline(alphago)
    p = R.build_lead_test_prompt(r, r["_deadline"])
    for k in R.LEAD_TEST_LABELS:
        check(f"PROMPT: names the kind {k}", f'"{k}"' in p)
    check("PROMPT: the four kinds are world and own-results forecasts, own-plan announcements and relays",
          set(R.LEAD_TEST_LABELS) == {"world_forecast", "own_results_forecast", "own_plan_announcement", "relay"}
          and set(R.FORECAST_LABELS) == {"world_forecast", "own_results_forecast"})
    check("ONE LIST: the funnel's forecast labels are the prompt's", P2.LEAD_TEST_FORECASTS == R.FORECAST_LABELS)
    loud = dict(r, resolution={"status": "resolved", "outcome": "not_occurred"}, _resolution={"outcome": "x"})
    check("BLIND: attaching a resolution does not move the prompt by one byte",
          R.build_lead_test_prompt(loud, r["_deadline"]) == p)
    check("BLIND: no outcome vocabulary in the authored text", R.prior_prompt_leaks(p, R.prompt_facts(r, r["_deadline"])) == [],
          str(R.prior_prompt_leaks(p, R.prompt_facts(r, r["_deadline"]))))
    check("BLIND: no date of today", "Today is" not in p)
    ok = {"prediction_id": "ba64a6fd0016c9ea", "label": "own_plan_announcement",
          "reason": "DeepMind decides its own publishing schedule."}
    check("SCHEMA: a well-formed label passes", L.check_schema(ok, R.LEAD_TEST_SCHEMA) == []
          and R.validate_lead_test(ok, "ba64a6fd0016c9ea") == [])
    check("SCHEMA: an invented label is refused", L.check_schema(dict(ok, label="forecast"), R.LEAD_TEST_SCHEMA) != [])
    check("SCHEMA: an answer about another prediction is refused", R.validate_lead_test(ok, "zzz") != [])
    out = R.lead_test_record(r, r["_deadline"], ok, run_id="r", harness="fable", account="a", telemetry={},
                             labelled_at="t", prompt_sha="beef", leaks=[], release=REL, code_revision="c")
    check("RECORD: the sidecar records the label, its reason, the prompt hash and the release",
          out["stage"] == "lead_test" and out["label"] == "own_plan_announcement" and out["reason"]
          and out["prompt_sha256"] == "beef" and out["policy_release"] == REL, json.dumps(out)[:300])
    check("PATH: labels live apart from every other stage",
          R.sidecar_path(pathlib.Path("/x"), "lead_test", "ada", "p").parts[-3] == "lead_tests")
    check("RELEASE: the lead-test prompt is part of the pinned release",
          "lead_test_task" in R._policy_parts() and R.check_policy_release() == REL)

    print("the funnel reads the label only under the floor")
    base = P2.funnel_flags(r, 60)
    check("OFF: without labels nothing changes and no lead_test key is written",
          not base["eligible"] and "lead_test" not in base, json.dumps(base))
    for label, want in (("own_plan_announcement", False), ("relay", False), ("world_forecast", True),
                        ("own_results_forecast", True)):
        f = P2.funnel_flags(r, 60, lead_labels={r["prediction_id"]: label})
        check(f"UNDER: labelled {label}, eligible is {want}", f["eligible"] is want and f["lead_test"]["label"] == label,
              json.dumps(f))
    f = P2.funnel_flags(r, 60, lead_labels={})
    check("UNDER: unlabelled, it stays out and says it awaits a label",
          not f["eligible"] and f["lead_test"] == {"label": None} and P2.ineligible_reason("x", f) == "lead_under_floor",
          json.dumps(f))
    far = with_deadline(rec("far", target="2018-12-31"))
    f = P2.funnel_flags(far, 60, lead_labels={"far": "own_plan_announcement"})
    check("OVER: a record at or over the floor is unchanged, whatever its label",
          f["eligible"] and "lead_test" not in f, json.dumps(f))
    vague = with_deadline(rec("vague", spec="low"))
    f = P2.funnel_flags(vague, 60, lead_labels={"vague": "world_forecast"})
    check("OTHER CLAUSES: a forecast label does not rescue a record that fails another clause",
          not f["eligible"] and P2.ineligible_reason("vague", f) == "specificity", json.dumps(f))

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        corpus = root / "predictions"
        (corpus / "ada").mkdir(parents=True)
        recs = [alphago,
                rec("world", said="2020-03-01", target="2020-03-20", ctrl="external", cat="market_industry"),
                rec("results", said="2021-10-10", target="2021-10-31", claim="Revenue will beat guidance."),
                rec("unlab", said="2020-03-01", target="2020-03-20", ctrl="external", cat="macro_economy"),
                rec("vague", said="2020-03-01", target="2020-03-20", spec="low"),
                rec("notdue", said="2026-09-10", target="2026-10-31", ctrl="external"),
                rec("far", said="2019-01-01", target="2020-12-31")]
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(x) + "\n" for x in recs))
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))

        print("the stage selects records whose only failing clause is the lead floor, due or not")
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = RP.main(["--stage", "lead_test", "--predictions", str(corpus), "--out", str(root / "dry"),
                          "--as-of", "2026-09-28", "--dry-run"])
        check("CLI: --stage lead_test --dry-run prints the blind prompt and spends nothing",
              rc == 0 and "FORECAST OR ANNOUNCEMENT" in buf.getvalue(), buf.getvalue()[:300] + err.getvalue()[-300:])
        sel = [l for l in err.getvalue().splitlines() if l.startswith("stage=lead_test")]
        check("CLI: five records fail only the floor (four past due, one not yet due); the vague and the far one "
              "are not selected", sel and "to run=5" in sel[0], str(sel))

        print("the scorer, behind lead_test")
        run = root / "predictions" / "_experiments" / "run-a"
        for pid, dl in (("ba64a6fd0016c9ea", "2017-05-31"), ("world", "2020-03-20"), ("results", "2021-10-31"),
                        ("unlab", "2020-03-20")):
            write(run, pid, "resolve", dl)
            write(run, pid, "prior", dl)
        write(run, "ba64a6fd0016c9ea", "lead_test", "2017-05-31", label="own_plan_announcement")
        write(run, "world", "lead_test", "2020-03-20", label="world_forecast")
        write(run, "results", "lead_test", "2021-10-31", label="own_results_forecast")
        cfg_path = corpus / "scoring.json"
        basecfg = {"as_of": "2026-09-28", "trend": False, "min_lead_days": 60, "predictions": ["predictions"],
                   "runs": ["predictions/_experiments/run-a"], "index": "predictions/index.json",
                   "out": "predictions/scores.json", "policy_releases": ["legacy", REL]}

        def score(**extra):
            cfg_path.write_text(json.dumps({**basecfg, **extra}))
            out = corpus / "scores.json"
            if out.exists():
                out.unlink()
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg_path)],
                               capture_output=True, text=True)
            return p, (json.loads(out.read_text()) if p.returncode == 0 else {})

        p, doc = score()
        rows = {x["prediction_id"]: x for x in doc.get("predictions", [])}
        check("OFF: without the key every record under the floor stays out, labels or not",
              p.returncode == 0 and all(rows[k]["not_scored_because"] == "not_eligible:lead_under_floor"
                                        for k in ("ba64a6fd0016c9ea", "world", "results", "unlab"))
              and "lead_test" not in doc.get("corpus", {}), p.stderr[-400:])
        p, doc = score(lead_test=True)
        rows = {x["prediction_id"]: x for x in doc.get("predictions", [])}
        check("ON: exits 0", p.returncode == 0, p.stderr[-400:])
        check("ALPHAGO: DeepMind announcing its own publishing plan stays unscored",
              rows.get("ba64a6fd0016c9ea", {}).get("not_scored_because") == "not_eligible:lead_under_floor"
              and rows["ba64a6fd0016c9ea"]["flags"]["lead_test"]["label"] == "own_plan_announcement",
              json.dumps(rows.get("ba64a6fd0016c9ea"))[:300])
        check("FORECAST: a world forecast under the floor is scored",
              rows.get("world", {}).get("scored") is True, json.dumps(rows.get("world"))[:300])
        check("FORECAST: a forecast of the speaker's own results under the floor is scored",
              rows.get("results", {}).get("scored") is True, json.dumps(rows.get("results"))[:300])
        check("UNLABELLED: a record under the floor with no label stays out",
              rows.get("unlab", {}).get("not_scored_because") == "not_eligible:lead_under_floor")
        lt = doc.get("corpus", {}).get("lead_test", {})
        check("REPORT: scores.json counts past-due records under the floor by label, and names the unlabelled",
              lt == {"by_label": {"own_plan_announcement": 1, "own_results_forecast": 1, "world_forecast": 1},
                     "unlabelled": ["unlab"], "scored_as_forecast": 2}, json.dumps(lt))
        check("RULE: scores.json states the test is on", doc.get("rule", {}).get("lead_test") is True)
        check("RELEASE: labels are counted by release", doc.get("policy_releases", {}).get("counts", {}).get("lead_test")
              == {REL: 3}, json.dumps(doc.get("policy_releases")))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
