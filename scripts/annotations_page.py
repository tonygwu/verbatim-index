#!/usr/bin/env python3
"""The annotation page: its template, its data block, and what its answers become.

One page serves every project. What it asks is set by the session, never by the
study: the session's MODES say which panels the page shows, and its PROJECTS tag
each recording and quote.

  checklist  recording questions from the project's spec (`annotations_select`);
             only pundits has one today. Saved in the answers file's `labels`.
  speakers   who said which words: word ranges over the transcript, saved in
             `spans`. A quote's result (`attribution`) is DERIVED from the ranges
             on the server; no button sets it.
  captions   corrections to the caption text, saved in `corrections` as an overlay
             on the original tokens.

The page holds transcript text, so it lives in a data checkout and is served from
this machine only (`scripts/annotations.py serve`). Answers are never stored in the
page. Model drafts (`--drafts`) are shown as suggestions; a checklist answer saved
with one on screen records `draft_shown`, so calibration can leave it out.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

#: The page's data block, one line: `const D = {...};`. `</` is written `<\/`.
DATA_LINE = re.compile(r"^const D = (\{.*\});$", re.M)
#: Keys the page itself binds; a checklist option may not take one.
RESERVED_KEYS = {"j", "k", "v", "[", "]", "arrowup", "arrowdown"}


def page_payload(data: dict) -> str:
    """The data block's JSON, safe inside a <script> element."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def page_data(page: str) -> dict:
    """The data block of a built page. A page without one stops the caller."""
    m = DATA_LINE.search(page)
    if not m:
        raise SystemExit("REFUSING: no `const D = {...};` data block in the page; rebuild it with "
                         "scripts/annotations.py rebuild")
    return json.loads(m.group(1).replace("<\\/", "</"))


def page_ids(data: dict) -> dict[str, set[str]]:
    """The recording keys and quote ids the page can send, per answers section.

    Raises rather than returning empty sets: a page that carries nothing to answer
    is a build this tool does not understand, and accepting every id from it would
    turn a loud mismatch into a file of answers nothing can export.
    """
    keys = {r["key"] for r in data.get("rows", []) if r.get("key")}
    qids = {c["qid"] for r in data.get("quote_rows", []) for c in r.get("quotes", []) if c.get("qid")}
    transcripts = set(data.get("transcript_index", {}))
    if not keys and not qids and not transcripts:
        raise SystemExit("REFUSING: the page carries no recordings and no quotes")
    return {"labels": keys, "attribution": qids, "spans": transcripts, "corrections": transcripts}


#: What the page shows of a model draft. `evidence` is the model's own verbatim
#: transcript fragments, which the person can check without opening the video.
DRAFT_FIELDS = ("subject_present", "main_speaker", "venue", "political_content", "confidence", "reason", "evidence")


def load_drafts(path: Path, checklist: dict) -> dict:
    """Each recording's latest draft, by key. A re-run appends, so the last line wins.

    Refuses a draft for a recording the checklist does not have: that is a drafts
    file for another set of recordings, and showing it would mislabel the page.
    """
    latest = {}
    for line in path.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            latest[d["key"]] = d
    foreign = sorted(set(latest) - set(checklist))
    if foreign:
        raise SystemExit(f"REFUSING: {path} drafts {len(foreign)} recordings not on the checklist, e.g. {foreign[:3]}")
    return latest


def draft_view(draft: dict | None) -> tuple[dict | None, list[str]]:
    """(what the page shows of one draft, why a person should check it first).

    The reasons are `needs_review`'s, the same rule that builds speaker_review_queue.json,
    without the operator comparison: the page makes that live, as the person answers.
    """
    from pundits_speaker_infer import needs_review
    if draft is None:
        return None, ["no model draft"]
    if draft.get("error"):
        return None, needs_review(draft, None)
    return {**{f: draft.get(f) for f in DRAFT_FIELDS}, "model": draft["model"]}, needs_review(draft, None)


def render_page(data: dict, title: str, subtitle: str) -> str:
    """The page with its data, its words and its two embedded scripts filled in."""
    checklist = (data.get("session") or {}).get("checklist")
    for field in (checklist or {}).get("fields", []):
        for option in field.get("options", []):
            if str(option.get("key", "")).lower() in RESERVED_KEYS:
                raise SystemExit(f"REFUSING: checklist key {option['key']!r} is one the page already uses")
    page = TEMPLATE
    here = Path(__file__)
    for mark, value in (("/*__DATA__*/null", page_payload(data)), ("/*__TITLE__*/", html.escape(title)),
                        ("/*__SUBTITLE__*/", html.escape(subtitle)),
                        ("/*__SPAN_EDITOR__*/", here.with_name("annotations_span_editor.js").read_text()),
                        ("/*__TEXT_CORRECTIONS__*/", here.with_name("annotations_corrections.js").read_text())):
        if mark not in page:
            raise SystemExit(f"REFUSING: template placeholder {mark} is missing")
        page = page.replace(mark, value)
    return page


