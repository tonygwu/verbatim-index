#!/usr/bin/env python3
"""Full-claim sequence rules and repaired criteria reach pricing and resolution.

No model calls or production data: CLI dry-runs and scoring use temporary records.
Historical pairs retain their old prompt; new resolutions require the new question.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R
import resolve_predictions as RP
import test_restatements_scoring as T
from test_resolution_policy import judged_section, legacy_prior_prompt

ROOT = Path(__file__).resolve().parent.parent
DEADLINE = dt.date(2020, 4, 30)
ORIGINAL = "By 2020-04-30, at least one website preorder will have shipped."
REPAIRED = ("In late April 2020, website preorders begin shipping after all crowdfunding "
            "rewards have shipped.")


def record():
    r = T.rec("sequence", target=DEADLINE.isoformat())
    r["source"]["quote"] = "We will ship website preorders in late April after all crowdfunding rewards have shipped."
    r["prediction"].update(normalized_claim=REPAIRED, resolution_criteria=ORIGINAL,
                           target_date_text="late April 2020")
    return r


def repair():
    return {"prediction_id": "sequence", "transcript_id": "ada/t1", "statement_date": "2019-01-01",
            "verdict": "repaired", "criterion": REPAIRED, "criterion_original": ORIGINAL,
            "reasoning": "Keep the sequence and the stated window in the quote.", "harness": "human_review"}


def put_repair(run, obj=None, slug="ada"):
    path = run / "criteria_repairs" / slug / "sequence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj or repair()))
    return path


class SequenceRules(unittest.TestCase):
    def test_sequence_in_each_source_field_reaches_every_stage_without_outcome_leak(self):
        texts = ("The Developer Center opens before development-kit shipments begin.",
                 "Website preorders ship in late April after all crowdfunding rewards have shipped.",
                 "Documentation launches prior to shipping kits.")
        for field in ("quote", "normalized_claim", "resolution_criteria"):
            for text in texts:
                with self.subTest(field=field, text=text):
                    r = record()
                    r["source"]["quote"] = "We will ship."
                    r["prediction"].update(normalized_claim="The product ships.", resolution_criteria="It ships.")
                    (r["source"] if field == "quote" else r["prediction"])[field] = text
                    prompts = [R.build_prior_prompt(r, DEADLINE), R.build_resolver_prompt(r, DEADLINE, "2026-10-19"),
                               R.build_early_prompt(r, DEADLINE, "2019-10-19")]
                    sections = [judged_section(p) for p in prompts]
                    self.assertIn("A STATED SEQUENCE", sections[0])
                    self.assertEqual(sections, [sections[0]] * 3)
                    self.assertIn("all rather than some", sections[0])
                    self.assertIn("late April", sections[0])
                    self.assertEqual(R.prior_prompt_leaks(prompts[0], R.prompt_facts(r, DEADLINE)), [])
                    r["resolution"] = {"outcome": "not_occurred", "reasoning": "PRIVATE OUTCOME SENTINEL"}
                    self.assertEqual(R.build_prior_prompt(r, DEADLINE), prompts[0])

    def test_absolute_dates_and_cohort_labels_do_not_trigger(self):
        for text in ("We will ship before April 30, 2020.", "After 2020 we will ship.",
                     "Before the end of April we will ship.", "Post-Kickstarter website preorders will ship.",
                     "All rewards will ship by April 30."):
            with self.subTest(text=text):
                r = record()
                r["source"]["quote"] = text
                r["prediction"].update(normalized_claim=text, resolution_criteria=text)
                self.assertNotIn("A STATED SEQUENCE", R.judged_block(r))
                self.assertEqual(R.build_prior_prompt(r, DEADLINE), legacy_prior_prompt(r, DEADLINE))

    def test_already_public_requires_full_claim_in_both_outcome_prompts(self):
        for task in (R.RESOLVER_TASK, R.EARLY_TASK):
            rule = task.split("ALREADY PUBLIC BEFORE IT WAS SAID", 1)[1]
            for text in ("FULL\n   claim", "time window, sequence", "all rather\n   than some",
                         "access before shipments", "different shipping month"):
                self.assertIn(text, rule)

    def test_repairs_validate_preserve_original_and_refuse_stale_or_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a", Path(td) / "b"
            path = put_repair(a)
            rows = [record()]
            loaded = RP.repairs_across([a, a])
            self.assertEqual(R.apply_repairs(rows, loaded), (1, 0))
            self.assertEqual(rows[0]["prediction"]["resolution_criteria_original"], ORIGINAL)
            self.assertEqual(rows[0]["prediction"]["resolution_criteria"], REPAIRED)
            for builder in (lambda r: R.build_prior_prompt(r, DEADLINE),
                            lambda r: R.build_resolver_prompt(r, DEADLINE, "2026-10-19")):
                self.assertIn("  " + REPAIRED + "\n", builder(rows[0]))
                self.assertNotIn("  " + ORIGINAL + "\n", builder(rows[0]))
            changed = record()
            changed["prediction"]["resolution_criteria"] = "A newly extracted criterion."
            with self.assertRaisesRegex(ValueError, "stale criteria repair"):
                R.apply_repairs([changed], loaded)
            put_repair(b)
            with self.assertRaisesRegex(SystemExit, "sidecars in two runs"):
                RP.repairs_across([a, b])
            put_repair(a, slug="duplicate")
            with self.assertRaisesRegex(ValueError, "duplicate repair"):
                R.load_repairs(a)
            path.unlink()
            bad = repair()
            bad["criterion"] = None
            put_repair(a, bad, slug="duplicate")
            with self.assertRaisesRegex(ValueError, "invalid criteria repair"):
                R.load_repairs(a)
            self.assertEqual(RP.repairs_across([b], {"ada/t1": {"statement_date": "2018-01-01"}}), {})

    def test_runner_reads_repairs_from_scoring_runs_and_output_before_all_prompts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus = root / "predictions"
            (corpus / "ada").mkdir(parents=True)
            source = corpus / "ada" / "t1.jsonl"
            source.write_text(json.dumps(record()) + "\n")
            original_bytes = source.read_bytes()
            scored, out = root / "scored", root / "out"
            scored.mkdir()
            config = corpus / "scoring.json"
            config.write_text(json.dumps({"as_of": "2026-10-19", "trend": False, "min_lead_days": 60,
                                          "predictions": ["predictions"], "runs": ["scored"],
                                          "index": "predictions/index.json", "out": "predictions/scores.json"}))
            for run in (scored, out):
                rp = put_repair(run)
                for stage in ("prior", "resolve", "early"):
                    with self.subTest(run=run.name, stage=stage):
                        got = subprocess.run([sys.executable, str(ROOT / "scripts/resolve_predictions.py"),
                                              "--predictions", str(corpus), "--out", str(out), "--stage", stage,
                                              "--as-of", "2019-10-19" if stage == "early" else "2026-10-19",
                                              "--dry-run"], capture_output=True, text=True)
                        self.assertEqual(got.returncode, 0, got.stderr)
                        self.assertIn("  " + REPAIRED + "\n", got.stdout)
                        self.assertNotIn("  " + ORIGINAL + "\n", got.stdout)
                rp.unlink()
            self.assertEqual(source.read_bytes(), original_bytes)

    def test_scorer_prices_repaired_question_and_preserves_historical_pairs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus, run = root / "predictions", root / "run"
            (corpus / "ada").mkdir(parents=True)
            (corpus / "ada/t1.jsonl").write_text(json.dumps(record()) + "\n")
            index = corpus / "index.json"
            index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada"}]}))
            repaired = copy.deepcopy(record())
            R.apply_repairs([repaired], {"sequence": repair()})
            old_hash = hashlib.sha256(legacy_prior_prompt(record(), DEADLINE).encode()).hexdigest()
            new_hash = hashlib.sha256(R.build_prior_prompt(repaired, DEADLINE).encode()).hexdigest()
            for release, sha, has_repair, stale in (("resolution-2026-10-11", old_hash, False, False),
                                                    ("resolution-2026-10-11", old_hash, True, True),
                                                    (R.POLICY_RELEASE[0], new_hash, True, False),
                                                    (R.POLICY_RELEASE[0], old_hash, True, True)):
                with self.subTest(release=release, prior=sha, repaired=has_repair):
                    if has_repair:
                        put_repair(run)
                    T.write(run, "sequence", "resolve", policy_release=release, deadline=DEADLINE.isoformat())
                    T.write(run, "sequence", "prior", prompt_sha256=sha, deadline=DEADLINE.isoformat())
                    dest = root / "scores.json"
                    got = subprocess.run([sys.executable, str(ROOT / "scripts/score_predictions.py"),
                                          "--predictions", str(corpus), "--index", str(index), "--run", str(run),
                                          "--as-of", "2026-10-19", "--out", str(dest),
                                          "--policy-release", "legacy", "--policy-release", release],
                                         capture_output=True, text=True)
                    self.assertEqual(got.returncode, 0, got.stderr)
                    doc = json.loads(dest.read_text())
                    stale_rows = doc["corpus"].get("stale_sidecars", [])
                    self.assertEqual(any(r["prediction_id"] == "sequence" for r in stale_rows), stale, stale_rows)
                    self.assertEqual(doc["corpus"]["criteria_repairs_applied"], int(has_repair))


if __name__ == "__main__":
    unittest.main()
