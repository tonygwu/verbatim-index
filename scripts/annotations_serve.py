#!/usr/bin/env python3
"""Serve annotation sessions from this machine and save every answer as it is made.

Run it through `scripts/annotations.py serve --session DIR [--session DIR ...]`.
Each session is mounted at `/s/<name>/`; with one session `/` redirects to it, and
with several `/` lists them, so every project is annotated in one interface.

The socket binds to 127.0.0.1 and there is no flag to widen it, because a page
carries transcript text. A request may only write an id the served page carries,
in a section one of the session's modes owns: `labels` for the checklist, `spans`
for speakers and `corrections` for captions. `attribution` is never written by a
request: the server derives it from `spans` on every save and every read.
"""
from __future__ import annotations

import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annotations_corrections import update_corrections  # noqa: E402
from annotations_page import page_ids  # noqa: E402
from annotations_spans import reconcile_quote_reviews, token_kinds, validate_annotation  # noqa: E402
from annotations_store import SECTIONS, FileStore, Session, Store  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 5001
MAX_BODY = 256 * 1024
# How much of a refused body is read and thrown away before the refusal is sent.
# Answering with unread bytes in the socket makes the kernel send a reset, and the
# client then sees ECONNRESET instead of the 400 (3 of 60 test runs, 2026-10-11).
# Past this bound the connection is simply closed; nothing on this page sends that.
DRAIN_LIMIT = 16 * MAX_BODY
#: Once a label records that its draft was on screen, and the blind answers it had
#: before, no later save drops or replaces either. The page sends the whole label, so
#: a second tab still showing an older copy would otherwise turn an assisted label
#: back into a blind one.
STICKY_LABEL_FIELDS = ("draft_shown", "answers_before_draft")


def keep_assisted(value: dict, stored: dict | None) -> dict:
    """`value`, with any sticky field the stored label already has."""
    return {**value, **{f: stored[f] for f in STICKY_LABEL_FIELDS if stored and f in stored}}


class Mounted:
    """One session as the server holds it: its page bytes, ids and store."""

    def __init__(self, session: Session, store: Store):
        self.session = session
        self.store = store
        self.page_bytes = session.page.read_bytes()
        data = session.data()
        self.ids = page_ids(data)
        self.quote_rows = data.get("quote_rows", [])
        self.writable = session.sections()
        answers = store.load()
        for section in SECTIONS:
            extra = sorted(set(answers[section]) - self.ids[section])
            if extra:
                print(f"NOTE: {session.name}: {len(extra)} {section} answers name ids the current page does not "
                      f"carry, e.g. {extra[:3]}. They are kept in the file and cannot be changed from this page.", file=sys.stderr)
        if b"const artifactStore" in self.page_bytes:
            print(f"NOTE: {session.name}: the page was built by an older template; "
                  "`annotations.py rebuild` renders it with the current one and keeps every answer.", file=sys.stderr)

    def reviewed(self, answers: dict) -> dict:
        return reconcile_quote_reviews(answers, self.session.page, self.quote_rows)


def landing(mounts: dict[str, Mounted]) -> bytes:
    """The list of sessions, linking each to its page."""
    items = []
    for name, m in mounts.items():
        answers = m.store.load()
        items.append(
            f'<li><a href="/s/{quote(name)}/">{html.escape(name)}</a> '
            + "".join(f'<span class="chip">{html.escape(p)}</span>' for p in m.session.projects)
            + f'<span class="meta">{html.escape(", ".join(m.session.modes))} · {len(m.ids["spans"])} recordings · '
            f'{len(m.ids["attribution"])} quotes · {len(answers["spans"])} with speaker marks · '
            f'{len(answers["corrections"])} with caption corrections · {len(answers["labels"])} checklists</span></li>')
    return ("""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Annotations</title><style>
:root{--ground:#F4F4F2;--ink:#17191C;--muted:#5D646C;--accent:#1F6FB2;--rule:#C4C5BF}
@media (prefers-color-scheme:dark){:root{--ground:#121316;--ink:#EAECEF;--muted:#989FA8;--accent:#5EA3DE;--rule:#3A3F47}}
body{background:var(--ground);color:var(--ink);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px}
main{max-width:900px;margin:0 auto}ul{list-style:none;padding:0}li{padding:10px 0;border-top:1px solid var(--rule)}
a{color:var(--accent);font-weight:600;margin-right:8px}.chip{border:1px solid var(--rule);border-radius:999px;padding:0 8px;
margin-right:6px;font-size:.8rem}.meta{display:block;color:var(--muted);font-size:.85rem}
</style><main><h1>Annotations</h1><p>Sessions served from this machine. Each answer saves to its session's
answers file as you make it.</p><ul>""" + "".join(items) + "</ul></main>").encode()


