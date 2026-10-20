#!/usr/bin/env python3
"""The Gemini resolver's tool gate allows web search and public page reads, and nothing else.

`agy_resolver_gate.py` is the PreToolUse hook the Gemini resolver's jail carries
(`.agents/hooks.json`). agy asks it before every tool step; an answer other than
allow refuses the step. It is the only thing that lets the resolver open a page,
because agy asks before reading a URL and a headless run cannot answer, and it is
what keeps the resolver from reading files or running commands.

These cases are what the gate must decide. The DNS lookup is injected, so no
network is touched; the last block runs the real script under the interpreter the
hook names, `/usr/bin/python3 -I`, because the hook runs as another macOS user
with no access to this repo's venv.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_resolver_gate as GATE  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def resolver_for(table: dict):
    """A getaddrinfo stand-in: host -> list of addresses; a missing host fails like DNS does."""
    def fake(host, *_a, **_k):
        if host not in table:
            raise OSError(f"no such host {host}")
        return [(2, 1, 6, "", (addr, 443)) for addr in table[host]]
    return fake


DNS = resolver_for({"example.com": ["93.184.215.14"], "www.sec.gov": ["23.2.13.75", "2600:1408:ec00::1"],
                    "intranet.example.org": ["10.1.2.3"], "rebind.example.net": ["93.184.215.14", "127.0.0.1"],
                    "vertexaisearch.cloud.google.com": ["142.250.1.1"], "web.archive.org": ["207.241.224.2"],
                    "www.google.com": ["142.250.1.2"], "t.co": ["104.244.42.1"]})
GROUND = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
#: Where each redirect link leads, as a Location header would say; None means "no redirect".
HOPS = {GROUND + "toOwn": "https://verbatim-predictions.tonygwu.com/p/1", GROUND + "toSec": "https://www.sec.gov/x",
        GROUND + "toLocal": "http://127.0.0.1:8765/", GROUND + "toT": "https://t.co/abc",
        "https://t.co/abc": "https://example.com/doc", "https://example.com/doc": None,
        "https://www.sec.gov/x": None, GROUND + "relative": "/elsewhere"}
for i in range(7):
    HOPS[GROUND + f"loop{i}"] = GROUND + f"loop{i + 1}"
for i in range(5):  # exactly five redirects, then a page
    HOPS[GROUND + f"five{i}"] = GROUND + f"five{i + 1}"
HOPS[GROUND + "five5"] = None
for i in range(6):  # six redirects: one more than allowed
    HOPS[GROUND + f"six{i}"] = GROUND + f"six{i + 1}"
HOPS[GROUND + "six6"] = None
HOPS[GROUND + "relative-ok"] = "/landing"            # a relative Location, resolved against the hop
HOPS["https://vertexaisearch.cloud.google.com/landing"] = None
FOLLOWED: list = []


def follow(url):
    FOLLOWED.append(url)
    if url == GROUND + "broken":
        raise OSError("connection reset")
    if url not in HOPS:
        raise OSError(f"no fake hop for {url}")
    return HOPS[url]


HOME_TMP = tempfile.TemporaryDirectory()
HOME = Path(HOME_TMP.name).resolve()
CONV = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"


def page_file(conv: str, step: str, name: str = "content.md") -> Path:
    f = HOME / ".gemini" / "antigravity-cli" / "brain" / conv / ".system_generated" / "steps" / step / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("<html>page</html>")
    return f


def decide(name, args=None, payload=None, conv=CONV):
    p = payload if payload is not None else {"toolCall": {"name": name, "args": args or {}}, "conversationId": conv}
    return GATE.decide(p, resolve=DNS, home=HOME, follow=follow)[:2]


def overrides(name, args):
    return GATE.decide({"toolCall": {"name": name, "args": args}, "conversationId": CONV}, resolve=DNS, home=HOME,
                       follow=follow)[2]


def url_call(url, key="Url"):
    return decide("read_url_content", {key: url})


# ---- allowed --------------------------------------------------------------
d, why = decide("search_web", {"query": "acme q3 revenue"})
check("search_web is allowed", d == "allow", f"{d} {why}")
d, why = url_call("https://example.com/report")
check("a public https page is allowed", d == "allow", f"{d} {why}")
d, why = url_call("http://www.sec.gov/Archives/x.htm")
check("a public http page whose names all resolve to public addresses is allowed", d == "allow", f"{d} {why}")
d, why = url_call("https://example.com/", key="url")
check("the URL argument is read under its lower-case key too", d == "allow", f"{d} {why}")
d, why = decide("search_web", {"query": "acme q3 revenue", "domain": "sec.gov"})
check("search_web restricted to another domain is allowed", d == "allow", f"{d} {why}")

# MEASURED 2026-10-20 in the third live probe: the hook's allow alone does not
# open a page. agy's own permission check still asks, a headless run cannot
# answer, and the run ended with no output. The hook grants the one host for the
# one call, through permissionOverrides, and grants nothing for anything else.
check("an allowed page read grants read_url for exactly its host",
      overrides("read_url_content", {"Url": "https://Example.COM./report"}) == ["read_url(example.com)"],
      str(overrides("read_url_content", {"Url": "https://Example.COM./report"})))
check("a search grants no permission", overrides("search_web", {"query": "q"}) == [],
      str(overrides("search_web", {"query": "q"})))
check("a refused page read grants no permission", overrides("read_url_content", {"Url": "http://127.0.0.1/"}) == [],
      str(overrides("read_url_content", {"Url": "http://127.0.0.1/"})))
check("a refused tool grants no permission", overrides("run_command", {"CommandLine": "ls"}) == [],
      str(overrides("run_command", {"CommandLine": "ls"})))

# ---- refused searches -----------------------------------------------------
# MEASURED 2026-10-20 in the first live probe: asked to read the predictions site,
# Gemini 4 Argon called search_web with domain "verbatim-predictions.tonygwu.com".
# The stream carries no search results, so a search aimed at the project's own
# sites is refused here, where it can be seen.
for args, label in [({"query": "acme", "domain": "verbatim-predictions.tonygwu.com"}, "a domain on the project's site"),
                    ({"query": "acme", "domain": "TonyGWu.com"}, "the project's domain in capitals"),
                    ({"query": "https://verbatim-predictions.tonygwu.com/"}, "a query naming the project's site"),
                    ({"query": "site:tonygwu.com acme"}, "a site: query on the project's domain"),
                    ({"query": ""}, "an empty query"),
                    ({"domain": "sec.gov"}, "no query"),
                    ({"query": ["a", "b"]}, "a query that is not a string")]:
    d, why = decide("search_web", args)
    check(f"search_web refuses {label}", d == "deny" and why, f"{d} {why!r}")

# ---- links that lead somewhere else ----------------------------------------
# Review of 2026-10-20: every search source comes as a Google redirect link, so a
# host check alone would let a link to the project's own site through. A link on a
# redirect host is followed, hop by hop, without fetching a page, and each hop is
# checked like the first. A link whose text names the project's site anywhere
# (an archive, a translation proxy, google.com/url?q=) is refused without a request.
FOLLOWED.clear()
d, why = url_call("https://example.com/report")
check("a page on an ordinary host is never followed", d == "allow" and FOLLOWED == [], f"{d} {why} {FOLLOWED}")
d, why = url_call(GROUND + "toSec")
check("a search link that leads to a public page is allowed", d == "allow", f"{d} {why}")
check("and the hop was looked up", FOLLOWED[-2:] == [GROUND + "toSec", "https://www.sec.gov/x"] or
      FOLLOWED[-1:] == [GROUND + "toSec"], str(FOLLOWED))
d, why = url_call(GROUND + "toT")
check("a chain through a second redirect host is followed to its end", d == "allow"
      and "https://t.co/abc" in FOLLOWED, f"{d} {why} {FOLLOWED}")
d, why = url_call(GROUND + "five0")
check("a chain of exactly MAX_HOPS redirects is allowed", d == "allow", f"{d} {why}")
d, why = url_call(GROUND + "six0")
check("a chain of MAX_HOPS + 1 redirects is refused", d == "deny" and why, f"{d} {why}")
d, why = url_call(GROUND + "relative-ok")
check("a relative Location is resolved against the hop it came from", d == "allow"
      and "https://vertexaisearch.cloud.google.com/landing" in FOLLOWED, f"{d} {why} {FOLLOWED[-3:]}")
for link, label in [(GROUND + "toOwn", "a search link that leads to the project's site"),
                    (GROUND + "toLocal", "a search link that leads to a loopback address"),
                    (GROUND + "loop0", "a chain of more than five redirects"),
                    (GROUND + "broken", "a link whose target cannot be read (fail closed)"),
                    (GROUND + "relative", "a relative Location on the redirect host, followed and not answered")]:
    d, why = url_call(link)
    check(f"read_url_content refuses {label}", d == "deny" and why, f"{d} {why!r}")
FOLLOWED.clear()
for url, label in [
    ("https://web.archive.org/web/2026/https://verbatim-predictions.tonygwu.com/p/1", "an archive copy of the site"),
    ("https://verbatim--predictions-tonygwu-com.translate.goog/p/1", "a translation proxy of the site"),
    ("https://www.google.com/url?q=https%3A%2F%2Fverbatim-predictions.tonygwu.com%2Fp", "a google.com/url wrapper"),
    ("https://example.com/?u=https%253A%252F%252Fpundits.tonygwu.com", "a twice-encoded mention in a query"),
]:
    d, why = url_call(url)
    check(f"read_url_content refuses {label}, without a request", d == "deny" and why, f"{d} {why!r}")
check("none of those was looked up", FOLLOWED == [], str(FOLLOWED))
for q, label in [("verbatim-predictions%2Etonygwu%2Ecom", "an encoded mention"), ("tonygwu-com acme", "the proxy form")]:
    d, why = decide("search_web", {"query": q})
    check(f"search_web refuses {label} of the project's domain", d == "deny" and why, f"{d} {why!r}")

# ---- refused page reads ---------------------------------------------------
for url, label in [
    ("file:///Users/tonygwu/Code/misc/verbatim-index/data/predictions/scoring.json", "a file:// URL"),
    ("http://localhost:8765/", "localhost"),
    ("http://127.0.0.1:8765/", "a loopback address"),
    ("http://[::1]:8765/", "an IPv6 loopback literal"),
    ("http://169.254.169.254/latest/meta-data/", "a link-local metadata address"),
    ("http://192.168.1.10/", "a private IPv4 literal"),
    ("https://intranet.example.org/", "a name that resolves to a private address"),
    ("https://rebind.example.net/", "a name with one public and one loopback address"),
    ("https://nowhere.invalid/", "a name that does not resolve (fail closed)"),
    ("https://verbatim-predictions.tonygwu.com/", "this project's public predictions site"),
    ("https://verbatim-index.tonygwu.com/", "this project's public leaderboard"),
    ("https://pundits.tonygwu.com/", "this project's public pundits site"),
    ("https://TONYGWU.COM./x", "the project's domain written in capitals with a trailing dot"),
    ("https://user:pw@example.com/", "a URL carrying credentials"),
    ("ftp://example.com/x", "a non-web scheme"),
    ("https:///nohost", "a URL with no host"),
    ("not a url", "text that is not a URL"),
]:
    d, why = url_call(url)
    check(f"read_url_content refuses {label}", d == "deny" and why, f"{d} {why!r}")
d, why = decide("read_url_content", {"Other": "https://example.com/"})
check("read_url_content with no URL argument is refused", d == "deny", f"{d} {why}")
d, why = decide("read_url_content", {"Url": ["https://example.com/"]})
check("a URL argument that is not a string is refused", d == "deny", f"{d} {why}")

# ---- page files: view_file reads only a page this conversation fetched ----
# MEASURED 2026-10-20 in the seventh and eighth live probes: read_url_content
# returns no body text. It saves the page to
# <home>/.gemini/antigravity-cli/brain/<conversation>/.system_generated/steps/<n>/content.md
# and tells the model to open that file with view_file.
mine = page_file(CONV, "4")
d, why = decide("view_file", {"AbsolutePath": str(mine)})
check("view_file may open a page this conversation fetched", d == "allow", f"{d} {why}")
d, why = decide("read_file", {"Path": str(mine)})
check("read_file, agy's model-facing name, may open it with Path", d == "allow", f"{d} {why}")
d, why = decide("read_file", {"Path": "/etc/hosts"})
check("read_file refuses any other file", d == "deny" and why, f"{d} {why}")
d, why = decide("view_file", {"AbsolutePath": str(mine), "StartLine": 1, "EndLine": 80})
check("view_file with a line range may open it too", d == "allow", f"{d} {why}")
check("opening a fetched page grants no permission", overrides("view_file", {"AbsolutePath": str(mine)}) == [],
      str(overrides("view_file", {"AbsolutePath": str(mine)})))
theirs = page_file(OTHER, "4")
transcript = page_file(CONV, "x", "transcript.jsonl").parent.parent.parent / "logs" / "transcript_full.jsonl"
transcript.parent.mkdir(parents=True, exist_ok=True)
transcript.write_text("{}")
outside = HOME / "secret.md"
outside.write_text("no")
link = page_file(CONV, "6")
link.unlink()
link.symlink_to(outside)
for args, label, conv in [
    ({"AbsolutePath": str(theirs)}, "a page another conversation fetched", CONV),
    ({"AbsolutePath": str(page_file(CONV, "4", "output.txt"))}, "a step file that is not content.md", CONV),
    ({"AbsolutePath": str(page_file(CONV, "abc"))}, "a step folder that is not a step number", CONV),
    ({"AbsolutePath": str(transcript)}, "this conversation's transcript", CONV),
    ({"AbsolutePath": str(mine.parent / ".." / ".." / ".." / ".." / OTHER / ".system_generated" / "steps" / "4"
                           / "content.md")}, "a path that climbs out with ..", CONV),
    ({"AbsolutePath": str(link)}, "a content.md that is a symlink out", CONV),
    ({"AbsolutePath": str(mine.parent / "9" / "content.md")}, "a page file that does not exist", CONV),
    ({"AbsolutePath": "/Users/tonygwu/Code/misc/verbatim-index/data/predictions/scoring.json"}, "a data file", CONV),
    ({"AbsolutePath": str(mine)}, "a page, when the payload names another conversation", OTHER),
    ({"AbsolutePath": str(mine)}, "a page, when the payload names no conversation", None),
    ({"AbsolutePath": "content.md"}, "a relative path", CONV),
    ({"Other": str(mine)}, "no path argument", CONV),
]:
    d, why = decide("view_file", args, conv=conv)
    check(f"view_file refuses {label}", d == "deny" and why, f"{d} {why!r}")

# ---- refused tools --------------------------------------------------------
for tool in ("run_command", "list_dir", "grep_search", "find_by_name", "write_to_file",
             "browser_subagent", "open_browser_url", "mcp_tool", "manage_subagents", "codesearch", "", "SEARCH_WEB"):
    d, why = decide(tool, {"AbsolutePath": "/Users/tonygwu/Code/misc/verbatim-index/data"})
    check(f"tool {tool!r} is refused", d == "deny" and why, f"{d} {why!r}")

# ---- malformed payloads ---------------------------------------------------
for payload, label in [({}, "no toolCall"), ({"toolCall": "search_web"}, "toolCall not an object"),
                       ({"toolCall": {"args": {}}}, "no tool name"), ([], "a list, not an object")]:
    d, why, _grants = GATE.decide(payload, resolve=DNS, home=HOME, follow=follow)
    check(f"a payload with {label} is refused", d == "deny", f"{d} {why}")

# ---- the real script, under the interpreter the hook names ----------------
script = Path(GATE.__file__).resolve()
py = Path("/usr/bin/python3")
if not py.exists():
    check("/usr/bin/python3 exists, the interpreter hooks.json names", False, "missing")
else:
    with tempfile.TemporaryDirectory() as tmp:
        def run(stdin: str):
            return subprocess.run([str(py), "-I", str(script)], input=stdin, capture_output=True, text=True,
                                  cwd=tmp, timeout=60)
        p = run(json.dumps({"toolCall": {"name": "search_web", "args": {"query": "q"}}}))
        out = json.loads(p.stdout or "{}")
        check("the script answers allow for search_web under /usr/bin/python3 -I", p.returncode == 0
              and out.get("decision") == "allow", f"rc={p.returncode} out={p.stdout!r} err={p.stderr[-300:]!r}")
        p = run(json.dumps({"toolCall": {"name": "read_url_content", "args": {"Url": "http://127.0.0.1:1/"}}}))
        out = json.loads(p.stdout or "{}")
        check("the script refuses a loopback page with no permission override", out.get("decision") == "deny"
              and "permissionOverrides" not in out, p.stdout)
        p = run(json.dumps({"toolCall": {"name": "view_file", "args": {"AbsolutePath": "/etc/hosts"}}}))
        out = json.loads(p.stdout or "{}")
        check("the script answers deny with a reason for view_file", out.get("decision") == "deny"
              and out.get("reason"), p.stdout)
        p = run("this is not json")
        out = json.loads(p.stdout or "{}")
        check("unreadable input is answered deny, never left unanswered", p.returncode == 0
              and out.get("decision") == "deny", f"rc={p.returncode} out={p.stdout!r}")
        log = Path(tmp) / GATE.LOG_NAME
        lines = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
        check("every decision is logged beside hooks.json, in order", [x.get("decision") for x in lines]
              == ["allow", "deny", "deny", "deny"], str(lines)[:400])
        check("a logged decision names the tool", [x.get("tool") for x in lines][:3]
              == ["search_web", "read_url_content", "view_file"], str(lines)[:400])
        check("each logged decision records how long the gate took, so a slow hook shows in the pilot",
              all(isinstance(x.get("seconds"), (int, float)) and x["seconds"] >= 0 for x in lines), str(lines)[:400])

# ---- the Stop hook copies this conversation's transcript into the jail ----
# The transcript is the one record of what the judge's searches returned: the
# stream carries the queries only. It lives under the call's macOS user's home,
# which this repo's user cannot read, so the Stop hook copies it beside hooks.json.
with tempfile.TemporaryDirectory() as tmp:
    page_file(CONV, "2")
    full = HOME / ".gemini" / "antigravity-cli" / "brain" / CONV / ".system_generated" / "logs" / "transcript_full.jsonl"
    full.write_text('{"step_index": 0}\n')
    out = GATE.stop(json.dumps({"conversationId": CONV, "transcriptPath": str(full.parent / "transcript.jsonl")}),
                    home=HOME, cwd=Path(tmp))
    copied = Path(tmp) / f"transcript_full.{CONV}.jsonl"
    check("the Stop hook copies this conversation's full transcript", copied.exists()
          and copied.read_text() == full.read_text(), str(sorted(p.name for p in Path(tmp).iterdir())))
    check("the Stop hook lets the run stop", out.get("decision") != "continue", str(out))
    out = GATE.stop(json.dumps({"conversationId": "../" + OTHER}), home=HOME, cwd=Path(tmp))
    check("a conversation id that is not a bare id copies nothing",
          sorted(p.name for p in Path(tmp).glob("transcript_full.*")) == [copied.name]
          and out.get("decision") != "continue", str(out))
    stops = [json.loads(x) for x in (Path(tmp) / GATE.LOG_NAME).read_text().splitlines()]
    check("each Stop is logged with what it copied", [x.get("copied") for x in stops] == [copied.name, None],
          str(stops))
    out = GATE.stop("not json", home=HOME, cwd=Path(tmp))
    check("an unreadable Stop payload still lets the run stop", out.get("decision") != "continue", str(out))

# ---- the hooks.json the jail carries --------------------------------------
cfg = GATE.hooks_config()
groups = cfg[GATE.HOOK_NAME]["PreToolUse"]
check("hooks.json gates every tool (matcher *)", [g["matcher"] for g in groups] == ["*"], str(groups))
check("hooks.json runs this script with /usr/bin/python3 -I", groups[0]["hooks"][0]["command"]
      == f"/usr/bin/python3 -I ./{GATE.SCRIPT_NAME}", str(groups))
check("hooks.json gives the gate time for its worst case: every hop, HEAD then GET, each timing out",
      groups[0]["hooks"][0]["timeout"] >= (GATE.MAX_HOPS + 1) * 2 * GATE.HOP_TIMEOUT_S + 10, str(groups))

# ---- follow_redirect against a real local server ----------------------------
# Review round 2: a 503 or 429 to HEAD made the hook pass the link unchecked,
# and agy's own fetch a moment later could follow the redirect. A redirect host
# that will not say where a link leads is now a link the gate cannot see through.
import http.server  # noqa: E402
import threading  # noqa: E402


def serve(head_code, get_code, location="https://verbatim-predictions.tonygwu.com/p"):
    class H(http.server.BaseHTTPRequestHandler):
        def _answer(self, code):
            self.send_response(code)
            if 300 <= code < 400:
                self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_HEAD(self):
            self._answer(head_code)

        def do_GET(self):
            self._answer(get_code)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/x"


for head, get, want, label in [(302, 302, "location", "a redirect answers its Location"),
                               (405, 302, "location", "a HEAD the host refuses is retried with GET"),
                               (200, 302, None, "a page that answers is the end of the chain"),
                               (404, 404, None, "a missing page is the end of the chain"),
                               (503, 302, "location", "a 503 to HEAD is retried with GET, and its redirect is checked"),
                               (503, 503, "raise", "a 503 to both is a link the gate cannot see through"),
                               (429, 429, "raise", "a 429 is a link the gate cannot see through"),
                               (500, 500, "raise", "a 500 is a link the gate cannot see through")]:
    srv, url = serve(head, get)
    try:
        try:
            got = GATE.follow_redirect(url, redirect_hosts=())
        except OSError as exc:
            got = "raise"
        if got not in (None, "raise"):
            got = "location"
        check(f"follow_redirect: {label}", got == want, f"HEAD {head} GET {get}: {got}")
    finally:
        srv.shutdown()
import inspect  # noqa: E402
check("production follow_redirect applies the 401/403 rule to the real redirect hosts",
      inspect.signature(GATE.follow_redirect).parameters["redirect_hosts"].default is GATE.REDIRECT_HOSTS,
      str(inspect.signature(GATE.follow_redirect)))
# Review round 3: a redirect host that answers 401 or 403 will not say where its
# link leads, so the link is refused. A final page's 403 still ends the chain:
# that page's own address is the one already checked.
for head, get, hosts, want, label in [
        (403, 403, ("127.0.0.1",), "raise", "a redirect host's 403 is a link the gate cannot see through"),
        (401, 401, ("127.0.0.1",), "raise", "a redirect host's 401 is a link the gate cannot see through"),
        (403, 403, (), None, "a final page's 403 ends the chain")]:
    srv, url = serve(head, get)
    try:
        try:
            got = GATE.follow_redirect(url, redirect_hosts=hosts)
        except OSError:
            got = "raise"
        check(f"follow_redirect: {label}", got == want, f"HEAD {head} GET {get} hosts {hosts}: {got}")
    finally:
        srv.shutdown()
check("hooks.json runs the Stop copy with the same script", [h["command"] for h in cfg[GATE.HOOK_NAME]["Stop"]]
      == [f"/usr/bin/python3 -I ./{GATE.SCRIPT_NAME} --stop"], str(cfg))

# ---- the agent the jail carries -------------------------------------------
md = GATE.agent_markdown()
front = md.split("---")[1]
check("the agent names itself", f"name: {GATE.AGENT_NAME}" in front, front)
check("the agent declares exactly the three tools the gate can allow",
      [ln.strip()[2:] for ln in front.splitlines() if ln.strip().startswith("- ")]
      == ["search_web", "read_url_content", "read_file"], front)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
