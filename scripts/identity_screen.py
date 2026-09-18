#!/usr/bin/env python3
"""Is the person we filed this under actually the one speaking? Decided WITHOUT a judge.

THE GAP THIS FILLS. `wrong_person_screen.py` is the detector that works, and it
works by reading `identity_guess` out of grades. The seven investors joining the
predictions board will never have a grade, because `grade.py`'s membership gate
drops them before a judge is chosen. So the screen that catches this class cannot
see them at all, and `name_in()` still matches "Hollywood" for Cathie Wood and
"s-lee-ping" for Tom Lee.

WHAT WAS ALREADY TRIED AND IS NOT ENOUGH. The rule AGENTS.md proposes, full name
or surname plus a company token, was implemented and replayed against the known
wrong-person cases: `accepted(bad)=8, rejected(good)=2`. It fails because the
surviving shapes are co-guest, interviewer and commentary, where the title names
the leader entirely correctly and somebody else is speaking. A stricter title
rule cannot fix a title that is true.

SO THIS SCREEN DOES NOT ASK "IS THE NAME IN THE TITLE". It asks four separate
questions, reports each one, and never collapses them into a bare boolean:

  identity      does the title or channel identify this person specifically,
                rather than by a surname that something else also matches
  exclusivity   does the title name OTHER people too? This is the co-guest and
                interviewer shape, and it is the one the replayed rule missed.
                "Satya Nadella | BG2 w/ Bill Gurley & Brad Gerstner" names three
                people and is a real record in this corpus
  aboutness     is the transcript ABOUT the person rather than BY them? Reuses
                qa_transcripts.name_density_after_intro, which is already
                calibrated and already grade-free, plus the possessive and
                narrative title shapes that the Happy Scribe finding named and
                that discover_sources' interrogative patterns miss
  own_voice     do the captions carry speaker labels? A human caption track
                marks turns as ">> NAME:", and where they exist own-voice is
                decidable mechanically. Where they do not, this returns unknown,
                which is NOT the same as pass

EVERY VERDICT CARRIES ITS REASONS. A screen that returns True or False teaches an
operator to trust it; one that says which signal fired lets them disagree with
it. The overall verdict is `pass`, `review` or `reject`, and `review` is the
honest answer for most records: this screen is a cheap filter in front of a human,
not a replacement for one.

DO NOT "CLEAN UP" THE EXCLUSIVITY NOISE. Some flagged names are title-case
phrases rather than people: "First Principles", "Silicon Valley", "Growth
Stocks". The obvious fix is to reject a pair whose last token is an ordinary
dictionary word. MEASURED 2026-09-18 against the 98 real candidates:

    removes 5 of 8 noise phrases
    LOSES   4 of 15 real co-guests: Jeff Jordan, Elad Gil, Rich Barton,
            Scott Miller

A 27% loss of true positives to remove a handful of phrases a human skims past is
the wrong trade for a screen whose whole purpose is recall. And the decisive case
is worse than the ratio suggests: that heuristic removes "One Medical Group",
which is the ONLY signal flagging "Keynote Tom Lee, Founder & CEO, One Medical
Group". That candidate is a different Tom Lee, the physician who founded One
Medical, not Fundstrat's Thomas J. Lee. Its identity and aboutness signals both
PASS, so silencing exclusivity turns the single most valuable catch this screen
has made into a clean pass.

The noise is the price of the catch. Leave it.

WHAT IT DELIBERATELY DOES NOT DO. It spends no quota, calls no judge, makes no
network request, and reads no grade. It is safe to run over any corpus at any
time, which is the whole point: the alternative on the table was hand-reviewing
roughly 84 transcripts, or accepting the risk.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

#: Possessive and narrative shapes: the video is ABOUT the person. The patterns
#: in discover_sources.THIRD_PERSON_TITLE are interrogative and biographical
#: ("who is", "the man who", "net worth"); these are the ones the Happy Scribe
#: pass let through, taken from the four recordings it actually admitted.
ABOUT_TITLE = re.compile(
    r"(\bhas a (message|warning|problem)\b|\bbegins? training\b|\bslams?\b|"
    r"\btorches\b|\bdestroys\b|\bhits? back\b|\bresponds? to\b|\breacts? to\b|"
    # NOT \blive:, \bwatch: or \bbreaking:. MEASURED over 664 live records, those
    # three produced 5 rejects and ALL FIVE were false positives: "LIVE: Mark
    # Zuckerberg speaks at ...", "WATCH LIVE: OpenAI's Sam Altman address at ...".
    # A broadcast prefix says the stream was live, not that somebody else is
    # talking. The Happy Scribe case that suggested them was
    # "live-jeff-bezos-rocket-new-glenn-attempting", where the signal is
    # "attempting", which is kept.
    r"\b(attempting|attempts) to\b|"
    r"\bwhat .* (said|got wrong|gets? wrong)\b|\baccording to\b)", re.I)

#: Speaker-label markers used by human caption tracks.
SPEAKER_LABEL = re.compile(r"(^|\n)\s*>>\s*([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3})\s*:")

#: A capitalised full name anywhere in a title: "Firstname Lastname".
OTHER_NAME = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b")

#: Words that look like a name to OTHER_NAME but are show furniture.
NOT_A_NAME = {
    "The", "This", "How", "What", "Why", "When", "Full", "Live", "New", "Best",
    "All", "Big", "Real", "Open", "Future", "Read", "Watch", "Part", "Episode",
    "Special", "Keynote", "Keynotes", "Fireside", "Chat", "Podcast", "Show",
    "Interview", "Conference", "Summit", "Series", "Season", "Artificial",
    "Intelligence", "Former", "Prime", "Minister", "CEO", "CTO", "CFO", "Founder",
    "Co", "President", "Chairman", "Professor", "Dr", "Mr", "Ms", "Mrs", "Sir",
    "Panel", "Discussion", "Talk", "Talks", "Session", "Day", "Class", "Academy",
    "Data", "Collection", "Use", "And", "Cost", "For", "Self", "Driving", "Cars",
    "More", "Than", "About", "Building", "Global", "World", "Tech", "Technology",
}



def speaker_labels(text: str) -> list[str]:
    """Distinct speaker labels in a caption track, in order of first appearance."""
    seen: list[str] = []
    for m in SPEAKER_LABEL.finditer(text or ""):
        who = m.group(2).strip()
        if who not in seen:
            seen.append(who)
    return seen


def other_named_people(title: str, person: dict) -> list[str]:
    """People OTHER than the subject who the title says are also present.

    THE CO-GUEST AND INTERVIEWER SHAPE, which is the one a stricter title rule
    cannot catch, because the title names the subject entirely correctly.

    NOT "every capitalised word pair". MEASURED over 664 live records, that
    version fired on 439 of them, because English title case makes ordinary
    phrases look like names: it returned 'Have To', 'Be Honest', 'Will Replace'
    and 'Million Jobs' from one Uber headline. A screen that flags two thirds of
    a clean corpus is noise an operator learns to ignore.

    What the real cases actually carry is LIST OR CONJUNCTION STRUCTURE joining
    the subject to somebody else, verbatim from this corpus:

      "Fireside Chat: Aidan Gomez and Alexandr Wang"
      "Vitalik Buterin & Brian Armstrong [LIVE]"
      "Jensen Huang, Lisa Su, James Litinsky, Chase Lochmiller"
      "Keynotes by Demis Hassabis, Yoshua Bengio"
      "Fireside Chat with Mario Draghi, former Prime Minister"
      "comma ai | Riccardo Biasini | Data Collection"

    So the pattern is a name-shaped token sequence in a joining position: after
    "and", "&", "with", "w/", "by", "interviewed by", "hosted by", "featuring",
    or inside a comma-separated run, or fenced by a pipe.
    """
    name = person.get("name", "")
    own = {p.lower().strip(".") for p in name.split()}
    NAME_TOKEN = r"[A-Z][a-zA-Z.'\u00c0-\u024f-]+"
    PERSON = rf"{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{1,3}}"
    joiners = [
        rf"(?:\band\b|&)\s+({PERSON})",
        rf"\b(?:with|w/|by|featuring|feat\.?|hosted by|interviewed by|joins?|vs\.?)\s+({PERSON})",
        rf",\s*({PERSON})(?=\s*(?:,|and\b|&|$))",
        rf"\|\s*({PERSON})\s*\|",
        rf"({PERSON})\s*(?:\band\b|&)",
    ]
    out: list[str] = []
    for pat in joiners:
        for m in re.finditer(pat, title or ""):
            cand = " ".join(m.group(1).split())
            toks = [t.strip(".") for t in cand.split()]
            if any(t in NOT_A_NAME for t in toks):
                continue
            if any(t.lower() in own for t in toks):
                continue
            if len(toks) < 2:
                continue
            if cand not in out:
                out.append(cand)
    return out


#: Where a transcript record actually keeps its title, in the order to try.
#: `yt_title` is what the YouTube fetcher writes, `declared_title` comes from the
#: manifest, and `title` is what the Happy Scribe path and the web corpus use.
TITLE_FIELDS = ("yt_title", "declared_title", "title")


def title_of(rec: dict) -> str:
    """The record's title. RAISES when it has none.

    NOT `rec.get("title") or ""`. The first version of this file did exactly
    that, and MEASURED over the live corpus it scored 664 records against an
    empty string: `identity` failed on 663 of 664 and `exclusivity` on 0,
    because there was no text to find a name in. Every verdict was meaningless
    and the screen reported them as if they were not. A missing title is a
    defect in whatever wrote the record, not a title of "".
    """
    for f in TITLE_FIELDS:
        v = rec.get(f)
        if v:
            return v
    raise RuntimeError(
        f"{rec.get('leader_slug')}/{rec.get('source_id')} carries none of "
        f"{list(TITLE_FIELDS)}, so identity cannot be screened for it. A record "
        f"with no title is a defect in the fetcher that wrote it; screening it "
        f"against an empty string would report a verdict that means nothing.")


def name_variants(name: str) -> list[str]:
    """Forms of `name` a real title uses. MEASURED against this corpus.

    The 14 identity failures on the first live run were almost all variants, not
    wrong people: "Alexander Karp" for Alex Karp, "Alex Wang" for Alexandr Wang,
    "Clement Delangue" and "Clement" for Clem Delangue, "Fei Fei Li" for
    Fei-Fei Li, "Tobias Lutke" for Tobi Lutke, "Vladimir Tenev" for Vlad Tenev,
    "@satyanadella" and "AndyJassy" with no space at all.
    """
    import unicodedata
    def fold(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", t)
                       if unicodedata.category(c) != "Mn").lower()
    parts = name.split()
    out = {fold(name), fold(name).replace(" ", ""), fold(name).replace("-", " ")}
    if len(parts) >= 2:
        given, surname = parts[0], parts[-1]
        # A title may lengthen or shorten the given name: Alex/Alexandr,
        # Clem/Clement, Tobi/Tobias, Vlad/Vladimir, Alex/Alexander.
        out.add(f"{fold(given)} {fold(surname)}")
        out.add(f"{fold(given)}{fold(surname)}")
    return sorted(x for x in out if x)


def given_name_prefix_match(name: str, low: str) -> str | None:
    """A title using a longer or shorter form of the given name, with the surname.

    Requires the SURNAME to be present as a word, so this cannot admit a
    different person: it only tolerates Alex/Alexandr beside Wang.
    """
    parts = name.split()
    if len(parts) < 2:
        return None
    import unicodedata
    def fold(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", t)
                       if unicodedata.category(c) != "Mn").lower()
    given, surname = fold(parts[0]), fold(parts[-1])
    if not re.search(r"\b" + re.escape(surname) + r"\b", low):
        return None
    for tok in re.findall(r"[a-z]+", low):
        if len(tok) >= 3 and (tok.startswith(given[:3]) or given.startswith(tok[:3])):
            if tok == given or tok.startswith(given) or given.startswith(tok):
                return f"given-name variant {tok!r} with the surname {surname!r}"
    return None


def identifies(title: str, channel: str, person: dict) -> tuple[bool, str]:
    """Does the title or channel name THIS person, not merely their surname?"""
    import unicodedata
    name = (person.get("name") or "").strip()
    hay = f"{title or ''} {channel or ''}"
    low = "".join(c for c in unicodedata.normalize("NFD", hay)
                  if unicodedata.category(c) != "Mn").lower()
    for v in name_variants(name):
        if v and v in low:
            return True, f"name present as {v!r}"
    why = given_name_prefix_match(name, low)
    if why:
        return True, why
    parts = name.split()
    surname = parts[-1].lower() if parts else ""
    company = (person.get("company") or "").strip()
    if surname and re.search(r"\b" + re.escape(surname) + r"\b", low):
        # WORD BOUNDARIES, not a substring. MEASURED while writing the test:
        # company "ARK" matched inside "markets", so "Wood talks markets" was
        # accepted as "surname plus company token". A three-letter company token
        # inside ordinary words is the same defect class this screen exists to
        # catch, arriving inside the screen itself.
        if company and re.search(r"\b" + re.escape(company.lower()) + r"\b", low):
            return True, f"surname plus company token {company!r}"
        return False, (f"surname {surname!r} present but neither the full name nor the "
                       f"company; this is the shape that matched 'Hollywood' for Cathie "
                       f"Wood and 's-lee-ping' for Tom Lee")
    return False, "neither the full name nor the surname appears"


def screen_one(rec: dict, person: dict, *, name_density_limit: float = 1.6) -> dict:
    """Four independent signals and one verdict, with every reason kept."""
    import qa_transcripts as QA

    title = title_of(rec)
    channel = rec.get("yt_channel") or rec.get("channel") or ""
    text = rec.get("text") or ""
    surname = (person.get("name") or "").split()[-1] if person.get("name") else ""

    ident_ok, ident_why = identifies(title, channel, person)
    others = other_named_people(title, person)
    rate, hits = QA.name_density_after_intro(text, surname)
    about = bool(ABOUT_TITLE.search(title))
    labels = speaker_labels(text)

    signals = {
        "identity": {"ok": ident_ok, "reason": ident_why},
        "exclusivity": {
            "ok": not others,
            "other_people_named_in_title": others,
            "reason": ("the title names only this person" if not others else
                       f"the title also names {', '.join(others)}, so the speaker being "
                       f"transcribed may be one of them; this is the co-guest and "
                       f"interviewer shape that a stricter title rule cannot catch"),
        },
        "aboutness": {
            "ok": (rate <= name_density_limit) and not about,
            "name_density_per_1000": round(rate, 2),
            "name_hits_after_intro": hits,
            "limit": name_density_limit,
            "about_title_match": about,
            "reason": ("speaks as themselves" if (rate <= name_density_limit and not about)
                       else f"named {rate:.1f} times per 1000 words after the introduction "
                            f"(limit {name_density_limit})" if rate > name_density_limit
                       else "the title is possessive or narrative, so the video is about them"),
        },
        "own_voice": {
            "ok": None,
            "speaker_labels": labels,
            "reason": "no speaker labels in the captions, so own voice is undecidable here",
        },
    }
    if labels:
        named = [l for l in labels
                 if surname and re.search(r"\b" + re.escape(surname) + r"\b", l, re.I)]
        signals["own_voice"] = {
            "ok": bool(named),
            "speaker_labels": labels,
            "reason": (f"captions label {len(labels)} speakers and one is {named[0]!r}"
                       if named else
                       f"captions label {len(labels)} speakers and none is {surname!r}"),
        }

    # THE VERDICT. Only aboutness can REJECT on its own, because it is the only
    # signal with a calibrated threshold behind it. Everything else routes to
    # review, which is the honest answer: this is a filter in front of a person.
    failed = [k for k, v in signals.items() if v["ok"] is False]
    if not signals["aboutness"]["ok"] or signals["own_voice"]["ok"] is False:
        verdict = "reject"
    elif failed:
        verdict = "review"
    else:
        verdict = "pass"
    # own_voice UNKNOWN does not by itself force review. MEASURED on this corpus:
    # 0 of 664 records carry speaker labels, because YouTube auto-captions have
    # none, so treating unknown as review returned "review" for all 664 and the
    # screen filtered nothing. Unknown is reported in the signal and is visible
    # in `own_voice_unknown` in the report; it is not a verdict.

    return {
        "source_id": rec.get("source_id") or rec.get("transcript_id"),
        "leader_slug": rec.get("leader_slug"),
        "title": title,
        "verdict": verdict,
        "failed_signals": failed,
        "signals": signals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcripts", required=True,
                    help="A transcript root. Every *.json under it is screened.")
    ap.add_argument("--roster", required=True)
    ap.add_argument("--only", default=None,
                    help="Comma-separated slugs. Without it every slug found is screened.")
    ap.add_argument("--out", default=None, help="Write the full report here as JSON.")
    args = ap.parse_args()

    roster = {p["slug"]: p for p in json.loads(Path(args.roster).read_text())["roster"]}
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    if only:
        unknown = sorted(only - set(roster))
        if unknown:
            raise SystemExit(f"--only names {unknown}, which are not in {args.roster}")

    rows, skipped = [], 0
    for p in sorted(Path(args.transcripts).rglob("*.json")):
        if any(part.startswith("_") for part in p.parts):
            continue
        rec = json.loads(p.read_text())
        slug = rec.get("leader_slug")
        if only and slug not in only:
            continue
        if slug not in roster:
            skipped += 1
            continue
        rows.append(screen_one(rec, roster[slug]))

    tally: dict[str, int] = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    report = {
        "screened": len(rows),
        "skipped_slug_not_in_roster": skipped,
        "verdicts": tally,
        # Reported because it bounds what this screen can know. On a corpus of
        # YouTube auto-captions this is every record, and own_voice contributes
        # nothing; on a corpus with human caption tracks it is the strongest
        # signal here. The number says which corpus you have.
        "own_voice_unknown": sum(1 for r in rows if r["signals"]["own_voice"]["ok"] is None),
        "signal_failures": {
            k: sum(1 for r in rows if r["signals"][k]["ok"] is False)
            for k in ("identity", "exclusivity", "aboutness", "own_voice")
        },
        "by_slug": {},
        "rows": rows,
    }
    for r in rows:
        s = report["by_slug"].setdefault(r["leader_slug"], {})
        s[r["verdict"]] = s.get(r["verdict"], 0) + 1

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    for r in rows:
        if r["verdict"] != "pass":
            print(f"  {r['verdict'].upper():6s} {r['leader_slug']}/{r['source_id']}  "
                  f"{r['title'][:70]}")
            for k in r["failed_signals"] or []:
                print(f"           {k}: {r['signals'][k]['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
