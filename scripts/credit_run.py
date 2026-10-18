#!/usr/bin/env python3
"""One model call on prepaid Anthropic API credit, through `quotapick run`.

Max plans grant monthly API credit that expires unused. `quotapick run`
(tonygwu/llm-quota-router, the installed CLI; the library pinned in
requirements.txt is v0.1.7 and has no `run`) spends it: one tool-less
`claude -p --bare --tools "" --safe-mode --strict-mcp-config
--no-session-persistence --max-budget-usd` call from an empty directory with the
pool's API key. That is a different harness from the subscription argv in
grade.fable_command, so every answer this returns names it in telemetry.

The pools must be named. Measured 2026-10-18: with no `--only`, run sent a Fable
call to the claude_e SUBSCRIPTION ("claude_e wins ... pool deadline in 11.4h"),
because it spends whatever quota would expire first, credit or not. With
`--only`, a call never leaves the named pools, and the router picks among them.

Every field the caller asked for is checked against the response's `served`
block. quotapick reads the served model from the CLI's own stream; `effort` is
the --effort flag it passed, so that check proves the flag, not the model's use.
`spent` receives the sum of every attempt's cost, a failed call's included: the
response's own top-level cost_usd is the LAST attempt's only. An attempt that
timed out names no cost; quotapick books an estimate in its own ledger instead.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

#: The longest call `quotapick run` accepts. A longer --timeout is refused,
#: never clamped: a call cut off at the limit is still billed.
MAX_TIMEOUT_S = 1800

#: quotapick's own ceiling on attempts per request.
MAX_ATTEMPTS = 3


class PoolsExhausted(RuntimeError):
    """No named pool may take this call: each is empty, or held by calls in flight,
    or unpriced. The last attempt spent nothing; an earlier one may have, and its
    cost reached `spent`. Running holds can cause this while money remains, so
    a run that ends here may be re-run with one worker to use up the rest."""


class CreditRunError(RuntimeError):
    """The call failed or was not served as asked. The message starts with a label."""


def request_for(prompt: str, *, model: str, effort: str, timeout_s: int, expected_cost_usd: float,
                request_id: str, pools: list[str], client: str = "verbatim-index") -> dict:
    if timeout_s > MAX_TIMEOUT_S:
        raise ValueError(f"quotapick run accepts at most {MAX_TIMEOUT_S}s, not {timeout_s}s")
    # One attempt per named pool, up to quotapick's ceiling, so an empty pool hands
    # the call to the next one: quotapick retries exhaustion, auth, transient and
    # wrong-model failures elsewhere and never a timeout. Exhaustion and auth cost
    # nothing. A wrong-model or transient attempt may be billed; its cost is in its
    # own attempts[] entry, and billed_usd sums them.
    return {"model": model, "effort": effort, "prompt": prompt, "timeout_s": timeout_s,
            "expected_cost_usd": expected_cost_usd, "max_attempts": min(MAX_ATTEMPTS, len(pools)),
            "client": client, "request_id": request_id}


def check_response(resp: dict, *, model: str, effort: str, pools: list[str]) -> dict:
    """The served block, after every field is checked. Raises with a label otherwise."""
    if resp.get("run_contract") != 1:
        raise CreditRunError(f"run_contract: {resp.get('run_contract')!r}, this module reads 1")
    outcome = resp.get("outcome")
    tried = {a.get("account") for a in resp.get("attempts") or []}
    # no_candidate: no named pool may take the call (empty, its in-flight holds
    # leave too little, or the router could not price credit; the warnings say
    # which). exhausted: the last attempt found its pool empty; the named pools
    # are done only if every one of them was tried.
    if outcome == "no_candidate" or (outcome == "exhausted" and set(pools) <= tried):
        raise PoolsExhausted(f"{outcome}: {_why(resp)}")
    if outcome != "ok" or resp.get("ok") is not True:
        raise CreditRunError(f"outcome_{outcome}: billed_usd {billed_usd(resp)!r}; {_why(resp)}")
    served = resp.get("served") or {}
    seen = served.get("models_seen") or []
    if served.get("model") != model or not seen or any(m != model for m in seen):
        raise CreditRunError(f"model_mismatch: served {served.get('model')!r}, models seen {seen}, requested {model!r}")
    wrong = {}
    if served.get("effort") != effort:
        wrong["effort"] = served.get("effort")
    if served.get("pool_kind") != "credit":
        wrong["pool_kind"] = served.get("pool_kind")
    if served.get("auth") != "api_key":
        wrong["auth"] = served.get("auth")
    if served.get("account") not in pools:
        wrong["account"] = served.get("account")
    if wrong:
        raise CreditRunError(f"not_served_as_asked: got {wrong}; wanted effort {effort!r}, a credit pool "
                             f"on an API key, one of {pools}")
    return served


def run(prompt: str, *, model: str, effort: str, pools: list[str], timeout_s: int, expected_cost_usd: float,
        request_id: str, raw_path: Path | None = None, spent=None, binary: str = "quotapick") -> tuple[str, dict]:
    """(answer text, telemetry). Raises PoolsExhausted or CreditRunError.

    `request_id` must be unique per attempt: quotapick settles a call's hold by it.
    """
    if not pools or any("," in p or not p.strip() for p in pools):
        raise ValueError(f"name each credit pool separately, got {pools!r}")
    if len(set(pools)) != len(pools):
        # A repeated name would ask quotapick for two attempts on one pool.
        raise ValueError(f"each credit pool once, got {pools!r}")
    req = request_for(prompt, model=model, effort=effort, timeout_s=timeout_s,
                      expected_cost_usd=expected_cost_usd, request_id=request_id, pools=pools)
    # The child's own timeout ends the call; this one only catches a wedged router.
    proc = subprocess.run([binary, "run", "--only", ",".join(pools)], input=json.dumps(req),
                          capture_output=True, text=True, timeout=timeout_s + 300)
    if raw_path is not None:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        from atomicio import write_atomic
        write_atomic(raw_path, json.dumps({"returncode": proc.returncode, "stdout": proc.stdout,
                                           "stderr": proc.stderr}, ensure_ascii=False) + "\n")
    if proc.returncode == 2:
        raise CreditRunError(f"refused: quotapick refused before spending: {(proc.stderr or proc.stdout).strip()[:400]}")
    if proc.returncode != 0:
        raise CreditRunError(f"cli_exit_{proc.returncode}: {(proc.stderr or proc.stdout).strip()[:400]}")
    resp = json.loads(proc.stdout)
    billed = billed_usd(resp)
    if spent is not None and billed is not None:
        spent(billed)
    served = check_response(resp, model=model, effort=effort, pools=pools)
    usage = resp.get("usage") or {}
    durations = [a.get("duration_ms") for a in resp.get("attempts") or []]
    return resp.get("text") or "", {
        "harness": "quotapick run", "credit_pool": served["account"], "served": served,
        "cost_usd": billed, "cost_usd_final_attempt": resp.get("cost_usd"), "request_id": resp.get("request_id"),
        "attempts": len(durations), "served_at_utc": resp.get("generated_at"),
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "thinking_tokens": (usage.get("output_tokens_details") or {}).get("thinking_tokens"),
        # None, not a partial sum, when any attempt does not say how long it took.
        "duration_ms": sum(durations) if durations and all(isinstance(d, int) for d in durations) else None,
    }


def billed_usd(resp: dict) -> float | None:
    """What every attempt of this call cost, summed; None when no attempt names a cost.

    quotapick's top-level cost_usd is only the final attempt's (run.py: `cost_usd =
    final.cost_usd`), so a call retried on a second pool would under-count. Nor is it
    a fallback: `final` is the last entry of `attempts`, so when no attempt names a
    cost the top level names none either.
    """
    costs = [a["cost_usd"] for a in resp.get("attempts") or [] if isinstance(a.get("cost_usd"), (int, float))]
    return sum(costs) if costs else None


def _why(resp: dict) -> str:
    """What the response says about a failure: each attempt, the router's reason, its warnings."""
    attempts = "; ".join(f"{a.get('account')}: {a.get('outcome')} {a.get('detail', '')}".strip()
                         for a in resp.get("attempts") or []) or "no attempts recorded"
    reason = (resp.get("decision") or {}).get("reason")
    warnings = " | ".join(resp.get("warnings") or [])
    return (f"attempts [{attempts}]" + (f"; router: {reason}" if reason else "")
            + (f"; warnings: {warnings}" if warnings else ""))[:700]
