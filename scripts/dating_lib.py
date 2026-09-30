#!/usr/bin/env python3
"""Pure functions for the dating stage: when were the words in a recording spoken?

Rescue round 4 (design section 1, critiques 1 and 3), operator decision VD-8 (c)
of 2026-09-29, "see what happens": ONE agent identifies the event and its date
range and cites sources with verbatim excerpts. A script with no model then
fetches each cited page and must find the excerpt on it, with a date inside the
agent's own range. The recording's own page never counts. A confirmed result is
an override entry that vouches for itself on every load; anything else is queued
for a person with its reason.

WHY. No stage ever tried to find out when a recording was made. Code copied the
YouTube upload date, or nothing, into the date the card prints as "Said", and a
2012 D10 interview re-uploaded in 2019 had "next year" resolved to 2020. The
models noticed, in notes that nothing reads.

What lives here, and nothing else (no network, no model, no argparse):
  - the prompt (DATING_TASK), its input block and the proposal schema
  - dates in text, and the time zone rule: a speech keeps the date where it
    happened, a publication is read in UTC
  - the own-page rule: the recording's own video page, any YouTube page, the
    transcript's own url and a Wayback copy of any of them never confirm
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
MERGE_VERSION = "merge-1"
MERGE_VERSIONS = (MERGE_VERSION,)
METHOD = "one_agent_plus_source_check"

VERDICTS = ("dated", "publication_only", "cannot_date")
EVENT_KINDS = ("conference_session", "keynote", "earnings_call", "podcast_episode", "interview", "lecture",
               "letter", "other")
OPENING_WORDS = 800          # design 1.4 input block
CLOSING_WORDS = 300
PASSAGE_CONTEXT_WORDS = 30
MAX_PASSAGES = 40            # the cap is reported in the prompt and the run log when it bites
MAX_LEADS = 12
MIN_EXCERPT_WORDS = 4        # a bare "May 30, 2012" would match any page that prints the day
WINDOW_CHARS = 600           # kept each side of the excerpt; the page itself is only hashed

ZONE_RULE = ("a speech, session or interview is dated in the local time of the place where it happened; "
             "a publication (verdict publication_only) is dated in UTC")
RULE = ("statement_date is the latest day of the agent's range; the range is confirmed only when a fetched "
        "page that is not the recording's own carries the cited excerpt and a date inside the range")

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


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d) if 1900 <= y <= 2100 else None
    except ValueError:
        return None


def dates_in_text(text: str) -> list[dict]:
    """Every date WITH A YEAR in the text, in order: {lo, hi, text, utc_lo, utc_hi}.

    A day gives lo == hi; "September 7-9, 2025" a range; "August 2023" the whole
    month. A time with a zone ("4:26 pm PT", "T01:30:00+02:00") also gives the UTC
    date, which only a publication is read in. A bare year, or a day with no year,
    is not a date here: "Sep 13" could be any year.
    """
    out: list[dict] = []
    taken: list[tuple[int, int]] = []

    def free(m) -> bool:
        return not any(m.start() < b and a < m.end() for a, b in taken)

    def add(m, lo, hi, utc=None):
        if lo is None or hi is None or hi < lo:
            return
        taken.append((m.start(), m.end()))
        out.append({"at": m.start(), "lo": lo, "hi": hi, "text": m.group(0).strip(),
                    "utc_lo": utc or lo, "utc_hi": utc or hi})

    for m in _ISO.finditer(text):
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        utc = _utc_date(d, int(m.group(4)), int(m.group(5)), m.group(6)) if d and m.group(4) and m.group(6) else None
        add(m, d, d, utc)
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
        add(m, lo, hi, utc)
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
    return [{k: v for k, v in d.items() if k != "at"} for d in out]


def date_for_verdict(d: dict, verdict: str) -> tuple[date, date]:
    """The zone rule: a speech keeps its written, local date; a publication is read in UTC."""
    return (d["utc_lo"], d["utc_hi"]) if verdict == "publication_only" else (d["lo"], d["hi"])


# ---------------------------------------------------------------------------
# The recording's own page never counts
# ---------------------------------------------------------------------------

YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
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
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    segs = [s for s in p.path.split("/") if s]
    q = "&".join(sorted(x for x in p.query.split("&") if x))
    return host, segs, q


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
    own = rec.get("url")
    if own:
        ohost, osegs, oq = _split(own)
        if (host, segs, q) == (ohost, osegs, oq):
            return "is the transcript's own page"
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
           "excerpt_found": False, "found_in": None, "window": None, "page_span": None}
    body = fetched.get("body") or b""
    if fetched.get("error") or fetched.get("status") != 200 or not body:
        out["fetch_error"] = fetched.get("error") or f"HTTP {fetched.get('status')} with {len(body)} bytes"
        return out
    out["fetched"] = True
    out["page_sha256"] = hashlib.sha256(body).hexdigest()
    raw = _decode(body, fetched.get("content_type"))
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
            "page_span": None}


def confirms(check: dict, prop: dict, rec: dict) -> tuple[bool, str]:
    """Does this stored check confirm this proposal? Re-derived from the stored window every time."""
    if check.get("refused"):
        return False, f"refused before fetch: {check['refused']}"
    why = own_page_reason(check["url"], rec)
    if why:
        return False, f"refused: {why}"
    if not check.get("fetched") or not check.get("page_sha256"):
        return False, f"the page could not be read: {check.get('fetch_error')}"
    if len(L.normalise(check["cited_excerpt"]).split()) < MIN_EXCERPT_WORDS:
        return False, f"the excerpt has fewer than {MIN_EXCERPT_WORDS} words"
    hit = _find(check.get("window") or "", check["cited_excerpt"])
    if hit is None:
        return False, "the excerpt is not on the page"
    span = check["window"][hit[0]:hit[1]]
    found = dates_in_text(span)
    if not found:
        return False, f"the excerpt carries no date with a year: {span[:80]!r}"
    e = date.fromisoformat(prop["speech_date_earliest"])
    lat = date.fromisoformat(prop["speech_date_latest"])
    inside = [d for d in found if e <= date_for_verdict(d, prop["verdict"])[0]
              and date_for_verdict(d, prop["verdict"])[1] <= lat]
    if not inside:
        shown = [f"{a.isoformat()}..{b.isoformat()}" for a, b in (date_for_verdict(d, prop["verdict"]) for d in found)]
        return False, f"the excerpt's dates {shown} are outside the range {e}..{lat} ({ZONE_RULE})"
    return True, "confirms"


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

DATING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["transcript_id", "verdict", "event", "event_kind", "speech_date_earliest", "speech_date_latest",
                 "sources", "transcript_evidence", "reupload", "reasoning"],
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
   at the time by the organiser or by a reporter who was there. Open the page.
   Do not rely on a search-result summary: in this project, summaries gave the
   wrong day in 3 of 10 checks.

   THE RECORDING'S OWN PAGE NEVER COUNTS. A YouTube page of any kind, the page
   named under URL below, another page of the same show on a transcript site, and
   a web.archive.org copy of any of them date an upload, not the event. The script
   refuses them without opening them. Cite the event's own record instead.

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
  "dated"            you identified the event and a source dates it.
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
talk, or null. "reupload" says whether the channel re-uploaded someone else's
recording.

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


def build_dating_prompt(rec: dict, leads: list[str]) -> tuple[str, dict]:
    """(prompt, meta). Only the opening, the closing and the dated passages are sent.

    A long prompt raises the odds that the Gemini harness reaches for a tool, has
    it auto-denied and returns an empty answer (AGENTS.md), and the date is in
    those three places when it is anywhere. meta reports what the caps cut.
    """
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    own_date, own_basis = L.own_statement_date(rec)
    labels = {"youtube_upload_date": "YouTube upload date", "publication_date": "publication date",
              "stated_in_page": "stated in the source"}
    upper = (f"UPPER BOUND: {own_date} ({labels.get(own_basis, own_basis)})" if own_date
             else "UPPER BOUND: none (the source carries no date)")
    words = (rec.get("text") or "").split()
    opening = words[:OPENING_WORDS]
    closing = words[max(OPENING_WORDS, len(words) - CLOSING_WORDS):]
    passages, cut = _passages(words, OPENING_WORDS, max(OPENING_WORDS, len(words) - CLOSING_WORDS))
    page_dates = rec.get("page_dates") or []
    lead_block = ("LEADS FROM EARLIER STAGES: none" if not leads else
                  "LEADS FROM EARLIER STAGES (unverified; use them to search, never cite them)\n"
                  + "\n".join(f"- {x}" for x in leads))
    cut_note = f", {cut} more cut by the cap of {MAX_PASSAGES}" if cut else ""
    prompt = f"""{DATING_TASK}

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
{rec.get('yt_description') or '(none)'}

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
    if not obj["sources"]:
        errs.append(f"verdict {obj['verdict']} cites no source")
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
                            r"failed|succeeded|achieved|resolv\w*|outcome|turned out|in fact|actually)\b", re.I)


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
            if not s:
                continue
            if _CLAIM_OUTCOME.search(s):
                dropped["claim_or_outcome_words"] += 1
                continue
            years = {int(y) for y in _LEAD_YEAR.findall(s)} | {d["lo"].year for d in dates_in_text(s)}
            if not years:
                dropped["no_date"] += 1
                continue
            said = ((rec or {}).get("source") or {}).get("statement_date")
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


