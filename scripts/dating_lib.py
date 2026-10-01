#!/usr/bin/env python3
"""Pure functions for the dating stage: when were the words in a recording spoken?

Rescue round 4 (design section 1, critiques 1 and 3), operator decision VD-8 (c)
of 2026-09-29, "see what happens": ONE agent identifies the event and its date
range and cites sources with verbatim excerpts. A script with no model then
fetches each cited page and must find the excerpt on it, with a date inside the
agent's own range. The recording's own page never counts, with one exception
since 2026-10-01: its stored DESCRIPTION, when it states the event's date (the
agent's description_evidence, or Tier 0, the description's one full day). A
confirmed result is an override entry that vouches for itself on every load;
anything else is queued for a person with its reason.

WHY. No stage ever tried to find out when a recording was made. Code copied the
YouTube upload date, or nothing, into the date the card prints as "Said", and a
2012 D10 interview re-uploaded in 2019 had "next year" resolved to 2020. The
models noticed, in notes that nothing reads.

What lives here, and nothing else (no network, no model, no argparse):
  - the prompt (DATING_TASK), its input block and the proposal schema
  - dates in text, and the time zone rule: a speech keeps the date where it
    happened, a publication is read in UTC
  - the own-page rule: the recording's own video page, any YouTube page (by host,
    or by YouTube's own page shapes /watch?v=, /channel/UC and /@handle on any
    mirror), an archive copy, the transcript's own url and a Wayback copy of any
    of them never confirm
  - the source check of one fetched page, and the stored window it keeps
  - the merge of one proposal (MERGE_VERSION), and the loader's re-verification
    of an entry from its stored proposal and windows
  - the leads block: dated sentences from extraction and verification notes,
    with claim and outcome text removed (critique 1 point 14)

`scripts/date_recordings.py` drives it; `predictions_lib.load_statement_date_overrides`
calls `verify_agent_entry` on every agent entry it loads.
"""
from __future__ import annotations

import hashlib
import html as htmlmod
import json
import re
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402

# The rules below, as one named version. An entry records the version that wrote
# it and the loader re-runs exactly that version, so an edit that changes what
# confirms a date must bump this, or every stored entry refuses to load (loud,
# by design: critique 3 C3).
# merge-1 never shipped; merge-2 was the review fixes of 2026-09-30. merge-3 (2026-10-01): the
# recording's own description counts when it states the event's date (cited, or Tier 0).
MERGE_VERSION = "merge-3"
MERGE_VERSIONS = (MERGE_VERSION,)
# How an entry was confirmed. A cited page or the description of ONE dater's proposal
# (METHOD), or two daters naming the same last day with nothing confirmed (VD-11).
METHOD = "agent_plus_source_check"
AGREEMENT_METHOD = "two_agent_agreement"
METHODS = (METHOD, AGREEMENT_METHOD)
# The daters each in-scope recording gets, in the order the merge reads them
# (operator decision VD-11, 2026-10-01): Gemini searches, Fable answers from memory.
DATERS = ("gemini", "fable")

VERDICTS = ("dated", "publication_only", "cannot_date")
EVENT_KINDS = ("conference_session", "keynote", "earnings_call", "podcast_episode", "interview", "lecture",
               "letter", "other")
OPENING_WORDS = 800          # design 1.4 input block
CLOSING_WORDS = 300
PASSAGE_CONTEXT_WORDS = 30
MAX_PASSAGES = 40            # the cap is reported in the prompt and the run log when it bites
MAX_LEADS = 12
MIN_EXCERPT_WORDS = 4        # a bare "May 30, 2012" would match any page that prints the day
WINDOW_CHARS = 1000          # kept each side of the excerpt (about 2 KB); the page itself is only hashed

AGREEMENT_RULE = ("statement_date is the last day that every dater named independently, exactly that day; "
                  "each proposal passed every rule before the source checks, so none ends after the upper "
                  "bound; no cited page or description confirmed it")
ZONE_RULE = ("a speech, session or interview is dated in the local time of the place where it happened; "
             "a publication (verdict publication_only) is dated in UTC")
RULE = ("statement_date is the latest day of the agent's range; the range is confirmed only when a fetched "
        "page that is not the recording's own carries the cited excerpt and a date inside the range, or the "
        "recording's stored description states a date inside the range (cited, or its one full day: Tier 0); "
        "a confirming source must show the latest day")

# ---------------------------------------------------------------------------
# Dates in text
# ---------------------------------------------------------------------------

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
           "oct": 10, "nov": 11, "dec": 12}
_MON = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_ZONES = ("PT", "PST", "PDT", "ET", "EST", "EDT", "CT", "CST", "CDT", "MT", "MST", "MDT", "UTC", "GMT", "BST",
          "CET", "CEST")
_TIME = (r"(?:\s*(?:at|,|@)?\s*(\d{1,2})[:.](\d{2})\s*(?:([ap])\.?\s*m\.?)?)?"
         r"(?:\s*\(?(" + "|".join(_ZONES) + r")\)?)?")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?)?")
_MDY = re.compile(r"\b" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–]\s*(\d{1,2})(?:st|nd|rd|th)?)?,?\s+"
                  r"(\d{4})\b" + _TIME, re.I)
_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–]\s*(\d{1,2})(?:st|nd|rd|th)?)?\s+(?:of\s+)?" + _MON +
                  r"\.?,?\s+(\d{4})\b", re.I)
_MY = re.compile(r"\b" + _MON + r"\.?,?\s+(\d{4})\b", re.I)
_FIXED = {"UTC": 0, "GMT": 0, "Z": 0, "BST": 1, "CET": 1, "CEST": 2, "PST": -8, "PDT": -7, "EST": -5,
          "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6}
_US_GENERIC = {"PT": (-8, -7), "ET": (-5, -4), "CT": (-6, -5), "MT": (-7, -6)}


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _us_dst(d: date) -> bool:
    """US daylight time on this local date, by the rule in force that year (the 2007 change included)."""
    if d.year >= 2007:
        return _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)
    return _nth_sunday(d.year, 4, 1) <= d < _last_sunday(d.year, 10)


def _utc_date(local: date, hour: int, minute: int, zone: str) -> date:
    z = zone.upper()
    if z in _US_GENERIC:
        std, dst = _US_GENERIC[z]
        offset = dst if _us_dst(local) else std
    elif z in _FIXED:
        offset = _FIXED[z]
    else:
        sign = -1 if z.startswith("-") else 1
        hh, mm = z[1:3], z[-2:]
        return (datetime(local.year, local.month, local.day, hour, minute)
                - sign * timedelta(hours=int(hh), minutes=int(mm))).date()
    return (datetime(local.year, local.month, local.day, hour, minute) - timedelta(hours=offset)).date()


def _is_utc(zone: str) -> bool:
    return zone.upper().replace(":", "") in ("Z", "UTC", "GMT", "+0000", "-0000")


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d) if 1900 <= y <= 2100 else None
    except ValueError:
        return None


def dates_in_text(text: str) -> list[dict]:
    """Every date WITH A YEAR in the text, in order: {lo, hi, text, utc_lo, utc_hi, utc_stamp}."""
    return [{k: v for k, v in d.items() if k not in ("at", "end")} for d in _dates_located(text)]


