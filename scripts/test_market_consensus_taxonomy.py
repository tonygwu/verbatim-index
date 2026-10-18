#!/usr/bin/env python3
"""The consensus run summary names a market API error as what it is (VI-30, 2026-10-18).

Every 2026-10-18 consensus manifest read `error_taxonomy: {"cli_nonzero_exit": N}` for failures
that were a Kalshi 429 or a Polymarket 400 or 403, because `classify_exception_detail` matched the
detail against `ALL_ERROR_TYPES`, which did not name `market_api_error`. A matcher failure keeps
the label it came with at the front (schema_validation_failed, router_no_account); one whose
message carries no label, such as a bare JSONDecodeError, now gets `matcher_error: ` in front.
"""
from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import market_consensus as M  # noqa: E402
import predictions_lib as L  # noqa: E402
import test_predictions_markets as TM  # noqa: E402  (fixtures only; its main() is guarded)


def cache(root: Path, fetcher) -> M.Cache:
    return M.Cache(root, fetcher=fetcher, write=lambda p, t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t)))


def run_one(matcher, fetcher) -> dict:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "ada" / "s1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(L.serialise_lines([TM.make_record(L)]))
    job = {"args": SimpleNamespace(force=False, dry_run=False, matcher="fable"), "path": str(path),
           "cache": cache(tmp / "cache", fetcher), "matcher": matcher, "contract": TM.contract_for(M, L),
           "run_id": "r", "kalshi": None}
    return M.process_file(job)


def never_called(prompt: str):
    raise AssertionError("the matcher was reached")


class Taxonomy(unittest.TestCase):
    def test_a_market_http_error_classifies_as_market_api_error(self):
        self.assertIn(M.E_MARKET_HTTP, L.ALL_ERROR_TYPES)
        self.assertEqual(L.classify_exception_detail("market_api_error: HTTP 429 for https://x"), "market_api_error")
        self.assertEqual(L.classify_exception_detail("market_api_error: cached 400 for https://x"), "market_api_error")

    def test_a_labelled_matcher_error_keeps_its_label(self):
        self.assertIn(M.E_MATCHER, L.ALL_ERROR_TYPES)
        self.assertEqual(L.classify_exception_detail("matcher_error: ValueError: boom"), "matcher_error")
        self.assertEqual(L.classify_exception_detail("schema_validation_failed: missing x"), "schema_validation_failed")
        self.assertEqual(L.classify_exception_detail("router_no_account: none"), "router_no_account")

    def test_a_429_from_the_market_files_under_market_api_error(self):
        res = run_one(never_called, lambda url: (429, '{"error":"too_many_requests"}'))
        self.assertEqual([e["error_type"] for e in res["errors"]], ["market_api_error"], res)
        self.assertTrue(res["errors"][0]["detail"].startswith("market_api_error: HTTP 429"), res["errors"])

    def test_a_bare_matcher_exception_files_under_matcher_error(self):
        def matcher(prompt: str):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        res = run_one(matcher, TM.fake_fetcher([]))
        self.assertEqual([e["error_type"] for e in res["errors"]], ["matcher_error"], res)
        self.assertIn("Expecting value", res["errors"][0]["detail"])

    def test_a_labelled_matcher_exception_keeps_its_label_in_the_summary(self):
        def matcher(prompt: str):
            raise RuntimeError(f"{L.E_SCHEMA}: missing prediction_id")
        res = run_one(matcher, TM.fake_fetcher([]))
        self.assertEqual([e["error_type"] for e in res["errors"]], [L.E_SCHEMA], res)

    def test_the_labels_are_defined_once(self):
        # `assertIs` would pass on two equal literals (CPython interns identifier-like strings),
        # so read the source: market_consensus must alias the lib's names, not spell its own.
        src = inspect.getsource(M)
        self.assertIn("E_MARKET_HTTP = L.E_MARKET_HTTP", src)
        self.assertIn("E_MATCHER = L.E_MATCHER", src)
        self.assertNotIn('E_MARKET_HTTP = "market_api_error"', src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
