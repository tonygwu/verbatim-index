#!/usr/bin/env python3
"""Pure functions for the dating stage: when were the words in a recording spoken?

Rescue round 4 (design section 1, critiques 1 and 3), operator decision VD-8 (c)
of 2026-09-29, "see what happens", with two daters since VD-11 (2026-10-01): each
dater (DATERS, Gemini then Fable) identifies the event and its date range and
cites sources with verbatim excerpts. A script with no model then fetches each
cited page and must find the excerpt on it, with a date inside that dater's own
range. The recording's own page never counts, with one exception: its stored
DESCRIPTION, when it states the event's date (the dater's description_evidence, or
Tier 0, the description's one full day), strictly before the upload and never next
to a cue word such as "born", "released" or "use code". merge() combines the
daters (rule R1, two_agent_agreement, dater_disagreement; see merge). A confirmed
result is an entry that vouches for itself on every load; anything else is queued
for a person with its reason. A single-dater merge is the one-agent rule of VD-8
(c) and its entries load like any other; production uses both daters.

merge-4 (2026-10-04, the operator's audit of seven recordings whose dates were all
findable) is MERGE_VERSION; merge-3 stays re-runnable, and an entry re-merges under
the version it names. See MERGE_VERSION for the findings (a)-(f) and the bounds.

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
  - the description check and Tier 0, with the cue-word filter
  - the merge of every dater's proposal (MERGE_VERSION), and the loader's
    re-verification of an entry from its stored proposals, windows and the
    transcript's own description
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
# merge-4 (2026-10-04, the operator's audit of seven recordings whose dates were findable):
#   (a) a page that embeds the recording may confirm a date that is not the upload date and is
#       before it (an organiser's archive that dates the session);
#   (b) a relative date in the description ("last November") resolves against the upload date;
#   (c) a date-only excerpt needs the speaker AND the host, the interviewer or the event named
#       near it on the page;
#   (e) an excerpt whose date the page writes another way ("12 February 2020") still matches;
#   (f) a day confirmed inside another dater's wider confirmed range refines it; it is not a
#       disagreement;
#       and a proposal's own floors and ceilings ("bounds") must hold its range.
#   From the live run of the same day: a UTC publication stamp may show the LAST day of a
#   range of days (a ceiling); transcript words the agent did not copy exactly are dropped
#   rather than discarding a page-confirmed proposal, and "A ... B" is read as fragments.
# merge-3 stays re-runnable: production holds entries that name it, and the loader re-merges each
# entry with the version it names (verify_agent_entry). A new run writes MERGE_VERSION.
MERGE_VERSION = "merge-4"
MERGE_VERSIONS = ("merge-3", "merge-4")
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
# merge-4: an excerpt of a date ALONE and shorter than MIN_EXCERPT_WORDS ("March 2, 2021") counts only when
# the page names the speaker AND another identifier of the occasion (host, interviewer, event, channel)
# within this many characters of the date. A news front page prints many dates near many names; a window of 1,000 would
# let one article's date borrow another headline's speaker.
NEAR_CHARS = 400

AGREEMENT_RULE = ("statement_date is the last day that every dater named independently, exactly that day; "
                  "each proposal passed every rule before the source checks, so none ends after the upper "
                  "bound; no cited page or description confirmed it")
ZONE_RULE = ("a speech, session or interview is dated in the local time of the place where it happened; "
             "a publication (verdict publication_only) is dated in UTC")
RULE_V3 = ("statement_date is the latest day of the agent's range; the range is confirmed only when a fetched "
           "page that is not the recording's own carries the cited excerpt and a date inside the range, or the "
           "recording's stored description states a date inside the range (cited, or its one full day: Tier 0); "
           "a confirming source must show the latest day")
RULE_V4 = ("statement_date is the latest day of the agent's range; the range is confirmed only when a fetched "
           "page that is not the recording's own carries the cited excerpt (its date may be written another way) "
           "and a date inside the range, or the recording's stored description states a date inside the range "
           "(cited, a relative date read against the upload date, or its one full day: Tier 0); a page that embeds "
           "the recording counts only for a date before the upload; a date-only excerpt counts only beside the "
           "speaker and the host, interviewer or event; a confirming source must show the latest day; a day "
           "confirmed inside another dater's wider confirmed range refines it; a UTC publication stamp may "
           "show the last day of a range of days; transcript words not in the transcript are dropped, and that "
           "proposal takes no part in an agreement or in rule R1")
RULES = {"merge-3": RULE_V3, "merge-4": RULE_V4}
RULE = RULES[MERGE_VERSION]


def merge_rank(version: str) -> int:
    """3 for "merge-3": the rules a version runs, by number. An unknown version raises; nothing is guessed."""
    if version not in MERGE_VERSIONS:
        raise ValueError(f"merge version {version!r} is not one this code can run ({list(MERGE_VERSIONS)})")
    return int(version.split("-", 1)[1])

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


# ---------------------------------------------------------------------------
# merge-4: an excerpt whose date the page writes another way (finding e)
# ---------------------------------------------------------------------------
#
# FOUND 2026-10-04 (operator's audit, tim-sweeney/academy-of-interactive-a-h7tgad): Gemini
# cited PC Gamer as "By Andy Chalk published February 12, 2020"; the page prints "By Andy
# Chalk Published 12 February 2020". The words and the day were all there, and the exact
# match refused it. Here every date with a year, on the page and in the excerpt alike, is
# replaced by one word naming its days before the match, so the two forms meet and two
# different days never do.

_DATE_WORD = re.compile(r"^zdate\d{16}z$")
# Words that may stand beside a date in an excerpt without identifying anything: a byline
# verb, a time and its zone. An excerpt of only these and dates is DATE-ONLY.
_FILLER = {"published", "posted", "updated", "modified", "last", "on", "by", "at", "date", "dated", "am", "pm",
           "a", "m", "p"} | {z.lower() for z in _ZONES}


def _canonical(text: str) -> tuple[str, list[int]]:
    """text with each date replaced by the word zdate<lo><hi>z, and a map from its characters to text's.

    The word's first character maps to the date's first character and its last to the
    date's last, so a match that ends on the word ends where the date ends.
    """
    out: list[str] = []
    cmap: list[int] = []
    pos = 0
    for d in _dates_located(text):
        if d["at"] < pos:
            continue
        out.append(text[pos:d["at"]])
        cmap.extend(range(pos, d["at"]))
        word = f" zdate{d['lo']:%Y%m%d}{d['hi']:%Y%m%d}z "
        out.append(word)
        cmap.extend([d["at"]] * (len(word) - 2) + [d["end"] - 1, d["end"] - 1])
        pos = d["end"]
    out.append(text[pos:])
    cmap.extend(range(pos, len(text)))
    return "".join(out), cmap


def _canonical_words(text: str) -> list[str]:
    return L.normalise(_canonical(text)[0]).split()


def excerpt_is_date_only(excerpt: str) -> bool:
    """True when the excerpt names a date with its year and nothing else but filler ("PST · February 2, 2021")."""
    words = _canonical_words(excerpt)
    dates = [w for w in words if _DATE_WORD.match(w)]
    rest = [w for w in words if not _DATE_WORD.match(w) and w not in _FILLER and not w.isdigit()]
    return bool(dates) and not rest


def _find_all_canonical(hay: str, needle: str) -> list[tuple[int, int]]:
    """Original offsets of every match of the needle in hay after both have their dates made canonical.

    Only a needle that carries a date is matched this way: with no date the exact match
    (_find) is the whole test, and canonical matching would add nothing but cost.
    """
    cneedle = L.normalise(_canonical(needle)[0])
    if not cneedle or not any(_DATE_WORD.match(w) for w in cneedle.split()):
        return []
    chay, cmap = _canonical(hay)
    nh, nmap = L.normalise_with_map(chay)
    out = []
    for k in L._find_all(nh, cneedle):
        s, e = cmap[nmap[k]], cmap[nmap[k + len(cneedle) - 1]] + 1
        out.append((s, e))
    return out


def find_excerpt(hay: str, needle: str, version: str = MERGE_VERSION) -> tuple[int, int] | None:
    """The excerpt's first match: exactly (every version), else with its dates made canonical (merge-4)."""
    hit = _find(hay, needle)
    if hit is not None or merge_rank(version) < 4:
        return hit
    hits = _find_all_canonical(hay, needle)
    return hits[0] if hits else None


