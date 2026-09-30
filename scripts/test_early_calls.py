#!/usr/bin/env python3
"""Calling a prediction before its deadline (VD-5 (c), operator 2026-09-29, "as Bayesian as possible").

An early call SCORES NOW, in both directions:
  occurred      a cited, dated source shows the criterion already met after the
                statement date;
  not_occurred  it can no longer happen by the deadline ("cannot_happen"), or the
                subject itself has publicly moved its own target past the
                deadline ("target_moved"), with a cited source;
  still_open    otherwise, the normal answer.
Each early result carries `early_called` in scores.json and is queued for a
FRESH resolution when the deadline arrives; the fresh answer then replaces the
early one through the replacement manifest (stage "early"), and the early answer
stays in the report as an agreement measure (critique 1 point 9: the fresh check
runs on EVERY record, so "occurred" does not get two looks and "not_occurred" one).

The prior is priced over the FULL window, byte-identical to the prompt used at
the deadline, and is never told the record is early (critique 1 points 9, 10).
There is no "more than 6 months out" limit (critique 2 point 2): an Optimus-shaped
record due in 94 days and an Isomorphic-shaped one ("sometime next year") are
selected.
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
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
import resolve_predictions as RP  # noqa: E402

FAILED = []
REL = R.POLICY_RELEASE[0]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, *, said="2025-05-01", target="2026-12-31", tdt="next year", spec="high", ctrl="external",
        cat="technology_product", claim=None):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical"},
        "prediction": {"target_date": target, "target_date_text": tdt, "horizon_years_inferred": None,
                       "specificity": spec, "subject_control": ctrl, "category": cat, "prediction_type": "milestone",
                       "horizon": "explicit", "normalized_claim": claim or f"claim {pid}",
                       "resolution_criteria": f"By the deadline, {pid} will have happened."},
        "source": {"statement_date": said, "quote": f"quote {pid}", "venue": "", "title": "t",
                   "context_before": "", "context_after": ""},
        "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None},
    }


def early(**over):
    obj = {"prediction_id": "opt", "outcome": "occurred", "not_occurred_basis": None, "confidence": "high",
           "sources": [{"what_it_shows": "sold to the public", "where": "https://x/", "date": "2026-05-27"}],
           "searched": ["a", "b", "c"], "already_public": None, "reasoning": "It already happened."}
    obj.update(over)
    return obj


def write(run, pid, stage, deadline, **kw):
    base = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "deadline": deadline}
    if stage == "resolve":
        base.update(stage="resolve", outcome="occurred", confidence="high", unresolvable_reason=None, reasoning="r",
                    sources=[{"where": "u", "what_it_shows": "w", "date": None}])
    elif stage == "prior":
        base.update(stage="prior", p=0.25, p_raw=0.25, clamped=False, reference_class="rc", reasoning="r")
    else:
        base.update(stage="early", outcome="occurred", not_occurred_basis=None, early_called=True, confidence="high",
                    sources=[{"where": "u", "what_it_shows": "w", "date": "2026-05-27"}], searched=["a", "b", "c"],
                    already_public=None, reasoning="r", as_of="2026-09-28", policy_release=REL)
    base.update(kw)
    fp = R.sidecar_path(run, stage, "ada", pid)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(base))


def main() -> int:
    d = dt.date(2026, 12, 31)
    print("the early prompt")
    t = " ".join(R.EARLY_TASK.split())
    check("PROMPT: three answers, still_open the normal one",
          '"occurred" | "not_occurred" | "still_open"' in R.EARLY_TASK and "This is the normal answer" in t)
    check("PROMPT: not_occurred when it cannot happen, or the subject itself moved its own target past the deadline",
          '"cannot_happen"' in t and '"target_moved"' in t and "moved its own target" in t, t[:1500])
    check("PROMPT: a state that must hold AT the deadline is not settled by holding today (critique 3 E6)",
          "AT the deadline" in t and "still_open" in t)
    check("PROMPT: the same effort, already-public and judged-block rules as the resolver",
          "at least three web searches" in t and "ALREADY PUBLIC BEFORE IT WAS SAID" in t
          and "HOW THIS RECORD IS JUDGED" in t)
    r0 = rec("opt")
    p = R.build_early_prompt(r0, d, "2026-09-28")
    check("PROMPT: the early prompt states today and the full deadline",
          "Today is 2026-09-28" in p and "Deadline:        2026-12-31" in p)

    print("the prior is the at-deadline prior, byte for byte")
    marked = dict(r0, _early={"outcome": "occurred"}, early_called=True, _due="not_due")
    check("PRIOR: a record marked early gets the byte-identical prior prompt (design S14)",
          R.build_prior_prompt(marked, d) == R.build_prior_prompt(r0, d))
    check("PRIOR: the prior prompt never mentions an early call", "early" not in R.build_prior_prompt(r0, d).lower())

    print("what an early answer must carry")
    ok = early()
    check("SCHEMA: a well-formed early call passes", L.check_schema(ok, R.EARLY_SCHEMA) == []
          and R.validate_early(ok, "opt", "2025-05-01", "2026-09-28") == [],
          str(L.check_schema(ok, R.EARLY_SCHEMA)) + str(R.validate_early(ok, "opt", "2025-05-01", "2026-09-28")))
    for label, obj in (
        ("occurred with no dated source", early(sources=[{"what_it_shows": "w", "where": "u", "date": None}])),
        ("occurred on a source dated before the statement", early(sources=[{"what_it_shows": "w", "where": "u",
                                                                            "date": "2025-04-01"}])),
        ("occurred on a source dated after today", early(sources=[{"what_it_shows": "w", "where": "u",
                                                                   "date": "2026-10-01"}])),
        ("not_occurred with no basis", early(outcome="not_occurred")),
        ("not_occurred with an invented basis", early(outcome="not_occurred", not_occurred_basis="unlikely")),
        ("still_open with a basis", early(outcome="still_open", not_occurred_basis="cannot_happen")),
        ("occurred with a basis", early(not_occurred_basis="target_moved")),
        ("two searches", early(searched=["a", "b"])),
    ):
        errs = R.validate_early(obj, "opt", "2025-05-01", "2026-09-28") + L.check_schema(obj, R.EARLY_SCHEMA)
        check(f"REFUSE: {label}", errs != [], "accepted")
    moved = early(outcome="not_occurred", not_occurred_basis="target_moved",
                  sources=[{"what_it_shows": "the company now targets 2027", "where": "u", "date": "2026-07-01"}])
    check("ACCEPT: not_occurred because the subject moved its own target, with a dated source",
          R.validate_early(moved, "opt", "2025-05-01", "2026-09-28") == [] and L.check_schema(moved, R.EARLY_SCHEMA) == [])
    still = early(outcome="still_open", sources=[])
    check("ACCEPT: still_open needs no source", R.validate_early(still, "opt", "2025-05-01", "2026-09-28") == [])
    out = R.early_record(r0, d, ok, run_id="r", harness="astra", account="a", telemetry={}, checked_at="t",
                         as_of="2026-09-28", prompt_sha="beef", release=REL, code_revision="c")
    check("RECORD: stage early, early_called, the window, the as-of and the release",
          out["stage"] == "early" and out["early_called"] is True and out["deadline"] == "2026-12-31"
          and out["as_of"] == "2026-09-28" and out["policy_release"] == REL and out["prompt_sha256"] == "beef",
          json.dumps(out)[:400])
    check("RECORD: a still_open record is not an early call",
          R.early_record(r0, d, still, run_id="r", harness="astra", account="a", telemetry={}, checked_at="t",
                         as_of="2026-09-28", prompt_sha="b", release=REL, code_revision="c")["early_called"] is False)
    check("PATH: early answers live apart from resolutions",
          R.sidecar_path(pathlib.Path("/x"), "early", "ada", "p").parts[-3] == "early")

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        corpus = root / "predictions"
        (corpus / "ada").mkdir(parents=True)
        recs = [rec("opt"),                                                    # due 2026-12-31: 94 days out
                rec("iso", said="2025-09-09", target=None, tdt="sometime next year"),  # derived 2026-12-31
                rec("vague", spec="low"),                                      # not eligible
                rec("past", said="2020-01-01", target="2021-12-31"),           # past due
                rec("late", said="2020-01-01", target="2026-06-30"),           # past due, called early before
                rec("both", said="2020-01-01", target="2026-06-30"),           # past due, early and fresh
                rec("miss", target="2027-06-30"),                              # not due, target moved
                rec("open", target="2027-06-30"),                              # not due, still open
                rec("nopri", target="2027-06-30"),                             # not due, called, no prior
                rec("stale", target="2027-06-30")]                             # early sidecar over another window
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))

        print("selection: eligible records not yet due, with no 6-month limit")
        sel = RP.select(corpus, dt.date(2026, 9, 28), 60, due="not_due")
        ids = {r["prediction_id"] for r in sel}
        check("SELECT: the Optimus shape, 94 days out, is selected", "opt" in ids, str(sorted(ids)))
        check("SELECT: the Isomorphic shape, 'sometime next year', closes 2026-12-31 and is selected",
              any(r["prediction_id"] == "iso" and r["_deadline"] == dt.date(2026, 12, 31) for r in sel), str(sorted(ids)))
        check("SELECT: a past-due record is not", "past" not in ids)
        rows, left = RP.narrow(sel, None, False, None)
        check("SELECT: an ineligible record is left out and counted",
              "vague" not in {r["prediction_id"] for r in rows} and left.get("specificity") == 1, str(dict(left)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = RP.main(["--stage", "early", "--predictions", str(corpus), "--out", str(root / "dry"),
                          "--as-of", "2026-09-28", "--dry-run"])
        check("CLI: --stage early --dry-run prints an early prompt and spends nothing",
              rc == 0 and "BEFORE its deadline" in buf.getvalue(), buf.getvalue()[:300])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = RP.main(["--stage", "prior", "--not-due", "--predictions", str(corpus), "--out", str(root / "dry"),
                          "--as-of", "2026-09-28", "--dry-run"])
        check("CLI: --stage prior --not-due prices a record before its deadline, with the at-deadline prompt",
              rc == 0 and "Stand on" in buf.getvalue() and "AT THE MOMENT IT WAS MADE" in buf.getvalue(),
              buf.getvalue()[:300])
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                RP.main(["--stage", "resolve", "--not-due", "--predictions", str(corpus), "--out", str(root / "dry"),
                         "--as-of", "2026-09-28", "--dry-run"])
            check("CLI: --not-due is refused for the resolver, which judges only a deadline that passed", False)
        except SystemExit as e:
            check("CLI: --not-due is refused for the resolver, which judges only a deadline that passed",
                  "--not-due" in str(e), str(e))

        print("the scorer")
        run = root / "predictions" / "_experiments" / "run-a"
        new = root / "predictions" / "_experiments" / "run-b"
        write(run, "opt", "early", "2026-12-31"); write(run, "opt", "prior", "2026-12-31", p=0.1)
        write(run, "late", "early", "2026-06-30"); write(run, "late", "prior", "2026-06-30")
        write(run, "both", "early", "2026-06-30"); write(run, "both", "prior", "2026-06-30")
        write(new, "both", "resolve", "2026-06-30", outcome="not_occurred")
        write(run, "miss", "early", "2027-06-30", outcome="not_occurred", not_occurred_basis="target_moved")
        write(run, "miss", "prior", "2027-06-30", p=0.7)
        write(run, "open", "early", "2027-06-30", outcome="still_open", early_called=False)
        write(run, "nopri", "early", "2027-06-30")
        write(run, "stale", "early", "2027-03-31"); write(run, "stale", "prior", "2027-03-31")
        write(run, "past", "resolve", "2021-12-31"); write(run, "past", "prior", "2021-12-31")
        cfg_path = corpus / "scoring.json"
        base = {"as_of": "2026-09-28", "trend": False, "min_lead_days": 60, "predictions": ["predictions"],
                "runs": ["predictions/_experiments/run-a", "predictions/_experiments/run-b"],
                "index": "predictions/index.json", "out": "predictions/scores.json",
                "policy_releases": ["legacy", REL]}

        def score(**extra):
            cfg_path.write_text(json.dumps({**base, **extra}))
            out = corpus / "scores.json"
            if out.exists():
                out.unlink()
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg_path)],
                               capture_output=True, text=True)
            return p, (json.loads(out.read_text()) if p.returncode == 0 else {})

        p, doc = score()
        check("OFF: without early_calls the early answers are not read, and nothing not yet due is scored",
              p.returncode == 0 and {r["prediction_id"] for r in doc["predictions"]} == {"past", "late", "both"}
              and not any("early_called" in r for r in doc["predictions"]), p.stderr[-400:])
        p, doc = score(early_calls=True)
        check("REFUSE: an early call and a fresh resolution of one past-due record, with no manifest entry",
              p.returncode != 0 and "both" in p.stderr and "early" in p.stderr and "replacement" in p.stderr,
              p.stderr[-500:])
        man = corpus / "replacements.json"
        man.write_text(json.dumps({"schema_version": 1, "replacements": [
            {"stage": "early", "prediction_id": "both", "run": "predictions/_experiments/run-a",
             "replacement": "predictions/_experiments/run-b", "reason": "the fresh check at the deadline"}]}))
        p, doc = score(early_calls=True, replacements="predictions/replacements.json")
        check("ON: exits 0", p.returncode == 0, p.stderr[-600:])
        rows = {r["prediction_id"]: r for r in doc.get("predictions", [])}
        o = rows.get("opt", {})
        check("SCORE NOW: an early 'occurred' before the deadline is scored, flagged early_called",
              o.get("scored") and o.get("early_called") is True and o.get("outcome") == "occurred"
              and o.get("points") is not None and o.get("not_due") is True, json.dumps(o)[:400])
        m = rows.get("miss", {})
        check("SCORE NOW: an early 'not_occurred' (the subject moved its own target) is scored as a miss",
              m.get("scored") and m.get("early_called") and m.get("outcome") == "not_occurred" and m["points"] < 0
              and m.get("early", {}).get("not_occurred_basis") == "target_moved", json.dumps(m)[:400])
        check("STILL OPEN: a still_open answer puts nothing on the board", "open" not in rows)
        check("NO PRIOR: an early call with no prior is a row, not a score",
              rows.get("nopri", {}).get("not_scored_because") == "no_prior" and rows["nopri"].get("early_called"),
              json.dumps(rows.get("nopri"))[:300])
        lt = rows.get("late", {})
        check("QUEUE: past its deadline with no fresh check yet, the early call still scores and is queued",
              lt.get("scored") and lt.get("early_called") and lt.get("fresh_check_due") is True,
              json.dumps(lt)[:400])
        b = rows.get("both", {})
        check("REPLACED: at the deadline the fresh answer replaces the early one",
              b.get("outcome") == "not_occurred" and not b.get("early_called"), json.dumps(b)[:400])
        rp = doc.get("replacements", {}).get("replaced_sidecars", [])
        check("REPLACED: the early answer stays in the report beside the fresh one, as an agreement measure",
              {"stage": "early", "prediction_id": "both", "was": "occurred", "now": "not_occurred"}.items()
              <= (rp[0] if rp else {}).items(), json.dumps(rp))
        st = rows.get("stale", {})
        check("STALE: an early answer over another window is a counted exclusion",
              st.get("not_scored_because") == "stale_sidecar:deadline_changed", json.dumps(st)[:300])
        e = doc.get("corpus", {}).get("early_calls", {})
        check("REPORT: scores.json counts early calls scored before the deadline, queued, replaced and still open",
              e == {"scored_before_deadline": 2, "scored_past_deadline_awaiting_fresh_check": 1,
                    "replaced_by_fresh_check": 1, "still_open": 1, "awaiting_fresh_check": ["late"]}, json.dumps(e))
        c = doc.get("corpus", {})
        check("REPORT: past_due counts only records whose deadline passed", c.get("past_due") == 3, str(c.get("past_due")))
        lead = {l["slug"]: l for l in doc.get("leaders", [])}.get("ada", {})
        # early_called: opt, miss, nopri, late, stale. Scored: past, late, both (on its fresh
        # resolution), opt, miss.
        check("REPORT: the person's row counts their early calls, and past_due still excludes them",
              lead.get("early_called") == 5 and lead.get("past_due") == 3 and lead.get("n_scored") == 5
              and lead.get("eligible") == 3, json.dumps(lead))
        check("RULE: scores.json states that early calls score now", doc.get("rule", {}).get("early_calls") is True)
        write(run, "opt", "prior", "2027-01-31", p=0.1)
        p, _ = score(early_calls=True, replacements="predictions/replacements.json")
        check("WINDOW: a prior over another window than its early call is refused",
              p.returncode != 0 and "opt" in p.stderr and "window" in p.stderr, p.stderr[-300:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
