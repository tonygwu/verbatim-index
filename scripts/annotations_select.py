#!/usr/bin/env python3
"""What each project annotates: its data, its checklist and how its quotes are chosen.

A PROJECT is the work a transcript feeds. `insights` is the leaderboard (study
`leaders`, board `leaders`), `predictions` is the predictions board (study
`leaders`, board `predictions`) and `pundits` is the pundits study. One recording
can belong to more than one project: insights and predictions read the same
`transcripts_open` file, so a session can tag a recording with both and the
person marks its speakers once.

The annotation tool itself knows nothing project-specific. Everything that differs
between projects is in PROJECTS below: where the transcript and roster are, which
quotes a person checks, and whether the recording has a checklist. Quote selection:

  insights     every evidence quote any judge cited, located in the open text
               (a blinded `[SUBJECT]` matches the name it replaced), deduplicated
               across judges and capped per recording by taking the judges in turn,
               strongest suspicion first. Blind: no judge label reaches the page.
  predictions  every ACCEPTED prediction, placed by its exact character offsets; an
               offset that does not reproduce `quote_original` stops the build.
  pundits      evidence quotes the judges credited to the subject that mechanical
               signals mark as suspect (`suspect_quotes`), across the graded corpus.

Every judge, extractor and verifier claim goes into the session's quote key, never
onto the page. This module must never convert a mark's time itself; `card` uses
`annotations_text.play_time` (checked by `scripts/test_play_time.py`).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annotations_text import CONTEXT_WORDS, MARK, _norm, locate, name_forms, play_time  # noqa: E402
from pundits_pilot import VENUES  # noqa: E402

MODES = ("checklist", "speakers", "captions")
DEFAULT_CAP = 6
QUOTE_CAP_PER_RECORDING = 4
SIGNAL_RANK = {"spans_turn": 3, "question_in_conversation": 2, "names_subject": 1}
# A judge whose speech share sits this far from the recording's median read the
# turns differently from the others, so its quotes are the likeliest to be wrong.
DISSENT_POINTS = 25
SIGNAL_WEIGHT = {"dissenting_judge": 4, "spans_turn": 3, "question": 2, "names_subject": 1,
                 "turn_near_quote": 1}

VENUE_HELP = {
    "solo": "The subject talks to the audience with no other live voice, including covering news stories.",
    "reaction": "The subject plays other material and comments on it, with no other live voice.",
    "conversation": "Other live voices talk with the subject, whoever hosts: interviews either way round, panels, "
                    "co-hosted shows, TV segments.",
    "debate": "Organised opposing sides with at least one named opponent, usually with a moderator or turns.",
    "speech": "A prepared talk to a live audience, with or without questions afterwards.",
}

#: The pundits P6 recording questions. The page renders any checklist from a spec of
#: this shape, and `export labels` requires exactly the `required` fields. Each
#: field's `draft_label` names it on the model-draft card; `differs_only_if` makes a
#: disagreement with the draft count only once that other field is true (the format
#: of a recording the subject is absent from does not matter, as in `needs_review`).
PUNDITS_CHECKLIST = {
    "fields": [
        {"name": "subject_present", "label": "Subject present", "help": "Takes part live; a played clip is not presence",
         "type": "bool", "required": True, "draft_label": "subject present",
         "options": [{"value": True, "label": "Yes", "key": "y", "cls": "y"},
                     {"value": False, "label": "No", "key": "n", "cls": "n"}]},
        {"name": "venue", "label": "Format", "help": "of this recording", "type": "enum", "required": True,
         "draft_label": "format", "differs_only_if": "subject_present",
         "prompt": "Pick the format that fills most of the recording.",
         "options": [{"value": v, "label": v, "key": str(i + 1), "help": VENUE_HELP[v]} for i, v in enumerate(VENUES)]},
        {"name": "political_content", "label": "Political content", "help": "politics, policy, news or public controversy",
         "type": "bool", "required": True, "draft_label": "political",
         "options": [{"value": True, "label": "Yes", "key": "p", "cls": "y"},
                     {"value": False, "label": "No", "key": "o", "cls": "n"}]},
    ],
    "notes_placeholder": "e.g. guest-only episode; the subject is only quoted",
    # A recording counts as verified only when every one of these is true; otherwise
    # it is excluded, and the list marks it so.
    "accept_when_true": ["subject_present", "political_content"],
    "goal": {"count": 5, "help": "recordings verified so far (subject present and political); 5 are needed to rank"},
    "draft_fields": [["subject_present", "subject present"], ["main_speaker", "main speaker"],
                     ["venue", "format"], ["political_content", "political"]],
}

PROJECTS = {
    "insights": {"study": "leaders", "board": "leaders", "transcript_dir": "transcripts_open",
                 "quote_help": "the judges scored them as this person's words", "checklist": None},
    "predictions": {"study": "leaders", "board": "predictions", "transcript_dir": "transcripts_open",
                    "quote_help": "the predictions site credits them to this person", "checklist": None},
    "pundits": {"study": "pundits", "board": None, "transcript_dir": "transcripts",
                "quote_help": "the judges credited them to the subject", "checklist": PUNDITS_CHECKLIST},
}
#: The `study` a version-1 manifest named, as a project. Version 1 used the board name.
LEGACY_STUDY_PROJECT = {"leaders": "insights", "predictions": "predictions"}


def project(name: str) -> dict:
    """A project's settings. An unknown name stops the caller rather than defaulting."""
    if name not in PROJECTS:
        raise SystemExit(f"REFUSING: unknown project {name!r}; known: {sorted(PROJECTS)}")
    return PROJECTS[name]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def card(qid: str, raw: str, toks: list, a: int, z: int, duration) -> dict:
    """One quote in context, in the shape the pundits page renders. `z` is inclusive.

    `t` is where the play link starts, from the shared `play_time`, so this page and
    the pundits page cannot time a quote differently.
    """
    b0 = max(0, a - CONTEXT_WORDS)
    last = min(len(toks) - 1, z + CONTEXT_WORDS)

    def strip(i, j):
        return MARK.sub("", raw[toks[i].start():toks[j].end()]).strip() if j >= i else ""

    return {"qid": qid, "t": play_time(toks, a, duration), "start": b0, "end": last + 1,
            "quote_start": a, "quote_end": z + 1, "before": strip(b0, a - 1), "text": strip(a, z),
            "after": strip(z + 1, last)}


