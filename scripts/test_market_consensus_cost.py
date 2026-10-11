#!/usr/bin/env python3
"""What market consensus spends on models, and a way to price a run before spending.

WHY THIS EXISTS. docs/plans/board-membership-2026-09-16.md called the stage
"public-API only, no model calls". It is not: every accepted record that finds a
candidate market goes to a model matcher, `--matcher auto` by default, and
counted from the records on 2026-10-11, 489 of 1115 accepted records carry a
`matcher` block, 405 served by Astra and 84 by Fable. No run summary recorded
that number, and the backlog's suggested measurement, "run it with the matcher
pinned off", had no switch to run it with.

What is asserted here, with fake market APIs and no model:

  OFF-ARG    `--matcher none` is accepted.
  OFF-COUNT  with the matcher off, a record that finds candidates is counted as
             one model call the run would make, and the matcher is never called.
  OFF-OTHER  records that end before the matcher are counted by how they end:
             no statement date, and a market API error, which also lands in the
             error taxonomy.
  OFF-WRITE  with the matcher off, the prediction file is byte-identical after.
  CALLS      the matcher counts each call it attempts, by harness; a router that
             refuses to pick made no call and is not counted.
  SUMMARY    the run summary carries `matcher_calls`, and a matcher-off run also
             carries `would_call_matcher`.

  .venv/bin/python scripts/test_market_consensus_cost.py
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import test_predictions_markets as TM  # noqa: E402  (fixtures only; its main() is guarded)

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def never_called(prompt: str):
    raise AssertionError("the matcher was called with the matcher off")


def fake_cache(M, root: Path, fetcher):
    wr = lambda p, t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t))  # noqa: E731
    return M.Cache(root, fetcher=fetcher, write=wr)


def failing_fetcher(url: str):
    return 500, "upstream down"


def write_predictions(L, root: Path, recs: list[dict]) -> Path:
    path = root / "ada" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(L.serialise_lines(recs))
    return path


def test_parser(M) -> None:
    print("\nOFF-ARG")
    try:
        a = M.build_parser().parse_args(["--matcher", "none"])
        ok, detail = a.matcher == "none", a.matcher
    except SystemExit as exc:
        ok, detail = False, f"argparse refused it (exit {exc.code})"
    check("--matcher none is accepted", ok, detail)


def test_matcher_off(M, L) -> None:
    print("\nOFF-COUNT / OFF-OTHER / OFF-WRITE")
    tmp = Path(tempfile.mkdtemp())
    good = TM.make_record(L)
    undated = copy.deepcopy(good)
    undated["prediction_id"] = "f" * 16
    undated["source"]["statement_date"] = None
    undated["source"]["statement_date_basis"] = "unknown"
    path = write_predictions(L, tmp / "preds", [good, undated])
    before = path.read_bytes()
    args = SimpleNamespace(force=False, dry_run=False, matcher="none")
    job = {"args": args, "path": str(path), "cache": fake_cache(M, tmp / "cache", TM.fake_fetcher([])),
           "matcher": never_called, "contract": None, "run_id": "r", "kalshi": None}
    try:
        res = M.process_file(job)
    except AssertionError as exc:
        check("with the matcher off, no model call is made", False, str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        check("with the matcher off, process_file runs", False, f"{type(exc).__name__}: {exc}")
        return
    off = res.get("matcher_off") or {}
    check("a record with candidate markets counts as one call the run would make",
          off.get("would_call_matcher") == 1, json.dumps(res)[:400])
    check("a record with no statement date is counted by how it ended",
          off.get("unavailable/no_statement_date") == 1, json.dumps(off))
    check("the prediction file is byte-identical afterwards", path.read_bytes() == before)

    path2 = write_predictions(L, tmp / "preds2", [copy.deepcopy(good)])
    job2 = {**job, "path": str(path2), "cache": fake_cache(M, tmp / "cache2", failing_fetcher)}
    res2 = M.process_file(job2)
    off2 = res2.get("matcher_off") or {}
    check("a market API error is counted, not called", off2.get("failed/market_error") == 1, json.dumps(res2)[:400])
    check("and it lands in the error taxonomy", len(res2.get("errors") or []) == 1, json.dumps(res2)[:400])


class StubRouter:
    def __init__(self, refuse: bool = False):
        self.refuse = refuse

    def pick(self, harness, _):
        if self.refuse:
            raise RuntimeError("router_no_account: nothing has headroom")
        return {"harness": "astra", "account_id": "codex"}


def test_call_count(M, L) -> None:
    print("\nCALLS")
    saved = M.call_harness
    M.call_harness = lambda route, prompt, timeout, wd, args: ("{}", {"requested_model": "g"}, "codex")
    try:
        args = SimpleNamespace(matcher="auto", timeout=1)
        m = M.make_matcher(StubRouter(), args, "run", Path(tempfile.mkdtemp()))
        m("p1")
        m("p2")
        calls = getattr(m, "calls", None)
        check("two calls through the matcher are counted, by harness",
              calls == {"attempted": 2, "by_harness": {"astra": 2}}, repr(calls))
        r = M.make_matcher(StubRouter(refuse=True), args, "run", Path(tempfile.mkdtemp()))
        try:
            r("p")
        except RuntimeError:
            pass
        check("a pick the router refused made no call and is not counted",
              getattr(r, "calls", None) == {"attempted": 0, "by_harness": {}}, repr(getattr(r, "calls", None)))
    finally:
        M.call_harness = saved


def test_summary(M, L) -> None:
    print("\nSUMMARY")
    tmp = Path(tempfile.mkdtemp())
    preds = tmp / "predictions"
    path = write_predictions(L, preds, [TM.make_record(L)])
    before = path.read_bytes()
    real_cache = M.Cache
    fetch = TM.fake_fetcher([])

    class OfflineCache(real_cache):
        def __init__(self, root, refresh=False):
            super().__init__(root, fetcher=fetch, refresh=refresh)

    M.Cache = OfflineCache
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = M.main(["--predictions", str(preds), "--matcher", "none", "--workers", "1"])
    except Exception as exc:  # noqa: BLE001
        check("a matcher-off run completes", False, f"{type(exc).__name__}: {exc}")
        return
    finally:
        M.Cache = real_cache
    lines = [l for l in out.getvalue().splitlines() if l.startswith("{")]
    summary = json.loads(lines[-1]) if lines else {}
    check("a matcher-off run exits 0", rc == 0, f"rc {rc}")
    check("its summary says how many model calls a real run would make",
          summary.get("would_call_matcher") == 1, json.dumps(summary)[:400])
    check("and that this run made none",
          summary.get("matcher_calls") == {"attempted": 0, "by_harness": {}}, json.dumps(summary)[:400])
    check("and it changed no record", path.read_bytes() == before)
    runs = list((preds / "_runs").glob("*-consensus-*.json"))
    check("the run summary is written beside the other runs", len(runs) == 1, str(runs))


def main() -> int:
    print("market consensus: model cost")
    L = TM.load("predictions_lib")
    M = TM.load("market_consensus")
    test_parser(M)
    test_matcher_off(M, L)
    test_call_count(M, L)
    test_summary(M, L)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