def _dates_located(text: str) -> list[dict]:
    """dates_in_text with each date's character offsets, "at" and "end".

    A day gives lo == hi; "September 7-9, 2025" a range; "August 2023" the whole
    month. A time with a zone ("4:26 pm PT", "T01:30:00+02:00") also gives the UTC
    date, which only a publication is read in. A bare year, or a day with no year,
    is not a date here: "Sep 13" could be any year.
    """
    out: list[dict] = []
    taken: list[tuple[int, int]] = []

    def free(m) -> bool:
        return not any(m.start() < b and a < m.end() for a, b in taken)

    def add(m, lo, hi, utc=None, utc_stamp=False):
        if lo is None or hi is None or hi < lo:
            return
        taken.append((m.start(), m.end()))
        out.append({"at": m.start(), "end": m.end(), "lo": lo, "hi": hi, "text": m.group(0).strip(),
                    "utc_lo": utc or lo, "utc_hi": utc or hi, "utc_stamp": utc_stamp})

    for m in _ISO.finditer(text):
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        utc = _utc_date(d, int(m.group(4)), int(m.group(5)), m.group(6)) if d and m.group(4) and m.group(6) else None
        add(m, d, d, utc, utc_stamp=bool(m.group(4) and m.group(6) and _is_utc(m.group(6))))
    for m in _MDY.finditer(text):
        if not free(m):
            continue
        mon, y = _MONTHS[m.group(1)[:3].lower()], int(m.group(4))
        lo, hi = _mk(y, mon, int(m.group(2))), _mk(y, mon, int(m.group(3) or m.group(2)))
        utc = None
        if lo and lo == hi and m.group(5) and m.group(8):
            hour = int(m.group(5)) % 12 + (12 if (m.group(7) or "").lower() == "p" else 0) \
                if m.group(7) else int(m.group(5))
            utc = _utc_date(lo, hour, int(m.group(6)), m.group(8))
        add(m, lo, hi, utc, utc_stamp=bool(m.group(5) and m.group(8) and _is_utc(m.group(8))))
    for m in _DMY.finditer(text):
        if not free(m):
            continue
        mon, y = _MONTHS[m.group(3)[:3].lower()], int(m.group(4))
        add(m, _mk(y, mon, int(m.group(1))), _mk(y, mon, int(m.group(2) or m.group(1))))
    for m in _MY.finditer(text):
        if not free(m):
            continue
        mon, y = _MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        first = _mk(y, mon, 1)
        last = (_mk(y + (mon == 12), mon % 12 + 1, 1) - timedelta(days=1)) if first else None
        add(m, first, last)
    out.sort(key=lambda d: d["at"])
    return out


def date_for_verdict(d: dict, verdict: str) -> tuple[date, date] | None:
    """The zone rule: a speech keeps its written, local date; a publication is read in UTC.

    A time stamped in UTC cannot date a speech at all (review item 13): 9:30 pm PT on
    May 30 is 04:30Z on May 31, and nothing in the stamp says where the venue was.
    None means "this date cannot be used for this verdict".
    """
    if verdict == "publication_only":
        return d["utc_lo"], d["utc_hi"]
    if d.get("utc_stamp"):
        return None
    return d["lo"], d["hi"]


# ---------------------------------------------------------------------------
# The recording's own page never counts
# ---------------------------------------------------------------------------

YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
# archive.today keeps copies under several names, and a copy of an unknown page may
# be the recording's own; front ends re-serve YouTube pages under other hosts.
ARCHIVE_COPY_HOSTS = ("archive.ph", "archive.today", "archive.is", "archive.li", "archive.vn", "archive.fo",
                      "archive.md", "ghostarchive.org")
FRONT_END_HOSTS = ("yewtu.be",)
FRONT_END_WORDS = ("invidious", "piped")
# YouTube's own page shapes, refused on ANY host (final review item 8): mirrors such as
# inv.nadeko.net and hooktube.com serve them under names no list can keep up with. A
# handle is refused as a channel page (the handle alone, or a channel tab under it),
# not every path under an @ segment: medium.com/@author/post and mastodon.social/@user/1
# are posts, which can date an event.
YOUTUBE_CHANNEL_TABS = ("videos", "streams", "shorts", "live", "featured", "playlists", "community", "about",
                        "podcasts", "releases")
# Transcript sites whose first path segment is the show: another episode page of
# the same show dates that show's uploads, not this event.
SHOW_HOSTS = ("podcasts.happyscribe.com",)
_WAYBACK = re.compile(r"^https?://(?:web\.)?archive\.org/web/[^/]*/(.+)$", re.I)


def unwrap_wayback(url: str) -> str:
    m = _WAYBACK.match(url.strip())
    inner = m.group(1) if m else url.strip()
    return inner if re.match(r"https?://", inner, re.I) else "http://" + inner


def _split(url: str) -> tuple[str, list[str], str]:
    p = urllib.parse.urlsplit(unwrap_wayback(url))
    # A fully qualified name's trailing dot (www.youtube.com.) is the same host.
    host = (p.hostname or "").lower().rstrip(".")
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    segs = [s for s in p.path.split("/") if s]
    q = "&".join(sorted(x for x in p.query.split("&") if x))
    return host, segs, q


def youtube_page_shape(segs: list[str], q: str) -> str | None:
    """"watch page" or "channel page" when the path is one of YouTube's own, on any host."""
    if segs[:1] == ["watch"] and any(x.startswith("v=") for x in q.split("&")):
        return "watch page"
    if len(segs) >= 2 and segs[0] == "channel" and segs[1].startswith("UC"):
        return "channel page"
    if segs and segs[0].startswith("@") and len(segs[0]) > 1 and (len(segs) == 1 or segs[1] in YOUTUBE_CHANNEL_TABS):
        return "channel page"
    return None


def own_page_reason(url: str, rec: dict) -> str | None:
    """Why this URL cannot confirm the recording's date, or None when it may.

    Critique 3 C2: both a model and a reader reach first for the video's own page,
    which shows only when the file was uploaded. For the D10 re-upload that is the
    2019 date the whole defect came from, so such a page is refused before any
    fetch. Every YouTube page is refused, not only this video's: a watch page dates
    an upload and a channel page lists them, and neither dates the event.
    """
    vid = rec.get("video_id")
    if vid and vid in url:
        return f"names the recording's own video id {vid}; the recording's own page dates an upload, not the event"
    host, segs, q = _split(url)
    if any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS):
        return "is a YouTube page; it dates an upload, not the event"
    if any(host == h or host.endswith("." + h) for h in ARCHIVE_COPY_HOSTS):
        return "is an archive.today copy, which could be a copy of the recording's own page; cite the page itself"
    if any(host == h or host.endswith("." + h) for h in FRONT_END_HOSTS) or \
            any(w in host for w in FRONT_END_WORDS):
        return "is a YouTube front end; it dates an upload, not the event"
    if re.match(r"^(?:www\.)?google\.[a-z.]+$", host) and segs[:1] == ["url"]:
        return "is a google.com/url redirect, which hides the page; cite the page itself"
    shape = youtube_page_shape(segs, q)
    if shape:
        return f"is a YouTube {shape} served by {host}; it dates an upload, not the event"
    own = rec.get("url")
    if own:
        ohost, osegs, _ = _split(own)
        if (host, segs) == (ohost, osegs):
            return "is the transcript's own page (the query string aside)"
        if host == ohost and host in SHOW_HOSTS and segs[:1] == osegs[:1] and segs:
            return f"is another page of the recording's own show on {host}"
    return None


# ---------------------------------------------------------------------------
# One fetched page
# ---------------------------------------------------------------------------

_SCRIPT = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(raw: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(_TAG.sub(" ", _SCRIPT.sub(" ", raw)))).strip()


def _find(hay: str, needle: str) -> tuple[int, int] | None:
    """Original offsets of the normalised needle in hay, on word boundaries, or None."""
    nn = L.normalise(needle)
    if not nn:
        return None
    nh, omap = L.normalise_with_map(hay)
    k = f" {nh} ".find(f" {nn} ")
    if k < 0:
        return None
    return omap[k], omap[k + len(nn) - 1] + 1


def _decode(body: bytes, content_type: str | None) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    try:
        return body.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def check_source(src: dict, rec: dict, fetched: dict) -> dict:
    """What the script found on one cited page. Stores a small window, never the page.

    `fetched` is {status, final_url, body (bytes), via (direct|wayback), error,
    content_type (optional)}. The window keeps WINDOW_CHARS each side of the match
    so a later load can re-check the excerpt and its date without the page.
    """
    out = {"url": src["url"], "publisher": src.get("publisher"), "cited_excerpt": src["verbatim_excerpt"],
           "refused": None, "fetched": False, "fetched_via": fetched.get("via"), "http_status": fetched.get("status"),
           "final_url": fetched.get("final_url"), "fetch_error": fetched.get("error"), "page_sha256": None,
           "excerpt_found": False, "found_in": None, "window": None, "page_span": None, "page_title": None,
           "page_names_video_id": False}
    body = fetched.get("body") or b""
    if fetched.get("error") or fetched.get("status") != 200 or not body:
        out["fetch_error"] = fetched.get("error") or f"HTTP {fetched.get('status')} with {len(body)} bytes"
        return out
    out["fetched"] = True
    out["page_sha256"] = hashlib.sha256(body).hexdigest()
    final = fetched.get("final_url") or src["url"]
    why = own_page_reason(final, rec)
    if why:
        out["refused"] = f"the cited address led to {final}, which {why}"
        return out
    raw = _decode(body, fetched.get("content_type"))
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    out["page_title"] = re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip()[:300] if m else None
    vid = rec.get("video_id")
    out["page_names_video_id"] = bool(vid and vid in raw)
    for where, hay in (("text", html_to_text(raw)), ("markup", htmlmod.unescape(raw))):
        hit = _find(hay, src["verbatim_excerpt"])
        if hit:
            s, e = hit
            out.update(excerpt_found=True, found_in=where, page_span=hay[s:e],
                       window=hay[max(0, s - WINDOW_CHARS):e + WINDOW_CHARS])
            break
    return out


