#!/usr/bin/env python3
"""Render the Verbatim Predictions page from data/predictions into one self-contained HTML file.

An INDEX of what each person said would happen, not a ranking of who predicts
well. The table is alphabetical by default and no column measures foresight;
the test forbids the vocabulary of accuracy anywhere outside the disclaimer.

Only accepted records are embedded (extractor and verifier agreed). Rejected
candidates are counted per person and never shown, because publishing a claim
the pipeline said is not this person's prediction, under their name, asserts
what the verifier denied. The record on disk keeps everything for audit.

Same idiom as build_site.py: one TEMPLATE string with __TOKEN__ placeholders,
JSON embedded so the page needs no server, the shared tokens from
site_theme.py, and an atomic write. Numbers in the prose come from
index.json, never from a literal in this file.

  .venv/bin/python scripts/build_predictions_site.py --index data/predictions/index.json \
      --predictions data/predictions --roster data/roster/final.json --out site-predictions/index.html
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402
from site_theme import FONT_LINKS, THEME_CSS  # noqa: E402
import predictions_lib as L  # noqa: E402

MODEL_LABELS = {
    "claude-fable-5-1": "Claude Fable 5.1",
    "gpt-6-astra": "OpenAI GPT-6 Astra",
    "gemini-3.8-flash-high": "Google Gemini 3.8 Flash",
}
PLATFORM_LABELS = {"polymarket": "Polymarket", "kalshi": "Kalshi"}

TEMPLATE = r"""<title>Verbatim Predictions</title>
__FONTS__
<style>
__THEME__
*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55; margin:0;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1276px; margin:0 auto; padding:0 24px 96px}
a{color:var(--d1)}
h1,h2,h3{text-wrap:balance; margin:0}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums}

/* ---------- masthead (mirrors build_site.py) ---------- */
header.mast{padding:56px 0 28px; border-bottom:1px solid var(--rule-strong)}
.eyebrow{
  font-family:"IBM Plex Mono",monospace; font-size:11px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted); margin-bottom:14px;
}
h1{
  font-family:"Instrument Serif",Georgia,serif; font-weight:400;
  font-size:clamp(44px,7vw,76px); line-height:1.02; letter-spacing:-.015em;
}
h1 em{font-style:italic; color:var(--d2)}
.thesis{max-width:62ch; margin-top:18px; font-size:17px; color:var(--ink-2)}
.thesis strong{color:var(--ink); font-weight:600}

/* ---------- strip ---------- */
.strip{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:0; border-bottom:1px solid var(--rule-strong); margin-bottom:34px;
}
.strip div{padding:16px 18px 18px; border-right:1px solid var(--rule)}
.strip div:last-child{border-right:none}
.strip dt{
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--faint); margin-bottom:6px;
}
.strip dd{
  margin:0; font-family:"IBM Plex Mono",monospace; font-size:22px;
  font-weight:500; font-variant-numeric:tabular-nums; letter-spacing:-.02em;
}
.strip dd small{font-size:12px; color:var(--muted); font-weight:400; margin-left:3px}
.strip dd.models{font-size:12px; line-height:1.4; font-weight:400; letter-spacing:0}

/* ---------- section headings ---------- */
.sec{margin:52px 0 18px}
.sec h2{font-family:"Instrument Serif",Georgia,serif; font-weight:400; font-size:30px; letter-spacing:-.01em}
.sec p{margin:8px 0 0; color:var(--muted); max-width:70ch; font-size:14px}
.legend{display:flex; flex-wrap:wrap; gap:16px; margin:14px 0 0; font-size:12.5px; color:var(--muted)}
.legend b{color:var(--ink)}

/* ---------- table ---------- */
.tablecard{background:var(--surface); border:1px solid var(--rule); border-radius:3px; box-shadow:var(--shadow); overflow-x:auto}
table{border-collapse:collapse; width:100%; min-width:1100px; table-layout:fixed}
thead th{
  position:sticky; top:0; z-index:2; background:var(--surface);
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; font-weight:500;
  letter-spacing:.06em; text-transform:uppercase; color:var(--muted);
  text-align:center; padding:14px 7px 11px; border-bottom:1px solid var(--rule-strong);
  white-space:nowrap; cursor:pointer; user-select:none;
}
thead th:hover{color:var(--ink)}
thead th .arrow{opacity:.35; margin-left:3px; font-size:9px}
thead th[aria-sort] .arrow{opacity:1; color:var(--d2)}
tbody tr.row{border-bottom:1px solid var(--rule); cursor:pointer}
tbody tr.row:hover{background:var(--surface-2)}
tbody tr.row:focus-visible{outline:2px solid var(--d1); outline-offset:-2px}
td{padding:11px 7px; vertical-align:middle}
td.num{text-align:right; font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums}
td.num.zero{color:var(--faint)}
.who{width:190px; padding-left:16px}
.who .nm{font-weight:600; letter-spacing:-.01em}
.who .rl{font-size:12px; color:var(--muted); margin-top:1px}
td.org{color:var(--ink-2); font-size:13.5px}
td.org .sector{display:block; font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.06em; text-transform:uppercase; color:var(--faint); margin-top:2px}
td.date{font-family:"IBM Plex Mono",monospace; font-size:12.5px; text-align:right}
td.date.unknown{color:var(--faint)}

