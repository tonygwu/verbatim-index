#!/usr/bin/env python3
"""Transcript text helpers shared by every annotation session.

A transcript is the `text` of a record: whitespace tokens, with `[hh:mm:ss]` marks
the fetcher writes about once a minute and `>>` caption turn marks. Every offset in
an annotation is an index into those tokens. This module finds a judge's quote in
the text, places a quote in time for its play link, and cuts reading excerpts.

It is the ONLY annotation module that turns a mark's hours and minutes into
seconds (`scripts/test_play_time.py` checks the builders do not), so a quote card
and a passage cannot be timed two different ways.
"""
from __future__ import annotations

import re

EXCERPT_AT = (0.12, 0.50, 0.85)
EXCERPT_WORDS = 130
MARK = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]")
# Seconds of lead before a quote's estimated start. MEASURED 2026-09-28 on one
# video (sergey-brin/badbellabear-9uzqfz, 3,187 words, true caption times fetched
# once): interpolation lands a median 1.4 s from the true time, and with a 5 s lead
# playback starts after the word for 19 of 3,187 words, against 192 with 3 s.
PLAY_LEAD_SECONDS = 5
# A gap between two marks whose words arrive at less than this share of the
# recording's typical rate has lost words, as a paragraph-loop collapse does.
SPARSE_GAP_SHARE = 0.5


