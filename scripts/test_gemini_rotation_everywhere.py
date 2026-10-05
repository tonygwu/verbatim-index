#!/usr/bin/env python3
"""Every script that calls the Gemini judge uses the config rotation, and every call records its agy version.

CHANGED 2026-10-04. 8275e2f gave grade.py a rotation built from the
llm-quota-router config, a preflight for the wrapper's exits 75 and 77, and an
identity check on every call. date_recordings.py, extract_predictions.py and
market_consensus.py kept the old agy_profiles(): default HOME plus GEMINI_USERS,
no preflight, no identity check, and --agy-bin "agy", which the agy-as-user
wrapper refuses with exit 77. This test pins three rules:

  1. All four scripts build the rotation through one helper,
     grade.gemini_rotation_preflight(), and pass expected_identity on every
     call_gemini. Their --agy-bin default is /usr/local/bin/agy.
  2. Every Gemini call records `agy_version`, read from that call's own
     --log-file ("Language server version: X"). A log with no version line, or
     two different versions, fails the call as agy_version_unreadable rather
     than writing an answer with no provenance. The binary's mtime is never read.
  3. The preflight header prints each profile's version, as `agy --version`
     reports it through that profile's own launch path.

Pure checks: fake subprocesses, no sudo, no quota.

  .venv/bin/python scripts/test_gemini_rotation_everywhere.py
"""
from __future__ import annotations
import importlib.util, io, json, re, sys, tempfile, contextlib
from pathlib import Path
from types import SimpleNamespace as NS

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))

import grade as g  # noqa: E402
import extract_predictions as EP  # noqa: E402
import market_consensus as MC  # noqa: E402
import date_recordings as DR  # noqa: E402

E_VER = getattr(g, "E_AGY_VERSION", None)
WRAPPER_BIN = g.AGY_JUDGE_BIN if hasattr(g, "AGY_JUDGE_BIN") else "/usr/local/bin/agy"

def acct(id_, macos_user=None, email=None, env=None):
    return NS(id=id_, provider="antigravity", macos_user=macos_user, identity_email=email,
              env=env or {}, enabled=True)
MACHINE = {
    "antigravity_gemini": acct("antigravity_gemini", email="a@gmail.com"),
    "antigravity_claude": acct("antigravity_claude", email="a@gmail.com", env={"AGY_MODEL": "claude"}),
    "antigravity_gemini_b": acct("antigravity_gemini_b", macos_user="second", email="b@gmail.com"),
}

print("1. the agy version is read from the call's own log")
fn = getattr(g, "agy_version_from_log", None)
check("grade.agy_version_from_log exists", fn is not None)
check("the taxonomy has an agy-version label", E_VER is not None and E_VER in g.ALL_ERROR_TYPES)
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    real = td / "real.log"
    real.write_text("I1004 22:57:18.478391      39 server.go:1595] Language server version: 1.2.0\n"
                    "ChainedAuth: authenticated via keyring\nuser a@gmail.com\n")
    check("reads the version off a real-shaped log line", fn is not None and fn(real) == "1.2.0")
    newer = td / "newer.log"
    newer.write_text("I1003 04:21:20.327141      38 server.go:1663] Language server version: 1.2.16\n")
    check("a later build's line, another server.go line number, still reads", fn is not None and fn(newer) == "1.2.16")
    for label, body in (("no version line", "user a@gmail.com\n"),
                        ("two different versions", "Language server version: 1.2.0\nLanguage server version: 1.2.16\n")):
        p = td / f"{label}.log"; p.write_text(body)
        try:
            fn(p); err = None
        except RuntimeError as e:
            err = str(e)
        except Exception as e:  # noqa: BLE001
            err = f"wrong exception {type(e).__name__}: {e}"
        check(f"a log with {label} fails, labelled agy_version_unreadable",
              err is not None and E_VER is not None and g.classify_exception_detail(err) == E_VER, str(err))
    try:
        fn(td / "absent.log"); err = None
    except Exception as e:  # noqa: BLE001
        err = str(e)
    check("a missing log fails with the same label", err is not None and E_VER is not None
          and g.classify_exception_detail(err) == E_VER, str(err))
    src = (REPO / "scripts" / "grade.py").read_text()
    body = src.split("def agy_version_from_log")[1].split("\ndef ")[0] if fn else ""
    check("the version reader never consults mtime", fn is not None and "mtime" not in body.replace("never", "")
          and "st_" not in body and "getmtime" not in body)

