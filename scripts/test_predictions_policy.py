#!/usr/bin/env python3
"""Quota-free regressions for policy releases and safe reuse of predictions."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import extract_predictions as D
import predictions_lib as L
import aggregate_predictions as A
import grade as G
from test_predictions_driver import REC, ROSTER, cand


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tx = self.root / "transcripts" / "ada" / "s1.json"
        self.tx.parent.mkdir(parents=True)
        self.tx.write_text(json.dumps(REC))
        self.out = self.root / "predictions"
        self.args = D.build_parser().parse_args([])
        self.args.extractor = "astra"
        self.args.verifier = "fable"
        self.args.force = False
        self.release = L.load_policy_release() if hasattr(L, "load_policy_release") else {"release": "test"}
        self.job = {
            "args": self.args, "path": str(self.tx), "out": self.out,
            "roster": {"ada": ROSTER}, "exclusions": {}, "router": None,
            "run_id": "test-run", "workroot": self.root / "work",
            "release": self.release, "code_revision": "test-code",
            "contract": L.extraction_contract(),
            "spec": L.read_spec(L.SKILL / L.EXTRACTION_SPEC) if hasattr(L, "read_spec")
                    else (L.SKILL / L.EXTRACTION_SPEC).read_text(),
            "schema": json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()),
            "schema_text": (L.SKILL / L.EXTRACTOR_SCHEMA).read_text(),
        }

    def test_old_success_is_not_silently_cached_or_overwritten(self):
        _, mp = D.paths_for(self.out, "ada", "s1")
        old = {"extract": {"status": "ok", "contract_id": "old-contract"},
               "verify": {"status": "not_run"}}
        D.write_meta(mp, old)
        before = mp.read_bytes()
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            result = D.extract_one(self.job)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "cache_stale")
        self.assertEqual(mp.read_bytes(), before)

    def test_shared_policy_changes_both_contracts(self):
        self.assertTrue(hasattr(L, "POLICY_SPEC"), "both stages need one shared policy")
        sk = self.root / "skill"
        shutil.copytree(L.SKILL, sk)
        before = [f(sk)["contract_id"] for f in (L.extraction_contract, L.verification_contract)]
        with (sk / L.POLICY_SPEC).open("a") as f:
            f.write("\nA policy change.\n")
        after = [f(sk)["contract_id"] for f in (L.extraction_contract, L.verification_contract)]
        self.assertTrue(all(a != b for a, b in zip(before, after)))
        with self.assertRaisesRegex(ValueError, "policy_release_mismatch"):
            L.load_policy_release(sk)

    def extract(self, empty=False):
        self.job["router"] = Mock()
        self.job["router"].pick.return_value = {"harness": "astra", "account_id": "codex"}
        obj = {"schema_version": "1", "transcript_id": "ada/s1", "attribution_notes": "",
               "subject_speech_share_estimate_pct": 100, "candidates_considered": 1,
               "cap_hit": False, "estimated_total_qualifying": 0 if empty else 1,
               "candidates": [] if empty else [cand("I think by 2030 most code will be written by AI")]}
        telemetry = {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}
        with patch.object(D, "call_harness", return_value=(json.dumps(obj), telemetry, "codex")):
            result = D.extract_one(self.job)
        self.assertEqual(result["status"], "ok")
        return D.paths_for(self.out, "ada", "s1")

    def verifier_job(self):
        job = {**self.job, "contract": L.verification_contract(),
               "extraction_spec": self.job["spec"], "extraction_schema_text": self.job["schema_text"],
               "spec": L.read_spec(L.SKILL / L.VERIFICATION_SPEC),
               "schema": json.loads((L.SKILL / L.VERIFIER_SCHEMA).read_text()),
               "schema_text": (L.SKILL / L.VERIFIER_SCHEMA).read_text()}
        job["router"] = Mock()
        job["router"].pick.return_value = {"harness": "fable", "account_id": "claude"}
        return job

    def test_identical_extraction_reuses_cache_without_a_call(self):
        rp, mp = self.extract()
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            self.assertEqual(D.extract_one(self.job)["status"], "cached")
        m = json.loads(mp.read_text())
        r = L.parse_lines(rp.read_text(), str(rp))[0]
        self.assertEqual(m["extract"]["audit"], r["extraction"]["telemetry"]["prediction_audit"])
        self.assertEqual(L.check_schema(r, L.load_record_schema()), [])
        saved = json.loads(next((self.out / "_inputs").rglob("*.json")).read_text())
        self.assertEqual(saved["audit"]["input_sha256"], L.json_sha256(saved["inputs"]))
        self.assertEqual(saved["audit"]["prompt_sha256"], L.json_sha256(saved["prompts"]))
        self.assertIn((L.SKILL / L.POLICY_SPEC).read_text(), saved["prompts"][0])
        self.assertNotIn(L.POLICY_MARKER, saved["prompts"][0])

    def test_changed_input_prompt_or_model_is_not_reused(self):
        _, mp = self.extract()
        before = mp.read_bytes()
        for change in ("input", "prompt", "model"):
            with self.subTest(change=change):
                rec = {**REC, "text": REC["text"] + " changed"} if change == "input" else REC
                self.tx.write_text(json.dumps(rec))
                job = {**self.job, "spec": self.job["spec"] + ("\nChanged prompt" if change == "prompt" else "")}
                with patch.object(self.args, "astra_model", "different-model" if change == "model" else "gpt-6-astra"):
                    with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
                        result = D.extract_one(job)
                self.assertEqual(result["error_type"], L.E_CACHE_STALE)
                self.assertEqual(mp.read_bytes(), before)

    def test_old_extraction_cannot_be_verified_even_with_force(self):
        rp, mp = self.extract()
        m = json.loads(mp.read_text())
        m["extract"]["contract_id"] = "legacy"
        D.write_meta(mp, m)
        before = mp.read_bytes()
        self.args.force = True
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            result = D.verify_one(self.verifier_job())
        self.assertEqual(result["error_type"], L.E_POLICY)
        self.assertEqual(mp.read_bytes(), before)

    def test_compatible_verification_and_changed_claim_cache(self):
        rp, mp = self.extract()
        record = L.parse_lines(rp.read_text(), str(rp))[0]
        verdict = {"prediction_id": record["prediction_id"], "attribution": "subject",
                   "gates": {g: True for g in L.GATES}, "claim_faithful": True,
                   "confidence_type_seen": "none", "qualifies": True,
                   "resolution_criteria": "By 2030, most code is AI-written.", "notes": None}
        obj = {"schema_version": "1", "transcript_id": "ada/s1", "verdicts": [verdict]}
        tel = {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}
        job = self.verifier_job()
        with patch.object(D, "call_harness", return_value=(json.dumps(obj), tel, "test")):
            result = D.verify_one(job)
        self.assertEqual(result["status"], "ok")
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            self.assertEqual(D.verify_one(job)["status"], "cached")
            rows = L.parse_lines(rp.read_text(), str(rp))
            self.assertEqual(L.check_schema(rows[0], L.load_record_schema()), [])
            rows[0]["prediction"]["normalized_claim"] = "A different claim."
            L.write_prediction_file(rp, L.serialise_lines(rows))
            self.assertEqual(D.verify_one(job)["error_type"], L.E_CACHE_STALE)

    def test_empty_extraction_has_versioned_no_call_verification(self):
        self.extract(empty=True)
        job = self.verifier_job()
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            self.assertEqual(D.verify_one(job)["status"], "nothing_to_verify")
            self.assertEqual(D.verify_one(job)["status"], "cached")

    def test_acceptance_pairs_do_not_pool_versions_or_pending(self):
        rp, _ = self.extract()
        r = L.parse_lines(rp.read_text(), str(rp))[0]
        one = json.loads(json.dumps(r))
        one["verification"].update(status="ok", contract_id="v1")
        one["accepted"] = True
        two = json.loads(json.dumps(one))
        two["verification"]["contract_id"] = "v2"
        two["accepted"] = False
        pairs = A.acceptance_by_contract_pair([one, two, r])
        self.assertEqual([p["reviewed"] for p in pairs], [1, 1])
        self.assertEqual([p["acceptance_rate"] for p in pairs], [1.0, 0.0])

    def test_cli_responses_are_saved_before_success_or_failure_parsing(self):
        raw = self.root / "raw" / "fable.json"
        payload = {"result": "answer", "modelUsage": {"claude-fable-5-1": {
            "inputTokens": 10, "outputTokens": 3}}, "total_cost_usd": 0.01}
        proc = subprocess.CompletedProcess([], 0, json.dumps(payload), "stderr retained")
        with patch.object(G.subprocess, "run", return_value=proc):
            answer, tel = G.call_fable("prompt", "__DEFAULT__", 10, workdir=str(self.root),
                                      raw_response_path=raw)
        self.assertEqual(answer, "answer")
        self.assertEqual(tel["judge_model"], "claude-fable-5-1")
        self.assertEqual(json.loads(raw.read_text())["stdout"], proc.stdout)
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "astra answer"}},
            {"type": "turn.completed", "usage": {"reasoning_output_tokens": 2, "input_tokens": 10}},
        ]
        proc = subprocess.CompletedProcess([], 0, "\n".join(map(json.dumps, events)), "")
        raw = self.root / "raw" / "astra.json"
        with patch.object(G.subprocess, "run", return_value=proc):
            answer, tel = G.call_astra("prompt", 10, self.root, raw_response_path=raw)
        self.assertEqual(answer, "astra answer")
        self.assertEqual(tel["requested_model"], "gpt-6-astra")
        self.assertEqual(json.loads(raw.read_text())["stdout"], proc.stdout)
        proc = subprocess.CompletedProcess([], 1, "provider failure", "fatal stderr")
        with patch.object(G.subprocess, "run", return_value=proc):
            with self.assertRaises(RuntimeError):
                G.call_astra("prompt", 10, self.root, raw_response_path=raw)
        self.assertEqual(json.loads(raw.read_text())["stderr"], "fatal stderr")


if __name__ == "__main__":
    unittest.main()