def make_handler(mounts: dict[str, Mounted]):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "annotations/2"

        def log_message(self, fmt, *args):  # one line per write, not per asset
            if self.command == "POST":
                sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

        def _send(self, code, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def _drain(self, length: int) -> None:
            """Read and discard up to `length` body bytes, never more than DRAIN_LIMIT."""
            left = min(max(length, 0), DRAIN_LIMIT)
            while left > 0:
                chunk = self.rfile.read(min(left, 64 * 1024))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True

        def _route(self) -> tuple[Mounted | None, str | None]:
            """(session, path inside it) for /s/<name>/..., else (None, None)."""
            parts = urlsplit(self.path).path.split("/", 3)
            if len(parts) >= 3 and parts[1] == "s" and parts[2] in mounts:
                return mounts[parts[2]], "/" + (parts[3] if len(parts) == 4 else "")
            return None, None

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                if len(mounts) == 1:
                    return self._send(302, b"", "text/plain", {"Location": f"/s/{quote(next(iter(mounts)))}/"})
                return self._send(200, landing(mounts), "text/html; charset=utf-8")
            m, sub = self._route()
            if m is None:
                return self._json(404, {"error": f"no such path: {path}"})
            if not path.endswith("/") and sub == "/":
                # The page's api paths are relative, so its address must end in a slash.
                return self._send(301, b"", "text/plain", {"Location": path + "/"})
            if sub in ("/", "/index.html"):
                return self._send(200, m.page_bytes, "text/html; charset=utf-8")
            if sub == "/api/answers":
                return self._json(200, m.reviewed(m.store.load()))
            if sub == "/api/transcript":
                key = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
                if key not in m.ids["spans"]:
                    return self._json(404, {"error": "recording is not on this page"})
                try:
                    payload = json.loads(m.session.sidecar(key).read_text())
                except (OSError, ValueError):
                    return self._json(409, {"error": "transcript unavailable; rebuild the page"})
                return self._json(200, {**payload, "token_kinds": token_kinds(payload["tokens"])})
            return self._json(404, {"error": f"no such path: {path}"})

        def do_POST(self):
            m, sub = self._route()
            if m is None or sub != "/api/answer":
                return self._json(404, {"error": f"no such path: {self.path}"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "unreadable Content-Length"})
            if length <= 0 or length > MAX_BODY:
                self._drain(length)
                return self._json(400, {"error": f"body must be 1..{MAX_BODY} bytes, got {length}"})
            try:
                msg = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError) as exc:
                return self._json(400, {"error": f"body is not JSON: {exc}"})
            if not isinstance(msg, dict):
                return self._json(400, {"error": "body is not an object"})
            kind, ident, value = msg.get("kind"), msg.get("id"), msg.get("value")
            if kind not in SECTIONS:
                return self._json(400, {"error": f"kind must be one of {SECTIONS}, got {kind!r}"})
            if kind == "attribution":
                return self._json(409, {"error": "Quote results follow your word markings and are not saved directly. "
                                                 "Reload the page to continue."})
            if kind not in m.writable:
                return self._json(400, {"error": f"this session's modes ({', '.join(m.session.modes)}) do not "
                                                 f"write {kind}"})
            if ident not in m.ids[kind]:
                return self._json(400, {"error": f"{ident!r} is not a {kind} id on this page"})
            if not isinstance(value, dict):
                return self._json(400, {"error": "value is not an object"})
            try:
                transcript = json.loads(m.session.sidecar(ident).read_text()) if kind != "labels" else None
            except (OSError, ValueError) as exc:
                return self._json(400, {"error": f"transcript unavailable: {exc}"})
            if kind == "spans":
                try:
                    validate_annotation(value, transcript)
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
            stored = {}

            def change(answers: dict) -> dict:
                new = value
                if kind == "corrections":
                    new = update_corrections(value, answers["corrections"].get(ident), transcript)
                if kind == "labels":
                    new = keep_assisted(value, answers["labels"].get(ident))
                stored["value"] = new
                return m.reviewed({**answers, kind: {**answers[kind], ident: new}})

            try:
                answers = m.store.update(change)
            except ValueError as exc:
                return self._json(409, {"error": str(exc)})
            except OSError:
                return self._json(500, {"error": "answer could not be written to disk; retry"})
            return self._json(200, {"ok": True, "saved": {s: len(answers[s]) for s in SECTIONS},
                                    "attribution": answers["attribution"],
                                    **({"correction": stored["value"]} if kind == "corrections" else {})})

    return Handler


def build_server(sessions: list[Session], port: int, stores: list[Store] | None = None) -> ThreadingHTTPServer:
    """A server for `sessions` on 127.0.0.1:`port` (0 picks a free port).

    Each session writes to its own `FileStore` unless `stores` names one per session.
    Two sessions with the same name, or two that share an answers file, stop it.
    """
    if not sessions:
        raise SystemExit("REFUSING: no session to serve")
    names = [s.name for s in sessions]
    if len(set(names)) != len(names):
        raise SystemExit(f"REFUSING: two sessions share a name: {names}")
    files = [s.answers.resolve() for s in sessions]
    if len(set(files)) != len(files):
        raise SystemExit("REFUSING: two sessions share one answers file")
    seen: dict[str, str] = {}
    for s in sessions:
        for key in s.manifest["recordings"]:
            if key in seen:
                # Two pages over one transcript collect two independent sets of word
                # ranges; that is allowed (old sessions overlap new ones), never silent.
                print(f"WARNING: recording {key} is in both {seen[key]} and {s.name}; a range saved in one is "
                      "not seen by the other", file=sys.stderr)
            else:
                seen[key] = s.name
    stores = stores or [FileStore(s.answers) for s in sessions]
    mounts = {s.name: Mounted(s, st) for s, st in zip(sessions, stores)}
    httpd = ThreadingHTTPServer((HOST, port), make_handler(mounts))
    httpd.mounts = mounts
    return httpd