def fake_agy(email, version_line):
    def run(argv, **kw):
        log_path = Path(argv[argv.index("--log-file") + 1])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text((version_line or "") + f"ChainedAuth: authenticated via keyring\nuser {email}\n")
        out = "\n".join(json.dumps(e) for e in [
            {"event": "init", "init": {"model": g.GEMINI_MODEL}},
            {"event": "result", "result": {"status": "SUCCESS", "response": "{\"ok\": 1}",
                                           "usage": {"thinking_tokens": 5}}}])
        return NS(returncode=0, stdout=out, stderr="")
    return run

real_run = g.subprocess.run
with tempfile.TemporaryDirectory() as td:
    try:
        g.subprocess.run = fake_agy("a@gmail.com", "x server.go:1595] Language server version: 1.2.0\n")
        _, tel = g.call_gemini("p", "/h/default", 120, workdir=str(Path(td) / "w1"), expected_identity="a@gmail.com")
        check("call_gemini records agy_version in its telemetry", tel.get("agy_version") == "1.2.0", str(tel))
        g.subprocess.run = fake_agy("a@gmail.com", None)
        try:
            g.call_gemini("p", "/h/default", 120, workdir=str(Path(td) / "w2"), expected_identity="a@gmail.com"); err = None
        except RuntimeError as e:
            err = str(e)
        check("a call whose log has no version line fails, not a silent None",
              err is not None and E_VER is not None and g.classify_exception_detail(err) == E_VER, str(err))
    finally:
        g.subprocess.run = real_run

print("2. one preflight helper: rotation, exits 75/77, and each profile's version in the header")
pre = getattr(g, "gemini_rotation_preflight", None)
check("grade.gemini_rotation_preflight exists", pre is not None)

def version_runner(versions, rc=None):
    seen = []
    def run(argv, **kw):
        seen.append(list(argv))
        user = argv[argv.index(g.GEMINI_USER_WRAPPER) + 1] if g.GEMINI_USER_WRAPPER in argv else "default"
        if rc and user in rc:
            return NS(returncode=rc[user], stdout="", stderr="no session")
        return NS(returncode=0, stdout=versions[user] + "\n" if "--version" in argv else "usage", stderr="")
    return run, seen

if pre is not None:
    g._GEMINI_BENCH.clear()
    run, seen = version_runner({"default": "1.2.0", "second": "1.2.0"})
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf), contextlib.redirect_stdout(err_buf):
        rot = pre(WRAPPER_BIN, accounts=MACHINE, default_home="/h/default", runner=run)
    out = err_buf.getvalue()
    check("returns the profiles and the identity each must prove",
          rot.profiles == ["/h/default", "user:second"]
          and rot.identities == {"/h/default": "a@gmail.com", "user:second": "b@gmail.com"}
          and rot.accounts == {"/h/default": "antigravity_gemini", "user:second": "antigravity_gemini_b"}, str(rot))
    check("reads each profile's version through that profile's own launch",
          rot.versions == {"/h/default": "1.2.0", "user:second": "1.2.0"}
          and any(g.GEMINI_USER_WRAPPER in a and "--version" in a for a in seen), f"{rot.versions} {seen}")
    check("the header names each profile, its account and its version",
          "user:second" in out and "b@gmail.com" in out and "agy 1.2.0" in out and "/h/default" in out, out)
    g._GEMINI_BENCH.clear()
    run, _ = version_runner({"default": "1.2.0", "second": "1.2.0"}, rc={"second": 75})
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        rot = pre(WRAPPER_BIN, accounts=MACHINE, default_home="/h/default", runner=run)
    check("exit 75 benches the profile and reports it, with no version to read",
          rot.benched == ["user:second"] and "user:second" not in rot.versions, str(rot))
    g._GEMINI_BENCH.clear()
    run, _ = version_runner({"default": "1.2.0", "second": "1.2.0"}, rc={"second": 77})
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            pre("agy", accounts=MACHINE, default_home="/h/default", runner=run); msg = None
    except SystemExit as e:
        msg = str(e)
    check("exit 77 stops before any call", msg is not None and "77" in msg, str(msg))
    g._GEMINI_BENCH.clear()
    run, _ = version_runner({"default": "", "second": "1.2.0"})
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            pre(WRAPPER_BIN, accounts=MACHINE, default_home="/h/default", runner=run); msg = None
    except SystemExit as e:
        msg = str(e)
    check("a profile whose --version prints nothing stops the pass", msg is not None, str(msg))
    run, _ = version_runner({"default": "1.2.0", "second": "1.2.0"})
    with contextlib.redirect_stderr(io.StringIO()):
        rot = pre(WRAPPER_BIN, accounts=MACHINE, default_home="/h/default", runner=run, select="antigravity_gemini_b")
    check("a selection narrows the rotation by profile or account id", rot.profiles == ["user:second"], str(rot))
    g._GEMINI_BENCH.clear()

