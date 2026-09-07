#!/usr/bin/env python3
"""Render the leaderboard HTML from results.json and results_audit.json.

The page is self-contained apart from Google Fonts. Data is embedded as JSON
so the table can sort and the audit drawers can open without a server.

Usage:
  build_site.py --results data/results.json --audit data/results_audit.json \
      --roster data/roster/final.json --calibration data/logs/calibration.json \
      --out site/index.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# scripts/ is not a package, and this module is also loaded by importlib in the
# test harness, so make the sibling import work in both cases.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402

TEMPLATE = r"""<title>Verbatim Index</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{
  --ground:#F2F3F5; --surface:#FCFCFB; --surface-2:#E9EBEF;
  --ink:#15181D; --ink-2:#3C4450; --muted:#5B646F; --faint:#8A929C;
  --rule:#DCDFE5; --rule-strong:#C3C8D1;
  --d1:#2E6FC9; --d2:#BA5416; --d3:#00875A;
  /* Overall is deliberately achromatic. It is a summary of the other three,
     so giving it a fourth hue would read as a fourth dimension, and the old
     maroon was the Insight hue exactly. */
  --d0:#6B7280; --d0-soft:#9CA3AF;
  --d1-wash:#2E6FC91A; --d2-wash:#BA54161A; --d3-wash:#00875A1A;
  --warn:#9A6700; --bad:#A33A2A;
  --shadow:0 1px 2px #15181D0F, 0 4px 16px #15181D0A;
}
:root:not([data-theme="light"]){
  @media (prefers-color-scheme: dark){
    --ground:#121417; --surface:#1B1E23; --surface-2:#23272E;
    --ink:#E9ECF1; --ink-2:#C3C9D2; --muted:#9AA3AE; --faint:#6E7883;
    --rule:#2C3138; --rule-strong:#3B424B;
    --d1:#5A96DE; --d2:#D2702C; --d3:#2E9C6E;
    --d0:#9AA3B2; --d0-soft:#6F7787;
    --d1-wash:#5A96DE26; --d2-wash:#D2702C26; --d3-wash:#2E9C6E26;
    --warn:#D9A441; --bad:#E0806F;
    --shadow:0 1px 2px #00000040, 0 4px 16px #00000030;
  }
}
:root[data-theme="dark"]{
  --ground:#121417; --surface:#1B1E23; --surface-2:#23272E;
  --ink:#E9ECF1; --ink-2:#C3C9D2; --muted:#9AA3AE; --faint:#6E7883;
  --rule:#2C3138; --rule-strong:#3B424B;
  --d1:#5A96DE; --d2:#D2702C; --d3:#2E9C6E;
  --d0:#9AA3B2; --d0-soft:#6F7787;
  --d1-wash:#5A96DE26; --d2-wash:#D2702C26; --d3-wash:#2E9C6E26;
  --warn:#D9A441; --bad:#E0806F;
  --shadow:0 1px 2px #00000040, 0 4px 16px #00000030;
}
*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.55; margin:0;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1220px; margin:0 auto; padding:0 24px 96px}
a{color:var(--d1)}
h1,h2,h3{text-wrap:balance; margin:0}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums}

/* ---------- masthead ---------- */
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
.thesis{
  max-width:62ch; margin-top:18px; font-size:17px; color:var(--ink-2);
}
.thesis strong{color:var(--ink); font-weight:600}

/* ---------- method strip ---------- */
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

/* ---------- section headings ---------- */
.sec{margin:52px 0 18px}
.sec h2{
  font-family:"Instrument Serif",Georgia,serif; font-weight:400;
  font-size:30px; letter-spacing:-.01em;
}
.sec p{margin:8px 0 0; color:var(--muted); max-width:70ch; font-size:14px}

/* ---------- table ---------- */
.tablecard{
  background:var(--surface); border:1px solid var(--rule);
  border-radius:3px; box-shadow:var(--shadow); overflow-x:auto;
}
/* The natural width of every column below adds up to less than .wrap, so the
   card does not scroll sideways on a desktop. overflow-x on .tablecard is the
   fallback for a narrow window, not the normal state. */
table{border-collapse:collapse; width:100%; min-width:1120px; table-layout:fixed}
thead th{
  position:sticky; top:0; z-index:2; background:var(--surface);
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; font-weight:500;
  letter-spacing:.06em; text-transform:uppercase; color:var(--muted);
  text-align:center; padding:14px 7px 11px; border-bottom:1px solid var(--rule-strong);
  white-space:nowrap; cursor:pointer; user-select:none;
}
thead th:hover{color:var(--ink)}
/* The interval header is a scale, not a sort key. */
thead th.nosort{cursor:default}
thead th.nosort:hover{color:var(--muted)}
thead th .arrow{opacity:.35; margin-left:3px; font-size:9px}
thead th[aria-sort] .arrow{opacity:1; color:var(--d2)}
tbody tr.row{border-bottom:1px solid var(--rule); cursor:pointer}
tbody tr.row:hover{background:var(--surface-2)}
tbody tr.row:focus-visible{outline:2px solid var(--d1); outline-offset:-2px}
td{padding:11px 7px; vertical-align:middle}
td.num{text-align:right; font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums}