def answered(field: dict, value) -> bool:
    """Whether a checklist answer is a complete answer to `field`."""
    if field["type"] == "bool":
        return isinstance(value, bool)
    if field["type"] == "enum":
        return any(value == o["value"] for o in field["options"])
    return isinstance(value, str) and bool(value.strip())


def to_labels(docs: list[dict], keys, checklist: dict) -> dict:
    """Complete checklist answers, in the shape `pundits_pilot.py report` reads.

    Refuses a document whose key is not on the checklist, and reports rather than
    guesses a missing field: a partly answered recording is left out, not filled.
    """
    fields = checklist["fields"]
    out, partial, unknown = {}, [], []
    for d in docs:
        key = d.get("key")
        if key not in keys:
            unknown.append(key)
            continue
        if not all(answered(f, d.get(f["name"])) for f in fields if f.get("required")):
            partial.append(key)
            continue
        out[key] = {**{f["name"]: d.get(f["name"]) for f in fields},
                    "checked_by": d.get("checked_by") or "operator", "notes": d.get("notes") or "",
                    # An assisted label says so, so calibration can leave it out.
                    **({"draft_shown": d["draft_shown"]} if d.get("draft_shown") else {})}
    if unknown:
        raise SystemExit(f"REFUSING: {len(unknown)} labels name recordings not on the checklist, e.g. {unknown[:3]}")
    return {"labels": out, "partial": sorted(partial), "unlabelled": sorted(set(keys) - set(out) - set(partial))}


def docs_from(raw, section: str) -> list[dict]:
    """Documents out of either an Artifact db export or the local server's answers file.

    Three shapes reach here and all three are named rather than sniffed: the server
    writes {"labels": {...}, "attribution": {...}}, an ArtifactData listing comes back
    as a list, and a hand-made export may be one object of documents. Anything else
    stops the import, because a shape this does not recognise is a file the operator
    did not mean to hand over, not a file to interpret generously.
    """
    id_field = "key" if section == "labels" else "qid"
    if isinstance(raw, dict) and {"labels", "attribution"} <= set(raw):
        raw = raw[section]
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [dict(v, **{id_field: v.get(id_field, k)}) for k, v in raw.items() if isinstance(v, dict)]
    raise SystemExit(f"REFUSING: {section} is neither a list of documents nor an object of them")


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
        if d.get("review_status") == "incomplete":
            continue
        if d.get("answer") not in ANSWERS:
            bad.append(qid)
            continue
        out[qid] = {**key_map[qid], "answer": d["answer"], "notes": d.get("notes") or "",
                    "checked_by": d.get("checked_by") or "operator",
                    "review_method": d.get("review_method", "legacy_quote_check")}
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