def _decode(body: bytes, content_type: str | None) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    try:
        return body.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def check_source(src: dict, rec: dict, fetched: dict, prop: dict | None = None) -> dict:
    """What the script found on one cited page. Stores a small window, never the page.

    `fetched` is {status, final_url, body (bytes), via (direct|wayback), error,
    content_type (optional)}. The window keeps WINDOW_CHARS each side of the match
    so a later load can re-check the excerpt and its date without the page.

    The match is exact first, on the page's text and then its markup, exactly as
    merge-3 checked; only when neither holds is the excerpt matched with its dates
    made canonical (merge-4, finding e), so a check that merge-3 could read is the
    same check today. For a date-only excerpt the occurrence kept is the first whose
    surroundings name the speaker and another identifier of `prop`'s occasion, else
    the first; the window around it is what every later load reads.
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
    hays = (("text", html_to_text(raw)), ("markup", htmlmod.unescape(raw)))
    for where, hay in hays:
        hit = _find(hay, src["verbatim_excerpt"])
        if hit:
            s, e = hit
            out.update(excerpt_found=True, found_in=where, page_span=hay[s:e],
                       window=hay[max(0, s - WINDOW_CHARS):e + WINDOW_CHARS])
            return out
    cands = [(where, hay, h) for where, hay in hays for h in _find_all_canonical(hay, src["verbatim_excerpt"])]
    if not cands:
        return out
    if prop is not None and len(L.normalise(src["verbatim_excerpt"]).split()) < MIN_EXCERPT_WORDS \
            and excerpt_is_date_only(src["verbatim_excerpt"]):
        cands = [c for c in cands if _near_context_ok(c[1], c[2], rec, prop)[0]] or cands
    where, hay, (s, e) = cands[0]
    out.update(excerpt_found=True, found_in=where, page_span=hay[s:e],
               window=hay[max(0, s - WINDOW_CHARS):e + WINDOW_CHARS])
    return out


def refused_check(src: dict, reason: str) -> dict:
    """A cited page that is refused before any fetch, recorded with the reason."""
    return {"url": src["url"], "publisher": src.get("publisher"), "cited_excerpt": src["verbatim_excerpt"],
            "refused": reason, "fetched": False, "fetched_via": None, "http_status": None, "final_url": None,
            "fetch_error": None, "page_sha256": None, "excerpt_found": False, "found_in": None, "window": None,
            "page_span": None, "page_title": None, "page_names_video_id": False}


def confirms(check: dict, prop: dict, rec: dict, version: str = MERGE_VERSION) -> tuple[bool, str]:
    """Does this stored check confirm this proposal under `version`'s rules? Re-derived from the stored window."""
    return confirming_spans(check, prop, rec, version)[:2]


def confirming_spans(check: dict, prop: dict, rec: dict,
                     version: str = MERGE_VERSION) -> tuple[bool, str, list[tuple[date, date]]]:
    """(confirms, why, the days inside the range this check shows), the days being what the latest-day rule reads.

    merge-3 reads the days of the excerpt's first exact match, as it always did; merge-4
    those of every occurrence that passes its rules, less an embedding page's upload days.
    """
    if merge_rank(version) >= 4:
        return _confirms_v4(check, prop, rec)
    ok, why = _confirms_v3(check, prop, rec)
    if not ok:
        return ok, why, []
    s, t = _find(check["window"], check["cited_excerpt"])
    return ok, why, _spans_in_range(check["window"][s:t], prop)


def _confirms_v3(check: dict, prop: dict, rec: dict) -> tuple[bool, str]:
    """merge-3, unchanged: the rules every merge-3 entry in production was confirmed under."""
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
    tokens = context_tokens(rec, prop, "merge-3")
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


_UPLOAD_FIELD = re.compile(r"upload_?date[\"'\s:=]*([^\"'<>,}\]]{6,40})", re.I)


def _own_day(rec: dict) -> date | None:
    own, _ = L.own_statement_date(rec)
    return date.fromisoformat(own) if own else None