/* rank + tie bracket: ranks the method cannot separate are bracketed together */
td.rank{
  width:62px; padding-left:16px; position:relative;
  font-family:"IBM Plex Mono",monospace; font-size:15px; color:var(--muted);
  font-variant-numeric:tabular-nums;
}
td.rank .tie{
  position:absolute; left:6px; top:0; bottom:0; width:5px;
  border-left:1.5px solid var(--rule-strong);
}
tr.tie-start td.rank .tie{border-top:1.5px solid var(--rule-strong); top:6px}
tr.tie-end td.rank .tie{border-bottom:1.5px solid var(--rule-strong); bottom:6px}

.who{width:180px}
.who .nm{font-weight:600; letter-spacing:-.01em}
.who .rl{font-size:12px; color:var(--muted); margin-top:1px}
td.org{color:var(--ink-2); font-size:13.5px; width:142px}
td.org .sector{
  display:block; font-family:"IBM Plex Mono",monospace; font-size:10px;
  letter-spacing:.06em; text-transform:uppercase; color:var(--faint); margin-top:2px;
}

/* score cells: number plus a thin meter, one hue per dimension */
.score{display:flex; align-items:center; justify-content:flex-end; gap:9px}
.score .v{
  font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:14px; font-weight:500; min-width:30px; text-align:right;
}
.meter{width:42px; height:5px; border-radius:2px; background:var(--surface-2); overflow:hidden; flex:none}
.meter i{display:block; height:100%; border-radius:2px}
.m1 i{background:var(--d1)} .m2 i{background:var(--d2)} .m3 i{background:var(--d3)}
td.overall{background:var(--surface-2)}

/* Overall is two cells: the score, then its 95% interval.

   The score gets its own cell and is left-aligned, so the digits line up down
   the column. Previously it shared a cell with the band and drifted with it.

   The interval is a dot plot on ONE scale shared by every row. The x position
   of a dot means the same thing in row 1 and row 40, so intervals can be
   compared by eye without reading a single number, and the faint rules behind
   them are a ruler the eye can trace down the column.

   Three earlier layouts failed and are recorded so they are not retried. A
   per-row band scaled at fixed pixels-per-point made every interval start at
   the same place, so a high score and a low score drew the same picture. An
   absolute 0-100 domain collapsed a typical 7-point interval into a few
   pixels. Endpoint labels centred under their dots overlapped into "70.574.7".
   The domain is now the data's own range, rounded out to a multiple of 5, and
   the exact endpoints live in the cell's tooltip instead of beside the dots. */
td.oscore{
  text-align:left; padding-left:10px; padding-right:2px;
  font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums;
}
td.oscore .v{font-size:18px; font-weight:600; color:var(--ink)}
td.oci{position:relative; padding-left:12px; padding-right:12px}

/* The rules span the whole cell box, top to bottom, so adjacent rows join them
   into continuous verticals down the column. */
.ci-grid{position:absolute; left:12px; right:12px; top:0; bottom:0; pointer-events:none}
.ci-grid i{position:absolute; top:0; bottom:0; width:1px; background:var(--rule)}
.ci-track{position:relative; display:block; height:12px}
.ci-track .rule{
  position:absolute; top:5px; height:2px; border-radius:1px;
  background:var(--d0); opacity:.55;
}
.ci-track .dot{
  position:absolute; top:2.5px; width:7px; height:7px; margin-left:-3.5px;
  border-radius:50%; background:var(--surface);
  border:1.5px solid var(--d0); box-sizing:border-box;
}
.ci-track .pt{
  position:absolute; top:0; width:2px; height:12px; margin-left:-1px;
  border-radius:1px; background:var(--ink-2);
}
.ci-none{color:var(--faint); font-size:11px}

/* The axis under the interval header, on the same coordinates as the rules. */
th.ocih{padding-left:12px; padding-right:12px}
.ci-axis{position:relative; display:block; height:11px; margin-top:6px}
.ci-axis i{
  position:absolute; transform:translateX(-50%); font-style:normal;
  font-size:9px; letter-spacing:.02em; color:var(--faint); line-height:1;
}

.pill{
  display:inline-block; font-family:"IBM Plex Mono",monospace; font-size:10px;
  letter-spacing:.05em; text-transform:uppercase; padding:2px 6px;
  border-radius:2px; border:1px solid var(--rule-strong); color:var(--muted);
}
.pill.low{color:var(--bad); border-color:currentColor}
.pill.medium{color:var(--warn); border-color:currentColor}
.halo{font-size:13px}
.halo.pos{color:var(--d2)} .halo.neg{color:var(--d3)}

/* ---------- (?) affordance + shared tooltip ----------
   The tooltip is a single element on <body>, positioned with position:fixed.
   It cannot live inside the header cell: .tablecard sets overflow-x:auto, so
   overflow-y computes to auto as well and would clip any popover drawn there. */
button.info{
  all:unset; box-sizing:border-box; display:inline-grid; place-items:center;
  width:14px; height:14px; margin-left:5px; border-radius:50%;
  border:1px solid var(--rule-strong); color:var(--muted);
  font-family:"IBM Plex Sans",system-ui,sans-serif;
  font-size:9px; font-weight:600; line-height:1; letter-spacing:0;
  text-transform:none; cursor:help; vertical-align:middle; flex:none;
}
button.info:hover,button.info[aria-expanded="true"]{
  color:var(--surface); background:var(--d1); border-color:var(--d1);
}
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
#tip .k{font-family:"IBM Plex Mono",monospace; font-weight:600}
#tip .k.pos{color:var(--d2)} #tip .k.neg{color:var(--d3)}
#tip p{margin:0 0 7px}
#tip p:last-child{margin-bottom:0}
#tip .note{color:var(--muted); font-size:11.5px}

