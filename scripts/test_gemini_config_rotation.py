#!/usr/bin/env python3
"""The Gemini rotation comes from the router config, and every call proves its account.

CHANGED 2026-10-04: the machine gained a second real Antigravity account. The
default macOS user serves tonygwu@gmail.com and the macOS user `tonyagents`
serves gptwufamily@gmail.com. Before this, the rotation was the default HOME
plus whatever GEMINI_USERS named, and the account a call reached was recorded
but never checked. Three rules follow, and each has a check here:

  1. The profile list is built from the llm-quota-router config: every enabled
     Antigravity account in the Gemini pool, with `macos_user` becoming
     `user:<macos_user>`. GEMINI_USERS may restate it but may not disagree.
  2. A call whose log names a different account than the config declares is an
     identity failure, not a grade. A running Antigravity desktop app can write
     a stale login back into the Keychain item that agy reads.
  3. The wrapper's exit 75 (that user has no login session) benches the profile
     for the run, loudly. Its exit 77 (wrong binary) stops the pass at preflight.

Pure checks: fake accounts, a fake subprocess, no sudo, no quota.

  .venv/bin/python scripts/test_gemini_config_rotation.py
"""
from __future__ import annotations
import importlib.util, json, math, sys
from pathlib import Path
from types import SimpleNamespace as NS

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))

