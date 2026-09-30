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
                    "as_of": "2026-09-28"},
          "expect": {"deadline": "2012-06-06", "lead_days": [7, 7], "eligible": False, "past_due": True}}
DATING = {"id": "D-dx", "operator_case": "A3", "stage": "dating",
          "input": {"transcript": "transcripts_open/ada/re-upload-abc123.json",
                    "records": "predictions/ada/re-upload-abc123.jsonl", "harness": "gemini"},
          "expect": {"pass_within": ["2012-05-30", "2012-05-30"], "hard_outside": ["2012-05-30", "2012-05-30"]}}
RESOLVE = {"id": "R-public", "operator_case": "A3", "stage": "resolve",
           "input": {"record": {"file": "predictions/ada/re-upload-abc123.jsonl", "prediction_id": REC_ID},
                     "set": {"source.statement_date": "2012-05-30"}, "deadline": "2017-05-30", "today": "2026-09-29",
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
            "unresolvable_reason": None,
            "already_public": {"date": date, "where": "https://news.example.com/deal",
                               "what_it_shows": "the thing was reported"} if public else None}


SCHEMA_WITH_PUBLIC = copy.deepcopy(R.RESOLUTION_SCHEMA)
SCHEMA_WITH_PUBLIC["properties"]["already_public"] = {"anyOf": [{"type": "null"}, {"type": "object"}]}


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

    def record_dating(self, g, text, prompt_sha=None, checks=None):
        d = g / "recordings" / "D-dx"
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.json")))
        prompt = E.build_prompt(DATING, E.Context(self.data, g))
        (d / f"r{n:02d}.json").write_text(json.dumps({
            "prompt_sha256": prompt_sha or hashlib.sha256(prompt.encode()).hexdigest(), "response_text": text,
            "telemetry": {}, "source_checks": checks or [], "recorded_at_utc": "2026-09-30T00:00:00Z"}))

    def dx_checks(self, obj):
        return [E.DL.check_source(s, D10, {"status": 200, "final_url": s["url"], "body": LIVEBLOG.encode(),
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

        wrong = proposal(e="2012-05-29", l="2012-05-31",
                         sources=[{**good["sources"][0], "verbatim_excerpt": "Posted May 30, 2012 at 4:26 pm PT"}])
        g2 = self.root / "g2"
        g2.mkdir()
        (g2 / "cases.json").write_text((g / "cases.json").read_text())
        for _ in range(3):
            self.record_dating(g2, json.dumps(wrong), checks=self.dx_checks(wrong))
        rc, out = run(["--gold", str(g2), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("[HARD_FAIL] D-dx", out)
        self.assertIn("wrong auto-confirmations: 1", out)

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
            return json.dumps(answers[case][seen.count(case) - 1]), {"served_model": "gpt-6-astra"}, "codex"
        with patch.object(R, "RESOLUTION_SCHEMA", SCHEMA_WITH_PUBLIC):
            rc, out = run(["--gold", str(g), "--data", str(self.data), "--live", "--smoke"], {"PREDICT_LIVE": "1"},
                          caller=caller)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] R-public (2 of 3 valid repeats pass", out)
        self.assertIn("[PASS] R-control", out)
        self.assertEqual(len(list((g / "recordings" / "R-public").glob("*.json"))), 3)

    def test_a_control_that_says_public_is_a_hard_failure(self):
        g = gold(self.root, [CONTROL])

        def caller(*a):
            return json.dumps(resolver_answer(date="2012-05-28")), {}, "codex"
        with patch.object(R, "RESOLUTION_SCHEMA", SCHEMA_WITH_PUBLIC):
            rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"}, caller=caller)
        self.assertEqual(rc, 1, out)
        self.assertIn("[HARD_FAIL] R-control", out)


class Live(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)

    def test_refused_without_predict_live(self):
        g = gold(self.root, [DATING])
        with patch.dict(os.environ, {"PREDICT_LIVE": ""}):
            with self.assertRaises(SystemExit) as cm:
                E.main(["--gold", str(g), "--data", str(self.data), "--live"])
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

        def caller2(*a):
            x = next(answers)
            if isinstance(x, Exception):
                raise x
            return x, {"served_model": "gemini-3.8-flash-high"}, "a@example.com"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], {"PREDICT_LIVE": "1"},
                      caller=caller2, opener=lambda url, t: (200, url, LIVEBLOG.encode(), "text/html"), sleep=lambda s: None)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx (2 of 2 valid repeats pass; 1 infrastructure failure excluded", out)

    def test_one_valid_pass_is_not_enough(self):
        """Two timeouts and one good answer: one valid repeat proves nothing about a sampled verdict."""
        g = gold(self.root, [DATING])
        answers = iter([RuntimeError("cli_timeout: no answer"), RuntimeError("auth_or_quota: spent"),
                        json.dumps(proposal())])

        def caller(*a):
            x = next(answers)
            if isinstance(x, Exception):
                raise x
            return x, {}, "a@example.com"
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

    def test_smoke_cost_is_stated_before_a_live_run(self):
        g = gold(self.root, [RESOLVE, DATING], smoke=["R-public", "D-dx"])
        with patch.object(R, "RESOLUTION_SCHEMA", SCHEMA_WITH_PUBLIC):
            rc, out = run(["--gold", str(g), "--data", str(self.data), "--smoke", "--estimate"])
        self.assertIn("live run: 2 model cases x 3 repeats = 6 calls (astra 3, gemini 3)", out)


if __name__ == "__main__":
    unittest.main()