/* ---------- audit drawer ---------- */
tr.audit>td{padding:0; background:var(--surface-2); border-bottom:1px solid var(--rule-strong)}
.drawer{padding:20px 22px 26px}
.drawer h3{
  font-family:"Instrument Serif",Georgia,serif; font-size:21px; font-weight:400;
  margin-bottom:3px;
}
.drawer .sub{font-size:12.5px; color:var(--muted); margin-bottom:18px}
.tcard{
  background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  padding:15px 17px; margin-bottom:12px;
}
.tcard .hdr{
  display:flex; flex-wrap:wrap; gap:10px; align-items:baseline;
  padding-bottom:9px; margin-bottom:11px; border-bottom:1px solid var(--rule);
}
.tcard .hdr .t{font-weight:600; font-size:14px}
.tcard .hdr .meta{
  font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--muted);
  margin-left:auto; text-align:right;
}
.judgegrid{display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px}
.judge{border-left:2px solid var(--rule-strong); padding-left:13px}
.judge>.name{
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.09em;
  text-transform:uppercase; color:var(--muted); margin-bottom:10px;
}
.dim{margin-bottom:13px}
.dim .dh{display:flex; align-items:baseline; gap:8px; margin-bottom:4px}
.dim .dh b{
  font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.06em;
  text-transform:uppercase; font-weight:500;
}
.dim.k1 .dh b{color:var(--d1)} .dim.k2 .dh b{color:var(--d2)} .dim.k3 .dh b{color:var(--d3)}
.dim .dh .s{
  font-family:"IBM Plex Mono",monospace; font-size:14px; font-weight:600;
  margin-left:auto; font-variant-numeric:tabular-nums;
}
.dim .why{font-size:13px; color:var(--ink-2); line-height:1.5}
.dim .counter{
  font-size:12.5px; color:var(--muted); margin-top:6px; padding-left:9px;
  border-left:1.5px solid var(--rule-strong);
}
.dim .counter em{
  font-family:"IBM Plex Mono",monospace; font-style:normal; font-size:10px;
  letter-spacing:.07em; text-transform:uppercase; color:var(--faint);
  display:block; margin-bottom:2px;
}
.quotes{margin:7px 0 0; padding:0; list-style:none; display:flex; flex-direction:column; gap:5px}
.quotes li{font-size:12.5px; color:var(--ink-2); display:flex; gap:8px}
.quotes .ts{
  font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--faint);
  flex:none; padding-top:1px;
}
.quotes q{font-style:italic}
.flags{margin-top:11px; font-size:12.5px}
.flags .lbl{
  font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.07em;
  text-transform:uppercase; color:var(--bad); margin-bottom:3px;
}
.flags ul{margin:0; padding-left:17px; color:var(--ink-2)}
.flags li{margin-bottom:2px}

/* ---------- prose ---------- */
.prose{max-width:72ch}
.prose h3{
  font-size:15px; font-weight:600; margin:22px 0 6px; letter-spacing:-.005em;
}
.prose p{margin:0 0 11px; color:var(--ink-2); font-size:14.5px}
.prose ul{margin:0 0 11px; padding-left:19px; color:var(--ink-2); font-size:14.5px}
.prose li{margin-bottom:5px}
.prose code{
  font-family:"IBM Plex Mono",monospace; font-size:12.5px;
  background:var(--surface-2); padding:1px 4px; border-radius:2px;
}
.callout{
  border-left:2px solid var(--d2); background:var(--surface);
  padding:14px 17px; margin:16px 0; border-radius:0 3px 3px 0; font-size:14px;
}
.callout b{color:var(--ink)}
.legend{display:flex; flex-wrap:wrap; gap:16px; margin:14px 0 0; font-size:12.5px; color:var(--muted)}
.legend span{display:flex; align-items:center; gap:6px}
.legend i{width:11px; height:11px; border-radius:2px; display:block}
footer{
  margin-top:60px; padding-top:20px; border-top:1px solid var(--rule);
  font-size:12.5px; color:var(--faint);
}
.toggle{
  position:fixed; top:14px; right:14px; z-index:9;
  font-family:"IBM Plex Mono",monospace; font-size:11px; letter-spacing:.06em;
  background:var(--surface); color:var(--muted); border:1px solid var(--rule-strong);
  border-radius:2px; padding:6px 10px; cursor:pointer;
}
.toggle:hover{color:var(--ink)}
@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
</style>

<button class="toggle" id="themeBtn" type="button">THEME</button>
<div class="wrap">

<header class="mast">
  <div class="eyebrow">__RUNDATE__ &middot; Blinded transcripts &middot; Two independent judges</div>
  <h1>Verbatim <em>Index</em></h1>
  <p class="thesis">
    __N_LEADERS__ technology leaders, ranked on the thinking their public speech actually demonstrates.
    Every score comes from <strong>verbatim transcripts alone</strong> &mdash; no company results,
    no market capitalisation, no reputation. Two frontier models graded each transcript independently
    against a 15-criterion rubric, and every score below carries the written reasoning behind it.
  </p>
</header>