def refused_check(src: dict, reason: str) -> dict:
    """A cited page that is refused before any fetch, recorded with the reason."""
    return {"url": src["url"], "publisher": src.get("publisher"), "cited_excerpt": src["verbatim_excerpt"],
            "refused": reason, "fetched": False, "fetched_via": None, "http_status": None, "final_url": None,
            "fetch_error": None, "page_sha256": None, "excerpt_found": False, "found_in": None, "window": None,
            "page_span": None, "page_title": None, "page_names_video_id": False}


def confirms(check: dict, prop: dict, rec: dict) -> tuple[bool, str]:
    """Does this stored check confirm this proposal? Re-derived from the stored window every time."""
    if check.get("refused"):
        return False, f"refused: {check['refused']}"
    for u in (check["url"], check.get("final_url")):
        why = own_page_reason(u, rec) if u else None
        if why:
            return False, f"refused: {u} {why}"
    if not check.get("fetched") or not check.get("page_sha256"):
        return False, f"the page could not be read: {check.get('fetch_error')}"
    if check.get("page_names_video_id"):
        return False, "the page embeds the recording's own video, so its dates are the upload's"
    if len(L.normalise(check["cited_excerpt"]).split()) < MIN_EXCERPT_WORDS:
        return False, f"the excerpt has fewer than {MIN_EXCERPT_WORDS} words"
    window = check.get("window") or ""
    vid = rec.get("video_id")
    if vid and vid in window:
        return False, "the window names the recording's own video id, so the page embeds the upload"
    if re.search(r"upload_?date", window, re.I):
        return False, "the window carries a video uploadDate; it dates an upload, not the event"
    hit = _find(window, check["cited_excerpt"])
    if hit is None:
        return False, "the excerpt is not on the page"
    tokens = context_tokens(rec, prop)
    hay = f" {L.normalise(window + ' ' + (check.get('page_title') or ''))} "
    if not any(f" {tok} " in hay for tok in tokens):
        return False, (f"the window and the page title name neither the speaker nor the event "
                       f"(looked for {sorted(tokens)}); it may be a page about another occasion")
    span = window[hit[0]:hit[1]]
    found = dates_in_text(span)
    if not found:
        return False, f"the excerpt carries no date with a year: {span[:80]!r}"
    usable = [r for r in (date_for_verdict(d, prop["verdict"]) for d in found) if r is not None]
    if not usable:
        return False, (f"the excerpt's only dates are UTC timestamps, which cannot give the venue's day for a "
                       f"speech: {[d['text'] for d in found]} ({ZONE_RULE})")
    e = date.fromisoformat(prop["speech_date_earliest"])
    lat = date.fromisoformat(prop["speech_date_latest"])
    if not [r for r in usable if e <= r[0] and r[1] <= lat]:
        shown = [f"{a.isoformat()}..{b.isoformat()}" for a, b in usable]
        return False, f"the excerpt's dates {shown} are outside the range {e}..{lat} ({ZONE_RULE})"
    return True, "confirms"


# Words in an event name that do not identify an occasion: a page about ANY interview
# carries "interview". A pure number is not an identifier either (a year matches pages
# about every event that year).
_EVENT_STOP = {"the", "and", "with", "for", "from", "about", "session", "interview", "conference", "keynote",
               "talk", "podcast", "episode", "full", "video", "live", "annual", "event", "day", "part", "speech",
               "lecture", "fireside", "chat", "panel", "remarks", "meeting", "call", "earnings", "show", "his",
               "her", "their", "its", "our", "upload", "recording", "discussion", "conversation", "appearance"}


def context_tokens(rec: dict, prop: dict) -> set[str]:
    """What a page about THIS occasion names: the speaker's surname, or a word of the event (review item 12)."""
    toks: set[str] = set()
    parts = [x for x in (rec.get("leader_slug") or "").split("-") if x]
    if parts:
        toks.add(L.normalise(parts[-1]))
    for w in L.normalise(prop.get("event") or "").split():
        if len(w) >= 3 and w not in _EVENT_STOP and not w.isdigit():
            toks.add(w)
    return {x for x in toks if x}


# ---------------------------------------------------------------------------
# The recording's own description (operator, 2026-10-01)
# ---------------------------------------------------------------------------
#
# FOUND by the operator: the own-page rule stopped Gemini from using the strongest
# evidence it had. bill-gates/techno-optimism-t3p9ko's description says "Bill Gates,
# Mehtap Ozkan, Saturday, February 25, 2023", the upload is 2023-04-02, and Gemini
# answered cannot_date, quoting the rule. The rule stops an agent passing off the
# UPLOAD date as the event's; a date the description STATES about the event is
# evidence. It is read from the transcript record, never fetched, so the loader
# re-checks it from the same stored text. Never the title: "What Aaron Levie Saw in
# 2004" (aaron-levie/hd-in-hd-podcast--u5-zt) names the subject, not the event.

def recording_description(rec: dict) -> str | None:
    """The description stored with the transcript: yt_description, else declared_description, else None.

    MEASURED 2026-10-01 over the 1,027 stored transcripts: yt_description on 675,
    declared_description on none (the name is kept for a web source that stores
    one). hs_description is Happy Scribe's boilerplate ("Read the full transcript
    of ..."), never the show's own words, so it is not read.
    """
    for k in ("yt_description", "declared_description"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def upper_bound(rec: dict) -> tuple[str, str] | None:
    """(YYYY-MM-DD, what it is): the own date, else the fetch date, else None. Never the local clock."""
    own_date, own_basis = L.own_statement_date(rec)
    if own_date is not None:
        return own_date, f"the {own_basis}"
    if fetch_bound(rec):
        return fetch_bound(rec), "the day this transcript was fetched (the source carries no date)"
    return None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _spans_in_range(text: str, prop: dict) -> list[tuple[date, date]]:
    """The dates in text, read for the proposal's verdict, that lie wholly inside its range."""
    e, lat = date.fromisoformat(prop["speech_date_earliest"]), date.fromisoformat(prop["speech_date_latest"])
    out = []
    for d in dates_in_text(text):
        r = date_for_verdict(d, prop["verdict"])
        if r is not None and e <= r[0] and r[1] <= lat:
            out.append(r)
    return out


# Words that, next to a day in a description, say the day dates something other than
# this event (review fixes 6 and 7): a birth, a founding, a release, premiere, upload,
# livestream, broadcast or launch, an older original, a sponsor's code or deadline,
# and the next event. Judged within the date's own sentence, up to CUE_WORDS_BEFORE
# words before it and CUE_WORDS_AFTER after it.
_CUE = re.compile(r"\b(?:born|birth(?:day)?|founded|founding|established|released?|premiere[sd]?|uploaded|"
                  r"upload|streamed|aired|launch(?:ed|es|ing)?|originally|"
                  r"(?:use|promo|discount|coupon)\s+code|sponsor(?:ed)?|deadline|until|before|expires?|"
                  r"next\s+(?:event|week|month|year|episode|show|session|time)|upcoming|coming\s+up)\b", re.I)
_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:com|org|net|io|co|tv|fm|me|ly|be|app|news)/\S*", re.I)
CUE_WORDS_BEFORE, CUE_WORDS_AFTER = 12, 3