/* ---------- (?) affordance + shared tooltip (mirrors build_site.py) ---------- */
button.info{
  all:unset; box-sizing:border-box; display:inline-grid; place-items:center;
  width:14px; height:14px; margin-left:5px; border-radius:50%;
  border:1px solid var(--rule-strong); color:var(--muted);
  font-family:"IBM Plex Sans",system-ui,sans-serif;
  font-size:9px; font-weight:600; line-height:1; letter-spacing:0;
  text-transform:none; cursor:help; vertical-align:middle; flex:none;
}
button.info:hover,button.info[aria-expanded="true"]{color:var(--surface); background:var(--d1); border-color:var(--d1)}
button.info:focus-visible{outline:2px solid var(--d1); outline-offset:2px}
#tip{
  position:fixed; z-index:60; max-width:310px; padding:12px 14px;
  background:var(--surface); color:var(--ink-2);
  border:1px solid var(--rule-strong); border-radius:4px; box-shadow:var(--shadow);
  font-family:"IBM Plex Sans",system-ui,sans-serif;
  font-size:12.5px; line-height:1.5; font-weight:400;
  letter-spacing:0; text-transform:none; text-align:left; white-space:normal;
}
#tip[hidden]{display:none}
#tip b{color:var(--ink); font-weight:600}
#tip p{margin:0 0 7px}
#tip p:last-child{margin-bottom:0}
#tip .note{color:var(--muted); font-size:11.5px}

/* ---------- drawer ---------- */
tr.audit>td{padding:0; background:var(--surface-2); border-bottom:1px solid var(--rule-strong)}
.drawer{padding:20px 22px 26px}
.drawer h3{font-family:"Instrument Serif",Georgia,serif; font-size:21px; font-weight:400; margin-bottom:3px}
.drawer .sub{font-size:12.5px; color:var(--muted); margin-bottom:14px}
.filters{display:flex; flex-wrap:wrap; gap:14px; align-items:center; margin-bottom:16px; font-size:12.5px; color:var(--muted)}
.filters label{display:flex; gap:6px; align-items:center}
.filters select{font:inherit; font-size:12.5px; color:var(--ink); background:var(--surface); border:1px solid var(--rule-strong); border-radius:2px; padding:3px 6px}
.filters .count{margin-left:auto; font-family:"IBM Plex Mono",monospace; font-size:11px}
.tcard{background:var(--surface); border:1px solid var(--rule); border-radius:3px; padding:15px 17px; margin-bottom:12px}
.tcard .hdr{display:flex; flex-wrap:wrap; gap:10px; align-items:baseline; padding-bottom:9px; margin-bottom:11px; border-bottom:1px solid var(--rule)}
.tcard .hdr .t{font-weight:600; font-size:14px}
.tcard .hdr .meta{font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--muted); margin-left:auto; text-align:right}
.pred{padding:12px 0 14px; border-bottom:1px dashed var(--rule)}
.pred:last-child{border-bottom:none; padding-bottom:2px}
.pred .claim{font-size:15px; font-weight:600; letter-spacing:-.005em; margin-bottom:6px}
.quotes{margin:7px 0 0; padding:0; list-style:none; display:flex; flex-direction:column; gap:5px}
.quotes li{font-size:13px; color:var(--ink-2); display:flex; gap:8px}
.quotes .ts{font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--faint); flex:none; padding-top:1px; text-decoration:none}
.quotes a.ts{color:var(--d1)}
.quotes q{font-style:italic}
dl.kv{display:grid; grid-template-columns:max-content 1fr; gap:3px 14px; margin:10px 0 0; font-size:12.5px}
dl.kv dt{font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.07em; text-transform:uppercase; color:var(--faint); padding-top:2px}
dl.kv dd{margin:0; color:var(--ink-2)}
dl.kv dd.pending{color:var(--muted)}
.market{margin-top:8px; font-size:12.5px; color:var(--ink-2); padding-left:9px; border-left:1.5px solid var(--d3)}
.market b{font-family:"IBM Plex Mono",monospace; font-weight:600; color:var(--d3)}
.market.proxy{border-left-color:var(--rule-strong)}
.market .why{color:var(--muted); font-size:11.5px}
details.ctx{margin-top:9px; font-size:12.5px}
details.ctx summary{cursor:pointer; color:var(--muted); font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.06em; text-transform:uppercase}
details.ctx p{margin:8px 0 0; color:var(--ink-2); line-height:1.6; white-space:pre-wrap}
details.ctx mark{background:var(--d2-wash); color:var(--ink); padding:0 2px}
.prov{margin-top:8px; font-family:"IBM Plex Mono",monospace; font-size:10.5px; color:var(--faint)}
.prov code{font-family:inherit}

/* ---------- prose ---------- */
.prose{max-width:72ch}
.prose h3{font-size:15px; font-weight:600; margin:22px 0 6px; letter-spacing:-.005em}
.prose p{margin:0 0 11px; color:var(--ink-2); font-size:14.5px}
.prose ul{margin:0 0 11px; padding-left:19px; color:var(--ink-2); font-size:14.5px}
.prose li{margin-bottom:5px}
.prose code{font-family:"IBM Plex Mono",monospace; font-size:12.5px; background:var(--surface-2); padding:1px 4px; border-radius:2px}
.callout{border-left:2px solid var(--d2); background:var(--surface); padding:14px 17px; margin:16px 0; border-radius:0 3px 3px 0; font-size:14px}
.callout b{color:var(--ink)}
footer{margin-top:56px; padding-top:18px; border-top:1px solid var(--rule); color:var(--muted); font-size:12.5px; max-width:80ch}
.toggle{
  position:fixed; top:14px; right:14px; z-index:50;
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.1em;
  background:var(--surface); color:var(--muted); border:1px solid var(--rule-strong);
  border-radius:2px; padding:6px 10px; cursor:pointer;
}
.toggle:hover{color:var(--ink)}
@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
</style>