print("3. the three prediction scripts")
for name, mod in (("date_recordings", DR), ("extract_predictions", EP), ("market_consensus", MC)):
    src = (REPO / "scripts" / f"{name}.py").read_text()
    check(f"{name}: agy_profiles() is gone", "agy_profiles" not in src)
    check(f"{name}: uses gemini_rotation_preflight", "gemini_rotation_preflight(" in src)
    check(f"{name}: --agy-bin defaults to the wrapper's binary",
          mod.build_parser().parse_args(["--run-dir", "x"] if name == "date_recordings" else []).agy_bin == WRAPPER_BIN)

print("3b. every script that takes --agy-bin")
# FOUND 2026-10-04: eval_prediction_cases.py was not one of the three above, but
# its --live dating reaches date_recordings.call_agent with ITS OWN args, whose
# --agy-bin still defaulted to "agy". The rotation's preflight then stopped every
# live dating eval with wrapper exit 77. A list of known callers missed it, so
# this scans every script that declares the flag.
import eval_prediction_cases as EPC  # noqa: E402
check("eval_prediction_cases: --agy-bin defaults to the wrapper's binary",
      EPC.build_parser().parse_args(["--gold", "x"]).agy_bin == WRAPPER_BIN)
_flag = re.compile(r'add_argument\(\s*"--agy-bin"\s*,\s*default\s*=\s*([^,)\n]+)')
for path in sorted((REPO / "scripts").glob("*.py")):
    for m in _flag.finditer(path.read_text()):
        raw = m.group(1).strip()
        ok = raw.endswith("AGY_JUDGE_BIN") or raw.strip("\"'") == WRAPPER_BIN
        check(f"{path.name}: --agy-bin default {raw} is the wrapper's binary", ok)

captured = {}
def fake_call_gemini(prompt, home, timeout, **kw):
    captured.update(kw, home=home)
    return "{}", {"profile_identity": kw.get("expected_identity"), "agy_version": "1.2.0",
                  "served_model": g.GEMINI_MODEL, "served_model_verified": True, "requested_model": g.GEMINI_MODEL}

orig = EP.call_gemini
try:
    EP.call_gemini = fake_call_gemini
    route = {"harness": "gemini", "profile_home": "user:second", "expected_identity": "b@gmail.com",
             "account_id": "antigravity_gemini_b"}
    args = NS(gemini_model=g.GEMINI_MODEL, agy_bin=WRAPPER_BIN)
    _, tel, who = EP.call_harness(route, "p", 10, Path(tempfile.gettempdir()), args)
    check("extract_predictions: call_harness passes expected_identity and the binary",
          captured.get("expected_identity") == "b@gmail.com" and captured.get("binary") == WRAPPER_BIN, str(captured))
finally:
    EP.call_gemini = orig