def _confirms_v4(check: dict, prop: dict, rec: dict) -> tuple[bool, str, list[tuple[date, date]]]:
    """merge-4 (2026-10-04): merge-3's rules with findings a, c and e of the operator's audit.

    (a) A page that embeds the recording, names its video id beside the excerpt or
        carries an uploadDate there may confirm, but only a day STRICTLY BEFORE the
        recording's own date that is no uploadDate the window names. Khosla Ventures'
        CEO Summit archive dates the 2012 session and embeds the 2014 upload; Citi's
        Legends Live page dates 8 June 2026 and embeds the September upload. A page
        showing only the upload day is refused, as under merge-3.
    (e) The excerpt may match with its dates made canonical ("12 February 2020" for
        "February 12, 2020"), and an excerpt of a date alone may be shorter than
        MIN_EXCERPT_WORDS. Every occurrence in the window is tried.
    (c) An excerpt SHORTER than MIN_EXCERPT_WORDS counts only when it is a date alone
        and the page names the speaker AND another identifier of the occasion (the
        event, the host, the interviewer or the channel) within NEAR_CHARS of the
        date. Any other excerpt needs what merge-3 needed: at least MIN_EXCERPT_WORDS
        words, and the speaker or a word of the event, host or interviewer in the
        window or the page title.
    """
    if check.get("refused"):
        return False, f"refused: {check['refused']}", []
    for u in (check["url"], check.get("final_url")):
        why = own_page_reason(u, rec) if u else None
        if why:
            return False, f"refused: {u} {why}", []
    if not check.get("fetched") or not check.get("page_sha256"):
        return False, f"the page could not be read: {check.get('fetch_error')}", []
    excerpt = check["cited_excerpt"]
    # Only an excerpt SHORTER than MIN_EXCERPT_WORDS gets the date-alone allowance and its
    # stricter context test; a longer one is judged exactly as merge-3 judged it.
    short = len(L.normalise(excerpt).split()) < MIN_EXCERPT_WORDS
    date_only = short and excerpt_is_date_only(excerpt)
    if short and not date_only:
        return False, f"the excerpt has fewer than {MIN_EXCERPT_WORDS} words and is not a date alone", []
    window = check.get("window") or ""
    exact = _find(window, excerpt)
    hits = [exact] if exact else _find_all_canonical(window, excerpt)
    if not hits:
        return False, "the excerpt is not on the page", []
    vid = rec.get("video_id")
    embeds = [why for why, hit in (
        ("the page embeds the recording's own video", check.get("page_names_video_id")),
        ("the window names the recording's own video id", bool(vid and vid in window)),
        ("the window carries a video uploadDate", bool(re.search(r"upload_?date", window, re.I)))) if hit]
    upload_days = {d["lo"] for m in _UPLOAD_FIELD.finditer(window) for d in dates_in_text(m.group(1))}
    own = _own_day(rec)
    e = date.fromisoformat(prop["speech_date_earliest"])
    lat = date.fromisoformat(prop["speech_date_latest"])
    first_why, spans = None, []
    for s, t in hits:
        ok, why, got = _hit_confirms(window, (s, t), check, prop, rec, e, lat, date_only, embeds, upload_days, own)
        if ok:
            spans += got
        first_why = first_why or why
    return (True, "confirms", spans) if spans else (False, first_why, [])


def _hit_confirms(window: str, hit: tuple[int, int], check: dict, prop: dict, rec: dict, e: date, lat: date,
                  date_only: bool, embeds: list[str], upload_days: set,
                  own: date | None) -> tuple[bool, str | None, list[tuple[date, date]]]:
    """One occurrence of the excerpt in the window, judged by _confirms_v4's rules: (ok, why not, its days)."""
    span = window[hit[0]:hit[1]]
    found = dates_in_text(span)
    if not found:
        return False, f"the excerpt carries no date with a year: {span[:80]!r}", []
    usable = []
    for d in found:
        r = date_for_verdict(d, prop["verdict"])
        # A UTC timestamp cannot give a speech's local day, but it can CEIL a range: a page
        # published at that instant was written after the words. So for a "dated" range of
        # more than one day it may show the LAST day, read in UTC, as a publication is
        # (FOUND 2026-10-04: Gemini dated dara-khosrowshahi/greylock-fhxo7v as February 2 to
        # March 2, 2021, with Greylock's datePublished 2021-03-02T18:02:42+00:00 as the ceiling).
        if r is None and d.get("utc_stamp") and prop["verdict"] == "dated" and e < lat \
                and d["utc_lo"] == d["utc_hi"] == lat:
            r = (d["utc_lo"], d["utc_hi"])
        if r is not None:
            usable.append(r)
    if not usable:
        return False, (f"the excerpt's only dates are UTC timestamps, which cannot give the venue's day for a "
                       f"speech: {[d['text'] for d in found]} ({ZONE_RULE})"), []
    inside = [r for r in usable if e <= r[0] and r[1] <= lat]
    if not inside:
        shown = [f"{a.isoformat()}..{b.isoformat()}" for a, b in usable]
        return False, f"the excerpt's dates {shown} are outside the range {e}..{lat} ({ZONE_RULE})", []
    if embeds:
        if own is None:
            return False, (f"{embeds[0]}, and the recording has no upload date to tell the page's dates from it; "
                           f"its dates may be the upload's"), []
        inside = [r for r in inside if r[1] < own and not any(r[0] <= u <= r[1] for u in upload_days)]
        if not inside:
            return False, (f"{embeds[0]}, and the excerpt's date is not before the recording's own date {own} or is "
                           f"an uploadDate the window names ({sorted(u.isoformat() for u in upload_days)}); "
                           f"its dates are the upload's"), []
    if date_only:
        ok, detail = _near_context_ok(window, hit, rec, prop)
        if not ok:
            return False, (f"the excerpt is a date alone with fewer than {MIN_EXCERPT_WORDS} words, and within "
                           f"{NEAR_CHARS} characters of it the page does not name the speaker together with the "
                           f"host, the interviewer or the event: {detail}"), []
        return True, None, inside
    tokens = context_tokens(rec, prop, "merge-4")
    hay = f" {L.normalise(window + ' ' + (check.get('page_title') or ''))} "
    if not any(f" {tok} " in hay for tok in tokens):
        return False, (f"the window and the page title name neither the speaker nor the event "
                       f"(looked for {sorted(tokens)}); it may be a page about another occasion"), []
    return True, None, inside