<dl class="strip">
  <div><dt>Leaders</dt><dd>__N_LEADERS__</dd></div>
  <div><dt>Transcripts</dt><dd>__N_TRANSCRIPTS__</dd></div>
  <div><dt>Words graded</dt><dd>__N_WORDS__</dd></div>
  <div><dt>Judge calls</dt><dd>__N_CALLS__</dd></div>
  <div><dt>Tie band</dt><dd>&plusmn;__TIEBAND__<small>pts</small></dd></div>
  <div><dt>Judge agreement</dt><dd>__CORR__<small>r</small></dd></div>
</dl>

<div class="sec">
  <h2>The ranking</h2>
  <p>
    Click any row to read the judges' reasoning and the evidence they cited. Sort by any column.
    Ranks joined by a bracket in the left margin are <strong>statistically tied</strong>: repeat
    grading of an unchanged transcript moves the overall score by about __NOISE__ points, so gaps
    smaller than __TIEBAND__ points do not separate two leaders.
  </p>
  <div class="legend">
    <span><i style="background:var(--d2)"></i> Insight &mdash; 45% of Overall</span>
    <span><i style="background:var(--d3)"></i> Technical depth &mdash; 35%</span>
    <span><i style="background:var(--d1)"></i> Clarity &mdash; 20%</span>
  </div>
</div>

<div class="tablecard">
  <table id="board">
    <colgroup>
      <col style="width:46px"><col style="width:180px"><col style="width:142px">
      <col style="width:96px"><col style="width:96px"><col style="width:96px">
      <col style="width:76px"><col><col style="width:96px">
      <col style="width:70px"><col style="width:96px">
    </colgroup>
    <thead><tr>
      <th data-k="rank">#<span class="arrow">&#9650;</span></th>
      <th data-k="name">Leader<span class="arrow">&#9650;</span></th>
      <th data-k="company">Organisation<span class="arrow">&#9650;</span></th>
      <th data-k="d2">Insight<span class="arrow">&#9650;</span></th>
      <th data-k="d3">Technical<span class="arrow">&#9650;</span></th>
      <th data-k="d1">Clarity<span class="arrow">&#9650;</span></th>
      <th data-k="overall">Overall<span class="arrow">&#9650;</span></th>
      <th class="nosort ocih">95% interval<button class="info" type="button" data-info="ci"
        aria-expanded="false" aria-label="What is the 95% interval?">?</button><span class="ci-axis" id="ciaxis"></span></th>
      <th data-k="n">Transcripts<span class="arrow">&#9650;</span></th>
      <th data-k="halo">Halo<button class="info" type="button" data-info="halo"
        aria-expanded="false" aria-label="What does Halo mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="conf">Confidence<span class="arrow">&#9650;</span></th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table>
</div>

<div class="sec"><h2>How this was measured</h2></div>
<div class="prose">
__METHOD__
</div>

<footer>
  Generated __RUNDATE__ from __N_TRANSCRIPTS__ transcripts of public appearances.
  Transcripts are automatic captions of publicly posted recordings; quoted fragments are brief
  excerpts cited as evidence for a score, each linked to its source. Scores describe one body of
  recorded speech, not a person.
  The rubric, pipeline and grading harness are open source at
  <a href="https://github.com/tonygwu/verbatim-index">github.com/tonygwu/verbatim-index</a>;
  the transcripts and raw grades are not published.
</footer>
</div>

<div id="tip" role="tooltip" hidden></div>

<script>
const DATA = __DATA__;
const AUDIT = __AUDIT__;
const TIE = __TIEBAND__;
const DIMS = [["d2","Insight","k2"],["d3","Technical depth","k3"],["d1","Clarity","k1"]];
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* The 95% interval, drawn on ONE scale shared by every row.

   CI_DOM is the domain: the lowest ci_low and the highest ci_high in the whole
   table, each rounded outward to a multiple of 5. It is derived from the data
   rather than fixed at 0-100, because 0-100 wasted two thirds of the width and
   squeezed a typical interval into four pixels. It is derived once, from the
   full DATA array and not from the sorted rows, so sorting a column never
   moves a dot.

   CI_TICKS are the round scores inside the domain. They label the axis in the
   header and draw the faint rules behind every row. */
const CI_DOM = (() => {
  const lo = DATA.map(r => r.ci_low).filter(v => v != null);
  const hi = DATA.map(r => r.ci_high).filter(v => v != null);
  if (!lo.length || !hi.length) return null;
  const a = Math.floor(Math.min(...lo) / 5) * 5, b = Math.ceil(Math.max(...hi) / 5) * 5;
  return b > a ? {lo: a, hi: b} : null;
})();
const CI_TICKS = (() => {
  if (!CI_DOM) return [];
  const out = [];
  for (let v = Math.ceil(CI_DOM.lo / 10) * 10; v < CI_DOM.hi; v += 10)
    if (v > CI_DOM.lo) out.push(v);
  return out;
})();
const ciPct = v => ((v - CI_DOM.lo) / (CI_DOM.hi - CI_DOM.lo)) * 100;
const CI_GRID = CI_DOM
  ? `<span class="ci-grid" aria-hidden="true">`
    + CI_TICKS.map(t => `<i style="left:${ciPct(t).toFixed(3)}%"></i>`).join("")
    + `</span>`
  : "";

/* The endpoints are not printed beside the dots. On a shared scale they would
   sit at a different x in every row and fight the alignment the scale exists
   to give. They are in the cell's tooltip instead. */
