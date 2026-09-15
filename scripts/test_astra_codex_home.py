"""An Astra call must spawn in the Codex home the router chose.

Until this landed, `call_astra` passed no `env` and nothing in scripts/ ever set
CODEX_HOME, so every Astra call ran against whatever home the parent shell had.
The record still stored the account the ROUTER picked, and the two agreed only
by luck: the pinned llm-quota-router (0.1.1) cannot read a second Codex home, so
it only ever picked `codex`, which is also the shell default.

The live router (post-0.1.1) ranks `codex_b`. Raising the pin WITHOUT this fix
would book codex_b and spend codex, and every record would name an account that
did not serve the call. That is why this test exists before the pin moves.

It spawns nothing. It intercepts subprocess.run and asserts on the env.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grade  # noqa: E402
from extract_predictions import RouterUnavailable, route_from_selection  # noqa: E402

CHECKS = 0
FAILED: list[str] = []


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILED.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


class Launched(Exception):
    def __init__(self, kwargs):
        self.kwargs = kwargs


def spawn_env(fn, *a, **kw):
    """Call `fn`, intercept the spawn, return the env it asked for.

    A `call_astra` that does not accept `config_dir` is the PRE-FIX code, and
    this drops the argument and reports what that version actually spawns with,
    which is no env at all. The comparison then reads as a behavioural failure
    naming the missing CODEX_HOME, rather than as a TypeError that proves only
    that a signature changed. This repo's working agreement asks for exactly
    that distinction.
    """
    import inspect
    try:
        if "config_dir" not in inspect.signature(fn).parameters:
            kw.pop("config_dir", None)
    except (TypeError, ValueError):
        pass

    real = subprocess.run

    def stub(cmd, **kwargs):
        raise Launched(kwargs)

    subprocess.run = stub
    try:
        fn(*a, **kw)
    except Launched as exc:
        return exc.kwargs.get("env")
    except TypeError as exc:
        return f"call-refused:{exc}"
    finally:
        subprocess.run = real
    return "no-spawn"


# --- the regression: CODEX_HOME reaches the subprocess ----------------------

ACCOUNTS = [
    ("codex", "codex", "/Users/x/.codex", False),
    ("codex_b", "codex", "/Users/x/.codex-b", False),
    ("claude", "claude", "/Users/x/.claude", True),
]


def route_for(acct: str, provider: str = "codex") -> dict:
    return route_from_selection(
        {"decision": {"account": acct, "provider": provider, "fits": True}},
        ACCOUNTS, False)


r_b = route_for("codex_b")
check("route carries codex_b's home", r_b["config_dir"], "/Users/x/.codex-b")
check("route names codex_b", r_b["account_id"], "codex_b")
check("route resolves to astra", r_b["harness"], "astra")

r_a = route_for("codex")
check("route carries codex's home", r_a["config_dir"], "/Users/x/.codex")

with tempfile.TemporaryDirectory() as td:
    env = spawn_env(grade.call_astra, "prompt", 60, Path(td) / "jail",
                    config_dir=r_b["config_dir"])
    check("codex_b call exports its CODEX_HOME",
          (env or {}).get("CODEX_HOME"), "/Users/x/.codex-b")

with tempfile.TemporaryDirectory() as td:
    env = spawn_env(grade.call_astra, "prompt", 60, Path(td) / "jail",
                    config_dir=r_a["config_dir"])
    check("codex call exports its CODEX_HOME",
          (env or {}).get("CODEX_HOME"), "/Users/x/.codex")

# The two homes must not be the same string, or the test proves nothing.
check("the two homes differ", r_a["config_dir"] != r_b["config_dir"], True)

# --- inheriting is still possible, and is opt-in ----------------------------

with tempfile.TemporaryDirectory() as td:
    env = spawn_env(grade.call_astra, "prompt", 60, Path(td) / "jail")
    check("no config_dir means inherit the caller's env", env, None)

# --- the env is a copy, not a replacement -----------------------------------

import os  # noqa: E402

os.environ["ASTRA_TEST_SENTINEL"] = "kept"
try:
    with tempfile.TemporaryDirectory() as td:
        env = spawn_env(grade.call_astra, "prompt", 60, Path(td) / "jail",
                        config_dir="/Users/x/.codex-b")
        check("PATH survives", bool((env or {}).get("PATH")), True)
        check("unrelated vars survive", (env or {}).get("ASTRA_TEST_SENTINEL"), "kept")
finally:
    os.environ.pop("ASTRA_TEST_SENTINEL", None)

# --- an account the router does not know is refused, never defaulted --------

CHECKS += 1
try:
    route_for("codex_ghost")
    FAILED.append("an unknown codex account did not raise")
except RouterUnavailable:
    pass

# --- fable is untouched ------------------------------------------------------

r_f = route_for("claude", provider="claude")
check("fable still uses the default sentinel", r_f["config_dir"], "__DEFAULT__")
check("fable harness unchanged", r_f["harness"], "fable")

print(f"test_astra_codex_home: {CHECKS} checks, {len(FAILED)} failed")
for f in FAILED:
    print("  FAIL " + f)
sys.exit(1 if FAILED else 0)
