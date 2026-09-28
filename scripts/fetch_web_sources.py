#!/usr/bin/env python3
"""Fetch supplemental web sources and write them as transcript records.

Input is the findings written by the discovery agents under a run directory.
Output is one transcript-shaped JSON per source, which
`extract_predictions.py --transcripts <dir>` reads with no change at all. The
point of that shape is that a supplemental source goes through the SAME five
gates, the same two model families and the same mechanical quote grounding as
every YouTube transcript already in the corpus.

WHAT THIS REFUSES, rather than working around:

  robots.txt disallow      skipped, recorded, never fetched
  a non-200 response       failure, no record written
  a page under MIN_WORDS   failure; a nav-only page is a fetch bug, not a source
  a non-verbatim extract   failure; see web_source_text.assert_verbatim
  a date with a bad basis  failure; a date we cannot say how we know is worse
                           than no date at all. This repo has paid twice for a
                           silently invented one.

A MISSING date is NOT a failure. Such a record is written with basis "unknown"
and counted as `dateless`. It cannot carry a horizon or a market cutoff, and
every downstream stage already handles that. Rejecting them instead dropped six
of Sergey Brin's seven sources, which is a bias and not a detail.

Every outcome is counted and reported by name, per leader. A silent skip here
would read downstream as "this leader had little to say", which is the exact
wrong conclusion and the one the whole run exists to test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.robotparser as robotparser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import predictions_lib as L  # noqa: E402
from web_source_text import (assert_verbatim, html_to_text, letter_stream,  # noqa: E402
                             next_data_richtext)

UA = ("verbatim-index-research/0.1 (+https://verbatim-index.tonygwu.com; "
      "contact 446441+tonygwu@users.noreply.github.com)")

# A transcript under this is not a transcript. Chosen because the shortest real
# source in the existing corpus is about 3k words and a page that yields a few
# hundred is nav furniture, a paywall stub or a cookie wall. Reported when it
# bites, per leader, because a cap that silently drops one person's material is
# a bias and not a detail.
MIN_WORDS = 400

# Politeness. One request per host per interval, serial across the whole run.
PER_HOST_INTERVAL_S = 2.0

DATE_BASES = {"stated_in_page", "publication_date"}

PDFTOTEXT = shutil.which("pdftotext")

# THE READER ROUTE, opt-in with --reader-fallback. Some hosts refuse a plain
# GET (sec.gov EDGAR and happyscribe answer 403; happyscribe sits behind a
# Cloudflare check) and some serve a JavaScript shell whose text lives in
# embedded script data (palantir.com letters read as 7 words). The r.jina.ai
# reader renders the page in a browser, and `X-Return-Format: html` makes it
# hand back the rendered HTML rather than its own markdown rewrite. That HTML
# then goes through the SAME html_to_text and assert_verbatim as any page, so
# the reader is a transport, never an editor: a quote still has to appear
# verbatim in text this module extracted itself. robots.txt is still checked
# against the ORIGIN host before either route runs. The record names the route,
# the URL actually requested and why the direct route failed.
READER_PREFIX = "https://r.jina.ai/"
READER_ROUTE = "reader:r.jina.ai(x-return-format=html)"
READER_HOST = "r.jina.ai"
# The reader's free tier allows about 20 requests a minute without a key.
READER_INTERVAL_S = 3.5

# Direct failures the reader may recover. A missing pdftotext is NOT here: that
# is this machine's defect and the reader would only hide it.
READER_RECOVERABLE_PREFIXES = ("http_", "fetch_error", "too_short", "not_verbatim")

# A Wayback URL. The `id_` flag after the timestamp returns the archived bytes
# as captured, without the toolbar and rewritten links Wayback injects into the
# page, which would otherwise become part of the "transcript".
_WAYBACK = re.compile(r"^(https?://web\.archive\.org/web/)(\d{4,14})(?:[a-z]{2}_)?/(.+)$")


def wayback_original_bytes_url(url: str) -> str | None:
    """The `id_` form of a Wayback URL, or None for any other URL."""
    m = _WAYBACK.match(url)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}id_/{m.group(3)}"


class FetchFailure(Exception):
    """One named taxonomy category for a source that produced no record."""

    def __init__(self, category: str, detail: str = "") -> None:
        super().__init__(f"{category}: {detail}" if detail else category)
        self.category = category
        self.detail = detail


class NotVerbatim(ValueError):
    pass


def pdf_to_text(data: bytes) -> tuple[str, str]:
    """Verbatim text from a PDF, cross-checked by two extraction modes.

    `pdftotext` is an external binary (poppler), not a Python dependency, so it
    adds nothing to requirements.txt and does not diverge any clone's
    environment. If it is absent this raises, and the caller records a named
    taxonomy entry. It must never degrade to "skip the PDFs", because the best
    supplemental sources found for several leaders ARE PDFs: shareholder
    letters, written testimony and investor-relations transcripts.

    Returns (text, order_verdict). The cross-check replaces assert_verbatim,
    which needs source markup to compare against. Default mode and -layout mode
    lay text out differently and must agree on the multiset of alphanumeric
    characters. Disagreeing on ORDER alone is survivable and flagged; see the
    comment at the check itself. Disagreeing on CONTENT raises.
    """
    if PDFTOTEXT is None:
        raise RuntimeError(
            "pdftotext is not installed; PDFs cannot be read verbatim. "
            "Install poppler (brew install poppler) rather than skipping them.")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.pdf"
        src.write_bytes(data)
        outs = {}
        for mode, flags in (("plain", []), ("layout", ["-layout"])):
            dest = Path(td) / f"{mode}.txt"
            proc = subprocess.run(
                [PDFTOTEXT, "-enc", "UTF-8", *flags, str(src), str(dest)],
                capture_output=True, text=True)
            if proc.returncode != 0:
                raise NotVerbatim(f"pdftotext {mode} failed: {proc.stderr.strip()[:200]}")
            outs[mode] = dest.read_text(encoding="utf-8", errors="replace")
    a, b = letter_stream(outs["plain"]), letter_stream(outs["layout"])
    order = "modes_agree"
    if a != b:
        # Two different disagreements, and only one of them is a loss of text.
        #
        # SAME characters, different ORDER. A designed PDF with pull-quotes or
        # sidebars is read differently by the two modes: on the Stripe 2025
        # letter, plain mode hoists the pull-quote "At heart, competitive
        # markets are a sorting machine" above the real opening "Dear Stripe
        # community". Nothing is lost, so the quotes are still verbatim and
        # still ground. `-layout` follows the physical page, which is the
        # author's intended reading order, so it is preferred and the record is
        # FLAGGED. The residual risk is real and bounded: a 400-word context
        # window may cross a pull-quote boundary, so the verifier could read
        # slightly out-of-order context. That is recorded, not assumed away.
        #
        # DIFFERENT characters means text was lost or invented, and no reading
        # of it is safe.
        if sorted(a) != sorted(b):
            i = 0
            while i < min(len(a), len(b)) and a[i] == b[i]:
                i += 1
            raise NotVerbatim(
                f"pdf extraction modes disagree on CONTENT at character {i} "
                f"({len(a)} plain against {len(b)} layout): "
                f"plain={a[max(0, i - 30):i + 30]!r} layout={b[max(0, i - 30):i + 30]!r}")
        order = "layout_preferred_modes_reordered"
    text = outs["layout" if order != "modes_agree" else "plain"]
    # Same whitespace normalisation as the HTML path. Words are untouched.
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(), order


def looks_like_pdf(resp: requests.Response) -> bool:
    ctype = (resp.headers.get("content-type") or "").lower()
    return "application/pdf" in ctype or resp.content[:5] == b"%PDF-"


_HEADER_CHARSET = re.compile(r"""charset\s*=\s*["']?([^;"'\s]+)""", re.IGNORECASE)
_META_CHARSET = re.compile(rb"""<meta\b[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)


def decode_html(resp) -> tuple[str, str, str]:
    """(html, charset, basis). Never `resp.text`, and never errors="replace".

    requests decodes a text/html body with no charset in the HTTP header as
    ISO-8859-1. Pages that declare UTF-8 only in <meta charset> then became
    mojibake, "we’ve" as "weâ\x80\x99ve", and a model's quote cannot ground
    against that. Found on 13 of 94 round-3 transcripts, 2026-09-27.

    Order: the HTTP header, then the page's own <meta> declaration (searched
    in the first 64 KiB), then UTF-8 only if the bytes ARE valid UTF-8. Anything
    else is refused, because a guessed charset is an invented text.
    """
    body = resp.content
    m = _HEADER_CHARSET.search(resp.headers.get("content-type") or "")
    if m:
        charset, basis = m.group(1).lower(), "http_header"
    else:
        mm = _META_CHARSET.search(body[:65536])
        if mm:
            charset, basis = mm.group(1).decode("ascii").lower(), "meta_charset"
        else:
            charset, basis = "utf-8", "utf8_valid"
    try:
        return body.decode(charset, errors="strict"), charset, basis
    except (UnicodeDecodeError, LookupError) as exc:
        raise NotVerbatim(f"cannot decode as {charset} ({basis}): {exc}") from exc


def extract(resp: requests.Response) -> tuple[str, str]:
    """(text, how). Raises NotVerbatim if the text cannot be trusted."""
    if looks_like_pdf(resp):
        text, order = pdf_to_text(resp.content)
        return text, f"pdftotext({order})"
    raw, charset, basis = decode_html(resp)
    enc = f"[charset={charset}/{basis}]"
    text = html_to_text(raw)
    try:
        assert_verbatim(raw, text)
    except ValueError as exc:
        raise NotVerbatim(str(exc)) from exc
    if len(text.split()) < MIN_WORDS:
        # A Next.js shell whose body travels as rich-text script data (the
        # palantir.com letters). Tried ONLY when the visible text is too short to
        # be a source, so no page that already reads correctly changes route.
        try:
            rich = next_data_richtext(raw)
        except ValueError as exc:
            raise NotVerbatim(str(exc)) from exc
        if rich is not None and len(rich.split()) >= MIN_WORDS:
            return rich, f"web_source_text.next_data_richtext{enc}"
    return text, f"web_source_text.html_to_text{enc}"


def now_utc() -> str:
    """Wall-clock UTC, for WHEN WE FETCHED. Never for logical time."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def source_id_for(url: str) -> str:
    """Stable, unique, readable. Same URL gives the same id on every run."""
    host = urlparse(url).netloc.lower()
    host = re.sub(r"^www\.", "", host)
    token = re.sub(r"[^a-z0-9]+", "-", host.split(":")[0]).strip("-")[:24]
    return f"web-{token}-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


class Fetcher:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    def _wait(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            gap = PER_HOST_INTERVAL_S - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last_hit[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        """robots.txt says yes. A robots.txt we cannot read is treated as ALLOW.

        That is the conventional reading and it is stated here rather than left
        implicit: an unreachable robots.txt is not a disallow.
        """
        parsed = urlparse(url)
        host = parsed.netloc
        if host not in self._robots:
            self._wait(host)
            rob = robotparser.RobotFileParser()
            try:
                resp = self.session.get(f"{parsed.scheme}://{host}/robots.txt",
                                        timeout=self.timeout)
                if resp.status_code >= 400:
                    self._robots[host] = None
                else:
                    rob.parse(resp.text.splitlines())
                    self._robots[host] = rob
            except requests.RequestException:
                self._robots[host] = None
        rob = self._robots[host]
        return True if rob is None else rob.can_fetch(UA, url)

    def get(self, url: str) -> requests.Response:
        self._wait(urlparse(url).netloc)
        return self.session.get(url, timeout=self.timeout)

    def get_reader(self, url: str) -> requests.Response:
        """The ORIGINAL url through the reader, returning rendered HTML."""
        last = self._last_hit.get(READER_HOST)
        if last is not None:
            gap = READER_INTERVAL_S - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last_hit[READER_HOST] = time.monotonic()
        return self.session.get(READER_PREFIX + url, headers={"X-Return-Format": "html"},
                                timeout=max(self.timeout, 90))


def _attempt(get, url: str, route: str, request_url: str) -> dict:
    """One route, start to finish. Returns the acquisition or raises FetchFailure.

    The not_verbatim retry lives here so both routes get it. A not_verbatim
    failure can be TRANSIENT: some pages serve slightly different bytes per
    request, and conversationswithtyler.com passed, failed by ten characters,
    then agreed exactly. Each attempt validates its OWN bytes, so a retry is
    sound rather than a lucky second roll. Two failures is a refusal.
    """
    try:
        resp = get(url)
    except requests.RequestException as exc:
        raise FetchFailure("fetch_error", type(exc).__name__) from exc
    if resp.status_code != 200:
        raise FetchFailure(f"http_{resp.status_code}")
    text = how = None
    retried = False
    for attempt in (1, 2):
        try:
            text, how = extract(resp)
            break
        except NotVerbatim as exc:
            if attempt == 2:
                raise FetchFailure("not_verbatim", str(exc)[:200]) from exc
            retried = True
            try:
                resp = get(url)
            except requests.RequestException as exc2:
                raise FetchFailure("not_verbatim", f"refetch failed: {type(exc2).__name__}") from exc2
            if resp.status_code != 200:
                raise FetchFailure("not_verbatim", f"refetch answered {resp.status_code}")
        except RuntimeError as exc:
            raise FetchFailure("pdf_tool_missing", str(exc)) from exc
    n_words = len(text.split())
    if n_words < MIN_WORDS:
        raise FetchFailure("too_short", f"{n_words} words (min {MIN_WORDS})")
    return {"resp": resp, "text": text, "how": how, "route": route,
            "request_url": request_url, "direct_failure": None,
            "not_verbatim_retried": retried}


def acquire(fetcher, url: str, reader_fallback: bool) -> dict:
    """Fetch one source by the direct route, then the reader if allowed.

    A Wayback URL is always requested in its `id_` form. The reader is tried
    once, only after a RECOVERABLE direct failure, and only when asked for. A
    reader failure is reported as `<direct>+reader_<reader>`, so both reasons
    stay visible in the taxonomy.
    """
    wb = wayback_original_bytes_url(url)
    request_url = wb or url
    route = "wayback_id_" if wb else "direct"
    try:
        return _attempt(fetcher.get, request_url, route, request_url)
    except FetchFailure as direct:
        if not reader_fallback or not direct.category.startswith(READER_RECOVERABLE_PREFIXES):
            raise
        try:
            got = _attempt(fetcher.get_reader, url, READER_ROUTE, READER_PREFIX + url)
        except FetchFailure as via:
            raise FetchFailure(f"{direct.category}+reader_{via.category}",
                               f"direct: {direct.detail} | reader: {via.detail}") from via
        got["direct_failure"] = direct.category
        return got


class EvidenceShapeError(ValueError):
    """A gate_evidence entry this code cannot read. Refused, never skipped."""


def evidence_quotes(items) -> list[str]:
    """The quote text out of each gate_evidence entry, in either shape.

    Round 1 asked each discovery agent for a bare verbatim sentence, so an entry
    was a string. Round 2 asks for the DEADLINE and the RESOLUTION ROUTE beside
    it, because a quote that passes the five gates is still worth nothing to the
    board if its deadline has not passed, so an entry is an object carrying a
    `quote` key. Both shapes are read here and everything else is REFUSED by
    name.

    Refusing rather than skipping is the whole point. The grounding rate below
    is the integrity check on the discovery pass, and a silently skipped entry
    lowers it. That would read as "the agent paraphrased the page" when the
    truth is "this code could not parse the entry", which is the accept-and-guess
    that turns a loud failure into a quiet wrong answer.
    """
    out: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            quote = item
        elif isinstance(item, dict):
            if "quote" not in item:
                raise EvidenceShapeError(
                    f"gate_evidence object has no 'quote' key: {item!r}")
            quote = item["quote"]
            if not isinstance(quote, str):
                raise EvidenceShapeError(
                    f"gate_evidence 'quote' is {type(quote).__name__}, not str: {item!r}")
        else:
            raise EvidenceShapeError(
                f"gate_evidence entry is {type(item).__name__}, "
                f"expected str or an object with a 'quote' key: {item!r}")
        if not quote.strip():
            raise EvidenceShapeError(f"gate_evidence 'quote' is blank: {item!r}")
        out.append(quote)
    return out


def ground_evidence(text: str, quotes) -> dict:
    """How many of the agent's own evidence quotes are really in the page.

    This costs no quota and is the integrity check on the discovery pass. Two
    agents independently reported that the page-reading tool PARAPHRASED quotes,
    and one caught it attributing a sentence to a speaker that was not on the
    page at all. A quote that does not ground here would also not ground during
    extraction, so a low rate means the source was judged on text nobody read.

    Takes either gate_evidence shape; see evidence_quotes.
    """
    found, missing = 0, []
    for q in evidence_quotes(quotes):
        if "start" in L.locate_quote(text, q):
            found += 1
        else:
            missing.append(q[:90])
    return {"claimed": len(quotes or []), "grounded": found, "missing": missing}


def record_for(src: dict, slug: str, text: str, raw: str,
               resp: requests.Response, run: str, acquired: dict | None = None) -> dict:
    """A transcript record. Field names match what the pipeline already reads.

    `statement_date` and `statement_date_basis` are DECLARED here rather than
    written into `yt_upload_date`. This is not a YouTube recording and must not
    claim to be one. derive_statement_date() honours the declared pair and
    raises on a basis outside its vocabulary.
    """
    return {
        "leader_slug": slug,
        "source_id": source_id_for(src["url"]),
        "url": src["url"],
        "declared_title": src.get("title"),
        "declared_venue": src.get("publisher"),
        "declared_kind": src.get("kind"),
        # The basis is carried only when there IS a date. Several findings pair
        # a null date with a basis of "stated_in_page", which would leave a
        # record asserting how it knows a date it does not have.
        "statement_date": src.get("speech_date") or None,
        "statement_date_basis": (src.get("speech_date_basis")
                                 if src.get("speech_date") else None),
        "word_count": len(text.split()),
        "char_count": len(text),
        "text": text,
        "source_class": "supplemental_web",
        "fetched_at_utc": now_utc(),
        "fetch_method": f"requests+{raw}",
        # HOW the bytes were obtained, which fetch_method alone does not say.
        # "direct", "wayback_id_" or READER_ROUTE; request_url is what was
        # actually requested, and direct_failure why the direct route was not
        # enough. `url` above stays the source's own address.
        "fetch_route": (acquired or {}).get("route", "direct"),
        "request_url": (acquired or {}).get("request_url", src["url"]),
        "direct_failure": (acquired or {}).get("direct_failure"),
        "access_declared": src.get("access"),
        "http_status": resp.status_code,
        "content_type": resp.headers.get("content-type"),
        "raw_sha256": hashlib.sha256(resp.content).hexdigest(),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "discovery": {
            # The run NAME, taken from the run directory on the command line.
            # It was a hardcoded literal until 2026-09-16, so every record any
            # later sweep fetched would have claimed to come from the first one.
            # A provenance field that names the wrong run is worse than an
            # absent one, because nothing downstream can tell it is wrong.
            "run": run,
            "density_claimed": src.get("density"),
            "identity_note": src.get("identity_note"),
            "gate_evidence": src.get("gate_evidence", []),
            "evidence_grounding": ground_evidence(text, src.get("gate_evidence", [])),
            "agent_notes": src.get("notes"),
        },
    }


def usable(src: dict, allow_partial: bool = False) -> tuple[bool, str]:
    # --allow-partial-access admits a page the discovery agent marked "partial",
    # such as a paywalled post whose free preview carries the quotes. Only the
    # preview is fetched and only it becomes text, so nothing unseen is claimed;
    # the record carries access_declared so the class stays separable. Every
    # other gate below still applies, including the identity gate.
    if allow_partial and src.get("access") == "partial":
        pass
    else:
        if not src.get("full_text_available"):
            return False, "agent_said_no_full_text"
        if src.get("access") != "open":
            return False, f"access_{src.get('access')}"
    if not src.get("first_person_verified"):
        return False, "identity_not_verified"
    if not src.get("url"):
        return False, "no_url"
    # A DATE IS NOT REQUIRED, deliberately. An earlier version of this gate
    # rejected every dateless source, and the effect was not neutral: it dropped
    # 11 sources of which 6 were Sergey Brin's, the leader with the least
    # material on the board. A cap that bites one person six times harder than
    # anyone else is a bias, not a detail.
    #
    # A dateless record is still a real record. It simply cannot carry a horizon
    # or a market cutoff, and derive_statement_date returns (None, "unknown")
    # for it, which every downstream stage already handles. What is NOT allowed
    # is inventing the date, so nothing here infers one from the URL or the
    # title. They are counted as `dateless` and reported per leader.
    if src.get("speech_date") and src.get("speech_date_basis") not in DATE_BASES:
        return False, f"bad_date_basis_{src.get('speech_date_basis')}"
    return True, ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True,
                    help="run directory under data/predictions/_experiments/")
    ap.add_argument("--only", help="one slug, for a pilot before the sweep")
    ap.add_argument("--limit", type=int, help="stop after N successful fetches")
    ap.add_argument("--reader-fallback", action="store_true",
                    help="after a recoverable direct failure, fetch once through the "
                         "r.jina.ai reader in HTML mode; the same verbatim check applies")
    ap.add_argument("--allow-partial-access", action="store_true",
                    help="admit sources the discovery agent marked access 'partial'")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and report what would be fetched; no requests")
    args = ap.parse_args(argv)

    run = Path(args.run).resolve()
    findings = sorted((run / "findings").glob("*.json"))
    if args.only:
        findings = [f for f in findings if f.stem == args.only]
    if not findings:
        print(f"no findings under {run / 'findings'}", file=sys.stderr)
        return 2

    out_root = run / "transcripts"
    fetcher = Fetcher()
    tally: Counter[str] = Counter()
    per_leader: dict[str, Counter] = {}
    written: list[dict] = []

    for fpath in findings:
        data = json.loads(fpath.read_text())
        slug = data["slug"]
        counts = per_leader.setdefault(slug, Counter())
        for src in data.get("sources", []):
            ok, why = usable(src, allow_partial=args.allow_partial_access)
            if not ok:
                tally[f"skipped_{why}"] += 1
                counts[f"skipped_{why}"] += 1
                continue
            url = src["url"]
            if args.dry_run:
                tally["would_fetch"] += 1
                counts["would_fetch"] += 1
                print(f"  WOULD FETCH {slug:18} {source_id_for(url)}  {url}")
                continue
            if not fetcher.allowed(url):
                tally["robots_disallow"] += 1
                counts["robots_disallow"] += 1
                print(f"  ROBOTS      {slug:18} {url}")
                continue
            try:
                got = acquire(fetcher, url, reader_fallback=args.reader_fallback)
            except FetchFailure as exc:
                tally[exc.category] += 1
                counts[exc.category] += 1
                print(f"  FAILED      {slug:18} {exc.category}  {url}\n      {exc.detail[:200]}")
                continue
            resp, text, how = got["resp"], got["text"], got["how"]
            n_words = len(text.split())
            if got["not_verbatim_retried"]:
                tally["not_verbatim_retried"] += 1
            if got["route"] != "direct":
                tally[f"route_{got['route']}"] += 1
                counts[f"route_{got['route']}"] += 1
            rec = record_for(src, slug, text, how, resp, run=run.name, acquired=got)
            try:
                date, basis = L.derive_statement_date(rec)
            except L.PredictionError as exc:
                tally["bad_date"] += 1
                counts["bad_date"] += 1
                print(f"  BAD DATE    {slug:18} {exc}")
                continue
            dest = out_root / slug / f"{rec['source_id']}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            L.write_prediction_file(dest, json.dumps(rec, indent=1, sort_keys=True,
                                                     ensure_ascii=False) + "\n")
            tally["written"] += 1
            counts["written"] += 1
            if basis == "unknown":
                tally["dateless"] += 1
                counts["dateless"] += 1
            ev = rec["discovery"]["evidence_grounding"]
            written.append({"slug": slug, "source_id": rec["source_id"], "url": url,
                            "words": n_words, "statement_date": date,
                            "statement_date_basis": basis, "how": how,
                            "fetch_route": got["route"], "request_url": got["request_url"],
                            "direct_failure": got["direct_failure"],
                            "evidence_grounding": ev})
            tally["evidence_claimed"] += ev["claimed"]
            tally["evidence_grounded"] += ev["grounded"]
            counts["evidence_claimed"] += ev["claimed"]
            counts["evidence_grounded"] += ev["grounded"]
            print(f"  OK          {slug:18} {n_words:>6} words  {date} ({basis})  "
                  f"evidence {ev['grounded']}/{ev['claimed']}  {url}")
            if args.limit and tally["written"] >= args.limit:
                print(f"\n--limit {args.limit} reached")
                break
        if args.limit and tally["written"] >= args.limit:
            break

    # `attempted` counts OUTCOMES, not every key in the tally. evidence_claimed,
    # evidence_grounded and dateless are properties OF a written record, so
    # summing the whole Counter reported 352 attempts for 108 sources and turned
    # a 75% success rate into an apparent 23%. A progress line that inflates its
    # own denominator is the bare-count failure this repo forbids, arriving in
    # the report rather than in the pipeline.
    ANNOTATIONS = {"evidence_claimed", "evidence_grounded", "dateless", "would_fetch",
                   "not_verbatim_retried"}
    ANNOTATIONS |= {k for k in tally if k.startswith("route_")}
    outcomes = {k: v for k, v in tally.items() if k not in ANNOTATIONS}
    attempted = sum(outcomes.values())
    failed = attempted - tally["written"]
    print(f"\nattempted {attempted} / written {tally['written']} / failed {failed}"
          f"  ({tally['written'] / attempted:.0%} of attempts)"
          if attempted else "\nnothing attempted")
    print(f"agent evidence quotes: {tally['evidence_grounded']} of "
          f"{tally['evidence_claimed']} ground exactly in the fetched text")
    print("taxonomy:", dict(sorted(tally.items())))
    print("\nper leader:")
    for slug in sorted(per_leader):
        print(f"  {slug:20} {dict(sorted(per_leader[slug].items()))}")

    # ORPHAN SWEEP. A record this run REFUSED may still be on disk from an
    # earlier run that accepted it. Leaving it there is the withdrawal bug this
    # repo already documents: a derived artifact outlives the decision that
    # produced it, and everything downstream keeps reading it. Only swept on a
    # full run, because --only or --limit legitimately writes a subset.
    if not args.dry_run and not args.only and not args.limit:
        live = {(w["slug"], w["source_id"]) for w in written}
        orphans = [p for p in sorted((run / "transcripts").rglob("*.json"))
                   if (p.parent.name, p.stem) not in live]
        for p in orphans:
            p.unlink()
            tally["orphans_removed"] += 1
            print(f"  ORPHAN REMOVED {p.parent.name}/{p.stem} "
                  f"(written by an earlier run, refused by this one)")

    if not args.dry_run and written:
        manifest = {
            "run": run.name,
            "built_at_utc": now_utc(),
            "min_words": MIN_WORDS,
            "per_host_interval_s": PER_HOST_INTERVAL_S,
            "user_agent": UA,
            "reader_fallback": args.reader_fallback,
            "reader_route": READER_ROUTE if args.reader_fallback else None,
            "allow_partial_access": args.allow_partial_access,
            "taxonomy": dict(sorted(tally.items())),
            "per_leader": {k: dict(sorted(v.items())) for k, v in sorted(per_leader.items())},
            "written": written,
        }
        L.write_prediction_file(run / "fetch_manifest.json",
                                json.dumps(manifest, indent=1, sort_keys=True,
                                           ensure_ascii=False) + "\n")
        print(f"\nmanifest -> {run / 'fetch_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
