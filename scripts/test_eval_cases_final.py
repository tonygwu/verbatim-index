#!/usr/bin/env python3
"""The case harness after the final review of the combined branch, 2026-09-30 (items 5, 6, 7, 9).

Synthetic data root and fake models only: no quota, no network. What this pins:

  REPLAY   (item 5) one good resolver answer recorded live replays offline as a
           PASS. It fails if the recording drops the web_search telemetry, or if
           replay judges without the recorded telemetry: production's effort floor
           reads exactly that block, so either loss turns every replay into a miss
  GOLD     (item 6) every resolve and early case's gold deadline is checked against
           the deadline production derives BEFORE the first call, and --estimate
           says so too, so a --live run never spends calls before refusing; every
           funnel case states the implied-window configuration it tests, and the
           harness uses the one it states
  EARLY    (item 6) the early stage runs: production's early prompt, EARLY_SCHEMA,
           validate_early and the effort floor, and the case's expected outcome
  JUDGED   (item 7) "N judged dating cases" counts only cases that were judged:
           RECORDING_REFUSED and INCONCLUSIVE are not
  GUARDS   (item 9) an answer served by another model is never recorded or judged;
           an empty selection is refused rather than passing with nothing run

  .venv/bin/python scripts/test_eval_cases_final.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_prediction_cases as E  # noqa: E402
from test_dating import proposal  # noqa: E402
from test_eval_prediction_cases import (DATING, FUNNEL, REC_ID, RESOLVE, SEARCHED, gold, make_data,  # noqa: E402
                                        resolver_answer, run)

LIVE = {"PREDICT_LIVE": "1"}


def good_resolve_caller(calls=None):
    def caller(harness, prompt, timeout, workdir, args, idx):
        if calls is not None:
            calls.append(harness)
        return json.dumps(resolver_answer()), copy.deepcopy(SEARCHED), "codex"
    return caller


def early_answer(outcome="still_open", **over):
    obj = {"prediction_id": REC_ID, "outcome": outcome, "not_occurred_basis": None, "confidence": "high",
           "sources": [] if outcome == "still_open" else
           [{"what_it_shows": "shipped", "where": "https://e.example.com", "date": "2014-01-10"}],
           "searched": ["q one", "q two", "q three"], "already_public": None, "reasoning": "r"}
    obj.update(over)
    return obj


EARLY = {"id": "E-open", "operator_case": "A6", "stage": "early",
         "input": {"record": {"file": "predictions/ada/re-upload-abc123.jsonl", "prediction_id": REC_ID},
                   "set": {"source.statement_date": "2012-05-30", "prediction.target_date": "2015"},
                   "deadline": "2015-12-31", "today": "2014-06-01", "harness": "astra"},
         "expect": {"outcome_in": ["still_open"], "hard_outcomes": ["not_occurred"]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)


class RecordThenReplay(Base):
    def test_a_good_answer_recorded_live_replays_offline_as_a_pass(self):
        g = gold(self.root, [RESOLVE])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=good_resolve_caller())
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] R-public (3 of 3 valid repeats pass", out)
        recs = sorted((g / "recordings" / "R-public").glob("*.json"))
        self.assertEqual(len(recs), 3)
        self.assertEqual(json.loads(recs[0].read_text())["telemetry"]["web_search"], SEARCHED["web_search"])
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] R-public (3 of 3 valid repeats pass", out)


class GoldBeforeAnyCall(Base):
    def wrong(self, case=RESOLVE, deadline="2017-05-30", cid="R-wrong"):
        w = copy.deepcopy(case)
        w["id"], w["input"]["deadline"] = cid, deadline
        return w

    def test_live_refuses_before_its_first_call_even_when_a_good_case_comes_first(self):
        calls = []
        g = gold(self.root, [RESOLVE, self.wrong()])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=good_resolve_caller(calls))
        self.assertEqual(calls, [], "a call was spent before the gold was refused")
        self.assertIn("R-wrong", str(cm.exception))
        self.assertIn("production derives 2015-05-30", str(cm.exception))
        self.assertFalse((g / "recordings").exists())

    def test_estimate_refuses_a_gold_deadline_production_would_not_derive(self):
        g = gold(self.root, [RESOLVE, self.wrong()])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertIn("R-wrong", str(cm.exception))
        self.assertIn("gold deadline is 2017-05-30", str(cm.exception))

    def test_estimate_checks_early_cases_too(self):
        g = gold(self.root, [self.wrong(EARLY, "2016-12-31", "E-wrong")])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertIn("E-wrong", str(cm.exception))

    def test_a_correct_gold_estimates(self):
        g = gold(self.root, [RESOLVE, EARLY])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertEqual(rc, 0, out)
        self.assertIn("live run: 2 model cases x 3 repeats = 6 calls (astra 6)", out)


class FunnelConfiguration(Base):
    """Resolve cases derive deadlines with implied windows on; a funnel case says which it tests."""

    def implied_case(self, implied, expect):
        c = copy.deepcopy(FUNNEL)
        c["id"] = f"F-imp-{implied}"
        c["input"]["set"] = {"source.statement_date": "2012-05-30", "prediction.target_date": None,
                             "prediction.target_date_text": None, "prediction.horizon": "none",
                             "prediction.subject_control": "external"}
        c["input"]["implied"] = implied
        c["expect"] = expect
        return c

    def test_a_funnel_case_that_states_no_configuration_is_refused(self):
        bare = copy.deepcopy(FUNNEL)
        bare["input"].pop("implied", None)
        g = gold(self.root, [bare])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data)])
        self.assertIn("F-lead", str(cm.exception))
        self.assertIn("implied", str(cm.exception))

    def test_the_stated_configuration_is_the_one_used(self):
        on = self.implied_case(1.0, {"deadline": "2015-05-30", "eligible": False, "past_due": True,
                                     "failing_clauses": ["lead_under_floor"]})
        off = self.implied_case(None, {"deadline": None})
        rc, out = run(["--gold", str(gold(self.root, [on, off])), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] F-imp-1.0", out)
        self.assertIn("[PASS] F-imp-None", out)

    def test_a_wrong_failing_clause_fails(self):
        on = self.implied_case(1.0, {"deadline": "2015-05-30", "failing_clauses": []})
        rc, out = run(["--gold", str(gold(self.root, [on])), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("failing_clauses", out)


class EarlyStage(Base):
    def test_record_then_replay(self):
        g = gold(self.root, [EARLY])
        seen = []

        def caller(harness, prompt, timeout, workdir, args, idx):
            seen.append(prompt)
            return json.dumps(early_answer()), copy.deepcopy(SEARCHED), "codex"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=caller)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] E-open (3 of 3 valid repeats pass", out)
        self.assertIn("Today is 2014-06-01. The deadline is 2015-12-31, which has not passed.", seen[0])
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)

    def test_a_hard_outcome_is_a_hard_failure(self):
        g = gold(self.root, [EARLY])
        ans = early_answer("not_occurred", not_occurred_basis="cannot_happen")
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE,
                      caller=lambda *a: (json.dumps(ans), copy.deepcopy(SEARCHED), "codex"))
        self.assertEqual(rc, 1, out)
        self.assertIn("[HARD_FAIL] E-open", out)

    def test_production_rules_apply(self):
        """An early 'occurred' needs a source dated after the statement and by today (validate_early)."""
        g = gold(self.root, [dict(copy.deepcopy(EARLY), expect={"outcome_in": ["occurred"]})])
        ans = early_answer("occurred", sources=[{"what_it_shows": "w", "where": "https://e.example.com",
                                                 "date": "2015-01-10"}])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE,
                      caller=lambda *a: (json.dumps(ans), copy.deepcopy(SEARCHED), "codex"))
        self.assertEqual(rc, 1, out)
        self.assertIn("invalid early call", out)

    def test_the_effort_floor_applies(self):
        g = gold(self.root, [EARLY])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE,
                      caller=lambda *a: (json.dumps(early_answer()), {"served_model": "gpt-6-astra"}, "codex"))
        self.assertEqual(rc, 1, out)
        self.assertIn("research effort", out)


class JudgedCount(Base):
    def record(self, g, case, harness="gemini", served="gemini-3.8-flash-high", n=1):
        d = g / "recordings" / case["id"]
        d.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(E.build_prompt(case, E.Context(self.data, g)).encode()).hexdigest()
        for i in range(n):
            (d / f"r{i:02d}.json").write_text(json.dumps({
                "prompt_sha256": sha, "response_text": json.dumps(proposal()), "harness": harness,
                "served_model": served, "source_checks": [], "telemetry": {}}))

    def test_refused_and_inconclusive_cases_are_not_judged(self):
        refused, thin, queued = (dict(copy.deepcopy(DATING), id=x) for x in ("D-refused", "D-thin", "D-queued"))
        g = gold(self.root, [refused, thin, queued])
        self.record(g, refused, harness="fable")         # RECORDING_REFUSED
        self.record(g, thin, n=1)                         # one valid repeat: INCONCLUSIVE
        self.record(g, queued, n=2)                       # no checks, so the merge queues it: QUEUED, judged
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertIn("[RECORDING_REFUSED] D-refused", out)
        self.assertIn("[INCONCLUSIVE] D-thin", out)
        self.assertIn("[QUEUED] D-queued", out)
        self.assertIn("wrong auto-confirmations: 0 of 1 judged dating cases (2 of 3 not judged", out)


class Guards(Base):
    def test_an_answer_from_another_model_is_neither_recorded_nor_judged(self):
        g = gold(self.root, [RESOLVE])

        def caller(*a):
            return json.dumps(resolver_answer()), {**SEARCHED, "served_model": "gpt-5-other"}, "codex"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=caller)
        self.assertEqual(rc, 3, out)
        self.assertIn("[INCONCLUSIVE] R-public", out)
        self.assertIn("model_identity_mismatch 3", out)
        self.assertFalse(list((g / "recordings").glob("*/*.json")) if (g / "recordings").exists() else [])

    def test_an_empty_selection_is_refused(self):
        g = gold(self.root, [RESOLVE])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--only", ","])
        self.assertIn("selection is empty", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
