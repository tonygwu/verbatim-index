#!/usr/bin/env python3
"""Every Fable `claude -p` harness gives its child the 128,000-token output cap (VI-42).

VI-23 raised the cap through `credit_run.child_env` for `credit_run.run` and
`grade.call_fable` only. Four other harnesses copied the environment as it was,
so their children ran at the CLI's 64,000 default and a long answer came back
cut: the dater (`date_recordings.call_fable_web`), the P6b speaker drafts
(`pundits_speaker_infer.call_model`), and two probes. Each is called here with
its subprocess replaced by a recorder, which stops the call after reading the
environment the child would get. The recorder plays the fake `claude` the item
asks for: it sees exactly what the child process would.

  .venv/bin/python scripts/test_fable_child_env.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import credit_run as CR  # noqa: E402
import date_recordings as DR  # noqa: E402
import p3_judge_probe as P3  # noqa: E402
import pundits_speaker_infer as PSI  # noqa: E402
import speaker_segment_probe as SSP  # noqa: E402

FAILED: list[str] = []
CAP = str(CR.FABLE_MAX_OUTPUT_TOKENS)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


class Stop(Exception):
    """Raised by the recorder once it has the child's environment."""


def recorder(seen: list[dict]):
    def run(cmd, **kw):
        seen.append(dict(kw.get("env") or {}))
        raise Stop()
    return run


def child_env_of(call) -> dict:
    """The environment `call` would hand its child, with subprocess.run replaced by the recorder."""
    seen: list[dict] = []
    real = subprocess.run
    subprocess.run = recorder(seen)
    try:
        call(recorder(seen))
    except Stop:
        pass
    finally:
        subprocess.run = real
    if not seen:
        raise AssertionError("the harness never started a child")
    return seen[0]


def main() -> int:
    # A value already in the caller's environment must not survive: the cap is set over it.
    os.environ[CR.MAX_OUTPUT_TOKENS_ENV] = "64000"
    with tempfile.TemporaryDirectory() as t:
        td = Path(t).resolve()
        cfg = str(td / "config")
        cases = {
            "date_recordings.call_fable_web": lambda r: DR.call_fable_web(
                "P", cfg, 5, workdir=str(td / "dating"), runner=r),
            "pundits_speaker_infer.call_model": lambda r: PSI.call_model("P", "fable", cfg, timeout=5),
            "speaker_segment_probe.call_claude": lambda r: SSP.call_claude(
                "P", "claude-fable-5-1", cfg, td / "seg", td / "seg-raw.json"),
            "p3_judge_probe.run_fable": lambda r: P3.run_fable("P", td, "(version 1)", cfg, 5),
        }
        for name, call in cases.items():
            env = child_env_of(call)
            check(f"{name}: the child gets {CR.MAX_OUTPUT_TOKENS_ENV}={CAP}",
                  env.get(CR.MAX_OUTPUT_TOKENS_ENV) == CAP, f"got {env.get(CR.MAX_OUTPUT_TOKENS_ENV)!r}")
            check(f"{name}: the child keeps its account's CLAUDE_CONFIG_DIR",
                  env.get("CLAUDE_CONFIG_DIR") == cfg, f"got {env.get('CLAUDE_CONFIG_DIR')!r}")

    print()
    print(f"FAILED: {len(FAILED)} failing check(s)" if FAILED else "OK: 0 failing check(s)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
