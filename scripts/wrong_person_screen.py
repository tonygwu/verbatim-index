#!/usr/bin/env python3
"""Find transcripts where the person graded is not the leader they are filed under.

The subject-share filter cannot catch these. It asks whether SOMEONE is speaking,
and a wrong-person recording answers yes with maximum confidence: Han-Wei Shen's
lecture scored 100% subject share under C.C. Wei on all three judges.

What can catch them is the judges themselves. Every blinded grade carries
`identity_guess`, and on every wrong-person transcript found so far the judges
named the person who was actually speaking: "Eugene Wei", "Adam Dell", "Mario
Draghi", "Sebastian Mallaby". This screen reads those guesses against the roster
and cross-checks them with the source metadata. It never reads the transcript
text, so it costs no quota.

Per grade, `identity_guess` is classified against the leader:

  MATCH         the full name, or a company alias, appears in the guess
  SURNAME_ONLY  the surname appears, the given name and every company do not
  NAMESAKE      the company appears only after a negation ("the DJ, not the
                Epic Games founder")
  OTHER         none of the above: a different person, "unknown", "no
                executive speaks in this transcript"

Per recording the rules are:

  R1 identity   at least two judges are non-MATCH, or any judge says NAMESAKE
  R2 absent     at least two judges put subject share at 0
  R5 dissent    exactly one judge puts share at 0 while the mean clears the
                cutoff, so the recording is on the board on the other judges'
                word. MEASURED 2026-09-10: 10 of 10 such recordings were
                subject-absent, and the high judge had scored the host, the
                co-guest or a biographer instead.
  R6 lone       exactly one judge is non-MATCH and nothing else fired
  R3 namesake   every guess is the bare full name, and no guess and no metadata
                names the company. A namesake with the same full name looks
                exactly like this.

R1 and R2 are flags. R3, R5 and R6 are review lists: read the title and the
judges' attribution notes before acting.

MEASURED on the corpus of 2026-09-10 (558 blinded recordings): R1|R2 flagged 42,
every one hand-verified as subject-absent or wrong-speaker, so 0 false
positives. 24 of the 42 were ON the board; the other 18 were all-judges-zero
and the share filter had already dropped them. R5 added 3 more on-board cases.
A seeded sample of 40 unflagged recordings held 0 misses.

Two matching traps, both hit on the first version:
  - a surname that is also the company ("Dell") must not count as company
    evidence, or "Adam Dell" passes;
  - a given name must match as a prefix after accent-stripping, or "Clément
    Delangue" reads as a stranger.

Usage:
  .venv/bin/python scripts/wrong_person_screen.py                 # live data/
  .venv/bin/python scripts/wrong_person_screen.py --grades SNAP/grades \
      --transcripts SNAP/transcripts_open --roster SNAP/roster/final.json \
      --out report.json
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
import statistics as st
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Below this mean share the recording is already off the board. Kept in step
# with aggregate.MIN_SUBJECT_SHARE by reading it from there when importable.
try:
    sys.path.insert(0, str(REPO / "scripts"))
    from aggregate import MIN_SUBJECT_SHARE  # noqa: E402
except Exception:  # noqa: BLE001
    MIN_SUBJECT_SHARE = 10

# Former employers and products a judge may name instead of the roster company.
# A judge writing "the CEO of DeepMind" has identified Hassabis; "Meta's chief
# AI scientist" has identified LeCun. Roster `company` alone misses those.
EXTRA_COMPANIES: dict[str, list[str]] = {
    "yann-lecun": ["Meta", "Facebook", "FAIR", "NYU"],
    "bill-gates": ["Microsoft"],
    "bret-taylor": ["Salesforce", "Facebook", "Google"],
    "pat-gelsinger": ["Intel", "VMware"],
    "sergey-brin": ["Google"],
    "jack-dorsey": ["Twitter", "Square", "Block"],
    "jeff-bezos": ["Amazon", "Blue Origin"],
    "mustafa-suleyman": ["DeepMind", "Inflection", "Microsoft"],
    "lip-bu-tan": ["Intel", "Cadence", "Walden"],
    "demis-hassabis": ["DeepMind"],
    "sam-altman": ["OpenAI", "Y Combinator"],
    "palmer-luckey": ["Oculus", "Anduril"],
    "andy-jassy": ["AWS", "Amazon"],
    "elon-musk": ["SpaceX", "Tesla", "xAI", "Twitter"],
    "sundar-pichai": ["Google"],
    "thomas-kurian": ["Google Cloud", "Oracle"],
    "evan-spiegel": ["Snapchat", "Snap"],
    "mark-zuckerberg": ["Facebook", "Meta"],
    "fei-fei-li": ["Stanford", "World Labs", "ImageNet"],
    "cc-wei": ["TSMC", "Taiwan Semiconductor"],
    "tim-sweeney": ["Epic", "Unreal", "Fortnite"],
    "dara-khosrowshahi": ["Uber", "Expedia"],
    "arthur-mensch": ["Mistral"],
    "michael-dell": ["Dell"],
}

# Words that appear in roster company strings and identify nothing on their own.
GENERIC = {"Inc.", "Technologies", "Labs", "Global", "Platforms", "Industries",
           "Foundation", "Project"}

NEGATION = (r"\b(?:not|never|rather than|unrelated to|different from|distinct from|"
            r"as opposed to|instead of|no relation to|namesake|same name as|"
            r"shares? (?:a|the) name)\b")
LEAD = re.compile(r"^(?i:(?:actual |the |primary |main )?(?:speaker|interviewee|subject|guest)\s*[:=]\s*)?"
                  r"(?:Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?|Sir|Lord|Dame)?\s*"
                  r"([A-Z][\w'\.]+(?:\s+[A-Z][\w'\.]+){1,2})")
NOT_A_NAME = {"the", "a", "an", "possibly", "probably", "likely", "subject", "intended",
              "not", "no", "unknown", "nominal", "designated", "blinded"}


def norm(s: str | None) -> str:
    """Accent-stripped ASCII with hyphens and dotted initials flattened, so
    'Clément' and 'Clem', 'Lip Bu Tan' and 'Lip-Bu Tan', 'C. C. Wei' and
    'C.C. Wei' compare equal."""
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    t = t.replace("-", " ")
    return re.sub(r"\b([A-Z])\.\s*(?=[A-Z]\b|[A-Z]\.)", r"\1.", t)


def wb(needle: str, hay: str) -> bool:
    """Word-bounded, case-insensitive containment, on normalised text."""
    return re.search(r"(?<![A-Za-z])" + re.escape(norm(needle)) + r"(?![A-Za-z])", norm(hay), re.I) is not None


def leader_aliases(person: dict) -> tuple[str, str, str, list[str]]:
    """(full name, given name, surname, company aliases) for one roster entry."""
    name = person["name"]
    parts = name.split()
    given, surname = parts[0], parts[-1]
    comps = [c.strip() for c in re.split(r"/|,", person.get("company") or "")]
    comps += EXTRA_COMPANIES.get(person["slug"], [])
    comps = [c for c in comps if c and c not in GENERIC]
    return name, given, surname, comps


def given_in(given: str, text: str) -> bool:
    """'Clem' must match 'Clément'; initials such as 'C.C.' match literally; a
    given name shorter than 3 letters is not evidence on its own."""
    if "." in given:
        return norm(given) in norm(text)
    if len(given) < 3:
        return False
    return re.search(r"(?<![A-Za-z])" + re.escape(norm(given)), norm(text), re.I) is not None


def leading_name(guess: str) -> str | None:
    """The person a guess opens with, if it opens with one.
    'Adam Dell: founder of Domain Money' -> 'Adam Dell'."""
    m = LEAD.match(norm(guess).strip())
    if not m:
        return None
    toks = m.group(1).split()
    if toks[0].lower() in NOT_A_NAME:
        return None
    return " ".join(toks)


def negated_company(guess: str, comps: list[str]) -> bool:
    """A company alias within 80 characters AFTER a negation."""
    g = norm(guess)
    for m in re.finditer(NEGATION, g, re.I):
        window = g[m.end(): m.end() + 80]
        if any(wb(c, window) for c in comps):
            return True
    return False


def classify(guess: str | None, name: str, given: str, surname: str, comps: list[str]
             ) -> tuple[str, bool, bool]:
    """(class, full_name_seen, company_seen) for one identity_guess."""
    g = guess or ""
    if negated_company(g, comps):
        return "NAMESAKE", False, False
    full = wb(name, g) or (given_in(given, g) and wb(surname, g))
    # A surname that is also the company must not count as company evidence,
    # or "Adam Dell" and "John Roese of Dell Technologies" both pass.
    comp = any(wb(c, g) for c in comps if c.lower() != surname.lower())
    # The person the guess OPENS with decides. "Chip Conley is the actual
    # interviewee; the transcript ID names Brian Chesky" names the leader too,
    # and is a wrong-person verdict. "Marc Benioff, hosting Sundar Pichai"
    # opens with the leader and is a match.
    lead = leading_name(g)
    lead_is_other = bool(lead) and not (given_in(given, lead) and wb(surname, lead)) and not wb(name, lead)
    if lead_is_other:
        return ("SURNAME_ONLY" if wb(surname, g) else "OTHER"), False, comp
    if full or comp:
        return "MATCH", bool(full), comp
    if wb(surname, g):
        return "SURNAME_ONLY", False, False
    return "OTHER", False, False


def load_grades(root: Path) -> dict[tuple[str, str], list[dict]]:
    """Valid blinded grades per (leader, source)."""
    out: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for p in root.rglob("*__blinded__r*.json"):
        if "_raw" in p.parts:
            continue
        g = json.loads(p.read_text())
        if g.get("validation_errors") or g.get("refused") or "dimensions" not in (g.get("grade") or {}):
            continue
        out[(g["leader_slug"], g["source_id"])].append(g)
    return out


def load_transcripts(root: Path | None) -> dict[tuple[str, str], dict]:
    out = {}
    if root is None or not root.exists():
        return out
    for p in root.rglob("*.json"):
        r = json.loads(p.read_text())
        r.pop("text", None)
        out[(r["leader_slug"], r["source_id"])] = r
    return out


def screen(grades: dict, transcripts: dict, roster: list[dict], cutoff: int = MIN_SUBJECT_SHARE
           ) -> list[dict]:
    by_slug = {p["slug"]: leader_aliases(p) for p in roster}
    rows = []
    for key, gs in grades.items():
        if key[0] not in by_slug:
            continue
        name, given, surname, comps = by_slug[key[0]]
        judges, shares = [], []
        company_in_guess = False
        for g in gs:
            gr = g["grade"]
            cls, _full, comp = classify(gr.get("identity_guess"), name, given, surname, comps)
            company_in_guess |= comp
            judges.append({"judge": g["judge"], "class": cls, "confident": gr.get("identity_confident"),
                           "guess": (gr.get("identity_guess") or "")[:120],
                           "notes": (gr.get("attribution_notes") or "")[:240],
                           "share": gr.get("subject_speech_share_pct")})
            if isinstance(gr.get("subject_speech_share_pct"), int):
                shares.append(gr["subject_speech_share_pct"])
        r = transcripts.get(key, {})
        meta = " ".join(str(r.get(f) or "") for f in
                        ("yt_title", "declared_title", "yt_description", "yt_channel", "declared_venue"))
        meta_full = wb(name, meta) or (given_in(given, meta) and wb(surname, meta))
        meta_comp = any(wb(c, meta) for c in comps if c.lower() != surname.lower())
        n = len(judges)
        nonmatch = sum(1 for j in judges if j["class"] != "MATCH")
        namesake = sum(1 for j in judges if j["class"] == "NAMESAKE")
        zeros = sum(1 for s in shares if s == 0)
        mean_share = st.mean(shares) if shares else None
        on_board = mean_share is None or mean_share >= cutoff
        R1 = nonmatch >= 2 or (n == 1 and nonmatch == 1) or namesake >= 1
        R2 = zeros >= 2 or (n == 1 and zeros == 1)
        R5 = zeros == 1 and n > 1 and on_board
        R6 = nonmatch == 1 and n > 1 and not (R1 or R2 or R5)
        R3 = not (R1 or R2 or R5 or R6) and not company_in_guess and not meta_comp
        rows.append({
            "leader_slug": key[0], "source_id": key[1], "n_judges": n,
            "title": (r.get("yt_title") or r.get("declared_title") or "")[:120],
            "channel": r.get("yt_channel") or r.get("declared_venue"),
            "shares": shares, "mean_share": round(mean_share, 1) if mean_share is not None else None,
            "on_board": on_board, "meta_full_name": meta_full, "meta_company": meta_comp,
            "judges": judges,
            "R1_identity": R1, "R2_absent": R2, "R5_dissent_zero": R5, "R6_lone_dissent": R6,
            "R3_namesake_review": R3,
            "flagged": R1 or R2,
        })
    rows.sort(key=lambda x: (x["leader_slug"], x["source_id"]))
    return rows


def print_report(rows: list[dict], sample: int, seed: int) -> None:
    flagged = [x for x in rows if x["flagged"]]
    print(f"recordings screened: {len(rows)}")
    print(f"FLAGGED (R1 identity or R2 absent): {len(flagged)}  "
          f"[R1 {sum(x['R1_identity'] for x in rows)}, R2 {sum(x['R2_absent'] for x in rows)}]; "
          f"on the board: {sum(1 for x in flagged if x['on_board'])}")
    for x in flagged:
        where = "ON BOARD" if x["on_board"] else "already excluded"
        print(f"\nFLAG {x['leader_slug']}/{x['source_id']}  R1={x['R1_identity']} R2={x['R2_absent']}  {where}")
        print(f"   title: {x['title']!r} | {x['channel']}   shares={x['shares']}")
        for j in x["judges"]:
            print(f"   {j['judge']:6s} {j['class']:12s} {j['guess'][:80]!r}")
    for rule, label in (("R5_dissent_zero", "R5: one judge says 0, recording on the board"),
                        ("R6_lone_dissent", "R6: one judge names someone else"),
                        ("R3_namesake_review", "R3: bare name everywhere, company nowhere")):
        hits = [x for x in rows if x[rule]]
        print(f"\n==== REVIEW {label}: {len(hits)} ====")
        for x in hits:
            print(f"REV {x['leader_slug']}/{x['source_id']:34s} shares={x['shares']} title={x['title'][:60]!r}")
            for j in x["judges"]:
                if rule != "R3_namesake_review" and (j["class"] != "MATCH" or j["share"] == 0):
                    print(f"      {j['judge']:6s} {j['class']:12s} {j['guess'][:70]!r} :: {j['notes'][:140]!r}")
    if sample:
        clean = [x for x in rows if not any(x[k] for k in
                 ("flagged", "R5_dissent_zero", "R6_lone_dissent", "R3_namesake_review"))]
        rng = random.Random(seed)
        print(f"\n==== unflagged {len(clean)}; seeded sample of {min(sample, len(clean))} for a false-negative check ====")
        for x in rng.sample(clean, min(sample, len(clean))):
            print(f"UN {x['leader_slug']}/{x['source_id']:34s} shares={x['shares']} title={x['title'][:55]!r} "
                  f"guesses={[j['guess'][:28] for j in x['judges']]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--grades", default=str(REPO / "data" / "grades"))
    ap.add_argument("--transcripts", default=str(REPO / "data" / "transcripts_open"),
                    help="Source metadata (title, channel, description). Text is never read.")
    ap.add_argument("--roster", default=str(REPO / "data" / "roster" / "final.json"))
    ap.add_argument("--out", default=None, help="Write per-recording verdicts as JSON here.")
    ap.add_argument("--sample", type=int, default=40, help="Unflagged recordings to print for a false-negative check.")
    ap.add_argument("--seed", type=int, default=20260910)
    args = ap.parse_args()

    roster = json.loads(Path(args.roster).read_text())["roster"]
    grades = load_grades(Path(args.grades))
    if not grades:
        raise SystemExit(f"no blinded grades under {args.grades}")
    transcripts = load_transcripts(Path(args.transcripts) if args.transcripts else None)
    if not transcripts:
        print(f"WARNING: no transcript metadata under {args.transcripts}; R3 and the "
              f"metadata columns will be blank", file=sys.stderr)
    rows = screen(grades, transcripts, roster)
    print_report(rows, args.sample, args.seed)
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        print(f"\nverdicts written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
