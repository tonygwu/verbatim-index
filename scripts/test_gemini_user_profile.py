#!/usr/bin/env python3
"""A Gemini profile may be a macOS USER, because two HOMEs share one Keychain.

MEASURED 2026-09-10: every Gemini grade in the corpus came from one account
although two profile HOMEs alternated, because `agy` keeps its token in one
Keychain item per macOS user. A `user:<name>` profile runs the call as that
user under `sudo -n -u <name> -H`, in a jail both users can write. Pure checks,
no sudo, no quota.

  .venv/bin/python scripts/test_gemini_user_profile.py
"""
from __future__ import annotations
import importlib.util, os, stat, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))

spec = importlib.util.spec_from_file_location("g", REPO / "scripts" / "grade.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

print("profiles")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "agy-homes"; (root / "b" / ".gemini" / "antigravity-cli").mkdir(parents=True)
    (root / "b" / ".gemini" / "antigravity-cli" / "antigravity-oauth-token").write_text("{}")
    homes = g.agy_profiles(root=root, default_home="/h/default", users="tonyagents, other")
    check("HOME profiles come first, then one user profile per GEMINI_USERS name",
          homes == ["/h/default", str(root / "b"), "user:tonyagents", "user:other"], str(homes))
    check("no users means no user profiles", g.agy_profiles(root=root, default_home="/h/default", users="") == ["/h/default", str(root / "b")])
    check("a user profile is recognised", g.is_user_profile("user:tonyagents") and not g.is_user_profile("/h/default"))
    check("labels", g.profile_label("user:tonyagents") == "user:tonyagents" and g.profile_label("/h/default") == "default"
          and g.profile_label(str(root / "b")) == "b")

print("launch")
cmd = ["agy", "-p", "hi", "--log-file", "/x/agy-cli.log"]
argv, env = g.gemini_launch("/h/b", cmd, {"HOME": "/h/default", "PATH": "/bin"})
check("a HOME profile sets HOME and leaves argv alone", argv == cmd and env["HOME"] == "/h/b")
argv, env = g.gemini_launch("user:tonyagents", cmd, {"HOME": "/h/default", "PATH": "/bin"})
check("a user profile prefixes sudo -n -u <user> -H", argv[:5] == ["sudo", "-n", "-u", "tonyagents", "-H"] and argv[5:] == cmd, str(argv))
check("and does not carry this shell's HOME", "HOME" not in env)
check("the real command is untouched by the launch helper", g.gemini_command("p", "m", "agy", 60, Path("/x/l.log"))[0] == "agy")

print("jail")
with tempfile.TemporaryDirectory() as td:
    shared = Path(td) / "shared"
    j = g.gemini_jail("user:tonyagents", str(Path(td) / "work" / "job-1"), shared_root=shared)
    check("a user profile's jail is under the shared root, named after the job", j == shared / "job-1" and j.is_dir(), str(j))
    mode = stat.S_IMODE(os.stat(j).st_mode)
    check("the jail is group-writable with setgid, so the other staff user can write the log",
          mode & 0o070 == 0o070 and mode & stat.S_ISGID, oct(mode))
    check("so is the shared root", stat.S_IMODE(os.stat(shared).st_mode) & 0o2070 == 0o2070)
    j2 = g.gemini_jail("/h/b", str(Path(td) / "work" / "job-2"))
    check("a HOME profile's jail is the workdir itself", j2 == Path(td) / "work" / "job-2" and j2.is_dir())

print("startup check")
class R:
    def __init__(self, rc, err=""): self.returncode, self.stderr, self.stdout = rc, err, ""
calls = []
def ok_runner(argv, **kw): calls.append(argv); return R(0)
def bad_runner(argv, **kw): calls.append(argv); return R(1, "sudo: a password is required")
g.check_user_profiles(["/h/default", "user:tonyagents"], runner=ok_runner)
check("only user profiles are probed, with sudo -n and /usr/bin/true",
      calls == [["sudo", "-n", "-u", "tonyagents", "-H", "/usr/bin/true"]], str(calls))
try:
    g.check_user_profiles(["user:tonyagents"], runner=bad_runner); raised = None
except SystemExit as e:
    raised = str(e)
check("a refused switch stops the pass before any job", raised is not None)
check("and the message names the sudoers rule", raised is not None and "NOPASSWD" in raised and "sudoers.d/agy-tonyagents" in raised, str(raised)[:200])
g.check_user_profiles(["/h/default"], runner=bad_runner)
check("HOME profiles never trigger the check", True)

print("wiring")
src = (REPO / "scripts" / "grade.py").read_text()
check("call_gemini launches through gemini_launch", "cmd, env = gemini_launch(profile_home," in src)
check("call_gemini jails through gemini_jail", "jail = gemini_jail(profile_home, workdir)" in src)
check("main checks user profiles before queueing", "check_user_profiles(gem_profiles)" in src)
check("no bare HOME assignment survives in call_gemini",
      'env["HOME"] = profile_home' not in src.split("def call_gemini")[1].split("\ndef ")[0])
check("GEMINI_USERS is read from the environment, no name is hardcoded",
      'os.environ.get("GEMINI_USERS"' in src and "tonyagents" not in src.split("def agy_profiles")[1].split("\ndef ")[0])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