function ciPlot(v, lo, hi){
  if (!CI_DOM || v == null || lo == null || hi == null)
    return CI_GRID + `<span class="ci-none">&mdash;</span>`;
  const a = ciPct(lo), b = ciPct(hi), pt = ciPct(v);
  const t = esc(`${v.toFixed(1)} \u2014 95% interval ${lo.toFixed(1)} to ${hi.toFixed(1)}`);
  return CI_GRID
    + `<span class="ci-track" title="${t}" role="img" aria-label="${t}">`
    +   `<span class="rule" style="left:${a.toFixed(3)}%; width:${(b - a).toFixed(3)}%"></span>`
    +   `<span class="dot" style="left:${a.toFixed(3)}%"></span>`
    +   `<span class="dot" style="left:${b.toFixed(3)}%"></span>`
    +   `<span class="pt" style="left:${pt.toFixed(3)}%"></span>`
    + `</span>`;
}

function ciAxis(){
  const el = document.getElementById("ciaxis");
  if (!el) return;
  el.innerHTML = CI_DOM
    ? CI_TICKS.map(t => `<i style="left:${ciPct(t).toFixed(3)}%">${t}</i>`).join("")
    : "";
}

function meter(v, cls){
  const w = Math.max(0, Math.min(100, v));
  return `<div class="score"><span class="v">${v == null ? "&ndash;" : v.toFixed(1)}</span>`
       + `<span class="meter ${cls}"><i style="width:${w}%"></i></span></div>`;
}

/* Bracket runs of leaders whose Overall scores all sit inside the tie band. */
function tieGroups(rows){
  const g = new Array(rows.length).fill(-1);
  let id = 0, i = 0;
  while (i < rows.length){
    let j = i;
    while (j + 1 < rows.length && Math.abs(rows[i].overall - rows[j + 1].overall) < TIE) j++;
    if (j > i) for (let k = i; k <= j; k++) g[k] = id;
    id++; i = j + 1;
  }
  return g;
}

function quoteList(evs){
  if (!evs || !evs.length) return "";
  return `<ul class="quotes">` + evs.map(e =>
    `<li><span class="ts">${esc(e.timestamp)}</span><q>${esc(e.quote)}</q></li>`).join("") + `</ul>`;
}

function judgeBlock(a){
  let h = `<div class="judge"><div class="name">${esc(a.judge)} &middot; ${esc(a.mode)} `
        + `&middot; ${esc(a.venue_type || "")} &middot; challenge ${a.venue_challenge}/5 `
        + `&middot; coverage ${Math.round((a.coverage || 0) * 100)}%</div>`;
  for (const [k, label, cls] of DIMS){
    const key = k === "d1" ? "d1_clarity" : k === "d2" ? "d2_insight" : "d3_technical_depth";
    const d = a.dimensions[key]; if (!d) continue;
    h += `<div class="dim ${cls}"><div class="dh"><b>${label}</b><span class="s">${d.score}</span></div>`
       + `<div class="why">${esc(d.reasoning)}</div>`
       + quoteList(d.evidence)
       + (d.counterevidence ? `<div class="counter"><em>Counterevidence</em>${esc(d.counterevidence)}</div>` : "")
       + `</div>`;
  }
  if (a.red_flags && a.red_flags.length){
    h += `<div class="flags"><div class="lbl">Red flags</div><ul>`
       + a.red_flags.map(f => `<li>${esc(f)}</li>`).join("") + `</ul></div>`;
  }
  h += `</div>`;
  return h;
}

function drawer(slug, person){
  const rows = (AUDIT[slug] || []).filter(a => a.mode === "blinded");
  const bySrc = {};
  for (const a of rows) (bySrc[a.source_id] = bySrc[a.source_id] || []).push(a);
  const ids = Object.keys(bySrc);
  if (!ids.length) return `<div class="drawer"><div class="sub">No graded transcripts yet.</div></div>`;
  let h = `<div class="drawer"><h3>${esc(person.name)} &mdash; the evidence</h3>`
        + `<div class="sub">${ids.length} graded transcript${ids.length > 1 ? "s" : ""}. `
        + `Each judge read the transcript blinded and wrote its own reasoning. `
        + `Scores you disagree with are meant to be arguable from what is shown here.</div>`;
  for (const sid of ids){
    const set = bySrc[sid], first = set[0];
    const meta = (person.sources || {})[sid] || {};
    h += `<div class="tcard"><div class="hdr">`
       + `<span class="t">${esc(meta.title || sid)}</span>`
       + `<span class="meta">${esc(meta.venue || "")}${meta.year ? " &middot; " + meta.year : ""}`
       + (meta.video_id ? ` &middot; <a href="https://www.youtube.com/watch?v=${esc(meta.video_id)}" target="_blank" rel="noopener">source</a>` : "")
       + `<br>subject spoke ~${first.subject_share_pct}% &middot; captions ${esc(first.asr_quality)}</span>`
       + `</div><div class="judgegrid">` + set.map(judgeBlock).join("") + `</div></div>`;
  }
  return h + `</div>`;
}

