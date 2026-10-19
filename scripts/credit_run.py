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

An answer longer than one turn's output cap comes back cut (VI-23). `claude -p`
continues in a new turn when a turn hits its cap, and returns only the last
turn's text. So this module raises the child's cap to Fable's maximum
(FABLE_MAX_OUTPUT_TOKENS), and refuses an answer whose earlier turn hit the cap
anyway (truncation_detail). grade.call_fable, the subscription harness, does both
through the same names.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

#: The longest call `quotapick run` accepts. A longer --timeout is refused,
#: never clamped: a call cut off at the limit is still billed.
MAX_TIMEOUT_S = 1800

#: quotapick's own ceiling on attempts per request.
MAX_ATTEMPTS = 3

#: The environment variable that sets the output cap of one `claude -p` turn.
#: Confirmed in the installed binary, Claude Code 2.1.303: its error text says "To
#: configure this behavior, set the CLAUDE_CODE_MAX_OUTPUT_TOKENS environment
#: variable". MEASURED 2026-10-19: with it at 1000, a `claude -p` turn stopped at
#: 1,000 output tokens and the CLI continued in a second turn. quotapick passes
#: its own environment to the child, less proxy and auth variables
#: (quota_router/run.py, child_env), so it reaches the credit child too. Do not
#: read the cap back from modelUsage's `maxOutputTokens`: the CLI fills that
#: field with the model's default, so it said 64000 in that same call.
MAX_OUTPUT_TOKENS_ENV = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"

#: The output cap every Fable child runs under: Claude Fable 5.1's maximum output.
#: Sources, 2026-10-19: the claude-api skill (shared/models.md, "Max Output 128K"
#: for claude-fable-5-1), and Claude Code 2.1.303's model table,
#: `max_output_tokens:{default:64000,upper:128000}` for claude-fable-5-1. The CLI
#: caps a larger value to that upper limit and only logs it, so a higher number
#: here would buy nothing. The model is not told the cap, so an answer that fits
#: the old 64,000 is the same answer under this one.
FABLE_MAX_OUTPUT_TOKENS = 128_000

#: The cap a `claude -p` child runs under when the variable above does not reach
#: it: Claude Code 2.1.303's default for claude-fable-5-1, and the cap the two cut
#: answers of 2026-10-18 hit (each lost exactly 64,000 tokens).
CLI_DEFAULT_MAX_OUTPUT_TOKENS = 64_000

#: The label of an answer whose earlier turn hit the output cap (VI-23). grade.py,
#: extract_predictions.py and resolve_predictions.py file it under this name.
E_CONTINUATION_TRUNCATED = "continuation_truncated"


def child_env(base: dict | None = None) -> dict:
    """`base` (the process environment by default) with the output cap set to Fable's maximum.

    Set over any value the caller holds, so every call runs under the one cap
    this module names.
    """
    return {**(os.environ if base is None else base), MAX_OUTPUT_TOKENS_ENV: str(FABLE_MAX_OUTPUT_TOKENS)}


def continuation_gap(usage: dict) -> int | None:
    """Output tokens of the turns before the last one; None when `usage` has no iterations.

    `usage.output_tokens` counts every turn of the call; `usage.iterations` holds
    only the last turn's. A missing per-iteration count counts as 0, so it can
    only widen the gap and make truncation_detail refuse, never hide a cut.
    """
    iterations = usage.get("iterations")
    total = usage.get("output_tokens")
    if not isinstance(iterations, list) or not iterations or not isinstance(total, int):
        return None
    kept = sum(i["output_tokens"] for i in iterations
               if isinstance(i, dict) and isinstance(i.get("output_tokens"), int))
    return total - kept


def truncation_detail(usage: dict, cap: int, text: str) -> str | None:
    """Why `text` is only the last part of a longer answer, or None when no earlier turn hit `cap`.

    MEASURED 2026-10-18 (pat-gelsinger/web-fool-com-335b172e, two credit
    extractions): output_tokens minus the one iteration kept was exactly 64,000,
    the turn cap, and the text started mid-string. The token gap is the check.
    The text's shape is never one: a prose answer must not be refused for not
    starting with `{`. A gap below the cap is a turn that ended on its own, such
    as a denied tool call on the subscription harness, and passes.

    Two known false refusals, both of a whole answer. First, when a turn hits
    the cap while still thinking, the CLI drops that reasoning and asks for a
    fresh answer, so the gap is the cap; at 128,000 that needs 128,000 tokens of
    thinking. Second, run() tests against 64,000 while its child runs under
    128,000, so an earlier turn of 64,000 or more that ended on its own, such as
    one with no visible text that the CLI asks to continue, is refused too. The
    message names the thinking tokens, so a reader can tell these cases apart.
    """
    gap = continuation_gap(usage)
    if gap is None or gap < cap:
        return None
    kept = usage["output_tokens"] - gap
    thinking = (usage.get("output_tokens_details") or {}).get("thinking_tokens")
    return (f"usage.output_tokens {usage['output_tokens']} minus usage.iterations {kept} leaves {gap}, "
            f"at least the {cap}-token turn cap, so an earlier turn was cut off and the {len(text)}-character "
            f"text is only the continuation (thinking_tokens {thinking}; text starts {text[:60]!r})")


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
                          capture_output=True, text=True, timeout=timeout_s + 300, env=child_env())
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
    # The response does not say which cap the child ran under, so the threshold is
    # the smallest it could have been: the CLI default, which applies when the
    # variable does not reach the child. If a quotapick release stopped passing it
    # on, answers would be cut at 64,000 again, and a 128,000 threshold would let
    # those fragments through as schema failures, the bug VI-23 fixes. With no
    # tools, an earlier turn is almost always a capped one. MEASURED 2026-10-19:
    # of 158 saved credit responses with iterations, the 2 cut answers have a gap
    # of exactly 64,000 and the other 156 a gap of 0.
    cut = truncation_detail(usage, CLI_DEFAULT_MAX_OUTPUT_TOKENS, resp.get("text") or "")
    if cut:
        raise CreditRunError(f"{E_CONTINUATION_TRUNCATED}: {cut}; billed_usd {billed!r}")
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
