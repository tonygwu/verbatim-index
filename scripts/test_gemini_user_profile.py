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
argv, env = g.gemini_launch("user:tonyagents", cmd, {"HOME": "/h/default", "PATH": "/bin"}, wrapper="/w/agy-as-user")
check("a user profile goes through the root-owned wrapper, which takes the user then the argv",
      argv == ["sudo", "-n", "/w/agy-as-user", "tonyagents"] + cmd, str(argv))
check("and does not carry this shell's HOME, which would pick the wrong profile dir", "HOME" not in env)
check("the judge binary reaches the wrapper as an argument, so a drifting --agy-bin is visible to it",
      argv[4] == "agy")
check("the real command is untouched by the launch helper", g.gemini_command("p", "m", "agy", 60, Path("/x/l.log"))[0] == "agy")

print("jail")
with tempfile.TemporaryDirectory() as td:
    shared = Path(td) / "shared"
    j = g.gemini_jail("user:tonyagents", str(Path(td) / "work" / "job-1"), shared_root=shared)
    check("a user profile's jail is under the shared root, named after the job", j == shared / "job-1" and j.is_dir(), str(j))
    mode = stat.S_IMODE(os.stat(j).st_mode)
    check("the jail is group-writable with setgid, so the other user can write its log",
          mode & 0o070 == 0o070 and mode & stat.S_ISGID, oct(mode))
    check("so is the shared root", stat.S_IMODE(os.stat(shared).st_mode) & 0o2070 == 0o2070)
    # FOUND 2026-09-11: a dir under /Users/Shared inherits group wheel, and
    # chmod 2775 on it fails with EPERM because the operator is not in wheel.
    check("the jail is re-grouped to a group this process belongs to",
          os.stat(j).st_gid in os.getgroups(), f"gid {os.stat(j).st_gid} not in {os.getgroups()}")
    j2 = g.gemini_jail("/h/b", str(Path(td) / "work" / "job-2"))
    check("a HOME profile's jail is the workdir itself", j2 == Path(td) / "work" / "job-2" and j2.is_dir())

print("startup check")
class R:
    def __init__(self, rc, err=""): self.returncode, self.stderr, self.stdout = rc, err, ""
calls = []
def ok_runner(argv, **kw): calls.append(argv); return R(0)
def bad_runner(argv, **kw): calls.append(argv); return R(1, "sudo: a password is required")
g.check_user_profiles(["/h/default", "user:tonyagents"], binary="/usr/local/bin/agy", runner=ok_runner)
check("only user profiles are probed, through the wrapper, with the REAL binary, not /usr/bin/true",
      len(calls) == 1 and calls[0][:4] == ["sudo", "-n", g.GEMINI_USER_WRAPPER, "tonyagents"]
      and calls[0][4:] == ["/usr/local/bin/agy", "--help"], str(calls))
try:
    g.check_user_profiles(["user:tonyagents"], binary="agy", runner=bad_runner); raised = None
except SystemExit as e:
    raised = str(e)
check("a refused switch stops the pass before any job", raised is not None)
check("and the message names all three preconditions: readable binary, wrapper, live session",
      raised is not None and "NOPASSWD" in raised and "/usr/local/bin/agy" in raised
      and "agy_as_user.sh" in raised and "logged in" in raised, str(raised)[:400])
g.check_user_profiles(["/h/default"], runner=bad_runner)
check("HOME profiles never trigger the check", True)

print("wrapper script")
w = REPO / "scripts" / "agy_as_user.sh"
check("the wrapper exists and is executable", w.exists() and os.access(w, os.X_OK))
wsrc = w.read_text() if w.exists() else ""
check("it uses launchctl asuser, which is what reaches the other user's Keychain",
      "launchctl asuser" in wsrc)
check("it refuses a binary outside its allowlist", 'refusing to run' in wsrc and "ALLOWED_BINARY" in wsrc)
check("it refuses to run the judge as root", "refusing to run the judge as root" in wsrc)
check("it refuses a user with no login session, rather than timing out per call",
      "no active login session" in wsrc)
proc = subprocess.run(["/bin/sh", str(w), "nobody", "/bin/echo", "x"], capture_output=True, text=True)
check("a non-allowlisted binary is rejected without running anything",
      proc.returncode == 77 and "refusing to run" in proc.stderr, f"rc={proc.returncode} {proc.stderr[:120]}")
proc = subprocess.run(["/bin/sh", str(w)], capture_output=True, text=True)
check("no arguments prints usage", proc.returncode == 64 and "usage:" in proc.stderr)

print("wiring")
src = (REPO / "scripts" / "grade.py").read_text()
check("call_gemini launches through gemini_launch", "cmd, env = gemini_launch(profile_home," in src)
check("call_gemini jails through gemini_jail", "jail = gemini_jail(profile_home, workdir)" in src)
check("main checks user profiles before queueing, with the configured binary", "check_user_profiles(gem_profiles, args.agy_bin)" in src)
check("no bare HOME assignment survives in call_gemini",
      'env["HOME"] = profile_home' not in src.split("def call_gemini")[1].split("\ndef ")[0])
check("GEMINI_USERS is read from the environment, no name is hardcoded",
      'os.environ.get("GEMINI_USERS"' in src and "tonyagents" not in src.split("def agy_profiles")[1].split("\ndef ")[0])

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