def description_cue(desc: str, at: int, end: int) -> str | None:
    """Why the date at desc[at:end] is not this event's, or None. Never reads the title."""
    for m in _LINK.finditer(desc):
        if m.start() <= at and end <= m.end():
            return f"it is part of a link, {m.group(0)[:80]!r}"
    start = max([desc.rfind("\n", 0, at)] + [desc.rfind(p, 0, at) for p in (". ", "! ", "? ")]) + 1
    stops = [i for i in [desc.find("\n", end)] + [desc.find(p, end) for p in (". ", "! ", "? ")] if i >= 0]
    near = " ".join(desc[start:at].split()[-CUE_WORDS_BEFORE:] + ["|"]
                    + desc[end:min(stops) if stops else len(desc)].split()[:CUE_WORDS_AFTER])
    m = _CUE.search(near)
    return f"it sits next to {m.group(0)!r}, so it dates something other than this event" if m else None


def check_description(rec: dict, prop: dict) -> dict | None:
    """The agent's description_evidence checked as a page excerpt is checked, or None when it gave none.

    A normalised match on word boundaries, at least MIN_EXCERPT_WORDS words, a
    date with its year inside the agent's range, STRICTLY before the transcript's
    own date (review fix 2), and not next to a cue word or inside a link (fixes 6
    and 7). The context and embed rules of a page do not apply: the description is
    this recording's own text by construction. "spans" keeps the days that passed,
    which are the only ones the latest-day rule may read.
    """
    ev = prop.get("description_evidence")
    if not ev:
        return None
    desc = recording_description(rec) or ""
    out = {"route": "description", "basis": "cited", "cited_excerpt": ev,
           "description_sha256": _sha(desc) if desc else None, "span": None, "spans": [], "ok": False, "why": None}

    def no(why: str) -> dict:
        out["why"] = why
        return out
    if not desc:
        return no("the recording has no stored description")
    if not rec.get("url"):
        return no("the recording has no url to cite its description by")
    if len(L.normalise(ev).split()) < MIN_EXCERPT_WORDS:
        return no(f"the description excerpt has fewer than {MIN_EXCERPT_WORDS} words")
    hit = _find(desc, ev)
    if hit is None:
        return no(f"the cited words are not in the description: {ev[:80]!r}")
    out["span"] = span = desc[hit[0]:hit[1]]
    found = _dates_located(span)
    if not found:
        return no(f"the cited description words carry no date with a year: {span[:80]!r}")
    if not any(date_for_verdict(d, prop["verdict"]) for d in found):
        return no(f"the cited description dates are UTC timestamps, which cannot give the venue's day ({ZONE_RULE})")
    e, lat = date.fromisoformat(prop["speech_date_earliest"]), date.fromisoformat(prop["speech_date_latest"])
    inside = [(d, r) for d, r in ((d, date_for_verdict(d, prop["verdict"])) for d in found)
              if r is not None and e <= r[0] and r[1] <= lat]
    if not inside:
        return no(f"the description's dates {[d['text'] for d in found]} are outside the range {e}..{lat}")
    ub = upper_bound(rec)
    if ub is None:
        return no("nothing bounds the recording from above, so a description date cannot be checked against it")
    # STRICTLY before the own date (review fix 2): a description day ON the upload day is
    # an upload, premiere or livestream day, and confirming it would CHECK the upload date.
    early = [(d, r) for d, r in inside if r[1] < date.fromisoformat(ub[0])]
    if not early:
        return no(f"the description's dates in the range are not before {ub[1]}, {ub[0]}; a description date on "
                  f"or after the upload is not the event's")
    clean, cued = [], []
    for d, r in early:
        cue = description_cue(desc, hit[0] + d["at"], hit[0] + d["end"])
        (cued if cue else clean).append((d, r, cue))
    if not clean:
        return no(f"the description's date {cued[0][0]['text']!r}: {cued[0][2]}")
    out.update(ok=True, why="confirms", spans=[[r[0].isoformat(), r[1].isoformat()] for _, r, _ in clean])
    return out


def _tier0_days(desc: str) -> tuple[list[dict], list[str]]:
    """The description's full days with their year that no cue word or link disqualifies, and the ones that do."""
    days, cued = [], []
    for d in _dates_located(desc):
        if d["lo"] != d["hi"]:
            continue
        cue = description_cue(desc, d["at"], d["end"])
        if cue:
            cued.append(f"{d['text']!r}: {cue}")
        else:
            days.append(d)
    return days, cued


def tier0_day(rec: dict, verdict: str) -> tuple[str | None, str]:
    """(YYYY-MM-DD, why) when the stored description names exactly ONE full day with its year that no cue word
    disqualifies, STRICTLY before the upper bound; (None, why) otherwise. Deterministic, no model.

    Only day-precision dates count: a month, a range of days or a bare year is not
    the day of an event. A day next to a cue word or inside a link is dropped first
    (review fixes 6 and 7). Two different remaining days mean the description dates
    more than one thing, so neither is taken. The title is never read.
    """
    desc = recording_description(rec)
    if not desc:
        return None, "the recording has no stored description"
    found, cued = _tier0_days(desc)
    days: dict[date, dict] = {}
    for d in found:
        days.setdefault(d["lo"], d)
    if not days:
        return None, ("the description's only full days are not this event's: " + "; ".join(cued) if cued else
                      "the description names no full day with its year")
    if len(days) > 1:
        return None, (f"the description names {len(days)} different days "
                      f"({', '.join(sorted(x.isoformat() for x in days))}), so none is taken as the event's")
    (only, d), = days.items()
    r = date_for_verdict(d, verdict)
    if r is None:
        return None, f"the description's one day is a UTC timestamp, {d['text']!r} ({ZONE_RULE})"
    ub = upper_bound(rec)
    if ub is None:
        return None, "nothing bounds the recording from above"
    if r[0] >= date.fromisoformat(ub[0]):
        return None, f"the description's one day {r[0]} is not before {ub[1]}, {ub[0]}"
    return r[0].isoformat(), f"the description names one day, {r[0]}"


def tier0_check(rec: dict, day: str, verdict: str) -> dict:
    """The Tier 0 confirmation as a stored check: the description line that carries the day.

    The day is matched as tier0_day read it, among the same uncued days and through
    date_for_verdict, so a publication read in UTC finds its own text (review fix 4:
    matching the local day, with an eager fallback, raised IndexError).
    """
    desc = recording_description(rec) or ""
    found = [d for d in _tier0_days(desc)[0]
             if (date_for_verdict(d, verdict) or (None,))[0] is not None
             and date_for_verdict(d, verdict)[0].isoformat() == day]
    if not found:
        raise ValueError(f"tier0_check: the description carries no {verdict} day {day}; tier0_day and tier0_check "
                         f"disagree")
    text = found[0]["text"]
    line = next((ln.strip() for ln in desc.splitlines() if text in ln), text)
    return {"route": "description", "basis": "tier0", "cited_excerpt": None, "description_sha256": _sha(desc),
            "span": line[:300], "day": day, "ok": True, "why": f"the description names one day, {day}"}


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

DATING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["transcript_id", "verdict", "event", "event_kind", "speech_date_earliest", "speech_date_latest",
                 "sources", "transcript_evidence", "description_evidence", "reupload", "reasoning"],
    "properties": {
        "transcript_id": {"type": "string", "minLength": 3},
        "verdict": {"enum": list(VERDICTS)},
        "event": {"type": ["string", "null"]},
        "event_kind": {"enum": list(EVENT_KINDS) + [None]},
        "speech_date_earliest": {"type": ["string", "null"]},
        "speech_date_latest": {"type": ["string", "null"]},
        "sources": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["url", "publisher", "date_on_source", "verbatim_excerpt", "kind"],
            "properties": {"url": {"type": "string", "minLength": 8}, "publisher": {"type": "string"},
                           "date_on_source": {"type": ["string", "null"]},
                           "verbatim_excerpt": {"type": "string", "minLength": 1},
                           "kind": {"enum": ["primary", "secondary"]}}}},
        "transcript_evidence": {"type": ["string", "null"]},
        "description_evidence": {"type": ["string", "null"]},
        "reupload": {"enum": ["yes", "no", "unclear"]},
        "reasoning": {"type": "string", "minLength": 1},
    },
}

