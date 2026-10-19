#!/usr/bin/env python3
"""A Fable answer that overran one turn's output cap is refused with its own label, on every path (VI-23).

On 2026-10-18 two credit extractions of pat-gelsinger/web-fool-com-335b172e ($4.81 and
$5.03) came back as a fragment that starts mid-string: the first turn hit the
64,000-token cap, `claude -p` continued in a second turn, and only that turn's text
was returned. The extractor filed it as a schema failure, which names the model when
the harness is at fault. The signal is in `usage`: `output_tokens` counts every turn,
`iterations` only the last one, so a gap of at least one turn's cap means an earlier
turn was cut off.

  SUBSCRIPTION  grade.call_fable refuses the gap as continuation_truncated, judged against
                the 128,000 cap it sets, never modelUsage's maxOutputTokens (the CLI fills
                that with the model's default, 64,000); an earlier tool turn below the cap
                (measured 2026-10-02: 73,007 tokens and a whole answer) passes; a single
                turn and a usage with no iterations pass
  CAP           the `claude -p` child gets CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 over the
                caller's own value
  POOL          grade.call_fable_pool files it as continuation_truncated, not credit_pool_refused
  EXTRACT       extract_predictions.call_fable_credit keeps the label at the front instead of
                credit_run_failed, so predictions_lib.classify_exception_detail files it
  TAXONOMY      the label is in grade.ALL_ERROR_TYPES and predictions_lib.ALL_ERROR_TYPES, and
                resolve_predictions.classify keeps it

No quota: fake `claude` and `quotapick` binaries print canned responses.

  .venv/bin/python scripts/test_continuation_truncated.py
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
LABEL = "continuation_truncated"
FRAGMENT = '.","timestamp_hint":"unmarked","normalized_claim":"Intel\'s first efficient-core"}]}'


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def fake_claude(tmp: Path) -> Path:
    """A `claude` stand-in: records the output-cap variable, prints $FAKE_CLAUDE_OUT's file."""
    return executable(tmp / "claude", "#!/bin/sh\n"
                      f"printf '%s' \"${{CLAUDE_CODE_MAX_OUTPUT_TOKENS-UNSET}}\" > '{tmp}/claude_cap_env'\n"
                      "cat \"$FAKE_CLAUDE_OUT\"\n")


def fake_quotapick(tmp: Path) -> Path:
    """A `quotapick` stand-in that prints $FAKE_QP_OUT's file."""
    return executable(tmp / "quotapick", "#!/bin/sh\ncat > /dev/null\ncat \"$FAKE_QP_OUT\"\n")


def cli_payload(total: int, kept: list[int] | None, text: str, cap: int | None) -> dict:
    """The `claude -p --output-format json` result, shaped like the 2026-10-18 subscription answer."""
    usage = {"input_tokens": 2, "output_tokens": total, "output_tokens_details": {"thinking_tokens": 39077}}
    if kept is not None:
        usage["iterations"] = [{"type": "message", "output_tokens": n} for n in kept]
    model = {"inputTokens": 2, "outputTokens": total, "costUSD": 3.25, "canonicalModel": "claude-fable-5-1"}
    if cap is not None:
        model["maxOutputTokens"] = cap
    return {"type": "result", "is_error": False, "result": text, "session_id": "sid", "num_turns": 1,
            "total_cost_usd": 3.25, "duration_ms": 616400, "usage": usage,
            "modelUsage": {"claude-fable-5-1": model}}


def credit_payload(total: int, kept: list[int], text: str, account: str = "anthropic_api_a") -> dict:
    served = {"account": account, "provider": "anthropic_api", "pool_kind": "credit", "model": "claude-fable-5-1",
              "model_requested": "claude-fable-5-1", "models_seen": ["claude-fable-5-1"], "effort": "max",
              "auth": "api_key"}
    return {"run_contract": 1, "ok": True, "outcome": "ok", "text": text, "served": served,
            "usage": {"input_tokens": 8, "output_tokens": total, "output_tokens_details": {"thinking_tokens": 57349},
                      "iterations": [{"type": "message", "output_tokens": n} for n in kept]},
            "cost_usd": 5.03, "request_id": "rid", "generated_at": "2026-10-18T08:02:10Z",
            "attempts": [{"account": account, "outcome": "ok", "duration_ms": 762768, "cost_usd": 5.03}]}


