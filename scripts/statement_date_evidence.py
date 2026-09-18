#!/usr/bin/env python3
"""Where a recording's REAL date can be read from, when the upload date is wrong.

VP-16. Eleven past-due predictions target a date BEFORE their own statement date,
across six leaders. The cause is known: `declared_year()` takes the YouTube upload
date, and a 2006 keynote uploaded in 2013 makes "this year" resolve to 2013. The
resolver then marks the record `unresolvable:deadline_incoherent` and it scores
nothing. MEASURED against the published board, that is costing records on leaders
still UNDER the rank floor, `bill-gates` worst at four.

THIS TOOL DOES NOT DECIDE THE DATE. It gathers every date signal already on disk
for the affected recordings, quotes the text each one came from, and says whether
they agree. A statement date is an input to whether a prediction came true, so a
guessed one does not merely lose a record, it silently flips a verdict. The
repo's rule is fail-loud over accept-and-guess, and a date is exactly where that
matters.

WHERE THE SIGNALS COME FROM, in the order this file trusts them:

  description   `yt_description` often carries the real occasion verbatim:
                "On May 9, 2019, our founder discussed ..." or "Microsoft Keynote
                at the Consumer Electronics Show 2006". This is the strongest
                signal because a human wrote it about the event.
  source_id     the slug is derived from the title, so a title carrying the year
                puts it here: `microsoftces2005-4ch1ow`.
  title         `yt_title`, same reasoning, kept separate because the slug is
                lossy.
  transcript    the opening of a keynote very often dates itself: "welcome to
                CES 2006". Only the first stretch is read, because a later
                mention is usually a reference to some other year.
  upload        `yt_upload_date`, reported for contrast. It is the signal that is
                WRONG in every one of these cases, so it never votes.

A VERDICT OF `conflict` IS A RESULT, NOT A FAILURE. The first record inspected
while writing this, `bill-gates/microsoftces2005-4ch1ow`, has a source_id saying
2005 and a description saying "Consumer Electronics Show 2006". Those are
different keynotes a year apart. Anything that picked one would have been
guessing, and this prints both.

NOTHING IS WRITTEN. Applying a correction edits production prediction records and
belongs to a reviewed step with a person in it.

No quota, no network, no writes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Plausible years for this corpus. A four-digit number outside it is a quantity,
#: a price or a product number, not a date.
YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")

#: STRONG signals name the occasion. A title and a slug are a human's label FOR
#: THE VIDEO, so a year in them is the event's year: "Microsoft PDC 1996 Keynote
#: with Bill Gates", "Jeff Bezos - March 1998, earliest long speech".
STRONG = ("title", "source_id")

#: A description is prose and a bare year in it is usually about something else.
#: MEASURED: lisa-su `tbpn-8jqi1y` is a live 2026 show whose description is a
#: timestamped chapter list about other guests, and a bare-year rule proposed
#: 2014 as its statement date. So a description votes ONLY when it carries a full
#: date, month and day and year together, which prose almost never does by
#: accident: "On May 9, 2019, our founder discussed ...".
WEAK = ("description",)
AUTHORITATIVE = STRONG + WEAK

#: "On May 9, 2019" / "May 9 2019" / "9 May 2019". The month name is what
#: separates a date from a bare year, and a full date beats a year.
FULL_DATE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(19[89]\d|20[0-4]\d)\b", re.I)

#: How much of the transcript opening to read. A keynote dates itself in the
#: welcome; a mention 40 minutes in is usually about a different year.
OPENING_WORDS = 400


def _snippet(text: str, at: int, width: int = 70) -> str:
    lo, hi = max(0, at - width), min(len(text), at + width)
    return " ".join(text[lo:hi].split())


def years_in(text: str, *, source: str) -> list[dict]:
    out = []
    for m in FULL_DATE.finditer(text or ""):
        out.append({"source": source, "kind": "full_date", "year": int(m.group(3)),
                    "value": " ".join(m.group(0).split()),
                    "quote": _snippet(text, m.start())})
    for m in YEAR.finditer(text or ""):
        if any(d["kind"] == "full_date" and str(d["year"]) in m.group(0) for d in out):
            continue
        out.append({"source": source, "kind": "year", "year": int(m.group(1)),
                    "value": m.group(1), "quote": _snippet(text, m.start())})
    return out


def evidence_for(rec: dict) -> dict:
    """Every date signal on disk for one transcript record, with its quote."""
    sid = rec.get("source_id") or ""
    title = rec.get("yt_title") or rec.get("declared_title") or ""
    desc = rec.get("yt_description") or ""
    text = " ".join((rec.get("text") or "").split()[:OPENING_WORDS])
    upload = rec.get("yt_upload_date") or ""

    signals: list[dict] = []
    signals += years_in(desc, source="description")
    # The slug carries no spaces, so YEAR needs help finding a year glued to a word.
    for m in re.finditer(r"(19[89]\d|20[0-4]\d)", sid):
        signals.append({"source": "source_id", "kind": "year", "year": int(m.group(1)),
                        "value": m.group(1), "quote": sid})
    signals += years_in(title, source="title")
    signals += years_in(text, source="transcript_opening")

    # ONLY THE SIGNALS THAT DESCRIBE THE EVENT VOTE. transcript_opening is
    # reported as context and never counted. MEASURED over 38 affected records,
    # letting it vote produced 30 conflicts and 8 agreements, and the conflicts
    # were nearly all biographical prose: "vice president of web services since
    # April 2006", "from January 2005 to April 2006". Those are years the speaker
    # mentions, not the year they are speaking in.
    voting = [s for s in signals
              if s["source"] in STRONG
              or (s["source"] in WEAK and s["kind"] == "full_date")]
    # A RECORDING CANNOT PREDATE ITS OWN UPLOAD IN THE OTHER DIRECTION. A year
    # AFTER the upload year is impossible as a statement date and is a year the
    # description mentions, usually the prediction's own target: bill-gates
    # 'jay-shetty-podcast' uploaded 2025 offered 2028, and lisa-su
    # 'bloomberg-podcasts' uploaded 2026 offered 2027. Both would have been
    # proposed as statement dates without this, which is the accept-and-guess
    # this file exists to refuse.
    upload_year = int(upload[:4]) if upload[:4].isdigit() else None
    impossible = []
    if upload_year:
        # Reported from EVERY authoritative signal, not only the voting ones. A
        # bare description year never votes, but an operator reading this wants
        # to know a 2028 was seen and why it was not used.
        impossible = [x for x in signals
                      if x["source"] in AUTHORITATIVE and x["year"] > upload_year]
        voting = [x for x in voting if x["year"] <= upload_year]
    years = Counter(s["year"] for s in voting)
    # A full date outranks a bare year from the same place, and description
    # outranks everything, because a human wrote it about the event.
    best = None
    for src in STRONG + WEAK:
        cands = [s for s in voting if s["source"] == src]
        full = [s for s in cands if s["kind"] == "full_date"]
        if full:
            best = full[0]
            break
        if cands and best is None:
            best = cands[0]
    verdict = "none"
    if years:
        distinct = set(years)
        verdict = "agreed" if len(distinct) == 1 else "conflict"
    return {
        "source_id": sid,
        "leader_slug": rec.get("leader_slug"),
        "upload_date": upload,
        "upload_year": upload_year,
        "discarded_after_upload": [
            {"source": x["source"], "value": x["value"], "year": x["year"]} for x in impossible],
        "verdict": verdict,
        "years_seen": dict(sorted(years.items())),
        "best_guess": best,
        "signals": signals,
    }


def incoherent_transcripts(scores_path: Path) -> dict[str, set[str]]:
    """Transcript ids the resolver marked deadline_incoherent, per leader."""
    out: dict[str, set[str]] = {}
    if not scores_path.is_file():
        return out
    data = json.loads(scores_path.read_text())
    rows = data if isinstance(data, list) else data.get("leaders") or data.get("rows") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    for row in rows:
        slug = row.get("slug") or row.get("leader_slug")
        for p in row.get("predictions") or row.get("records") or []:
            if "deadline_incoherent" in str(p.get("not_scored_because") or ""):
                tid = p.get("transcript_id") or p.get("source_id")
                if slug and tid:
                    out.setdefault(slug, set()).add(tid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcripts", default="data/transcripts_open")
    ap.add_argument("--only", default=None, help="Comma-separated slugs.")
    ap.add_argument("--source-ids", default=None,
                    help="Comma-separated source ids, for the records the resolver named.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    want = {s.strip() for s in args.source_ids.split(",")} if args.source_ids else None

    rows = []
    for p in sorted(Path(args.transcripts).rglob("*.json")):
        if any(part.startswith("_") for part in p.parts):
            continue
        rec = json.loads(p.read_text())
        if only and rec.get("leader_slug") not in only:
            continue
        if want and rec.get("source_id") not in want:
            continue
        ev = evidence_for(rec)
        # Only interesting when a non-upload signal disagrees with the upload year.
        if ev["years_seen"] and ev["upload_year"] and \
                any(y != ev["upload_year"] for y in ev["years_seen"]):
            rows.append(ev)

    tally = Counter(r["verdict"] for r in rows)
    report = {"examined": len(rows), "verdicts": dict(tally), "rows": rows}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n")

    print(json.dumps({"examined": len(rows), "verdicts": dict(tally)}, indent=1))
    for r in sorted(rows, key=lambda r: (r["leader_slug"] or "", r["source_id"])):
        print(f"\n{r['verdict'].upper():8s} {r['leader_slug']}/{r['source_id']}")
        print(f"         upload says {r['upload_date']}, other signals say "
              f"{sorted(r['years_seen'])}")
        for s in r["signals"][:4]:
            print(f"           {s['source']:18s} {s['value']:16s} {s['quote'][:78]!r}")
    if tally.get("conflict"):
        print(f"\n{tally['conflict']} record(s) have signals that DISAGREE. Those need a "
              f"person, not a heuristic: a wrong statement date does not lose a "
              f"prediction, it flips whether it came true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
