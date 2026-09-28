#!/usr/bin/env python3
"""Fetch routes other than a plain GET, for sources a plain GET cannot read.

Round 3 of the supplemental sweep (2026-09-27) met five page shapes that the
round-1 fetcher could only refuse:

  sec.gov EDGAR          403 to our User-Agent
  happyscribe            403 behind a Cloudflare check
  palantir.com letters   200, but the text lives in embedded script data, so
                         the page reads as 7 words and fails MIN_WORDS
  web.archive.org        the Wayback toolbar is injected into the page
  paywalled previews     the discovery agent marked access "partial"

The fixes, each opt-in or narrowly keyed, and each checked here:

1. A Wayback URL is fetched with the `id_` flag, which returns the archived
   bytes WITHOUT the injected toolbar. The record names the URL requested.
2. `--reader-fallback`: when the direct route fails with a recoverable reason,
   the page is fetched once through the r.jina.ai reader in HTML mode, and that
   HTML goes through the SAME html_to_text and assert_verbatim as any page. The
   record says which route produced it and why the direct one failed. A reader
   answer that is itself a challenge page fails MIN_WORDS and is reported with
   BOTH reasons, never written.
3. `--allow-partial-access` admits a source the agent marked access "partial".
   It is off by default, and the record carries the declared access.
4. A page whose visible text is under MIN_WORDS and which carries Contentful
   rich text in `__NEXT_DATA__` is read from that data (palantir.com letters;
   the reader served the same unrendered shell for three of four). A flat walk
   of every text node cross-checks the renderer, as assert_verbatim does.
5. assert_verbatim's naive strip ended a tag at the first ">" even inside a
   quoted attribute, so pages carrying JSON in data-* attributes
   (huggingface.co, cnn.com) were refused although the extraction was correct.

MEASURED on round 3 (104 sources): written 73 with the old fetcher, 94 with
these routes; the reader route wrote 15, the Wayback id_ route 1, rich text 4.

A fake fetcher stands in for the network, so this spends nothing.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_web_sources as F  # noqa: E402

checks = 0
failures: list[str] = []


def check(label: str, got, want) -> None:
    global checks
    checks += 1
    if got != want:
        failures.append(f"{label}\n     got  {got!r}\n     want {want!r}")


def run(label: str, fn):
    """Call fn, turning an exception into a recorded failure, not a crash."""
    global checks
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        checks += 1
        failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
        return None


BODY = " ".join(f"word{i}" for i in range(600))
QUOTE = "We will ship the new runtime to every customer by the end of 2024."
ARTICLE = f"<html><body><article><p>{QUOTE}</p><p>{BODY}</p></article></body></html>"
JS_SHELL = ('<html><body><div id="root"></div><script id="__NEXT_DATA__">'
            f'{{"text": "{QUOTE} {BODY}"}}</script></body></html>')
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Checking</body></html>"


class Resp:
    def __init__(self, status: int, html: str, ctype: str = "text/html") -> None:
        self.status_code = status
        self.text = html
        self.content = html.encode()
        self.headers = {"content-type": ctype}


class FakeFetcher:
    def __init__(self, direct: dict[str, Resp], reader: dict[str, Resp]) -> None:
        self.direct, self.reader = direct, reader
        self.direct_calls: list[str] = []
        self.reader_calls: list[str] = []

    def get(self, url: str) -> Resp:
        self.direct_calls.append(url)
        return self.direct[url]

    def get_reader(self, url: str) -> Resp:
        self.reader_calls.append(url)
        return self.reader[url]


def failure_category(fn) -> str | None:
    try:
        fn()
    except F.FetchFailure as exc:
        return exc.category
    return None


# --- 1. Wayback: request the original bytes, not the toolbar-wrapped page -------
WB = "http://web.archive.org/web/20250904162814/https://example.com/ep-82"
WB_ID = "http://web.archive.org/web/20250904162814id_/https://example.com/ep-82"
check("wayback url rewritten to id_", run("wayback rewrite", lambda: F.wayback_original_bytes_url(WB)), WB_ID)
check("wayback id_ url left alone", run("wayback id_", lambda: F.wayback_original_bytes_url(WB_ID)), WB_ID)
check("non-wayback url is not rewritten",
      run("non-wayback", lambda: F.wayback_original_bytes_url("https://example.com/a")), None)

fake = FakeFetcher({WB_ID: Resp(200, ARTICLE)}, {})
got = run("acquire wayback", lambda: F.acquire(fake, WB, reader_fallback=False))
if got is not None:
    check("wayback: the id_ url is what was requested", fake.direct_calls, [WB_ID])
    check("wayback: route named", got["route"], "wayback_id_")
    check("wayback: request_url recorded", got["request_url"], WB_ID)
    check("wayback: quote survives", QUOTE in got["text"], True)

# --- 2. reader fallback ---------------------------------------------------------
U403 = "https://www.sec.gov/Archives/x.htm"
fake = FakeFetcher({U403: Resp(403, "Forbidden")}, {U403: Resp(200, ARTICLE, "text/plain")})
check("403 without --reader-fallback is refused as http_403",
      run("403 no fallback", lambda: failure_category(lambda: F.acquire(fake, U403, reader_fallback=False))),
      "http_403")
check("403 without --reader-fallback never touches the reader", fake.reader_calls, [])

fake = FakeFetcher({U403: Resp(403, "Forbidden")}, {U403: Resp(200, ARTICLE, "text/plain")})
got = run("acquire 403 with fallback", lambda: F.acquire(fake, U403, reader_fallback=True))
if got is not None:
    check("403 + fallback: reader asked for the ORIGINAL url", fake.reader_calls, [U403])
    check("403 + fallback: route names the reader", got["route"], F.READER_ROUTE)
    check("403 + fallback: direct failure recorded", got["direct_failure"], "http_403")
    check("403 + fallback: reader HTML goes through html_to_text, not treated as text/plain",
          QUOTE in got["text"] and "<p>" not in got["text"], True)

UJS = "https://www.palantir.com/letter/"
fake = FakeFetcher({UJS: Resp(200, JS_SHELL)}, {UJS: Resp(200, ARTICLE, "text/plain")})
got = run("acquire js shell", lambda: F.acquire(fake, UJS, reader_fallback=True))
if got is not None:
    check("js shell: too_short direct falls back", got["direct_failure"], "too_short")
    check("js shell: reader text used", QUOTE in got["text"], True)

UCF = "https://podcasts.happyscribe.com/x"
fake = FakeFetcher({UCF: Resp(403, CHALLENGE)}, {UCF: Resp(200, CHALLENGE, "text/plain")})
check("reader returning a challenge page is refused, naming both reasons",
      run("challenge", lambda: failure_category(lambda: F.acquire(fake, UCF, reader_fallback=True))),
      "http_403+reader_too_short")

# The verbatim guard must run on the READER's bytes too. Break it and the reader
# route must refuse rather than write.
real_assert = F.assert_verbatim


def refuse(raw, text):
    raise ValueError("forced divergence")


F.assert_verbatim = refuse
fake = FakeFetcher({U403: Resp(403, "Forbidden")}, {U403: Resp(200, ARTICLE, "text/plain")})
check("reader route is still held to assert_verbatim",
      run("verbatim on reader", lambda: failure_category(lambda: F.acquire(fake, U403, reader_fallback=True))),
      "http_403+reader_not_verbatim")
F.assert_verbatim = real_assert

# A direct success must not consult the reader at all.
UOK = "https://example.com/ok"
fake = FakeFetcher({UOK: Resp(200, ARTICLE)}, {})
got = run("acquire direct ok", lambda: F.acquire(fake, UOK, reader_fallback=True))
if got is not None:
    check("direct ok: route direct", got["route"], "direct")
    check("direct ok: no direct_failure", got["direct_failure"], None)
    check("direct ok: reader untouched", fake.reader_calls, [])

# --- 3. partial access ------------------------------------------------------------
PARTIAL = {"url": UOK, "access": "partial", "full_text_available": False,
           "first_person_verified": True}
check("partial access refused by default, with the pre-existing reason",
      run("usable default", lambda: F.usable(PARTIAL)), (False, "agent_said_no_full_text"))
check("partial access with full text also refused by default",
      run("usable default ft", lambda: F.usable({**PARTIAL, "full_text_available": True})),
      (False, "access_partial"))
check("partial access admitted when asked",
      run("usable partial", lambda: F.usable(PARTIAL, allow_partial=True)), (True, ""))
check("allow_partial does not admit an unverified speaker",
      run("usable unverified", lambda: F.usable({**PARTIAL, "first_person_verified": False},
                                                allow_partial=True)),
      (False, "identity_not_verified"))
check("allow_partial does not admit a closed page",
      run("usable closed", lambda: F.usable({**PARTIAL, "access": "paywalled"}, allow_partial=True)),
      (False, "agent_said_no_full_text"))
check("allow_partial does not admit a closed page that claims full text",
      run("usable closed ft", lambda: F.usable({**PARTIAL, "access": "paywalled",
                                                "full_text_available": True}, allow_partial=True)),
      (False, "access_paywalled"))

# --- 4. the record says how it was fetched ---------------------------------------
fake = FakeFetcher({U403: Resp(403, "Forbidden")}, {U403: Resp(200, ARTICLE, "text/plain")})
got = run("acquire for record", lambda: F.acquire(fake, U403, reader_fallback=True))
if got is not None:
    rec = run("record_for", lambda: F.record_for(
        {**PARTIAL, "url": U403, "speech_date": "2024-01-02", "speech_date_basis": "stated_in_page"},
        "someone", got["text"], got["how"], got["resp"], run="round3", acquired=got))
    if rec is not None:
        check("record: fetch_route", rec.get("fetch_route"), F.READER_ROUTE)
        check("record: request_url is the reader url", rec.get("request_url"), F.READER_PREFIX + U403)
        check("record: direct_failure", rec.get("direct_failure"), "http_403")
        check("record: declared access carried", rec.get("access_declared"), "partial")
        check("record: url stays the ORIGINAL", rec.get("url"), U403)

# --- 5. Next.js shells whose body is rich-text script data (palantir.com) --------
import json as _json  # noqa: E402

import web_source_text as W  # noqa: E402


def para(*nodes):
    return {"nodeType": "paragraph", "data": {}, "content": list(nodes)}


def txt(v, marks=()):
    return {"nodeType": "text", "value": v, "marks": [{"type": m} for m in marks], "data": {}}


LINKED = {"nodeType": "hyperlink", "data": {"uri": "https://x"}, "content": [txt("our platform")]}
DOC = {"nodeType": "document", "data": {}, "content": [
    para(txt("August 7, 2023", ("italic",))),
    para(txt("We expect to remain profitable "), txt("on both a quarterly and annual basis", ("bold",)),
         txt(" this year, and to grow "), LINKED, txt(".")),
    para(txt(BODY)),
]}
NEXT = {"props": {"pageProps": {
    "page": {"fields": {"blocks": [{"fields": {"text": DOC}}]}},
    # the same document again, where the real page repeats it; must not be read twice
    "metadata": {"page": {"fields": {"blocks": [{"fields": {"text": DOC}}]}}},
}}}
SHELL = ('<html><body><div id="__next"><p>Loading</p></div>'
         f'<script id="__NEXT_DATA__" type="application/json">{_json.dumps(NEXT)}</script></body></html>')
SENTENCE = ("We expect to remain profitable on both a quarterly and annual basis this year, "
            "and to grow our platform.")

rich = run("richtext render", lambda: W.next_data_richtext(SHELL))
if rich is not None:
    check("richtext: inline marks and hyperlinks keep every word, in order", SENTENCE in rich, True)
    check("richtext: blocks become paragraphs", rich.startswith("August 7, 2023\n\nWe expect"), True)
    check("richtext: the metadata copy is not read twice", rich.count("August 7, 2023"), 1)
check("richtext: a page with no __NEXT_DATA__ is None, not an error",
      run("richtext none", lambda: W.next_data_richtext(ARTICLE)), None)

# A text node the renderer cannot reach, under a key other than `content`,
# must make the self-check refuse rather than return a letter with a hole.
HIDDEN = {"props": {"pageProps": {"page": {"fields": {"blocks": [{"fields": {
    "text": DOC, "sidebar": {"items": [txt("A sentence the renderer never visits.")]}}}]}}}}}
HSHELL = f'<script id="__NEXT_DATA__" type="application/json">{_json.dumps(HIDDEN)}</script>'
try:
    W.next_data_richtext(HSHELL)
    checks += 1
    failures.append("richtext: an unreachable text node did not make the self-check raise")
except Exception as exc:  # noqa: BLE001
    checks += 1
    if not (isinstance(exc, ValueError) and "not verbatim" in str(exc)):
        failures.append(f"richtext: wanted the verbatim refusal, got {type(exc).__name__}: {exc}")

got = run("extract shell", lambda: F.extract(Resp(200, SHELL)))
if got is not None:
    check("extract: a too-short shell with rich text reads the rich text",
          (SENTENCE in got[0], got[1]), (True, "web_source_text.next_data_richtext"))
got = run("extract normal", lambda: F.extract(Resp(200, ARTICLE)))
if got is not None:
    check("extract: a normal page keeps its route", got[1], "web_source_text.html_to_text")

# --- 6. assert_verbatim and a ">" inside a quoted attribute ----------------------
ATTR_PAGE = ('<html><body><div class="post" data-props=\'{"note": "a > b", "html": "<span>x</span>"}\'>'
             f'<p>{QUOTE}</p><p>{BODY}</p></div></body></html>')
try:
    W.assert_verbatim(ATTR_PAGE, W.html_to_text(ATTR_PAGE))
    checks += 1
except Exception as exc:  # noqa: BLE001
    checks += 1
    failures.append(f"assert_verbatim refused a correct extraction of a page with '>' in a "
                    f"quoted attribute: {str(exc)[:160]}")
# ...and it still refuses a real loss of text on the same page shape.
try:
    W.assert_verbatim(ATTR_PAGE, W.html_to_text(ATTR_PAGE).replace(QUOTE, ""))
    checks += 1
    failures.append("assert_verbatim accepted an extraction missing a sentence")
except ValueError:
    checks += 1

if failures:
    print(f"FAIL {len(failures)} of {checks} checks")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"ok {checks} checks")