# Words that name no occasion even beside a speaker: titles, roles and the common words of
# event names. merge-4's identifiers leave them out; merge-3's context test is unchanged.
_GENERIC_V4 = {"ceo", "cto", "cfo", "founder", "cofounder", "chairman", "chair", "president", "inc", "corp", "company",
               "new", "series", "speaker", "speakers", "guest", "guests", "host", "hosted", "hosts", "featuring",
               "edition", "official", "channel", "media", "news", "partner", "partners", "general", "how", "why",
               "what", "who", "when", "where", "you", "your", "our", "all", "one", "two", "first", "best", "big",
               "great", "get", "gets", "build", "building", "future", "world", "life", "lessons", "story", "stories",
               "mission", "platform", "anything", "anywhere", "everything", "today", "this", "that", "into", "out",
               "over", "after", "before", "inside", "behind", "join", "joins", "joined", "sat", "down", "talks",
               "speaks", "discusses", "shares", "special", "award", "awards", "presentation", "stage", "onstage",
               "followed", "full", "highlights", "video", "audio", "transcript", "notes", "show"}


def identifiers(rec: dict, prop: dict) -> tuple[set[str], set[str]]:
    """(speaker, others): the speaker's surname, and the words that name THIS occasion (merge-4, finding c).

    Others come from the proposal's event, host_organization and interviewer and from
    the recording's channel, less the speaker's own names, stop words, generic words,
    numbers and words under three letters. A channel that re-uploads other people's
    videos adds words that will simply not be on the page.
    """
    parts = [L.normalise(x) for x in (rec.get("leader_slug") or "").split("-") if x]
    speaker = {parts[-1]} if parts else set()
    words: list[str] = []
    for text in (prop.get("event"), prop.get("host_organization"), prop.get("interviewer"),
                 rec.get("yt_channel") or rec.get("declared_venue")):
        words += L.normalise(text if isinstance(text, str) else "").split()
    others = {w for w in words if len(w) >= 3 and not w.isdigit() and w not in _EVENT_STOP and w not in _GENERIC_V4
              and w not in parts}
    return {x for x in speaker if x}, others


def _near_context_ok(hay: str, hit: tuple[int, int], rec: dict, prop: dict) -> tuple[bool, str]:
    """Does the text within NEAR_CHARS of hay[hit] name the speaker AND another identifier of the occasion?"""
    near = f" {L.normalise(hay[max(0, hit[0] - NEAR_CHARS):hit[1] + NEAR_CHARS])} "
    speaker, others = identifiers(rec, prop)
    says = sorted(t for t in speaker if f" {t} " in near)
    also = sorted(t for t in others if f" {t} " in near)
    return bool(says and also), f"speaker {sorted(speaker)} named: {says or 'no'}; others {sorted(others)[:12]} named: {also or 'none'}"


# Words in an event name that do not identify an occasion: a page about ANY interview
# carries "interview". A pure number is not an identifier either (a year matches pages
# about every event that year).
_EVENT_STOP = {"the", "and", "with", "for", "from", "about", "session", "interview", "conference", "keynote",
               "talk", "podcast", "episode", "full", "video", "live", "annual", "event", "day", "part", "speech",
               "lecture", "fireside", "chat", "panel", "remarks", "meeting", "call", "earnings", "show", "his",
               "her", "their", "its", "our", "upload", "recording", "discussion", "conversation", "appearance"}


def context_tokens(rec: dict, prop: dict, version: str) -> set[str]:
    """What a page about THIS occasion names: the speaker's surname, or a word of the event (review item 12).

    merge-4 also takes the words of the proposal's host_organization and interviewer.
    """
    toks: set[str] = set()
    parts = [x for x in (rec.get("leader_slug") or "").split("-") if x]
    if parts:
        toks.add(L.normalise(parts[-1]))
    texts = [prop.get("event")] + ([prop.get("host_organization"), prop.get("interviewer")]
                                   if merge_rank(version) >= 4 else [])
    for text in texts:
        for w in L.normalise(text if isinstance(text, str) else "").split():
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


# merge-4, finding b: a relative date in the description, read against the upload date.
# FOUND 2026-10-04 (bill-gates/village-global-w5g4sp): "We asked Bill to join us in San
# Francisco for a fireside chat ... last November", uploaded 2019-06-21. Two daters answered
# cannot_date because the words carry no year, and the third cited them and was refused for
# the same reason. Against the upload date they say November 2018. Only "last" and "this
# past" are read, never a bare month ("in November" could be the next one), and only
# against an upload or publication date, never the day a transcript was fetched.
_SEASONS = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 2)}
_REL = re.compile(r"\b(?:last|this\s+past)\s+(?:(?P<mon>" + _MON[1:-1] + r")|(?P<season>spring|summer|fall|autumn|"
                  r"winter)|(?P<unit>year|month))\b|\b(?P<ytd>earlier\s+this\s+year)\b", re.I)
RELATIVE_BASES = ("youtube_upload_date", "publication_date")
# "last November" said within this many days after a November ended may mean that one or
# the one a year before; the reading then spans both rather than choosing.
AMBIGUOUS_DAYS = 31


def _month_last(y: int, m: int) -> date:
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def relative_range(m: re.Match, ref: date) -> tuple[date, date] | None:
    """The days a relative phrase names, read against `ref` (the upload date), or None when it names none."""
    if m.group("ytd"):
        return (date(ref.year, 1, 1), ref - timedelta(days=1)) if ref > date(ref.year, 1, 1) else None
    if m.group("unit"):
        if m.group("unit").lower() == "year":
            return date(ref.year - 1, 1, 1), date(ref.year - 1, 12, 31)
        prev = date(ref.year, ref.month, 1) - timedelta(days=1)
        return date(prev.year, prev.month, 1), prev
    if m.group("mon"):
        mon = _MONTHS[m.group("mon")[:3].lower()]
        y = ref.year if _month_last(ref.year, mon) < ref else ref.year - 1
        lo, hi = date(y, mon, 1), _month_last(y, mon)
        return (date(y - 1, mon, 1) if (ref - hi).days <= AMBIGUOUS_DAYS else lo), hi
    a, b = _SEASONS[m.group("season").lower()]
    end_year = ref.year if _month_last(ref.year, b) < ref else ref.year - 1
    first_year = end_year - (a > b)
    lo, hi = date(first_year, a, 1), _month_last(end_year, b)
    return (date(first_year - 1, a, 1) if (ref - hi).days <= AMBIGUOUS_DAYS else lo), hi


