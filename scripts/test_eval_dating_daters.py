#!/usr/bin/env python3
"""The case harness runs a dating case with both daters (operator decision VD-11, 2026-10-01).

Production dates each recording with a Gemini and a Fable proposal and merges
them, so a dating case is judged the same way: one --live repeat makes one call
per dater, both answers are recorded and checked, and the real merge reads both.
Synthetic data root and fake models only, no quota, no network:

  ESTIMATE  --estimate counts one call per dater per dating repeat, by harness
  LIVE      each repeat calls gemini then fable once and records both; an
            infrastructure failure of either dater excludes the whole repeat,
            because the merge needs both
  REPLAY    a repeat replays only with every dater's recording, each from its own
            harness and model under its own prompt's sha256; agreement of the two
            recorded answers confirms as the merge does
  GOLD      a dating case whose legacy "harness" names no dater is refused before
            any call

  .venv/bin/python scripts/test_eval_dating_daters.py
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
from test_eval_prediction_cases import DATING, RESOLVE, gold, make_data, run  # noqa: E402

LIVE = {"PREDICT_LIVE": "1"}
MODELS = {"gemini": "gemini-3.8-flash-high", "fable": "claude-fable-5-1", "astra": "gpt-6-astra"}
CANNOT = dict(verdict="cannot_date", e=None, l=None, sources=[], event=None, event_kind=None)
GONE = {"url": "https://gone.example.com/ada", "publisher": "x", "date_on_source": None,
        "verbatim_excerpt": "Ada at DX on May 30, 2012 in full", "kind": "secondary"}


def web(url, timeout):
    return (200, url, LIVEBLOG.encode(), "text/html") if "liveblog" in url else (404, url, b"", "text/html")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root)

    def record(self, g, case, n, harness, obj, served=None, sha=None):
        d = g / "recordings" / case["id"]
        d.mkdir(parents=True, exist_ok=True)
        prompt = E.build_prompt(case, E.Context(self.data, g), harness)
        checks = [E.DL.check_source(s, D10, dict(zip(("status", "final_url", "body", "content_type"), web(s["url"], 1)),
                                                 via="direct", error=None if "liveblog" in s["url"] else "HTTP 404"))
                  for s in obj["sources"]]
        (d / f"r{n:02d}.{harness}.json").write_text(json.dumps({
            "prompt_sha256": sha or hashlib.sha256(prompt.encode()).hexdigest(), "response_text": json.dumps(obj),
            "harness": harness, "served_model": served or MODELS[harness], "requested_model": MODELS[harness],
            "telemetry": {}, "source_checks": checks}))


class Estimate(Base):
    def test_one_call_per_dater_per_dating_repeat(self):
        g = gold(self.root, [RESOLVE, DATING])
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertEqual(rc, 0, out)
        self.assertIn("live run: 2 model cases x 3 repeats: 9 calls (astra 3, fable 3, gemini 3)", out)
        self.assertIn("a dating repeat calls each of its daters once (gemini, fable)", out)


class Live(Base):
    def test_each_repeat_calls_both_daters_and_records_both(self):
        g = gold(self.root, [DATING])
        calls = []

        def caller(harness, prompt, timeout, workdir, args, idx):
            calls.append(harness)
            obj = proposal() if harness == "gemini" else proposal(**CANNOT)
            return json.dumps(obj), {"served_model": MODELS[harness]}, "x"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=caller, opener=web,
                      sleep=lambda s: None)
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, ["gemini", "fable"] * 3)
        self.assertIn("[PASS] D-dx (3 of 3 valid repeats pass", out)
        names = sorted(p.name for p in (g / "recordings" / "D-dx").glob("*.json"))
        self.assertEqual(names, [f"r{n:02d}.{h}.json" for n in range(3) for h in ("fable", "gemini")])
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx (3 of 3 valid repeats pass", out)

    def test_an_infrastructure_failure_of_either_dater_excludes_the_repeat(self):
        g = gold(self.root, [DATING])
        seen = []

        def caller(harness, prompt, timeout, workdir, args, idx):
            seen.append(harness)
            if harness == "fable" and seen.count("fable") == 1:
                raise RuntimeError("cli_timeout: no answer")
            return json.dumps(proposal()), {"served_model": MODELS[harness]}, "x"
        rc, out = run(["--gold", str(g), "--data", str(self.data), "--live"], LIVE, caller=caller, opener=web,
                      sleep=lambda s: None)
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx (2 of 2 valid repeats pass; 1 infrastructure failure excluded (cli_timeout 1)", out)
        self.assertEqual(len(list((g / "recordings" / "D-dx").glob("r*.json"))), 4)
        self.assertEqual(len(list((g / "recordings" / "D-dx" / "partial").glob("*.json"))), 1)


class Replay(Base):
    def test_a_repeat_without_every_daters_recording_is_refused(self):
        g = gold(self.root, [DATING])
        for n in range(2):
            self.record(g, DATING, n, "gemini", proposal())
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("[RECORDING_REFUSED] D-dx", out)
        self.assertIn("fable", out)

    def test_a_daters_recording_from_another_model_is_refused(self):
        g = gold(self.root, [DATING])
        for n in range(2):
            self.record(g, DATING, n, "gemini", proposal())
            self.record(g, DATING, n, "fable", proposal(**CANNOT), served="gemini-3.8-flash-high")
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("[RECORDING_REFUSED] D-dx", out)

    def test_each_daters_prompt_is_checked_against_its_own_sha(self):
        g = gold(self.root, [DATING])
        for n in range(2):
            self.record(g, DATING, n, "gemini", proposal())
            self.record(g, DATING, n, "fable", proposal(**CANNOT),
                        sha=hashlib.sha256(E.build_prompt(DATING, E.Context(self.data, g), "gemini").encode()).hexdigest())
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 1, out)
        self.assertIn("prompt changed; re-record live", out)

    def test_two_daters_naming_the_same_day_confirm_by_agreement(self):
        g = gold(self.root, [DATING])
        for n in range(2):
            for h in ("gemini", "fable"):
                self.record(g, DATING, n, h, proposal(sources=[GONE]))
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx (2 of 2 valid repeats pass", out)


class InvalidAnswer(Base):
    """Review fix 5, as production merges it: a dater's invalid answer is an invalid proposal, so the other
    dater's confirmation stands; the repeat is judged on the merge, never failed for the answer alone."""

    def test_an_unparseable_fable_answer_leaves_geminis_confirmation_standing(self):
        g = gold(self.root, [DATING])
        d = g / "recordings" / DATING["id"]
        for n in range(2):
            self.record(g, DATING, n, "gemini", proposal())
            self.record(g, DATING, n, "fable", proposal(**CANNOT))
            f = d / f"r{n:02d}.fable.json"
            f.write_text(json.dumps({**json.loads(f.read_text()), "response_text": "I could not find it."}))
        rc, out = run(["--gold", str(g), "--data", str(self.data)])
        self.assertEqual(rc, 0, out)
        self.assertIn("[PASS] D-dx (2 of 2 valid repeats pass", out)


class Gold(Base):
    def test_a_dating_case_naming_a_harness_that_is_not_a_dater_is_refused(self):
        bad = copy.deepcopy(DATING)
        bad["input"]["harness"] = "astra"
        g = gold(self.root, [bad])
        with self.assertRaises(SystemExit) as cm:
            run(["--gold", str(g), "--data", str(self.data), "--estimate"])
        self.assertIn("astra", str(cm.exception))
        self.assertIn("daters", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