<button class="toggle" id="themeBtn" type="button">THEME</button>
<div class="wrap">

<header class="mast">
  <div class="eyebrow">__GENDATE__ &middot; Verbatim quotes, dated &middot; Every item pending &middot; <a href="https://verbatim-index.tonygwu.com">Verbatim Index &rarr;</a></div>
  <h1>Verbatim <em>Predictions</em></h1>
  <p class="thesis">
    Forward-looking claims that __N_PEOPLE__ technology leaders made in public, quoted
    <strong>verbatim</strong> from transcripts of their own recorded speech, with the date they said
    it and the date it refers to. <!-- disclaimer:start --><strong>This is an index of what was said. It is not a ranking of
    who predicts well.</strong> Nothing here has been checked against what happened; every item is
    pending, and the table is alphabetical.<!-- disclaimer:end -->
  </p>
</header>

<dl class="strip">
  <div><dt>People</dt><dd>__N_PEOPLE__</dd></div>
  <div><dt>Transcripts scanned</dt><dd>__N_TX__</dd></div>
  <div><dt>Predictions</dt><dd>__N_ACCEPTED__</dd></div>
  <div><dt>With a statement date</dt><dd>__PCT_DATED__<small>%</small></dd></div>
  <div><dt>With a stated probability</dt><dd>__N_PROB__</dd></div>
  <div><dt>Extractor / verifier</dt><dd class="models">__EXTRACTOR__<br>__VERIFIER__</dd></div>
</dl>

<div class="sec">
  <h2>The index</h2>
  <p>
    Click any row to read every prediction with its verbatim quote and the surrounding transcript.
    Sort by any column; the default is alphabetical, and no column measures foresight.
  </p>
  <div class="legend">
    <span><b>Accepted</b> means the extractor (__EXTRACTOR__) proposed the claim and an independent
    verifier (__VERIFIER__) agreed it is a forward-looking, falsifiable statement by this speaker.
    Candidates the verifier rejected are kept on file and counted, not shown.</span>
  </div>
</div>

<div class="tablecard">
  <table id="board">
    <colgroup>
      <col><col style="width:150px">
      <col style="width:84px"><col style="width:90px"><col style="width:84px"><col style="width:84px">
      <col style="width:84px"><col style="width:90px"><col style="width:96px">
      <col style="width:100px"><col style="width:100px">
    </colgroup>
    <thead><tr>
      <th data-k="name" aria-sort="ascending">Person<span class="arrow">&#9650;</span></th>
      <th data-k="company">Organisation<span class="arrow">&#9650;</span></th>
      <th data-k="accepted">Accepted<button class="info" type="button" data-info="accepted"
        aria-expanded="false" aria-label="What does Accepted mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="h_explicit">Explicit date<button class="info" type="button" data-info="h_explicit"
        aria-expanded="false" aria-label="What does Explicit date mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="h_inferable">Inferable<button class="info" type="button" data-info="h_inferable"
        aria-expanded="false" aria-label="What does Inferable mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="h_none">No date<button class="info" type="button" data-info="h_none"
        aria-expanded="false" aria-label="What does No date mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="p_explicit">Stated p<button class="info" type="button" data-info="p_explicit"
        aria-expanded="false" aria-label="What does Stated p mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="p_qual">Qualitative<button class="info" type="button" data-info="p_qual"
        aria-expanded="false" aria-label="What does Qualitative mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="transcripts">Transcripts<button class="info" type="button" data-info="transcripts"
        aria-expanded="false" aria-label="What does Transcripts mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="earliest">Earliest<button class="info" type="button" data-info="dates"
        aria-expanded="false" aria-label="What do the dates mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="latest">Latest<span class="arrow">&#9650;</span></th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table>
</div>

<div class="sec"><h2>How this was built</h2></div>
<div class="prose">
__METHOD__
</div>

<footer>
  Generated __GENDATE__ from __N_TX__ transcripts of public appearances. Transcripts are automatic
  captions of publicly posted recordings; each quote is a brief excerpt linked to its source at the
  nearest timestamp. The transcripts, the raw model output and the candidates the verifier rejected
  are not published. The pipeline is open source at
  <a href="https://github.com/tonygwu/verbatim-index">github.com/tonygwu/verbatim-index</a>.
  Extraction run <code>__RUN_ID__</code>, contracts <code>__CONTRACT_ID__</code>.
</footer>
</div>

<div id="tip" role="tooltip" hidden></div>

<script>
const DATA = __DATA__;
const SRC = __SRC__;
const PRED = __PRED__;
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const CAT = {ai_capability:"AI capability", technology_product:"Technology & product", company_business:"Company & business",
  market_industry:"Market & industry", macro_economy:"Macro & economy", policy_regulation:"Policy & regulation",
  science:"Science", society:"Society", other:"Other"};
const TYPE = {numeric:"Numeric", milestone:"Milestone", binary_event:"Binary event", trend_direction:"Trend / direction", comparative:"Comparative", other:"Other"};
const HOR = {explicit:"Explicit date", inferable:"Inferable from context", none:"No date"};
const CTRL = {external:"External to the speaker", partial:"Partly under the speaker's control", own:"Under the speaker's own control"};