rot = getattr(g, "GeminiRotation", None)
if rot is not None:
    r = EP.Router.__new__(EP.Router)
    r.accounts = [("antigravity_gemini", "antigravity", None, False), ("antigravity_gemini_b", "antigravity", None, False)]
    r.exclude_ids, r.allow_degraded, r._n = [], False, 0
    import threading
    r._lock = threading.Lock()
    r.gemini = rot(profiles=["/h/default", "user:second"], identities={"/h/default": "a@gmail.com",
                   "user:second": "b@gmail.com"}, benched=[], versions={},
                   accounts={"/h/default": "antigravity_gemini", "user:second": "antigravity_gemini_b"})
    r._select = lambda **kw: NS(to_dict=lambda: {"selected": "antigravity_gemini"})
    orig_route = EP.route_from_selection
    try:
        EP.route_from_selection = lambda sel, accounts, deg: {"harness": "gemini", "account_id": "antigravity_gemini",
                                                               "config_dir": None}
        picks = [r.pick(None, None) for _ in range(2)]
    finally:
        EP.route_from_selection = orig_route
    check("extract_predictions: Router puts each profile's expected identity on its route",
          sorted((p["profile_home"], p["expected_identity"]) for p in picks)
          == [("/h/default", "a@gmail.com"), ("user:second", "b@gmail.com")], str(picks))
    # The quota router picked antigravity_gemini both times, and round-robin sent
    # the second call to user:second. The record must name the account that
    # served, not the one the router reserved.
    check("extract_predictions: a route's account_id is the account of the profile it calls",
          sorted((p["profile_home"], p["account_id"]) for p in picks)
          == [("/h/default", "antigravity_gemini"), ("user:second", "antigravity_gemini_b")], str(picks))

check("extract_predictions: a fable-only run never preflights Gemini",
      EP.gemini_reachable([("antigravity_gemini", "antigravity", None, False)], [], ["fable"]) is False
      if hasattr(EP, "gemini_reachable") else False)
check("extract_predictions: an excluded Gemini account is not reachable",
      EP.gemini_reachable([("antigravity_gemini", "antigravity", None, False)], ["antigravity_gemini"], ["auto"]) is False
      if hasattr(EP, "gemini_reachable") else False)
check("extract_predictions: an auto pin with an eligible Gemini account is reachable",
      EP.gemini_reachable([("antigravity_gemini", "antigravity", None, False)], [], ["auto"]) is True
      if hasattr(EP, "gemini_reachable") else False)

orig_g = DR.G if hasattr(DR, "G") else None
import grade as G2
orig_cg, orig_pre = G2.call_gemini, getattr(G2, "gemini_rotation_preflight", None)
try:
    captured.clear()
    G2.call_gemini = fake_call_gemini
    G2.gemini_rotation_preflight = lambda binary, **kw: g.GeminiRotation(
        profiles=["user:second"], identities={"user:second": "b@gmail.com"}, benched=[], versions={"user:second": "1.2.0"},
        accounts={"user:second": "antigravity_gemini_b"})
    DR._gemini_rotation = None
    args = NS(gemini_model=g.GEMINI_MODEL, agy_bin=WRAPPER_BIN)
    _, tel, who = DR.call_agent("gemini", "p", 10, Path(tempfile.mkdtemp()), args, 0)
    check("date_recordings: call_agent passes expected_identity",
          captured.get("expected_identity") == "b@gmail.com" and captured.get("home") == "user:second", str(captured))
except Exception as e:  # noqa: BLE001
    check("date_recordings: call_agent passes expected_identity", False, f"{type(e).__name__}: {e}")
finally:
    G2.call_gemini = orig_cg
    if orig_pre is not None:
        G2.gemini_rotation_preflight = orig_pre
    DR._gemini_rotation = None

dsrc = (REPO / "scripts" / "date_recordings.py").read_text()
check("date_recordings: a proposal's telemetry keeps agy_version", '"agy_version"' in dsrc.split("def propose_one")[1])

prov = {"harness": "gemini", "requested_model": "g", "served_model": "g", "served_model_verified": True, "account": "b@gmail.com"}
block = MC.matcher_block(prov, {"agy_version": "1.2.0"}, {"contract_id": "c"}, "run") if hasattr(MC, "matcher_block") else {}
check("market_consensus: the matcher block records agy_version for a Gemini match", block.get("agy_version") == "1.2.0", str(block))
block_f = MC.matcher_block({**prov, "harness": "fable"}, {}, {"contract_id": "c"}, "run") if hasattr(MC, "matcher_block") else {"agy_version": 1}
check("market_consensus: a non-Gemini match carries no agy_version key", "agy_version" not in block_f, str(block_f))
import predictions_lib as L
schema = L.load_record_schema() if hasattr(L, "load_record_schema") else json.loads(
    (L.SKILL / L.RECORD_SCHEMA).read_text())
