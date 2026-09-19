#!/usr/bin/env python3
"""Build the speaker-check page a person uses to label P6 recordings.

Pundits plan, P6: discovery proves who UPLOADED a video, not who speaks in it, so a
person labels every recording before it is graded. `pundits_pilot.py precheck`
writes the checklist of recordings that need a person; this turns it into one
self-contained page with, for each recording, a YouTube link, the description
(which usually names the guest), and three transcript excerpts with the subject's
name highlighted and a link to the matching moment in the video.

Labels are NOT stored in the page. The page declares the Artifact `db` capability
and writes one document per recording to the `labels` collection, keyed
`<slug>:<source_id>`, carrying exactly the fields `pundits_pilot.py report`
reads: subject_present, venue, political_content, checked_by, notes.
`pundits_verify_page.py import` turns an export of that collection into the
human_labels.json shape.

The page holds transcript text, so it is written into the PRIVATE data checkout
and never into this repository. No lean label is read or written.

  pundits_verify_page.py build  --checklist data-pundits/logs/p6b/human_checklist.json \\
      --transcripts data-pundits/transcripts --roster data-pundits/roster/final.json \\
      --out data-pundits/logs/p6b/speaker_check.html
  pundits_verify_page.py import --export labels_export.json \\
      --checklist data-pundits/logs/p6b/human_checklist.json \\
      --out data-pundits/logs/p6b/human_labels.json

QUOTE CHECK. With `--grades` and `--quote-key`, build also flags evidence quotes the
judges credited to the subject that are most likely someone else's (see
`suspect_quotes`), shows each in context on a second tab, and writes the judges'
labels to the private key file only. `import-quotes` joins the operator's answers
with that key. The sample is chosen for being suspect, so its rates describe flagged
quotes only and cannot stand in for the P7 random quote audit.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VENUES = ("solo", "reaction", "conversation", "debate", "speech")
EXCERPT_AT = (0.12, 0.50, 0.85)
EXCERPT_WORDS = 130
MARK = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]")


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
        out.append({"at": frac, "t": secs, "text": MARK.sub("", chunk).strip()})
    return out


CONTEXT_WORDS = 35
QUOTE_CAP_PER_RECORDING = 4
WILDCARD = {"[subject]", "[company]"}
SIGNAL_RANK = {"spans_turn": 3, "question_in_conversation": 2, "names_subject": 1}


def _norm(tok: str) -> str:
    t = tok.lower()
    if t in WILDCARD or t == ">>":
        return t
    return re.sub(r"[^\w']", "", t)


def locate(quote: str, raw: str):
    """Find a judge's quote in the raw transcript; returns (first, last) raw token indices or None.

    Matching is on normalized words. `[SUBJECT]` and `[COMPANY]` in a quote taken from
    blinded text stand for the one to three raw words of the name they replaced, at any
    position. An elided quote ("...") is matched on its longest piece. Caption turn marks
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
            for n in (1, 2, 3):
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
        for back in range(lead, 3 * lead + 1):
            st = s0 - back
            if st < 0:
                break
            end = match(0, st)
            if end is not None:
                return words[st][0], words[end - 1][0]
    return None


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
    report = {"subject_quotes": 0, "located": 0, "not_located": 0, "flagged": 0}
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
            a, z = q["a"], q["z"]
            b0 = max(0, a - CONTEXT_WORDS)
            marks = list(MARK.finditer(raw, 0, toks[a].start()))
            t = None
            if marks:
                h, m, s_ = (int(x) for x in marks[-1].groups())
                t = h * 3600 + m * 60 + s_
            strip = lambda i, j: MARK.sub("", raw[toks[i].start():toks[j].end()]).strip() if j >= i else ""
            cards.append({"qid": q["qid"], "t": t, "before": strip(b0, a - 1),
                          "text": strip(a, z), "after": strip(z + 1, min(len(toks) - 1, z + CONTEXT_WORDS))})
            key_map[q["qid"]] = {"key": key, "signals": sorted(q["signals"]), "judges": q["judges"]}
        report["flagged"] += len(cards)
        rows.append({"key": key, "slug": slug, "sid": sid, "person": person["name"],
                     "role": person.get("role", ""), "title": rec.get("yt_title") or "",
                     "channel": rec.get("yt_channel") or "", "upload": rec.get("yt_upload_date") or "",
                     "video_id": rec.get("video_id"), "duration": rec.get("yt_duration_sec") or rec.get("duration_sec"),
                     "forms": name_forms(person), "quotes": cards})
    rows.sort(key=lambda r: (r["person"].split()[-1], r["person"], r["upload"]))
    return rows, key_map, report