TEMPLATE = r"""<title>/*__TITLE__*/</title>
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
[hidden]{display:none!important}
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
details.exwrap summary{cursor:pointer;color:var(--muted);font-size:.8rem}
details.exwrap[open] summary{margin-bottom:8px}
.exhd{font-size:.8rem;color:var(--muted);max-width:80ch;margin-bottom:8px}
.exhd b{color:var(--ink2)}
.exhd code{font-family:var(--mono);font-size:.95em}
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
.sec{padding:8px 12px 6px;font-size:.74rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--ink2);border-top:1px solid var(--rule2)}
.sec small{font-weight:400;text-transform:none;letter-spacing:0;color:var(--muted)}
.mdraft{border:1px dashed var(--rule2);border-radius:9px;padding:12px 14px;display:grid;gap:8px;font-size:.86rem;max-width:92ch}
.mdraft .hd{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;font-size:.78rem;color:var(--muted)}
.mdraft .hd b{color:var(--ink2);font-weight:600}
.mdraft dl{display:flex;flex-wrap:wrap;gap:4px 18px;margin:0}
.mdraft dt{display:inline;color:var(--muted)}
.mdraft dd{display:inline;margin:0 0 0 4px;font-weight:500}
.mdraft p{margin:0;color:var(--ink2)}
.mdraft blockquote{margin:0;border-left:2px solid var(--rule2);padding-left:10px;color:var(--ink2);font-size:.82rem}
.mdraft .differ{color:var(--warn);font-size:.8rem}
.opt .mtag{font:500 .66rem var(--mono);color:var(--muted);border:1px dashed var(--rule2);border-radius:4px;padding:0 4px}
.qitem{display:grid;gap:8px;padding:10px 12px;border:1px solid var(--rule);border-radius:9px}
.qitem[data-focus="true"]{border-color:var(--accent);box-shadow:0 0 0 3px var(--accentbg)}
.qitem .hd{display:flex;justify-content:space-between;gap:10px;font-family:var(--mono);font-size:.72rem;color:var(--faint)}
.qitem .hd a{color:var(--accent);text-decoration:none}

/* Speaker attribution: label + pattern, never color alone. */
.quote-exact{border-left:3px solid var(--muted);padding:4px 12px;font-size:.86rem}
.quote-exact p{margin:4px 0;color:var(--ink)}
.span-top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.span-instructions,.span-model{font-size:.82rem;color:var(--ink2);margin:8px 0}
.span-legend{display:flex;gap:8px 16px;flex-wrap:wrap;font-size:.73rem;margin:10px 0}
.span-legend span{padding:2px 5px}
.subject{background:var(--yesbg);color:var(--ink)}
.other{background:var(--nobg);color:var(--ink)}
.unclear,.conflict{background:var(--warnbg);color:var(--ink)}
.draft.subject,.draft.other{border-bottom:2px dashed var(--muted)}
.reviewed.subject{border-bottom:2px solid var(--yes)}
.reviewed.other{border-bottom:2px solid var(--no)}
.reviewed.unclear,.conflict{border-bottom:2px dotted var(--warn)}
.evidence{text-decoration:underline;text-decoration-color:var(--accent);text-decoration-thickness:2px;text-underline-offset:5px}
.span-actions{padding:10px;background:var(--surface2);border:1px solid var(--rule);border-radius:7px;margin:10px 0}
.span-selection{font-size:.8rem;max-height:3.5em;overflow:auto;margin-bottom:8px;color:var(--ink2)}
.span-transcript{font-size:.94rem;line-height:2.1;padding:16px;border:1px solid var(--rule2);border-radius:8px;max-height:440px;overflow:auto;user-select:text;margin:10px 0}
.word.selected-word{background:var(--accentbg);outline:0}
.span-transcript ::selection{background:var(--accent);color:var(--surface)}
.span-boundaries{display:flex;gap:20px;flex-wrap:wrap;font-size:.78rem;margin-top:10px}
.span-boundaries[hidden]{display:none}
.span-boundaries label{display:grid;gap:4px;flex:1;min-width:140px}
.span-boundaries input{width:100%;accent-color:var(--accent)}
.span-range{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:7px 0;border-bottom:1px solid var(--rule);font-size:.76rem}
.span-range>span{flex:1;min-width:120px}
.span-ranges{margin:10px 0}
.range-extra>summary,.span-ranges>summary{cursor:pointer;color:var(--ink2)}
.range-extra{border-top:1px solid var(--rule);padding:12px 0}
.span-status{margin:10px 0}
.caption-gap,.caption-time,.caption-turn{user-select:none;-webkit-user-select:none;color:var(--muted)}
.caption-gap{display:inline-block;background:var(--surface2);border:1px solid var(--rule);border-radius:12px;padding:0 7px;font-size:.7rem;line-height:1.7;vertical-align:middle}
.caption-time{display:block;margin:10px 0 2px;font-family:var(--mono);font-size:.72rem}
.caption-time a{color:var(--accent);text-decoration:none}
.caption-turn{font-size:.75rem;padding:0 6px}
.quote-summary{border:1px solid var(--rule2);background:var(--surface2);border-radius:8px;padding:12px 14px;margin-top:12px}
.quote-summary.pending{border-left:3px solid var(--warn)}
.quote-summary.complete{border-left:3px solid var(--yes)}
.quote-summary p{font-size:.8rem;color:var(--ink2);margin:5px 0 8px}
.correction-form{padding:14px;border:1px solid var(--accent);border-radius:8px;margin:10px 0;background:var(--surface2)}
.correction-form textarea{display:block;width:100%;margin:7px 0 10px;font:inherit;color:var(--ink);background:var(--surface);padding:10px;box-sizing:border-box}
.text-corrections{margin:12px 0;font-size:.82rem}.text-corrections summary{cursor:pointer;color:var(--accent)}
.text-correction{padding:10px 0;border-bottom:1px solid var(--rule)}.text-correction del{color:var(--muted)}
.word.corrected{box-shadow:inset 0 2px var(--accent);border-radius:2px}
[data-span-editor] button[disabled]{opacity:.5;cursor:not-allowed}
.span-samples{display:block;margin:12px 0}
.span-samples select{font:inherit;color:var(--ink);background:var(--surface);padding:5px}

.pchip{font:500 .7rem var(--mono);border:1px solid var(--rule2);border-radius:999px;padding:0 7px;color:var(--ink2);background:var(--surface2);white-space:nowrap}
.mode{display:grid;gap:12px}
.mode+.mode{border-top:1px solid var(--rule);padding-top:14px}
.mode-hd{margin:0;font-size:.74rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--ink2)}
.mode-hd small{font-weight:400;text-transform:none;letter-spacing:0;color:var(--muted);margin-left:8px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
<div class="app">
 <header>
  <div>
   <h1>/*__TITLE__*/</h1>
   <div class="sub">/*__SUBTITLE__*/</div>
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
  <div class="seg" role="group" aria-label="Project" id="projects" hidden></div>
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
// What this page asks comes from its session, never from the study: the modes it
// enables, the projects that tag each recording, and the checklist spec if any.
const S = D.session;
const CHECK = S.modes.includes("checklist") ? S.checklist : null;
const FIELDS = CHECK ? CHECK.fields : [];
const HAS = mode => S.modes.includes(mode);
// A session with only the captions mode has no answer to complete: progress is the
// recordings with corrections, and no recording is ever reported done.
const CAPTIONS_ONLY = !CHECK && !HAS("speakers");
const projectsOf = r => r.projects || S.projects;
const projectOf = c => c.project || S.projects[0];
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const el = id => document.getElementById(id);

// ONE item per recording. A recording may need its checklist, a set of quote
// attributions, or both — everything about it is answered on one screen, so a video
// is never opened twice.
const REC = {};
for(const r of D.rows) REC[r.key] = {...r, ask:!!CHECK, quotes:[]};
for(const r of (D.quote_rows||[])){
 const x = REC[r.key] ||= {...r, ask:false, hints:[], excerpts:[], description:"", mentions:null};
 x.quotes = r.quotes; if(!x.title) Object.assign(x, {title:r.title, channel:r.channel, upload:r.upload, video_id:r.video_id, duration:r.duration, forms:r.forms, person:r.person, role:r.role});
}
// With model drafts (build --drafts), recordings the model flagged come first, then
// the ones it was confident about, then recordings that only have quotes to check.
// Without drafts every recording is in one section, so the order is as it was.
const HAS_DRAFTS = D.rows.some(r=>"doubt" in r);
const SECTIONS = ["Check first", "Model was confident", "Quotes only"];
const SECTION_HELP = ["The model was unsure, found the subject absent or not the main speaker, or has no draft",
 "The model answered with high confidence. Its draft is a suggestion, never an answer", "No recording questions, only flagged quotes"];
const section = r => !HAS_DRAFTS ? 0 : !r.ask ? 2 : (r.doubt||[]).length ? 0 : 1;
const recs = Object.values(REC).sort((a,b)=>section(a)-section(b) || (a.person.split(" ").pop()+a.person+a.upload).localeCompare(b.person.split(" ").pop()+b.person+b.upload));
// A page with no recording-level questions is only quotes.
const QUOTE_ONLY = !D.rows.length;
let filter=CAPTIONS_ONLY?"all":"todo", projectFilter="all", cur=recs.length?recs[0].key:null, focusQ=0;
let labels={}, attrib={}, saver=null, writable=false;

const answered = (f, v) => f.type==="bool" ? typeof v==="boolean" : f.type==="enum" ? f.options.some(o=>o.value===v)
 : typeof v==="string" && v.trim()!=="";
// Count the questions, not the blocks: a fresh recording has three unanswered
// questions and used to report "1 left", which reads as one click away from done.
const askLeft = r => {if(!r.ask) return 0; const l=labels[r.key]||{};
 return FIELDS.filter(f=>f.required && !answered(f, l[f.name])).length;};
const askDone = r => askLeft(r)===0;
// Quote results count only where the session has the speakers mode that makes them.
const openQuotes = r => HAS("speakers") ? r.quotes.filter(c=>!(attrib[c.qid]||{}).answer) : [];
const quotesDone = r => !openQuotes(r).length &&
 (!r.quotes.length || !HAS("speakers") || (!spanPending[r.key] && !spanErrors[r.key]));
const complete = r => !CAPTIONS_ONLY && askDone(r) && quotesDone(r);
function recState(r){
 if(CAPTIONS_ONLY) return correctionAnswers[r.key]?.edits?.length ? "part" : "todo";
 if(complete(r)){
  const l=labels[r.key]||{};
  if(r.ask && !CHECK.accept_when_true.every(f=>l[f]===true)) return "rej";
  if(r.quotes.some(c=>["other","both"].includes((attrib[c.qid]||{}).answer))) return "rej";
  return "done";}
 return (labels[r.key]||spanAnswers[r.key]?.ranges.length||r.quotes.some(c=>(attrib[c.qid]||{}).answer)) ? "part" : "todo";}
const outstanding = r => askLeft(r) + openQuotes(r).length;

function fmtT(s){if(s==null)return "";const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+":"+String(m).padStart(2,"0"):m)+":"+String(x).padStart(2,"0");}
function fmtDate(d){return d&&d.length===8?`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`:"unknown";}
function highlight(text, forms){let h=esc(text).replace(/&gt;&gt;/g,'<span class="turn">⟩⟩ </span>');
 const sorted=[...(forms||[])].sort((a,b)=>b.length-a.length).map(f=>f.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));
 if(!sorted.length) return h; return h.replace(new RegExp("\\b("+sorted.join("|")+")\\b","gi"),"<mark>$1</mark>");}
const visible = () => recs.filter(r=> (projectFilter==="all" || projectsOf(r).includes(projectFilter))
 && (filter==="all" || (filter==="todo" ? !complete(r) : complete(r))));
const chips = ps => S.projects.length>1 ? ps.map(p=>` <span class="pchip">${esc(p)}</span>`).join("") : "";
const curRec = () => REC[cur];

function renderList(){
 const vis=visible(), groups={}, per={};
 // One group per person within each section, so a person's flagged recordings
 // are not pulled down into their confident ones.
 for(const r of vis)(groups[section(r)+"\u0000"+r.person] ||= []).push(r);
 for(const r of recs){const p=(per[r.person] ||= {n:0,ok:0,q:0,qa:0,fixed:0}); p.n++; if(r.ask&&recState(r)==="done") p.ok++; p.q+=r.quotes.length; p.qa+=r.quotes.filter(c=>(attrib[c.qid]||{}).answer).length;
  if(correctionAnswers[r.key]?.edits?.length) p.fixed++;}
 let h="", lastSec=null;
 for(const [gk,rs] of Object.entries(groups)){
  const person=rs[0].person, p=per[person], sec=section(rs[0]);
  if(HAS_DRAFTS && sec!==lastSec){lastSec=sec;
   const all=recs.filter(r=>section(r)===sec);
   h+=`<div class="sec" title="${esc(SECTION_HELP[sec])}">${SECTIONS[sec]} <small>· ${all.filter(complete).length} of ${all.length} checked</small></div>`;}
  h+= CAPTIONS_ONLY
   ? `<div class="grp"><b>${esc(person)}</b><span title="recordings with a saved caption correction">${p.fixed} of ${p.n} corrected</span></div>`
   : QUOTE_ONLY
   ? `<div class="grp"><b>${esc(person)}</b><span class="${p.qa===p.q?"ok":""}" title="quotes with a saved answer">${p.qa} of ${p.q} quotes answered</span></div>`
   : `<div class="grp"><b>${esc(person)}</b><span class="${p.ok>=CHECK.goal.count?"ok":""}" title="${esc(CHECK.goal.help)}">${p.ok} verified of ${p.n}${p.q?` · ${p.q} quotes`:""}</span></div>`;
  for(const r of rs){
   const left=outstanding(r);
   h+=`<div class="item" tabindex="0" data-k="${esc(r.key)}" aria-current="${r.key===cur}"><span class="dot ${recState(r)}"></span><span class="t">${esc(r.title)}${r.quotes.length?` <span class="turn">· ${r.quotes.length} quote${r.quotes.length>1?"s":""}</span>`:""}${chips(projectsOf(r))}</span></div>`;}
 }
 el("list").innerHTML = h || `<div class="item">Nothing here. ${filter==="todo"?"Everything has an answer.":""}</div>`;
 const done=recs.filter(complete).length, q=recs.reduce((n,r)=>n+r.quotes.length,0);
 if(CAPTIONS_ONLY){const fixed=recs.filter(r=>correctionAnswers[r.key]?.edits?.length).length;
  el("count").textContent=`${fixed} of ${recs.length} recordings have caption corrections`;
  el("bar").style.width=(100*fixed/(recs.length||1)).toFixed(1)+"%"; return;}
 el("count").textContent=`${done} of ${recs.length} recordings checked${q?` · ${recs.reduce((n,r)=>n+r.quotes.filter(c=>(attrib[c.qid]||{}).answer).length,0)} of ${q} quotes`:""}`;
 el("bar").style.width=(100*done/(recs.length||1)).toFixed(1)+"%";}

function opt(store, id, field, value, label, key, cls=""){
 const on=(store[id]||{})[field]===value;
 const fab = store===labels && REC[id]?.draft?.[field]===value ? ` <span class="mtag" title="the model's draft answer">model</span>` : "";
 return `<button type="button" class="opt ${cls}" data-id="${esc(id)}" data-f="${field}" data-v='${JSON.stringify(value)}' aria-pressed="${on}" ${writable?"":"disabled"}>${esc(label)}${fab} <kbd>${key}</kbd></button>`;}

// The model's draft, shown as a suggestion beside the questions. Where the person's
// saved answer differs, the card says so, so a slip is caught before moving on.
const YN = v => v===true?"yes":v===false?"no":"?";
function draftCard(r){
 if(!HAS_DRAFTS || !r.ask) return "";
 const why=(r.doubt||[]).map(w=>`<span class="chip">${esc(w)}</span>`).join("");
 const d=r.draft;
 if(!d) return `<div class="mdraft"><div class="hd"><b>No usable model draft</b></div>${why?`<div class="chips">${why}</div>`:""}</div>`;
 const l=labels[r.key]||{};
 // A field marked differs_only_if counts only once that other answer is true, as in needs_review.
 const differ=FIELDS.filter(f=>f.name in l && l[f.name]!==d[f.name] && !(f.differs_only_if && !l[f.differs_only_if])).map(f=>f.draft_label);
 return `<div class="mdraft">
  <div class="hd"><b>Model draft</b><span>${esc(d.model)} · confidence ${esc(d.confidence)}</span><span>a suggestion: you still pick each answer</span></div>
  <dl>${CHECK.draft_fields.map(([f,label])=>`<div><dt>${esc(label)}</dt><dd>${typeof d[f]==="string"?esc(d[f]):YN(d[f])}</dd></div>`).join("")}</dl>
  ${why?`<div class="chips">${why}</div>`:""}
  <p>${esc(d.reason)}</p>
  ${(d.evidence||[]).map(x=>`<blockquote>${esc(x)}</blockquote>`).join("")}
  ${differ.length?`<div class="differ">Your answer differs from the model's on: ${esc(differ.join(", "))}</div>`:""}
 </div>`;}

function renderDetail(){
 const r=curRec();
 if(!r){el("detail").innerHTML='<p class="sub">Pick a recording on the left.</p>';return;}
 const l=labels[r.key]||{}, start=r.duration?Math.floor(r.duration*0.2):0;
 const hints=(r.hints||[]).map(h=>`<span class="chip">${esc(h)}</span>`).join("")
  + (r.mentions!=null?`<span class="chip info">${r.mentions} mention${r.mentions===1?"":"s"} of the name in the transcript</span>`:"");
 const ask = r.ask ? `<section class="mode" data-mode="checklist"><h3 class="mode-hd">Checklist<small>about this recording</small></h3>
   ${FIELDS.map((f,i)=>{
    const cur=(f.options||[]).find(o=>o.value===l[f.name]);
    return `<div class="q"><label class="l">${i+1} · ${esc(f.label)}<small>${esc(f.help||"")}</small></label><div class="opts">${(f.options||[]).map(o=>opt(labels,r.key,f.name,o.value,o.label,o.key,o.cls||"")).join("")}</div></div>`
     + ((f.options||[]).some(o=>o.help) ? `<div class="q"><span></span><div class="def">${cur?esc(cur.help):esc(f.prompt||"")}</div></div>` : "");}).join("")}
   <div class="q"><label class="l" for="notes">Notes<small>optional</small></label><textarea id="notes" ${writable?"":"disabled"} placeholder="${esc(CHECK.notes_placeholder||"")}">${esc(l.notes||"")}</textarea></div></section>` : "";
 const helps=[...new Set(r.quotes.map(c=>S.project_help[projectOf(c)]))].join("; ");
 const quotes = r.quotes.length && HAS("speakers") ? `
  <section class="mode qblock" data-mode="speakers"><h3 class="mode-hd">Speakers<small>who says the quoted words</small></h3>
   <div class="q"><label class="l">${r.ask?(FIELDS.length+1)+" · ":""}Who says these lines?<small>${esc(helps)}</small></label>
    <div class="qhelp">Label the underlined quote words. You can also label the surrounding speech, but only the quote determines this review's result. The result updates and saves automatically.</div></div>
   ${r.quotes.map((c,i)=>`<div class="qitem" data-q="${i}" data-focus="${i===focusQ}">
     <div class="hd"><span>quote ${i+1} of ${r.quotes.length}${chips([projectOf(c)])}</span>${c.t!=null?`<a href="https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${c.t}s" target="_blank" rel="noopener">play from ${fmtT(c.t)}</a>`:""}</div>
     <div class="quote-exact"><b>Quote being checked</b><p>${esc(c.text)}</p></div>
     <div data-span-editor="${i}">Loading speaker-range editor…</div>
    </div>`).join("")}
  </section>` : "";
 const extra = (!r.quotes.length || !HAS("speakers")) && (HAS("speakers")||HAS("captions"))
  ? `<details class="range-extra"><summary>${HAS("speakers")?"Mark speaker ranges in this recording (optional)":"Correct the captions of this recording"}</summary><div data-span-editor="-1">Loading transcript…</div></details>` : "";
 el("detail").innerHTML=`
  <div class="who"><h2>${esc(r.person)}</h2><span class="role">${esc(r.role||"")}</span>${chips(projectsOf(r))}</div>
  <p class="title">${esc(r.title)}</p>
  <div class="facts"><span>${esc(r.channel||"")}</span><span>uploaded ${fmtDate(r.upload)}</span><span>${r.duration?Math.round(r.duration/60)+" min":""}</span>${r.words?`<span>${r.words.toLocaleString()} words</span>`:""}</div>
  ${hints?`<div class="chips">${hints}</div>`:""}
  <a class="yt" id="yt" href="https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${start}s" target="_blank" rel="noopener">Open on YouTube at ${fmtT(start)} ↗</a>
  ${r.description?`<details class="desc"><summary>Video description</summary><p>${esc(r.description)}</p></details>`:""}
  ${draftCard(r)}
  <div class="form">${ask}${quotes}
   ${extra}
   <div class="foot"><div class="nav"><button type="button" class="opt" id="prev">Previous <kbd>k</kbd></button><button type="button" class="opt" id="next">Next <kbd>j</kbd></button></div><span class="status" id="status"></span></div>
  </div>`;
 el("status").textContent = CAPTIONS_ONLY ? "Captions: correct any errors you notice; there is nothing else to answer"
  : complete(r) ? "All answered" : `${outstanding(r)} answer${outstanding(r)===1?"":"s"} left on this recording`;
 el("detail").querySelectorAll("button[data-f]").forEach(b=>b.onclick=()=>setField(labels, b.dataset.id, b.dataset.f, JSON.parse(b.dataset.v)));
 el("detail").querySelectorAll(".qitem").forEach(n=>n.onclick=()=>{focusQ=+n.dataset.q;});
 mountSpanEditors(r);
 el("prev").onclick=()=>step(-1); el("next").onclick=()=>step(1);
 const ta=el("notes"); if(ta){let tm; ta.oninput=()=>{clearTimeout(tm); tm=setTimeout(()=>setField(labels,r.key,"notes",ta.value,true),700);};}}

function select(k){cur=k; history.replaceState(null,"","#"+encodeURIComponent(k)); focusQ=firstOpenQuote(REC[k]); renderList(); renderDetail();
 const n=el("list").querySelector(`[data-k="${CSS.escape(k)}"]`); n&&n.scrollIntoView({block:"nearest"});}
function firstOpenQuote(r){const i=r.quotes.findIndex(c=>!(attrib[c.qid]||{}).answer); return i<0?0:i;}
function step(d){const vis=visible(), order=vis.length?vis:recs; let i=order.findIndex(r=>r.key===cur);
 if(i<0) i = d>0 ? -1 : order.length; const n=order[Math.min(Math.max(i+d,0),order.length-1)]; n&&select(n.key);}

const queue={};
function setField(store, id, f, v, quiet){
 if(!writable) return;
 const next={...(store[id]||{}), key:id, [f]:v, checked_by:"operator", updated_at:new Date().toISOString()};
 // Saved while a draft was on screen: an assisted label, and it says so.
 if(store===labels && REC[id]?.draft) next.draft_shown=REC[id].draft.model;
 store[id]=next;
 if(!quiet){renderList();renderDetail();}
 const st=el("status");st&&(st.textContent="Saving…",st.className="status");
 queue[id]=(queue[id]||Promise.resolve()).then(()=>saver.put("labels",id,next)).then(()=>{
  if(el("status")&&cur===id) el("status").textContent=complete(curRec())?"All answered":`${outstanding(curRec())} answers left on this recording`;
 }).catch(e=>{
  if(el("status")){el("status").textContent="Not saved: "+(e&&e.message||e)+". Reload and try again.";el("status").className="status err";}
 });
}

/*__SPAN_EDITOR__*/
/*__TEXT_CORRECTIONS__*/

const CHECK_KEYS={}; for(const f of FIELDS) for(const o of f.options||[]) if(o.key!=null) CHECK_KEYS[String(o.key).toLowerCase()]=[f.name,o.value];
const fieldKeys = f => {const ks=(f.options||[]).map(o=>String(o.key));
 return ks.length>2 && ks.every((k,i)=>k===String(i+1)) ? `<b>1</b>–<b>${ks.length}</b>` : ks.map(k=>`<b>${esc(k)}</b>`).join("/");};
document.addEventListener("keydown", e=>{
 if(["TEXTAREA","INPUT","SELECT"].includes(e.target.tagName)||e.target.closest("[data-span-editor]")){ if(e.key==="Escape") e.target.blur(); return; }
 if(e.metaKey||e.ctrlKey||e.altKey) return;
 const r=curRec(); if(!r) return;
 const k=e.key.toLowerCase();
 if(k==="j"||k==="arrowdown"){step(1);e.preventDefault();return;}
 if(k==="k"||k==="arrowup"){step(-1);e.preventDefault();return;}
 if(k==="v"){const a=el("yt"); a&&window.open(a.href,"_blank","noopener");return;}
 if(k==="]"){if(r.quotes.length){focusQ=(focusQ+1)%r.quotes.length; renderDetail(); e.preventDefault();}return;}
 if(k==="["){if(r.quotes.length){focusQ=(focusQ-1+r.quotes.length)%r.quotes.length; renderDetail(); e.preventDefault();}return;}
 if(!r.ask) return;
 const hit=CHECK_KEYS[k]; if(hit) setField(labels,r.key,hit[0],hit[1]);
});
el("list").addEventListener("click", e=>{const n=e.target.closest(".item[data-k]"); n&&select(n.dataset.k);});
el("list").addEventListener("keydown", e=>{if(e.key==="Enter"){const n=e.target.closest(".item[data-k]"); n&&select(n.dataset.k);}});
if(CAPTIONS_ONLY) for(const [id,f] of [["f-todo","todo"],["f-all","all"],["f-done","done"]]) el(id).setAttribute("aria-pressed", f===filter);
for(const [id,f] of [["f-todo","todo"],["f-all","all"],["f-done","done"]]) el(id).onclick=()=>{filter=f; for(const b of ["f-todo","f-all","f-done"]) el(b).setAttribute("aria-pressed", b===id); renderList();};
el("legend").innerHTML = `<span class="dot done" style="display:inline-block;vertical-align:-1px"></span> verified · <span class="dot rej" style="display:inline-block;vertical-align:-1px"></span> excluded or a misattributed quote · <span class="dot part" style="display:inline-block;vertical-align:-1px"></span> partly answered`;
el("keyhelp").innerHTML = (QUOTE_ONLY || !CHECK
 ? "Keys: " : "Keys: " + FIELDS.map(f=>`${fieldKeys(f)} ${esc(f.draft_label||f.label)}`).join(" · ") + " · quotes: ")
 + "<b>[</b>/<b>]</b> move between quotes · <b>j</b>/<b>k</b> next recording · <b>v</b> open video";
if(S.projects.length>1){const box=el("projects"); box.hidden=false;
 const opts=["all",...S.projects];
 box.innerHTML=opts.map(p=>`<button type="button" data-project="${esc(p)}" aria-pressed="${p===projectFilter}">${p==="all"?"All projects":esc(p)}</button>`).join("");
 box.onclick=e=>{const b=e.target.closest("button[data-project]"); if(!b) return; projectFilter=b.dataset.project;
  for(const x of box.querySelectorAll("button")) x.setAttribute("aria-pressed", x.dataset.project===projectFilter); renderList();};}

// Answers live in the session's answers file on this machine, through the local
// server (`scripts/annotations.py serve`). Without it the page is read-only.
const localStore = {
 where: "this machine",
 async load(){
  const res = await fetch("api/answers", {headers:{accept:"application/json"}});
  if(!res.ok) throw new Error("api/answers returned "+res.status);
  const j = await res.json();
  if(!j || typeof j.labels!=="object" || typeof j.attribution!=="object")
   throw new Error("api/answers returned an unexpected shape");
  return j;
 },
 async put(coll, id, value){
  const res = await fetch("api/answer", {method:"POST", headers:{"content-type":"application/json"},
   body: JSON.stringify({kind:coll, id, value})});
  let j={}; try{ j = await res.json(); }catch(e){}
  if(!res.ok) throw new Error(j.error || ("the server answered "+res.status));
  return j;
 }};
function startAt(){let key="";try{key=decodeURIComponent(location.hash.slice(1));}catch(e){}
 const todo=REC[key]||recs.find(r=>!complete(r)); if(todo){cur=todo.key; focusQ=firstOpenQuote(todo);}}

renderList(); renderDetail();
(async()=>{
 let local=null;
 try{ local = await localStore.load(); }catch(e){ local=null; }
 if(!local){ writable=false; el("banner").hidden=false;
  el("banner").textContent="Answers can't be saved in this view. Serve the session with scripts/annotations.py serve and open the localhost address it prints; every answer then saves as you make it.";
  renderDetail(); return; }
 saver=localStore; writable=true;
 labels=local.labels; attrib=local.attribution; spanAnswers=local.spans||{}; correctionAnswers=local.corrections||{};
 startAt(); renderList(); renderDetail();
})();
</script>
"""