def play_time(toks: list, a: int, duration=None, lead: int = PLAY_LEAD_SECONDS):
    """Whole seconds at which to start playing the word at token index `a`, or None.

    `toks` are the `re.finditer(r"\\S+", text)` matches of a transcript. The fetcher
    writes a `[hh:mm:ss]` mark about once a minute, each right before the caption
    whose start it records, so a mark is exact to the second and the words between
    two marks fill the time between them. The word's time is interpolated between
    the marks around it by spoken-word position. Marks and `>>` turn marks are not
    words. The result is `lead` seconds earlier, so playback starts just before the
    quote.

    Three cases do not interpolate. Each leans toward starting early rather than
    late, because a late start makes the listener scrub back past the opening
    words they must attribute. None of them is guaranteed to land before the quote:

      - A SPARSE gap, whose words arrive at under SPARSE_GAP_SHARE of the typical
        rate, has lost words (a paragraph-loop collapse drops a replay and keeps
        only the later mark). Where the survivors sat inside it is unknown, so the
        word is placed at the typical rate from the earlier mark. That lands in the
        first half of the gap, since a sparse gap's words take under half its time
        at the typical rate.
      - Before the first mark, or after the last, the word is extrapolated from the
        nearest mark at the typical rate, and clamped to [0, duration].
      - With no rate at all (one mark and no duration) the nearest earlier mark, or
        0, is used; with no mark and no duration the answer is None.

    The typical rate is the median words per second over the recording's gaps, not
    word count over `duration`, which counts intros and outros with no speech.
    With fewer than two marks it falls back to words over `duration`.
    """
    if not 0 <= a < len(toks):
        raise IndexError(f"token {a} is outside a transcript of {len(toks)} tokens")
    marks, words, pos = [], 0, None
    for i, t in enumerate(toks):
        if i == a:
            pos = words
        m = MARK.fullmatch(t.group())
        if m:
            h, mi, s = (int(x) for x in m.groups())
            marks.append((words, h * 3600 + mi * 60 + s))
        elif t.group() != ">>":
            words += 1
    rates = sorted((c1 - c0) / (s1 - s0) for (c0, s0), (c1, s1) in zip(marks, marks[1:])
                   if c1 > c0 and s1 > s0)
    if rates:
        typical = rates[len(rates) // 2]
    elif duration and words:
        typical = words / duration
    else:
        typical = None
    before = [k for k, (c, _) in enumerate(marks) if c <= pos]
    if before:
        k = before[-1]
        c0, s0 = marks[k]
        if k + 1 < len(marks):
            c1, s1 = marks[k + 1]
            if typical and (c1 - c0) / max(s1 - s0, 1e-9) < SPARSE_GAP_SHARE * typical:
                t = s0 + (pos - c0) / typical
            else:
                t = s0 + (pos - c0) / (c1 - c0) * (s1 - s0)
        else:
            t = s0 + (pos - c0) / typical if typical else s0
    elif marks:
        c1, s1 = marks[0]
        t = s1 - (c1 - pos) / typical if typical else 0
    elif typical:
        t = pos / typical
    else:
        return None
    if duration:
        t = min(t, duration)
    return max(0, int(t) - lead)


def name_forms(person: dict) -> list[str]:
    parts = person["name"].split()
    forms = [person["name"], parts[0], parts[-1]] + list(person.get("handles") or [])
    return [f for f in dict.fromkeys(forms) if len(f) >= 3]


def excerpts(text: str) -> list[dict]:
    """Three windows of the transcript, each with the time of the nearest earlier mark."""
    words = list(re.finditer(r"\S+", text))
    out = []
    for frac in EXCERPT_AT:
        if not words:
            break
        i = min(int(len(words) * frac), max(0, len(words) - EXCERPT_WORDS))
        span = words[i:i + EXCERPT_WORDS]
        start = span[0].start()
        marks = [m for m in MARK.finditer(text, 0, start)]
        secs = None
        if marks:
            h, m, s = (int(x) for x in marks[-1].groups())
            secs = h * 3600 + m * 60 + s
        chunk = text[start:span[-1].end()]
        out.append({"at": frac, "t": secs, "text": MARK.sub("", chunk).strip(),
                    "start": i, "end": i + len(span)})
    return out

CONTEXT_WORDS = 35
# A blinding token in a quote taken from blinded text, and the most raw words it
# can stand for. [AFFILIATION] is the pundits token for a show or outlet, which
# runs longer than a name ("The Matt Walsh Show").
WILDCARD_SPAN = {"[subject]": 3, "[company]": 3, "[affiliation]": 5}
WILDCARD = set(WILDCARD_SPAN)


def _norm(tok: str) -> str:
    t = tok.lower()
    if t in WILDCARD or t == ">>":
        return t
    # One apostrophe, and none at the edges: a judge quoting a quotation writes
    # 'Oh, no.' where the captions have "Oh, no.", and either side may be curly.
    t = re.sub(r"[^\w']", "", t.replace("\u2019", "'").replace("\u2018", "'"))
    return t.strip("'")


def locate(quote: str, raw: str):
    """Find a judge's quote in the raw transcript; returns (first, last) raw token indices or None.

    Matching is on normalized words. `[SUBJECT]` and `[COMPANY]` in a quote taken from
    blinded text stand for the one to three raw words of the name they replaced, at any
    position, and `[AFFILIATION]` for one to five words of a show or outlet. An elided quote ("...") is matched on its longest piece. Caption turn marks
    `>>` and timestamp marks are skipped. A quote shorter than four words is not located,
    because a match that short says nothing about where it came from.
    """
    toks = list(re.finditer(r"\S+", raw))
    words = [(i, _norm(m.group())) for i, m in enumerate(toks)
             if not MARK.fullmatch(m.group())]
    words = [(i, w) for i, w in words if w and w != ">>"]
    piece = max(re.split(r"\.\.\.|…", quote), key=lambda x: len(x.split()))
    q = [w for w in (_norm(t) for t in piece.split()) if w and w != ">>"]
    if len(q) < 4 or all(w in WILDCARD for w in q):
        return None

    def match(qi: int, wi: int):
        if qi == len(q):
            return wi
        if q[qi] in WILDCARD:
            for n in range(1, WILDCARD_SPAN[q[qi]] + 1):
                if wi + n <= len(words):
                    end = match(qi + 1, wi + n)
                    if end is not None:
                        return end
            return None
        if wi < len(words) and words[wi][1] == q[qi]:
            return match(qi + 1, wi + 1)
        return None

    lead = next(k for k, w in enumerate(q) if w not in WILDCARD)
    anchor = q[lead]
    for s0, (_, w0) in enumerate(words):
        if w0 != anchor:
            continue
        for back in range(lead, max(WILDCARD_SPAN.values()) * lead + 1):
            st = s0 - back
            if st < 0:
                break
            end = match(0, st)
            if end is not None:
                return words[st][0], words[end - 1][0]
    return None


def mark_times(tokens: list[str]) -> list[list[int]]:
    """`[token index, seconds]` for every `[hh:mm:ss]` mark token, in order."""
    out = []
    for i, token in enumerate(tokens):
        mark = MARK.fullmatch(token)
        if mark:
            h, m, s = map(int, mark.groups())
            out.append([i, h * 3600 + m * 60 + s])
    return out
