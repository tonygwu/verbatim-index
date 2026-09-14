#!/usr/bin/env python3
"""A fake judge run under the real pundits sandbox cannot read, list, write or shell into the container.

Pundits plan, Verification. The judges' own tool calls cannot be triggered in a
test without spending quota, so a shell script stands in for a judge that tries
everything a tool-using judge could: read the roster canary with cat, list the
container, write a file into it, and read the canary through a child shell. It
runs under grade.sandbox_wrapper, the exact wrapper every pundits judge call
uses. Network access is NOT tested: the sandbox does not deny it by design,
because Astra's and Gemini's web search runs on the provider's side and the
user accepted that (docs/PUNDITS-P3-PROBES.md).

  READ     cat of the canary is denied and the canary never appears in output
  LIST     listing the container is denied
  WRITE    a write into the container does not create the file
  SHELL    a child shell reading the canary is denied too
  OUTSIDE  the same script can read and write outside the container, so the
           denials above are the sandbox and not a broken script

Needs macOS sandbox-exec. No quota.

  .venv/bin/python scripts/test_judge_jail.py
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
CANARY = "JAILCANARY-51c2e8"

FAKE_JUDGE = """#!/bin/sh
echo "READ:$(cat "$1/repo/roster.json" 2>&1)"
echo "LIST:$(ls "$1/repo" 2>&1)"
echo "x" > "$1/repo/written.txt" 2>/dev/null; echo "WRITE:$?"
echo "SHELL:$(/bin/sh -c "cat '$1/repo/roster.json'" 2>&1)"
echo "OUTREAD:$(cat "$2/ok.txt" 2>&1)"
echo "y" > "$2/written.txt" 2>/dev/null; echo "OUTWRITE:$?"
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("judge jail")
    if shutil.which("sandbox-exec") is None:
        check("sandbox-exec is available on this machine", False, "the pundits harness requires macOS sandbox-exec")
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    spec = importlib.util.spec_from_file_location("grade_jail", REPO / "scripts" / "grade.py")
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)

    with tempfile.TemporaryDirectory(prefix="jail-") as td:
        tmp = Path(td).resolve()
        root, outside = tmp / "container", tmp / "outside"
        (root / "repo").mkdir(parents=True)
        outside.mkdir()
        (root / "repo" / "roster.json").write_text(CANARY)
        (outside / "ok.txt").write_text("fine")
        judge = outside / "fake_judge.sh"
        judge.write_text(FAKE_JUDGE)
        judge.chmod(0o755)

        proc = subprocess.run([*G.sandbox_wrapper(root), "/bin/sh", str(judge), str(root), str(outside)],
                              capture_output=True, text=True, timeout=60)
        out = dict(line.split(":", 1) for line in proc.stdout.splitlines() if ":" in line)

        print("\n[READ]")
        check("cat of the canary is denied", "not permitted" in out.get("READ", "") or "denied" in out.get("READ", "").lower(),
              out.get("READ"))
        check("the canary never appears in any output", CANARY not in proc.stdout + proc.stderr)
        print("\n[LIST]")
        check("listing the container is denied", "roster.json" not in out.get("LIST", ""), out.get("LIST"))
        print("\n[WRITE]")
        check("a write into the container creates nothing", not (root / "repo" / "written.txt").exists()
              and out.get("WRITE") != "0", out.get("WRITE"))
        print("\n[SHELL]")
        check("a child shell reading the canary is denied", CANARY not in out.get("SHELL", ""), out.get("SHELL"))
        print("\n[OUTSIDE]")
        check("the same script reads outside the container", out.get("OUTREAD") == "fine", out.get("OUTREAD"))
        check("the same script writes outside the container",
              out.get("OUTWRITE") == "0" and (outside / "written.txt").exists(), out.get("OUTWRITE"))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
