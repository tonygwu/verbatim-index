#!/usr/bin/env python3
"""credit_run.py spends API credit only as asked, and refuses an answer served any other way.

  ARGV      the call is `quotapick run --only <pools>`, one attempt per named pool up to
            quotapick's three, the request on stdin
  OK        a response served as asked returns its text and names harness and pool
  REFUSE    a wrong model, a second model in models_seen, another effort, a subscription,
            OAuth, a pool outside the named set, run_contract 2, a non-ok outcome,
            exit 2 and any other non-zero exit are each refused with their label
  DONE      no_candidate, and exhausted once every named pool was tried, raise
            PoolsExhausted; exhausted with a pool left untried is a plain failure
  SPENT     a billed failure still reports its cost; a call retried on a second pool
            reports both attempts, not only the last (quotapick's own cost_usd); a
            timeout names none and reports none
  WHY       a failure's message carries each attempt, the router's reason and its warnings
  RAW       the full response is written to disk before any check runs
  LIMITS    a timeout over 1800 s, a comma inside one pool name and a repeated pool name are refused before any call
  TRUNCATED an answer whose earlier turn hit the output cap (usage.output_tokens minus the
            usage.iterations it kept is at least the cap) is refused as continuation_truncated,
            after its cost is reported; a gap below the cap, a prose answer and a usage with no
            iterations pass (VI-23)
  CAP       quotapick, and so its `claude -p` child, gets CLAUDE_CODE_MAX_OUTPUT_TOKENS set to
            Fable's maximum, over any value the caller's environment holds

No quota: a fake quotapick binary prints a canned response.

  .venv/bin/python scripts/test_credit_run.py
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


MODEL = "claude-fable-5-1"
POOLS = ["anthropic_api_e", "anthropic_api_b"]


def good(**over) -> dict:
    served = {"account": "anthropic_api_e", "provider": "anthropic_api", "pool_kind": "credit", "model": MODEL,
              "model_requested": MODEL, "models_seen": [MODEL], "effort": "max", "auth": "api_key"}
    resp = {"run_contract": 1, "ok": True, "outcome": "ok", "text": "ANSWER", "served": served,
            "usage": {"input_tokens": 10, "output_tokens": 900, "output_tokens_details": {"thinking_tokens": 700}},
            "cost_usd": 1.25,
            "attempts": [{"account": "anthropic_api_e", "outcome": "ok", "duration_ms": 4000, "cost_usd": 1.25}],
            "request_id": "rid"}
    for k, v in over.items():
        if k.startswith("served_"):
            served[k[len("served_"):]] = v
        else:
            resp[k] = v
    return resp


def fake_binary(tmp: Path, resp: dict | None, exit_code: int = 0) -> Path:
    """A quotapick stand-in: records argv and stdin, prints `resp`, exits `exit_code`."""
    (tmp / "resp.json").write_text(json.dumps(resp) if resp is not None else "")
    b = tmp / "quotapick"
    b.write_text("#!/bin/sh\n"
                 f"printf '%s\\n' \"$@\" > '{tmp}/argv'\n"
                 f"printf '%s' \"${{CLAUDE_CODE_MAX_OUTPUT_TOKENS-UNSET}}\" > '{tmp}/cap_env'\n"
                 f"cat > '{tmp}/stdin'\n"
                 f"cat '{tmp}/resp.json'\n"
                 f"[ {exit_code} -eq 2 ] && echo 'refused: bad request' >&2\n"
                 f"exit {exit_code}\n")
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    return b


def call(tmp: Path, resp: dict | None, exit_code: int = 0, spent=None, raw: Path | None = None):
    import credit_run as C
    return C.run("PROMPT", model=MODEL, effort="max", pools=POOLS, timeout_s=1800, expected_cost_usd=3,
                 request_id="rid", raw_path=raw, spent=spent, binary=str(fake_binary(tmp, resp, exit_code)))


def raises(tmp: Path, resp: dict | None, exc_name: str, label: str, exit_code: int = 0) -> tuple[bool, str]:
    try:
        call(tmp, resp, exit_code)
    except Exception as exc:  # noqa: BLE001 -- the test inspects the type and label
        return type(exc).__name__ == exc_name and str(exc).startswith(label), f"{type(exc).__name__}: {exc}"
    return False, "returned normally"


def main() -> int:
    print("credit_run")
    import credit_run as C

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        print("\n[ARGV]")
        raw = tmp / "raw" / "one.json"
        text, tel = call(tmp, good(), raw=raw)
        argv = (tmp / "argv").read_text().split("\n")[:-1]
        req = json.loads((tmp / "stdin").read_text())
        check("argv is `run --only <pools joined by commas>`", argv == ["run", "--only", ",".join(POOLS)], str(argv))
        check("one attempt per named pool, the asked model and effort, timeout and expected cost in the request",
              req["max_attempts"] == 2 and req["model"] == MODEL and req["effort"] == "max"
              and req["timeout_s"] == 1800 and req["expected_cost_usd"] == 3 and req["prompt"] == "PROMPT", str(req))
        caps = [C.request_for("P", model=MODEL, effort="max", timeout_s=60, expected_cost_usd=1, request_id="r",
                              pools=[f"p{i}" for i in range(n)])["max_attempts"] for n in (1, 3, 5)]
        check("one pool gets one attempt, and five get quotapick's ceiling of three", caps == [1, 3, 3], str(caps))

        print("\n[OK]")
        check("the answer text comes back", text == "ANSWER")
        check("telemetry names the harness, the pool, the cost and the thinking tokens",
              tel["harness"] == "quotapick run" and tel["credit_pool"] == "anthropic_api_e"
              and tel["cost_usd"] == 1.25 and tel["thinking_tokens"] == 700, str(tel))
        check("a pool from the named set other than the first is accepted",
              call(tmp, good(served_account="anthropic_api_b"))[1]["credit_pool"] == "anthropic_api_b")

        print("\n[RAW]")
        stored = json.loads(raw.read_text())
        check("the full response is stored with its exit code", stored["returncode"] == 0
              and json.loads(stored["stdout"])["text"] == "ANSWER", str(stored)[:200])
        bad_raw = tmp / "raw" / "bad.json"
        try:
            call(tmp, good(served_model="claude-opus-5"), raw=bad_raw)
        except C.CreditRunError:
            pass
        check("a refused answer is stored too", bad_raw.exists() and "claude-opus-5" in bad_raw.read_text())

        print("\n[REFUSE]")
        for label, resp, exc, prefix, code in (
                ("a different served model", good(served_model="claude-opus-5", served_models_seen=["claude-opus-5"]),
                 "CreditRunError", "model_mismatch", 0),
                ("a second model in models_seen", good(served_models_seen=[MODEL, "claude-haiku-5-5"]),
                 "CreditRunError", "model_mismatch", 0),
                ("empty models_seen", good(served_models_seen=[]), "CreditRunError", "model_mismatch", 0),
                ("another effort", good(served_effort="high"), "CreditRunError", "not_served_as_asked", 0),
                ("a subscription", good(served_pool_kind="subscription"), "CreditRunError", "not_served_as_asked", 0),
                ("OAuth", good(served_auth="oauth"), "CreditRunError", "not_served_as_asked", 0),
                ("a pool outside the named set", good(served_account="anthropic_api_d"),
                 "CreditRunError", "not_served_as_asked", 0),
                ("run_contract 2", good(run_contract=2), "CreditRunError", "run_contract", 0),
                ("a timeout outcome", good(ok=False, outcome="timeout"), "CreditRunError", "outcome_timeout", 0),
                ("ok true with a non-ok outcome", good(outcome="wrong_model"), "CreditRunError", "outcome_wrong_model", 0),
                ("exit 2", None, "CreditRunError", "refused", 2),
                ("exit 1", good(), "CreditRunError", "cli_exit_1", 1)):
            ok, detail = raises(tmp, resp, exc, prefix, code)
            check(f"{label} is refused as {prefix}", ok, detail)

        print("\n[DONE]")
        both = [{"account": p, "outcome": "exhausted"} for p in POOLS]
        ok, detail = raises(tmp, good(ok=False, outcome="exhausted", cost_usd=0, attempts=both),
                            "PoolsExhausted", "exhausted")
        check("exhausted after every named pool was tried raises PoolsExhausted", ok, detail)
        ok, detail = raises(tmp, good(ok=False, outcome="no_candidate", cost_usd=0, attempts=[]),
                            "PoolsExhausted", "no_candidate")
        check("no_candidate raises PoolsExhausted", ok, detail)
        ok, detail = raises(tmp, good(ok=False, outcome="exhausted", cost_usd=0, attempts=both[:1]),
                            "CreditRunError", "outcome_exhausted")
        check("exhausted with a named pool left untried is a plain failure, not the end of the pools", ok, detail)

        print("\n[SPENT]")
        seen = []
        try:
            call(tmp, good(ok=False, outcome="wrong_model", cost_usd=4.5,
                           attempts=[{"account": "anthropic_api_e", "outcome": "wrong_model", "cost_usd": 4.5}]),
                 spent=seen.append)
        except C.CreditRunError:
            pass
        check("a billed failure still reports its cost", seen == [4.5], str(seen))
        seen = []
        try:
            call(tmp, good(ok=False, outcome="timeout", cost_usd=None,
                           attempts=[{"account": "anthropic_api_e", "outcome": "timeout", "cost_usd": None}]),
                 spent=seen.append)
        except C.CreditRunError:
            pass
        check("a timeout names no cost and reports none", seen == [], str(seen))
        seen = []
        tel = call(tmp, good(cost_usd=1.2, attempts=[
            {"account": "anthropic_api_e", "outcome": "transient", "duration_ms": 900, "cost_usd": 1.0},
            {"account": "anthropic_api_b", "outcome": "ok", "duration_ms": 4000, "cost_usd": 1.2}],
            served_account="anthropic_api_b"), spent=seen.append)[1]
        check("a call retried on a second pool reports both attempts' cost, not only the last",
              seen == [2.2] and tel["cost_usd"] == 2.2 and tel["cost_usd_final_attempt"] == 1.2, f"{seen} {tel}")
        tel = call(tmp, good(attempts=[{"account": "anthropic_api_e", "outcome": "transient", "duration_ms": 4000,
                                        "cost_usd": 0.1},
                                       {"account": "anthropic_api_e", "outcome": "ok", "cost_usd": 1.25}]))[1]
        check("duration_ms is None, not a partial sum, when an attempt gives no duration",
              tel["duration_ms"] is None and tel["attempts"] == 2, str(tel))

        print("\n[WHY]")
        ok, detail = raises(tmp, good(ok=False, outcome="transient", cost_usd=0.2,
                                      attempts=[{"account": "anthropic_api_e", "outcome": "transient",
                                                 "detail": "overloaded_error", "cost_usd": 0.2}],
                                      decision={"reason": "anthropic_api_e wins"}, warnings=["pool b unpriced"]),
                            "CreditRunError", "outcome_transient")
        check("the message names the attempt, its detail, the router's reason and the warnings",
              ok and all(x in detail for x in ("anthropic_api_e: transient overloaded_error",
                                               "router: anthropic_api_e wins", "warnings: pool b unpriced",
                                               "billed_usd 0.2")), detail)

        print("\n[LIMITS]")
        for label, kwargs in (("a timeout over 1800 s", {"timeout_s": 1801}),
                              ("a comma inside one pool name", {"pools": ["anthropic_api_e,anthropic_api_d"]}),
                              ("a repeated pool name", {"pools": ["anthropic_api_e", "anthropic_api_e"]}),
                              ("no pools", {"pools": []})):
            os.utime(tmp / "argv", ns=(0, 0))
            args = {"model": MODEL, "effort": "max", "pools": POOLS, "timeout_s": 1800, "expected_cost_usd": 3,
                    "request_id": "rid", "binary": str(tmp / "quotapick")} | kwargs
            try:
                C.run("PROMPT", **args)
                refused = False
            except ValueError:
                refused = True
            called = (tmp / "argv").stat().st_mtime_ns != 0
            check(f"{label} is refused before any call", refused and not called, f"refused={refused} called={called}")

        print("\n[TRUNCATED]")
        # The shape of data predictions/_raw/responses/pat-gelsinger/web-fool-com-335b172e__extract__
        # 20261018T053831Z-both-499ae6b1.json: the text starts mid-string, and output_tokens (64,247)
        # minus the one iteration kept (247) is exactly the 64,000-token turn cap.
        fragment = 'in the span.","resolution_criteria":"By 2023-12-31, the price premium"}]}'

        def cut(total, kept, text=fragment, cost=4.81):
            return good(text=text, cost_usd=cost,
                        usage={"input_tokens": 8, "output_tokens": total,
                               "output_tokens_details": {"thinking_tokens": 53449},
                               "iterations": [{"type": "message", "output_tokens": n} for n in kept]},
                        attempts=[{"account": "anthropic_api_e", "outcome": "ok", "duration_ms": 705472,
                                   "cost_usd": cost}])

        seen = []
        cut_raw = tmp / "raw" / "cut.json"
        try:
            call(tmp, cut(64247, [247]), spent=seen.append, raw=cut_raw)
            got = "returned normally"
        except Exception as exc:  # noqa: BLE001 -- the test inspects the type and label
            got = f"{type(exc).__name__}: {exc}"
        check("an answer whose first turn hit the 64,000 cap is refused as continuation_truncated",
              got.startswith("CreditRunError: continuation_truncated"), got)
        check("the message names the gap and the cap", "64000" in got and "247" in got, got)
        check("its cost still reaches spent", seen == [4.81], str(seen))
        check("its raw response is stored", cut_raw.exists() and "resolution_criteria" in cut_raw.read_text())
        ok, detail = raises(tmp, cut(128_000 + 900, [900]), "CreditRunError", "continuation_truncated")
        check("two capped turns (a gap of 128,000) are refused too", ok, detail)
        for label, resp in (("a single turn whose iterations sum to output_tokens",
                             cut(64_000, [64_000], text='{"candidates": []}')),
                            ("a gap below the cap (an earlier turn that did not hit it)",
                             cut(9_000 + 63_999, [9_000], text='{"candidates": []}')),
                            ("a prose answer that does not start with {",
                             cut(900, [900], text="The answer is no.")),
                            ("a usage with no iterations, as before", good())):
            try:
                text = call(tmp, resp)[0]
                passed = text == resp["text"]
            except Exception as exc:  # noqa: BLE001
                passed, text = False, f"{type(exc).__name__}: {exc}"
            check(f"{label} passes", passed, text)

        print("\n[CAP]")
        os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "1000"
        try:
            call(tmp, good())
        finally:
            del os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]
        cap_env = (tmp / "cap_env").read_text()
        check("quotapick gets CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 over the caller's own 1000",
              cap_env == "128000", cap_env)
        check("the cap is one named constant, Fable's maximum output of 128,000 tokens",
              getattr(C, "FABLE_MAX_OUTPUT_TOKENS", None) == 128_000, str(getattr(C, "FABLE_MAX_OUTPUT_TOKENS", None)))
        call(tmp, good())
        check("with nothing in the caller's environment the child still gets it",
              (tmp / "cap_env").read_text() == "128000", (tmp / "cap_env").read_text())

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