spec = importlib.util.spec_from_file_location("g", REPO / "scripts" / "grade.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

def acct(id_, provider="antigravity", macos_user=None, email=None, env=None, enabled=True):
    return NS(id=id_, provider=provider, macos_user=macos_user, identity_email=email,
              env=env or {}, enabled=enabled)

# The shape of ~/.config/quota-router/config.toml on 2026-10-04, plus accounts
# of other providers that must be ignored. Deliberately NOT named tonyagents in
# every case, so a hardcoded name cannot pass.
MACHINE = {
    "claude": acct("claude", provider="claude", email="x@y"),
    "codex_b": acct("codex_b", provider="codex", email="x@y"),
    "antigravity_gemini": acct("antigravity_gemini", email="tonygwu@gmail.com"),
    "antigravity_claude": acct("antigravity_claude", email="tonygwu@gmail.com", env={"AGY_MODEL": "claude"}),
    "antigravity_gemini_b": acct("antigravity_gemini_b", macos_user="tonyagents", email="gptwufamily@gmail.com"),
    "antigravity_claude_b": acct("antigravity_claude_b", macos_user="tonyagents", email="gptwufamily@gmail.com",
                                 env={"AGY_MODEL": "claude"}),
}

def rotation(accounts, users_env=None):
    return g.gemini_rotation_from_config(accounts, default_home="/h/default", users_env=users_env)

def raises(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e)
    return None

print("1. the rotation is built from the router config")
r = rotation(MACHINE)
check("both Gemini-pool accounts, default HOME first, the macOS user as user:<name>",
      r == [("/h/default", "tonygwu@gmail.com", "antigravity_gemini"),
            ("user:tonyagents", "gptwufamily@gmail.com", "antigravity_gemini_b")], str(r))
check("the Claude pool (AGY_MODEL=claude) is not a Gemini profile, so no profile appears twice",
      len({p for p, _, _ in r}) == len(r) == 2, str(r))
other = {**MACHINE, "antigravity_gemini_b": acct("antigravity_gemini_b", macos_user="someoneelse",
                                                 email="z@gmail.com")}
check("the macOS user comes from the config, not from a name in the code",
      rotation(other)[1] == ("user:someoneelse", "z@gmail.com", "antigravity_gemini_b"), str(rotation(other)))
three = {**MACHINE, "antigravity_gemini_c": acct("antigravity_gemini_c", macos_user="third", email="c@gmail.com")}
check("a third account joins with no code change", [p for p, _, _ in rotation(three)]
      == ["/h/default", "user:tonyagents", "user:third"], str(rotation(three)))
off = {**MACHINE, "antigravity_gemini_b": acct("antigravity_gemini_b", macos_user="tonyagents",
                                               email="gptwufamily@gmail.com", enabled=False)}
check("a disabled account is not in the rotation", [p for p, _, _ in rotation(off)] == ["/h/default"])
check("GEMINI_USERS that restates the config is accepted",
      rotation(MACHINE, users_env="tonyagents") == r)
check("an empty GEMINI_USERS is the same as unset", rotation(MACHINE, users_env="") == r)
msg = raises(lambda: rotation(MACHINE, users_env="other"))
check("GEMINI_USERS naming a user the config lacks raises", msg is not None and "GEMINI_USERS" in msg, str(msg))
msg = raises(lambda: rotation(MACHINE, users_env="tonyagents,other"))
check("GEMINI_USERS naming an extra user raises", msg is not None, str(msg))
msg = raises(lambda: rotation(three, users_env="tonyagents"))
check("GEMINI_USERS missing a configured user raises too", msg is not None, str(msg))
noid = {**MACHINE, "antigravity_gemini_b": acct("antigravity_gemini_b", macos_user="tonyagents")}
msg = raises(lambda: rotation(noid))
check("an account with no identity_email raises: nothing could be verified against it",
      msg is not None and "identity_email" in msg, str(msg))
dup = {**MACHINE, "antigravity_gemini_x": acct("antigravity_gemini_x", email="q@gmail.com")}
msg = raises(lambda: rotation(dup))
check("two Gemini-pool accounts on one profile raise, because one Keychain item cannot be two accounts",
      msg is not None and "antigravity_gemini_x" in msg, str(msg))
msg = raises(lambda: rotation({"claude": MACHINE["claude"]}))
check("a config with no Antigravity account raises rather than running an empty arm", msg is not None, str(msg))

src = (REPO / "scripts" / "grade.py").read_text()
body = src.split("def gemini_rotation_from_config")[1].split("\ndef ")[0] if "def gemini_rotation_from_config" in src else ""
check("no macOS user name is hardcoded in the rotation", body and "tonyagents" not in body)
check("main builds the rotation from the config, through the shared preflight",
      "gemini_rotation_preflight(" in src.split("def main")[1]
      and "gemini_rotation_from_config(" in src.split("def gemini_rotation_preflight")[1].split("\ndef ")[0])

print("2. a call whose log names another account is an identity failure")
check("the taxonomy has an identity label", hasattr(g, "E_IDENTITY") and g.E_IDENTITY in g.ALL_ERROR_TYPES)

def fake_agy(log_email, rc=0, stdout=None):
    """A subprocess.run stand-in: writes the call's own --log-file, then answers."""
    def run(argv, **kw):
        log_path = Path(argv[argv.index("--log-file") + 1])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("server.go:1595] Language server version: 1.2.0\n"
                            + (f"ChainedAuth: authenticated via keyring\nuser {log_email}\n" if log_email else "no address\n"))
        out = stdout if stdout is not None else "\n".join(json.dumps(e) for e in [
            {"event": "init", "init": {"model": g.GEMINI_MODEL}},
            {"event": "result", "result": {"status": "SUCCESS", "response": "{\"ok\": 1}",
                                           "usage": {"thinking_tokens": 5}}}])
        return NS(returncode=rc, stdout=out, stderr="")
    return run

import tempfile
real_run = g.subprocess.run
with tempfile.TemporaryDirectory() as td:
    try:
        g.subprocess.run = fake_agy("tonygwu@gmail.com")
        text, tel = g.call_gemini("p", "/h/default", 120, workdir=str(Path(td) / "w1"),
                                  expected_identity="tonygwu@gmail.com")
        check("a matching identity returns the grade and says it was verified",
              tel.get("profile_identity") == "tonygwu@gmail.com" and tel.get("profile_identity_verified") is True, str(tel))
        g.subprocess.run = fake_agy("gptwufamily@gmail.com")
        try:
            g.call_gemini("p", "/h/default", 120, workdir=str(Path(td) / "w2"),
                          expected_identity="tonygwu@gmail.com"); err = None
        except RuntimeError as e:
            err = str(e)
        check("a mismatch raises, labelled as an identity failure",
              err is not None and g.classify_exception_detail(err) == getattr(g, "E_IDENTITY", "?"), str(err))
        check("and the message names both addresses",
              err is not None and "gptwufamily@gmail.com" in err and "tonygwu@gmail.com" in err, str(err))
        g.subprocess.run = fake_agy(None)
        try:
            g.call_gemini("p", "/h/default", 120, workdir=str(Path(td) / "w3"),
                          expected_identity="tonygwu@gmail.com"); err = None
        except RuntimeError as e:
            err = str(e)
        check("a log that names no account cannot prove the account, so it fails too",
              err is not None and g.classify_exception_detail(err) == getattr(g, "E_IDENTITY", "?"), str(err))

        print("3. wrapper exit 75 benches the profile for the run; 77 stops the pass")
        g._GEMINI_BENCH.clear()
        g.subprocess.run = fake_agy(None, rc=75, stdout="")
        shared = Path(td) / "shared"
        orig_jail = g.gemini_jail
        g.gemini_jail = lambda p, w, shared_root=shared: orig_jail(p, w, shared_root=shared)
        try:
            g.call_gemini("p", "user:someone", 120, workdir=str(Path(td) / "w4"),
                          expected_identity="z@gmail.com"); err = None
        except RuntimeError as e:
            err = str(e)
        finally:
            g.gemini_jail = orig_jail
        check("a call that meets exit 75 fails as auth_or_quota and says the Keychain is locked",
              err is not None and g.classify_exception_detail(err) == g.E_AUTH and "login session" in err, str(err))
        check("and the profile is benched for the rest of the run",
              math.isinf(g._GEMINI_BENCH.get("user:someone", 0.0)), str(g._GEMINI_BENCH))
        check("so the round-robin steps around it",
              g.pick_gemini_profile("user:someone", ["/h/default", "user:someone"]) == "/h/default")
        g._GEMINI_BENCH.clear()
    finally:
        g.subprocess.run = real_run

class R:
    def __init__(self, rc, err=""): self.returncode, self.stderr, self.stdout = rc, err, ""
g._GEMINI_BENCH.clear()
benched = g.check_user_profiles(["/h/default", "user:someone"], binary="/usr/local/bin/agy",
                                runner=lambda argv, **kw: R(75, "has no active login session"))
check("preflight: exit 75 does not stop the pass", True)
check("preflight: it benches that profile for the run and reports it",
      benched == ["user:someone"] and math.isinf(g._GEMINI_BENCH.get("user:someone", 0.0)), f"{benched} {g._GEMINI_BENCH}")
g._GEMINI_BENCH.clear()
msg = raises(lambda: g.check_user_profiles(["user:someone"], binary="/usr/local/bin/agy",
                                           runner=lambda argv, **kw: R(75, "no active login session")))
check("preflight: if 75 benches every profile, the pass stops instead of failing every call",
      msg is not None, str(msg))
g._GEMINI_BENCH.clear()
msg = raises(lambda: g.check_user_profiles(["/h/default", "user:someone"], binary="agy",
                                           runner=lambda argv, **kw: R(77, "refusing to run 'agy'")))
check("preflight: exit 77 stops the pass and names the binary the wrapper runs",
      msg is not None and "--agy-bin /usr/local/bin/agy" in msg and "77" in msg, str(msg))

loop = (REPO / "scripts" / "grade_loop.sh").read_text()
check("grade_loop.sh passes the wrapper's binary, or the config-derived rotation stops every cycle at preflight",
      '--agy-bin "$AGY_BIN"' in loop and 'AGY_BIN="${AGY_BIN:-/usr/local/bin/agy}"' in loop)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
