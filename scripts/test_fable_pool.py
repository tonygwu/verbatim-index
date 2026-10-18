#!/usr/bin/env python3
"""The credit-pool Fable harness: `grade.py --fable-pool` and `resolve_predictions.py --fable-pool`.

WHY THIS EXISTS. Prepaid Anthropic API credit ("credit pools") is reachable only
through `quotapick run` (tonygwu/llm-quota-router), which runs one tool-less
`claude -p --bare` call with the pool's API key. That is a different harness from
the production judge: tools absent instead of denied, no session transcript, no
subscription. These checks hold the lines that keep it honest:

  REQUEST    the request names Fable, effort max, the timeout, one attempt per
             named pool, and `run --only <pools>`, so a call can never fall back
             to a subscription. Since 2026-10-18 the pool is a comma list and the
             call goes through credit_run.run, the one credit path (VI-5).
  IDENTITY   an answer counts only when `served` names Fable (every model seen),
             effort max, a credit pool, API-key auth and the pool asked for.
  OUTCOMES   each quotapick outcome maps to this repo's taxonomy; "exhausted" and
             "no_candidate" are E_POOL_EXHAUSTED; exit 2 is E_POOL_REFUSED; an
             unknown outcome is refused, never guessed.
  BILLING    a failed call's cost is still tallied (a timed-out call is billed).
  GRADE      grade_one with a pool writes a record that names harness
             "quotapick run" and the pool, and the pool's "empty" stops the
             next job before it is sent.
  GUARDS     --fable-pool is refused for contract v2, outside experiments/, over
             1800 s, and without Fable; --credit-production admits exactly the
             study's grades/ directory and nothing else (operator decision
             2026-10-18, VI-14); resolve_predictions refuses it for an Astra
             stage and for a run the scores read.
  CLASSIFY   resolve_predictions.classify reads the pool labels before its
             keyword rules.

No quota: `quotapick` is replaced by a fake script.

  .venv/bin/python scripts/test_fable_pool.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
req = json.loads(sys.stdin.read())
with open(os.environ["FAKE_QP_CAPTURE"], "w") as fh:
    json.dump({"argv": sys.argv[1:], "request": req}, fh)
scen = os.environ["FAKE_QP_SCENARIO"]
if scen == "refused_exit2":
    print("bad config: no such pool", file=sys.stderr); sys.exit(2)
served = {"account": os.environ.get("FAKE_QP_ACCOUNT", "anthropic_api_d"), "provider": "anthropic_api",
          "pool_kind": "credit", "model": "claude-fable-5-1", "model_requested": "claude-fable-5-1",
          "models_seen": ["claude-fable-5-1"], "effort": "max", "auth": "api_key"}
resp = {"run_contract": 1, "ok": True, "outcome": "ok", "text": os.environ.get("FAKE_QP_TEXT", "FABLE-OK"),
        "served": served, "cost_usd": 2.5, "request_id": req.get("request_id"),
        "generated_at": "2026-10-18T03:00:00Z",
        "usage": {"input_tokens": 100, "output_tokens": 50, "output_tokens_details": {"thinking_tokens": 40}},
        "attempts": [{"account": served["account"], "outcome": "ok", "duration_ms": 1234, "detail": ""}]}
if scen == "wrong_model":
    served["model"] = "claude-opus-5-5"; served["models_seen"] = ["claude-opus-5-5"]
elif scen == "mixed_models":
    served["models_seen"] = ["claude-fable-5-1", "claude-haiku-5-5"]
elif scen == "subscription":
    served["pool_kind"] = "subscription"; served["auth"] = "oauth"
elif scen == "effort_high":
    served["effort"] = "high"
elif scen in ("exhausted", "no_candidate", "timeout_billed", "weird"):
    resp.update(ok=False, outcome={"timeout_billed": "timeout"}.get(scen, scen), text="",
                cost_usd=1.23 if scen == "timeout_billed" else 0.0)
    resp["attempts"][0].update(outcome=resp["outcome"], detail="pool says no")
elif scen == "contract2":
    resp["run_contract"] = 2
elif scen == "no_duration":
    del resp["attempts"][0]["duration_ms"]
for a in resp["attempts"]:
    a["cost_usd"] = resp["cost_usd"]
print(json.dumps(resp))
'''


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_pooltest", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = load("grade")


def run_call(tmp: Path, scenario: str, account: str = "anthropic_api_d", text: str = "FABLE-OK",
             pool: str = "anthropic_api_d", timeout: int = 300):
    """One call_fable_pool against the fake. Returns (result or exception, capture, costs)."""
    os.environ.update(FAKE_QP_SCENARIO=scenario, FAKE_QP_ACCOUNT=account, FAKE_QP_TEXT=text,
                      FAKE_QP_CAPTURE=str(tmp / "capture.json"))
    costs: list[float] = []
    try:
        out = G.call_fable_pool("the prompt", pool, timeout, request_id="ada/s1", expected_cost_usd=5.0,
                                raw_response_path=tmp / "raw" / "r.response.json",
                                binary=str(tmp / "quotapick"), spent=costs.append)
    except Exception as exc:  # noqa: BLE001
        out = exc
    cap = json.loads((tmp / "capture.json").read_text()) if (tmp / "capture.json").exists() else None
    return out, cap, costs


def label_of(out) -> str:
    return G.classify_exception_detail(str(out)) if isinstance(out, Exception) else "ok"


def valid_grade(tid: str) -> dict:
    words = " ".join(["word"] * 25)
    return {"transcript_id": tid, "subcriteria": [{"code": c, "score": 3} for c in G.SUBCRITERIA],
            "dimensions": {k: {"score": 60, "reasoning": words, "counterevidence": "some",
                               "evidence": [{"quote": "a short quote"}]} for k in G.WEIGHTS},
            "overall": 60.0, "coverage": 1.0}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "quotapick").write_text(FAKE)
        (tmp / "quotapick").chmod(0o755)

        print("\n[REQUEST] what is sent, and to which pool only")
        out, cap, costs = run_call(tmp, "ok")
        req = cap["request"]
        check("argv is `run --only <pool>`", cap["argv"] == ["run", "--only", "anthropic_api_d"], f"{cap['argv']}")
        check("the request names Fable at effort max",
              (req["model"], req["effort"]) == ("claude-fable-5-1", "max"), f"{req}")
        check("the request carries the timeout, cost, client, id and one attempt",
              (req["timeout_s"], req["expected_cost_usd"], req["client"], req["request_id"], req["max_attempts"])
              == (300, 5.0, "verbatim-index", "ada/s1", 1), f"{req}")
        check("an ok call returns the text", isinstance(out, tuple) and out[0] == "FABLE-OK", f"{out}")
        tel = out[1] if isinstance(out, tuple) else {}
        check("telemetry names the harness and pool",
              (tel.get("harness"), tel.get("credit_pool"), tel.get("pool_kind"), tel.get("auth"))
              == ("quotapick run", "anthropic_api_d", "credit", "api_key"), f"{tel}")
        check("telemetry carries thinking tokens, cost and the served time",
              (tel.get("thinking_tokens"), tel.get("cost_usd"), tel.get("served_at_utc"))
              == (40, 2.5, "2026-10-18T03:00:00Z"), f"{tel}")
        check("the full response is saved before parsing", (tmp / "raw" / "r.response.json").exists())
        check("an ok call's cost is tallied", costs == [2.5], f"{costs}")
        check("an ok call's duration is the attempts' sum", tel.get("duration_ms") == 1234, f"{tel}")
        out, _, _ = run_call(tmp, "no_duration")
        check("a missing attempt duration is None, not 0",
              isinstance(out, tuple) and out[1].get("duration_ms") is None, f"{out!r}")
        try:
            G.call_fable_pool("p", "anthropic_api_d", 2400, request_id="x", expected_cost_usd=1.0,
                              binary=str(tmp / "quotapick"))
            check("a timeout over 1800 s is refused before any call", False, "no exception")
        except ValueError:
            check("a timeout over 1800 s is refused before any call", True)

        print("\n[POOLS] a comma list names several pools, and any of them may serve")
        out, cap, costs = run_call(tmp, "ok", account="anthropic_api_b", pool="anthropic_api_a,anthropic_api_b")
        check("argv is `run --only a,b`", cap["argv"] == ["run", "--only", "anthropic_api_a,anthropic_api_b"],
              f"{cap['argv']}")
        check("the request asks one attempt per named pool", cap["request"]["max_attempts"] == 2,
              f"{cap['request'].get('max_attempts')}")
        check("an answer served by the second named pool is accepted and names it",
              isinstance(out, tuple) and out[1].get("credit_pool") == "anthropic_api_b", f"{out!r}")
        out, _, _ = run_call(tmp, "ok", account="anthropic_api_c", pool="anthropic_api_a,anthropic_api_b")
        check("an answer from a pool outside the list is refused as account_identity_mismatch",
              label_of(out) == G.E_IDENTITY, f"{out!r}")
        for bad in ("", "anthropic_api_a,,anthropic_api_b", " ,", "anthropic_api_a,anthropic_api_a"):
            try:
                G.call_fable_pool("p", bad, 300, request_id="x", expected_cost_usd=1.0, binary=str(tmp / "quotapick"))
                check(f"a malformed pool list {bad!r} is refused before any call", False, "no exception")
            except Exception as exc:  # noqa: BLE001
                # A ValueError is the refusal; anything else means the call was sent.
                check(f"a malformed pool list {bad!r} is refused before any call", isinstance(exc, ValueError), repr(exc))

        print("\n[ONE PATH] call_fable_pool is credit_run.run with grade.py's labels (VI-5)")
        # The module instance grade.py imported, not a second load: the mapping
        # catches credit_run's exception classes by identity, as production does.
        CR = G.credit_run
        real_run = G.credit_run.run
        try:
            def stub(exc):
                def _run(*a, **k):
                    raise exc
                return _run
            for exc, want in ((CR.CreditRunError("not_served_as_asked: got {'effort': 'high'}"), G.E_IDENTITY),
                              (CR.CreditRunError("model_mismatch: served 'claude-opus-5-5'"), G.E_MODEL_MISMATCH),
                              (CR.PoolsExhausted("no_candidate: attempts []"), G.E_POOL_EXHAUSTED),
                              (CR.CreditRunError("refused: quotapick refused before spending: x"), G.E_POOL_REFUSED),
                              (CR.CreditRunError("cli_exit_1: boom"), G.E_CLI),
                              (CR.CreditRunError("outcome_timeout: billed_usd 1.2; attempts []"), G.E_TIMEOUT),
                              (CR.CreditRunError("outcome_auth: billed_usd None; attempts []"), G.E_AUTH),
                              (CR.CreditRunError("outcome_zzz: billed_usd None; attempts []"), G.E_POOL_REFUSED)):
                G.credit_run.run = stub(exc)
                try:
                    G.call_fable_pool("p", "anthropic_api_a", 300, request_id="x", expected_cost_usd=1.0)
                    check(f"credit_run {str(exc)[:22]!r} -> {want}", False, "no exception")
                except Exception as got:  # noqa: BLE001
                    check(f"credit_run {str(exc)[:22]!r} -> {want}", G.classify_exception_detail(str(got)) == want,
                          f"{got!r}")
        finally:
            G.credit_run.run = real_run
        check("the same served-field mismatch is one label through credit_run.check_response itself",
              G.classify_exception_detail(str(G.pool_error(CR.CreditRunError("not_served_as_asked: got {}"))))
              == G.E_IDENTITY)

        print("\n[IDENTITY] an answer counts only when served as asked")
        for scen, want in (("wrong_model", G.E_MODEL_MISMATCH), ("mixed_models", G.E_MODEL_MISMATCH),
                           ("subscription", G.E_IDENTITY), ("effort_high", G.E_IDENTITY)):
            out, _, _ = run_call(tmp, scen)
            check(f"{scen} is refused as {want}", label_of(out) == want, f"{out!r}")
        out, _, _ = run_call(tmp, "ok", account="anthropic_api_c")
        check("an answer from another pool is refused as account_identity_mismatch",
              label_of(out) == G.E_IDENTITY, f"{out!r}")

        print("\n[OUTCOMES] quotapick outcomes map to the taxonomy")
        for scen, want in (("exhausted", G.E_POOL_EXHAUSTED), ("no_candidate", G.E_POOL_EXHAUSTED),
                           ("timeout_billed", G.E_TIMEOUT), ("weird", G.E_POOL_REFUSED),
                           ("refused_exit2", G.E_POOL_REFUSED), ("contract2", G.E_POOL_REFUSED)):
            out, _, costs = run_call(tmp, scen)
            check(f"{scen} -> {want}", label_of(out) == want, f"{out!r}")
            if scen == "timeout_billed":
                print("\n[BILLING] a failed call's cost is still tallied")
                check("a billed timeout reports its cost", costs == [1.23], f"{costs}")

        print("\n[GRADE] grade_one through a pool")
        os.environ.update(FAKE_QP_SCENARIO="ok", FAKE_QP_ACCOUNT="anthropic_api_d",
                          FAKE_QP_TEXT=json.dumps(valid_grade("ada-lovelace/s1")),
                          FAKE_QP_CAPTURE=str(tmp / "capture.json"))
        state = {"exhausted": threading.Event(), "spend": (spent := []).append}
        out_dir = tmp / "data" / "experiments" / "x" / "grades"

        def job(sid: str) -> dict:
            stem = f"{sid}__fable__blinded__r1"
            return {"rec": {"leader_slug": "ada-lovelace", "source_id": sid, "text": "words " * 50,
                            "word_count": 50}, "judge": "fable", "mode": "blinded", "run": 1, "force": False,
                    "regrade_invalid": False, "rubric": "R", "schema": "{}", "timeout": 300,
                    "contract": {"contract_id": "c"}, "config_dir": "__DEFAULT__", "fable_bin": "claude",
                    "workdir": str(tmp / "wd"), "fable_pool": "anthropic_api_d", "pool_expected_cost": 5.0,
                    "pool_state": state, "obsolete_root": str(out_dir / "_obsolete"),
                    "dest": str(out_dir / "fable" / "ada-lovelace" / f"{stem}.json"),
                    "raw_dest": str(out_dir / "_raw" / "fable" / "ada-lovelace" / f"{stem}.txt")}

        real = G.call_fable_pool
        G.call_fable_pool = lambda *a, **k: real(*a, **{**k, "binary": str(tmp / "quotapick")})
        try:
            r = G.grade_one(job("s1"))
            check("a valid pool answer is graded ok", r.get("status") == "ok", f"{r}")
            rec = json.loads((out_dir / "fable" / "ada-lovelace" / "s1__fable__blinded__r1.json").read_text())
            check("the record names harness 'quotapick run' and the pool",
                  (rec.get("harness"), rec.get("credit_pool")) == ("quotapick run", "anthropic_api_d"), f"{rec}")
            check("the record's telemetry names the harness too",
                  rec["telemetry"].get("harness") == "quotapick run", f"{rec['telemetry']}")
            check("the sent request id names the grade",
                  json.loads((tmp / "capture.json").read_text())["request"]["request_id"]
                  == "ada-lovelace/s1__fable__blinded__r1")
            check("the response JSON is kept beside the raw text",
                  (out_dir / "_raw" / "fable" / "ada-lovelace" / "s1__fable__blinded__r1.response.json").exists())
            os.environ["FAKE_QP_SCENARIO"] = "exhausted"
            r = G.grade_one(job("s2"))
            check("an empty pool fails the job as credit_pool_exhausted",
                  (r.get("status"), r.get("error_type")) == ("failed", G.E_POOL_EXHAUSTED), f"{r}")
            check("and marks the pool empty for the run", state["exhausted"].is_set())
            (tmp / "capture.json").unlink()
            r = G.grade_one(job("s3"))
            check("the next job is skipped without a call",
                  (r.get("status"), r.get("error_type")) == ("skipped", G.E_POOL_EXHAUSTED)
                  and not (tmp / "capture.json").exists(), f"{r}")
            check("every billed cost was tallied", spent == [2.5, 0.0], f"{spent}")
        finally:
            G.call_fable_pool = real

        print("\n[GUARDS] where --fable-pool may not run")
        link = tmp / "data"
        (link / "experiments").mkdir(parents=True, exist_ok=True)
        ok_out = str(link / "experiments" / "run" / "grades")
        check("an experiments --out passes",
              G.fable_pool_refusal("anthropic_api_d", ok_out, 1800, ["fable"], 1, link) is None)
        check("no pool, no refusal", G.fable_pool_refusal(None, str(link / "grades"), 2400, ["astra"], 2, link) is None)
        for name, args in (("the production grades dir", ("p", str(link / "grades"), 1800, ["fable"], 1)),
                           ("a sibling that only starts with 'experiments'",
                            ("p", str(link / "experiments-old" / "g"), 1800, ["fable"], 1)),
                           ("a contract v2 study", ("p", ok_out, 1800, ["fable"], 2)),
                           ("--timeout 2400", ("p", ok_out, 2400, ["fable"], 1)),
                           ("judges without Fable", ("p", ok_out, 1800, ["astra"], 1))):
            check(f"refused: {name}", bool(G.fable_pool_refusal(*args, link)), f"{args}")

        print("\n[PRODUCTION] --credit-production admits exactly the study's grades/ (VI-14)")
        prod = str(link / "grades")
        check("--credit-production admits <data>/grades",
              G.fable_pool_refusal("a,b", prod, 1800, ["fable"], 1, link, credit_production=True) is None)
        cwd0 = os.getcwd()
        os.chdir(link)
        try:
            check("... written as a relative path too",
                  G.fable_pool_refusal("a,b", "grades", 1800, ["fable"], 1, link, credit_production=True) is None)
        finally:
            os.chdir(cwd0)
        for name, args in (("a subdirectory of grades", ("p", str(link / "grades" / "fable"), 1800, ["fable"], 1)),
                           ("a sibling grades_smoke", ("p", str(link / "grades_smoke"), 1800, ["fable"], 1)),
                           ("contract v2 with the flag", ("p", prod, 1800, ["fable"], 2)),
                           ("--timeout 2400 with the flag", ("p", prod, 2400, ["fable"], 1)),
                           ("judges without Fable with the flag", ("p", prod, 1800, ["astra"], 1))):
            check(f"still refused: {name}", bool(G.fable_pool_refusal(*args, link, credit_production=True)), f"{args}")
        check("--credit-production without --fable-pool is refused",
              bool(G.fable_pool_refusal(None, prod, 2400, ["fable"], 1, link, credit_production=True)))
        check("without the flag the production grades dir is still refused",
              bool(G.fable_pool_refusal("p", prod, 1800, ["fable"], 1, link)))
        check("an experiments --out still passes with the flag",
              G.fable_pool_refusal("p", ok_out, 1800, ["fable"], 1, link, credit_production=True) is None)

        print("\n[MIX] aggregate.py counts grades per judge per harness (VI-14)")
        AG = load("aggregate")
        mix = AG.harness_counts([{"judge": "fable"}, {"judge": "fable", "harness": "quotapick run"},
                                 {"judge": "fable", "harness": "quotapick run"}, {"judge": "astra"}])
        check("a grade with no harness key is the production harness, a pool grade its own",
              mix == {"astra": {"production": 1}, "fable": {"production": 1, "quotapick run": 2}}, str(mix))
        check("an empty corpus counts nothing", AG.harness_counts([]) == {})

        RP = load("resolve_predictions")
        ns = lambda **k: argparse.Namespace(**{"fable_pool": "anthropic_api_c", "stage": "prior",  # noqa: E731
                                               "timeout": 900, **k})
        runs = [tmp / "pred" / "_experiments" / "prod-run"]
        check("resolve: a fresh prior run passes",
              RP.fable_pool_refusal(ns(), tmp / "pred" / "_experiments" / "new", runs) is None)
        check("resolve: the resolve stage is refused", bool(RP.fable_pool_refusal(ns(stage="resolve"), tmp / "n", runs)))
        check("resolve: a run the scores read is refused", bool(RP.fable_pool_refusal(ns(), runs[0], runs)))
        check("resolve: --timeout 2400 is refused", bool(RP.fable_pool_refusal(ns(timeout=2400), tmp / "n", runs)))
        check("resolve: a pool list is refused (one pool here, a list is grade.py's)",
              bool(RP.fable_pool_refusal(ns(fable_pool="anthropic_api_a,anthropic_api_b"), tmp / "n", runs)))

        print("\n[CLASSIFY] resolve_predictions reads the pool labels first")
        for lab in (G.E_POOL_EXHAUSTED, G.E_POOL_REFUSED, G.E_MODEL_MISMATCH, G.E_IDENTITY):
            got = RP.classify(f"{lab}: quotapick outcome 'x' on pool: auth timeout")
            check(f"{lab} is kept", got == lab, got)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