DATING_TASK = """You find WHEN the words in one recording were spoken. You do not judge any
prediction, and you are not told what anyone predicted. A script then opens every
source you cite and refuses your answer if your excerpt is not on the page, or if
the excerpt does not show a date inside the range you give. Only an answer the
script can confirm is used.

WORK IN THIS ORDER.

1. IDENTIFY THE EVENT. Use the title, the description, the channel and the
   transcript to name the occasion: a conference session, a keynote, an earnings
   call, a podcast episode, a televised interview, a lecture, a letter. Copy the
   words that identify it. A channel that re-uploads other people's videos is not
   the event.

2. FIND WHEN THE EVENT HAPPENED. Search for the event itself, not for the video:
   the organiser's schedule or press release, a dated live blog or news report of
   the session, the podcast's own episode page or feed, a company's investor
   relations page, an archived copy on web.archive.org. Prefer a source written
   at the time by the organiser or by a reporter who was there. How you read a
   source depends on your tools; see YOUR TOOLS below. Either way the script
   opens every page you cite and checks your excerpt against it, which is where a
   summary that gave the wrong day (3 of 10 checks in this project) is caught.

   THE RECORDING'S OWN PAGE NEVER COUNTS AS A SOURCE. A YouTube page of any kind,
   the page named under URL below, another page of the same show on a transcript
   site, and a web.archive.org copy of any of them date an upload, not the event.
   The script refuses them without opening them. Cite the event's own record
   instead.

   THE DESCRIPTION IS THE ONE EXCEPTION. If the Description below states when the
   event itself happened ("Recorded August 2023", "Bill Gates, Mehtap Ozkan,
   Saturday, February 25, 2023"), that date counts as evidence. Copy those words
   exactly into "description_evidence", at least four words with the date and its
   year; the script checks them against the stored description. The upload date,
   a "premiered" or "streamed live" date that YouTube shows, and a date the
   description gives for anything other than this event never count.

3. TEST THE DATE AGAINST THE TRANSCRIPT. Look for remarks that date the talk:
   "this afternoon", "welcome to the second developer conference", "we
   announced last week", a price, a product, a figure, a named event. If the
   transcript contradicts a date, that date is wrong.

4. ONLY THEN USE THE UPPER BOUND. The date labelled UPPER BOUND below is when the
   recording was uploaded or published. The words cannot have been spoken after
   it. It is often days, and sometimes years, later than the speech, because
   channels re-upload old talks. Report it as the latest possible day only when
   steps 1 to 3 find no earlier event, and say what shows that.

TIME ZONE. Date a speech, a session or an interview in the local time of the
place where it happened: a keynote that ended at 9:30 pm in San Francisco on
May 30 is May 30, although it was May 31 in UTC. Date a publication (verdict
"publication_only") in UTC.

ANSWER WITH A RANGE, NOT A GUESS. Give the first and the last day on which the
words could have been spoken, given your evidence, as YYYY-MM-DD. When a source
names the day, give the same day twice. When you know only that it was at a
three-day conference, give the three days. Never give a last day later than the
upper bound.

EXCERPTS. For every source, copy into "verbatim_excerpt" at least four
consecutive words exactly as they appear on that page, including a date written
with its year ("May 30, 2012", "30 May 2012", "2012-05-30" or "May 2012") that
falls inside your range. The script matches the words after ignoring case and
punctuation, and nothing else. An excerpt the script cannot find, or whose date
is outside your range, confirms nothing.

VERDICT
  "dated"            you identified the event and a source, or the description,
                     dates it.
  "publication_only" the recording is its own event (a podcast episode, a studio
                     interview, a letter) and the best evidence is when it was
                     published. The last day is the publication date. The first
                     day is the earliest your evidence allows.
  "cannot_date"      you could not identify the event, or could not find a source
                     for its date. This is an honest answer. A guessed date is
                     worse than none, because every deadline in the record is
                     computed from it. With "cannot_date", give null for both
                     days, for "event" and for "event_kind".

"transcript_evidence" is words copied exactly from the transcript that date the
talk, or null. "description_evidence" is words copied exactly from the
Description below that state when the event happened, or null. Give at least one
source or description_evidence with "dated" or "publication_only". "reupload"
says whether the channel re-uploaded someone else's recording.

Answer with one JSON object and nothing else."""

_PASSAGE_RE = re.compile(r"\b(?:19[89]\d|20[0-4]\d)\b|\b(?:january|february|april|june|july|august|september|"
                         r"october|november|december)\b|\b(?:march|may)\s+\d", re.I)


def _passages(words: list[str], skip_lo: int, skip_hi: int) -> tuple[list[str], int]:
    """Every dated passage outside the opening and closing, 30 words each side, greedy, non-overlapping."""
    spans: list[tuple[int, int]] = []
    for i, w in enumerate(words):
        if skip_lo <= i < skip_hi and _PASSAGE_RE.search(" ".join(words[i:i + 2])):
            if spans and i <= spans[-1][1]:
                continue
            spans.append((max(skip_lo, i - PASSAGE_CONTEXT_WORDS), min(skip_hi, i + PASSAGE_CONTEXT_WORDS + 1)))
    shown = spans[:MAX_PASSAGES]
    return [" ".join(words[a:b]) for a, b in shown], len(spans) - len(shown)


_FETCHED = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def fetch_bound(rec: dict) -> str | None:
    """The UTC date the transcript was fetched, read from the record, never from a file's mtime."""
    f = rec.get("fetched_at_utc")
    return f[:10] if isinstance(f, str) and _FETCHED.fullmatch(f) else None


#: What each harness can do, stated in its prompt. FOUND in the smoke pilot on
#: 2026-09-30: the shared text told every agent to "Open the page", and Gemini in
#: print mode may search but may not open a page or run a command. Each try was
#: soft-denied and ended the turn with an empty answer, 9 of 9 attempts on D10
#: (RunCommand twice, ReadUrlContent once). Granting it page access is not an
#: option: that permission lives in the shared agy config, which the leaders
#: board's Gemini judge also reads.
HARNESS_TOOLS = {
    "gemini": """YOUR TOOLS. You can search the web. You cannot open a page, read a URL or
run a command: if you try, this harness ends your turn and discards your answer.
So work from search results only. Cite the URL of a result, and copy into
"verbatim_excerpt" words exactly as the search result shows them, with their date.
The script then opens that page and must find your words on it; a result whose
text is shortened or reworded confirms nothing and goes to a person, which is
safe, so prefer results that quote the page.""",
    "astra": """YOUR TOOLS. You can search the web and open pages. Open each source you cite
and copy the excerpt from the page itself, not from a search-result summary.""",
    "fable": """YOUR TOOLS. You have no working tools: you cannot search or open pages. Cite
only sources you know well, with words you are confident appear on them; the
script opens every page and refuses an excerpt it cannot find there.""",
}


def build_dating_prompt(rec: dict, leads: list[str], harness: str) -> tuple[str, dict]:
    """(prompt, meta). Only the opening, the closing and the dated passages are sent.

    A long prompt raises the odds that the Gemini harness reaches for a tool, has
    it auto-denied and returns an empty answer (AGENTS.md), and the date is in
    those three places when it is anywhere. meta reports what the caps cut.
    """
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    own_date, own_basis = L.own_statement_date(rec)
    labels = {"youtube_upload_date": "YouTube upload date", "publication_date": "publication date",
              "stated_in_page": "stated in the source"}
    fetched = fetch_bound(rec)
    upper = (f"UPPER BOUND: {own_date} ({labels.get(own_basis, own_basis)})" if own_date else
             f"UPPER BOUND: {fetched} (the day this transcript was fetched; the source itself carries no date)"
             if fetched else "UPPER BOUND: none (the source carries no date)")
    words = (rec.get("text") or "").split()
    opening = words[:OPENING_WORDS]
    closing = words[max(OPENING_WORDS, len(words) - CLOSING_WORDS):]
    passages, cut = _passages(words, OPENING_WORDS, max(OPENING_WORDS, len(words) - CLOSING_WORDS))
    page_dates = rec.get("page_dates") or []
    lead_block = ("LEADS FROM EARLIER STAGES: none" if not leads else
                  "LEADS FROM EARLIER STAGES (unverified; use them to search, never cite them)\n"
                  + "\n".join(f"- {x}" for x in leads))
    cut_note = f", {cut} more cut by the cap of {MAX_PASSAGES}" if cut else ""
    if harness not in HARNESS_TOOLS:
        raise ValueError(f"no tool statement for harness {harness!r}; expected one of {sorted(HARNESS_TOOLS)}")
    prompt = f"""{DATING_TASK}

{HARNESS_TOOLS[harness]}

It must validate against this schema:

{json.dumps(DATING_SCHEMA, indent=1)}

transcript_id must be exactly: {tid}

=========================== RECORDING ===========================
Speaker: {rec['leader_slug'].replace('-', ' ').title()}
Title: {rec.get('yt_title') or rec.get('declared_title') or 'unknown'}
Channel or publisher: {rec.get('yt_channel') or rec.get('declared_venue') or 'unknown'}
URL: {rec.get('url') or 'unknown'}
Source id: {rec['source_id']}
{upper}
Dates the page itself carried: {json.dumps(page_dates) if page_dates else 'none recorded'}

Description:
{recording_description(rec) or '(none)'}

Transcript opening (first {len(opening)} words):
{' '.join(opening)}

Transcript closing (last {len(closing)} words):
{' '.join(closing) if closing else '(the opening is the whole transcript)'}

Passages that mention a year or a month ({len(passages)} shown{cut_note}):
{chr(10).join('- ' + p for p in passages) if passages else '(none)'}

{lead_block}
========================= END RECORDING =========================

Answer with the JSON object now."""
    return prompt, {"opening_words": len(opening), "closing_words": len(closing), "passages_shown": len(passages),
                    "passages_cut": cut, "leads": len(leads), "prompt_words": len(prompt.split())}