def _queue(reason: str, detail: str, checks: list | None = None) -> dict:
    return {"outcome": "queue", "reason": reason, "detail": detail, "checks": checks or []}


def merge_one(rec: dict, doc: dict, checks: list[dict], proposal_ref: dict | None = None,
              run_rel: str | None = None) -> dict:
    """One proposal and its source checks -> {"outcome": "override", "entry"} or {"outcome": "queue", reason}.

    Deterministic, and the same function the loader re-runs. The order of the
    rules is the order of the reasons a person reads in the queue:
      invalid_proposal, cannot_date, after_upper_bound (design 1.5 rule 5: the
      Singju "Sep 13" for a Sep 12 upload), transcript_evidence_not_found,
      no_confirming_source (with every check's reason), strong_year_conflict
      (a title or source-id year the range misses: "CES 2006" on a 2013 upload,
      and also "What Aaron Levie Saw in 2004", which a person reads).
    The entry has no confirmed_at_utc; the caller stamps it.
    """
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    prop = doc["proposal"]
    errs = validate_proposal(prop, tid)
    if errs:
        return _queue("invalid_proposal", "; ".join(errs[:5]))
    if prop["verdict"] == "cannot_date":
        return _queue("cannot_date", prop["reasoning"][:400])
    e, lat = prop["speech_date_earliest"], prop["speech_date_latest"]
    own_date, own_basis = L.own_statement_date(rec)
    if own_date is not None and lat > own_date:
        return _queue("after_upper_bound", f"the range ends {lat}, after the {own_basis} {own_date}; the words "
                                           f"cannot have been spoken after the recording was published")
    te = prop.get("transcript_evidence")
    if te and "error" in L.locate_quote(rec.get("text") or "", te) and \
            L.locate_quote(rec.get("text") or "", te)["error"] in ("not_found", "empty_quote"):
        return _queue("transcript_evidence_not_found", f"{te[:200]!r} is not in the transcript")
    verdicts = [(c, *confirms(c, prop, rec)) for c in checks]
    good = [c for c, ok, _ in verdicts if ok]
    if not good:
        return _queue("no_confirming_source", "; ".join(f"{c['url']}: {why}" for c, _, why in verdicts)
                      or "no source was checked", [dict(c) for c in checks])
    years = strong_years(rec)
    span_years = set(range(int(e[:4]), int(lat[:4]) + 1))
    if years and not (years & span_years):
        return _queue("strong_year_conflict", f"the title or source id names {sorted(years)}; the confirmed range "
                                              f"{e}..{lat} does not include it")
    first_days = []
    for c in good:
        s, t = _find(c["window"], c["cited_excerpt"])
        first_days += [date_for_verdict(d, prop["verdict"])[0] for d in dates_in_text(c["window"][s:t])]
    evidenced = date.fromisoformat(e) in first_days
    lead = good[0]
    entry = {
        "statement_date": lat,
        "basis": f"{prop['event'].strip()} ({prop['event_kind']}"
                 + ("; publication date" if prop["verdict"] == "publication_only" else "") + ")",
        "source_url": lead["url"],
        "verbatim_evidence": lead["page_span"],
        "confirmed_by": L.AGENT_CONFIRMATION,
        "earliest_evidenced": evidenced,
        **({"statement_date_earliest": e, "precision": L.date_precision(e, lat)} if e != lat else {}),
        **({"internal_evidence": f"Transcript: {te}"} if te else {}),
        "confirmation": {
            "method": METHOD, "merge_version": MERGE_VERSION, "run": run_rel, "proposal": proposal_ref,
            "verdict": prop["verdict"], "range": [e, lat], "rule": RULE, "zone_rule": ZONE_RULE,
            "harness": doc.get("harness"), "requested_model": doc.get("requested_model"),
            "served_model": doc.get("served_model"), "served_model_verified": doc.get("served_model_verified"),
            "identity": doc.get("identity"),
            "source_checks": [{k: c[k] for k in ("url", "publisher", "cited_excerpt", "fetched_via", "http_status",
                                                 "final_url", "page_sha256", "found_in", "window", "page_span",
                                                 "refused", "fetched", "fetch_error", "excerpt_found")}
                              for c in good],
        },
    }
    return {"outcome": "override", "entry": entry}


