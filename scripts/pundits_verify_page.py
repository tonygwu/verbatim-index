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
    data = json.dumps({"rows": rows, "venues": VENUES}, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("/*__DATA__*/null", data)
    Path(args.out).write_text(page)
    print(f"wrote {args.out}: {len(rows)} recordings, {len({r['slug'] for r in rows})} people, "
          f"{len(page) / 1024:.0f} KB")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    for a in ("--checklist", "--transcripts", "--roster", "--out"):
        b.add_argument(a, required=True)
    i = sub.add_parser("import")
    for a in ("--export", "--checklist", "--out"):
        i.add_argument(a, required=True)
    args = ap.parse_args()
    return build(args) if args.cmd == "build" else do_import(args)


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
  <span class="keys"><span class="dot done" style="display:inline-block;vertical-align:-1px"></span> verified · <span class="dot rej" style="display:inline-block;vertical-align:-1px"></span> excluded · <span class="dot part" style="display:inline-block;vertical-align:-1px"></span> incomplete</span>
  <span class="keys">Keys: <b>y</b>/<b>n</b> subject present · <b>1</b>–<b>5</b> format · <b>p</b>/<b>o</b> political yes/no · <b>j</b>/<b>k</b> next/previous · <b>v</b> open video</span>
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
const rows = D.rows, byKey = Object.fromEntries(rows.map(r=>[r.key,r]));
const docId = k => k.replace("/", ":");
let labels = {}, cur = null, filter = "todo", db = null, writable = true;
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const el = id => document.getElementById(id);

// pundits_pilot.py report needs ALL THREE answers for every recording, the
// excluded ones included, so a recording is complete only when all three exist.
function state(k){const l=labels[k]; if(!l) return "todo";
 const answered = typeof l.subject_present==="boolean" && typeof l.political_content==="boolean" && D.venues.includes(l.venue);
 if(!answered) return "part";
 return (l.subject_present && l.political_content) ? "done" : "rej";}
const complete = k => ["done","rej"].includes(state(k));
function fmtT(s){if(s==null)return "";const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+":"+String(m).padStart(2,"0"):m)+":"+String(x).padStart(2,"0");}
function fmtDate(d){return d&&d.length===8?`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`:"unknown";}
function highlight(text, forms){let h=esc(text).replace(/&gt;&gt;/g,'<span class="turn">⟩⟩ </span>');
 const sorted=[...forms].sort((a,b)=>b.length-a.length).map(f=>f.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));
 if(!sorted.length) return h; return h.replace(new RegExp("\\b("+sorted.join("|")+")\\b","gi"),"<mark>$1</mark>");}

function visible(){return rows.filter(r=> filter==="all" || (filter==="todo" ? !complete(r.key) : complete(r.key)));}

function renderList(){
 const vis = visible(), groups = {};
 for(const r of vis)(groups[r.person] ||= []).push(r);
 const perPerson = {};
 for(const r of rows){const p=(perPerson[r.person] ||= {n:0,ok:0}); p.n++; if(state(r.key)==="done") p.ok++;}
 let h="";
 for(const [person, rs] of Object.entries(groups)){
  const p=perPerson[person];
  h+=`<div class="grp"><b>${esc(person)}</b><span class="${p.ok>=5?"ok":""}" title="recordings verified so far (subject present and political); 5 are needed to rank">${p.ok} verified of ${p.n}</span></div>`;
  for(const r of rs) h+=`<div class="item" tabindex="0" data-k="${esc(r.key)}" aria-current="${r.key===cur}"><span class="dot ${state(r.key)}"></span><span class="t">${esc(r.title)}</span></div>`;
 }
 el("list").innerHTML = h || `<div class="item">Nothing here. ${filter==="todo"?"Every recording has a complete answer.":""}</div>`;
 const done = rows.filter(r=>complete(r.key)).length;
 el("count").textContent = `${done} of ${rows.length} checked`;
 el("bar").style.width = (100*done/rows.length).toFixed(1)+"%";
}