def validate_proposal(obj: dict, tid: str) -> list[str]:
    """Schema, then the rules a proposal must meet before any source is checked."""
    errs = L.check_schema(obj, DATING_SCHEMA)
    if errs:
        return errs
    if obj["transcript_id"] != tid:
        errs.append(f"transcript_id {obj['transcript_id']!r} is not {tid}")
    e, lat = obj["speech_date_earliest"], obj["speech_date_latest"]
    if obj["verdict"] == "cannot_date":
        if e or lat or obj["event_kind"] is not None:
            errs.append("cannot_date carries dates or an event kind")
        return errs
    for name, v in (("speech_date_earliest", e), ("speech_date_latest", lat)):
        if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) or _mk(*map(int, v.split("-"))) is None:
            errs.append(f"{name} {v!r} is not a real YYYY-MM-DD date")
    if not errs and e > lat:
        errs.append(f"speech_date_earliest {e} is after speech_date_latest {lat}")
    if not obj["sources"] and not (obj.get("description_evidence") or "").strip():
        errs.append(f"verdict {obj['verdict']} cites no source and no description_evidence")
    if not (obj["event"] or "").strip() or obj["event_kind"] is None:
        errs.append(f"verdict {obj['verdict']} names no event or event kind")
    return errs


# ---------------------------------------------------------------------------
# Leads, with claim and outcome text removed (critique 1 point 14)
# ---------------------------------------------------------------------------

_LEAD_YEAR = re.compile(r"\b(?:19[89]\d|20[0-4]\d)\b")
# Words that belong to a claim or to what happened after it. A sentence that
# carries one is dropped whole: the agent is told nothing about any prediction.
_CLAIM_OUTCOME = re.compile(r"\b(?:will|would|predict\w*|forecast\w*|expect\w*|claim\w*|criterion|criteria|"
                            r"target\w*|deadline|occurred|came true|come true|happened|did not happen|"
                            r"fails?|failed|pass(?:es)?|succeeded|achieved|resolv\w*|outcome|turned out|in fact|"
                            r"actually|G[1-5]|gates?|quot(?:e|es|ed|ing)|refer(?:s|red)? to)\b", re.I)
# A note's date reasoning usually runs "<when the recording was made>, so <what that
# makes the claim mean>". Only the first half is about the recording.
_SO_CLAUSE = re.compile(r",?\s+so\s+.*$", re.S)


def _grams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    w = L.normalise(text).split()
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def leads_from_records(records: list[dict], meta: dict | None) -> tuple[list[str], dict]:
    """Dated sentences earlier stages wrote about this recording, for the agent to SEARCH with.

    Only extraction and verification notes, the stages' date doubts and the
    extractor's attribution notes. Never a resolver's or a prior's reasoning,
    which can name what happened (critique 1 point 14: a835b240's resolution said
    "The milestone came approximately twelve months after the statement"). A
    sentence is kept only when it names a date other than the record's own, and
    carries no claim or outcome word and no four words in a row from the quote,
    the claim or either criterion. Returns (leads, dropped counts by reason).
    """
    dropped = {"claim_or_outcome_words": 0, "no_date": 0, "same_as_statement_date": 0, "shares_claim_text": 0,
               "duplicate": 0, "cut_by_cap": 0}
    leads: list[str] = []
    seen: set[str] = set()

    def consider(text: str | None, rec: dict | None) -> None:
        for s in re.split(r"(?<=[.!?;])\s+", (text or "").strip()):
            s = s.strip()
            cut = _SO_CLAUSE.sub("", s).rstrip(" .;:,")
            if cut != s.rstrip(" .;:,"):
                s = cut + "."
            if not s:
                continue
            if _CLAIM_OUTCOME.search(s):
                dropped["claim_or_outcome_words"] += 1
                continue
            years = {int(y) for y in _LEAD_YEAR.findall(s)} | {d["lo"].year for d in dates_in_text(s)}
            if not years:
                dropped["no_date"] += 1
                continue
            said = ((rec or first or {}).get("source") or {}).get("statement_date")
            if said and years == {int(said[:4])}:
                dropped["same_as_statement_date"] += 1
                continue
            if rec is not None:
                own = set()
                for t in ((rec.get("source") or {}).get("quote"), (rec.get("prediction") or {}).get("normalized_claim"),
                          (rec.get("prediction") or {}).get("resolution_criteria"),
                          (rec.get("verification") or {}).get("verifier_resolution_criteria")):
                    own |= _grams(t or "")
                if _grams(s) & own:
                    dropped["shares_claim_text"] += 1
                    continue
            key = L.normalise(s)
            if key in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(key)
            leads.append(s)

    first = records[0] if records else None
    for r in records:
        consider((r.get("extraction") or {}).get("gate_notes"), r)
        consider(((r.get("extraction") or {}).get("statement_date_doubt") or {}).get("evidence"), r)
        consider((r.get("verification") or {}).get("notes"), r)
        consider(((r.get("verification") or {}).get("statement_date_doubt") or {}).get("evidence"), r)
    consider(((meta or {}).get("extract") or {}).get("attribution_notes"), None)
    if len(leads) > MAX_LEADS:
        dropped["cut_by_cap"] = len(leads) - MAX_LEADS
        leads = leads[:MAX_LEADS]
    return leads, dropped


# ---------------------------------------------------------------------------
# The merge of one proposal (MERGE_VERSION)
# ---------------------------------------------------------------------------

def strong_years(rec: dict) -> set[int]:
    """Years a title or a source id names, no later than the upload: statement_date_evidence's STRONG signals."""
    import statement_date_evidence as SDE  # noqa: PLC0415
    ev = SDE.evidence_for(rec)
    up = ev["upload_year"]
    return {s["year"] for s in ev["signals"] if s["source"] in SDE.STRONG and (up is None or s["year"] <= up)}


PAGE_CHECK_KEYS = ("url", "publisher", "cited_excerpt", "fetched_via", "http_status", "final_url", "page_sha256",
                   "found_in", "window", "page_span", "refused", "fetched", "fetch_error", "excerpt_found",
                   "page_title", "page_names_video_id")


def _queue(reason: str, detail: str, checks: list | None = None) -> dict:
    return {"outcome": "queue", "reason": reason, "detail": detail, "checks": checks or []}