const INFO = {
  accepted: `<p><b>Accepted predictions.</b> How many forward-looking claims the pipeline accepted from this
    person's transcripts: the extractor proposed each one and an independent verifier agreed.</p>
    <p>A count of what was said, <b>not a measure of foresight</b>. Someone with more long-form
    appearances says more things. Nothing here has been checked against what happened.</p>`,
  h_explicit: `<p><b>Explicit date.</b> The quote itself names a date, year, quarter or dated event
    ("by 2030", "next year", "before the election"), so the claim carries a target date.</p>`,
  h_inferable: `<p><b>Inferable.</b> The quote names no date, but the surrounding transcript fixes one
    ("once the current fab is done"). The estimate is the model's and is labelled as such.</p>`,
  h_none: `<p><b>No date.</b> Falsifiable but open-ended: an event the speaker says will happen with no
    time anchor. Still a prediction; harder to resolve.</p>`,
  p_explicit: `<p><b>Stated probability.</b> The speaker gave a number, a percentage or odds ("70% chance",
    "one in three"). Shown as they said it. <b>No probability is ever inferred</b> from words like
    "very likely"; those count in the next column.</p>`,
  p_qual: `<p><b>Qualitative confidence.</b> The speaker used words of likelihood or certainty ("almost
    certainly", "I'd bet"), quoted verbatim on the card. Never converted to a number.</p>`,
  transcripts: `<p><b>Transcripts</b> holding at least one accepted prediction. The drawer says how many of
    this person's transcripts extraction ran on, so a low count can be read against its coverage.</p>`,
  dates: `<p><b>Earliest and latest</b> statement dates among this person's accepted predictions. The
    statement date is the recording's publication date, an upper bound on when it was said, unless
    the record says otherwise. Unknown dates sort last.</p>`,
};

const fmtDate = d => d ? d : "date unknown";
const pct = p => (p == null) ? null : Math.round(p * 100) + "%";
const ytLink = (vid, t) => vid && t != null ? `https://www.youtube.com/watch?v=${encodeURIComponent(vid)}&t=${t}s` : null;
const stale = s => s < 3600 ? Math.round(s / 60) + " min" : s < 172800 ? Math.round(s / 3600) + " h" : Math.round(s / 86400) + " days";

function marketLine(m){
  if (!m || m.status === "not_searched") return "";
  if (m.status === "matched" && m.exact){
    const e = m.exact;
    return `<div class="market"><b>${esc(pct(m.probability))}</b> contemporaneous market &middot; ${esc(e.platform)} &middot; exact match
      &middot; observed ${esc(stale(e.staleness_sec))} before publication${m.precision === "date" ? " (date-level cutoff)" : ""}
      &middot; <a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.question)}</a>
      <div class="why">${esc(e.rationale)}</div></div>`;
  }
  let h = "";
  for (const p of (m.proxies || [])){
    h += `<div class="market proxy">Related market (proxy, no probability shown) &middot; ${esc(p.platform)} &middot;
      <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.question)}</a><div class="why">${esc(p.rationale)}</div></div>`;
  }
  return h;
}

