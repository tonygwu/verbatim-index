#!/usr/bin/env python3
"""The case harness for the 2026-10-04 dater comparison: pairs, the truth judge, and stored replays.

The operator's seven audited recordings are judged three ways at once: Gemini with
Fable (production, VD-11), Gemini with Fable given web tools, and Gemini with Astra.
One repeat calls every dater in the union once, so the pairs share Gemini's answer
and differ only in their second dater. Synthetic data root and fake models only, no
quota, no network:

  JUDGE     the "truth" shape: the last day inside the true range passes; a range
            accepted as a bound passes only as a range; a correct but wider bound
            fails softly; a range that misses the truth is a wrong auto-confirmation
  PAIRS     --estimate counts the union; each repeat calls each dater once and
            judges every pair; a failure excludes the repeat only for the pairs
            holding that dater, and a dater no pair could use is not called;
            the replay judges the same pairs from r<n>.<dater>.json and failed/
  STORED    dating_stored replays proposals and checks on disk through the real
            merge under the version the case names, every file pinned by sha256

  .venv/bin/python scripts/test_eval_dating_pairs.py
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
from test_dating import D10, LIVEBLOG, proposal  # noqa: E402
from test_eval_prediction_cases import gold, make_data, run  # noqa: E402

LIVE = {"PREDICT_LIVE": "1"}
MODELS = {"gemini": "gemini-3.8-flash-high", "fable": "claude-fable-5-1", "fable_web": "claude-fable-5-1",
          "astra": "gpt-6-astra"}
CANNOT = dict(verdict="cannot_date", e=None, l=None, sources=[], event=None, event_kind=None)
PAIRS = [["gemini", "fable"], ["gemini", "fable_web"], ["gemini", "astra"]]
CASE = {"id": "P-dx", "operator_case": "2026-10-04 test", "stage": "dating",
        "input": {"transcript": "transcripts_open/ada/re-upload-abc123.json",
                  "records": "predictions/ada/re-upload-abc123.jsonl", "pairs": PAIRS},
        "expect": {"truth": ["2012-05-30", "2012-05-30"]}}


def web(url, timeout):
    return (200, url, LIVEBLOG.encode(), "text/html") if "liveblog" in url else (404, url, b"", "text/html")


def entry(e, lat):
    return {"outcome": "override", "entry": {"statement_date": lat, **({"statement_date_earliest": e} if e != lat else {})}}


class Judge(unittest.TestCase):
    EX = {"truth": ["2021-02-02", "2021-02-28"], "accept_bound": ["2021-03-01", "2021-03-02"]}

    def test_the_truth_shape(self):
        j = E.judge_merge
        self.assertEqual(j(self.EX, entry("2021-02-02", "2021-02-28"))[0], "pass")
        self.assertEqual(j(self.EX, entry("2021-02-15", "2021-02-15"))[0], "pass")
        ok, why = j(self.EX, entry("2021-02-02", "2021-03-02"))
        self.assertEqual(ok, "pass")
        self.assertIn("accepted as a bound", why)
        # the publication day as a single day of speech is wrong, never a bound
        self.assertEqual(j(self.EX, entry("2021-03-02", "2021-03-02"))[0], "hard_fail")
        self.assertEqual(j(self.EX, entry("2021-02-02", "2021-12-01"))[0], "fail")
        self.assertEqual(j(self.EX, entry("2020-12-01", "2021-01-31"))[0], "hard_fail")
        self.assertEqual(j({"truth": ["2018-11-01", "2018-11-02"]}, entry("2018-11-01", "2018-11-30"))[0], "fail")
        self.assertEqual(j(self.EX, {"outcome": "queue", "reason": "x", "detail": "y"})[0], "queued")


class Pairs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)

    def test_estimate_counts_the_union_of_the_pairs(self):
        g = gold(self.root, [CASE])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertEqual(rc, 0, out)
        self.assertIn("1 model cases x 3 repeats: 12 calls (astra 3, fable 3, fable_web 3, gemini 3)", out)

    def test_each_repeat_calls_each_dater_once_and_judges_every_pair(self):
        g = gold(self.root, [CASE])
        calls = []

        def caller(h, prompt, timeout, workdir, args, idx):
            calls.append(h)
            obj = proposal() if h in ("gemini", "astra") else proposal(**CANNOT)
            return json.dumps(obj), {"served_model": MODELS[h], "web_searches": 2 if h == "fable_web" else None}, "x"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=caller, opener=web,
                      sleep=lambda s: None)
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, ["gemini", "fable", "fable_web", "astra"] * 3)
        for pair in ("gemini+fable", "gemini+fable_web", "gemini+astra"):
            self.assertIn(f"[PASS] P-dx[{pair}]  3 of 3 valid repeats pass", out)
        rec = json.loads((g / "recordings" / "P-dx" / "r00.fable_web.json").read_text())
        self.assertEqual(rec["telemetry"]["web_searches"], 2)
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] P-dx[gemini+astra]  3 of 3 valid repeats pass", out)

    def test_a_failure_excludes_the_repeat_only_for_the_pairs_holding_that_dater(self):
        g = gold(self.root, [CASE])
        seen = []

        def caller(h, prompt, timeout, workdir, args, idx):
            seen.append((h, idx))
            if h == "astra" and idx == 0:
                raise RuntimeError("cli_timeout: no answer")
            return json.dumps(proposal()), {"served_model": MODELS[h]}, "x"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=caller, opener=web,
                      sleep=lambda s: None)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] P-dx[gemini+fable]  3 of 3 valid repeats pass", out)
        self.assertIn("[PASS] P-dx[gemini+astra]  2 of 2 valid repeats pass; 1 infrastructure failure excluded "
                      "(cli_timeout 1)", out)
        failed = json.loads((g / "recordings" / "P-dx" / "failed" / "r00.astra.json").read_text())
        self.assertEqual(failed["label"], "cli_timeout")
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertIn("[PASS] P-dx[gemini+astra]  2 of 2 valid repeats pass; 1 infrastructure failure excluded", out)

    def test_when_gemini_fails_no_other_dater_is_called(self):
        g = gold(self.root, [{**CASE, "input": {**CASE["input"]}}])
        calls = []

        def caller(h, prompt, timeout, workdir, args, idx):
            calls.append(h)
            if h == "gemini":
                raise RuntimeError("empty_response: nothing")
            return json.dumps(proposal()), {"served_model": MODELS[h]}, "x"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live", "--repeats", "2"], LIVE, caller=caller,
                      opener=web, sleep=lambda s: None)
        self.assertEqual(calls, ["gemini", "gemini"])
        self.assertIn("[INCONCLUSIVE] P-dx[gemini+fable]  0 valid repeat(s)", out)
        skipped = json.loads((g / "recordings" / "P-dx" / "failed" / "r00.fable_web.json").read_text())
        self.assertEqual(skipped["label"], "skipped")

    def test_a_pair_naming_an_unknown_dater_is_refused_before_any_call(self):
        bad = copy.deepcopy(CASE)
        bad["input"]["pairs"] = [["gemini", "opus"]]
        g = gold(self.root, [bad])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertIn("opus", str(cm.exception))


class Stored(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)
        run_dir = self.data / "predictions" / "_experiments" / "dating-x"
        p = run_dir / "proposals" / "ada" / "re-upload-abc123.gemini.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"proposal": proposal(), "harness": "gemini", "daters": ["gemini"], "leads": []}))
        src = proposal()["sources"][0]
        checks = [E.DL.check_source(src, D10, {"status": 200, "final_url": src["url"], "body": LIVEBLOG.encode(),
                                               "via": "direct", "error": None})]
        c = run_dir / "source_checks" / "ada" / "re-upload-abc123.gemini.json"
        c.parent.mkdir(parents=True)
        c.write_text(json.dumps({"checks": checks}))
        sha = {x: hashlib.sha256(x.read_bytes()).hexdigest() for x in (p, c)}
        self.case = {"id": "S-dx", "stage": "dating_stored",
                     "input": {"transcript": "transcripts_open/ada/re-upload-abc123.json", "daters": ["gemini"],
                               "merge_version": "merge-4",
                               "proposals": {"gemini": {"path": str(p.relative_to(self.data)), "sha256": sha[p]}},
                               "checks": {"gemini": {"path": str(c.relative_to(self.data)), "sha256": sha[c]}}},
                     "expect": {"truth": ["2012-05-30", "2012-05-30"]}}

    def test_a_stored_proposal_and_its_checks_replay_through_the_merge(self):
        g = gold(self.root, [self.case])
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] S-dx  merge-4: confirmed (override) 2012-05-30..2012-05-30", out)
        self.assertIn("dating_stored (no model): {'PASS': 1}", out)

    def test_a_changed_file_is_refused_before_anything_runs(self):
        bad = copy.deepcopy(self.case)
        bad["input"]["proposals"]["gemini"]["sha256"] = "0" * 64
        g = gold(self.root, [bad])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data)])
        self.assertIn("sha256", str(cm.exception))

    def test_an_inline_control_that_must_queue_passes_as_negative(self):
        ctl = {"id": "C-embed-upload", "stage": "dating_stored",
               "input": {"transcript": "transcripts_open/ada/re-upload-abc123.json", "daters": ["gemini"],
                         "proposals": {"gemini": {"inline": proposal(sources=[])}}, "checks": {"gemini": None}},
               "expect": {"negative": True, "pass_within": ["2012-05-30", "2012-05-30"]}}
        g = gold(self.root, [ctl])
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertIn("[PASS] C-embed-upload", out)
        self.assertIn("queued: invalid_proposal", out)


if __name__ == "__main__":
    unittest.main()
