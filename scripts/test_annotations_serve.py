#!/usr/bin/env python3
"""The local answer server accepts what a session's page can send and refuses everything else.

It runs a REAL server on a real socket and talks to it over HTTP. Reading the source
could not tell a working route from one that never matches, and the bind address is
the whole privacy argument for serving locally instead of publishing a fourth Worker,
so that one is read off the listening socket rather than off the constant.

  LOOPBACK   the socket listens on 127.0.0.1 and nothing else
  PAGE       / redirects to the only session, and /s/<name>/ serves its page
  ROUNDTRIP  a saved answer comes back from GET api/answers and is on disk
  MERGE      a second answer replaces its own entry and leaves the others alone
  DERIVED    a quote result cannot be posted: it follows the word ranges
  FOREIGN    an id the page does not carry is refused, and nothing is written
  KIND       a kind that is no answers section is refused
  MODE       a section no mode of the session writes is refused
  SHAPE      a non-object value, a bad body and an oversized body are refused
  EXPORT     the file the server writes is one `export labels` and `export quotes` read
  BROKEN     a page with no data block stops the server rather than accepting any id
  KEPT       an answer for an id missing from a rebuilt page is kept, not dropped
  SESSIONS   two sessions are served side by side and listed at /; two with one
             name, or one answers file, stop the server

  .venv/bin/python scripts/test_annotations_serve.py
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
# A request returns as soon as the server answers, so this bound costs nothing on a
# healthy run; it only decides how slow a loaded machine may be. This file's
# intermittent failure (d9f2321, 2026-09-27) was NOT a timeout: reproduced on
# 2026-10-11 as a connection reset at the oversized-body check, 3 runs in 60, and
# fixed in the server (annotations_serve.DRAIN_LIMIT).
HTTP_TIMEOUT_S = 30


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def post(base, obj, raw=None):
    body = raw if raw is not None else json.dumps(obj).encode()
    req = urllib.request.Request(base + "/api/answer", data=body, method="POST",
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=HTTP_TIMEOUT_S) as r:
        return r.status, r.read()


def session_data(keys, qids):
    return {"rows": [{"key": k} for k in keys],
            "quote_rows": [{"key": keys[0] if keys else "p/a", "quotes": [{"qid": q} for q in qids]}] if qids else [],
            "transcript_index": {}}


def main() -> int:
    print("annotation server")
    import annotations as C
    import annotations_serve as S
    from annotations_fixtures import write_session

    td = Path(tempfile.mkdtemp())
    keys = ["p/a", "p/b"]
    qids = ["p:a:0", "p:a:1"]
    modes = ("checklist", "speakers", "captions")
    session = write_session(td / "one", session_data(keys, qids), modes=modes)
    answers = session.answers

    httpd = S.build_server([session], 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    root = f"http://127.0.0.1:{port}"
    base = root + "/s/t"
    try:
        print("\n[LOOPBACK]")
        check("the socket listens on 127.0.0.1", host == "127.0.0.1", host)
        check("and the listening family is not a wildcard bind",
              httpd.socket.getsockname()[0] == "127.0.0.1", str(httpd.socket.getsockname()))
        # gethostbyname(gethostname()) answers 127.0.0.1 on this Mac, which would test
        # loopback against itself and pass whatever the server bound to. Ask the routing
        # table instead; the UDP connect sends no packet.
        outward = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
            outward = probe.getsockname()[0]
            probe.close()
        except OSError:
            pass
        if outward and not outward.startswith("127."):
            s = socket.socket()
            s.settimeout(1.5)
            refused = s.connect_ex((outward, port)) != 0
            s.close()
            check(f"and a connection to this machine's LAN address ({outward}) is refused", refused,
                  "the page holds private transcript text; it must not be reachable off-machine")
        else:
            check("and a connection to this machine's LAN address is refused", False,
                  f"could not find a non-loopback address to test against (got {outward!r}); "
                  "this check did not run, so treat the bind as unproven")

        print("\n[PAGE]")
        code, body = get(root, "/")
        check("GET / reaches the only session's page", code == 200 and b"const D = " in body, str(code))
        code, body = get(base, "/")
        check("GET /s/<name>/ serves the page", code == 200 and body == session.page.read_bytes(), str(code))
        code, body = get(base, "")
        check("and /s/<name> without the slash lands on it too", code == 200 and b"const D = " in body, str(code))

        print("\n[ROUNDTRIP]")
        code, res = post(base, {"kind": "labels", "id": "p/a",
                                "value": {"key": "p/a", "subject_present": True, "venue": "solo",
                                          "political_content": True, "checked_by": "operator"}})
        check("a valid answer is accepted", code == 200 and res.get("ok"), str(res))
        code, body = get(base, "/api/answers")
        check("and comes back from GET api/answers",
              json.loads(body)["labels"].get("p/a", {}).get("venue") == "solo", body[:200].decode())
        check("and is on disk at once, not at shutdown",
              json.loads(answers.read_text())["labels"].get("p/a", {}).get("venue") == "solo")

        print("\n[MERGE]")
        post(base, {"kind": "labels", "id": "p/b",
                    "value": {"key": "p/b", "subject_present": False, "venue": "debate",
                              "political_content": True, "checked_by": "operator"}})
        post(base, {"kind": "labels", "id": "p/a",
                    "value": {"key": "p/a", "subject_present": True, "venue": "reaction",
                              "political_content": True, "checked_by": "operator"}})
        on_disk = json.loads(answers.read_text())
        check("a re-answer replaces its own entry", on_disk["labels"]["p/a"]["venue"] == "reaction")
        check("and leaves the other recording alone", on_disk["labels"]["p/b"]["venue"] == "debate")
        check("the file keeps all four sections", set(on_disk) == {"labels", "attribution", "spans", "corrections"},
              str(sorted(on_disk)))

        print("\n[DERIVED]")
        before = answers.read_text()
        code, res = post(base, {"kind": "attribution", "id": "p:a:0", "value": {"qid": "p:a:0", "answer": "other"}})
        check("a quote result cannot be posted directly", code == 409 and "word markings" in res.get("error", ""),
              str(res))
        check("and nothing was written", answers.read_text() == before)

        print("\n[FOREIGN]")
        code, res = post(base, {"kind": "labels", "id": "q/zz", "value": {"key": "q/zz", "subject_present": True}})
        check("an id the page does not carry is refused", code == 400 and "not a labels id" in res.get("error", ""), str(res))
        code, res = post(base, {"kind": "spans", "id": "p/zz", "value": {}})
        check("and so is a recording the page does not carry", code == 400, str(res))
        check("and nothing was written", answers.read_text() == before)

        print("\n[KIND]")
        code, res = post(base, {"kind": "leans", "id": "p/a", "value": {}})
        check("an unknown kind is refused", code == 400 and "kind must be" in res.get("error", ""), str(res))

        print("\n[SHAPE]")
        code, res = post(base, {"kind": "labels", "id": "p/a", "value": "solo"})
        check("a value that is not an object is refused", code == 400, str(res))
        code, res = post(base, None, raw=b"{not json")
        check("a body that is not JSON is refused", code == 400 and "not JSON" in res.get("error", ""), str(res))
        code, res = post(base, None, raw=b"x" * (S.MAX_BODY + 1))
        check("an oversized body is refused", code == 400 and "bytes" in res.get("error", ""), str(res))
        # The server used to answer before reading the body, so the socket closed
        # with unread bytes and the kernel sent a reset: the client saw ECONNRESET
        # instead of the refusal. MEASURED 2026-10-11: 3 of 60 runs failed this way
        # at MAX_BODY + 1, and a 1 MiB body was reset 30 times in 30.
        outcomes = []
        for _ in range(5):
            try:
                outcomes.append(post(base, None, raw=b"x" * (4 * S.MAX_BODY))[0])
            except urllib.error.URLError as exc:
                outcomes.append(f"reset: {exc.reason}")
        check("a body four times the cap gets the 400, not a connection reset",
              outcomes == [400] * 5, str(outcomes))
        check("and after every refusal the good answers are still there",
              json.loads(answers.read_text())["labels"]["p/a"]["venue"] == "reaction")

        print("\n[EXPORT]")
        (session.root / "quote_key.json").write_text(json.dumps(
            {"p:a:0": {"key": "p/a", "signals": ["spans_turn"], "judges": [{"judge": "j", "label": "subject"}]}}))
        session.manifest["projects"] = ["pundits"]
        got = C.export_result(session, "labels")
        check("export labels reads the server's file and writes both labels",
              set(got["labels"]) == set(keys) and got["labels"]["p/a"]["venue"] == "reaction", str(got))
        check("every exported label passes report's own validator",
              not any(__import__("pundits_pilot").human_errors(v) for v in got["labels"].values()))
        q = C.export_result(session, "quotes")
        check("export quotes reads the same file and reports the unanswered quote",
              q["unanswered"] == ["p:a:0"] and q["tally"]["other"] == 0, str(q))
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n[MODE]")
    quiet = write_session(td / "speakers-only", session_data(keys, qids), modes=("speakers",), name="sp")
    h = S.build_server([quiet], 0)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    try:
        code, res = post(f"http://127.0.0.1:{h.server_address[1]}/s/sp", {"kind": "labels", "id": "p/a",
                                                                      "value": {"key": "p/a"}})
        check("a session without the checklist mode refuses a checklist answer",
              code == 400 and "do not write labels" in res.get("error", ""), str(res))
        check("and writes no answers file", not quiet.answers.exists())
    finally:
        h.shutdown()
        h.server_close()

    print("\n[BROKEN]")
    bad = write_session(td / "bad", session_data(keys, []), modes=modes, name="bad")
    bad.page.write_text("<title>t</title><script>const D = null;</script>")
    try:
        S.build_server([bad], 0)
        check("a page with no data block stops the server", False, "it started and would accept any id")
    except SystemExit as exc:
        check("a page with no data block stops the server", "no `const D" in str(exc), str(exc))

    print("\n[KEPT]")
    shrunk = write_session(td / "one", session_data(["p/a"], []), modes=modes)
    h2 = S.build_server([shrunk], 0)
    try:
        check("an answer for a recording the rebuilt page dropped is kept, not deleted",
              "p/b" in h2.mounts["t"].store.load()["labels"])
        check("and the page's own ids no longer include it", "p/b" not in h2.mounts["t"].ids["labels"])
    finally:
        h2.server_close()

    print("\n[SESSIONS]")
    other = write_session(td / "two", session_data(["q/x"], []), modes=("speakers", "captions"),
                          projects=("insights", "predictions"), name="two")
    h3 = S.build_server([shrunk, other], 0)
    threading.Thread(target=h3.serve_forever, daemon=True).start()
    try:
        code, body = get(f"http://127.0.0.1:{h3.server_address[1]}", "/")
        page = body.decode()
        check("with two sessions, / lists both with their projects",
              code == 200 and 'href="/s/t/"' in page and 'href="/s/two/"' in page and "insights" in page
              and "predictions" in page, page[:300])
        code, body = get(f"http://127.0.0.1:{h3.server_address[1]}", "/s/two/")
        check("and each is served at its own address", code == 200 and body == other.page.read_bytes())
    finally:
        h3.shutdown()
        h3.server_close()
    import contextlib
    import io
    overlap = write_session(td / "three", session_data(["p/a"], []) | {"transcript_index": {"p/a": {}}},
                            modes=("speakers",), projects=("insights",), name="three")
    base_one = write_session(td / "four", session_data(["p/a"], []) | {"transcript_index": {"p/a": {}}},
                             modes=("speakers",), projects=("predictions",), name="four")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        h4 = S.build_server([base_one, overlap], 0)
    h4.server_close()
    check("two sessions over one recording start, but say so: a range saved in one is not seen by the other",
          "recording p/a is in both four and three" in err.getvalue(), err.getvalue())
    for label, pair in (("two sessions with one name", [shrunk, write_session(td / "dup", session_data(["p/a"], []))]),
                        ("two sessions with one answers file", [shrunk, type(shrunk)(shrunk.root, {**shrunk.manifest, "name": "x"})])):
        try:
            S.build_server(pair, 0)
            check(f"{label} stop the server", False, "it started")
        except SystemExit as exc:
            check(f"{label} stop the server", "REFUSING" in str(exc), str(exc))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