def _relative_dates(text: str, rec: dict, taken: list[dict]) -> tuple[list[dict], str | None]:
    """Relative dates in text as _dates_located gives dates, each marked relative; (dates, why none could be read)."""
    own, basis = L.own_statement_date(rec)
    out, why = [], None
    for m in _REL.finditer(text):
        if any(m.start() < d["end"] and d["at"] < m.end() for d in taken):
            continue
        if own is None or basis not in RELATIVE_BASES:
            why = (f"{m.group(0)!r} is a relative date, and the recording has no upload or publication date to read "
                   f"it against (its own date basis is {basis!r})")
            continue
        r = relative_range(m, date.fromisoformat(own))
        if r is None:
            continue
        out.append({"at": m.start(), "end": m.end(), "lo": r[0], "hi": r[1], "text": m.group(0), "utc_lo": r[0],
                    "utc_hi": r[1], "utc_stamp": False, "relative": True})
    return out, why


def check_description(rec: dict, prop: dict, version: str = MERGE_VERSION) -> dict | None:
    """The agent's description_evidence checked as a page excerpt is checked, or None when it gave none.

    A normalised match on word boundaries, at least MIN_EXCERPT_WORDS words, a
    date with its year inside the agent's range, STRICTLY before the transcript's
    own date (review fix 2), and not next to a cue word or inside a link (fixes 6
    and 7). The context and embed rules of a page do not apply: the description is
    this recording's own text by construction. "spans" keeps the days that passed,
    which are the only ones the latest-day rule may read. merge-4 also reads a
    relative date ("last November") against the upload date (finding b), and records
    each reading in "read_as".
    """
    ev = prop.get("description_evidence")
    if not ev:
        return None
    v4 = merge_rank(version) >= 4
    desc = recording_description(rec) or ""
    out = {"route": "description", "basis": "cited", "cited_excerpt": ev,
           "description_sha256": _sha(desc) if desc else None, "span": None, "spans": [], "ok": False, "why": None}
    if v4:
        out["read_as"] = []

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
    if v4:
        rel, rel_why = _relative_dates(span, rec, found)
        found = sorted(found + rel, key=lambda d: d["at"])
        out["read_as"] = [{"text": d["text"], "range": [d["lo"].isoformat(), d["hi"].isoformat()],
                           "against": L.own_statement_date(rec)[0]} for d in rel]
        if not found:
            return no(f"the cited description words carry no date with a year and no relative date that can be read "
                      f"against the upload: {rel_why or repr(span[:80])}")
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
        # merge-4 (2026-10-04). OPTIONAL in the schema, so every proposal stored before them
        # still validates and every merge-3 entry still re-merges; the prompt asks for them.
        "host_organization": {"type": ["string", "null"]},
        "interviewer": {"type": ["string", "null"]},
        "bounds": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "date", "evidence"],
            "properties": {"kind": {"enum": ["floor", "ceiling"]}, "date": {"type": "string"},
                           "evidence": {"type": "string", "minLength": 1},
                           "source_url": {"type": ["string", "null"]}}}},
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
   call, a podcast episode, a televised interview, a lecture, a letter. Name three
   parties when the recording shows them: the HOST ORGANIZATION (the fund, company,
   conference, school or show that put it on), the INTERVIEWER or moderator, and
   the GUEST, who is the speaker below. Put the first two in "host_organization"
   and "interviewer" (null when there is none). A channel that re-uploads other
   people's videos is not the host.