def outcome(fn):
    """(text or None, exception text or None)."""
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 -- the test inspects the label
        return None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print("continuation_truncated")
    import credit_run
    import extract_predictions as X
    import grade as G
    import predictions_lib as L
    import resolve_predictions as RP

    with tempfile.TemporaryDirectory(prefix="vi23-") as td:
        tmp = Path(td).resolve()
        claude = fake_claude(tmp)
        out_file = tmp / "claude_out.json"
        os.environ["FAKE_CLAUDE_OUT"] = str(out_file)

        def sub(payload: dict):
            out_file.write_text(json.dumps(payload))
            return outcome(lambda: G.call_fable("PROMPT", str(tmp / "cfg"), 30, binary=str(claude),
                                                workdir=str(tmp / "jail")))

        print("\n[SUBSCRIPTION]")
        got, err = sub(cli_payload(128_000 + 300, [300], FRAGMENT, 64_000))
        check("a first turn cut at the 128,000 cap is refused as continuation_truncated",
              err is not None and G.classify_exception_detail(err.split(": ", 1)[1]) == LABEL, str(err or got))
        got, err = sub(cli_payload(2 * 128_000 + 300, [300], FRAGMENT, 64_000))
        check("two cut turns are refused too", err is not None and LABEL in err, str(err or got))
        got, err = sub(cli_payload(73_007 + 21_167, [21_167], '{"candidates": []}', 64_000))
        check("an earlier tool turn of 73,007 tokens passes, though modelUsage says maxOutputTokens 64000",
              err is None and got[0] == '{"candidates": []}', str(err or got))
        got, err = sub(cli_payload(49_159, [49_159], "A prose answer.", 64_000))
        check("a single turn passes, prose or not", err is None and got[0] == "A prose answer.", str(err or got))
        got, err = sub(cli_payload(49_159, None, '{"candidates": []}', 64_000))
        check("a usage with no iterations passes as before", err is None, str(err))

        print("\n[CAP]")
        os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "1000"
        try:
            got, err = sub(cli_payload(49_159, [49_159], "{}", 64_000))
        finally:
            del os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]
        cap_env = (tmp / "claude_cap_env").read_text()
        check("the subscription child gets CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 over the caller's 1000",
              err is None and cap_env == "128000", f"{cap_env} {err}")

        print("\n[POOL]")
        qp = fake_quotapick(tmp)
        qp_file = tmp / "qp_out.json"
        os.environ["FAKE_QP_OUT"] = str(qp_file)
        qp_file.write_text(json.dumps(credit_payload(68_707, [4_707], FRAGMENT)))
        spent = []
        got, err = outcome(lambda: G.call_fable_pool("PROMPT", "anthropic_api_a", 300, request_id="x",
                                                     expected_cost_usd=3.0, binary=str(qp), spent=spent.append))
        check("call_fable_pool files it as continuation_truncated, not credit_pool_refused",
              err is not None and G.classify_exception_detail(err.split(": ", 1)[1]) == LABEL, str(err or got))
        check("and the cost of the lost answer is still counted", spent == [5.03], str(spent))

        print("\n[EXTRACT]")
        path = os.environ["PATH"]
        os.environ["PATH"] = f"{tmp}{os.pathsep}{path}"
        try:
            got, err = outcome(lambda: X.call_fable_credit(["anthropic_api_a"], "PROMPT", 1800, None))
        finally:
            os.environ["PATH"] = path
        detail = (err or "").split(": ", 1)[-1]
        check("call_fable_credit keeps the label at the front, not credit_run_failed",
              detail.startswith(LABEL), str(err or got))
        check("predictions_lib.classify_exception_detail files it as continuation_truncated",
              L.classify_exception_detail(detail) == LABEL, L.classify_exception_detail(detail))

        print("\n[TAXONOMY]")
        check("grade.ALL_ERROR_TYPES names it", LABEL in G.ALL_ERROR_TYPES)
        check("predictions_lib.ALL_ERROR_TYPES names it once", list(L.ALL_ERROR_TYPES).count(LABEL) == 1)
        check("grade.pool_error maps credit_run's label to it",
              G.classify_exception_detail(str(G.pool_error(credit_run.CreditRunError(f"{LABEL}: gap 64000"))))
              == LABEL)
        got = RP.classify(f"{LABEL}: quotapick {LABEL}: an auth timeout word in the text")
        check("resolve_predictions.classify keeps it before its keyword rules", got == LABEL, got)
        check("resolve_predictions.ERROR_TYPES names it", LABEL in RP.ERROR_TYPES)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