mprops = schema["properties"]["consensus"]["anyOf"][1]["properties"]["matcher"]["anyOf"][1]
check("record schema: matcher.agy_version is allowed and optional",
      "agy_version" in mprops["properties"] and "agy_version" not in mprops["required"], json.dumps(mprops)[:300])

print("4. a Gemini extraction or verification keeps agy_version on the meta file, even with no record written")
# FOUND in the 2026-10-04 smoke: both calls returned no candidates, so no record
# carried the call's telemetry and the meta file named the account but not the
# agy build. The meta file is the only trace of such a call.
from unittest.mock import Mock, patch
from test_predictions_policy import PolicyTests
from test_predictions_driver import cand
t = PolicyTests("test_shared_policy_changes_both_contracts"); t.setUp()
try:
    t.job["router"] = Mock()
    t.job["router"].pick.return_value = {"harness": "gemini", "account_id": "antigravity_gemini_b"}
    gem_tel = {"requested_model": g.GEMINI_MODEL, "served_model": g.GEMINI_MODEL, "served_model_verified": True,
               "profile_identity": "b@gmail.com", "agy_version": "1.2.0"}
    def ext_obj(cands):
        return {"schema_version": "1", "transcript_id": "ada/s1", "attribution_notes": "",
                "subject_speech_share_estimate_pct": 100, "candidates_considered": 1, "cap_hit": False,
                "estimated_total_qualifying": len(cands),
                "statement_date_doubt": {"doubt": "none", "evidence": None, "evidence_year": None},
                "candidates": cands}
    t.args.extractor = "gemini"
    with patch.object(EP, "call_harness", return_value=(json.dumps(ext_obj([])), gem_tel, "b@gmail.com")):
        r = EP.extract_one(t.job)
    _, mp = EP.paths_for(t.out, "ada", "s1")
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    check("an empty Gemini extraction records agy_version on the meta file",
          r.get("status") == "ok" and meta.get("extract", {}).get("agy_version") == "1.2.0", f"{r} {meta.get('extract')}")
    t.args.force = True
    with patch.object(EP, "call_harness", return_value=(json.dumps(ext_obj(
            [cand("I think by 2030 most code will be written by AI", claim_form="simple")])), gem_tel, "b@gmail.com")):
        EP.extract_one(t.job)
    t.args.force = False
    rp, _ = EP.paths_for(t.out, "ada", "s1")
    import predictions_lib as L2
    rec = L2.parse_lines(rp.read_text(), str(rp))[0]
    check("a Gemini record's extraction telemetry carries agy_version",
          rec["extraction"]["telemetry"].get("agy_version") == "1.2.0", str(rec["extraction"]["telemetry"])[:200])
    # Verification needs a different harness from extraction, so re-extract with Astra.
    t.args.force = True
    t.extract()
    t.args.force = False
    rec = L2.parse_lines(rp.read_text(), str(rp))[0]
    vjob = t.verifier_job()
    vjob["router"].pick.return_value = {"harness": "gemini", "account_id": "antigravity_gemini"}
    t.args.verifier = "auto"
    verdict = {"prediction_id": rec["prediction_id"], "attribution": "subject",
               "gates": {k: True for k in L2.GATES}, "claim_faithful": True, "confidence_type_seen": "none",
               "qualifies": True, "resolution_criteria": "By 2030, most code is AI-written.", "notes": None}
    vobj = {"schema_version": "1", "transcript_id": "ada/s1", "verdicts": [verdict],
            "statement_date_doubt": {"doubt": "none", "evidence": None, "evidence_year": None}}
    vtel = {**gem_tel, "agy_version": "1.2.16", "profile_identity": "a@gmail.com"}
    with patch.object(EP, "call_harness", return_value=(json.dumps(vobj), vtel, "a@gmail.com")):
        vr = EP.verify_one(vjob)
    meta = json.loads(mp.read_text())
    check("a Gemini verification records each batch's agy_version on the meta file",
          meta.get("verify", {}).get("agy_versions") == ["1.2.16"], f"{vr} {meta.get('verify')}")
finally:
    t.tmp.cleanup()

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
