#!/usr/bin/env python3
"""The deploy's read of the live revision.json names itself, so a bot filter lets it through.

FOUND 2026-09-29: verbatim-predictions.tonygwu.com started answering 403 to
urllib's default "Python-urllib/3.x" user agent, and 200 to curl or to any named
agent. live_revision_error() sent the default, so every predictions deploy
refused with "cannot read the live revision ... HTTP Error 403". The deploy on
2026-09-28 had passed the same check, so the filter changed, not the code.

This runs the real function against a local server that behaves the same way,
refusing the default agent and recording what it was sent. No network.
"""
from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import data_clone_workflow as D  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


seen: list[str] = []
REVISION = {}


class BotFilter(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        seen.append(ua)
        if not ua or ua.startswith("Python-urllib"):
            self.send_response(403)
            self.end_headers()
            return
        body = json.dumps({"data_revision": REVISION["sha"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


with tempfile.TemporaryDirectory() as td:
    repo = Path(td) / "data"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a").write_text("1")
    git(repo, "add", "a")
    git(repo, "commit", "-q", "-m", "one")
    REVISION["sha"] = git(repo, "rev-parse", "HEAD")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BotFilter)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["VI_LIVE_REVISION_URL"] = f"http://127.0.0.1:{srv.server_port}/revision.json"
    try:
        why = D.live_revision_error(repo, REVISION["sha"], first=False)
    finally:
        srv.shutdown()
    check("a filter that refuses the default Python agent still answers the deploy's read",
          why is None, str(why))
    check("the read names itself: a verbatim-index agent, never Python-urllib",
          bool(seen) and seen[-1].startswith("verbatim-index") and "Python-urllib" not in seen[-1], str(seen))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