def _find_run_dir(run_rel: str, override_path: Path) -> Path:
    for anc in Path(override_path).resolve().parents:
        cand = anc / run_rel
        if cand.is_dir():
            return cand
    raise L.PredictionError(f"statement_date_override: dating run {run_rel!r} is not under any parent of "
                            f"{override_path}")


def verify_agent_entry(tid: str, entry: dict, trec: dict, override_path) -> None:
    """Re-verify an agent entry from what it stored, or raise. Called by the override loader.

    The proposal file must match its sha256, and re-running this module's merge
    (the version the entry names) over the proposal and the stored windows must
    give exactly the stored entry. The page itself is not re-fetched: its sha256
    and a window around the excerpt are what was kept (critique 3 C3).
    """
    c = entry.get("confirmation")
    if not isinstance(c, dict):
        raise L.PredictionError(f"statement_date_override: {tid}: confirmation is not an object")
    if c.get("method") != METHOD or c.get("merge_version") not in MERGE_VERSIONS:
        raise L.PredictionError(f"statement_date_override: {tid}: confirmation method {c.get('method')!r} / "
                                f"merge_version {c.get('merge_version')!r} is not one this code can re-run "
                                f"({METHOD}, {list(MERGE_VERSIONS)})")
    prop = c.get("proposal") or {}
    if not isinstance(c.get("run"), str) or not prop.get("path") or not prop.get("sha256"):
        raise L.PredictionError(f"statement_date_override: {tid}: confirmation names no run or proposal file")
    path = _find_run_dir(c["run"], override_path) / prop["path"]
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise L.PredictionError(f"statement_date_override: {tid}: proposal {path} is missing") from exc
    if hashlib.sha256(raw).hexdigest() != prop["sha256"]:
        raise L.PredictionError(f"statement_date_override: {tid}: proposal {path} does not match its recorded sha256")
    out = merge_one(trec, json.loads(raw), c.get("source_checks") or [], proposal_ref=prop, run_rel=c["run"])
    if out["outcome"] != "override":
        raise L.PredictionError(f"statement_date_override: {tid}: the stored evidence no longer confirms the entry "
                                f"on re-merge ({out['reason']}: {out['detail'][:300]})")
    have = {k: v for k, v in entry.items() if k != "confirmed_at_utc"}
    if out["entry"] != have:
        diff = sorted(k for k in set(have) | set(out["entry"]) if have.get(k) != out["entry"].get(k))
        raise L.PredictionError(f"statement_date_override: {tid}: the entry differs from its re-merge in {diff}")


def utc_stamp() -> str:
    """A provenance stamp only. Never logical time: the dates come from the pages."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