function opt(field, value, label, key, cls=""){
 const l=labels[cur]||{}; const on = l[field]===value;
 return `<button type="button" class="opt ${cls}" data-f="${field}" data-v='${JSON.stringify(value)}' aria-pressed="${on}" ${writable?"":"disabled"}>${esc(label)} <kbd>${key}</kbd></button>`;}

function renderDetail(){
 const r = byKey[cur]; if(!r){el("detail").innerHTML='<p class="sub">Pick a recording on the left.</p>';return;}
 const l = labels[cur]||{};
 const start = r.duration ? Math.floor(r.duration*0.2) : 0;
 const yt = `https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${start}s`;
 const hints = r.hints.map(h=>`<span class="chip">${esc(h)}</span>`).join("")
  + `<span class="chip info">${r.mentions} mention${r.mentions===1?"":"s"} of the name in the transcript</span>`;
 const ex = r.excerpts.map(e=>`<article><div class="at"><span>${Math.round(e.at*100)}% in</span>${e.t!=null?`<a href="https://www.youtube.com/watch?v=${encodeURIComponent(r.video_id)}&t=${e.t}s" target="_blank" rel="noopener">play from ${fmtT(e.t)}</a>`:""}</div>${highlight(e.text, r.forms)}</article>`).join("");
 const venues = D.venues.map((v,i)=>opt("venue", v, v, i+1)).join("");
 el("detail").innerHTML = `
  <div class="who"><h2>${esc(r.person)}</h2><span class="role">${esc(r.role)}</span></div>
  <p class="title">${esc(r.title)}</p>
  <div class="facts"><span>${esc(r.channel)}</span><span>uploaded ${fmtDate(r.upload)}</span><span>${r.duration?Math.round(r.duration/60)+" min":""}</span><span>${(r.words||0).toLocaleString()} words</span></div>
  <div class="chips">${hints}</div>
  <a class="yt" href="${yt}" target="_blank" rel="noopener" id="yt">Open on YouTube at ${fmtT(start)} ↗</a>
  ${r.description?`<details class="desc"><summary>Video description</summary><p>${esc(r.description)}</p></details>`:""}
  <div class="ex">${ex}</div>
  <div class="form">
   <div class="q"><label class="l">Subject present<small>Takes part live; a played clip is not presence</small></label><div class="opts">${opt("subject_present",true,"Yes","y","y")}${opt("subject_present",false,"No","n","n")}</div></div>
   <div class="q"><label class="l">Format<small>of this recording</small></label><div class="opts">${venues}</div></div>
   <div class="q"><span></span><div class="def" id="vdef">${l.venue?esc(VENUE_DEF[l.venue]):"Pick the format that fills most of the recording."}</div></div>
   <div class="q"><label class="l">Political content<small>politics, policy, news or public controversy</small></label><div class="opts">${opt("political_content",true,"Yes","p","y")}${opt("political_content",false,"No","o","n")}</div></div>
   <div class="q"><label class="l" for="notes">Notes<small>optional</small></label><textarea id="notes" ${writable?"":"disabled"} placeholder="e.g. guest-only episode; the subject is only quoted">${esc(l.notes||"")}</textarea></div>
   <div class="foot"><div class="nav"><button type="button" class="opt" id="prev">Previous <kbd>k</kbd></button><button type="button" class="opt" id="next">Next <kbd>j</kbd></button></div><span class="status" id="status">${l.updated_at?"Saved":"Not answered yet"}</span></div>
  </div>`;
 el("detail").querySelectorAll("button[data-f]").forEach(b=>b.onclick=()=>setField(b.dataset.f, JSON.parse(b.dataset.v)));
 el("prev").onclick=()=>step(-1); el("next").onclick=()=>step(1);
 const ta=el("notes"); let t; ta.oninput=()=>{clearTimeout(t); t=setTimeout(()=>setField("notes", ta.value, true), 700);};
}

