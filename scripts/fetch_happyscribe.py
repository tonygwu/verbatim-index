#!/usr/bin/env python3
"""Fetch transcripts from Happy Scribe, as a second source alongside YouTube.

Why a second source at all: YouTube's caption endpoint rate-limits per IP and
has blocked this pipeline repeatedly. Happy Scribe is a different host with a
different limit, so the two can run at the same time and neither one stalls the
other.

Two things verified before this was written, both by measurement:
  - robots.txt permits everything except /surprise-me and /search, and names no
    Anthropic-specific rule.
  - HTTP/2 draws a Cloudflare 403 and HTTP/1.1 returns 200. The requests
    Session below is pinned to HTTP/1.1 for that reason.

Output records carry the core fields the YouTube fetcher writes (the
`declared_*` block, the word, character and timestamp counts, `duration_sec`,
`fetched_at_utc` and `text`), with `video_id: None` and
`fetch_method: happyscribe`, so the grading stages treat them identically. The
shapes are not the same. A Happy Scribe record has none of YouTube's `yt_*`
metadata, so no `yt_upload_date`. Instead it carries `hs_*` page fields,
`text_unescaped`, and, when the page states one, a declared `statement_date`
with basis `publication_date`, or `hs_date_unreadable` saying why it could not
be read (see page_dates). Only the predictions pipeline reads the date. The
leaders judge prompt is byte-identical with and without these fields, which
scripts/test_hs_fetch_record.py checks in its YEAR section.
Deduplication against the YouTube corpus is a SEPARATE step, in
dedupe_transcripts.py. This script never decides what to keep; it only fetches.

Usage:
  fetch_happyscribe.py --discover --roster data/roster/final.json \
      --candidates data/sources/happyscribe_candidates.json
  fetch_happyscribe.py --report-unsearched --roster data/roster/final.json \
      --candidates data/sources/happyscribe_candidates.json
  fetch_happyscribe.py --fetch --candidates data/sources/happyscribe_candidates.json \
      --out data/transcripts_hs --target-per-leader 5
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import html as htmlmod
import json
import os
import random
import re
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

BASE = "https://podcasts.happyscribe.com"
SITEMAP_INDEX = f"{BASE}/sitemap.xml"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/133.0 Safari/537.36")

# robots.txt disallows exactly these. Checked 2026-09-06; re-check if this
# script starts 403ing rather than assuming the block is rate-based.
ROBOTS_DISALLOW = ("/surprise-me", "/search")

E_HTTP = "http_error"
E_NO_TRANSCRIPT = "no_transcript_in_page"
E_TOO_SHORT = "below_min_words"
E_BLOCKED = "blocked_or_ratelimited"
E_OTHER = "other"

MIN_WORDS = 700
_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, file=sys.stderr, flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_session() -> requests.Session:
    """A session pinned to HTTP/1.1, which is the only version that works here."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    # requests uses HTTP/1.1 by default. Stated explicitly because it is
    # load-bearing: HTTP/2 returns 403 from this host.
    return s