2. FIND WHEN THE EVENT HAPPENED. Search for the event itself, not for the video:
   search for the host organization, the interviewer and the guest TOGETHER
   ("Greylock Reid Hoffman Dara Khosrowshahi"). A third-party page that names that
   combination, or the guest with the named event, and gives a date describes
   this occasion: the same host, interviewer and guest do not meet on stage twice
   in the same weeks. It counts even when it does not link to the video; when it
   names the date, use it rather than answer cannot_date. Good sources: the
   organiser's schedule, archive or press release, a dated news report or live
   blog, the podcast's episode page or feed, an investor relations page, a copy
   on web.archive.org. How you read a source depends on YOUR TOOLS below; either
   way the script opens every page you cite and checks your excerpt against it.

   THE RECORDING'S OWN PAGE NEVER COUNTS AS A SOURCE. A YouTube page of any kind,
   the page named under URL below, another page of the same show on a transcript
   site, and a web.archive.org copy of any of them date an upload, not the event.
   The script refuses them without opening them. Cite the event's own record
   instead. An organiser's page that EMBEDS the video does count when it dates the
   session itself with a day before the upload; the upload date shown beside an
   embedded video never counts.

   THE DESCRIPTION IS THE ONE EXCEPTION. If the Description below states when the
   event itself happened ("Recorded August 2023", "Bill Gates, Mehtap Ozkan,
   Saturday, February 25, 2023"), that date counts as evidence. Copy those words
   exactly into "description_evidence", at least four words with the date; the
   script checks them against the stored description. A RELATIVE date there
   ("last November", "earlier this year") counts too: the script reads it against
   the upload date, so "last November" uploaded in June 2019 is November 2018. The
   upload date, a "premiered" or "streamed live" date that YouTube shows, and a
   date the description gives for anything other than this event never count. A
   RELEASE date ("Originally released March 9, 2020 on podcast services") is a
   ceiling, never the day the words were spoken.

3. TEST THE DATE AGAINST THE TRANSCRIPT. Look for remarks that date the talk:
   "this afternoon", "welcome to the second developer conference", "we
   announced last week", a price, a product, a figure, a named event. If the
   transcript contradicts a date, that date is wrong.

4. SET THE BOUNDS. Most evidence gives a bound, not the date:
   - a PAST event the talk mentions ("our recent acquisition of Drizly") is a
     FLOOR: the words came on or after it, maybe months or years later, so never
     place the date "around" it;
   - an UPCOMING event ("we're doing one on December 16th") is a CEILING: the
     last possible day is the day before it;
   - a publication, release, upload or posting date, of the recording or of a
     page about the talk, is a CEILING; text on that page can narrow it ("In
     February, Greylock kicked off ..." on a page published March 2);
   - a source that names the day of the session gives both.
   List each in "bounds": kind "floor" or "ceiling", the date as YYYY-MM-DD (a
   floor is the first possible day, a ceiling the last), the evidence in a few
   words, and its URL or null. Your range runs from the latest floor to the
   earliest ceiling; the script refuses a range that breaks your own bounds.

5. ONLY THEN USE THE UPPER BOUND. The date labelled UPPER BOUND below is when the
   recording was uploaded or published. The words cannot have been spoken after
   it. It is often days, and sometimes years, later than the speech, because
   channels re-upload old talks. Report it as the latest possible day only when
   steps 1 to 4 find no earlier ceiling, and say what shows that.

TIME ZONE. Date a speech, a session or an interview in the local time of the
place where it happened: a keynote that ended at 9:30 pm in San Francisco on
May 30 is May 30, although it was May 31 in UTC. Date a publication (verdict
"publication_only") in UTC.

ANSWER WITH A RANGE, NOT A GUESS. Give the first and the last day on which the
words could have been spoken, given your evidence, as YYYY-MM-DD. When a source
names the day, give the same day twice. When you know only that it was at a
three-day conference, give the three days. The last day is the statement date
every deadline is computed from, so it must be shown by a source you cite or by
the description. Never give a last day later than the upper bound.

EXCERPTS. For every source, copy into "verbatim_excerpt" at least four
consecutive words exactly as they appear on that page, including a date written
with its year ("May 30, 2012", "30 May 2012", "2012-05-30" or "May 2012") that
falls inside your range, written as the page writes it. The script ignores case
and punctuation and reads a date written another way as the same day. A date
alone ("March 2, 2021") counts only when the page names the guest with the host,
the interviewer or the event beside it. An excerpt the script cannot find, or
whose date is outside your range, confirms nothing.

VERDICT
  "dated"            you identified the event and a source, or the description,
                     dates it. A third-party page that names the guest with the
                     host, the interviewer or the event and gives a date is such
                     a source.
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
says whether the channel re-uploaded someone else's recording. Always give
"host_organization", "interviewer" and "bounds" (an empty list when you have none).

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
    # A dating-only Fable harness with web search and page fetch and nothing else
    # (coordinator, 2026-10-04: every dating model should have web search). Never the
    # judge's harness: grade.call_fable denies every tool, and the prior and lead-test
    # stages stay outcome-blind by design.
    "fable_web": """YOUR TOOLS. You can search the web (WebSearch) and open pages (WebFetch), and
nothing else: no files, no shell. Search for the event, open each page you cite,
and copy the excerpt from the page itself, not from a search-result summary.
BUDGET: at most 20 searches and 20 page opens in all. Stop as soon as an opened
page names the date, and answer; if the budget runs out, answer with what you
have, or cannot_date. A run that never answers is worth nothing.""",
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


def validate_proposal(obj: dict, tid: str, version: str = MERGE_VERSION) -> list[str]:
    """Schema, then the rules a proposal must meet before any source is checked.

    merge-4 adds one: the range must sit inside the proposal's own bounds, from its
    latest floor to its earliest ceiling (the operator's learning of 2026-10-04: a past
    event is a floor and not the date, an upcoming event or a publication a ceiling).
    """
    errs = L.check_schema(obj, DATING_SCHEMA)
    if errs:
        return errs
    v4 = merge_rank(version) >= 4
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
    if v4 and not errs:
        errs += bound_errors(obj)
    return errs


def bound_errors(obj: dict) -> list[str]:
    """Why a dated proposal's range breaks its own bounds (merge-4), or [] when it keeps them or names none.

    A floor is the first day the words could have been spoken (on or after a past event),
    a ceiling the last (the day before an upcoming event, or a publication day). The
    range must start on or after every floor and end on or before every ceiling.
    """
    errs = []
    for i, b in enumerate(obj.get("bounds") or []):
        d = b["date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or _mk(*map(int, d.split("-"))) is None:
            errs.append(f"bounds[{i}].date {d!r} is not a real YYYY-MM-DD date")
        elif b["kind"] == "floor" and obj["speech_date_earliest"] < d:
            errs.append(f"the range starts {obj['speech_date_earliest']}, before its own floor {d} "
                        f"({b['evidence'][:80]!r})")
        elif b["kind"] == "ceiling" and obj["speech_date_latest"] > d:
            errs.append(f"the range ends {obj['speech_date_latest']}, after its own ceiling {d} "
                        f"({b['evidence'][:80]!r})")
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

_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")


def transcript_evidence_found(rec: dict, te: str, version: str = MERGE_VERSION) -> bool:
    """Are the agent's transcript words in the transcript? merge-3: as one quote. merge-4 also: as fragments.

    merge-4 reads words an agent joined with an ellipsis ("A ... B ... C") as separate
    quotes, each of at least three words, and finds every one (FOUND 2026-10-04: Fable with
    web tools joined three exact passages of bill-gates/khosla-ventures-8bosqk with "...").
    """
    text = rec.get("text") or ""

    def found(q: str) -> bool:
        r = L.locate_quote(text, q)
        return not ("error" in r and r["error"] in ("not_found", "empty_quote"))
    if found(te):
        return True
    if merge_rank(version) < 4:
        return False
    parts = [p for p in _ELLIPSIS.split(te) if len(L.normalise(p).split()) >= 3]
    return len(parts) > 1 and all(found(p) for p in parts)


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


def assess(rec: dict, doc: dict, checks: list[dict], version: str = MERGE_VERSION) -> dict:
    """One proposal under `version`'s rules for ONE proposal, before any other dater's proposal is read.

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
    errs = validate_proposal(prop, tid, version)
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
    if te and not transcript_evidence_found(rec, te, version):
        if merge_rank(version) < 4:
            return queued("transcript_evidence_not_found", f"{te[:200]!r} is not in the transcript")
        # merge-4: the words are dropped and never cited. The proposal may still be confirmed by
        # its own page or description, but it is not eligible: it takes no part in an
        # agreement, and it contradicts nothing under rule R1. FOUND in the live run of
        # 2026-10-04: Gemini dated michael-dell/citi-z30abb to Citi's own page and misspelled one
        # name in its transcript quote, and merge-3 discarded the right date for it.
        out["te_dropped"] = te
    else:
        out["eligible"] = True
    # A check counts only for a url AND excerpt the proposal itself cited (review item 10), so
    # neither a stray check nor one swapped in later can confirm, at merge or at load.
    # Description checks are DERIVED here from the transcript, never taken as input: a
    # stored one (route "description") is what an entry recorded, and is re-derived.
    pages = [c for c in checks if c.get("route", "page") == "page"]
    cited = {(s["url"], L.normalise(s["verbatim_excerpt"])) for s in prop["sources"]}
    verdicts = [(c, False, "the proposal did not cite this url and excerpt", [])
                if (c["url"], L.normalise(c["cited_excerpt"])) not in cited
                else (c, *confirming_spans(c, prop, rec, version)) for c in pages]
    good = [c for c, ok, _, _ in verdicts if ok]
    page_spans = [r for _, ok, _, rs in verdicts if ok for r in rs]
    reasons = [f"{c['url']}: {why}" for c, _, why, _ in verdicts]
    desc = check_description(rec, prop, version)
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
        if out.get("te_dropped"):
            # Nothing confirmed, so the queue says what merge-3 said first, then every check's reason.
            return queued("transcript_evidence_not_found", f"{te[:200]!r} is not in the transcript; "
                          + ("; ".join(reasons) or "no source was checked"),
                          [dict(c) for c in pages] + ([desc] if desc else []))
        return queued("no_confirming_source", "; ".join(reasons) or "no source was checked",
                      [dict(c) for c in pages] + ([desc] if desc else []))
    # The statement date is the LAST day of the range, so a source must show that day
    # (review item 2): "September 7-9, 2025", "May 2012" or the publication day itself.
    # A page check's days come from confirming_spans: under merge-3 the first exact match's,
    # under merge-4 every occurrence that passed, less an embedding page's upload days.
    spans = list(page_spans)
    for c in good:
        if c.get("route") == "description":
            # Only the days the description check accepted, never every date in its span (review
            # fixes 2, 6, 7): a cued or upload-day date beside a good one must not source the last day.
            spans += ([(date.fromisoformat(c["day"]),) * 2] if c["basis"] == "tier0" else
                      [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in c["spans"]])
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


def _shared_input(rec: dict, docs: list[dict], lat: str) -> str | None:
    """Why two daters naming `lat` are not independent, or None (review fix 3).

    Both prompts print the same UPPER BOUND, the same leads and the same page
    dates; two agents copying one of them agree by construction, not by finding
    the event. A full day in a lead or a page date counts; a month or a year does
    not, since it names no day. A proposal file that does not record the leads it
    was shown cannot be checked, so it cannot agree.
    """
    ub = upper_bound(rec)
    if ub is not None and lat == ub[0]:
        return f"both daters named {lat}, the upper bound ({ub[1]}) their prompts printed; that is not independent"
    if any("leads" not in d for d in docs):
        return (f"a proposal file does not record the leads its prompt showed ({[d.get('harness') for d in docs if 'leads' not in d]}), "
                f"so the agreement on {lat} cannot be checked against them")
    texts = [x for d in docs for x in (d["leads"] or [])]
    if rec.get("page_dates"):
        texts.append(json.dumps(rec["page_dates"]))
    days = {x["lo"].isoformat() for t in texts for x in dates_in_text(t) if x["lo"] == x["hi"]}
    if lat in days:
        return (f"both daters named {lat}, a day that appears in the leads or the page dates both prompts showed; "
                f"that is not independent")
    return None


def _strong_year_conflict(rec: dict, e: str, lat: str) -> dict | None:
    years = strong_years(rec)
    if years and not (years & set(range(int(e[:4]), int(lat[:4]) + 1))):
        return _queue("strong_year_conflict", f"the title or source id names {sorted(years)}; the confirmed range "
                                              f"{e}..{lat} does not include it")
    return None


def _entry(rec: dict, prop: dict, verdict: str, e: str, lat: str, evidence: dict, confirmed_by: str,
           evidenced: bool, te: str | None, confirmation: dict, basis_note: str = "",
           version: str = MERGE_VERSION) -> dict:
    """The override or check entry. `evidence` is {source_url, verbatim_evidence} for a confirmed source, or
    {agents_named} for two agents that agreed with no source (review fix 1). It names the merge version
    whose rules made it, which is the version the loader re-runs."""
    own_date, _ = L.own_statement_date(rec)
    kind = "check" if own_date is not None and lat == own_date else "override"
    return {
        "statement_date": lat,
        "basis": f"{prop['event'].strip()} ({prop['event_kind']}"
                 + ("; publication date" if verdict == "publication_only" else "") + basis_note + ")",
        **evidence,
        "confirmed_by": confirmed_by,
        "earliest_evidenced": evidenced,
        **({"statement_date_earliest": e, "precision": L.date_precision(e, lat)} if e != lat else {}),
        **({"internal_evidence": f"Transcript: {te}"} if te else {}),
        "confirmation": {"merge_version": version, "kind": kind, "verdict": verdict, "range": [e, lat],
                         "zone_rule": ZONE_RULE, **confirmation},
    }


def _agents_named(found: list[dict]) -> list[dict]:
    """What each agreeing agent named, copied from its proposal and labelled unconfirmed: its words, not a source."""
    return [{"agent": a["harness"], "unconfirmed": True, "event": a["prop"]["event"],
             "event_kind": a["prop"]["event_kind"], "verdict": a["prop"]["verdict"],
             "range": [a["prop"]["speech_date_earliest"], a["prop"]["speech_date_latest"]],
             "cited": [{"url": s["url"], "verbatim_excerpt": s["verbatim_excerpt"]} for s in a["prop"]["sources"]],
             **({"description_evidence": a["prop"]["description_evidence"]}
                if a["prop"].get("description_evidence") else {})} for a in found]


def merge(rec: dict, docs: list[dict], checks_by: dict[str, list[dict]], refs: dict | None = None,
          run_rel: str | None = None, version: str = MERGE_VERSION) -> dict:
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

    `version` names the rules: the loader passes the version an entry names, so a
    merge-3 entry re-merges under merge-3 exactly. merge-4 changes step 2 (finding f
    of the operator's audit, 2026-10-04): when every confirmed range NESTS inside the
    others, the narrowest is a refinement, not a disagreement, and it leads. Case
    tim-sweeney/bafta-guru-cjxc-u: Gemini's photo agency page dated the award on
    June 12, 2019, and Fable's Wikipedia line said "June 2019"; merge-3 queued the two
    as disagreeing. Ranges that overlap without nesting, or do not meet, still queue.
    Rule R1 is unchanged and still applies to every eligible dater that confirmed
    nothing: so when Fable's page confirms the awards night (February 13) and Gemini
    named the keynote day (February 12) without a confirming page, the recording is
    still queued (tim-sweeney/academy-of-interactive-a-h7tgad).
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
    merge_rank(version)   # an unknown version raises before any proposal is read
    rule = RULES[version]
    found = [assess(rec, d, checks_by.get(h) or [], version) for d, h in zip(docs, hs)]
    proposals = [_proposal_record(d, refs.get(h)) for d, h in zip(docs, hs)]
    confirmed = [a for a in found if a["confirmed"]]
    refined: list[dict] = []
    if merge_rank(version) >= 4 and len(confirmed) > 1:
        nested = _nested_lead(confirmed)
        if nested is not None:
            # The narrowest leads; the others are recorded as what it refined.
            refined = [{"dater": a["harness"], "range": [a["prop"]["speech_date_earliest"],
                                                         a["prop"]["speech_date_latest"]]}
                       for a in confirmed if a is not nested
                       and a["prop"]["speech_date_latest"] != nested["prop"]["speech_date_latest"]]
            confirmed = [nested] + [a for a in confirmed if a is not nested]
    if not refined and len({a["prop"]["speech_date_latest"] for a in confirmed}) > 1:
        return {**_queue("dater_disagreement", "; ".join(
            f"{a['harness']} confirmed {a['prop']['speech_date_latest']} by "
            f"{', '.join(c.get('route') or 'page' for c in a['good'])}" for a in confirmed),
            [_check_record(c, a["harness"]) for a in confirmed for c in a["good"]]),
            "by_dater": {a["harness"]: ("confirmed" if a["confirmed"] else a["queue"]["reason"]) for a in found}}
    if confirmed:
        lead = confirmed[0]
        prop = lead["prop"]
        e, lat = prop["speech_date_earliest"], prop["speech_date_latest"]
        # Rule R1 (coordinator's decision, 2026-10-01, reversible): every other dater whose
        # proposal passed the rules before the checks must not contradict the confirmed day,
        # meaning its own range contains it. Measured on the pilot: it removes the one wrong
        # confirmation (A9, a publication day) and loses one right one (evan-spiegel).
        against = [a for a in found if a is not lead and a["eligible"]
                   and not (a["prop"]["speech_date_earliest"] <= lat <= a["prop"]["speech_date_latest"])]
        if against:
            return {**_queue("dater_disagreement", f"{lead['harness']} confirmed {lat}; " + "; ".join(
                f"{a['harness']} named {a['prop']['speech_date_earliest']}..{a['prop']['speech_date_latest']}, "
                f"which does not contain it (rule R1)" for a in against),
                [_check_record(c, a["harness"]) for a in confirmed for c in a["good"]]),
                "by_dater": {a["harness"]: ("confirmed" if a["confirmed"] else a["queue"]["reason"]) for a in found}}
        conflict = _strong_year_conflict(rec, e, lat)
        if conflict:
            return conflict
        first = lead["good"][0]
        desc = first.get("route") == "description"
        return _confirmed(_entry(
            rec, prop, prop["verdict"], e, lat,
            # A description lives on the recording's own page, so that page is its address.
            {"source_url": rec["url"] if desc else first["url"],
             "verbatim_evidence": first["span"] if desc else first["page_span"]}, L.AGENT_CONFIRMATION,
            any(a == date.fromisoformat(e) for a, _ in lead["spans"]),
            None if lead.get("te_dropped") else prop.get("transcript_evidence"),
            {"method": METHOD, "rule": rule, "run": run_rel, "lead": lead["harness"], "proposals": proposals,
             "source_checks": [_check_record(c, a["harness"]) for a in confirmed for c in a["good"]],
             **({"refines": refined} if refined else {})}, version=version))
    lats = {a["prop"].get("speech_date_latest") for a in found}
    if len(found) >= 2 and all(a["eligible"] for a in found) and len(lats) == 1:
        lat = lats.pop()
        shared = _shared_input(rec, docs, lat)
        if shared:
            return _queue("agreement_on_shared_input", shared)
        e = min(a["prop"]["speech_date_earliest"] for a in found)
        conflict = _strong_year_conflict(rec, e, lat)
        if conflict:
            return conflict
        verdict = "dated" if all(a["prop"]["verdict"] == "dated" for a in found) else "publication_only"
        te = next((a["prop"]["transcript_evidence"] for a in found if a["prop"].get("transcript_evidence")), None)
        # No source confirmed this day, so the entry names none (review fix 1): it records what
        # the agents named, labelled as their words, and says so wherever the date is shown.
        return _confirmed(_entry(
            rec, found[0]["prop"], verdict, e, lat, {"agents_named": _agents_named(found)},
            L.AGREEMENT_CONFIRMATION, False, te,
            {"method": AGREEMENT_METHOD, "rule": AGREEMENT_RULE, "run": run_rel, "lead": None,
             "proposals": proposals, "source_checks": []}, basis_note="; two daters agree", version=version))
    if len(found) == 1:
        return found[0]["queue"]
    by = {a["harness"]: a["queue"]["reason"] for a in found}
    reason = next(iter(set(by.values()))) if len(set(by.values())) == 1 else "no_confirmation"
    return {**_queue(reason, "; ".join(f"{a['harness']}: {a['queue']['reason']}: {a['queue']['detail'][:300]}"
                                       for a in found),
                     [{**c, "proposal": a["harness"]} for a in found for c in a["queue"]["checks"]]),
            "by_dater": by}


def _nested_lead(confirmed: list[dict]) -> dict | None:
    """The narrowest confirmed proposal when every other confirmed range contains it, else None (merge-4, f).

    Ties go to the first in the merge's order (DATERS), as merge-3's lead did.
    """
    def rng(a):
        return a["prop"]["speech_date_earliest"], a["prop"]["speech_date_latest"]
    narrow = min(confirmed, key=lambda a: (date.fromisoformat(rng(a)[1]) - date.fromisoformat(rng(a)[0])).days)
    lo, hi = rng(narrow)
    if all(rng(a)[0] <= lo and hi <= rng(a)[1] for a in confirmed):
        return narrow
    return None


def _confirmed(entry: dict) -> dict:
    """A CHECK confirms the own date and supersedes no record (review item 14); an earlier date is an OVERRIDE."""
    return {"outcome": entry["confirmation"]["kind"], "entry": entry}


def merge_one(rec: dict, doc: dict, checks: list[dict], proposal_ref: dict | None = None,
              run_rel: str | None = None, version: str = MERGE_VERSION) -> dict:
    """One proposal and its source checks: merge() over a single dater."""
    h = doc.get("harness") or "agent"
    return merge(rec, [doc], {h: checks}, {h: proposal_ref} if proposal_ref else {}, run_rel, version)


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
        # The rules of the version the entry names, never today's: a merge-3 entry re-merges as merge-3.
        out = merge(trec, docs, checks_by, refs, run_rel=c["run"], version=c["merge_version"])
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