function select(k){cur=k; renderList(); renderDetail();
 const it=el("list").querySelector(`[data-k="${CSS.escape(k)}"]`); it&&it.scrollIntoView({block:"nearest"});}
function step(d){const vis=visible(); const order=vis.length?vis:rows; let i=order.findIndex(r=>r.key===cur);
 if(i<0) i = d>0 ? -1 : order.length; const n=order[Math.min(Math.max(i+d,0),order.length-1)]; n&&select(n.key);}

const queue = {};
function setField(f, v, quiet){
 if(!writable||!cur) return;
 const k=cur; const next={...(labels[k]||{}), key:k, [f]:v, checked_by:"operator", updated_at:new Date().toISOString()};
 labels[k]=next; if(!quiet){renderList(); renderDetail();}
 el("status")&&(el("status").textContent="Saving…", el("status").className="status");
 queue[k]=(queue[k]||Promise.resolve()).then(()=>db.collection("labels").doc(docId(k)).set(next)).then(()=>{
   if(cur===k&&el("status")){el("status").textContent="Saved";}
 }).catch(e=>{
   if(e&&e.code==="invalid_argument"){writable=false;}
   if(cur===k&&el("status")){el("status").textContent="Not saved: "+(e&&e.message||e)+". Reload the page and try again."; el("status").className="status err";}
 });
 if(!quiet && complete(k) && f!=="notes") setTimeout(()=>{ if(cur===k) step(1); }, 250);
}

document.addEventListener("keydown", e=>{
 if(e.target.tagName==="TEXTAREA"){ if(e.key==="Escape") e.target.blur(); return; }
 if(e.metaKey||e.ctrlKey||e.altKey) return;
 const k=e.key.toLowerCase();
 if(k==="j"||k==="arrowdown"){step(1);e.preventDefault();}
 else if(k==="k"||k==="arrowup"){step(-1);e.preventDefault();}
 else if(k==="y") setField("subject_present",true);
 else if(k==="n") setField("subject_present",false);
 else if(k==="p") setField("political_content",true);
 else if(k==="o") setField("political_content",false);
 else if(k==="v"){const a=el("yt"); a&&window.open(a.href,"_blank","noopener");}
 else if(/^[1-5]$/.test(k)) setField("venue", D.venues[+k-1]);
});
el("list").addEventListener("click", e=>{const it=e.target.closest(".item[data-k]"); it&&select(it.dataset.k);});
el("list").addEventListener("keydown", e=>{if(e.key==="Enter"){const it=e.target.closest(".item[data-k]"); it&&select(it.dataset.k);}});
for(const [id,f] of [["f-todo","todo"],["f-all","all"],["f-done","done"]]) el(id).onclick=()=>{filter=f; for(const b of ["f-todo","f-all","f-done"]) el(b).setAttribute("aria-pressed", b===id); renderList();};

cur = rows[0].key; renderList(); renderDetail();
(async()=>{
 db = await (window.claude?.use ? window.claude.use("db") : null);
 if(!db){ writable=false; el("banner").hidden=false;
  el("banner").textContent="Answers can't be saved in this view. Open this page on claude.ai while signed in, and every answer saves as you pick it.";
  renderDetail(); return; }
 db.collection("labels").onSnapshot(snap=>{
  const next={}; for(const d of snap.docs){const x=d.data(); if(x&&x.key) next[x.key]=x;}
  labels=next; const first=!renderList._seen; renderList._seen=true; renderList();
  if(first){const todo=rows.find(r=>!complete(r.key)); if(todo){cur=todo.key;} renderList(); renderDetail();}
 }, err=>{ writable=false; el("banner").hidden=false; el("banner").textContent="Saved answers stopped loading ("+err.code+"). Reload the page."; renderDetail(); });
})();
</script>
"""

if __name__ == "__main__":
    raise SystemExit(main())