function predCard(r){
  const s = SRC[r.transcript_id] || {};
  const link = ytLink(s.video_id, r.t);
  const ts = link ? `<a class="ts" href="${esc(link)}" target="_blank" rel="noopener" aria-label="Open the video at ${esc(r.timestamp_mark)}">${esc(r.timestamp_mark)}</a>`
                  : `<span class="ts">${esc(r.timestamp_mark)}</span>`;
  const conf = r.confidence_type === "explicit_probability" ? `${esc(pct(r.probability))} &mdash; &ldquo;${esc(r.confidence_language)}&rdquo;`
             : r.confidence_type === "qualitative" ? `&ldquo;${esc(r.confidence_language)}&rdquo;` : "not specified";
  const target = r.target_date ? esc(r.target_date) + (r.target_date_text ? ` &mdash; &ldquo;${esc(r.target_date_text)}&rdquo;` : "")
               : r.target_date_text ? `&ldquo;${esc(r.target_date_text)}&rdquo;` : "none stated";
  return `<div class="pred" data-cat="${esc(r.category)}" data-type="${esc(r.prediction_type)}" data-hor="${esc(r.horizon)}" data-ctrl="${esc(r.subject_control)}">
    <div class="claim">${esc(r.claim)}</div>
    <ul class="quotes"><li>${ts}<q>${esc(r.quote)}</q></li></ul>
    <dl class="kv">
      <dt>Said</dt><dd>${esc(fmtDate(r.statement_date))}${r.statement_date ? ` <span class="why">(${esc(r.statement_date_basis.replace(/_/g, " "))})</span>` : ""}</dd>
      <dt>Target</dt><dd>${target}${r.horizon === "inferable" && r.horizon_years_inferred != null ? ` &middot; about ${esc(r.horizon_years_inferred)} years, inferred` : ""}</dd>
      <dt>Confidence</dt><dd>${conf}</dd>
      <dt>Category</dt><dd>${esc(CAT[r.category] || r.category)} &middot; ${esc(TYPE[r.prediction_type] || r.prediction_type)} &middot; ${esc(CTRL[r.subject_control] || r.subject_control)}</dd>
      <dt>Resolves if</dt><dd>${esc(r.resolution_criteria)}<br><span class="why">Verifier's reading: ${esc(r.verifier_criteria)}</span></dd>
      <dt>Status</dt><dd class="pending">Pending</dd>
      <dt>Source</dt><dd>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || r.transcript_id)}</a>` : esc(s.title || r.transcript_id)}${s.venue ? ` &middot; ${esc(s.venue)}` : ""}</dd>
    </dl>
    ${marketLine(r.market)}
    <details class="ctx"><summary>Show surrounding transcript</summary>
      <p>${esc(r.context_before)} <mark>${esc(r.quote)}</mark> ${esc(r.context_after)}</p></details>
    <div class="prov">extracted by ${esc(r.extractor)} &middot; verified by ${esc(r.verifier)} &middot; <code>${esc(r.prediction_id)}</code></div>
  </div>`;
}

function options(recs, key, labels){
  const vals = [...new Set(recs.map(r => r[key]))].sort();
  return `<option value="">all</option>` + vals.map(v => `<option value="${esc(v)}">${esc(labels[v] || v)}</option>`).join("");
}

function cards(slug, filt){
  const recs = (PRED[slug] || []).filter(r =>
    (!filt.cat || r.category === filt.cat) && (!filt.type || r.prediction_type === filt.type)
    && (!filt.hor || r.horizon === filt.hor) && (!filt.ctrl || r.subject_control === filt.ctrl));
  const groups = new Map();
  for (const r of recs){ if (!groups.has(r.transcript_id)) groups.set(r.transcript_id, []); groups.get(r.transcript_id).push(r); }
  let h = "";
  for (const [tid, rs] of groups){
    const s = SRC[tid] || {};
    h += `<div class="tcard"><div class="hdr"><span class="t">${esc(s.title || tid)}</span>
      <span class="meta">${esc(s.venue || "")}${rs[0].statement_date ? " &middot; " + esc(rs[0].statement_date) : ""}${s.url ? ` &middot; <a href="${esc(s.url)}" target="_blank" rel="noopener">source</a>` : ""}</span></div>`
      + rs.map(predCard).join("") + `</div>`;
  }
  return {html: h || `<p class="sub">No predictions match these filters.</p>`, n: recs.length};
}

function drawer(slug, person){
  const recs = PRED[slug] || [];
  const c = cards(slug, {});
  const cov = person.tx_attempted != null ? `; extraction ran on ${person.tx_succeeded} of ${person.tx_attempted} of their transcripts` : "";
  return `<div class="drawer" data-slug="${esc(slug)}">
    <h3>${esc(person.name)} &mdash; ${recs.length} accepted prediction${recs.length === 1 ? "" : "s"}</h3>
    <div class="sub">from ${person.transcripts} transcript${person.transcripts === 1 ? "" : "s"}${cov};
      ${person.rejected} candidate${person.rejected === 1 ? "" : "s"} rejected by the verifier and not shown.</div>
    <div class="filters">
      <label>Category <select class="pf" data-f="cat">${options(recs, "category", CAT)}</select></label>
      <label>Type <select class="pf" data-f="type">${options(recs, "prediction_type", TYPE)}</select></label>
      <label>Horizon <select class="pf" data-f="hor">${options(recs, "horizon", HOR)}</select></label>
      <label>Control <select class="pf" data-f="ctrl">${options(recs, "subject_control", CTRL)}</select></label>
      <span class="count">${c.n} shown</span>
    </div>
    <div class="cards">${c.html}</div>
  </div>`;
}

let sortKey = "name", sortDir = 1;
function render(){
  const rows = DATA.slice().sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (sortKey === "earliest" || sortKey === "latest"){
      if (x == null && y == null) return a.name.localeCompare(b.name);
      if (x == null) return 1;               // unknown dates always last
      if (y == null) return -1;
    }
    if (typeof x === "string" && typeof y === "string") return sortDir * x.localeCompare(y);
    return sortDir * ((x || 0) - (y || 0)) || a.name.localeCompare(b.name);
  });
  const tb = document.getElementById("tb");
  tb.innerHTML = rows.map(r => `<tr class="row" tabindex="0" data-slug="${esc(r.slug)}" aria-expanded="false">
    <td class="who"><div class="nm">${esc(r.name)}</div><div class="rl">${esc(r.role || "")}</div></td>
    <td class="org">${esc(r.company || "")}<span class="sector">${esc(r.sector || "")}</span></td>
    ${["accepted","h_explicit","h_inferable","h_none","p_explicit","p_qual","transcripts"].map(k => `<td class="num${r[k] ? "" : " zero"}">${r[k]}</td>`).join("")}
    <td class="date${r.earliest ? "" : " unknown"}">${esc(fmtDate(r.earliest))}</td>
    <td class="date${r.latest ? "" : " unknown"}">${esc(fmtDate(r.latest))}</td>
  </tr>`).join("");
}

const tip = document.getElementById("tip");
let tipBtn = null;
function hideTip(){
  if (!tipBtn) return;
  tipBtn.setAttribute("aria-expanded", "false");
  tipBtn = null;
  tip.hidden = true;
}
function showTip(btn){
  const body = INFO[btn.dataset.info];
  if (!body) return;
  if (tipBtn && tipBtn !== btn) tipBtn.setAttribute("aria-expanded", "false");
  tipBtn = btn;
  btn.setAttribute("aria-expanded", "true");
  tip.innerHTML = body;
  tip.hidden = false;
  const b = btn.getBoundingClientRect();
  const t = tip.getBoundingClientRect();
  const pad = 8;
  let left = b.left + b.width / 2 - t.width / 2;
  left = Math.max(pad, Math.min(left, window.innerWidth - t.width - pad));
  let top = b.bottom + 6;
  if (top + t.height > window.innerHeight - pad) top = b.top - t.height - 6;
  tip.style.left = left + "px";
  tip.style.top = Math.max(pad, top) + "px";
}
document.addEventListener("pointerover", e => {
  const btn = e.target.closest && e.target.closest("button.info");
  if (btn) showTip(btn);
  else if (tipBtn && !e.target.closest("#tip")) hideTip();
});
document.addEventListener("focusin", e => {
  const btn = e.target.closest && e.target.closest("button.info");
  if (btn) showTip(btn); else if (tipBtn) hideTip();
});
window.addEventListener("scroll", hideTip, true);
window.addEventListener("resize", hideTip);

document.addEventListener("click", e => {
  const info = e.target.closest("button.info");
  if (info){
    e.stopPropagation();
    if (tipBtn === info) hideTip(); else showTip(info);
    return;
  }
  if (tipBtn) hideTip();
  if (e.target.closest("tr.audit")) return;          // links, selects and details inside a drawer never toggle it
  const th = e.target.closest("thead th");
  if (th && th.dataset.k){
    const k = th.dataset.k;
    sortDir = sortKey === k ? -sortDir : (k === "name" || k === "company" || k === "earliest" ? 1 : -1);
    sortKey = k;
    document.querySelectorAll("thead th").forEach(x => x.removeAttribute("aria-sort"));
    th.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
    document.querySelectorAll("tr.audit").forEach(x => x.remove());
    render();
    return;
  }
  const tr = e.target.closest("tr.row");
  if (!tr) return;
  const nxt = tr.nextElementSibling;
  if (nxt && nxt.classList.contains("audit")){ nxt.remove(); tr.setAttribute("aria-expanded", "false"); return; }
  document.querySelectorAll("tr.audit").forEach(x => x.remove());
  document.querySelectorAll("tr.row[aria-expanded='true']").forEach(x => x.setAttribute("aria-expanded", "false"));
  const slug = tr.dataset.slug;
  const person = DATA.find(d => d.slug === slug);
  const row = document.createElement("tr");
  row.className = "audit";
  row.innerHTML = `<td colspan="11">${drawer(slug, person)}</td>`;
  tr.after(row);
  tr.setAttribute("aria-expanded", "true");
});
document.addEventListener("change", e => {
  const sel = e.target.closest && e.target.closest("select.pf");
  if (!sel) return;
  const d = sel.closest(".drawer");
  const filt = {};
  d.querySelectorAll("select.pf").forEach(s => { filt[s.dataset.f] = s.value; });
  const c = cards(d.dataset.slug, filt);
  d.querySelector(".cards").innerHTML = c.html;
  d.querySelector(".count").textContent = `${c.n} shown`;
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && tipBtn){ const b = tipBtn; hideTip(); b.blur(); return; }
  if (e.key === "Enter" && e.target.classList && e.target.classList.contains("row")) e.target.click();
});
document.getElementById("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const dark = cur ? cur === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
});
render();
</script>
"""


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------

def ts_seconds(mark: str | None) -> int | None:
    return L.mark_seconds(mark)


def load_records(pred_dir: Path) -> dict:
    """Accepted records plus counts taken BEFORE any filter, so staleness is checkable."""
    files = sorted(p for p in pred_dir.glob("*/*.jsonl") if not p.parent.name.startswith("_"))
    accepted, rejected, lines, runs = [], 0, 0, set()
    for f in files:
        for r in L.parse_lines(f.read_text(), str(f)):
            lines += 1
            runs.add(r["extraction"]["run_id"])
            if r["accepted"]:
                accepted.append(r)
            elif r["extraction"]["qualifies"] and r["verification"]["status"] == "ok":
                rejected += 1
    return {"accepted": accepted, "files_read": len(files), "lines_read": lines, "rejected": rejected, "run_ids": sorted(runs)}


def model_label(m: str | None) -> str:
    if not m:
        return "unknown"
    for k, v in MODEL_LABELS.items():
        if m.startswith(k):
            return v
    return m


def trim_market(c: dict) -> dict | None:
    """The public projection of the consensus block: status, the exact match's number and where it came from, proxies as links."""
    st = c.get("status", "not_searched")
    if st == "not_searched":
        return None
    out = {"status": st, "probability": c.get("market_probability"), "precision": (c.get("cutoff") or {}).get("precision"), "exact": None, "proxies": []}
    em = c.get("exact_match")
    if st == "matched" and em and em.get("observation"):
        out["exact"] = {"platform": PLATFORM_LABELS.get(em["platform"], em["platform"]), "question": em["question"], "url": em["market_url"],
                        "observed_at": em["observation"]["observed_at_utc"], "staleness_sec": em["observation"]["staleness_sec"],
                        "match_confidence": em["match_confidence"], "rationale": em["rationale"]}
    for p in c.get("proxy_matches") or []:
        out["proxies"].append({"platform": PLATFORM_LABELS.get(p["platform"], p["platform"]), "question": p["question"],
                               "url": p["market_url"], "rationale": p["rationale"]})
    return out


def trim(rec: dict) -> dict:
    """What the page needs and nothing else. Dropped: char offsets, status, accepted, telemetry, per-gate verifier booleans, harness/run internals."""
    s, p, c, x, v = rec["source"], rec["prediction"], rec["confidence"], rec["extraction"], rec["verification"]
    return {
        "prediction_id": rec["prediction_id"], "transcript_id": rec["transcript_id"],
        "statement_date": s["statement_date"], "statement_date_basis": s["statement_date_basis"],
        "quote": s["quote_original"], "timestamp_mark": s["timestamp_mark"], "t": ts_seconds(s["timestamp_mark"]),
        "context_before": s["context_before"], "context_after": s["context_after"],
        "claim": p["normalized_claim"], "category": p["category"], "prediction_type": p["prediction_type"],
        "target_date": p["target_date"], "target_date_text": p["target_date_text"], "horizon": p["horizon"],
        "horizon_years_inferred": p["horizon_years_inferred"], "resolution_criteria": p["resolution_criteria"],
        "specificity": p["specificity"], "subject_control": p["subject_control"],
        "confidence_type": c["type"], "probability": c["probability"], "confidence_language": c["verbatim_confidence_language"],
        "extractor": model_label(x["served_model"] or x["requested_model"]),
        "verifier": model_label(v["served_model"] or v["requested_model"]),
        "verifier_criteria": v["verifier_resolution_criteria"],
        "market": trim_market(rec["consensus"]),
    }


def src_map(records: list[dict]) -> dict:
    out = {}
    for r in records:
        out.setdefault(r["transcript_id"], {"title": r["source"]["title"], "venue": r["source"]["venue"],
                                            "url": r["source"]["url"], "video_id": r["source"]["video_id"]})
    return out


def person_rows(index: dict, roster: dict) -> list[dict]:
    rows = []
    for l in index["leaders"]:
        entry = roster.get(l["slug"], {})
        rows.append({
            "slug": l["slug"], "name": l["name"], "role": entry.get("role") or l.get("role"), "company": l.get("company") or entry.get("company"),
            "sector": l.get("sector") or entry.get("sector"),
            "accepted": l["accepted"], "rejected": l["rejected_by_verifier"],
            "h_explicit": l["by_horizon"].get("explicit", 0), "h_inferable": l["by_horizon"].get("inferable", 0), "h_none": l["by_horizon"].get("none", 0),
            "p_explicit": l["explicit_probability"], "p_qual": l["qualitative_confidence"],
            "transcripts": l["transcripts_with_accepted"], "earliest": l["earliest_statement_date"], "latest": l["latest_statement_date"],
            "tx_attempted": l["transcripts_on_disk"] or None, "tx_succeeded": l["transcripts_extracted"],
            "by_category": l["by_category"], "by_type": l["by_prediction_type"],
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def check_index_matches_disk(index: dict, by_slug: dict[str, list[dict]]) -> None:
    """A table saying 9 over a drawer showing 12 is the render-integrity failure this repo already paid for once."""
    for l in index["leaders"]:
        have = len(by_slug.get(l["slug"], []))
        if have != l["accepted"]:
            raise SystemExit(f"index.json says {l['slug']} has {l['accepted']} accepted predictions but the files hold {have}; "
                             f"re-run aggregate_predictions.py")


def safe_json(obj) -> str:
    """A quote can contain '</script>'; inside a script block that would end it."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def nice_date(iso: str) -> str:
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%-d %B %Y")


def build_method(index: dict, loaded: dict) -> str:
    c, cov = index["corpus"], index["coverage"]
    ex = ", ".join(model_label(m) for m in c["extractor_models"]) or "unknown"
    ve = ", ".join(model_label(m) for m in c["verifier_models"]) or "unknown"
    cats = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in sorted(c["by_category"].items(), key=lambda kv: -kv[1]))
    cons = c.get("consensus_by_status", {})
    dated = c["accepted"] - c["statement_date_unknown"]
    e = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    reviewed = c["accepted"] + c["rejected_by_verifier"]
    acceptance = (
        f"Verifier acceptance: {e(c['accepted'])} of {e(reviewed)} extractor-proposed candidates reviewed "
        f"({e(round(c['accepted'] / reviewed * 100))}%)."
        if reviewed else "Verifier acceptance: not yet measured (no extractor-proposed candidates reviewed)."
    )
    parts = [
        f"<h3>Where the predictions come from</h3>",
        f"<p>Extraction ran on {e(cov['extract'].get('ok', 0))} transcripts and failed on {e(cov['extract'].get('failed', 0))}; "
        f"{e(cov['extract'].get('excluded', 0))} were excluded as recordings of the wrong person. One model, chosen per transcript by "
        f"measured quota ({e(ex)}), read the whole transcript and proposed candidates that pass five gates: forward-looking, "
        f"falsifiable (it must write the observation that would show the claim wrong), committed rather than hedged, in the "
        f"speaker's own voice, and intelligible on its own. Every quote was then matched mechanically against the transcript; "
        f"{e(cov['ungrounded_candidates_total'])} candidates that did not match exactly were discarded.</p>",
        f"<p>A second, independent model family ({e(ve)}) then re-judged each candidate from a window of about "
        f"{e(L.CONTEXT_WORDS)} words on each side of the quote and the extractor's one-sentence claim, without seeing the extractor's "
        f"reasoning. Of {e(c['candidates'])} candidates written, {e(c['accepted'])} were accepted by both and "
        f"{e(c['rejected_by_verifier'])} were rejected by the verifier; {e(c['verification_pending'])} await verification. "
        f"{acceptance}</p>",
        f"<h3>What is recorded</h3>",
        f"<p>Each record keeps the verbatim span at its character offsets, the nearest timestamp, {e(L.CONTEXT_WORDS)} words of "
        f"context each side, a normalized claim, the extractor's and the verifier's resolution criteria, a time horizon "
        f"(explicit for {e(c['by_horizon'].get('explicit', 0))}, inferable for {e(c['by_horizon'].get('inferable', 0))}, none for "
        f"{e(c['by_horizon'].get('none', 0))}), and the speaker's own confidence: a stated number for "
        f"{e(c['explicit_probability'])}, words of likelihood for {e(c['qualitative_confidence'])}, nothing for the rest. "
        f"Categories observed: {e(cats)}.</p>",
        f"<p>The statement date is the recording's publication date, which is an upper bound on when the words were said; "
        f"{e(dated)} of {e(c['accepted'])} accepted predictions carry one. Predictions under the speaker's own control "
        f"(roadmaps, guidance) are kept and tagged ({e(c['by_subject_control'].get('own', 0))} of them) so a reader can set them aside.</p>",
    ]
    if cons and set(cons) - {"not_searched"}:
        parts.append(
            f"<h3>Contemporaneous markets</h3>"
            f"<p>For accepted predictions, Polymarket and Kalshi were searched through their public APIs for a contract about the "
            f"same proposition. A model judged only whether a contract matches; the price is read from the market's own history "
            f"as the latest observation strictly before the publication date, never a current price. Only an exact match shows a "
            f"number; related markets are linked without one. Results: "
            + e(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(cons.items()))) + ". The speaker's stated confidence is never changed by a market.</p>")
    parts.append(
        "<!-- disclaimer:start -->"
        "<div class=\"callout\"><b>What this page is not.</b> No prediction here has been resolved against what happened. "
        "There is no accuracy figure, no Brier score, no market edge and no ranking of forecasters, and none will be "
        "read into these counts: a person with more long-form appearances has more predictions. The extractor and the "
        "verifier are language models; their agreement is evidence that a sentence is a prediction, not that it is "
        "right. Resolution and any scoring are separate, later work.</div>"
        "<!-- disclaimer:end -->")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="data/predictions/index.json")
    ap.add_argument("--predictions", default="data/predictions")
    ap.add_argument("--roster", default="data/roster/final.json")
    ap.add_argument("--out", default="site-predictions/index.html")
    args = ap.parse_args(argv)

    index = json.loads(Path(args.index).read_text())
    for k in ("generated_at_utc", "run_ids_seen", "contracts_seen", "leaders", "corpus", "coverage", "files_read", "records_read"):
        if k not in index:
            raise SystemExit(f"index.json lacks {k}; re-run aggregate_predictions.py")
    roster = {r["slug"]: r for r in json.loads(Path(args.roster).read_text())["roster"]}
    loaded = load_records(Path(args.predictions))
    by_slug: dict[str, list[dict]] = {}
    for r in loaded["accepted"]:
        by_slug.setdefault(r["leader_slug"], []).append(r)
    check_index_matches_disk(index, by_slug)
    rows = person_rows(index, roster)
    pred = {slug: [trim(r) for r in sorted(rs, key=lambda r: (r["source"]["statement_date"] or "", r["transcript_id"], L.record_sort_key(r)))]
            for slug, rs in sorted(by_slug.items())}
    src = src_map(loaded["accepted"])
    c = index["corpus"]
    ex = " / ".join(model_label(m) for m in c["extractor_models"]) or "none yet"
    ve = " / ".join(model_label(m) for m in c["verifier_models"]) or "none yet"
    dated = c["accepted"] - c["statement_date_unknown"]
    contracts = ", ".join(sorted(set(index["contracts_seen"]["extraction"]) | set(index["contracts_seen"]["verification"]))) or "none"
    data_js, src_js, pred_js = safe_json(rows), safe_json(src), safe_json(pred)
    html_out = (TEMPLATE
        .replace("__FONTS__", FONT_LINKS)
        .replace("__THEME__", THEME_CSS)
        .replace("__DATA__", data_js)
        .replace("__SRC__", src_js)
        .replace("__PRED__", pred_js)
        .replace("__METHOD__", build_method(index, loaded))
        .replace("__GENDATE__", nice_date(index["generated_at_utc"]))
        .replace("__N_PEOPLE__", str(len(rows)))
        .replace("__N_TX__", str(index["coverage"]["extract"].get("ok", 0)))
        .replace("__N_ACCEPTED__", str(c["accepted"]))
        .replace("__PCT_DATED__", str(round(100 * dated / c["accepted"])) if c["accepted"] else "0")
        .replace("__N_PROB__", str(c["explicit_probability"]))
        .replace("__EXTRACTOR__", ex)
        .replace("__VERIFIER__", ve)
        .replace("__RUN_ID__", ", ".join(index["run_ids_seen"][-3:]) or "none")
        .replace("__CONTRACT_ID__", contracts))
    write_atomic(args.out, html_out)
    ctx = [len(r["context_before"]) + len(r["context_after"]) for rs in pred.values() for r in rs]
    print(f"wrote {args.out}  ({len(html_out) // 1024} KB; DATA {len(data_js) // 1024} KB, SRC {len(src_js) // 1024} KB, "
          f"PRED {len(pred_js) // 1024} KB; {len(rows)} people, {c['accepted']} accepted, {loaded['rejected']} rejected not embedded; "
          f"context chars median {int(statistics.median(ctx)) if ctx else 0} max {max(ctx) if ctx else 0})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
