#!/usr/bin/env python3
"""The local answer server accepts what the page can send and refuses everything else.

It runs a REAL server on a real socket and talks to it over HTTP. Reading the source
could not tell a working route from one that never matches, and the bind address is
the whole privacy argument for serving locally instead of publishing a fourth Worker,
so that one is read off the listening socket rather than off the constant.

  LOOPBACK   the socket listens on 127.0.0.1 and nothing else
  PAGE       GET / serves the built page
  ROUNDTRIP  a saved answer comes back from GET /api/answers and is on disk
  MERGE      a second answer replaces its own entry and leaves the others alone
  FOREIGN    an id the page does not carry is refused, and nothing is written
  KIND       a kind other than labels/attribution is refused
  SHAPE      a non-object value, a bad body and an oversized body are refused
  IMPORT     the file the server writes is one `import` and `import-quotes` accept
  BROKEN     a page with no data block stops the server rather than accepting any id
  KEPT       an answer for an id missing from a rebuilt page is kept, not dropped

  .venv/bin/python scripts/test_pundits_verify_serve.py
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
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def post(base, obj, raw=None):
    body = raw if raw is not None else json.dumps(obj).encode()
    req = urllib.request.Request(base + "/api/answer", data=body, method="POST",
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.status, r.read()


PAGE_TEMPLATE = """<title>t</title><script>
const D = %s;
</script>"""


def write_page(path: Path, keys, qids):
    data = {"rows": [{"key": k} for k in keys],
            "quote_rows": [{"key": keys[0] if keys else "p/a", "quotes": [{"qid": q} for q in qids]}] if qids else [],
            "venues": ["solo"]}
    path.write_text(PAGE_TEMPLATE % json.dumps(data).replace("</", "<\\/"))


def main() -> int:
    print("pundits local answer server")
    import pundits_verify_serve as S
    import pundits_verify_page as V

    td = Path(tempfile.mkdtemp())
    page, answers = td / "page.html", td / "human_answers.json"
    keys = ["p/a", "p/b"]
    qids = ["p:a:0", "p:a:1"]
    write_page(page, keys, qids)

    httpd = S.build_server(page, answers, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
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
        code, body = get(base, "/")
        check("GET / serves the page", code == 200 and b"const D = " in body, str(code))

        print("\n[ROUNDTRIP]")
        code, res = post(base, {"kind": "labels", "id": "p/a",
                                "value": {"key": "p/a", "subject_present": True, "venue": "solo",
                                          "political_content": True, "checked_by": "operator"}})
        check("a valid answer is accepted", code == 200 and res.get("ok"), str(res))
        code, body = get(base, "/api/answers")
        check("and comes back from GET /api/answers",
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
        post(base, {"kind": "attribution", "id": "p:a:0", "value": {"qid": "p:a:0", "answer": "other"}})
        on_disk = json.loads(answers.read_text())
        check("a re-answer replaces its own entry", on_disk["labels"]["p/a"]["venue"] == "reaction")
        check("and leaves the other recording alone", on_disk["labels"]["p/b"]["venue"] == "debate")
        check("quote answers are kept apart from recording answers",
              on_disk["attribution"]["p:a:0"]["answer"] == "other" and "p:a:0" not in on_disk["labels"])

        print("\n[FOREIGN]")
        before = answers.read_text()
        code, res = post(base, {"kind": "labels", "id": "q/zz", "value": {"key": "q/zz", "subject_present": True}})
        check("an id the page does not carry is refused", code == 400 and "not a labels id" in res.get("error", ""), str(res))
        code, res = post(base, {"kind": "attribution", "id": "p:zz:9", "value": {"answer": "subject"}})
        check("and so is a quote id the page does not carry", code == 400, str(res))
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
        check("and after every refusal the good answers are still there",
              json.loads(answers.read_text())["labels"]["p/a"]["venue"] == "reaction")

        print("\n[IMPORT]")
        checklist = td / "c.json"
        checklist.write_text(json.dumps({k: {} for k in keys}))
        out = td / "human_labels.json"
        V.do_import(SimpleNamespace(export=str(answers), checklist=str(checklist), out=str(out)))
        got = json.loads(out.read_text())
        check("import reads the server's file and writes both labels",
              set(got) == set(keys) and got["p/a"]["venue"] == "reaction", str(got))
        check("every imported label passes report's own validator",
              not any(__import__("pundits_pilot").human_errors(v) for v in got.values()))
        key_map = td / "k.json"
        key_map.write_text(json.dumps({"p:a:0": {"signals": ["spans_turn"], "judges": [{"judge": "fable", "label": "subject"}]}}))
        qout = td / "quotes.json"
        V.do_import_quotes(SimpleNamespace(export=str(answers), key=str(key_map), out=str(qout)))
        check("import-quotes reads the same file and joins the key",
              json.loads(qout.read_text())["answers"]["p:a:0"]["answer"] == "other")
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n[BROKEN]")
    bad = td / "bad.html"
    bad.write_text("<title>t</title><script>const D = null;</script>")
    try:
        S.build_server(bad, td / "x.json", 0)
        check("a page with no data block stops the server", False, "it started and would accept any id")
    except SystemExit as exc:
        check("a page with no data block stops the server", "no `const D" in str(exc), str(exc))

    print("\n[KEPT]")
    shrunk = td / "shrunk.html"
    write_page(shrunk, ["p/a"], [])
    h2 = S.build_server(shrunk, answers, 0)
    try:
        check("an answer for a recording the rebuilt page dropped is kept, not deleted",
              "p/b" in h2.answers["labels"])
        check("and the page's own ids no longer include it", "p/b" not in h2.ids["labels"])
    finally:
        h2.server_close()

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