let sortKey = "rank", sortDir = 1;
function render(){
  const rows = DATA.slice().sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (typeof x === "string") return sortDir * x.localeCompare(y);
    return sortDir * ((x == null ? -1e9 : x) - (y == null ? -1e9 : y));
  });
  const groups = sortKey === "rank" && sortDir === 1 ? tieGroups(rows) : new Array(rows.length).fill(-1);
  const tb = document.getElementById("tb");
  tb.innerHTML = rows.map((r, i) => {
    const g = groups[i];
    const cls = ["row", g >= 0 && groups[i - 1] !== g ? "tie-start" : "",
                 g >= 0 && groups[i + 1] !== g ? "tie-end" : ""].filter(Boolean).join(" ");
    const haloCls = r.halo == null ? "" : (r.halo > 0 ? "pos" : "neg");
    const haloTxt = r.halo == null ? "&ndash;" : (r.halo > 0 ? "+" : "") + r.halo.toFixed(1);
    return `<tr class="${cls}" tabindex="0" data-slug="${esc(r.slug)}">`
      + `<td class="rank">${g >= 0 ? '<span class="tie"></span>' : ""}${r.rank}</td>`
      + `<td class="who"><div class="nm">${esc(r.name)}</div><div class="rl">${esc(r.role)}</div></td>`
      + `<td class="org">${esc(r.company)}<span class="sector">${esc(r.sector)}</span></td>`
      + `<td class="num">${meter(r.d2, "m2")}</td>`
      + `<td class="num">${meter(r.d3, "m3")}</td>`
      + `<td class="num">${meter(r.d1, "m1")}</td>`
      + `<td class="overall oscore">${r.overall == null ? "&ndash;" : `<span class="v">${r.overall.toFixed(1)}</span>`}</td>`
      + `<td class="overall oci">${ciPlot(r.overall, r.ci_low, r.ci_high)}</td>`
      + `<td class="num">${r.n}</td>`
      + `<td class="num halo ${haloCls}">${haloTxt}</td>`
      + `<td><span class="pill ${r.conf}">${r.conf}</span></td></tr>`;
  }).join("");
}

/* ---------- (?) tooltips ----------
   Copy lives here so a column explanation is one string, not markup buried in
   the header row. Halo is the only one today; the mechanism takes more. */
const INFO = {
  ci: `<p><b>How firm is that score?</b></p>
    <p>The two dots are a 95% confidence interval: resampling this leader's
    transcripts 20,000 times puts their score between those endpoints 95% of
    the time. The tick between them is the score itself.</p>
    <p>Every row is drawn on the <b>same scale</b>, marked by the numbers above
    and the faint rules behind the dots. A dot further right is a higher score,
    in every row. Hover a row to read its exact endpoints.</p>
    <p>A leader graded on 3 transcripts carries a much wider interval than one
    graded on 14, because the transcripts we collected are a <em>sample</em> of
    what that person says in public.</p>
    <p class="note">Ranks come from the score alone. Where two intervals overlap
    heavily, the ranking between those two leaders is not meaningful.</p>`,
  halo: `<p><b>Halo &mdash; what the name is worth.</b></p>
    <p>Every transcript is graded twice. Once with the speaker's name and company
    hidden, once with them shown. Halo is the second score minus the first.</p>
    <p><span class="k pos">+2.0</span> knowing who it was pushed the score up.
    Reputation helped.<br>
    <span class="k neg">&minus;2.0</span> knowing who it was pushed the score down.</p>
    <p class="note">The Overall ranking uses the blinded score only, so Halo never
    moves it. Across the corpus it averages +0.48 points, which is inside noise.</p>`,
};

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
  // Measure after paint, then keep the box inside the viewport on both axes.
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
  // Touch has no hover, so the button toggles. It sits inside a sortable
  // header, so this must run before the sort branch and swallow the event.
  const info = e.target.closest("button.info");
  if (info){
    e.stopPropagation();
    if (tipBtn === info) hideTip(); else showTip(info);
    return;
  }
  if (tipBtn) hideTip();
  const th = e.target.closest("thead th");
  if (th && th.dataset.k){
    const k = th.dataset.k;
    sortDir = sortKey === k ? -sortDir : (k === "name" || k === "company" || k === "conf" || k === "rank" ? 1 : -1);
    sortKey = k;
    document.querySelectorAll("thead th").forEach(x => x.removeAttribute("aria-sort"));
    th.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
    render();
    return;
  }
  const tr = e.target.closest("tr.row");
  if (!tr) return;
  const nxt = tr.nextElementSibling;
  if (nxt && nxt.classList.contains("audit")){ nxt.remove(); return; }
  document.querySelectorAll("tr.audit").forEach(x => x.remove());
  const slug = tr.dataset.slug;
  const person = DATA.find(d => d.slug === slug);
  const row = document.createElement("tr");
  row.className = "audit";
  row.innerHTML = `<td colspan="11">${drawer(slug, person)}</td>`;
  tr.after(row);
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && tipBtn){ const b = tipBtn; hideTip(); b.blur(); return; }
  if (e.key === "Enter" && e.target.classList && e.target.classList.contains("row")) e.target.click();
});
document.getElementById("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const dark = cur ? cur === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
});
ciAxis();
render();
</script>
"""


def build_method(results: dict, calib: dict, roster: dict) -> str:
    d = results["diagnostics"]
    w = d["weights"]
    leak = d.get("blinding_leakage_rate")
    corr = d.get("inter_judge_correlation_overall")
    gap = d.get("mean_abs_judge_gap_overall")
    raw = d.get("judge_raw_means_blinded", {})
    head = (calib.get("headline") or {})
    noise = head.get("mean_within_judge_sd_overall")
    dropped = roster.get("dropped_for_no_transcripts", [])

    def esc(x):
        return html.escape(str(x))

    parts = []
    parts.append(f"""
