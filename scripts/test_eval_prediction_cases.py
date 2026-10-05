#!/usr/bin/env python3
"""The Tier R case harness, with a synthetic data root and fake models. No quota, no network.

Why (rescue round 4 design section 5, critique 3 E5 and F1): the operator's audited
cases must stay fixed, stage by stage, and the harness must never pass by
accident. What this pins:

  DATA     without the data root it refuses, and says so
  OFFLINE  deterministic stages (header, funnel) run with no model; a model stage
           replays a recorded answer only while its prompt's sha256 still matches,
           refusing with "prompt changed; re-record live" otherwise; a case with no
           recording is UNRECORDED, never a pass, and the run exits 3
  LIVE     refused unless PREDICT_LIVE=1; n repeats, each recorded; an infrastructure
           failure is excluded from n and counted; pass is a majority of the valid
           repeats with no hard failure; fewer than 2 valid repeats is inconclusive
  SMOKE    --smoke runs only the gold file's smoke list, in its order
  RESOLVE  a case needing a resolver field the contract lacks is BLOCKED before any
           call; with it, the already_public case and its controls are judged
  DATING   a recorded proposal and its recorded page checks go through the real
           merge; a confirmed date outside the gold band is a wrong
           auto-confirmation, and those are counted on their own line

  .venv/bin/python scripts/test_eval_prediction_cases.py
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_prediction_cases as E  # noqa: E402
import resolution_lib as R  # noqa: E402
from test_dating import D10, LIVEBLOG, proposal  # noqa: E402

REC_ID = "a1b2c3d4e5f60718"


def record(tid="ada/re-upload-abc123", pid=REC_ID, said="2019-02-27", basis="youtube_upload_date", target="2020"):
    slug, sid = tid.split("/")
    return {"prediction_id": pid, "transcript_id": tid, "leader_slug": slug, "source_id": sid, "accepted": True,
            "speaker": {"slug": slug, "name": "Ada L", "role": "CEO", "company": "Co"},
            "source": {"statement_date": said, "statement_date_basis": basis, "quote": "ada says the thing will ship",
                       "title": "t", "venue": "v", "context_before": "", "context_after": ""},
            "prediction": {"normalized_claim": "X ships.", "resolution_criteria": "By 2013-12-31, X ships.",
                           "target_date": target, "target_date_text": "next year", "horizon": "explicit",
                           "horizon_years_inferred": None, "specificity": "high", "category": "company_business",
                           "subject_control": "own"}}


def make_data(root: Path) -> Path:
    data = root / "data"
    (data / "transcripts_open" / "ada").mkdir(parents=True)
    (data / "transcripts_open" / "ada" / "re-upload-abc123.json").write_text(json.dumps(D10))
    (data / "predictions" / "ada").mkdir(parents=True)
    (data / "predictions" / "ada" / "re-upload-abc123.jsonl").write_text(json.dumps(record()) + "\n")
    # merge-5 reads the speaker's company from the roster; no fixture page names it.
    (data / "roster").mkdir()
    (data / "roster" / "final.json").write_text(json.dumps({"roster": [
        {"slug": "ada", "name": "Ada", "company": "Fixture Holdings"}]}))
    return data


HEADER = {"id": "H-override", "operator_case": "A3", "stage": "header",
          "input": {"transcript": "transcripts_open/ada/re-upload-abc123.json",
                    "override": {"statement_date": "2012-05-30", "basis": "DX 2012", "source_url": "https://e.example.com/x",
                                 "verbatim_evidence": "May 30, 2012", "confirmed_by": "eval gold",
                                 "confirmed_at_utc": "2026-09-29T00:00:00Z"}},
          "expect": {"contains": ["Statement date: 2012-05-30 (the day the words were spoken"],
                     "not_contains": ["no later than 2019-02-27"]}}
FUNNEL = {"id": "F-lead", "operator_case": "A5", "stage": "funnel",
          "input": {"record": {"file": "predictions/ada/re-upload-abc123.jsonl", "prediction_id": REC_ID},
                    "set": {"source.statement_date": "2012-05-30", "prediction.target_date": "2012-06-06"},
                    "as_of": "2026-09-28", "implied": 1.0},
          "expect": {"deadline": "2012-06-06", "lead_days": [7, 7], "eligible": False, "past_due": True}}
DATING = {"id": "D-dx", "operator_case": "A3", "stage": "dating",
          "input": {"transcript": "transcripts_open/ada/re-upload-abc123.json",
                    "records": "predictions/ada/re-upload-abc123.jsonl", "harness": "gemini"},
          "expect": {"pass_within": ["2012-05-30", "2012-05-30"], "hard_outside": ["2012-05-30", "2012-05-30"]}}
RESOLVE = {"id": "R-public", "operator_case": "A3", "stage": "resolve",
           "input": {"record": {"file": "predictions/ada/re-upload-abc123.jsonl", "prediction_id": REC_ID},
                     "set": {"source.statement_date": "2012-05-30", "prediction.target_date": None,
                             "prediction.target_date_text": None, "prediction.horizon": "none",
                             "prediction.subject_control": "external"},
                     "deadline": "2015-05-30", "today": "2026-09-29",
                     "harness": "astra"},
           "expect": {"already_public": "present", "already_public_on_or_before": "2012-05-30",
                      "already_public_mentions_all": [["thing"]]}}
CONTROL = {**copy.deepcopy(RESOLVE), "id": "R-control",
           "expect": {"already_public": "null", "hard_if_present_on_or_before": "2012-05-30"}}


def gold(root: Path, cases, smoke=None) -> Path:
    g = root / "gold"
    g.mkdir()
    (g / "cases.json").write_text(json.dumps({"schema_version": 1, "gold_set": "test", "smoke": smoke or [],
                                              "cases": cases}))
    return g


def run(argv, env=None, **kw):
    out = io.StringIO()
    with patch.dict(os.environ, env or {}, clear=False), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(out):
        rc = E.main(argv, **kw)
    return rc, out.getvalue()


def resolver_answer(pid=REC_ID, public=True, date="2012-05-29"):
    return {"prediction_id": pid, "outcome": "occurred", "confidence": "high", "reasoning": "r",
            "sources": [{"what_it_shows": "s", "where": "https://e.example.com", "date": "2012-06-04"}],
            "unresolvable_reason": None, "searched": ["q one", "q two", "q three"],
            "already_public": {"date": date, "where": "https://news.example.com/deal",
                               "what_it_shows": "the thing was reported"} if public else None}


# What the Astra harness records for a call that ran the three queries above
# (grade.web_search_actions): production's effort check reads exactly this.
SEARCHED = {"served_model": "gpt-6-astra", "web_search": {"queries": ["q one", "q two", "q three"], "opens": 0}}


MODELS = {"gemini": "gemini-3.8-flash-high", "fable": "claude-fable-5-1"}


def fable_cannot_date(gemini_answers):
    """A live caller: Gemini answers from the iterator (an exception is raised), Fable cannot date."""
    def caller(harness, prompt, timeout, workdir, args, idx):
        if harness == "fable":
            return json.dumps(proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None,
                                       event_kind=None)), {"served_model": MODELS["fable"]}, "f"
        x = next(gemini_answers)
        if isinstance(x, Exception):
            raise x
        return x, {"served_model": MODELS["gemini"]}, "a@example.com"
    return caller


class Offline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)

    def test_refuses_without_the_data_root(self):
        g = gold(self.root, [HEADER])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.root / "nowhere")])
        self.assertIn("data", str(cm.exception))

    def test_deterministic_stages_run_and_a_model_stage_without_a_recording_is_not_a_pass(self):
        g = gold(self.root, [HEADER, FUNNEL, DATING])
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 3, out)
        self.assertIn("[PASS] H-override", out)
        self.assertIn("[PASS] F-lead", out)
        self.assertIn("[UNRECORDED] D-dx", out)

    def test_a_failing_deterministic_case_fails(self):
        bad = copy.deepcopy(FUNNEL)
        bad["expect"]["eligible"] = True
        rc, out = run(["--gold", str(gold(self.root, [bad])), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("[FAIL] F-lead", out)

    def record_dating(self, g, text, prompt_sha=None, checks=None, fable=None, served=None, case=DATING,
                      wrong_harness=None):
        """One repeat: Gemini's answer (text, checks) and Fable's (cannot_date unless given), one file each.

        served overrides one dater's served model, {harness: model}; wrong_harness records Gemini's answer
        under that harness name instead."""
        d = g / "recordings" / case["id"]
        d.mkdir(parents=True, exist_ok=True)
        n = E._next_repeat(d)
        fable_text = fable or json.dumps(proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None,
                                                  event_kind=None))
        for h, t, c in (("gemini", text, checks), ("fable", fable_text, [])):
            label = wrong_harness if (h == "gemini" and wrong_harness) else h
            prompt = E.build_prompt(case, E.Context(self.data, g), h)
            (d / f"r{n:02d}.{label}.json").write_text(json.dumps({
                "prompt_sha256": (prompt_sha if h == "gemini" and prompt_sha else
                                  hashlib.sha256(prompt.encode()).hexdigest()),
                "response_text": t, "harness": label, "served_model": (served or {}).get(h) or MODELS[h],
                "requested_model": MODELS[h], "telemetry": {}, "source_checks": c or [],
                "recorded_at_utc": "2026-09-30T00:00:00Z"}))

    def dx_checks(self, obj, page=LIVEBLOG):
        return [E.DL.check_source(s, D10, {"status": 200, "final_url": s["url"], "body": page.encode(),
                                           "via": "direct", "error": None}) for s in obj["sources"]]

    def test_replay_runs_the_real_merge_and_counts_a_wrong_auto_confirmation(self):
        g = gold(self.root, [DATING])
        good = proposal()
        for _ in range(3):
            self.record_dating(g, json.dumps(good), checks=self.dx_checks(good))
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx", out)
        self.assertIn("wrong auto-confirmations: 0", out)

        # A page that really says May 31 confirms the agent's May 31, and the gold says May 30.
        wrong = proposal(e="2012-05-31", l="2012-05-31",
                         sources=[{**good["sources"][0], "verbatim_excerpt": "Posted May 31, 2012 at 4:26 pm PT"}])
        g2 = self.root / "g2"
        g2.mkdir()
        (g2 / "cases.json").write_text((g / "cases.json").read_text())
        for _ in range(3):
            self.record_dating(g2, json.dumps(wrong), checks=self.dx_checks(wrong, LIVEBLOG.replace("May 30", "May 31")))
        rc, out = run(["--gold", str(g2), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("[HARD_FAIL] D-dx", out)
        self.assertIn("wrong auto-confirmations: 1", out)

    def test_a_recording_from_another_harness_or_model_is_refused(self):
        """Review item 5 (probe E1): an answer served by another model, or by a harness that is not one of the
        case's daters, is not this case's evidence."""
        good = proposal()
        for i, kw in enumerate(({"served": {"fable": "gemini-3.8-flash-high"}}, {"served": {"gemini": "some-other-model"}},
                                {"wrong_harness": "astra"})):
            g = self.root / f"g-wrong-{i}"
            g.mkdir()
            (g / "cases.json").write_text(json.dumps({"schema_version": 1, "cases": [DATING], "smoke": []}))
            self.record_dating(g, json.dumps(good), checks=self.dx_checks(good), **kw)
            self.record_dating(g, json.dumps(good), checks=self.dx_checks(good))
            rc, out = run(["--gold", str(g), "--data", str(self.data)])
            self.assertEqual(rc, 1, out)
            self.assertIn("[RECORDING_REFUSED] D-dx", out)

    def test_a_negative_case_passes_on_a_queue_and_fails_only_on_its_statement_date(self):
        """Review item 6 (probes E2, E3): a queue is the safe answer; an unsourced first day is not a date."""
        neg = {**DATING, "id": "N-dx", "expect": {"negative": True, "pass_within": ["2012-05-30", "2012-05-30"]}}
        g = gold(self.root, [neg])
        queued = proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None, event_kind=None)
        wide = proposal(e="2012-05-01", l="2012-05-30")
        for obj in (queued, queued, wide):
            self.record_dating(g, json.dumps(obj), checks=self.dx_checks(obj) if obj["sources"] else [], case=neg)
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] N-dx (3 of 3 valid repeats pass", out)

    def test_a_changed_prompt_is_refused(self):
        g = gold(self.root, [DATING])
        good = proposal()
        self.record_dating(g, json.dumps(good), prompt_sha="0" * 64, checks=self.dx_checks(good))
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("prompt changed; re-record live", out)


class Resolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)

    def test_blocked_before_any_call_while_the_contract_lacks_the_field(self):
        g = gold(self.root, [RESOLVE])
        calls = []
        with patch.object(R, "RESOLUTION_SCHEMA", {**R.RESOLUTION_SCHEMA,
                                                   "properties": {k: v for k, v in R.RESOLUTION_SCHEMA["properties"].items()
                                                                  if k != "already_public"}}):
            rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"},
                          caller=lambda *a: calls.append(a))
        self.assertEqual(calls, [])
        self.assertIn("[BLOCKED] R-public", out)
        self.assertEqual(rc, 3, out)

    def test_already_public_and_its_control_with_k_of_n(self):
        g = gold(self.root, [RESOLVE, CONTROL], smoke=["R-public", "R-control"])
        answers = {"R-public": [resolver_answer(), resolver_answer(), resolver_answer(public=False)],
                   "R-control": [resolver_answer(public=False)] * 3}
        seen = []

        def caller(harness, prompt, timeout, workdir, args, idx):
            case = "R-control" if "2012-05-30" in prompt and seen.count("R-public") >= 3 else "R-public"
            seen.append(case)
            return json.dumps(answers[case][seen.count(case) - 1]), SEARCHED, "codex"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live", "--smoke"], {"PREDICT_LIVE": "1"},
                      caller=caller)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] R-public (2 of 3 valid repeats pass", out)
        self.assertIn("[PASS] R-control", out)
        self.assertEqual(len(list((g / "recordings" / "R-public").glob("*.json"))), 3)

    def test_a_control_that_says_public_is_a_hard_failure(self):
        g = gold(self.root, [CONTROL])

        def caller(*a):
            return json.dumps(resolver_answer(date="2012-05-28")), SEARCHED, "codex"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"}, caller=caller)
        self.assertEqual(rc, 1, out)
        self.assertIn("[HARD_FAIL] R-control", out)


    # MERGE WITH THE RESOLVER POLICY (review of the combined branch, 2026-09-30). The
    # harness must judge what production would: the deadline production derives, the
    # record with the case's own dates, and production's effort check on the harness's
    # own search telemetry.
    def test_a_gold_deadline_production_would_not_derive_is_refused(self):
        wrong = copy.deepcopy(RESOLVE)
        wrong["input"]["deadline"] = "2017-05-30"
        g = gold(self.root, [wrong])

        def caller(*a):
            raise AssertionError("no call may be made for a case whose gold disagrees with production")
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"}, caller=caller)
        self.assertIn("gold deadline is 2017-05-30", str(cm.exception))
        self.assertIn("production derives 2015-05-30", str(cm.exception))

    def test_already_public_is_judged_against_the_cases_own_statement_date(self):
        g = gold(self.root, [RESOLVE])

        def caller(*a):
            # Dated after the case's 2012-05-30, though before the fixture's stored 2019 date.
            return json.dumps(resolver_answer(date="2012-06-04")), SEARCHED, "codex"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"}, caller=caller)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("invalid resolution", out)

    def test_an_answer_production_would_refuse_for_effort_is_not_a_pass(self):
        g = gold(self.root, [RESOLVE])

        def caller(*a):
            return json.dumps(resolver_answer()), {"served_model": "gpt-6-astra"}, "codex"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"}, caller=caller)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("research effort", out)
        # The recording keeps the telemetry, and replay applies the same check.
        rc2, out2 = run(["--gold", str(g), "--data", str(self.data)])
        self.assertNotEqual(rc2, 0, out2)
        self.assertIn("research effort", out2)


class Live(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)

    def test_refused_without_predict_live(self):
        """Review item 7: a reviewer's mutation of the gate reached real agy and spent 3 Gemini calls.
        The fakes raise, so a broken gate fails this test instead of spending quota."""
        g = gold(self.root, [DATING])

        def must_not_call(*a):
            raise AssertionError("the PREDICT_LIVE gate let a live call through")
        with patch.dict(os.environ, {"PREDICT_LIVE": ""}):
            with self.assertRaises(SystemExit) as cm:
                E.main(["--gold", str(g), "--data", str(self.data), "--live"], caller=must_not_call,
                       opener=must_not_call, sleep=lambda s: None)
        self.assertIn("PREDICT_LIVE=1", str(cm.exception))

    def test_infrastructure_failures_are_excluded_and_too_few_is_inconclusive(self):
        g = gold(self.root, [DATING])
        good = proposal()

        def caller(*a):
            raise RuntimeError("empty_response: status SUCCESS with an empty response")
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"},
                      caller=caller, opener=lambda url, t: (200, url, LIVEBLOG.encode(), "text/html"), sleep=lambda s: None)
        self.assertEqual(rc, 3, out)
        self.assertIn("[INCONCLUSIVE] D-dx", out)
        self.assertIn("empty_response 3", out)
        answers = iter([RuntimeError("cli_timeout: no answer"), json.dumps(good), json.dumps(good)])
        caller2 = fable_cannot_date(answers)
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"},
                      caller=caller2, opener=lambda url, t: (200, url, LIVEBLOG.encode(), "text/html"), sleep=lambda s: None)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx (2 of 2 valid repeats pass; 1 infrastructure failure excluded", out)

    def test_one_valid_pass_is_not_enough(self):
        """Two timeouts and one good answer: one valid repeat proves nothing about a sampled verdict."""
        g = gold(self.root, [DATING])
        answers = iter([RuntimeError("cli_timeout: no answer"), RuntimeError("auth_or_quota: spent"),
                        json.dumps(proposal())])
        caller = fable_cannot_date(answers)
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"},
                      caller=caller, opener=lambda url, t: (200, url, LIVEBLOG.encode(), "text/html"), sleep=lambda s: None)
        self.assertEqual(rc, 3, out)
        self.assertIn("[INCONCLUSIVE] D-dx  1 valid repeat(s)", out)

    def test_smoke_runs_only_its_list_in_order(self):
        g = gold(self.root, [FUNNEL, HEADER, DATING], smoke=["H-override", "F-lead"])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--smoke"])
        lines = [x for x in out.splitlines() if x.startswith("[")]
        self.assertEqual([x.split()[1] for x in lines], ["H-override", "F-lead"])
        self.assertEqual(rc, 0, out)

    def test_estimate_leaves_out_blocked_cases_and_a_bad_selection_exits(self):
        """Review item 15."""
        g = gold(self.root, [RESOLVE, DATING], smoke=["R-public", "D-dx"])
        with patch.object(R, "RESOLUTION_SCHEMA", {**R.RESOLUTION_SCHEMA,
                                                   "properties": {k: v for k, v in R.RESOLUTION_SCHEMA["properties"].items()
                                                                  if k != "already_public"}}):
            rc, out = run(["--gold", str(g), "--data", str(self.data), "--smoke", "--estimate"])
        self.assertIn("live run: 1 model cases x 3 repeats: 6 calls (fable 3, gemini 3)", out)
        self.assertIn("1 blocked case(s) spend nothing", out)
        for only in ("D-dx,NOPE", "NOPE"):
            with self.assertRaises(SystemExit) as cm:
                run(["--gold", str(g), "--data", str(self.data), "--only", only])
            self.assertIn("NOPE", str(cm.exception))

    def test_a_minority_of_passes_is_a_fail(self):
        """Review mutation M44."""
        from collections import Counter
        self.assertEqual(E.aggregate([("pass", ""), ("fail", "x"), ("fail", "y")], Counter())[0], "FAIL")

    def test_smoke_cost_is_stated_before_a_live_run(self):
        g = gold(self.root, [RESOLVE, DATING], smoke=["R-public", "D-dx"])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--smoke", "--estimate"])
        self.assertIn("live run: 2 model cases x 3 repeats: 9 calls (astra 3, fable 3, gemini 3)", out)


if __name__ == "__main__":
    unittest.main()
