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
  FAILED    an extraction that fails on credit records the pools it was sent to, through
            extract_one itself, not only the helper; a pick that fails before any route
            exists is a recorded failure, not a crash
  CACHE     a credit answer and a subscription answer have different cache audits, an
            audit written without credit is unchanged, and a credit answer written before
            the audit named its harness is still known by the pool it names
  REVISION  the code revision a run records gains "+dirty" when scripts/ or the skill
            (reached through the .claude/skills link) holds uncommitted changes

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
    import tempfile
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
            ("a folder with no experiment marker at all", {}, REPO / "data-pundits" / "logs" / "x"),
            ("an auto extractor in a run whose verify stage is pinned to Fable",
             {"stage": "both", "extractor": "auto", "verifier": "fable"}, exp),
            ("an auto verifier in a run whose extract stage is pinned to Fable",
             {"stage": "both", "extractor": "fable", "verifier": "auto"}, exp)):
        why = X.credit_pools_refusal(["p"], SimpleNamespace(**{**base, **over}), out)
        check(f"{label} is refused", why is not None, str(why))
    check("both stages pinned, Fable extracting and Gemini verifying, is allowed", X.credit_pools_refusal(
        ["p"], SimpleNamespace(**{**base, "stage": "both", "verifier": "gemini"}), exp) is None)
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

    print("\n[FAILED]")
    patched = {(X, n): getattr(X, n) for n in ("read_meta", "write_meta", "read_transcript", "stage_audit",
                                               "save_inputs", "paths_for")}
    patched |= {(L, n): getattr(L, n) for n in ("build_extraction_prompt", "transcript_id_from_path")}
    patched[(credit_run, "run")] = credit_run.run
    written = {}
    try:
        X.read_meta = lambda p: {"extract": {}, "verify": {"status": "not_run"}}
        X.write_meta = lambda p, m: written.update(m)
        X.read_transcript = lambda *a: {"text": "t", "leader_slug": "s", "source_id": "i"}
        L.build_extraction_prompt = lambda *a, **k: "PROMPT"
        X.stage_audit = lambda *a, **k: {}
        X.save_inputs = lambda *a, **k: None
        X.paths_for = lambda out, slug, sid: (out / "a.jsonl", out / "m.json")
        L.transcript_id_from_path = lambda p: "slug/sid"

        def boom(*a, **k):
            raise credit_run.PoolsExhausted("no_candidate: attempts [no attempts recorded]")
        credit_run.run = boom
        rt = X.Router.__new__(X.Router)
        rt.credit_pools, rt.accounts, rt.exclude_ids = ["anthropic_api_d", "anthropic_api_c"], [], []
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            job = {"args": SimpleNamespace(dry_run=False, force=False, extractor="fable", timeout=1800),
                   "path": str(td / "x.json"), "out": td, "run_id": "run1", "exclusions": {},
                   "contract": {"contract_id": "c"}, "roster": {}, "spec": None, "schema_text": "",
                   "header_template": None, "workroot": td / "work", "router": rt}
            res = X.extract_one(job)
            ext = dict(written.get("extract", {}))

            def no_route(*a):
                raise RuntimeError("no_eligible_account: every account is out")
            rt.pick = no_route
            written.clear()
            try:
                res_pick = X.extract_one(job)
            except Exception as exc:   # an unbound route surfaces here as UnboundLocalError
                res_pick = {"raised": repr(exc)}
    finally:
        for (mod, name), fn in patched.items():
            setattr(mod, name, fn)
    check("an extraction that fails on credit records the pools it was sent to, and its label",
          ext.get("account") == "credit:anthropic_api_d,anthropic_api_c" and ext.get("harness") == "fable"
          and ext.get("error_type") == L.E_CREDIT_EXHAUSTED and res.get("account") == ext.get("account"), str(ext))
    check("a pick that fails before any route exists is a recorded failure, not a crash",
          res_pick.get("status") == "failed" and "no_eligible_account" in res_pick.get("detail", "")
          and written.get("extract", {}).get("status") == "failed", str(res_pick))

    print("\n[CACHE]")
    job = {"args": SimpleNamespace(extractor="fable", verifier="auto", astra_model="a", gemini_model="g",
                                   fable_credit_pools="anthropic_api_d,anthropic_api_c"),
           "release": {"release": "r"}, "code_revision": "c", "input_data_revision": "d"}
    credit = X.stage_audit(job, "extract", {"x": 1}, ["P"])
    job["args"].fable_credit_pools = ""
    sub = X.stage_audit(job, "extract", {"x": 1}, ["P"])
    check("a credit answer's cache audit differs from a subscription answer's",
          credit != sub and credit["model_request"]["fable_harness"] == "quotapick run", f"{credit} {sub}")
    check("an audit written without credit has no new key, so existing caches still match",
          sub["model_request"] == {"harness": "fable", "astra_model": None, "gemini_model": None}, str(sub))
    same = {k: credit[k] for k in ("policy_release", "input_sha256", "prompt_sha256")}
    plain = sub["model_request"]   # what a credit audit looked like before 328566c, too

    def saved(model_request, **who):
        return {"contract_id": "K", "audit": {**same, "model_request": model_request}, **who}
    # (saved meta, cached by a subscription run, cached by a credit run)
    shapes = {
        "pilot credit (no router id, pool account)": (saved(plain, account="anthropic_api_e", router_account_id=None), False, True),
        "credit before 328566c (credit: router id)": (saved(plain, account="anthropic_api_d",
                                                         router_account_id="credit:anthropic_api_d,anthropic_api_c"), False, True),
        "credit from 328566c on": (saved(credit["model_request"], account="anthropic_api_c",
                                         router_account_id="credit:anthropic_api_c"), False, True),
        "subscription": (saved(plain, account="claude_e", router_account_id="claude_e"), True, False),
        "older subscription with no router id": (saved(plain, account="claude"), True, False),
    }
    got = {k: (X.cache_matches(m, sub, "K"), X.cache_matches(m, credit, "K")) for k, (m, *_) in shapes.items()}
    check("a credit answer written before the fable_harness key is still known as credit by the pool it names, "
          "and a subscription answer, old or new, is not",
          got == {k: tuple(v[1:]) for k, v in shapes.items()}, str(got))

    patched = {(X, n): getattr(X, n) for n in ("read_meta", "write_meta", "read_transcript", "paths_for")}
    patched |= {(L, n): getattr(L, n) for n in ("build_extraction_prompt", "transcript_id_from_path")}
    try:
        rec = {"text": "t", "leader_slug": "s", "source_id": "i"}
        X.read_transcript = lambda *a: rec
        L.build_extraction_prompt = lambda *a, **k: "PROMPT"
        X.write_meta = lambda p, m: None
        X.paths_for = lambda out, slug, sid: (out / "a.jsonl", out / "m.json")
        L.transcript_id_from_path = lambda p: "slug/sid"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            args = SimpleNamespace(dry_run=False, force=False, extractor="fable", verifier="gemini", timeout=1800,
                                   astra_model="a", gemini_model="g", fable_credit_pools="")
            job = {"args": args, "path": str(td / "x.json"), "out": td, "run_id": "run2", "exclusions": {},
                   "contract": {"contract_id": "c"}, "roster": {}, "spec": None, "schema_text": "",
                   "header_template": None, "workroot": td / "work", "router": None,
                   "release": {"release": "r"}, "code_revision": "c", "input_data_revision": "d"}
            # The pilot's shape: written on credit before 328566c, so its audit equals a subscription audit.
            pilot = X.stage_audit(job, "extract", {"transcript": rec, "roster_entry": None}, ["PROMPT"])
            X.read_meta = lambda p: {"extract": {"status": "ok", "contract_id": "c", "harness": "fable",
                                                 "account": "anthropic_api_e", "router_account_id": None,
                                                 "audit": pilot}, "verify": {"status": "not_run"}}
            as_sub = X.extract_one(job)
            args.fable_credit_pools = "anthropic_api_e"
            as_credit = X.extract_one(job)
    finally:
        for (mod, name), fn in patched.items():
            setattr(mod, name, fn)
    check("through extract_one: a subscription run refuses the pilot's credit answer as stale, and a credit run "
          "takes it as cached",
          as_sub.get("error_type") == L.E_CACHE_STALE and as_credit.get("status") == "cached", f"{as_sub} {as_credit}")

    print("\n[REVISION]")
    import subprocess
    real_repo = L.REPO
    with tempfile.TemporaryDirectory() as td:
        g = Path(td).resolve() / "repo"
        # Parts, not one "scripts/..." string, which test_script_references would read as a reference.
        for f in (Path("scripts", "a.py"), Path(".agents/skills/x/PROMPT.md"), Path("README.md")):
            (g / f).parent.mkdir(parents=True, exist_ok=True)
            (g / f).write_text("v1\n")
        (g / ".claude").mkdir()
        (g / ".claude" / "skills").symlink_to("../.agents/skills")
        git = lambda *a: subprocess.run(["git", "-C", str(g), *a], capture_output=True, text=True, check=True).stdout
        git("init", "-q")
        git("add", "-A")
        git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "init")
        head = git("rev-parse", "HEAD").strip()
        skill = g / ".claude" / "skills" / "x"
        try:
            L.REPO = g
            rev = lambda: X.code_revision_of(g / "scripts", skill)
            clean = rev()
            (g / "README.md").write_text("v2\n")
            elsewhere = rev()
            (g / ".agents/skills/x/PROMPT.md").write_text("v2\n")
            in_skill = rev()
            git("checkout", "-q", "--", ".agents/skills/x/PROMPT.md")
            (g / "scripts" / "new.py").write_text("x\n")
            untracked = rev()
            try:
                X.code_revision_of(Path(td))
                outside = "ran"
            except SystemExit as exc:
                outside = str(exc)
        finally:
            L.REPO = real_repo
    check("a clean tree records HEAD alone, and an edit outside scripts/ and the skill leaves it so",
          clean == head and elsewhere == head, f"{clean} {elsewhere} {head}")
    check("an edit inside the skill, reached through the .claude/skills link, marks the revision dirty",
          in_skill == head + "+dirty", in_skill)
    check("a new untracked file under scripts/ marks it dirty too", untracked == head + "+dirty", untracked)
    check("a path outside the repository stops the run", "outside" in outside, outside)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