def recording_row(key: str, rec: dict, person: dict, quotes: list[dict]) -> dict:
    if not rec.get("video_id"):
        raise SystemExit(f"REFUSING: {key} has no video_id; the page cannot link the recording to listen to")
    slug, sid = key.split("/", 1)
    return {"key": key, "slug": slug, "sid": sid, "person": person["name"], "role": person.get("role", ""),
            "title": rec.get("yt_title") or rec.get("declared_title") or "", "channel": rec.get("yt_channel") or "",
            "upload": rec.get("yt_upload_date") or "", "video_id": rec["video_id"],
            "duration": rec.get("yt_duration_sec") or rec.get("duration_sec"), "forms": name_forms(person),
            "quotes": quotes}


def take_in_turn(entries: list[dict], cap: int | None) -> list[dict]:
    """Up to `cap` entries, taking each judge's strongest remaining quote in turn.

    Ranking alone would spend the whole cap on one judge whenever that judge carries
    the strongest signal, and then nobody checks what the other judges scored. A tie
    in score is broken by position in the transcript, so the choice is deterministic.
    A quote `locate()` cannot place is never shown; it is counted as `not_located`.
    One known cause: a placeholder with punctuation attached, such as `[COMPANY].`.
    """
    queues = {}
    for e in entries:
        for j in sorted({c["judge"] for c in e["judges"]}):
            queues.setdefault(j, []).append(e)
    for q in queues.values():
        q.sort(key=lambda e: (-e["score"], e["a"]))
    # The most suspect judge goes first in every round, so a cap smaller than the
    # number of judges still reaches it; ties go by name.
    order = sorted(queues, key=lambda j: (-queues[j][0]["score"], j))
    chosen, seen = [], set()
    while any(queues.values()) and (cap is None or len(chosen) < cap):
        for j in order:
            while queues[j] and id(queues[j][0]) in seen:
                queues[j].pop(0)
            if queues[j] and (cap is None or len(chosen) < cap):
                e = queues[j].pop(0)
                seen.add(id(e))
                chosen.append(e)
    return sorted(chosen, key=lambda e: e["a"])


