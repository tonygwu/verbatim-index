#!/usr/bin/env python3
"""The rules refusal where production calls it: resolve_predictions.main, resolve and early stages.

Final review of the combined branch, 2026-09-30, item 3. run_one validates every
resolver and early answer (validate_resolution / validate_early, then
validate_effort on the harness's own search telemetry) and refuses a failing one
with E_RULES before any sidecar is written. The rules had unit tests; the call
site had none, so deleting the refusal, or the effort check, or the date bound it
passes, failed nothing.

Each case runs the stage entry point over a temporary corpus with call_astra
stubbed (no model, no quota, no network) and asserts: exit 1, the error log names
rule_violation, the run summary counts it, and NO sidecar was written. A control
answer that meets every rule IS written, so "no sidecar" is never vacuous.

  .venv/bin/python scripts/test_resolve_rules_refusal.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R  # noqa: E402
import resolve_predictions as RP  # noqa: E402

AS_OF = "2026-09-28"
THREE = ["engine ship date", "Analytical engine release", "Analytical annual report"]


def rec(pid, *, said, target, source_extra=None):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical"},
        "prediction": {"target_date": target, "target_date_text": f"by {target}", "horizon_years_inferred": None,
                       "specificity": "high", "subject_control": "external", "category": "technology_product",
                       "prediction_type": "milestone", "horizon": "explicit", "normalized_claim": f"claim {pid}",
                       "resolution_criteria": f"By {target}, {pid} will have happened."},
        "source": {"statement_date": said, "statement_date_basis": "stated_in_page", "quote": f"quote {pid}",
                   "venue": "", "title": "t", "context_before": "", "context_after": "", **(source_extra or {})},
        "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None},
    }


def telemetry(queries):
    """What grade.web_search_actions records for a codex call (test_resolution_effort.py drives the real one)."""
    return {"served_model": "gpt-6-astra", "web_search": {"search_actions": len(queries), "other_actions": 0,
                                                          "search_actions_without_queries": 0, "queries": queries}}


def resolution(pid, **over):
    obj = {"prediction_id": pid, "outcome": "occurred", "confidence": "high", "unresolvable_reason": None,
           "sources": [{"what_it_shows": "shipped", "where": "https://x.example.com/", "date": "2021-03-01"}],
           "searched": THREE, "already_public": None, "reasoning": "It shipped in March 2021."}
    obj.update(over)
    return obj


def early(pid, **over):
    obj = {"prediction_id": pid, "outcome": "occurred", "not_occurred_basis": None, "confidence": "high",
           "sources": [{"what_it_shows": "sold", "where": "https://x.example.com/", "date": "2026-05-27"}],
           "searched": THREE, "already_public": None, "reasoning": "It already happened."}
    obj.update(over)
    return obj


class RulesRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_stage(self, stage, record, answer, tel):
        corpus = self.root / "predictions"
        (corpus / "ada").mkdir(parents=True, exist_ok=True)
        (corpus / "ada" / "t1.jsonl").write_text(json.dumps(record) + "\n")
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        out, errs = self.root / f"run-{stage}-{record['prediction_id']}", self.root / "errors.jsonl"
        calls = []

        def fake_astra(prompt, timeout, workdir, **kw):
            calls.append(prompt)
            return json.dumps(answer), tel
        with patch.object(RP, "call_astra", fake_astra), contextlib.redirect_stderr(io.StringIO()) as log, \
                contextlib.redirect_stdout(io.StringIO()):
            rc = RP.main(["--stage", stage, "--predictions", str(corpus), "--out", str(out), "--as-of", AS_OF,
                          "--workdir", str(self.root / "work"), "--errors", str(errs), "--workers", "1"])
        self.assertEqual(len(calls), 1, log.getvalue()[-2000:])
        summary = json.loads(next((out / "_runs").glob("*.json")).read_text())
        lines = [json.loads(x) for x in errs.read_text().splitlines()] if errs.exists() else []
        sidecar = R.sidecar_path(out, stage, "ada", record["prediction_id"])
        return rc, summary, lines, sidecar

    def assert_refused(self, rc, summary, lines, sidecar, why):
        self.assertEqual(rc, 1)
        self.assertEqual(summary["error_taxonomy"], {RP.E_RULES: 1}, summary)
        self.assertEqual([x["error_type"] for x in lines], [RP.E_RULES])
        self.assertIn(why, lines[0]["detail"])
        self.assertFalse(sidecar.exists(), f"{sidecar} was written for a refused answer")

    # -- resolve ------------------------------------------------------------------
    def test_resolve_control_meets_every_rule_and_is_written(self):
        r = rec("ok", said="2020-01-01", target="2021-12-31")
        rc, summary, lines, sidecar = self.run_stage("resolve", r, resolution("ok"), telemetry(THREE))
        self.assertEqual((rc, summary["succeeded"], lines), (0, 1, []))
        self.assertTrue(sidecar.exists())

    def test_resolve_refuses_telemetry_with_two_queries(self):
        """The answer LISTS three searches; the harness ran two. Only the telemetry check sees it."""
        r = rec("two", said="2020-01-01", target="2021-12-31")
        self.assert_refused(*self.run_stage("resolve", r, resolution("two"), telemetry(THREE[:2])),
                            "the harness ran 2 distinct search queries")

    def test_resolve_refuses_already_public_on_the_statement_date(self):
        r = rec("same", said="2020-01-01", target="2021-12-31")
        ans = resolution("same", already_public={"date": "2020-01-01", "where": "https://n.example.com",
                                                 "what_it_shows": "reported"})
        self.assert_refused(*self.run_stage("resolve", r, ans, telemetry(THREE)),
                            "is not strictly before the statement date 2020-01-01")

    # -- early --------------------------------------------------------------------
    def test_early_control_meets_every_rule_and_is_written(self):
        r = rec("eok", said="2025-05-01", target="2026-12-31")
        rc, summary, lines, sidecar = self.run_stage("early", r, early("eok"), telemetry(THREE))
        self.assertEqual((rc, summary["succeeded"], lines), (0, 1, []))
        self.assertTrue(sidecar.exists())

    def test_early_refuses_telemetry_with_two_queries(self):
        r = rec("etwo", said="2025-05-01", target="2026-12-31")
        self.assert_refused(*self.run_stage("early", r, early("etwo"), telemetry(THREE[:2])),
                            "the harness ran 2 distinct search queries")

    def test_early_refuses_already_public_on_the_statement_date(self):
        r = rec("esame", said="2025-05-01", target="2026-12-31")
        ans = early("esame", already_public={"date": "2025-05-01", "where": "https://n.example.com",
                                             "what_it_shows": "reported"})
        self.assert_refused(*self.run_stage("early", r, ans, telemetry(THREE)),
                            "is not strictly before the statement date 2025-05-01")

    def test_early_refuses_already_public_inside_the_date_range(self):
        """The bound is the range's FIRST day (statement_bound), not the statement date."""
        r = rec("erange", said="2025-05-01", target="2026-12-31",
                source_extra={"statement_date_check": {"statement_date_earliest": "2025-04-25"}})
        ans = early("erange", already_public={"date": "2025-04-28", "where": "https://n.example.com",
                                              "what_it_shows": "reported"})
        self.assert_refused(*self.run_stage("early", r, ans, telemetry(THREE)),
                            "is not strictly before the statement date 2025-04-25")


if __name__ == "__main__":
    unittest.main()
