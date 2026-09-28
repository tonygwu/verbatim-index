#!/usr/bin/env python3
"""Build a speaker-check page for the leaders board or the predictions board.

Both boards credit words to a named person. The leaders board scores the evidence
quotes the judges cite, and the rubric requires those to be the subject's own
speech. The predictions board publishes accepted predictions, each a quote the
extractor and the verifier both said the subject spoke. Nothing in a caption track
says who is talking, so each of those is a model's inference about speaker turns.
This page puts a chosen few in front of a person, who marks who actually spoke.

It reuses the pundits speaker-check page (`pundits_verify_page.py`), its local
server (`pundits_verify_serve.py`), its word-range editor and its importers
unchanged. Only the choice of quotes differs:

  leaders      every evidence quote any judge cited in the recording, located in
               `transcripts_open` (the blinded quote's `[SUBJECT]` matches the name
               it replaced). Deduplicated across judges, then capped per recording
               by taking the judges in turn, strongest suspicion first, so every
               judge's reading is checked.
  predictions  every ACCEPTED prediction in the recording, which is what the
               predictions site publishes. Each carries exact character offsets into
               `transcripts_open`; an offset that does not reproduce
               `quote_original` stops the build rather than being searched for.

The person names the recordings with --keys. Choosing them is a judgement and the
page does not pretend otherwise: record why in --reasons.

The review is BLIND. Transcript sidecars are built with no model suggestions, so
every word starts unknown, and no judge, extractor or verifier label reaches the
page. Those claims stay in the private key file that `import-quotes` joins with
the answers. The page carries transcript text, so write it into a private data
checkout and serve it locally; never publish it.

  .venv/bin/python scripts/speaker_audit_page.py build --study leaders \\
      --data ../data --keys marc-benioff/exacttarget-9game7,... \\
      --out data/predictions/_experiments/RUN/leaders/speaker_check.html
  .venv/bin/python scripts/pundits_verify_serve.py --port 5002 \\
      --page data/predictions/_experiments/RUN/leaders/speaker_check.html
  .venv/bin/python scripts/pundits_verify_page.py import-quotes \\
      --export .../human_answers.json --key .../quote_key.json \\
      --page .../speaker_check.html --out .../quote_results.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402
from pundits_speaker_spans import build_transcript, sidecar_path  # noqa: E402
from pundits_verify_page import CONTEXT_WORDS, MARK, locate, name_forms, render_page, _norm  # noqa: E402

STUDIES = ("leaders", "predictions")
DEFAULT_CAP = 6
# A judge whose speech share sits this far from the recording's median read the
# turns differently from the others, so its quotes are the likeliest to be wrong.
DISSENT_POINTS = 25
SIGNAL_WEIGHT = {"dissenting_judge": 4, "spans_turn": 3, "question": 2, "names_subject": 1,
                 "turn_near_quote": 1}
TITLES = {
    "leaders": ("Leaders Speaker Check",
                "Check who said each quote the judges scored as this leader's words. Each answer saves the moment you pick it."),
    "predictions": ("Predictions Speaker Check",
                    "Check who said each prediction the site credits to this person. Each answer saves the moment you pick it."),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mark_before(raw: str, char_pos: int):
    marks = list(MARK.finditer(raw, 0, char_pos))
    if not marks:
        return None
    h, m, s = (int(x) for x in marks[-1].groups())
    return h * 3600 + m * 60 + s


def card(qid: str, raw: str, toks: list, a: int, z: int) -> dict:
    """One quote in context, in the shape the pundits page renders. `z` is inclusive."""
    b0 = max(0, a - CONTEXT_WORDS)
    last = min(len(toks) - 1, z + CONTEXT_WORDS)

    def strip(i, j):
        return MARK.sub("", raw[toks[i].start():toks[j].end()]).strip() if j >= i else ""

    return {"qid": qid, "t": mark_before(raw, toks[a].start()), "start": b0, "end": last + 1,
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


def leaders_quotes(key: str, raw: str, grades: list[dict], forms: list[str], cap: int | None):
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
        cards.append(card(qid, raw, toks, e["a"], e["z"]))
        key_map[qid] = {"key": key, "board": "leaders", "signals": sorted(e["signals"]) or ["recording_selected"],
                        "judges": e["judges"]}
    return cards, key_map, report


def char_span_to_tokens(toks: list, start: int, end: int) -> tuple[int, int]:
    """First and last (inclusive) whitespace tokens overlapping text[start:end]."""
    inside = [i for i, t in enumerate(toks) if t.end() > start and t.start() < end]
    if not inside:
        raise ValueError(f"no word overlaps characters {start}:{end}")
    return inside[0], inside[-1]


def predictions_quotes(key: str, raw: str, records: list[dict], cap: int | None):
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
        cards.append(card(qid, raw, toks, a, z))
        v = r.get("verification") or {}
        key_map[qid] = {"key": key, "board": "predictions", "signals": signals or ["recording_selected"],
                        "judges": [{"judge": "extractor", "claimed_speaker": "subject" if r["extraction"]["gates"].get("own_voice") else "not_subject",
                                    "model": r["extraction"].get("served_model"), "notes": r["extraction"].get("gate_notes")},
                                   {"judge": "verifier", "claimed_speaker": v.get("attribution"),
                                    "model": v.get("served_model"), "notes": v.get("notes")}],
                        "prediction_id": qid, "normalized_claim": r["prediction"].get("normalized_claim"),
                        "quote": s["quote"]}
    report = {"accepted": len(accepted), "shown": len(cards), "cut_by_cap": len(accepted) - len(cards),
              "not_accepted_ignored": len(records) - len(accepted)}
    return cards, key_map, report


def git_revision(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def build(args) -> int:
    data = Path(args.data)
    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    if not keys or len(keys) != len(set(keys)):
        raise SystemExit("REFUSING: --keys must name at least one recording, each once")
    roster = {p["slug"]: p for p in json.loads((data / "roster" / "final.json").read_text())["roster"]}
    reasons = json.loads(Path(args.reasons).read_text()) if args.reasons else {}
    if set(reasons) - set(keys):
        raise SystemExit(f"REFUSING: --reasons names recordings not in --keys: {sorted(set(reasons) - set(keys))}")
    out = Path(args.out)
    rows, key_map, reports, inputs = [], {}, {}, {}
    for key in keys:
        slug, sid = key.split("/", 1)
        if slug not in roster:
            raise SystemExit(f"REFUSING: {slug} is not on the roster")
        tpath = data / "transcripts_open" / slug / f"{sid}.json"
        rec = json.loads(tpath.read_text())
        raw = rec["text"]
        inputs[str(tpath.relative_to(data))] = sha256_file(tpath)
        if args.study == "leaders":
            gpaths = sorted(p for p in (data / "grades").glob(f"*/{slug}/{sid}__*__blinded__r0.json")
                            if not {"_obsolete", "_raw"} & set(p.parts))
            grades = []
            for p in gpaths:
                g = json.loads(p.read_text())
                if g.get("validation_errors") or not isinstance((g.get("grade") or {}).get("dimensions"), dict):
                    continue
                grades.append(g)
                inputs[str(p.relative_to(data))] = sha256_file(p)
            if not grades:
                raise SystemExit(f"REFUSING: {key} has no valid blinded grade")
            quotes, kmap, rep = leaders_quotes(key, raw, grades, name_forms(roster[slug]), args.cap)
        else:
            ppath = data / "predictions" / slug / f"{sid}.jsonl"
            records = [json.loads(line) for line in ppath.read_text().splitlines() if line.strip()]
            inputs[str(ppath.relative_to(data))] = sha256_file(ppath)
            quotes, kmap, rep = predictions_quotes(key, raw, records, args.cap)
        if not quotes:
            raise SystemExit(f"REFUSING: {key} yields no quote to check ({rep})")
        rows.append(recording_row(key, rec, roster[slug], quotes))
        key_map.update(kmap)
        reports[key] = {**rep, "reason_selected": reasons.get(key)}
        # No grades are passed, so the editor shows no model suggestion: a blind review.
        transcript = build_transcript(key, raw, [])
        write_atomic(sidecar_path(out, key), json.dumps(transcript, ensure_ascii=False))
        reports[key]["text_sha256"] = transcript["text_sha256"]
    transcript_index = {r["key"]: {"text_sha256": reports[r["key"]]["text_sha256"],
                                   "token_count": len(re.findall(r"\S+", json.loads(
                                       (data / "transcripts_open" / (r["key"] + ".json")).read_text())["text"]))}
                        for r in rows}
    payload = json.dumps({"rows": [], "quote_rows": rows, "venues": [], "transcript_index": transcript_index},
                         ensure_ascii=False).replace("</", "<\\/")
    title, subtitle = TITLES[args.study]
    page = render_page(payload, title, subtitle)
    write_atomic(out.with_name("quote_key.json"), json.dumps(key_map, indent=1, ensure_ascii=False) + "\n")
    manifest = {"schema_version": 1, "study": args.study, "cap_per_recording": args.cap,
                "data_revision": git_revision(data), "code_revision": git_revision(Path(__file__).parent),
                "inputs_sha256": inputs, "recordings": reports,
                "blind": "no model suggestion or claimed speaker is on the page; see quote_key.json"}
    write_atomic(out.with_name("manifest.json"), json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    write_atomic(out, page)
    shown = sum(len(r["quotes"]) for r in rows)
    print(f"wrote {out}: {len(rows)} recordings, {shown} quotes to attribute; {len(page) / 1024:.0f} KB")
    for key, rep in reports.items():
        print(f"  {key}: {({k: v for k, v in rep.items() if k not in ('reason_selected', 'text_sha256')})}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--study", required=True, choices=STUDIES)
    b.add_argument("--data", required=True, help="private data checkout to read, e.g. ../data")
    b.add_argument("--keys", required=True, help="comma-separated slug/source_id recordings")
    b.add_argument("--out", required=True, help="page path inside a private data checkout")
    b.add_argument("--reasons", help="JSON {key: why it was chosen}, recorded in manifest.json")
    b.add_argument("--cap", type=int, default=DEFAULT_CAP, help=f"quotes per recording (default {DEFAULT_CAP})")
    args = ap.parse_args()
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