def insights_quotes(key: str, raw: str, grades: list[dict], forms: list[str], cap: int | None, duration):
    """Evidence quotes for one recording, and a report of what was found and cut."""
    toks = list(re.finditer(r"\S+", raw))
    shares = {g["judge"]: g["grade"].get("subject_speech_share_pct") for g in grades}
    known = sorted(v for v in shares.values() if isinstance(v, (int, float)))
    median = known[len(known) // 2] if known else None
    dissent = {j for j, v in shares.items()
               if median is not None and isinstance(v, (int, float)) and abs(v - median) >= DISSENT_POINTS}
    entries, report = {}, {"judges": sorted(shares), "shares": shares, "dissenting_judges": sorted(dissent),
                           "cited": 0, "located": 0, "not_located": 0}
    for g in grades:
        for dim, d in sorted(g["grade"]["dimensions"].items()):
            for e in d.get("evidence") or []:
                q = e.get("quote") or ""
                report["cited"] += 1
                span = locate(q, raw)
                if span is None:
                    report["not_located"] += 1
                    continue
                report["located"] += 1
                a, z = span
                signals = set()
                if g["judge"] in dissent:
                    signals.add("dissenting_judge")
                if any(toks[i].group() == ">>" for i in range(a, z + 1)):
                    signals.add("spans_turn")
                if q.strip().endswith("?"):
                    signals.add("question")
                if "[SUBJECT]" in q or any(re.search(r"\b" + re.escape(f) + r"\b", q, re.I) for f in forms):
                    signals.add("names_subject")
                dedupe = " ".join(_norm(t.group()) for t in toks[a:a + 8])
                entry = entries.setdefault(dedupe, {"a": a, "z": z, "signals": set(), "judges": []})
                entry["signals"] |= signals
                entry["judges"].append({"judge": g["judge"], "mode": g["mode"], "dimension": dim,
                                        "claimed_speaker": "subject", "quote": q, "timestamp": e.get("timestamp")})
    for e in entries.values():
        e["score"] = sum(SIGNAL_WEIGHT[s] for s in e["signals"])
    chosen = take_in_turn(list(entries.values()), cap)
    report.update({"distinct_quotes": len(entries), "shown": len(chosen), "cut_by_cap": len(entries) - len(chosen)})
    slug, sid = key.split("/", 1)
    cards, key_map = [], {}
    for e in chosen:
        qid = f"{slug}:{sid}:{e['a']}"
        cards.append(card(qid, raw, toks, e["a"], e["z"], duration))
        key_map[qid] = {"key": key, "project": "insights", "board": "leaders", "signals": sorted(e["signals"]) or ["recording_selected"],
                        "judges": e["judges"]}
    return cards, key_map, report


def char_span_to_tokens(toks: list, start: int, end: int) -> tuple[int, int]:
    """First and last (inclusive) whitespace tokens overlapping text[start:end]."""
    inside = [i for i, t in enumerate(toks) if t.end() > start and t.start() < end]
    if not inside:
        raise ValueError(f"no word overlaps characters {start}:{end}")
    return inside[0], inside[-1]


def predictions_quotes(key: str, raw: str, records: list[dict], cap: int | None, duration):
    toks = list(re.finditer(r"\S+", raw))
    accepted = [r for r in records if r.get("accepted") is True]
    cards, key_map = [], {}
    for r in sorted(accepted, key=lambda r: r["source"]["quote_char_start"])[:cap]:
        s = r["source"]
        start, end = s["quote_char_start"], s["quote_char_end"]
        if raw[start:end] != s["quote_original"]:
            raise SystemExit(f"REFUSING: prediction {r['prediction_id']} in {key}: text[{start}:{end}] is not "
                             "quote_original, so its offsets do not point into this transcript")
        a, z = char_span_to_tokens(toks, start, end)
        signals = []
        if any(toks[i].group() == ">>" for i in range(a, z + 1)):
            signals.append("spans_turn")
        if any(t.group() == ">>" for t in toks[max(0, a - 12):a] + toks[z + 1:z + 9]):
            signals.append("turn_near_quote")
        if s["quote"].strip().endswith("?"):
            signals.append("question")
        qid = r["prediction_id"]
        cards.append(card(qid, raw, toks, a, z, duration))
        v = r.get("verification") or {}
        key_map[qid] = {"key": key, "project": "predictions", "board": "predictions", "signals": signals or ["recording_selected"],
                        "judges": [{"judge": "extractor", "claimed_speaker": "subject" if r["extraction"]["gates"].get("own_voice") else "not_subject",
                                    "model": r["extraction"].get("served_model"), "notes": r["extraction"].get("gate_notes")},
                                   {"judge": "verifier", "claimed_speaker": v.get("attribution"),
                                    "model": v.get("served_model"), "notes": v.get("notes")}],
                        "prediction_id": qid, "normalized_claim": r["prediction"].get("normalized_claim"),
                        "quote": s["quote"]}
    report = {"accepted": len(accepted), "shown": len(cards), "cut_by_cap": len(accepted) - len(cards),
              "not_accepted_ignored": len(records) - len(accepted)}
    return cards, key_map, report


def suspect_quotes(grades_dir: Path, transcripts_dir: Path, roster: dict) -> tuple[list, dict, dict]:
    """The quotes a judge credited to the subject that are most likely someone else's.

    Signals, strongest first, all mechanical because the judges report no per-quote
    confidence: the quote's span crosses a caption turn mark `>>`; it is a question
    in a conversation or debate, where questions are usually the other voice's; it
    contains the subject's own name or the blinded subject token, which people rarely
    say about themselves. Deduplicated per recording across judges and modes, capped
    at QUOTE_CAP_PER_RECORDING. Returns (page rows, private answer key, report). The
    judge's own label never reaches the page rows.
    """
    by_rec: dict = {}
    report = {"subject_quotes": 0, "located": 0, "not_located": 0, "empty": 0, "flagged": 0}
    raw_cache: dict = {}
    for gp in sorted(Path(grades_dir).glob("*/*/*__r0.json")):
        if "_obsolete" in gp.parts or "_raw" in gp.parts:
            continue
        g = json.loads(gp.read_text())
        body = g.get("grade") or {}
        if g.get("validation_errors") or not isinstance(body.get("dimensions"), dict):
            continue
        slug, sid = g["leader_slug"], g["source_id"]
        person = roster.get(slug)
        if person is None:
            continue
        if (slug, sid) not in raw_cache:
            rp = Path(transcripts_dir) / slug / f"{sid}.json"
            raw_cache[(slug, sid)] = json.loads(rp.read_text()) if rp.exists() else None
        rec = raw_cache[(slug, sid)]
        if rec is None:
            continue
        raw = rec.get("text") or ""
        toks = list(re.finditer(r"\S+", raw))
        forms = name_forms(person)
        for dim, d in body["dimensions"].items():
            for e in d.get("evidence") or []:
                if e.get("speaker") != "subject":
                    continue
                report["subject_quotes"] += 1
                q = e.get("quote") or ""
                if not q.strip():
                    # A judge that cites nothing is not a quote the matcher missed.
                    report["empty"] += 1
                    continue
                span = locate(q, raw)
                if span is None:
                    report["not_located"] += 1
                    continue
                report["located"] += 1
                a, z = span
                signals = []
                if any(toks[i].group() == ">>" for i in range(a, z + 1)):
                    signals.append("spans_turn")
                if q.strip().endswith("?") and body.get("venue_type") in ("conversation", "debate"):
                    signals.append("question_in_conversation")
                if "[SUBJECT]" in q or any(re.search(r"\b" + re.escape(f) + r"\b", q, re.I) for f in forms):
                    signals.append("names_subject")
                if not signals:
                    continue
                dedupe = " ".join(_norm(t.group()) for t in toks[a:a + 8])
                key = f"{slug}/{sid}"
                entry = by_rec.setdefault(key, {}).setdefault(dedupe, {
                    "qid": f"{slug}:{sid}:{a}", "a": a, "z": z, "signals": set(), "judges": []})
                entry["signals"].update(signals)
                entry["judges"].append({"judge": g["judge"], "mode": g["mode"], "dimension": dim,
                                        "label": "subject", "quote": q})
    rows, key_map = [], {}
    for key, quotes in by_rec.items():
        slug, sid = key.split("/", 1)
        rec, person = raw_cache[(slug, sid)], roster[slug]
        raw = rec.get("text") or ""
        toks = list(re.finditer(r"\S+", raw))
        ranked = sorted(quotes.values(), key=lambda q: (-max(SIGNAL_RANK[s] for s in q["signals"]), q["a"]))
        cards = []
        for q in ranked[:QUOTE_CAP_PER_RECORDING]:
            cards.append(card(q["qid"], raw, toks, q["a"], q["z"], rec.get("yt_duration_sec") or rec.get("duration_sec")))
            key_map[q["qid"]] = {"key": key, "project": "pundits", "signals": sorted(q["signals"]), "judges": q["judges"]}
        report["flagged"] += len(cards)
        rows.append(recording_row(key, rec, person, cards))
    rows.sort(key=lambda r: (r["person"].split()[-1], r["person"], r["upload"]))
    return rows, key_map, report


def git_revision(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