def assess(rec: dict, doc: dict, checks: list[dict]) -> dict:
    """One proposal under the rules for ONE proposal, before any other dater's proposal is read.

    Returns {"harness", "prop", "eligible", "confirmed", "queue", "good", "spans"}.
    eligible: the proposal passed every rule before the source checks (valid, a date,
    not a re-upload's publication date, inside the upper bound, its transcript
    evidence found), which is what two_agent_agreement needs. confirmed: a
    confirming source also shows its last day. The rules run in the order of the
    reasons a person reads in the queue:
      invalid_proposal, cannot_date, reupload_publication_only,
      no_upper_bound / after_upper_bound (design 1.5 rule 5: the Singju "Sep 13"
      for a Sep 12 upload; an undated source is bounded by its fetch date),
      transcript_evidence_not_found, no_confirming_source (with every check's
      reason), latest_day_unsourced.
    """
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    out = {"harness": doc.get("harness") or "agent", "prop": doc["proposal"], "eligible": False,
           "confirmed": False, "queue": None, "good": [], "spans": []}

    def queued(reason: str, detail: str, cks: list | None = None) -> dict:
        out["queue"] = _queue(reason, detail, cks)
        return out
    prop = doc["proposal"]
    errs = validate_proposal(prop, tid)
    if errs:
        return queued("invalid_proposal", "; ".join(errs[:5]))
    if prop["verdict"] == "cannot_date":
        return queued("cannot_date", prop["reasoning"][:400])
    if prop["verdict"] == "publication_only" and prop.get("reupload") == "yes":
        return queued("reupload_publication_only", "the agent says the channel re-uploaded someone else's recording, "
                                                   "so the date it was published there is not the event's")
    e, lat = prop["speech_date_earliest"], prop["speech_date_latest"]
    ub = upper_bound(rec)
    if ub is None:
        return queued("no_upper_bound", "the source carries no date and the record no fetched_at_utc, so nothing "
                                        "bounds the range from above")
    bound, what = ub
    if lat > bound:
        return queued("after_upper_bound", f"the range ends {lat}, after {what}, {bound}; the words cannot have "
                                           f"been spoken after that")
    te = prop.get("transcript_evidence")
    if te and "error" in L.locate_quote(rec.get("text") or "", te) and \
            L.locate_quote(rec.get("text") or "", te)["error"] in ("not_found", "empty_quote"):
        return queued("transcript_evidence_not_found", f"{te[:200]!r} is not in the transcript")
    out["eligible"] = True
    # A check counts only for a url AND excerpt the proposal itself cited (review item 10), so
    # neither a stray check nor one swapped in later can confirm, at merge or at load.
    # Description checks are DERIVED here from the transcript, never taken as input: a
    # stored one (route "description") is what an entry recorded, and is re-derived.
    pages = [c for c in checks if c.get("route", "page") == "page"]
    cited = {(s["url"], L.normalise(s["verbatim_excerpt"])) for s in prop["sources"]}
    verdicts = [(c, False, "the proposal did not cite this url and excerpt")
                if (c["url"], L.normalise(c["cited_excerpt"])) not in cited else (c, *confirms(c, prop, rec))
                for c in pages]
    good = [c for c, ok, _ in verdicts if ok]
    reasons = [f"{c['url']}: {why}" for c, _, why in verdicts]
    desc = check_description(rec, prop)
    if desc is not None:
        if desc["ok"]:
            good.append(desc)
        else:
            reasons.append(f"description: {desc['why']}")
    if not (desc and desc["ok"]):
        # Tier 0: one day in the description, inside the agent's range, needs no citation.
        day, why = tier0_day(rec, prop["verdict"])
        if day is not None and e <= day <= lat:
            good.append(tier0_check(rec, day, prop["verdict"]))
        else:
            reasons.append(f"description, Tier 0: {why if day is None else f'its one day {day} is outside the range {e}..{lat}'}")
    if not good:
        return queued("no_confirming_source", "; ".join(reasons) or "no source was checked",
                      [dict(c) for c in pages] + ([desc] if desc else []))
    # The statement date is the LAST day of the range, so a source must show that day
    # (review item 2): "September 7-9, 2025", "May 2012" or the publication day itself.
    spans = []
    for c in good:
        if c.get("route") == "description":
            # Only the days the description check accepted, never every date in its span (review
            # fixes 2, 6, 7): a cued or upload-day date beside a good one must not source the last day.
            spans += ([(date.fromisoformat(c["day"]),) * 2] if c["basis"] == "tier0" else
                      [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in c["spans"]])
            continue
        s, t_ = _find(c["window"], c["cited_excerpt"])
        spans += _spans_in_range(c["window"][s:t_], prop)
    if not any(a <= date.fromisoformat(lat) <= b for a, b in spans):
        return queued("latest_day_unsourced", f"no confirming excerpt shows {lat}, the last day of the range and so "
                                              f"the statement date; they show "
                                              f"{sorted({(a.isoformat(), b.isoformat()) for a, b in spans})}")
    out.update(confirmed=True, good=good, spans=spans)
    return out


def _check_record(c: dict, harness: str) -> dict:
    """A confirming check as an entry stores it, tagged with the dater whose proposal it checked."""
    if c.get("route") == "description":
        return {**c, "proposal": harness}
    return {"route": "page", "proposal": harness, **{k: c[k] for k in PAGE_CHECK_KEYS}}


def _proposal_record(doc: dict, ref: dict | None) -> dict:
    prop = doc["proposal"] if isinstance(doc.get("proposal"), dict) else {}
    return {"harness": doc.get("harness") or "agent", "path": (ref or {}).get("path"),
            "sha256": (ref or {}).get("sha256"), "requested_model": doc.get("requested_model"),
            "served_model": doc.get("served_model"), "served_model_verified": doc.get("served_model_verified"),
            "identity": doc.get("identity"), "verdict": prop.get("verdict"),
            "range": [prop.get("speech_date_earliest"), prop.get("speech_date_latest")]}


def _strong_year_conflict(rec: dict, e: str, lat: str) -> dict | None:
    years = strong_years(rec)
    if years and not (years & set(range(int(e[:4]), int(lat[:4]) + 1))):
        return _queue("strong_year_conflict", f"the title or source id names {sorted(years)}; the confirmed range "
                                              f"{e}..{lat} does not include it")
    return None


def _entry(rec: dict, prop: dict, verdict: str, e: str, lat: str, source_url: str, evidence: str,
           evidenced: bool, te: str | None, confirmation: dict, basis_note: str = "") -> dict:
    own_date, _ = L.own_statement_date(rec)
    kind = "check" if own_date is not None and lat == own_date else "override"
    return {
        "statement_date": lat,
        "basis": f"{prop['event'].strip()} ({prop['event_kind']}"
                 + ("; publication date" if verdict == "publication_only" else "") + basis_note + ")",
        "source_url": source_url,
        "verbatim_evidence": evidence,
        "confirmed_by": L.AGENT_CONFIRMATION,
        "earliest_evidenced": evidenced,
        **({"statement_date_earliest": e, "precision": L.date_precision(e, lat)} if e != lat else {}),
        **({"internal_evidence": f"Transcript: {te}"} if te else {}),
        "confirmation": {"merge_version": MERGE_VERSION, "kind": kind, "verdict": verdict, "range": [e, lat],
                         "zone_rule": ZONE_RULE, **confirmation},
    }


