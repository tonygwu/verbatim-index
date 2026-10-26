#!/usr/bin/env python3
"""A fake judge run under the real pundits sandbox cannot read, list, write or shell into the container.

Pundits plan, Verification. The judges' own tool calls cannot be triggered in a
test without spending quota, so a shell script stands in for a judge that tries
everything a tool-using judge could: read the roster canary with cat, list the
container, write a file into it, and read the canary through a child shell. It
runs under grade.sandbox_wrapper, the exact wrapper every pundits judge call
uses. Network access is NOT tested, except for one local service: the sandbox
does not deny the network by design, because Astra's and Gemini's web search
runs on the provider's side and the user accepted that
(docs/PUNDITS-P3-PROBES.md).

  READ     cat of the canary is denied and the canary never appears in output
  LIST     listing the container is denied
  WRITE    a write into the container does not create the file
  SHELL    a child shell reading the canary is denied too
  OUTSIDE  the same script can read and write outside the container, so the
           denials above are the sandbox and not a broken script
  SERVICE  the transcript labeling service (VI-59): connections to port 8790 on
           127.0.0.1, ::1 and the IPv4-mapped ::ffff:127.0.0.1 are refused; the
           port a scratch home's config.json names cannot be bound on any address
           or reached on any of those three inside, and can be outside; an
           unrelated port still connects inside; a canary under TL_HOME cannot
           be read. Port 8790 is never bound, so a gate run never holds it

Needs macOS sandbox-exec. No quota.

  .venv/bin/python scripts/test_judge_jail.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
CANARY = "JAILCANARY-51c2e8"
TL_CANARY = "TLCANARY-7d41a0"
CURL = "/usr/bin/curl"
BIND = ("import socket, sys; s = socket.socket(getattr(socket, sys.argv[1]));"
        " s.bind((sys.argv[2], int(sys.argv[3]))); print('BOUND')")

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


def listen(family: int, host: str, port: int) -> socket.socket:
    """A listener that answers every connection with a tiny HTTP reply."""
    s = socket.socket(family, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(8)

    def serve():
        while True:
            try:
                conn, _ = s.accept()
            except OSError:
                return
            with conn:
                conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
    threading.Thread(target=serve, daemon=True).start()
    return s


def curl(prefix: list[str], url: str) -> str:
    p = subprocess.run([*prefix, CURL, "-gsv", "--max-time", "5", url], capture_output=True, text=True, timeout=30)
    return p.stdout + p.stderr


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def bind(prefix: list[str], family: str, host: str, port: int) -> subprocess.CompletedProcess:
    return subprocess.run([*prefix, str(Path(sys.executable).resolve()), "-c", BIND, family, host, str(port)],
                          capture_output=True, text=True, timeout=30)


def service_checks(G, tmp: Path) -> None:
    """Build the real wrapper with TL_HOME pointed at a scratch home whose config.json names a
    scratch port, then try what a judge could. Port 8790 itself is never bound here, so a gate
    run never holds the live service's port; its forms are checked by the refusal alone."""
    home = tmp / "tl-home"
    home.mkdir()
    (home / "token").write_text(TL_CANARY)
    port, other = free_port(), free_port()
    (home / "config.json").write_text(f'{{"port": {port}, "operator_id": "operator", '
                                      f'"allowed_hosts": [], "access": {{}}}}')
    saved = os.environ.get("TL_HOME")
    os.environ["TL_HOME"] = str(home)
    try:
        wrapper = G.sandbox_wrapper(tmp / "container")
    finally:
        if saved is None:
            os.environ.pop("TL_HOME", None)
        else:
            os.environ["TL_HOME"] = saved
    print("\n[SERVICE]")
    for url in ("http://127.0.0.1:8790/", "http://[::1]:8790/", "http://[::ffff:127.0.0.1]:8790/"):
        inside = curl(wrapper, url)
        check(f"a jailed connection to {url} is refused by the sandbox",
              "Operation not permitted" in inside and "Connected to" not in inside, inside[-300:])
    for family, host in (("AF_INET", "127.0.0.1"), ("AF_INET", "0.0.0.0"), ("AF_INET6", "::1"),
                         ("AF_INET6", "::ffff:127.0.0.1"), ("AF_INET6", "::")):
        jailed = bind(wrapper, family, host, port)
        check(f"a jailed bind of {host} on the port config.json names is denied",
              "BOUND" not in jailed.stdout and "Operation not permitted" in jailed.stderr, jailed.stderr[-200:])
    free = bind([], "AF_INET", "127.0.0.1", port)
    check("the same bind outside the jail succeeds", "BOUND" in free.stdout, free.stderr[-200:])
    listeners = [listen(socket.AF_INET, "127.0.0.1", port), listen(socket.AF_INET6, "::1", port),
                 listen(socket.AF_INET, "127.0.0.1", other)]
    try:
        for url in (f"http://127.0.0.1:{port}/", f"http://[::1]:{port}/", f"http://[::ffff:127.0.0.1]:{port}/"):
            inside, outside = curl(wrapper, url), curl([], url)
            check(f"a jailed connection to {url} (the config port) is refused by the sandbox",
                  "Operation not permitted" in inside and "Connected to" not in inside, inside[-300:])
            check(f"the same connection to {url} outside the jail succeeds", "Connected to" in outside,
                  outside[-300:])
        control = curl(wrapper, f"http://127.0.0.1:{other}/")
        check("a jailed connection to an unrelated local port still succeeds, so the deny is the service's",
              "Connected to" in control, control[-300:])
    finally:
        for s in listeners:
            s.close()
    cat = subprocess.run([*wrapper, "/bin/cat", str(home / "token")], capture_output=True, text=True)
    check("a jailed cat of the token under TL_HOME is denied",
          cat.returncode != 0 and "Operation not permitted" in cat.stderr, cat.stderr[-200:])
    check("the token canary never appears in jailed output", TL_CANARY not in cat.stdout + cat.stderr)


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

        service_checks(G, tmp)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