def build(args) -> int:
    checklist = json.loads(Path(args.checklist).read_text())
    roster = {p["slug"]: p for p in json.loads(Path(args.roster).read_text())["roster"]}
    rows = []
    for key, row in checklist.items():
        slug, sid = key.split("/", 1)
        person = roster[slug]
        rec = json.loads((Path(args.transcripts) / slug / f"{sid}.json").read_text())
        text = rec.get("text") or ""
        forms = name_forms(person)
        mentions = sum(len(re.findall(r"\b" + re.escape(f) + r"\b", text, re.I)) for f in forms[:1] + forms[2:])
        rows.append({
            "key": key, "slug": slug, "sid": sid,
            "person": person["name"], "role": person.get("role", ""),
            "title": row.get("title") or rec.get("yt_title") or "",
            "channel": row.get("channel") or rec.get("yt_channel") or "",
            "upload": row.get("upload") or rec.get("yt_upload_date") or "",
            "url": row.get("url") or rec.get("url"),
            "video_id": rec.get("video_id"),
            "duration": rec.get("yt_duration_sec") or rec.get("duration_sec"),
            "words": rec.get("word_count"),
            "hints": [h for h in row.get("hints", []) if not h.startswith("passes automatic checks")],
            "description": (rec.get("yt_description") or "")[:700],
            "forms": forms,
            "mentions": mentions,
            "excerpts": excerpts(text),
        })
    rows.sort(key=lambda r: (r["person"].split()[-1], r["person"], r["upload"]))
    quote_rows, key_map, qrep = ([], {}, {})
    if args.grades:
        quote_rows, key_map, qrep = suspect_quotes(Path(args.grades), Path(args.transcripts), roster)
        # The judges' own labels stay out of the page; the key sits beside it in the
        # private checkout and is joined only at import.
        Path(args.quote_key).write_text(json.dumps(key_map, indent=1, ensure_ascii=False) + "\n")
    data = json.dumps({"rows": rows, "quote_rows": quote_rows, "venues": VENUES},
                      ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("/*__DATA__*/null", data)
    Path(args.out).write_text(page)
    print(f"wrote {args.out}: {len(rows)} recordings to speaker-check, {len({r['slug'] for r in rows})} people; "
          f"{sum(len(r['quotes']) for r in quote_rows)} quotes to attribute across {len(quote_rows)} recordings; "
          f"{len(page) / 1024:.0f} KB")
    if qrep:
        print(f"quote scan: {qrep}")
    return 0


def to_labels(docs: list[dict], checklist: dict) -> dict:
    """The human_labels.json shape `pundits_pilot.py report` reads, from db documents.

    Refuses a document whose key is not on the checklist, and reports rather than
    guesses a missing field: a partly labelled recording is left out, not filled.
    """
    out, partial, unknown = {}, [], []
    for d in docs:
        key = d.get("key")
        if key not in checklist:
            unknown.append(key)
            continue
        # report needs all three for every recording, excluded ones included.
        if not isinstance(d.get("subject_present"), bool) or not isinstance(d.get("political_content"), bool) \
                or d.get("venue") not in VENUES:
            partial.append(key)
            continue
        out[key] = {"subject_present": d["subject_present"], "venue": d.get("venue"),
                    "political_content": d["political_content"],
                    "checked_by": d.get("checked_by") or "operator", "notes": d.get("notes") or ""}
    if unknown:
        raise SystemExit(f"REFUSING: {len(unknown)} labels name recordings not on the checklist, e.g. {unknown[:3]}")
    return {"labels": out, "partial": sorted(partial), "unlabelled": sorted(set(checklist) - set(out) - set(partial))}


def do_import(args) -> int:
    checklist = json.loads(Path(args.checklist).read_text())
    raw = json.loads(Path(args.export).read_text())
    docs = raw if isinstance(raw, list) else [dict(v, key=v.get("key", k)) for k, v in raw.items()]
    res = to_labels(docs, checklist)
    Path(args.out).write_text(json.dumps(res["labels"], indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}: {len(res['labels'])} complete labels; "
          f"{len(res['partial'])} partly labelled (left out); {len(res['unlabelled'])} not yet labelled")
    return 0


ANSWERS = ("subject", "other", "both", "unclear")


def join_quotes(docs: list[dict], key_map: dict) -> dict:
    """Join the operator's quote answers with the judges' labels kept out of the page.

    Every flagged quote carries the judge label `subject`, so an answer of `other` or
    `both` is a misattribution the judge made. The rate is reported PER SIGNAL and is
    a rate among FLAGGED quotes only: the sample was chosen for being suspect, so it
    says nothing about how often the judges are wrong across all quotes.
    """
    out, unknown, bad = {}, [], []
    for d in docs:
        qid = d.get("qid")
        if qid not in key_map:
            unknown.append(qid)
            continue
        if d.get("answer") not in ANSWERS:
            bad.append(qid)
            continue
        out[qid] = {**key_map[qid], "answer": d["answer"], "notes": d.get("notes") or "",
                    "checked_by": d.get("checked_by") or "operator"}
    if unknown:
        raise SystemExit(f"REFUSING: {len(unknown)} answers name quotes not in the key, e.g. {unknown[:3]}")
    by_signal: dict = {}
    for r in out.values():
        for sig in r["signals"]:
            t = by_signal.setdefault(sig, {a: 0 for a in ANSWERS})
            t[r["answer"]] += 1
    tally = {a: sum(1 for r in out.values() if r["answer"] == a) for a in ANSWERS}
    return {"answers": out, "tally": tally, "by_signal": by_signal,
            "unanswered": sorted(set(key_map) - set(out)), "invalid": sorted(bad),
            "note": "Rates are among quotes FLAGGED as suspect, not across all quotes."}


def do_import_quotes(args) -> int:
    key_map = json.loads(Path(args.key).read_text())
    raw = json.loads(Path(args.export).read_text())
    docs = raw if isinstance(raw, list) else [dict(v, qid=v.get("qid", k)) for k, v in raw.items()]
    res = join_quotes(docs, key_map)
    Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}: {sum(res['tally'].values())} answered of {len(key_map)} flagged; "
          f"{res['tally']}; {len(res['invalid'])} invalid")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    for a in ("--checklist", "--transcripts", "--roster", "--out"):
        b.add_argument(a, required=True)
    b.add_argument("--grades", default=None, help="graded corpus to draw suspect quotes from")
    b.add_argument("--quote-key", default=None, help="private file for the judges' labels of those quotes")
    i = sub.add_parser("import")
    for a in ("--export", "--checklist", "--out"):
        i.add_argument(a, required=True)
    q = sub.add_parser("import-quotes")
    for a in ("--export", "--key", "--out"):
        q.add_argument(a, required=True)
    args = ap.parse_args()
    return {"build": build, "import": do_import, "import-quotes": do_import_quotes}[args.cmd](args)


