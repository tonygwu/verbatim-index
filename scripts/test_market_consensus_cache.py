#!/usr/bin/env python3
"""The market HTTP cache keeps answers, not outages (VI-24, 2026-10-18).

FOUND on the thin-supplement consensus run of 2026-10-18 (4 workers, 707 HTTP calls): 14 of the
126 records failed on Kalshi `too_many_requests`, 8 of them replayed from the cache within the
same run (one `series_ticker=ECLIPSECOVER` URL, cached minutes earlier), because `Cache.get_json`
wrote every response whatever its status and raised `market_api_error: cached 429` on every later
read. `--refresh-cache` was the only way out, and it re-fetches every URL. The operator deleted the
cached 429/403 files by hand and re-ran with one worker.

Now a transient status (429, 403, any 5xx) is never written to the cache, a cached transient
status left by an older run counts as a miss and is fetched again, and the Kalshi fetches run
one at a time whatever `--workers` says, because Kalshi is the host that rate-limits. A 4xx
request error such as 400 or 404 stays cached, as before: it is the request that is wrong, and
repeating it would be a wasted call.

Synthetic fetchers only, no network.
  .venv/bin/python scripts/test_market_consensus_cache.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_consensus as M  # noqa: E402

URL = "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=ECLIPSECOVER&limit=100"


def writer(p: Path, t: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t)


def scripted(answers: list[tuple[int, str]], calls: list[str]):
    """A fetcher that pops the next (status, body) and records every URL it was asked."""
    def fetch(url: str) -> tuple[int, str]:
        calls.append(url)
        return answers.pop(0)
    return fetch


def cache_path(root: Path, platform: str, url: str) -> Path:
    return root / platform / (hashlib.sha256(url.encode()).hexdigest() + ".json")


class TransientNotCached(unittest.TestCase):
    def test_a_429_is_raised_but_not_written_and_the_next_read_fetches_again(self):
        root = Path(tempfile.mkdtemp())
        calls: list[str] = []
        cache = M.Cache(root, fetcher=scripted([(429, '{"error":"too_many_requests"}'), (200, '{"markets": []}')], calls),
                        write=writer)
        with self.assertRaises(RuntimeError) as cm:
            cache.get_json("kalshi", URL)
        self.assertIn(M.E_MARKET_HTTP, str(cm.exception))
        self.assertIn("HTTP 429", str(cm.exception))
        self.assertFalse(cache_path(root, "kalshi", URL).exists(), "a rate limit is not an answer; it must not be cached")
        self.assertEqual(cache.get_json("kalshi", URL), {"markets": []})
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(cache_path(root, "kalshi", URL).read_text())["status"], 200)
        self.assertEqual((cache.calls, cache.hits), (2, 0))

    def test_403_and_5xx_are_transient_too(self):
        for status in (403, 500, 502, 503, 504):
            with self.subTest(status=status):
                root = Path(tempfile.mkdtemp())
                cache = M.Cache(root, fetcher=scripted([(status, "<html>blocked</html>"), (200, "[]")], []), write=writer)
                with self.assertRaises(RuntimeError):
                    cache.get_json("polymarket", URL)
                self.assertFalse(cache_path(root, "polymarket", URL).exists())
                self.assertEqual(cache.get_json("polymarket", URL), [])

    def test_a_cached_transient_status_from_an_older_run_is_a_miss(self):
        """The 2026-10-18 cache held 6 x 429 and 2 x 403 files; a rerun fetches them again, no hand edit."""
        root = Path(tempfile.mkdtemp())
        p = cache_path(root, "kalshi", URL)
        writer(p, json.dumps({"url": URL, "fetched_at_utc": "2026-10-18T09:02:16Z", "status": 429, "body": "{}"}))
        calls: list[str] = []
        cache = M.Cache(root, fetcher=scripted([(200, '{"markets": [1]}')], calls), write=writer)
        self.assertEqual(cache.get_json("kalshi", URL), {"markets": [1]})
        self.assertEqual(calls, [URL])
        self.assertEqual(json.loads(p.read_text())["status"], 200)
        self.assertEqual((cache.calls, cache.hits), (1, 0))

    def test_a_request_error_stays_cached_and_is_replayed(self):
        """A 400 ('interval is too long', VI-25) is the request's fault; repeating it is a wasted call."""
        root = Path(tempfile.mkdtemp())
        calls: list[str] = []
        cache = M.Cache(root, fetcher=scripted([(400, '{"error":"invalid filters"}')], calls), write=writer)
        with self.assertRaises(RuntimeError):
            cache.get_json("polymarket", URL)
        self.assertEqual(json.loads(cache_path(root, "polymarket", URL).read_text())["status"], 400)
        with self.assertRaises(RuntimeError) as cm:
            cache.get_json("polymarket", URL)
        self.assertIn("cached 400", str(cm.exception))
        self.assertEqual(len(calls), 1)
        self.assertEqual((cache.calls, cache.hits), (1, 1))

    def test_a_200_is_cached_and_replayed_as_before(self):
        root = Path(tempfile.mkdtemp())
        calls: list[str] = []
        cache = M.Cache(root, fetcher=scripted([(200, '{"a": 1}')], calls), write=writer)
        self.assertEqual(cache.get_json("kalshi", URL), {"a": 1})
        self.assertEqual(cache.get_json("kalshi", URL), {"a": 1})
        self.assertEqual((len(calls), cache.calls, cache.hits), (1, 1, 1))

    def test_refresh_still_refetches_everything(self):
        root = Path(tempfile.mkdtemp())
        writer(cache_path(root, "kalshi", URL), json.dumps({"url": URL, "fetched_at_utc": "x", "status": 200, "body": "[0]"}))
        cache = M.Cache(root, fetcher=scripted([(200, "[1]")], []), refresh=True, write=writer)
        self.assertEqual(cache.get_json("kalshi", URL), [1])


class KalshiOneAtATime(unittest.TestCase):
    def _max_in_flight(self, platform: str) -> int:
        root = Path(tempfile.mkdtemp())
        lock, state = threading.Lock(), {"now": 0, "max": 0}

        def fetch(url: str) -> tuple[int, str]:
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return 200, "[]"

        cache = M.Cache(root, fetcher=fetch, write=writer)
        urls = [f"{URL}&page={i}" for i in range(6)]
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lambda u: cache.get_json(platform, u), urls))
        return state["max"]

    def test_kalshi_fetches_are_serialized_whatever_the_worker_count(self):
        self.assertEqual(self._max_in_flight("kalshi"), 1)

    def test_polymarket_fetches_still_run_in_parallel(self):
        self.assertGreater(self._max_in_flight("polymarket"), 1)


class Docstring(unittest.TestCase):
    def test_the_module_no_longer_promises_that_every_response_is_cached(self):
        self.assertNotIn("Every HTTP response is\ncached", M.__doc__)
        self.assertIn("transient", M.__doc__.lower())


if __name__ == "__main__":
    unittest.main(verbosity=1)
