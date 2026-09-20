#!/usr/bin/env python3
"""Serve the P6 speaker-check page from this machine and save every answer to a file.

WHY THIS EXISTS. The page was published as an Artifact, where answers save to the
Artifact's own store. That store accepts writes only from the ONE Claude account that
owns the page: the runtime grants writes to people who can interact or edit, and never
to a view-only viewer or a link visitor, and the page cannot lower that bar. The
operator watches YouTube signed into a different Google account, so labelling and
watching were stuck in two browsers. Served from here, the page needs no account at
all, so any browser profile on this machine can label while YouTube stays signed in
where the subscription is.

It also removes a step. On the Artifact route the answers had to be exported from the
store and then imported; here they land straight in a file that
`pundits_verify_page.py import` and `import-quotes` read.

PRIVACY. The page carries transcript text from the private data checkout, so the
socket binds to loopback only and there is no flag to widen it. Nothing leaves the
machine. That is the whole reason this is not a fourth Cloudflare Worker.

WHAT IT REFUSES. An answer whose id is not on the page it is serving, and a `kind`
other than labels or attribution. The page is the one source of valid ids: the server
reads them out of the served file rather than from the checklist, so the ids it
accepts are exactly the ids the page can send. `import` refuses a foreign key at the
end of the pipeline; refusing it here as well means a typo or a stale page cannot
quietly accumulate answers that the import will later throw away.

  .venv/bin/python scripts/pundits_verify_serve.py \\
      --page data-pundits/logs/p6b/speaker_check.html
  # then open http://127.0.0.1:5001/ in any browser on this Mac

  .venv/bin/python scripts/pundits_verify_page.py import \\
      --export data-pundits/logs/p6b/human_answers.json \\
      --checklist data-pundits/logs/p6b/human_checklist.json \\
      --out data-pundits/logs/p6b/human_labels.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402
from pundits_speaker_spans import sidecar_path, validate_annotation, token_kinds, reconcile_quote_reviews  # noqa: E402
from pundits_text_corrections import update_corrections  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 5001
SECTIONS = ("labels", "attribution", "spans", "corrections")
MAX_BODY = 256 * 1024
DATA_LINE = re.compile(r"^const D = (\{.*\});$", re.M)


def page_ids(page: str) -> dict[str, set[str]]:
    """The recording keys and quote ids the served page can send, read out of the page.

    Raises rather than returning empty sets: a page whose data block cannot be read is
    a build this server does not understand, and accepting every id from it would turn
    a loud mismatch into a file of answers nothing can import.
    """
    m = DATA_LINE.search(page)
    if not m:
        raise SystemExit("REFUSING: no `const D = {...};` data block in the page; rebuild it with pundits_verify_page.py build")
    data = json.loads(m.group(1).replace("<\\/", "</"))
    keys = {r["key"] for r in data.get("rows", []) if r.get("key")}
    qids = {c["qid"] for r in data.get("quote_rows", []) for c in r.get("quotes", []) if c.get("qid")}
    if not keys and not qids:
        raise SystemExit("REFUSING: the page carries no recordings and no quotes")
    return {"labels": keys, "attribution": qids, "spans": set(data.get("transcript_index", {})),
            "corrections": set(data.get("transcript_index", {}))}


def load_answers(path: Path) -> dict:
    """Existing answers, or an empty pair. A malformed file stops the server."""
    if not path.exists():
        return {s: {} for s in SECTIONS}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or not {"labels", "attribution"} <= set(raw) or set(raw) - set(SECTIONS) or not all(isinstance(v, dict) for v in raw.values()):
        raise SystemExit(f"REFUSING: {path} is not an answers file ({{'labels': ..., 'attribution': ...}})")
    return {s: raw.get(s, {}) for s in SECTIONS}


def make_handler(page_bytes: bytes, ids: dict[str, set[str]], answers: dict, answers_path: Path, lock: threading.Lock,
                 page_path: Path):
    data = json.loads(DATA_LINE.search(page_bytes.decode()).group(1).replace("<\\/", "</"))
    quote_rows = data.get("quote_rows", [])
    quote_recordings = {q["qid"]: r["key"] for r in quote_rows for q in r.get("quotes", [])}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "pundits-verify/1"

        def log_message(self, fmt, *args):  # one line per write, not per asset
            if self.command == "POST":
                sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(200, page_bytes, "text/html; charset=utf-8")
            if path == "/api/answers":
                with lock:
                    return self._json(200, reconcile_quote_reviews(answers, page_path, quote_rows))
            if path == "/api/transcript":
                key = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
                if key not in ids["spans"]:
                    return self._json(404, {"error": "recording is not on this page"})
                try:
                    payload = json.loads(sidecar_path(page_path, key).read_text())
                except (OSError, ValueError):
                    return self._json(409, {"error": "transcript unavailable; rebuild the page"})
                return self._json(200, {**payload, "token_kinds": token_kinds(payload["tokens"])})
            return self._json(404, {"error": f"no such path: {path}"})

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/answer":
                return self._json(404, {"error": f"no such path: {self.path}"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "unreadable Content-Length"})
            if length <= 0 or length > MAX_BODY:
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
            if ident not in ids[kind]:
                return self._json(400, {"error": f"{ident!r} is not a {kind} id on this page"})
            if not isinstance(value, dict):
                return self._json(400, {"error": "value is not an object"})
            if kind == "spans":
                try:
                    transcript = json.loads(sidecar_path(page_path, ident).read_text())
                    validate_annotation(value, transcript)
                except (OSError, ValueError) as exc:
                    return self._json(400, {"error": str(exc)})
            with lock:
                if kind == "corrections":
                    try:
                        transcript = json.loads(sidecar_path(page_path, ident).read_text())
                        value = update_corrections(value, answers["corrections"].get(ident), transcript)
                    except (OSError, ValueError) as exc:
                        return self._json(409, {"error": str(exc)})
                if kind == "attribution" and quote_recordings.get(ident) in answers["spans"]:
                    return self._json(409, {"error": "Quote results now follow your word markings. Reload the page to continue."})
                updated = {**answers, kind: {**answers[kind], ident: value}}
                updated = reconcile_quote_reviews(updated, page_path, quote_rows)
                try:
                    write_atomic(answers_path, json.dumps(updated, indent=1, ensure_ascii=False) + "\n")
                except OSError:
                    return self._json(500, {"error": "answer could not be written to disk; retry"})
                answers.update(updated)
                counts = {s: len(answers[s]) for s in SECTIONS}
                reviews = dict(answers["attribution"])
            return self._json(200, {"ok": True, "saved": counts, "attribution": reviews,
                                    **({"correction": value} if kind == "corrections" else {})})

    return Handler


def build_server(page_path: Path, answers_path: Path, port: int) -> ThreadingHTTPServer:
    page = page_path.read_text()
    ids = page_ids(page)
    answers = load_answers(answers_path)
    stale = {s: sorted(set(answers[s]) - ids[s]) for s in SECTIONS}
    for section, extra in stale.items():
        if extra:
            print(f"NOTE: {len(extra)} {section} answers name ids the current page does not carry, "
                  f"e.g. {extra[:3]}. They are kept in the file and cannot be changed from this page.")
    httpd = ThreadingHTTPServer((HOST, port), make_handler(page.encode(), ids, answers, answers_path, threading.Lock(), page_path))
    httpd.answers = answers
    httpd.ids = ids
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--page", required=True, help="the page built by pundits_verify_page.py build")
    ap.add_argument("--answers", help="where answers are saved (default: human_answers.json beside the page)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    page_path = Path(args.page)
    answers_path = Path(args.answers) if args.answers else page_path.parent / "human_answers.json"
    httpd = build_server(page_path, answers_path, args.port)
    counts = {s: len(httpd.answers[s]) for s in SECTIONS}
    print(f"serving {page_path} on http://{HOST}:{httpd.server_address[1]}/  (loopback only)")
    print(f"answers -> {answers_path}  ({counts['labels']} recordings, {counts['attribution']} quotes so far)")
    print(f"page carries {len(httpd.ids['labels'])} recordings and {len(httpd.ids['attribution'])} quotes. Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