TEMPLATE = r"""<title>Pundit Speaker Check</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
 --ground:#F4F4F2;--surface:#FDFDFC;--surface2:#EAEAE6;--ink:#17191C;--ink2:#3E434A;--muted:#5D646C;--faint:#8C939B;
 --rule:#DEDEDA;--rule2:#C4C5BF;--accent:#1F6FB2;--accentbg:#1F6FB21F;--yes:#0F766E;--yesbg:#0F766E1A;--no:#A33A2A;--nobg:#A33A2A14;
 --warn:#8A6100;--warnbg:#8A61001A;--mark:#F2D98A;--markink:#17191C;
 --serif:"Newsreader",Georgia,serif;--sans:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --ground:#121316;--surface:#1A1C20;--surface2:#23262B;--ink:#EAECEF;--ink2:#C2C7CE;--muted:#989FA8;--faint:#6C737B;
 --rule:#2B2F35;--rule2:#3A3F47;--accent:#5EA3DE;--accentbg:#5EA3DE22;--yes:#35A08F;--yesbg:#35A08F22;--no:#E08876;--nobg:#E0887622;
 --warn:#D9A441;--warnbg:#D9A44122;--mark:#6B5A1F;--markink:#F5EFD8;}}
:root[data-theme="dark"]{
 --ground:#121316;--surface:#1A1C20;--surface2:#23262B;--ink:#EAECEF;--ink2:#C2C7CE;--muted:#989FA8;--faint:#6C737B;
 --rule:#2B2F35;--rule2:#3A3F47;--accent:#5EA3DE;--accentbg:#5EA3DE22;--yes:#35A08F;--yesbg:#35A08F22;--no:#E08876;--nobg:#E0887622;
 --warn:#D9A441;--warnbg:#D9A44122;--mark:#6B5A1F;--markink:#F5EFD8;}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:14.5px;line-height:1.5;margin:0;padding-inline:16px;padding-block:16px 40px}
.app{max-width:1280px;margin:0 auto;display:grid;gap:14px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 20px;justify-content:space-between}
h1{font-family:var(--serif);font-weight:400;font-size:1.7rem;margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:.85rem}
.meter{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:.8rem;color:var(--ink2)}
.meter .bar{width:180px;max-width:40vw;height:6px;background:var(--surface2);border-radius:3px;overflow:hidden}
.meter .bar i{display:block;height:100%;background:var(--accent)}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.seg{display:inline-flex;border:1px solid var(--rule2);border-radius:7px;overflow:hidden}
.seg button{appearance:none;border:0;background:transparent;color:var(--ink2);font:500 .8rem var(--sans);padding:5px 11px;cursor:pointer}
.seg button+button{border-left:1px solid var(--rule2)}
.seg button[aria-pressed="true"]{background:var(--accentbg);color:var(--accent)}
.banner{border:1px solid var(--warn);background:var(--warnbg);border-radius:8px;padding:10px 14px;font-size:.88rem}
.main{display:grid;grid-template-columns:320px minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:860px){.main{grid-template-columns:1fr}.list{max-height:34vh}}
.list{background:var(--surface);border:1px solid var(--rule);border-radius:10px;max-height:calc(100vh - 150px);overflow:auto;position:sticky;top:env(safe-area-inset-top,0px)}
.grp{position:sticky;top:0;background:var(--surface2);padding:6px 12px;font-size:.78rem;display:flex;justify-content:space-between;gap:8px;z-index:1}
.grp b{font-weight:600}
.grp span{font-family:var(--mono);color:var(--muted);font-variant-numeric:tabular-nums}
.grp span.ok{color:var(--yes)}
.item{display:flex;gap:9px;align-items:flex-start;padding:7px 12px;border-top:1px solid var(--rule);cursor:pointer;font-size:.82rem;color:var(--ink2)}
.item:hover{background:var(--accentbg)}
.item[aria-current="true"]{background:var(--accentbg);color:var(--ink);box-shadow:inset 3px 0 0 var(--accent)}
.dot{flex:none;width:9px;height:9px;border-radius:50%;margin-top:5px;border:1.5px solid var(--rule2)}
.dot.done{background:var(--yes);border-color:var(--yes)}
.dot.rej{background:var(--no);border-color:var(--no)}
.dot.part{background:var(--warn);border-color:var(--warn)}
.item .t{overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.detail{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:18px 20px;display:grid;gap:16px;min-width:0}
.who{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:baseline}
.who h2{font-family:var(--serif);font-weight:400;font-size:1.45rem;margin:0}
.who .role{color:var(--muted);font-size:.85rem}
.title{font-size:1.02rem;font-weight:500;margin:0;text-wrap:balance}
.facts{display:flex;flex-wrap:wrap;gap:4px 16px;font-family:var(--mono);font-size:.76rem;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:.76rem;border-radius:999px;padding:2px 10px;border:1px solid var(--warn);background:var(--warnbg);color:var(--ink)}
.chip.info{border-color:var(--rule2);background:var(--surface2)}
a.yt{display:inline-flex;align-items:center;gap:6px;font-weight:500;color:var(--accent);text-decoration:none;border:1px solid var(--accent);border-radius:7px;padding:5px 12px;font-size:.85rem;width:fit-content}
a.yt:hover{background:var(--accentbg)}
details.desc{font-size:.85rem;color:var(--ink2)}
details.desc summary{cursor:pointer;color:var(--muted);font-size:.8rem}
details.desc p{white-space:pre-wrap;margin:.4em 0 0;max-width:80ch}
.ex{display:grid;gap:10px}
.ex article{border-left:2px solid var(--rule2);padding:2px 0 2px 12px;font-size:.88rem;color:var(--ink2);max-width:90ch}
.ex .at{font-family:var(--mono);font-size:.72rem;color:var(--faint);display:flex;gap:10px;margin-bottom:3px}
.ex .at a{color:var(--accent);text-decoration:none}
mark{background:var(--mark);color:var(--markink);border-radius:2px;padding:0 1px}
.turn{color:var(--faint);font-family:var(--mono);font-size:.75rem}
.form{border-top:1px solid var(--rule);padding-top:14px;display:grid;gap:12px}
.q{display:grid;grid-template-columns:150px minmax(0,1fr);gap:8px 14px;align-items:center}
@media (max-width:560px){.q{grid-template-columns:1fr}}
.q label.l{font-size:.85rem;font-weight:600}
.q label.l small{display:block;font-weight:400;color:var(--muted);font-size:.74rem}
.opts{display:flex;flex-wrap:wrap;gap:6px}
.opt{appearance:none;border:1px solid var(--rule2);background:var(--surface);color:var(--ink);border-radius:7px;padding:6px 12px;font:500 .83rem var(--sans);cursor:pointer;display:inline-flex;gap:7px;align-items:center}
.opt kbd{font-family:var(--mono);font-size:.7rem;color:var(--faint);border:1px solid var(--rule);border-radius:4px;padding:0 4px}
.opt[aria-pressed="true"]{border-color:var(--accent);background:var(--accentbg);color:var(--accent)}
.opt.y[aria-pressed="true"]{border-color:var(--yes);background:var(--yesbg);color:var(--yes)}
.opt.n[aria-pressed="true"]{border-color:var(--no);background:var(--nobg);color:var(--no)}
.opt:disabled{opacity:.45;cursor:not-allowed}
textarea{width:100%;min-height:54px;resize:vertical;border:1px solid var(--rule2);border-radius:7px;background:var(--surface);color:var(--ink);font:inherit;padding:7px 9px}
.foot{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;justify-content:space-between}
.nav{display:flex;gap:6px}
.status{font-family:var(--mono);font-size:.76rem;color:var(--muted)}
.status.err{color:var(--no)}
.keys{font-size:.74rem;color:var(--faint)}
button:focus-visible,a:focus-visible,textarea:focus-visible,.item:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.def{font-size:.74rem;color:var(--muted);max-width:80ch}
.qcard{border:1px solid var(--rule2);border-radius:9px;padding:12px 14px;font-size:.9rem;line-height:1.6;color:var(--muted);max-width:92ch}
.qcard .q{display:inline;color:var(--ink);background:var(--accentbg);box-shadow:0 0 0 2px var(--accentbg);border-radius:3px}
.qhelp{font-size:.8rem;color:var(--muted);max-width:80ch}
.qblock{display:grid;gap:10px;border-top:1px solid var(--rule);padding-top:14px}
.qitem{display:grid;gap:8px;padding:10px 12px;border:1px solid var(--rule);border-radius:9px}
.qitem[data-focus="true"]{border-color:var(--accent);box-shadow:0 0 0 3px var(--accentbg)}
.qitem .hd{display:flex;justify-content:space-between;gap:10px;font-family:var(--mono);font-size:.72rem;color:var(--faint)}
.qitem .hd a{color:var(--accent);text-decoration:none}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
<div class="app">
 <header>
  <div>
   <h1>Pundit Speaker Check</h1>
   <div class="sub">Confirm who is speaking before a recording is graded. Each answer saves the moment you pick it.</div>
  </div>
  <div class="meter"><span id="count"></span><span class="bar"><i id="bar"></i></span></div>
 </header>
 <div id="banner" class="banner" hidden></div>
 <div class="toolbar">
  <div class="seg" role="group" aria-label="Show">
   <button type="button" id="f-todo" aria-pressed="true">To do</button>
   <button type="button" id="f-all" aria-pressed="false">All</button>
   <button type="button" id="f-done" aria-pressed="false">Done</button>
  </div>
  <span class="keys" id="legend"></span>
  <span class="keys" id="keyhelp"></span>
 </div>
 <div class="main">
  <nav class="list" id="list" aria-label="Recordings"></nav>
  <section class="detail" id="detail" aria-live="polite"></section>
 </div>
</div>
<script>
const D = /*__DATA__*/null;
const VENUE_DEF = {
 solo:"The subject talks to the audience with no other live voice, including covering news stories.",
 reaction:"The subject plays other material and comments on it, with no other live voice.",
 conversation:"Other live voices talk with the subject, whoever hosts: interviews either way round, panels, co-hosted shows, TV segments.",
 debate:"Organised opposing sides with at least one named opponent, usually with a moderator or turns.",
 speech:"A prepared talk to a live audience, with or without questions afterwards."};
const ANSWERS = [["subject","The subject","s","y"],["other","Someone else","e","n"],["both","Both: it spans two speakers","b","n"],["unclear","Can't tell","u",""]];
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const el = id => document.getElementById(id);

// ONE item per recording. A recording may need the three questions, a set of quote
// attributions, or both — everything about it is answered on one screen, so a video
// is never opened twice.
const REC = {};
for(const r of D.rows) REC[r.key] = {...r, ask:true, quotes:[]};
for(const r of (D.quote_rows||[])){
 const x = REC[r.key] ||= {...r, ask:false, hints:[], excerpts:[], description:"", mentions:null};
 x.quotes = r.quotes; if(!x.title) Object.assign(x, {title:r.title, channel:r.channel, upload:r.upload, video_id:r.video_id, duration:r.duration, forms:r.forms, person:r.person, role:r.role});
}
const recs = Object.values(REC).sort((a,b)=>(a.person.split(" ").pop()+a.person+a.upload).localeCompare(b.person.split(" ").pop()+b.person+b.upload));
let filter="todo", cur=recs.length?recs[0].key:null, focusQ=0;
let labels={}, attrib={}, db=null, writable=true;

const askDone = r => {const l=labels[r.key]||{}; return !r.ask || (typeof l.subject_present==="boolean" && typeof l.political_content==="boolean" && D.venues.includes(l.venue));};
const quotesDone = r => r.quotes.every(c=>!!(attrib[c.qid]||{}).answer);
const complete = r => askDone(r) && quotesDone(r);
function recState(r){
 if(complete(r)){
  const l=labels[r.key]||{};
  if(r.ask && !(l.subject_present && l.political_content)) return "rej";
  if(r.quotes.some(c=>["other","both"].includes((attrib[c.qid]||{}).answer))) return "rej";
  return "done";}
 return (labels[r.key]||r.quotes.some(c=>(attrib[c.qid]||{}).answer)) ? "part" : "todo";}
const outstanding = r => (r.ask && !askDone(r) ? 1 : 0) + r.quotes.filter(c=>!(attrib[c.qid]||{}).answer).length;

function fmtT(s){if(s==null)return "";const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+":"+String(m).padStart(2,"0"):m)+":"+String(x).padStart(2,"0");}
function fmtDate(d){return d&&d.length===8?`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`:"unknown";}
function highlight(text, forms){let h=esc(text).replace(/&gt;&gt;/g,'<span class="turn">⟩⟩ </span>');
 const sorted=[...(forms||[])].sort((a,b)=>b.length-a.length).map(f=>f.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));
 if(!sorted.length) return h; return h.replace(new RegExp("\\b("+sorted.join("|")+")\\b","gi"),"<mark>$1</mark>");}
const visible = () => recs.filter(r=> filter==="all" || (filter==="todo" ? !complete(r) : complete(r)));
const curRec = () => REC[cur];

function renderList(){
 const vis=visible(), groups={}, per={};
 for(const r of vis)(groups[r.person] ||= []).push(r);
 for(const r of recs){const p=(per[r.person] ||= {n:0,ok:0,q:0}); p.n++; if(r.ask&&recState(r)==="done") p.ok++; p.q+=r.quotes.length;}
 let h="";
 for(const [person,rs] of Object.entries(groups)){
  const p=per[person];
  h+=`<div class="grp"><b>${esc(person)}</b><span class="${p.ok>=5?"ok":""}" title="recordings verified so far (subject present and political); 5 are needed to rank">${p.ok} verified of ${p.n}${p.q?` · ${p.q} quotes`:""}</span></div>`;
  for(const r of rs){
   const left=outstanding(r);
   h+=`<div class="item" tabindex="0" data-k="${esc(r.key)}" aria-current="${r.key===cur}"><span class="dot ${recState(r)}"></span><span class="t">${esc(r.title)}${r.quotes.length?` <span class="turn">· ${r.quotes.length} quote${r.quotes.length>1?"s":""}</span>`:""}</span></div>`;}
 }
 el("list").innerHTML = h || `<div class="item">Nothing here. ${filter==="todo"?"Everything has an answer.":""}</div>`;
 const done=recs.filter(complete).length, q=recs.reduce((n,r)=>n+r.quotes.length,0);
 el("count").textContent=`${done} of ${recs.length} recordings checked${q?` · ${recs.reduce((n,r)=>n+r.quotes.filter(c=>(attrib[c.qid]||{}).answer).length,0)} of ${q} quotes`:""}`;
 el("bar").style.width=(100*done/(recs.length||1)).toFixed(1)+"%";}

function opt(store, id, field, value, label, key, cls=""){
 const on=(store[id]||{})[field]===value;
 return `<button type="button" class="opt ${cls}" data-store="${store===labels?"l":"a"}" data-id="${esc(id)}" data-f="${field}" data-v='${JSON.stringify(value)}' aria-pressed="${on}" ${writable?"":"disabled"}>${esc(label)} <kbd>${key}</kbd></button>`;}

function renderDetail(){
 const r=curRec();
 if(!r){el("detail").innerHTML='<p class="sub">Pick a recording on the left.</p>';return;}
 const l=labels[r.key]||{}, start=r.duration?Math.floor(r.duration*0.2):0;
 const hints=(r.hints||[]).map(h=>`<span class="chip">${esc(h)}</span>`).join("")
  + (r.mentions!=null?`<span class="chip info">${r.mentions} mention${r.mentions===1?"":"s"} of the name in the transcript</span>`:"");
 const ex=(r.excerpts||[]).map(e=>`<article><div class="at"><span>${Math.round(e.at*100)}% in</span>${e.t!=null?`<a href="https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${e.t}s" target="_blank" rel="noopener">play from ${fmtT(e.t)}</a>`:""}</div>${highlight(e.text,r.forms)}</article>`).join("");
 const ask = r.ask ? `
   <div class="q"><label class="l">1 · Subject present<small>Takes part live; a played clip is not presence</small></label><div class="opts">${opt(labels,r.key,"subject_present",true,"Yes","y","y")}${opt(labels,r.key,"subject_present",false,"No","n","n")}</div></div>
   <div class="q"><label class="l">2 · Format<small>of this recording</small></label><div class="opts">${D.venues.map((v,i)=>opt(labels,r.key,"venue",v,v,i+1)).join("")}</div></div>
   <div class="q"><span></span><div class="def">${l.venue?esc(VENUE_DEF[l.venue]):"Pick the format that fills most of the recording."}</div></div>
   <div class="q"><label class="l">3 · Political content<small>politics, policy, news or public controversy</small></label><div class="opts">${opt(labels,r.key,"political_content",true,"Yes","p","y")}${opt(labels,r.key,"political_content",false,"No","o","n")}</div></div>
   <div class="q"><label class="l" for="notes">Notes<small>optional</small></label><textarea id="notes" ${writable?"":"disabled"} placeholder="e.g. guest-only episode; the subject is only quoted">${esc(l.notes||"")}</textarea></div>` : "";
 const quotes = r.quotes.length ? `
  <div class="qblock">
   <div class="q"><label class="l">${r.ask?"4 · ":""}Who says these lines?<small>the judges credited them to the subject</small></label>
    <div class="qhelp">The highlighted words are the quote; grey text is context. If the transcript can't settle it, play the moment.</div></div>
   ${r.quotes.map((c,i)=>`<div class="qitem" data-q="${i}" data-focus="${i===focusQ}">
     <div class="hd"><span>quote ${i+1} of ${r.quotes.length}</span>${c.t!=null?`<a href="https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${c.t}s" target="_blank" rel="noopener">play from ${fmtT(c.t)}</a>`:""}</div>
     <div class="qcard">${highlight(c.before,r.forms)} <span class="q">${highlight(c.text,r.forms)}</span> ${highlight(c.after,r.forms)}</div>
     <div class="opts">${ANSWERS.map(([v,lab,k,cls])=>opt(attrib,c.qid,"answer",v,lab,k,cls)).join("")}</div>
    </div>`).join("")}
  </div>` : "";
 el("detail").innerHTML=`
  <div class="who"><h2>${esc(r.person)}</h2><span class="role">${esc(r.role||"")}</span></div>
  <p class="title">${esc(r.title)}</p>
  <div class="facts"><span>${esc(r.channel||"")}</span><span>uploaded ${fmtDate(r.upload)}</span><span>${r.duration?Math.round(r.duration/60)+" min":""}</span>${r.words?`<span>${r.words.toLocaleString()} words</span>`:""}</div>
  ${hints?`<div class="chips">${hints}</div>`:""}
  <a class="yt" id="yt" href="https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${start}s" target="_blank" rel="noopener">Open on YouTube at ${fmtT(start)} ↗</a>
  ${r.description?`<details class="desc"><summary>Video description</summary><p>${esc(r.description)}</p></details>`:""}
  ${ex?`<div class="ex">${ex}</div>`:""}
  <div class="form">${ask}${quotes}
   <div class="foot"><div class="nav"><button type="button" class="opt" id="prev">Previous <kbd>k</kbd></button><button type="button" class="opt" id="next">Next <kbd>j</kbd></button></div><span class="status" id="status"></span></div>
  </div>`;
 el("status").textContent = complete(r) ? "All answered" : `${outstanding(r)} left on this recording`;
 el("detail").querySelectorAll("button[data-f]").forEach(b=>b.onclick=()=>{
  const store = b.dataset.store==="l" ? labels : attrib;
  if(b.dataset.store==="a"){const i=+b.closest(".qitem").dataset.q; focusQ=i;}
  setField(store, b.dataset.id, b.dataset.f, JSON.parse(b.dataset.v));});
 el("detail").querySelectorAll(".qitem").forEach(n=>n.onclick=e=>{ if(!e.target.closest("button")){focusQ=+n.dataset.q; renderDetail();} });
 el("prev").onclick=()=>step(-1); el("next").onclick=()=>step(1);
 const ta=el("notes"); if(ta){let tm; ta.oninput=()=>{clearTimeout(tm); tm=setTimeout(()=>setField(labels,r.key,"notes",ta.value,true),700);};}}

function select(k){cur=k; focusQ=firstOpenQuote(REC[k]); renderList(); renderDetail();
 const n=el("list").querySelector(`[data-k="${CSS.escape(k)}"]`); n&&n.scrollIntoView({block:"nearest"});}
function firstOpenQuote(r){const i=r.quotes.findIndex(c=>!(attrib[c.qid]||{}).answer); return i<0?0:i;}
function step(d){const vis=visible(), order=vis.length?vis:recs; let i=order.findIndex(r=>r.key===cur);
 if(i<0) i = d>0 ? -1 : order.length; const n=order[Math.min(Math.max(i+d,0),order.length-1)]; n&&select(n.key);}

const queue={};
function setField(store, id, f, v, quiet){
 if(!writable) return;
 const isQuote = store===attrib;
 const base = isQuote ? {qid:id, key:cur} : {key:id};
 const next={...(store[id]||{}), ...base, [f]:v, checked_by:"operator", updated_at:new Date().toISOString()};
 store[id]=next;
 const r=curRec();
 if(!quiet){ if(isQuote && f==="answer"){const nx=firstOpenQuote(r); focusQ = nx; } renderList(); renderDetail(); }
 const st=el("status"); st&&(st.textContent="Saving…", st.className="status");
 const ref = isQuote ? db.collection("attribution").doc(id) : db.collection("labels").doc(id.replace("/",":"));
 queue[id]=(queue[id]||Promise.resolve()).then(()=>ref.set(next)).then(()=>{
   if(el("status")&&cur===(isQuote?next.key:id)) el("status").textContent = complete(curRec()) ? "All answered" : `${outstanding(curRec())} left on this recording`;
 }).catch(e=>{
   if(e&&e.code==="invalid_argument") writable=false;
   if(el("status")){el("status").textContent="Not saved: "+(e&&e.message||e)+". Reload the page and try again."; el("status").className="status err";}
 });
 if(!quiet && f!=="notes" && complete(r)) setTimeout(()=>{ if(cur===r.key) step(1); }, 250);}

document.addEventListener("keydown", e=>{
 if(e.target.tagName==="TEXTAREA"){ if(e.key==="Escape") e.target.blur(); return; }
 if(e.metaKey||e.ctrlKey||e.altKey) return;
 const r=curRec(); if(!r) return;
 const k=e.key.toLowerCase();
 if(k==="j"||k==="arrowdown"){step(1);e.preventDefault();return;}
 if(k==="k"||k==="arrowup"){step(-1);e.preventDefault();return;}
 if(k==="v"){const a=el("yt"); a&&window.open(a.href,"_blank","noopener");return;}
 if(k==="]"||k==="tab"){if(r.quotes.length){focusQ=(focusQ+1)%r.quotes.length; renderDetail(); e.preventDefault();}return;}
 if(k==="["){if(r.quotes.length){focusQ=(focusQ-1+r.quotes.length)%r.quotes.length; renderDetail(); e.preventDefault();}return;}
 const ans=ANSWERS.find(x=>x[2]===k);
 if(ans && r.quotes.length){ setField(attrib, r.quotes[focusQ].qid, "answer", ans[0]); return; }
 if(!r.ask) return;
 if(k==="y") setField(labels,r.key,"subject_present",true); else if(k==="n") setField(labels,r.key,"subject_present",false);
 else if(k==="p") setField(labels,r.key,"political_content",true); else if(k==="o") setField(labels,r.key,"political_content",false);
 else if(/^[1-5]$/.test(k)) setField(labels,r.key,"venue",D.venues[+k-1]);
});
el("list").addEventListener("click", e=>{const n=e.target.closest(".item[data-k]"); n&&select(n.dataset.k);});
el("list").addEventListener("keydown", e=>{if(e.key==="Enter"){const n=e.target.closest(".item[data-k]"); n&&select(n.dataset.k);}});
for(const [id,f] of [["f-todo","todo"],["f-all","all"],["f-done","done"]]) el(id).onclick=()=>{filter=f; for(const b of ["f-todo","f-all","f-done"]) el(b).setAttribute("aria-pressed", b===id); renderList();};
el("legend").innerHTML = `<span class="dot done" style="display:inline-block;vertical-align:-1px"></span> verified · <span class="dot rej" style="display:inline-block;vertical-align:-1px"></span> excluded or a misattributed quote · <span class="dot part" style="display:inline-block;vertical-align:-1px"></span> partly answered`;
el("keyhelp").innerHTML = "Keys: <b>y</b>/<b>n</b> subject present · <b>1</b>–<b>5</b> format · <b>p</b>/<b>o</b> political · quotes: <b>s</b> subject, <b>e</b> someone else, <b>b</b> both, <b>u</b> can't tell, <b>[</b>/<b>]</b> move between quotes · <b>j</b>/<b>k</b> next recording · <b>v</b> open video";

renderList(); renderDetail();
(async()=>{
 db = await (window.claude?.use ? window.claude.use("db") : null);
 if(!db){ writable=false; el("banner").hidden=false;
  el("banner").textContent="Answers can't be saved in this view. Open this page on claude.ai while signed in, and every answer saves as you pick it.";
  renderDetail(); return; }
 let first=true;
 const sub=(coll, assign, keyf)=>db.collection(coll).onSnapshot(snap=>{
  const next={}; for(const d of snap.docs){const x=d.data(); const k=keyf(x); if(k) next[k]=x;}
  assign(next);
  if(first){first=false; const todo=recs.find(r=>!complete(r)); if(todo){cur=todo.key; focusQ=firstOpenQuote(todo);}}
  renderList(); renderDetail();
 }, err=>{ writable=false; el("banner").hidden=false; el("banner").textContent="Saved answers stopped loading ("+err.code+"). Reload the page."; renderDetail(); });
 sub("labels", x=>labels=x, x=>x&&x.key);
 sub("attribution", x=>attrib=x, x=>x&&x.qid);
})();
</script>
"""

if __name__ == "__main__":
    raise SystemExit(main())
