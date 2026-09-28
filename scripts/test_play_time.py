#!/usr/bin/env python3
"""A quote card's "play from" link starts just before the quote, not at the minute mark.

Both speaker-check pages link each quote to YouTube at `t` seconds. They used the
nearest EARLIER `[hh:mm:ss]` mark, and the fetcher writes one mark a minute, so on
sergey-brin/badbellabear-9uzqfz four quotes at words 1, 23, 63 and 154 all linked to
0:05. `play_time` in pundits_verify_page.py interpolates between the marks around the
word and starts PLAY_LEAD_SECONDS early. Both builders call it, so they cannot drift.

Synthetic text only: this repository is public.

  HELPER    interpolation, lead, >> and marks not counted, both ends, a sparse gap,
            no marks, and the answer is never negative or past the duration
  LEADERS   speaker_audit_page.py gives four first-minute quotes four distinct times
  PUNDITS   pundits_verify_page.suspect_quotes gives the same times for the same quotes
  SHARED    neither builder reads a mark's hours and minutes itself

  .venv/bin/python scripts/test_play_time.py
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pundits_verify_page as V  # noqa: E402
import speaker_audit_page as A  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def stamp(sec: int) -> str:
    return f"[{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}]"


# Four marks, at 0:10, 1:10, 2:10 and 3:10, each followed by 120 words, so every
# word n is spoken at 10 + n/2 seconds. A turn mark `>>` sits inside each quote.
QUOTE_AT = (2, 24, 64, 110)
DURATION = 400
LEAD = V.PLAY_LEAD_SECONDS if hasattr(V, "PLAY_LEAD_SECONDS") else 5


def uniform_text() -> str:
    out = []
    for n in range(480):
        if n % 120 == 0:
            out.append(stamp(10 + n // 2))
        if n - 1 in QUOTE_AT:
            out.append(">>")
        out.append(f"w{n}")
    return " ".join(out)


def toks_of(text: str) -> list:
    return list(re.finditer(r"\S+", text))


def tok_of_word(toks: list, n: int) -> int:
    return next(i for i, t in enumerate(toks) if t.group() == f"w{n}")


def expected(n: int) -> int:
    return max(0, int(10 + n / 2) - LEAD)


def quote(n: int) -> str:
    return f"w{n} >> w{n + 1} w{n + 2} w{n + 3} w{n + 4}"


def helper_checks():
    print("[HELPER]")
    if not hasattr(V, "play_time"):
        check("pundits_verify_page defines the shared play_time helper", False, "no play_time")
        return
    P = V.play_time
    text = uniform_text()
    toks = toks_of(text)
    check("a word between two marks is interpolated by word position, less the lead",
          P(toks, tok_of_word(toks, 180), DURATION) == 100 - LEAD,
          P(toks, tok_of_word(toks, 180), DURATION))
    check("the lead is a parameter", P(toks, tok_of_word(toks, 180), DURATION, lead=0) == 100)
    turns = toks_of(stamp(0) + " a " + " ".join([">>"] * 10) + " b " + stamp(10))
    check("turn marks are not counted as spoken words", P(turns, 12, None, lead=0) == 5,
          P(turns, 12, None, lead=0))
    check("after the last mark the typical rate carries on",
          P(toks, tok_of_word(toks, 470), DURATION, lead=0) == 245)
    short = toks_of(uniform_text().rsplit(" ", 1)[0] + " " + " ".join(f"x{k}" for k in range(1000)))
    check("after the last mark the time is clamped to the recording's duration",
          P(short, len(short) - 1, DURATION, lead=0) == DURATION)
    pre = toks_of("p0 p1 p2 p3 p4 p5 p6 p7 p8 p9 " + text)
    check("before the first mark the time is extrapolated back at the typical rate",
          P(pre, 0, DURATION, lead=0) == 5 and P(pre, 4, DURATION, lead=0) == 7)
    check("the answer is never negative", P(pre, 0, DURATION, lead=20) == 0)
    # 0:00, 1:00, 2:00 with 120 words a gap, then a gap of 10 words over 280 s, the
    # shape a paragraph-loop collapse leaves, then a normal gap again.
    words = iter(range(10 ** 6))
    parts = []
    for sec, count in ((0, 120), (60, 120), (120, 10), (400, 120), (460, 0)):
        parts.append(stamp(sec))
        parts += [f"w{next(words)}" for _ in range(count)]
    sparse = toks_of(" ".join(parts))
    got = P(sparse, tok_of_word(sparse, 244), 500, lead=0)
    check("in a sparse gap a word is placed at the typical rate from the earlier mark, not stretched",
          got == 122, f"got {got}; stretched interpolation would give 232")
    nomark = toks_of(" ".join(f"w{k}" for k in range(200)))
    check("with no mark the time comes from words over duration", P(nomark, 100, 100, lead=0) == 50)
    check("with no mark and no duration there is no time", P(nomark, 100, None) is None)
    one = toks_of("a b c " + stamp(30) + " d e f")
    check("with one mark and no rate, a word after it gets the mark and a word before it gets 0",
          P(one, 5, None, lead=0) == 30 and P(one, 0, None, lead=0) == 0)
    try:
        P(toks, len(toks), DURATION)
        check("a token index outside the transcript is refused", False, "no error")
    except IndexError:
        check("a token index outside the transcript is refused", True)


def leaders_times(root: Path) -> dict:
    (root / "roster").mkdir(parents=True)
    (root / "roster" / "final.json").write_text(json.dumps({"roster": [
        {"slug": "jane-roe", "name": "Jane Roe", "role": "CEO"}]}))
    (root / "transcripts_open" / "jane-roe").mkdir(parents=True)
    (root / "transcripts_open" / "jane-roe" / "talk-1.json").write_text(json.dumps({
        "leader_slug": "jane-roe", "source_id": "talk-1", "video_id": "vid1", "yt_title": "T",
        "yt_duration_sec": DURATION, "text": uniform_text()}))
    d = root / "grades" / "fable" / "jane-roe"
    d.mkdir(parents=True)
    (d / "talk-1__fable__blinded__r0.json").write_text(json.dumps({
        "leader_slug": "jane-roe", "source_id": "talk-1", "judge": "fable", "mode": "blinded", "run": 0,
        "validation_errors": [], "grade": {"subject_speech_share_pct": 50, "dimensions": {
            "d1": {"evidence": [{"quote": quote(n)} for n in QUOTE_AT]}}}}))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)
    out = root / "session" / "speaker_check.html"
    A.build(SimpleNamespace(study="leaders", data=str(root), keys="jane-roe/talk-1", out=str(out),
                            reasons=None, cap=6))
    page = out.read_text()
    data = json.loads(page.split("const D = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</"))
    return {c["text"].split()[0]: c["t"] for c in data["quote_rows"][0]["quotes"]}


def pundits_times(root: Path) -> dict:
    (root / "t" / "jane-roe").mkdir(parents=True)
    (root / "t" / "jane-roe" / "talk-1.json").write_text(json.dumps({
        "video_id": "vid1", "yt_title": "T", "yt_duration_sec": DURATION, "text": uniform_text()}))
    (root / "g" / "fable" / "jane-roe").mkdir(parents=True)
    (root / "g" / "fable" / "jane-roe" / "talk-1__fable__blinded__r0.json").write_text(json.dumps({
        "leader_slug": "jane-roe", "source_id": "talk-1", "judge": "fable", "mode": "blinded", "run": 0,
        "grade": {"venue_type": "conversation", "dimensions": {"d1": {"evidence": [
            {"quote": quote(n), "speaker": "subject"} for n in QUOTE_AT]}}}}))
    rows, _, _ = V.suspect_quotes(root / "g", root / "t", {"jane-roe": {"slug": "jane-roe", "name": "Jane Roe"}})
    return {c["text"].split()[0]: c["t"] for c in rows[0]["quotes"]}


def main() -> int:
    helper_checks()
    want = {f"w{n}": expected(n) for n in QUOTE_AT}
    with tempfile.TemporaryDirectory() as td:
        print("\n[LEADERS]")
        lead_t = leaders_times(Path(td) / "leaders")
        check("every quote in the first minute is shown", set(lead_t) == set(want), str(sorted(lead_t)))
        check("four first-minute quotes link to four distinct times", len(set(lead_t.values())) == 4, str(lead_t))
        check("each link starts the lead before its quote's interpolated time", lead_t == want,
              f"got {lead_t}, want {want}")
        print("\n[PUNDITS]")
        pun_t = pundits_times(Path(td) / "pundits")
        check("the pundits quote cards link to the same interpolated times", pun_t == want,
              f"got {pun_t}, want {want}")
        check("the two builders agree card for card", pun_t == lead_t, f"pundits {pun_t}, leaders {lead_t}")
    print("\n[SHARED]")
    check("speaker_audit_page no longer carries its own mark lookup", not hasattr(A, "mark_before"))
    for name, src in (("speaker_audit_page", inspect.getsource(A)),
                      ("pundits_verify_page.suspect_quotes", inspect.getsource(V.suspect_quotes))):
        check(f"{name} converts no mark to seconds itself", "3600" not in src)
    print(f"\n{'FAILED: ' + '; '.join(FAILED) if FAILED else 'all passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