class Pacer:
    """Shared, jittered gap between requests. Same discipline as the YouTube path."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval * random.uniform(0.7, 1.3)
            gap = start - now
        if gap > 0:
            time.sleep(gap)


def allowed(path: str) -> bool:
    return not any(path.startswith(d) for d in ROBOTS_DISALLOW)


# Shared with the YouTube discovery path so both sources apply one definition of
# "this is commentary, not an appearance". The transcript-stage name-density gate
# in qa_transcripts.py is the backstop for whatever slips through here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_sources import THIRD_PERSON_TITLE  # noqa: E402

# Episode slugs carry commentary shapes the video-title filter never had to
# handle: "why-X-is-selling-stock", "scale-like-X", "X explained". These are
# people talking ABOUT the leader. Caught here to avoid wasting fetches; the
# name-density gate in qa_transcripts.py remains the real defence, because it
# measures the transcript rather than guessing from a slug.
COMMENTARY_SLUG = re.compile(
    r"(^|-)(why|how|what|when|lessons?|secrets?|rules?|habits?|advice|playbook|"
    r"strategy|blueprint|method|mindset|genius|empire|downfall|scandal)(-|$)"
    r"|(^|-)(like|about|behind|inside|vs|versus|reacts?|reaction|explained|"
    r"analysis|breakdown|recap|review)(-|$)", re.I)


# ---------------------------------------------------------------- discovery

def get(session: requests.Session, url: str, pacer: Pacer, timeout: int = 60) -> requests.Response:
    pacer.wait()
    return session.get(url, timeout=timeout, allow_redirects=True)


def unsearched_leaders(roster_path, pool_path, board=None) -> tuple[list[str], list[str]]:
    """Which roster slugs the candidate pool has never been searched for.

    Returns (unsearched, stale). The pool is DERIVED from the roster, so it has
    to track it. happyscribe_loop.sh used to run discovery only when the pool
    file was missing, which meant the roster could move underneath it forever.
    It did: the roster grew from 40 to 50 on 2026-09-10 and eleven leaders were
    never searched, while C.C. Wei stayed in the pool after being removed from
    the study. The loop reported COMPLETE the whole time, truthfully, because
    every candidate it knew of had been fetched. It simply knew of none for them.

    A leader PRESENT with an empty list counts as SEARCHED. Larry Ellison,
    Michael Dell and Sergey Brin were searched and genuinely have no podcast
    appearances, so treating empty as unsearched would re-walk 38 sitemaps every
    cycle forever and hide the real gap behind constant activity.

    An absent or empty pool file means nobody has been searched, rather than an
    error: that is the first-run case the loop already handles.
    """
    roster = [r["slug"] for r in json.loads(Path(roster_path).read_text())["roster"]]
    # THE LEADERS BOARD, not the roster. This function decides whether the loop
    # runs a Happy Scribe sitemap crawl. Since 2026-09-18 the roster carries
    # seven people on the predictions board only; they have never been searched
    # and never will be by this path, so leaving them in reported "7 roster
    # leader(s) never searched" on EVERY cycle and triggered a fresh crawl each
    # time, which is the forever-re-walking failure the docstring above already
    # describes, arriving from a new direction. Their transcripts would also land
    # in transcripts_hs and be merged onto the GRADED shelf, which the membership
    # plan forbids for predictions-only people; their sourcing is P4's, through
    # transcripts_web.
    if board is not None:
        import membership as _MB
        roster = [s for s in roster if _MB.on_board(board, s, "leaders")]
    pool_path = Path(pool_path)
    pool: dict = {}
    if pool_path.is_file() and pool_path.stat().st_size:
        pool = json.loads(pool_path.read_text())
    unsearched = [s for s in roster if s not in pool]
    stale = [k for k in pool if k not in roster]
    return unsearched, sorted(stale)


def select_roster(roster: list[dict], only: list[str] | None) -> list[dict]:
    """Restrict discovery to named slugs, refusing a slug the roster does not hold.

    Adding seven people to the roster makes happyscribe_loop.sh re-run discovery,
    and without a scope that re-derives the pool for everyone. --only writes just
    the named slugs. It does NOT save the sitemap walk: discover() walks
    children[:max_sitemaps] whatever it is matching against, so the saving is in
    what gets written, not in what gets fetched.

    An unknown slug RAISES rather than selecting nothing. A typo that quietly
    discovers nobody would leave the slug absent from the pool, and an absent
    slug is what makes the loop re-run discovery every cycle for ever.
    """
    if only is None:
        return roster
    by_slug = {p["slug"]: p for p in roster}
    unknown = [s for s in only if s not in by_slug]
    if unknown:
        raise SystemExit(f"--only names {unknown!r}, which are not on the roster. "
                         f"Roster holds {len(by_slug)} slugs.")
    return [by_slug[s] for s in only]


def merge_pool(existing: dict, found: dict, *, replace: bool) -> tuple[dict, dict]:
    """Fold a discovery result into the candidate pool without losing candidates.

    A fresh crawl legitimately returns LESS than the pool holds: discover() caps
    at max_sitemaps (40) and skips any child sitemap that does not answer 200, so
    one transient failure shrinks the result. Writing that result wholesale
    deleted the difference, and because the leader stays PRESENT in the pool it
    still counts as searched, so nothing ever re-found it.

    Candidates are identified by source_id, existing order is preserved, and new
    ones are appended. A leader discovered with an empty list is still WRITTEN,
    because present-but-empty is how this file records "searched, found nothing".
    """
    pool = {k: list(v) for k, v in existing.items()}
    report: dict = {"candidates_kept_from_pool": 0, "candidates_added": 0,
                    "candidates_dropped_by_replace": {}}
    for slug, cands in found.items():
        old = pool.get(slug, [])
        if replace:
            lost = sorted({c["source_id"] for c in old} - {c["source_id"] for c in cands})
            if lost:
                report["candidates_dropped_by_replace"][slug] = lost
            pool[slug] = list(cands)
            continue
        have = {c["source_id"] for c in old}
        added = [c for c in cands if c["source_id"] not in have]
        # Never a bare count: a kept candidate is one this crawl did not return,
        # which is the difference a wholesale write used to delete.
        report["candidates_kept_from_pool"] += len(have - {c["source_id"] for c in cands})
        report["candidates_added"] += len(added)
        pool[slug] = old + added
    return pool, report


def discover(roster: list[dict], session: requests.Session, pacer: Pacer,
             max_sitemaps: int = 40) -> dict:
    """Walk the sitemap index and keep episodes whose slug names one of our leaders.

    Matching on the EPISODE SLUG rather than on a show allowlist. An episode
    slug reliably carries the guest's name, e.g. "405-jeff-bezos-amazon-and-blue-
    origin", so this finds appearances on shows we never thought to list, and it
    does not depend on guessing show slugs correctly.
    """
    r = get(session, SITEMAP_INDEX, pacer)
    r.raise_for_status()
    children = re.findall(r"<loc>([^<]+)</loc>", r.text)
    log(f"sitemap index: {len(children)} child sitemaps")

    # FULL NAME ONLY. Surname matching was tried and produced garbage: "prince"
    # matched 23 episodes about Prince Harry, Saudi princes and Jordanian
    # princes, none of them Cloudflare's chief executive. A surname that is also
    # an ordinary English word cannot carry this on its own.
    keys: list[tuple[str, str]] = []
    for p in roster:
        parts = [w for w in re.split(r"\s+", p["name"]) if len(w) > 1]
        keys.append((p["slug"], "-".join(w.lower() for w in parts)))

    seen: set[str] = set()
    found: dict[str, list[dict]] = {p["slug"]: [] for p in roster}
    for i, child in enumerate(children[:max_sitemaps], 1):
        try:
            rc = get(session, child, pacer)
            if rc.status_code != 200:
                log(f"  sitemap {i}/{len(children)}: HTTP {rc.status_code}, skipping")
                continue
        except Exception as exc:  # noqa: BLE001
            log(f"  sitemap {i}/{len(children)}: {type(exc).__name__}, skipping")
            continue
        urls = re.findall(r"<loc>([^<]+)</loc>", rc.text)
        hits = 0
        for u in urls:
            clean = u.split("?")[0]
            path = clean[len(BASE):] if clean.startswith(BASE) else clean
            if not allowed(path) or clean in seen:
                continue
            segs = [s for s in path.split("/") if s]
            if len(segs) != 2:
                continue
            show, ep = segs
            low = f"{show}/{ep}".lower()
            # A slug can name the person and still be a show ABOUT them rather
            # than an appearance BY them: "why-jeff-bezos-is-selling-amazon-stock"
            # names him and is commentary. Reuse the same third-person filter the
            # YouTube discovery uses, so both sources reject the same shapes.
            if THIRD_PERSON_TITLE.search(ep.replace("-", " ")) or COMMENTARY_SLUG.search(ep):
                continue
            for slug, full in keys:
                if full not in low:
                    continue
                seen.add(clean)
                found[slug].append({"url": clean, "show": show, "episode": ep})
                hits += 1
                break
        if i % 10 == 0 or hits:
            total = sum(len(v) for v in found.values())
            log(f"  sitemap {i}/{len(children)}: +{hits} (running total {total})")

    return found


# ------------------------------------------------------------------- fetch

TRANSCRIPT_BLOCK = re.compile(
    r'<div[^>]*class="[^"]*episode-transcription-body[^"]*"[^>]*>(.*?)</div>\s*(?:</div>|<footer)',
    re.S | re.I)
TS = re.compile(r"\[(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)?\]")


def extract_transcript(page: str) -> tuple[str, int]:
    """Pull the transcript and normalise timestamps to [hh:mm:ss].

    The page renders the transcript TWICE. A JSON payload early in the document
    carries it with timestamps intact, and a later HTML block repeats it with
    the timestamps stripped. Scraping the visible HTML looks like the obvious
    move and silently loses all 576 position markers, which are what lets a
    judge cite where in an appearance a passage sits. So the JSON field is the
    primary path and the HTML block is only a fallback.

    Both paths return UNESCAPED text. The JSON string is itself HTML-escaped
    ("we&#39;re"), so decoding the JSON is only half the job. FOUND 2026-09-28:
    this path skipped the unescape, and "&#39;" reached the corpus, the
    extractor's quotes and the published prediction cards. Records written
    before that date keep their escaped text; see `text_unescaped` in fetch_one.
    """
    marker = '"transcript":'
    idx = page.find(marker)
    if idx != -1:
        # Decode the JSON string properly rather than regexing to the next quote:
        # the transcript contains escaped quotes and would be truncated.
        q = page.find('"', idx + len(marker))
        if q != -1:
            try:
                raw, _ = json.JSONDecoder().raw_decode(page[q:])
                if isinstance(raw, str) and len(raw.split()) > 200:
                    return _normalise(htmlmod.unescape(raw))
            except ValueError:
                pass

    m = TRANSCRIPT_BLOCK.search(page)
    chunk = m.group(1) if m else ""
    if not chunk:
        m2 = re.search(r'<section[^>]*class="[^"]*episode-transcript-section[^"]*"[^>]*>(.*?)</section>',
                       page, re.S | re.I)
        chunk = m2.group(1) if m2 else ""
    if not chunk:
        return "", 0
    chunk = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", chunk)
    chunk = re.sub(r"(?s)<[^>]+>", " ", chunk)
    return _normalise(htmlmod.unescape(chunk))


def _normalise(text: str) -> tuple[str, int]:
    """Collapse whitespace and rewrite [hh:mm:ss.ff] as [hh:mm:ss].

    The YouTube fetcher emits [hh:mm:ss], so both sources must agree or a judge
    sees two different citation formats and the rubric's timestamp instruction
    stops meaning one thing.
    """
    text = re.sub(r"[ \t]+", " ", text)
    n_marks = len(TS.findall(text))
    text = TS.sub(lambda m: f"\n[{int(m.group(1)):02d}:{m.group(2)}:{m.group(3)}] ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text, n_marks


LD_JSON = re.compile(r'<script[^>]*type=["\']?application/ld\+json["\']?[^>]*>(.*?)</script>',
                     re.S | re.I)
# The key as JSON writes it, quotes included. The bare word also matches prose
# and HTML comments, which name no date.
DATE_KEY = '"datePublished"'
# The record field, and the fetch_one status key, that says why a page's date
# could not be read. See page_dates.
DATE_UNREADABLE = "hs_date_unreadable"


class PageDateError(ValueError):
    """The page states a date for the transcript that cannot be read as one UTC date."""


def _ld_blocks(page: str) -> tuple[list[tuple[str, object]], list[str]]:
    """(label, parsed JSON) for each JSON-LD block, labelled ld[i] in page
    order, and one reason for each block that names datePublished and does not
    parse. A broken block that could hold the date must not read as "no date":
    that would write the transcript undated and hide why. A broken block that
    cannot hold it is skipped."""
    blocks: list[tuple[str, object]] = []
    broken: list[str] = []
    for i, text in enumerate(LD_JSON.findall(page)):
        try:
            blocks.append((f"ld[{i}]", json.loads(text)))
        except ValueError as exc:
            if "datePublished" in text:
                broken.append(f"JSON-LD block ld[{i}] names datePublished and is not valid JSON: {exc}")
    return blocks, broken


def _transcript_owners(obj, path: str) -> list[tuple[str, dict]]:
    """(path, object) for every object, at any depth, whose associatedMedia
    holds a media object with a `transcript` key. associatedMedia may be one
    media object or a list of them, as schema.org allows both."""
    found: list[tuple[str, dict]] = []
    if isinstance(obj, dict):
        media = obj.get("associatedMedia")
        if any(isinstance(m, dict) and "transcript" in m
               for m in (media if isinstance(media, list) else [media])):
            found.append((path, obj))
        for k, v in obj.items():
            found.extend(_transcript_owners(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_transcript_owners(v, f"{path}[{i}]"))
    return found


def _dates_published(obj, path: str) -> list[tuple[str, object]]:
    """(path, value) for every datePublished at any depth. A JSON null states
    that there is no value, so it is left out exactly as a missing key is."""
    found: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k != "datePublished":
                found.extend(_dates_published(v, f"{path}.{k}"))
            elif v is not None:
                found.append((f"{path}.{k}", v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_dates_published(v, f"{path}[{i}]"))
    return found


def _utc_date(value) -> date:
    """The UTC date of one ISO 8601 timestamp that carries its own offset.

    A value with no offset is refused, not read as UTC or as local time. The
    archived page stamps +02:00, the UTC date moves with the offset, and
    assuming a zone is the guess that the rule against the local clock forbids.
    """
    if not isinstance(value, str):
        raise PageDateError(f"datePublished {value!r} is not a string")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PageDateError(f"datePublished {value!r} is not an ISO 8601 timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PageDateError(f"datePublished {value!r} carries no UTC offset, so its UTC date "
                            f"cannot be known")
    return dt.astimezone(timezone.utc).date()


def _fetch_date(fetched_at_utc: str) -> date:
    """The UTC date of this record's own fetched_at_utc stamp. Our own stamp
    always carries Z, so one without an offset is a bug here, and it raises
    ValueError rather than PageDateError."""
    dt = datetime.fromisoformat(fetched_at_utc)
    if dt.utcoffset() is None:
        raise ValueError(f"fetched_at_utc {fetched_at_utc!r} carries no UTC offset")
    return dt.astimezone(timezone.utc).date()


def _owner_date(page: str, broken: list[str], owners: list,
                fetched_at_utc: str) -> tuple[str, str] | None:
    """(UTC date as YYYY-MM-DD, raw value) of the transcript owner's own
    datePublished, or None when the page states no date for the transcript.
    Raises PageDateError for every other case; page_dates says which."""
    if broken:
        raise PageDateError("; ".join(broken))
    if DATE_KEY not in page:
        return None
    if len(owners) != 1:
        raise PageDateError(
            f"the page names datePublished, but {len(owners)} JSON-LD objects carry a transcript "
            f"in associatedMedia ({', '.join(p for p, _ in owners) or 'none'}), so no date can be "
            f"tied to the stored text; exactly one must")
    path, owner = owners[0]
    value = owner.get("datePublished")
    if value is None:
        inside = sum(text.count(DATE_KEY) for text in LD_JSON.findall(page))
        outside = page.count(DATE_KEY) - inside
        if outside:
            raise PageDateError(
                f"the page names {DATE_KEY} {outside} time(s) outside any JSON-LD block this "
                f"fetcher reads, and the object that carries the transcript ({path}) states no "
                f"datePublished of its own")
        return None
    day = _utc_date(value)
    fetched = _fetch_date(fetched_at_utc)
    if day > fetched:
        raise PageDateError(
            f"datePublished {value!r} is on {day.isoformat()} in UTC, after {fetched.isoformat()}, "
            f"the UTC date this record was fetched; a page is not read before it is published")
    return day.isoformat(), value


def page_dates(page: str, fetched_at_utc: str) -> dict:
    """The record's date fields, read from the page's JSON-LD. Never raises
    PageDateError.

    THE DATE IS THE TRANSCRIPT'S OWN. The episode page carries it in the one
    JSON-LD object, a BlogPosting, whose associatedMedia.transcript is the text
    extract_transcript reads. MEASURED 2026-09-28 on the archived All-In page:
    "datePublished": "2025-09-17T23:05:00+02:00", which is 2025-09-17 in UTC. A
    publication date is an UPPER BOUND on when the words were spoken, which is
    what the `publication_date` basis in predictions_lib means. Exactly one
    object must carry the transcript, and only that object's own top-level
    datePublished is read. A datePublished on a nested entity, such as the
    episode in isPartOf, or in another block describes something else. Taking
    one silently dated a transcript by its series, and the override file could
    not correct it, because an override may not be later than the declared date.

    The fields returned are some of:
      statement_date, statement_date_basis, hs_date_published
                          written together, from the owner's own datePublished
      hs_date_unreadable  why the page's date for the transcript could not be read
      hs_dates_elsewhere  every other non-null datePublished on the page, with its
                          JSON path. Evidence for a person, never the date

    No date and no reason means the transcript's object states no date, and
    the page names none outside JSON-LD either. Nothing stands in for it: not
    dateCreated, not the fetch time, not the clock. JSON null is no date.

    AN UNREADABLE DATE DOES NOT DROP THE TRANSCRIPT (operator decision,
    2026-09-29, option b). The leaders board grades these transcripts and never
    reads the date, so a predictions-only field may not decide what the leaders
    corpus admits. The record is written without statement_date and says why in
    hs_date_unreadable, which keeps "unreadable" apart from "the page states
    none", and main counts and names each one. These are unreadable: a value
    that is not an ISO 8601 timestamp with an offset (a bare date has none), a
    broken JSON-LD block that names datePublished, a page that names
    datePublished while zero or several objects carry a transcript, a page that
    names it only outside the JSON-LD this fetcher reads, and a date later than
    the UTC date of the record's own fetched_at_utc.
    """
    blocks, broken = _ld_blocks(page)
    owners = [o for label, obj in blocks for o in _transcript_owners(obj, label)]
    own_path = f"{owners[0][0]}.datePublished" if len(owners) == 1 else None
    fields: dict = {}
    try:
        published = _owner_date(page, broken, owners, fetched_at_utc)
    except PageDateError as exc:
        fields[DATE_UNREADABLE] = str(exc)
    else:
        if published is not None:
            fields["statement_date"], fields["hs_date_published"] = published
            fields["statement_date_basis"] = "publication_date"
    elsewhere = [{"path": p, "value": v} for label, obj in blocks
                 for p, v in _dates_published(obj, label) if p != own_path]
    if elsewhere:
        fields["hs_dates_elsewhere"] = elsewhere
    return fields


def page_meta(page: str, fetched_at_utc: str) -> dict:
    """Title, description and the date fields from page_dates.

    `statement_date` and `statement_date_basis` are written only as a pair and
    only from datePublished; a page without one gets neither key, which
    predictions_lib.own_statement_date reads as (None, "unknown").
    """
    def grab(pat: str) -> str | None:
        m = re.search(pat, page, re.I | re.S)
        return htmlmod.unescape(m.group(1)).strip() if m else None
    return {
        "hs_title": grab(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"')
                    or grab(r"<title>([^<]+)</title>"),
        "hs_description": (grab(r'<meta[^>]+name="description"[^>]+content="([^"]+)"') or "")[:1000],
        **page_dates(page, fetched_at_utc),
    }


def fetch_one(cand: dict, slug: str, out_dir: Path, session: requests.Session,
              pacer: Pacer, force: bool) -> dict:
    sid = "hs-" + re.sub(r"[^a-z0-9]+", "-", cand["episode"].lower())[:44].strip("-")
    dest = out_dir / slug / f"{sid}.json"
    if dest.exists() and not force:
        return {"status": "cached", "leader_slug": slug, "source_id": sid}
    try:
        r = get(session, cand["url"], pacer)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_OTHER, "detail": f"{type(exc).__name__}: {exc}"[:300]}
    if r.status_code in (403, 429, 503):
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_BLOCKED, "detail": f"HTTP {r.status_code}"}
    if r.status_code != 200:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_HTTP, "detail": f"HTTP {r.status_code}"}

    text, n_marks = extract_transcript(r.text)
    words = len(text.split())
    if not text:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_NO_TRANSCRIPT, "detail": "no transcript container in page"}
    if words < MIN_WORDS:
        return {"status": "failed", "leader_slug": slug, "source_id": sid,
                "error_type": E_TOO_SHORT, "detail": f"{words} words < {MIN_WORDS}"}

    # One stamp, read once: it is the record's fetched_at_utc AND the upper bound
    # page_dates holds the publication date to, so the two can never disagree.
    fetched_at = utcnow()
    # Never raises for a date. An unreadable one comes back as hs_date_unreadable
    # and the transcript is still written, because the leaders board uses it and
    # never reads the date. See page_dates.
    meta = page_meta(r.text, fetched_at)
    # Duration is inferred from the last timestamp, since the page states none.
    last = TS.findall(text)
    dur = None
    if last:
        h, m_, s = last[-1]
        dur = int(h) * 3600 + int(m_) * 60 + int(s)

    rec = {
        "leader_slug": slug,
        "source_id": sid,
        "video_id": None,
        "url": cand["url"],
        "declared_title": meta.get("hs_title") or cand["episode"],
        "declared_venue": cand["show"],
        "declared_kind": "podcast",
        # Still 0, which both judge-prompt builders (grade.py and
        # grading_contract.py) print as "unknown", even when the page states a
        # publication date. The year is a GRADING input: every Happy Scribe
        # transcript on the leaders board was graded with no year, so writing
        # one here would change the judge's prompt for new transcripts only.
        # The date travels in statement_date instead, which only the
        # predictions pipeline reads. The key stays, rather than going, so the
        # record keeps every core field the YouTube fetcher writes.
        "declared_year": 0,
        "caption_track": "happyscribe",
        "word_count": words,
        "char_count": len(text),
        "duration_sec": dur,
        "n_timestamp_marks": n_marks,
        "fetched_at_utc": fetched_at,
        "fetch_method": "happyscribe",
        # extract_transcript unescapes on both paths since 2026-09-28. Records
        # written before then lack this key and still hold "&#39;", and their
        # quote offsets were measured against that escaped text. The key lets a
        # read-time view unescape only the old records, never a new one twice.
        "text_unescaped": True,
        "hs_show": cand["show"],
        "hs_episode": cand["episode"],
        **meta,
        "text": text,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    os.replace(tmp, dest)
    status = {"status": "ok", "leader_slug": slug, "source_id": sid, "words": words,
              "path": str(dest)}
    if DATE_UNREADABLE in meta:
        # A success, and still never a quiet one: it is logged here and counted
        # and named in the summary main prints.
        status[DATE_UNREADABLE] = meta[DATE_UNREADABLE]
        log(f"  {slug}/{sid}: written WITHOUT a statement date: {meta[DATE_UNREADABLE]}")
    return status


def fetch_summary(attempted: int, results: list[dict]) -> dict:
    """attempted / succeeded / failed with an error taxonomy, plus every record
    written without a readable date, counted and named.

    Those records are successes: the transcript is kept for the leaders board,
    which never reads the date. They are counted apart so that a page layout
    change that breaks the date shows up here, on the cycle it happens, and not
    later as a column of undated predictions.
    """
    ok = [r for r in results if r["status"] == "ok"]
    cached = [r for r in results if r["status"] == "cached"]
    failed = [r for r in results if r["status"] == "failed"]
    tax: dict[str, int] = {}
    for r in failed:
        tax[r["error_type"]] = tax.get(r["error_type"], 0) + 1
    undated = [{"leader_slug": r["leader_slug"], "source_id": r["source_id"],
                DATE_UNREADABLE: r[DATE_UNREADABLE]} for r in ok if DATE_UNREADABLE in r]
    return {
        "attempted": attempted,
        "succeeded": len(ok) + len(cached),
        "newly_fetched": len(ok),
        "cached": len(cached),
        "failed": len(failed),
        "error_taxonomy": tax,
        "written_with_unreadable_date": len(undated),
        "unreadable_dates": undated,
        "total_words": sum(r.get("words", 0) for r in ok),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    # Defaults come from the study; for leaders they are the old data/ paths.
    ap.add_argument("--roster", default=None, help="Default: <study data>/roster/final.json.")
    ap.add_argument("--candidates", default=None,
                    help="Default: <study data>/sources/happyscribe_candidates.json.")
    ap.add_argument("--out", default=None, help="Default: <study data>/transcripts_hs.")
    ap.add_argument("--errors", default=None, help="Default: <study data>/logs/happyscribe_errors.jsonl.")
    ap.add_argument("--target-per-leader", type=int, default=5)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-sitemaps", type=int, default=40)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default=None,
                    help="Comma-separated slugs to discover, instead of the whole "
                         "roster. Use it when the roster gains people, so the pool "
                         "for everyone else is not re-derived. An unknown slug is "
                         "refused.")
    ap.add_argument("--replace-candidates", action="store_true",
                    help="Overwrite the candidate pool with this crawl instead of "
                         "merging into it, DROPPING any candidate the crawl did not "
                         "return. The dropped ids are named in the output.")
    ap.add_argument("--report-unsearched", action="store_true",
                    help="Print the roster slugs absent from the candidate pool and exit. "
                         "The pool is derived from the roster, so the loop uses this to notice "
                         "a roster change instead of assuming one never happens.")
    import study_profile as SP
    import membership as MB
    SP.add_study_arg(ap)
    MB.add_membership_arg(ap)
    args = ap.parse_args()
    SP.guard(args.study)
    link = SP.data_link(args.study)
    args.roster = args.roster or f"{link}/roster/final.json"
    args.candidates = args.candidates or f"{link}/sources/happyscribe_candidates.json"
    args.out = args.out or f"{link}/transcripts_hs"
    args.errors = args.errors or f"{link}/logs/happyscribe_errors.jsonl"
    SP.guard(args.study, args.roster, args.candidates, args.out, args.errors)

    session = make_session()
    pacer = Pacer(args.interval)

    if args.report_unsearched:
        # Space-separated on stdout so the loop can test it for emptiness, with
        # the detail on stderr so a human reading the log sees who and why.
        unsearched, stale = unsearched_leaders(
            args.roster, args.candidates, MB.for_study(args.study, args.membership))
        if stale:
            print(f"pool holds {len(stale)} leader(s) no longer on the roster: "
                  f"{', '.join(stale)}", file=sys.stderr)
        if unsearched:
            print(f"{len(unsearched)} roster leader(s) never searched: "
                  f"{', '.join(unsearched)}", file=sys.stderr)
        print(" ".join(unsearched))
        return 0

    if args.discover:
        roster = json.loads(Path(args.roster).read_text())["roster"]
        only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
        selected = select_roster(roster, only)
        found = discover(selected, session, pacer, args.max_sitemaps)
        pool_path = Path(args.candidates)
        existing: dict = {}
        if pool_path.is_file() and pool_path.stat().st_size:
            try:
                existing = json.loads(pool_path.read_text())
            except json.JSONDecodeError as e:
                # Never silently start from empty: that is the wholesale write.
                raise SystemExit(f"{args.candidates} exists but is not valid JSON "
                                 f"({e}). Fix or remove it; refusing to overwrite a "
                                 "candidate pool this run cannot read.")
        pool, merge_report = merge_pool(existing, found,
                                        replace=args.replace_candidates)
        pool_path.parent.mkdir(parents=True, exist_ok=True)
        pool_path.write_text(json.dumps(pool, indent=1, ensure_ascii=False))
        n = sum(len(v) for v in found.values())
        with_any = sum(1 for v in found.values() if v)
        print(json.dumps({
            "discovered_for": len(selected),
            "candidates_found": n,
            "leaders_with_candidates": f"{with_any}/{len(selected)}",
            "pool_slugs": len(pool),
            "pool_candidates": sum(len(v) for v in pool.values()),
            **merge_report,
            "per_leader": {k: len(v) for k, v in sorted(found.items()) if v},
            "leaders_with_none": sorted(k for k, v in found.items() if not v),
        }, indent=2))
        return 0

    if not args.fetch:
        ap.error("pass --discover, --fetch or --report-unsearched")

    cands = json.loads(Path(args.candidates).read_text())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for slug, items in sorted(cands.items()):
        have = len(list((out_dir / slug).glob("*.json"))) if (out_dir / slug).exists() else 0
        for c in items[: max(0, args.target_per_leader - have) + 3]:
            jobs.append((slug, c))
    log(f"{len(jobs)} happyscribe pages queued across {len(cands)} leaders "
        f"at {args.interval}s pace, {args.workers} workers")

    results = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, c, slug, out_dir, session, pacer, args.force): (slug, c)
                for slug, c in jobs}
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 10 == 0:
                ok = sum(1 for x in results if x["status"] in ("ok", "cached"))
                log(f"  {done}/{len(jobs)} attempted | {ok} succeeded")

    failed = [r for r in results if r["status"] == "failed"]
    Path(args.errors).parent.mkdir(parents=True, exist_ok=True)
    with open(args.errors, "w") as fh:
        for r in failed:
            fh.write(json.dumps(r) + "\n")
    print(json.dumps(fetch_summary(len(jobs), results), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