<h3>What is being scored</h3>
<p>Each transcript is graded on three dimensions, each on a 1&ndash;100 scale, supported by
15 sub-criteria that a judge may also mark <em>not observed</em> when the format gave no
opportunity to demonstrate them. The Overall score is
<code>{w['d2_insight']:.2f}&times;Insight + {w['d3_technical_depth']:.2f}&times;Technical + {w['d1_clarity']:.2f}&times;Clarity</code>.</p>
<ul>
<li><b>Insight (45%)</b> &mdash; causal and counterfactual reasoning, originality, strategic
tradeoffs, understanding of incentives, calibration of confidence, engagement with opposing
arguments, and whether the speaker recomputes when a premise changes.</li>
<li><b>Technical depth (35%)</b> &mdash; mechanism, magnitudes and denominators used correctly,
operational and industry specificity, and movement between strategy and implementation.</li>
<li><b>Clarity (20%)</b> &mdash; directness, structure, concrete language, economy. Deliberately
the smallest weight: the rubric explicitly refuses to reward fluency, charisma, or a confident
delivery, because a polished non-answer is the failure mode being guarded against.</li>
</ul>

<h3>The pipeline</h3>
<ul>
<li>A roster of 40 was built by 12 parallel sector scouts pooling 240 candidates, merged, then
attacked by four adversarial critics checking fame, availability, factual accuracy, and coverage
bias. Contested cases were settled by measuring actual long-form supply, not by argument.</li>
<li>Transcripts are verbatim automatic captions of publicly posted recordings, pulled
programmatically with timestamps. No model paraphrased or summarised them at any point.</li>
<li>Every transcript passed deterministic quality gates before grading: out-of-vocabulary rate,
speech-recognition repetition loops, type-token ratio, words per minute, and minimum length.</li>
<li>Speaker and company names were replaced with <code>[SUBJECT]</code> and <code>[COMPANY]</code>,
including speech-recognition manglings of the surname found by phonetic matching. This step is
covered by tests, after an early version replaced the contraction &ldquo;that&rsquo;s&rdquo; with
<code>[SUBJECT]</code> 34 times in one transcript.</li>
<li>Two judges graded every transcript independently: <b>Claude Fable 5.1</b> at maximum reasoning
effort, and <b>OpenAI GPT-6 Astra</b> at maximum reasoning effort. Model identity was asserted from
each call's telemetry rather than assumed.</li>
</ul>
""")

    parts.append(f"""
<h3>How reliable is a score?</h3>
<p>One unchanged transcript was graded five times by each judge under identical conditions. The
spread that produced is pure method noise.</p>
<ul>
<li>Repeat grading moves the Overall score by about <b>{noise} points</b> of standard deviation.</li>
<li>So two leaders differing by less than <b>{head.get('least_significant_difference_95pct')} points</b>
are not distinguishable. The bracket in the rank column marks those groups.</li>
<li>Coverage and venue-difficulty judgements were <b>perfectly stable</b> across repeats
(standard deviation 0.00), so the judges read the same conversation the same way every time.</li>
</ul>
<div class="callout">
<b>The two judges disagree in a specific, correctable way.</b>
Across blinded grades the raw means were Fable {raw.get('fable', {}).get('d2_insight', '&ndash;')} and
Astra {raw.get('astra', {}).get('d2_insight', '&ndash;')} on insight, a consistent offset rather than
genuine disagreement about who is impressive. Each judge's distribution is therefore recentred on the
pooled distribution before averaging, so only real disagreement moves a leader.
Correlation between judges on the Overall score: <b>r&nbsp;=&nbsp;{corr}</b>.
Mean absolute gap: <b>{gap} points</b>.
</div>
""")

    leak_pct = f"{leak * 100:.0f}%" if isinstance(leak, (int, float)) else "not measured"
    parts.append(f"""
<h3>How much of this is measurement, and how much is noise</h3>
<p>Every figure below was measured on this corpus, not assumed.</p>
<ul>
<li><b>Each judge repeats itself within about 2 points.</b> Grading the same
transcript twice gave a mean absolute difference of 1.69 (Fable) and 2.06
(Astra), implying a single-grading standard deviation near 1.64. Measured two
independent ways, five repeats on one fixture and nine pairs across four
different transcripts, which agree.</li>
<li><b>The two judges differ from each other by 8.65 points</b>, which is four
to five times either judge's own noise. So where they disagree, that is a real
difference of opinion about the transcript and not instability in either model.
Agreement on the ranking is <b>ICC(3,1) = 0.657</b>, moderate on the Koo and Li
bands, and the 95% limits of agreement span 30 points. Read the ranking as the
shape of the field, never as a verdict on one appearance.</li>
<li><b>Length does not buy score.</b> Twelve padded variants of one transcript,
three padding styles at +25% and +60% words, moved the Overall score by +0.05
(Fable) and &minus;1.08 (Astra), every one inside the noise floor. Astra's
clarity score fell 5.7 on padded text while insight and technical depth held
flat, which is the rubric working as designed.</li>
<li><b>Fame does not buy score.</b> Correlation between a video's view count and
its Overall score is <b>+0.093</b>, against the 0.312 needed for significance at
this sample size.</li>
<li><b>The three dimensions measure three things.</b> In a multitrait-multimethod
matrix, every same-dimension cross-judge correlation (0.661 to 0.686) beats every
different-dimension pair (0.260 to 0.599).</li>
<li><b>Being told who is speaking barely moves the score.</b> Across 28 paired
blinded and unblinded gradings the halo is <b>+0.48 points</b>, inside two
standard errors of zero.</li>
</ul>

