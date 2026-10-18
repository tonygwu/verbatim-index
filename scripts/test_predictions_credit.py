#!/usr/bin/env python3
"""extract_predictions.py spends API credit only where it says, and records the harness.

  REFUSE    --fable-credit-pools without a stage pinned to Fable, with a timeout over
            1800 s, or with --out anywhere but under predictions/_experiments/ or an
            experiments/ folder outside any predictions tree is refused
  ROUTE     a stage pinned to Fable gets a credit route without asking select_account,
            naming the pools as its account so a failure records them; any other pin
            still goes to the router
  RECORD    a credit call asks for Fable at effort max; its answer keeps harness "fable"
            for the different-family rule, takes the pool as its account, and carries
            "quotapick run" in its telemetry
  TAXONOMY  exhaustion and every other credit failure have their own labels

No quota: credit_run.run is replaced by a stub.

  .venv/bin/python scripts/test_predictions_credit.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("predictions on API credit")
    import credit_run
    import extract_predictions as X
    import predictions_lib as L

    exp = REPO / "data" / "predictions" / "_experiments" / "x"
    base = dict(stage="extract", extractor="fable", verifier="auto", timeout=1800)

    print("\n[REFUSE]")
    check("no pools, no refusal", X.credit_pools_refusal([], SimpleNamespace(**base), exp) is None)
    check("a Fable-pinned extract into an experiment is allowed",
          X.credit_pools_refusal(["p"], SimpleNamespace(**base), exp) is None)
    check("a Fable-pinned verify is allowed",
          X.credit_pools_refusal(["p"], SimpleNamespace(**{**base, "stage": "verify", "extractor": "auto",
                                                           "verifier": "fable"}), exp) is None)
    for label, over, out in (
            ("an auto extractor", {"extractor": "auto"}, exp),
            ("a Gemini-pinned extractor", {"extractor": "gemini"}, exp),
            ("a verify stage whose verifier is not Fable", {"stage": "verify", "verifier": "gemini"}, exp),
            ("a timeout over 1800 s", {"timeout": 2400}, exp),
            ("--out in the production tree", {}, REPO / "data" / "predictions"),
            ("--out in a production leader folder", {}, REPO / "data" / "predictions" / "nate-silver"),
            ("an _experiments folder inside a production leader folder", {},
             REPO / "data" / "predictions" / "nate-silver" / "_experiments" / "x"),
            ("an _experiments folder outside predictions", {}, REPO / "data" / "_experiments" / "x"),
            ("an experiments folder inside a predictions tree", {},
             REPO / "data" / "predictions" / "nate-silver" / "experiments" / "x"),
            ("a folder with no experiment marker at all", {}, REPO / "data-pundits" / "logs" / "x")):
        why = X.credit_pools_refusal(["p"], SimpleNamespace(**{**base, **over}), out)
        check(f"{label} is refused", why is not None, str(why))
    check("the pundits data repo's experiments folder is allowed", X.credit_pools_refusal(
        ["p"], SimpleNamespace(**base), REPO / "data-pundits" / "experiments" / "x") is None)

    print("\n[ROUTE]")
    r = X.Router.__new__(X.Router)
    r.credit_pools, r.accounts, r.exclude_ids = ["anthropic_api_e", "anthropic_api_b"], [], []
    asked = []
    r._select = lambda **kw: asked.append(kw) or (_ for _ in ()).throw(RuntimeError("router asked"))
    route = r.pick("fable", None)
    check("a Fable pin returns a credit route without asking the router",
          route == {"harness": "fable", "account_id": "credit:anthropic_api_e,anthropic_api_b", "config_dir": None,
                    "credit_pools": ["anthropic_api_e", "anthropic_api_b"]} and not asked, str(route))
    try:
        r.pick("gemini", "fable")
        went = False
    except Exception as exc:  # noqa: BLE001 -- the stub raises once the router is consulted
        went = "router" in str(exc) or "pinned harness" in str(exc)
    check("a Gemini pin still goes to the router", went)
    check("a failure before any pool served still names the pools", X._route_fields(route)["account"]
          == "credit:anthropic_api_e,anthropic_api_b", str(X._route_fields(route)))

    print("\n[RECORD]")
    served = {"account": "anthropic_api_b", "model": "claude-fable-5-1", "effort": "max", "pool_kind": "credit",
              "auth": "api_key", "models_seen": ["claude-fable-5-1"]}
    real = credit_run.run
    asked = []
    credit_run.run = lambda *a, **k: asked.append(k) or ("{}", {"harness": "quotapick run", "credit_pool": "anthropic_api_b",
                                                               "served": served, "cost_usd": 1.0})
    try:
        text, tel, account = X.call_harness({"harness": "fable", "credit_pools": ["anthropic_api_b"]}, "P", 1800,
                                            Path("/tmp"), SimpleNamespace(), None)
    finally:
        credit_run.run = real
    check("a credit call asks for Fable at effort max on the route's pools",
          asked and asked[0]["model"] == "claude-fable-5-1" and asked[0]["effort"] == "max"
          and asked[0]["pools"] == ["anthropic_api_b"] and asked[0]["timeout_s"] == 1800
          and asked[0]["expected_cost_usd"] == X.CREDIT_EXPECTED_COST_USD, str(asked))
    prov = L.normalise_provenance("fable", tel, account, None)
    check("the record's harness stays fable, so the different-family rule still applies", prov["harness"] == "fable")
    check("the served model is read from the credit answer and counts as verified",
          prov["served_model"] == "claude-fable-5-1" and prov["served_model_verified"] is True, str(prov))
    check("the account is the pool that served it", prov["account"] == "anthropic_api_b", str(prov))
    check("the telemetry names the harness and pool", tel["harness"] == "quotapick run"
          and tel["credit_pool"] == "anthropic_api_b", str(tel))

    print("\n[TAXONOMY]")
    for exc, label in ((credit_run.PoolsExhausted("exhausted: x"), L.E_CREDIT_EXHAUSTED),
                       (credit_run.CreditRunError("model_mismatch: x"), L.E_CREDIT_FAILED)):
        credit_run.run = lambda *a, e=exc, **k: (_ for _ in ()).throw(e)
        try:
            X.call_fable_credit(["p"], "P", 1800, None)
            got = None
        except RuntimeError as err:
            got = L.classify_exception_detail(str(err))
        finally:
            credit_run.run = real
        check(f"{type(exc).__name__} is labelled {label}", got == label, str(got))
    check("the taxonomy lists each label once", len(L.ALL_ERROR_TYPES) == len(set(L.ALL_ERROR_TYPES)))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