def merge(rec: dict, docs: list[dict], checks_by: dict[str, list[dict]], refs: dict | None = None,
          run_rel: str | None = None) -> dict:
    """Every dater's proposal for one recording -> {"outcome": "override" | "check", "entry"} or a queue row.

    Operator decision VD-11 (2026-10-01). Deterministic, and the function the loader
    re-runs. In order:
      1. each proposal is assessed alone (assess);
      2. two proposals confirmed by their own checks on DIFFERENT last days:
         queued as dater_disagreement, never one of them;
      3. any confirmed proposal: its last day, from the first confirmed dater in
         the order given (DATERS), recording every proposal the merge read;
      4. nothing confirmed, two or more proposals, every one past the rules before
         the checks, and every one naming the SAME last day, exactly: that day,
         with method two_agent_agreement;
      5. otherwise queued: one proposal's own reason, or for several the common
         reason, else no_confirmation, with each dater's reason in by_dater.
    A strong title or source-id year the range misses queues 3 and 4 alike.
    The outcome is "override" for a date before the transcript's own, "check" for
    one that confirms it. The entry has no confirmed_at_utc; the caller stamps it.
    """
    hs = [d.get("harness") or "agent" for d in docs]
    if not docs or len(set(hs)) != len(hs):
        raise ValueError(f"merge takes one proposal per dater; got harnesses {hs}")
    # A proposal names the daters of the run that made it (sha256-pinned), so a merge or a
    # stored entry that leaves one out, where a disagreement could hide, is refused.
    for d, h in zip(docs, hs):
        if d.get("daters") is not None and sorted(d["daters"]) != sorted(hs):
            raise ValueError(f"the {h} proposal was made in a run whose daters are {d['daters']}, but the merge "
                             f"read {hs}; a dater's proposal is missing or extra")
    refs = refs or {}
    found = [assess(rec, d, checks_by.get(h) or []) for d, h in zip(docs, hs)]
    proposals = [_proposal_record(d, refs.get(h)) for d, h in zip(docs, hs)]
    confirmed = [a for a in found if a["confirmed"]]
    if len({a["prop"]["speech_date_latest"] for a in confirmed}) > 1:
        return {**_queue("dater_disagreement", "; ".join(
            f"{a['harness']} confirmed {a['prop']['speech_date_latest']} by "
            f"{', '.join(c.get('route') or 'page' for c in a['good'])}" for a in confirmed),
            [_check_record(c, a["harness"]) for a in confirmed for c in a["good"]]),
            "by_dater": {a["harness"]: ("confirmed" if a["confirmed"] else a["queue"]["reason"]) for a in found}}
    if confirmed:
        lead = confirmed[0]
        prop = lead["prop"]
        e, lat = prop["speech_date_earliest"], prop["speech_date_latest"]
        conflict = _strong_year_conflict(rec, e, lat)
        if conflict:
            return conflict
        first = lead["good"][0]
        desc = first.get("route") == "description"
        return _confirmed(_entry(
            rec, prop, prop["verdict"], e, lat,
            # A description lives on the recording's own page, so that page is its address.
            rec["url"] if desc else first["url"], first["span"] if desc else first["page_span"],
            any(a == date.fromisoformat(e) for a, _ in lead["spans"]), prop.get("transcript_evidence"),
            {"method": METHOD, "rule": RULE, "run": run_rel, "lead": lead["harness"], "proposals": proposals,
             "source_checks": [_check_record(c, a["harness"]) for a in confirmed for c in a["good"]]}))
    lats = {a["prop"].get("speech_date_latest") for a in found}
    if len(found) >= 2 and all(a["eligible"] for a in found) and len(lats) == 1:
        lat = lats.pop()
        e = min(a["prop"]["speech_date_earliest"] for a in found)
        conflict = _strong_year_conflict(rec, e, lat)
        if conflict:
            return conflict
        if not rec.get("url"):
            return _queue("agreement_without_address", "two daters agree, but the record has no url to name as the "
                                                       "entry's source")
        verdict = "dated" if all(a["prop"]["verdict"] == "dated" for a in found) else "publication_only"
        te = next((a["prop"]["transcript_evidence"] for a in found if a["prop"].get("transcript_evidence")), None)
        return _confirmed(_entry(
            rec, found[0]["prop"], verdict, e, lat, rec["url"],
            f"No page or description confirmed this day: {' and '.join(hs)} each named {lat} independently as the "
            f"last day the words could have been spoken.", False, te,
            {"method": AGREEMENT_METHOD, "rule": AGREEMENT_RULE, "run": run_rel, "lead": None,
             "proposals": proposals, "source_checks": []}, basis_note="; two daters agree"))
    if len(found) == 1:
        return found[0]["queue"]
    by = {a["harness"]: a["queue"]["reason"] for a in found}
    reason = next(iter(set(by.values()))) if len(set(by.values())) == 1 else "no_confirmation"
    return {**_queue(reason, "; ".join(f"{a['harness']}: {a['queue']['reason']}: {a['queue']['detail'][:300]}"
                                       for a in found),
                     [{**c, "proposal": a["harness"]} for a in found for c in a["queue"]["checks"]]),
            "by_dater": by}


def _confirmed(entry: dict) -> dict:
    """A CHECK confirms the own date and supersedes no record (review item 14); an earlier date is an OVERRIDE."""
    return {"outcome": entry["confirmation"]["kind"], "entry": entry}


def merge_one(rec: dict, doc: dict, checks: list[dict], proposal_ref: dict | None = None,
              run_rel: str | None = None) -> dict:
    """One proposal and its source checks: merge() over a single dater."""
    h = doc.get("harness") or "agent"
    return merge(rec, [doc], {h: checks}, {h: proposal_ref} if proposal_ref else {}, run_rel)


def _find_run_dir(run_rel: str, override_path: Path) -> Path:
    for anc in Path(override_path).resolve().parents:
        cand = anc / run_rel
        if cand.is_dir():
            return cand
    raise L.PredictionError(f"statement_date_override: dating run {run_rel!r} is not under any parent of "
                            f"{override_path}")


def verify_agent_entry(tid: str, entry: dict, trec: dict, override_path, kind: str = "override") -> None:
    """Re-verify an agent entry from what it stored, or raise. Called by the override loader.

    Every proposal file the merge read must match its sha256 and be the named
    dater's, and re-running this module's merge (the version the entry names) over
    those proposals and the stored windows must give exactly the stored entry. The
    page itself is not re-fetched: its sha256 and a window around the excerpt are
    what was kept (critique 3 C3). A description check is re-derived from the
    transcript's own stored description.
    """
    c = entry.get("confirmation")
    if not isinstance(c, dict):
        raise L.PredictionError(f"statement_date_override: {tid}: confirmation is not an object")
    if c.get("method") not in METHODS or c.get("merge_version") not in MERGE_VERSIONS:
        raise L.PredictionError(f"statement_date_override: {tid}: confirmation method {c.get('method')!r} / "
                                f"merge_version {c.get('merge_version')!r} is not one this code can re-run "
                                f"({list(METHODS)}, {list(MERGE_VERSIONS)})")
    props = c.get("proposals")
    if not isinstance(c.get("run"), str) or not isinstance(props, list) or not props or \
            not all(isinstance(p, dict) and p.get("harness") and p.get("path") and p.get("sha256") for p in props):
        raise L.PredictionError(f"statement_date_override: {tid}: confirmation names no run or proposal files")
    run_dir = _find_run_dir(c["run"], override_path)
    docs, refs = [], {}
    for p in props:
        path = run_dir / p["path"]
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise L.PredictionError(f"statement_date_override: {tid}: proposal {path} is missing") from exc
        if hashlib.sha256(raw).hexdigest() != p["sha256"]:
            raise L.PredictionError(f"statement_date_override: {tid}: proposal {path} does not match its recorded "
                                    f"sha256")
        doc = json.loads(raw)
        if not isinstance(doc.get("daters"), list) or not doc["daters"]:
            raise L.PredictionError(f"statement_date_override: {tid}: proposal {path} names no daters, so the "
                                    f"re-merge cannot tell whether a dater's proposal is missing")
        if (doc.get("harness") or "agent") != p["harness"]:
            raise L.PredictionError(f"statement_date_override: {tid}: proposal {path} was made by harness "
                                    f"{doc.get('harness')!r}, but the entry lists it as {p['harness']!r}")
        docs.append(doc)
        refs[p["harness"]] = {"path": p["path"], "sha256": p["sha256"]}
    stored = c.get("source_checks") or []
    checks_by = {p["harness"]: [ck for ck in stored if ck.get("route", "page") == "page"
                                and ck.get("proposal") == p["harness"]] for p in props}
    try:
        out = merge(trec, docs, checks_by, refs, run_rel=c["run"])
    except ValueError as exc:
        raise L.PredictionError(f"statement_date_override: {tid}: {exc}") from exc
    if out["outcome"] == "queue":
        raise L.PredictionError(f"statement_date_override: {tid}: the stored evidence no longer confirms the entry "
                                f"on re-merge ({out['reason']}: {out['detail'][:300]})")
    if out["outcome"] != kind:
        raise L.PredictionError(f"statement_date_override: {tid}: the re-merge gives a {out['outcome']}, but the entry "
                                f"sits in the {kind}s file")
    have = {k: v for k, v in entry.items() if k != "confirmed_at_utc"}
    if out["entry"] != have:
        diff = sorted(k for k in set(have) | set(out["entry"]) if have.get(k) != out["entry"].get(k))
        raise L.PredictionError(f"statement_date_override: {tid}: the entry differs from its re-merge in {diff}")


def utc_stamp() -> str:
    """A provenance stamp only. Never logical time: the dates come from the pages."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