<h3>What this cannot tell you</h3>
<ul>
<li><b>Blinding removed the name, not the identity.</b> This matters less than it
sounds: the measured halo above is +0.48 points, inside noise. Judges recognised the speaker anyway in
<b>{leak_pct}</b> of blinded transcripts, from products, projects, and context. Defeating that
would mean stripping the technical content the study exists to measure. Every transcript was
therefore also graded unblinded, and the <em>Halo</em> column reports the gap: how many points a
leader gains once the judges are told who they are. The published Overall score is the blinded one.</li>
<li><b>Captions have no speaker labels.</b> Judges separated the subject's speech from the
interviewer's by context and reported their confidence and the subject's estimated share of the
talking. Both are shown in each transcript card.</li>
<li><b>Venue difficulty is reported, never corrected for.</b> A leader who only sits for friendly
interviews will score lower on insight, because a soft conversation cannot demonstrate reasoning
under pressure. Adjusting for that would mean inventing a score for a conversation that never
happened.</li>
<li><b>Sampling is not exhaustive.</b> A handful of appearances per leader is a sample of a public
speaking record, not the whole of it. Leaders marked low confidence have too few transcripts for
their rank to be trusted.</li>
<li><b>Judges are language models.</b> Two frontier models with different training agreeing on a
ranking is meaningful evidence, and it is not the same thing as being correct.</li>
</ul>
""")

    if dropped:
        names = ", ".join(esc(x["name"]) for x in dropped[:12])
        parts.append(f"""
<h3>Who was excluded, and why</h3>
<p>Excluded names are recorded rather than silently omitted, because silence looks like an
oversight. {len(dropped)} people famous enough for consideration were left out, most for lack of
retrievable long-form public speech: {names}.</p>
""")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--roster", required=True)
    ap.add_argument("--calibration", required=True)
    ap.add_argument("--sources", default=None, help="discovered_sources.json, for titles and links")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    results = json.loads(Path(args.results).read_text())
    audit = json.loads(Path(args.audit).read_text())
    # The drawer only ever renders blinded grades, and sub-criterion justifications
    # are 15 extra strings per grade that nothing on the page reads. Both stay in
    # results_audit.json on disk for auditing; neither is embedded in the page.
    audit = {slug: [{k: v for k, v in a.items() if k != "subcriteria"}
                    for a in rows if a.get("mode") == "blinded"]
             for slug, rows in audit.items()}
    roster = json.loads(Path(args.roster).read_text())
    calib = json.loads(Path(args.calibration).read_text())

    src_meta: dict[str, dict] = {}
    if args.sources and Path(args.sources).exists():
        for led in json.loads(Path(args.sources).read_text()).get("leaders", []):
            src_meta[led["leader_slug"]] = {s["source_id"]: s for s in led.get("sources", [])}

    rows = []
    for l in results["leaders"]:
        b = l.get("blinded") or {}
        if not b:
            continue
        rows.append({
            "rank": l["rank"], "slug": l["slug"], "name": l["name"], "role": l["role"],
            "company": l["company"], "sector": l["sector"],
            "overall": b.get("overall"),
            "ci_low": b.get("ci_low"), "ci_high": b.get("ci_high"),
            "d1": b.get("d1_clarity"),
            "d2": b.get("d2_insight"), "d3": b.get("d3_technical_depth"),
            "n": l["n_transcripts"], "conf": l["confidence"],
            "halo": (l.get("halo") or {}).get("overall"),
            "sources": src_meta.get(l["slug"], {}),
        })

    d = results["diagnostics"]
    head = calib.get("headline") or {}
    total_words = sum(1 for _ in [])  # replaced below if transcripts are available
    tdir = Path("data/transcripts")
    words = 0
    if tdir.exists():
        for p in tdir.rglob("*.json"):
            try:
                words += json.loads(p.read_text()).get("word_count", 0)
            except Exception:
                pass

    html_out = (TEMPLATE
        .replace("__DATA__", json.dumps(rows))
        .replace("__AUDIT__", json.dumps(audit))
        .replace("__METHOD__", build_method(results, calib, roster))
        .replace("__RUNDATE__", datetime.now(timezone.utc).strftime("%d %B %Y"))
        .replace("__N_LEADERS__", str(len(rows)))
        .replace("__N_TRANSCRIPTS__", str(d.get("transcripts_with_blinded_consensus", 0)))
        .replace("__N_WORDS__", f"{words/1000:.0f}k" if words else "&ndash;")
        .replace("__N_CALLS__", str(d.get("grades_used", 0)))
        .replace("__CORR__", str(d.get("inter_judge_correlation_overall") or "&ndash;"))
        .replace("__NOISE__", str(head.get("mean_within_judge_sd_overall", "1.5")))
        .replace("__TIEBAND__", str(head.get("least_significant_difference_95pct", 4.3))))

    # Atomic: a clone may be reading this file to deploy while another writes it.
    write_atomic(args.out, html_out)
    print(f"wrote {args.out}  ({len(html_out)/1024:.0f} KB, {len(rows)} leaders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
