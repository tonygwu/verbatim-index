#!/usr/bin/env python3
"""Render the Verbatim Predictions page from data/predictions into one self-contained HTML file.

An index of what each person said would happen and, once a scores file is
supplied, a score over the part of it that has come due. With a scores file the
table opens sorted by Score, highest first, with unscored people after them in
name order; without one it opens in name order. Only the Score and Came true
columns measure foresight, and the test forbids the vocabulary of accuracy
anywhere outside the fenced score and disclaimer copy.

A person needs MIN_PREDICTIONS_TO_LIST accepted predictions for a row, and,
with scores, at least one that has come due. Everyone else is NAMED under the
table with the reason, because "deliberately not listed" and "missing" are
different facts.

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
import collections
import hashlib
import html
import json
import os
import re
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomicio import write_atomic  # noqa: E402
from site_theme import FONT_LINKS, THEME_CSS  # noqa: E402
import predictions_lib as L  # noqa: E402
import score_predictions as SP  # noqa: E402
import resolution_lib as R  # noqa: E402
import prediction_score as PS  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import year_summaries as YS  # noqa: E402

# The public origin, needed absolute because Open Graph and Twitter cards are
# fetched by a crawler that has no page context to resolve a relative path
# against. It matches the custom domain claimed in wrangler.predictions.toml.
SITE_URL = "https://verbatim-predictions.tonygwu.com/"

# Counts stay as placeholders so the card text is rendered from the corpus
# being published, never from a number typed here that goes stale.
SOCIAL_TITLE = "What __N_PEOPLE__ tech leaders predicted in public, quoted verbatim and dated"
SOCIAL_DESC = (
    "Forward-looking claims that __N_PEOPLE__ technology leaders made in public, quoted verbatim "
    "from transcripts of their own recorded speech, with the date they said it and the date it "
    "refers to. __N_ACCEPTED__ predictions from __N_TX__ transcripts."
)
# Once the page carries a score, the card says what the page now is, in the
# words its own intro opens with.
SOCIAL_DESC_SCORED = (
    "Who in tech or finance is best at predicting the future? The public predictions of __N_PEOPLE__ tech "
    "leaders, quoted verbatim, dated, and scored against how likely each one looked on the day "
    "it was said."
)

OG_CARD = Path(__file__).resolve().parent.parent / "site-predictions" / "og.png"
OG_CARD_META = OG_CARD.with_suffix(".meta.json")


def og_version() -> str:
    """Cache key for the social card image.

    Twitter and LinkedIn cache a card by its URL for days. A regenerated card
    at an unchanged URL therefore keeps showing the old picture. The key is the
    card's own bytes, so it changes exactly when the picture changes.
    """
    if not OG_CARD.is_file():
        return "0"
    return hashlib.sha256(OG_CARD.read_bytes()).hexdigest()[:12]


def check_og_card(index: dict) -> None:
    """Say so when the drawn card no longer matches the corpus it quotes.

    The card is a committed image rather than something this renderer draws, so
    nothing else would notice it going stale. This never blocks a render: a
    stale social card is worth reporting, and it is not worth refusing to
    publish a correct page over.
    """
    if not OG_CARD.is_file():
        print("WARNING: site-predictions/og.png is missing; social cards will show no image",
              file=sys.stderr)
        return
    if not OG_CARD_META.is_file():
        print("WARNING: site-predictions/og.png has no .meta.json; its counts cannot be checked",
              file=sys.stderr)
        return
    c = index["corpus"]
    accepted = c["accepted"]
    drawn = json.loads(OG_CARD_META.read_text()).get("counts", {})
    now = {
        "predictions": accepted,
        "transcripts_scanned": index["coverage"]["extract"].get("ok", 0),
        "pct_dated": round(100 * (accepted - c["statement_date_unknown"]) / accepted) if accepted else 0,
    }
    drift = {k: (drawn.get(k), v) for k, v in now.items() if drawn.get(k) != v}
    if drift:
        detail = ", ".join(f"{k}: card says {a}, corpus has {b}" for k, (a, b) in drift.items())
        print(f"WARNING: site-predictions/og.png is stale ({detail}); "
              f"re-run scripts/build_og_card.py --site predictions", file=sys.stderr)


MODEL_LABELS = {
    "claude-fable-5-1": "Claude Fable 5.1",
    "gpt-6-astra": "OpenAI GPT-6 Astra",
    "gemini-3.8-flash-high": "Google Gemini 3.8 Flash",
}
PLATFORM_LABELS = {"polymarket": "Polymarket", "kalshi": "Kalshi"}

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verbatim Predictions</title>
<!-- score:start --><meta name="description" content="__SOCIAL_DESC__"><!-- score:end -->
<link rel="canonical" href="__SITE_URL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Verbatim Predictions">
<meta property="og:locale" content="en_GB">
<meta property="og:url" content="__SITE_URL__">
<meta property="og:title" content="__SOCIAL_TITLE__">
<!-- score:start --><meta property="og:description" content="__SOCIAL_DESC__"><!-- score:end -->
<meta property="og:image" content="__SITE_URL__og.png?v=__OG_VERSION__">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Verbatim Predictions. __SOCIAL_TITLE__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="__SOCIAL_TITLE__">
<!-- score:start --><meta name="twitter:description" content="__SOCIAL_DESC__"><!-- score:end -->
<meta name="twitter:image" content="__SITE_URL__og.png?v=__OG_VERSION__">
<meta name="twitter:image:alt" content="Verbatim Predictions. __SOCIAL_TITLE__">
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
thead th.nosort{cursor:default}
thead th.nosort:hover{color:var(--muted)}
thead th .arrow{opacity:.35; margin-left:3px; font-size:9px}
thead th[aria-sort] .arrow{opacity:1; color:var(--d2)}
tbody tr.row{border-bottom:1px solid var(--rule); cursor:pointer}
tbody tr.row:hover{background:var(--surface-2)}
tbody tr.row:focus-visible{outline:2px solid var(--d1); outline-offset:-2px}
td{padding:11px 7px; vertical-align:middle}
td.num{text-align:right; font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums}
td.num.zero{color:var(--faint)}
/* Predictions: the total, then where each prediction stands. Left-aligned and
   smaller than the other numbers, so a six-line breakdown stays a compact block. */
th.pc{text-align:left; padding-left:12px}
td.pc{text-align:left; padding:7px 7px 7px 12px; font-size:11px; line-height:1.2; font-variant-numeric:tabular-nums}
td.pc .tot,td.pc li{display:flex; justify-content:space-between; gap:10px; max-width:118px}
td.pc .tot{font-size:13px; color:var(--ink); font-weight:600}
td.pc .tot span{font-weight:500}
td.pc .tot b,td.pc li b{font-family:"IBM Plex Mono",monospace; font-weight:inherit}
td.pc ul.bk{list-style:none; margin:1px 0 0; padding:0}
td.pc li{color:var(--muted)}
td.pc li b{color:var(--ink-2); font-weight:500}
td.pc li[title]{cursor:help; text-decoration:underline dotted var(--rule-strong); text-underline-offset:2px}
td.pc.zero{color:var(--faint)}
.who{padding-left:16px}
.who .nm{font-weight:600; letter-spacing:-.01em}
.who .rl{font-size:12px; color:var(--muted); margin-top:1px; overflow-wrap:anywhere}
td.org{color:var(--ink-2); font-size:13.5px}
td.org .sector{display:block; font-family:"IBM Plex Mono",monospace; font-size:10px; letter-spacing:.06em; text-transform:uppercase; color:var(--faint); margin-top:2px}
td.date{font-family:"IBM Plex Mono",monospace; font-size:12.5px; text-align:right}
td.date.unknown{color:var(--faint)}

/* ---------- when-it-was-said sparkline: one square per year, shared scale ---------- */
td.spark{padding:11px 10px}
.sq{display:flex; gap:2px; align-items:flex-end}
.sq i{flex:1 1 0; height:13px; border-radius:1px; background:var(--rule); min-width:3px; max-width:14px}
.sq i.q1{background:var(--d1); opacity:.30}
.sq i.q2{background:var(--d1); opacity:.55}
.sq i.q3{background:var(--d2); opacity:.80}
.sq i.q4{background:var(--d2)}
/* The year axis used to live INSIDE the "When it was said" header cell, which
   made that cell taller than its neighbours and pushed its label up off their
   line. It is now its own row, so all six header labels share one baseline.
   It HUGS the timeline rather than sitting in a band of its own: no rule under
   it and almost no padding, because a white band with a rule reads as a third
   region of the table, and the years belong to the squares under them.
   The header row is given an explicit height so the axis can stick to a known
   offset rather than to a guess. */
thead tr:first-child th{height:38px; box-sizing:border-box}
tr.axisrow td{
  position:sticky; top:38px; z-index:2; background:var(--surface);
  padding:2px 10px 0;
}
tr.axisrow td:first-child{padding-left:16px}
.sq-ax{display:flex; gap:2px}
.sq-ax i{flex:1 1 0; min-width:3px; max-width:14px; font-style:normal; font-size:9px; letter-spacing:0;
  text-align:center; color:var(--faint); text-transform:none}
/* Every five-year mark is darker and heavier, so the axis still has anchors to
   count from once every year carries a label. */
.sq-ax i.tick{color:var(--ink-2); font-weight:600}
.sq-nd{display:block; font-family:"IBM Plex Mono",monospace; font-size:9px; letter-spacing:.04em; color:var(--faint); margin-top:4px}
/* ---------- year-square popover ----------
   One element for the whole table, like #tip. Its text takes the colour of the
   square it describes. Where that colour is too light to read on the popover,
   readable() moves it along the SAME hue until it reaches WCAG AA, 4.5:1. The
   swatch beside it always shows the square's true colour. */
.sq:focus-visible{outline:2px solid var(--d1); outline-offset:3px; border-radius:1px}
.sq i.on{box-shadow:0 0 0 1.5px var(--ink)}
#sqtip{
  position:fixed; z-index:61; pointer-events:none; padding:8px 12px 9px;
  background:var(--surface); color:var(--ink-2);
  border:1px solid var(--rule-strong); border-radius:4px; box-shadow:var(--shadow);
  font-family:"IBM Plex Sans",system-ui,sans-serif; font-size:13.5px; line-height:1.35;
  white-space:nowrap; text-transform:none; letter-spacing:0;
}
#sqtip[hidden]{display:none}
#sqtip .l1{display:flex; align-items:center; gap:8px; font-weight:600; font-variant-numeric:tabular-nums}
#sqtip .l2{margin-top:3px; padding-left:19px; font-size:11.5px; color:var(--muted)}
#sqtip .sw{display:inline-block; width:11px; height:11px; border-radius:1px; background:var(--rule); flex:none}
#sqtip .sw.q1{background:var(--d1); opacity:.30}
#sqtip .sw.q2{background:var(--d1); opacity:.55}
#sqtip .sw.q3{background:var(--d2); opacity:.80}
#sqtip .sw.q4{background:var(--d2)}
p.omitted{margin:12px 0 0; max-width:92ch; font-size:12.5px; color:var(--muted)}
p.omitted b{color:var(--ink); font-weight:600}
.howscore{margin:16px 0 0; max-width:72ch; font-size:13.5px; color:var(--ink-2)}
.howscore h3{font-size:14px; font-weight:600; margin:0 0 6px; color:var(--ink)}
.sec .howscore p{margin:0 0 9px; color:var(--ink-2); font-size:13.5px; max-width:none}
.howscore .f{font-family:"IBM Plex Mono",monospace; font-size:12.5px; white-space:nowrap}
.howscore table{width:auto; min-width:0; table-layout:auto; margin:4px 0 2px; font-size:12.5px}
.howscore th,.howscore td{padding:3px 16px 3px 0; text-align:left; font-weight:400; border-bottom:1px solid var(--rule)}
.howscore th{font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.06em; text-transform:uppercase; color:var(--faint)}
.howscore td.n{font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums; text-align:right}
.howscore td .pos{color:var(--d3); font-weight:600}
.howscore td .neg{color:var(--bad); font-weight:600}
.legend i.k{display:inline-block; width:11px; height:11px; border-radius:1px; vertical-align:-1px; background:var(--rule)}
.legend i.k.q1{background:var(--d1); opacity:.30}
.legend i.k.q2{background:var(--d1); opacity:.55}
.legend i.k.q3{background:var(--d2); opacity:.80}
.legend i.k.q4{background:var(--d2)}
td.pend{text-align:center; font-family:"IBM Plex Mono",monospace; font-size:13px; color:var(--faint)}
/* score:start */
/* Green for a positive score, red for a negative one. NOT --d1/--d2, which are
   the sparkline's own blue and rust: reusing those made +0.19 and -0.11 render
   in the same colour, so the sign was invisible. --d3 and --bad are defined in
   both the light and dark palettes, so this stays theme-aware. */
/* Colour the verdict WORD, never the paragraph under it. Colouring the whole
   <dd> made the resolver's reasoning render bold and coloured too, which is a
   lot of shouting for what is a supporting sentence. */
dl.kv dd .verdict{font-weight:600}
dl.kv dd .verdict.yes{color:var(--d3)}
dl.kv dd .verdict.no{color:var(--bad)}
b.yes{color:var(--d3)}
b.no{color:var(--bad)}
ul.ev{margin:2px 0 0; padding-left:16px}
ul.ev li{margin-bottom:6px}
td.hit{text-align:right; padding-right:10px; font-family:"IBM Plex Mono",monospace;
  font-size:13px; font-variant-numeric:tabular-nums; color:var(--muted)}
td.hit .sl{color:var(--faint); padding:0 1px}
td.hit.none{text-align:center; color:var(--faint)}
td.hit.unranked{color:var(--faint)}
td.sc{text-align:right; padding-right:14px; font-family:"IBM Plex Mono",monospace; font-size:14px; font-variant-numeric:tabular-nums}
td.sc .v{font-weight:600}
td.sc .pos{color:var(--d3)}
td.sc .neg{color:var(--bad)}
td.sc .n{display:block; font-size:10px; color:var(--faint); letter-spacing:.02em; margin-top:2px}
td.sc.none{text-align:center; color:var(--faint)}
/* score:end */

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
.also{margin:5px 0 0; padding:0; list-style:none; display:flex; flex-direction:column; gap:3px; font-size:12.5px; color:var(--ink-2)}
.also q{font-style:italic}
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
</head>
<body>

<button class="toggle" id="themeBtn" type="button">THEME</button>
<div class="wrap">

<header class="mast">
  <div class="eyebrow">__GENDATE__ &middot; Verbatim quotes, dated &middot; __EYEBROW_STATUS__ &middot; <a href="https://verbatim-index.tonygwu.com">Verbatim Index &rarr;</a></div>
  <h1>Verbatim <em>Predictions</em></h1>
  <p class="thesis">
    __THESIS__
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
    Click any row to read every prediction with its verbatim quote and the surrounding transcript,
    and to filter by target date, category and how much of the outcome is under the speaker's control.
    __SORT_NOTE__
  </p>
  <div class="legend">
    <span>A <b>prediction</b> is a claim the extractor (__EXTRACTOR__) proposed and an independent
    verifier (__VERIFIER__) agreed is a forward-looking, falsifiable statement by this speaker.
    Candidates the verifier rejected are kept on file and counted, not shown. The two numbers are
    counts of what each person said. Neither is a measure of foresight.
    <!-- score:start -->__SCORE_LEGEND__<!-- score:end --></span>
  </div>
  <!-- score:start -->__HOWSCORE__<!-- score:end -->
</div>

<div class="tablecard">
  <table id="board">
    <colgroup>
      <col style="width:215px"><col style="width:140px">
      <col style="width:130px">
      <col style="width:315px"><col style="width:85px"><col style="width:95px">
    </colgroup>
    <thead><tr>
      <th data-k="name"__NAME_ARIA__>Person<span class="arrow">&#9650;</span></th>
      <th data-k="company">Organisation<span class="arrow">&#9650;</span></th>
      <th class="pc" data-k="accepted">Predictions<button class="info" type="button" data-info="accepted"
        aria-expanded="false" aria-label="What does Predictions mean?">?</button><span class="arrow">&#9650;</span></th>
      <th data-k="earliest">When it was said<button class="info" type="button" data-info="timeline"
        aria-expanded="false" aria-label="What does the timeline show?">?</button><span class="arrow">&#9650;</span></th>
      <!-- score:start -->__CAME_TRUE_HEADER____SCORE_HEADER__<!-- score:end -->
    </tr>
    <tr class="axisrow"><td></td><td></td><td></td><td><span class="sq-ax" id="ax"></span></td><td></td><td></td></tr>
    </thead>
    <tbody id="tb"></tbody>
  </table>
</div>
__OMITTED__
<div class="legend">
  <span><b>When it was said</b> is one square per year, __Y0__ on the left to __Y1__ on the right, the
  same years on every row. Shading is how many predictions that person made that year, on a scale
  shared by all rows: <i class="k q1"></i>&nbsp;1 &nbsp; <i class="k q2"></i>&nbsp;2&ndash;3 &nbsp;
  <i class="k q3"></i>&nbsp;4&ndash;7 &nbsp; <i class="k q4"></i>&nbsp;8 or more. An empty square is a
  year with none. Hover or tap a square to see its year and count; from the keyboard, tab to a row's
  squares and use the arrow keys. The statement date is the recording's
  publication date, an upper bound on when it was said.</span>
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
  <a href="__REPO_URL__">github.com/tonygwu/verbatim-index</a>.
  Extraction run <code>__RUN_ID__</code>, contracts <code>__CONTRACT_ID__</code>.
</footer>
</div>

<div id="tip" role="tooltip" hidden></div>
<div id="sqtip" role="tooltip" aria-live="polite" hidden></div>

<script>
const DATA = __DATA__;
const SRC = __SRC__;
/* score:start */
// The rank floor, from score_predictions.MIN_SCORED_TO_RANK by way of the
// renderer; never typed here, so the hover text cannot drift from the rule.
const MIN_SCORED = __MIN_SCORED__;
/* score:end */

/* The prediction records are deliberately NOT in this document.

   One person's accepted predictions live in predictions/<slug>.json, fetched
   the first time that row is opened and kept for the rest of the visit. They
   were inline until 2026-09-17, which made this page 4.7 MB. The board at
   verbatim-index went over Twitter's card-crawler limit the same way, at
   16 MB, and posted with no card. This page was the same defect waiting. */
const PRED_VERSION = "__PRED_VERSION__";
const PRED_SLUGS = __PRED_SLUGS__;
const PRED = {};
async function loadPred(slug){
  if (PRED[slug]) return PRED[slug];
  const url = `predictions/${encodeURIComponent(slug)}.json?v=${PRED_VERSION}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} answered HTTP ${res.status}`);
  const body = await res.text();
  let recs;
  try { recs = JSON.parse(body); }
  catch (err){
    /* A file the site does not have comes back as this page, with status 200,
       because the asset worker serves single-page-application fallbacks. An
       empty drawer would read as "this person predicted nothing". */
    throw new Error(`${url} did not answer with JSON (${body.length} bytes)`);
  }
  if (!Array.isArray(recs)) throw new Error(`${url} is not a list of predictions`);
  PRED[slug] = recs;
  return recs;
}
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const CAT = {ai_capability:"AI capability", technology_product:"Technology & product", company_business:"Company & business",
  market_industry:"Market & industry", macro_economy:"Macro & economy", policy_regulation:"Policy & regulation",
  science:"Science", society:"Society", other:"Other"};
const TYPE = {numeric:"Numeric", milestone:"Milestone", binary_event:"Binary event", trend_direction:"Trend / direction", comparative:"Comparative", other:"Other"};
const HOR = {explicit:"Explicit date", inferable:"Inferable from context", none:"No date"};
const CTRL = {external:"External to the speaker", partial:"Partly under the speaker's control", own:"Under the speaker's own control"};

const INFO = {
  /* score:start */
  accepted: `__ACCEPTED_INFO__`,
  /* score:end */
  timeline: `<p><b>When it was said.</b> One square per year, __Y0__ to __Y1__, the same years on every
    row. The shading is how many of this person's accepted predictions carry a statement date in that
    year, banded 1, 2&ndash;3, 4&ndash;7, 8 or more on a scale shared by every row. Hover or tap a
    square for its year and count.</p>
    <p>The statement date is the recording's <b>publication</b> date, an upper bound on when the words
    were said. A talk uploaded years after it was given sits in the upload year, so a square can be
    later than the event. Predictions from a recording with no date sit in no year and are counted
    beneath the squares.</p>
    <p>Sorting this column sorts by the earliest statement date; people with no dated prediction sort
    last.</p>`,
  /* score:start */
  __CAME_TRUE_INFO__
  __SCORE_INFO__
  /* score:end */
};

/* One square per statement year, the same span on every row so the columns line up.
   Bands, not a linear ramp: the corpus median cell is 1 and the max is 17, so a linear
   scale would render almost every square at the lightest shade. */
const YEARS = __YEARS__;
const band = n => n === 0 ? "" : n === 1 ? "q1" : n <= 3 ? "q2" : n <= 7 ? "q3" : "q4";
function spark(r){
  const y = r.years || {};
  /* No native title: the popover below says the same thing, readably, and a
     title would open a second, unstyled box on top of it. */
  const cells = YEARS.map(yr => {
    const n = y[yr] || 0;
    return `<i class="${band(n)}" data-y="${yr}" data-n="${n}"></i>`;
  }).join("");
  const bits = [];
  if (r.early) bits.push(`<span title="${r.early} prediction${r.early === 1 ? "" : "s"} from before the axis starts; too few predictions that early to give those years a column.">+${r.early} earlier</span>`);
  if (r.undated) bits.push(`<span title="${r.undated} of this person's predictions come from a recording with no publication date, so they sit in no year.">+${r.undated} undated</span>`);
  const nd = bits.length ? `<span class="sq-nd">${bits.join(" &middot; ")}</span>` : "";
  return `<div class="sq" tabindex="0" role="group" aria-label="Predictions per year by ${esc(r.name)}. Use the left and right arrow keys to read each year.">${cells}</div>${nd}`;
}
/* score:start */
/* One number per person: the MEAN points over their resolved, eligible predictions.
   Expected points are zero at every p under this rule, so a positive mean is foresight
   and volume alone earns nothing. A person below the floor keeps their predictions on
   the page and shows no number, the way the leaderboard's rank floor already works. */
/* How many of the scored predictions came true, as a plain fraction. It sits
   next to Score deliberately: the two disagree often, and that disagreement is
   the whole point of the rule. Somebody can be 3/3 and score +0.34 because the
   three were near-certainties, while 1/4 scores -0.06 because the three misses
   were long shots nobody expected to land. A reader who sees only the mean will
   assume it tracks the hit rate; the fraction shows that it does not. */
/* Where each of a person's predictions stands at the scoring run's as-of date.
   The builder derives the buckets and refuses to render a row whose lines do not
   add up to its total; only lines above zero are shown, in this fixed order. */
const BUCKETS = __BUCKETS__;
const UNRES_SHORT = __UNRES_SHORT__;
function predCell(r){
  if (!r.buckets) return `<td class="pc${r.accepted ? "" : " zero"}"><div class="tot"><span>Total</span><b>${r.accepted}</b></div></td>`;
  const lines = BUCKETS.filter(([k]) => r.buckets[k]).map(([k, lab]) => {
    const split = k === "unresolvable" && r.unres
      ? ` title="${esc(Object.entries(r.unres).sort((a, b) => b[1] - a[1])
          .map(([w, n]) => `${n} ${UNRES_SHORT[w] || w.replace(/_/g, " ")}`).join(", "))}"` : "";
    return `<li${split}><span>${esc(lab)}</span><b>${r.buckets[k]}</b></li>`;
  }).join("");
  return `<td class="pc"><div class="tot"><span>Total</span><b>${r.accepted}</b></div><ul class="bk">${lines}</ul></td>`;
}
function hitCell(r){
  if (r.score_hits == null) return `<td class="hit none">&mdash;</td>`;
  // Below the rank floor the fraction still prints, muted, and the hover says why
  // the Score beside it is blank. A count needs no floor; a mean does.
  const base = `${r.score_hits} of ${r.n_scored} scored prediction${r.n_scored === 1 ? "" : "s"} came true`;
  const cls = r.ranked ? "hit" : "hit unranked";
  const title = r.ranked ? base : `${base}; below the floor of ${MIN_SCORED} for a Score`;
  return `<td class="${cls}" title="${title}">` +
    `${r.score_hits}<span class="sl">/</span>${r.n_scored}</td>`;
}

function scoreCell(r){
  if (r.score == null) return `<td class="sc none" title="${esc(r.score_why || "not scored")}">&mdash;</td>`;
  const sign = r.score >= 0 ? "pos" : "neg";
  const v = (r.score >= 0 ? "+" : "\u2212") + Math.abs(r.score).toFixed(2);
  // No n= here any more: the Came true column prints the same count as its
  // denominator, and two copies of one number is noise.
  return `<td class="sc" title="mean over ${r.n_scored} resolved prediction${r.n_scored === 1 ? "" : "s"}">` +
    `<span class="v ${sign}">${v}</span></td>`;
}
/* score:end */
/* score:start */
/* What the two stages decided about ONE prediction, with the evidence attached.
   This is what makes a published number auditable: a reader who doubts a score can
   read the claim, the outcome, the sources it rests on, and the probability it was
   priced at, without leaving the page. */
const OUTCOME_LABEL = {occurred: "Came true", not_occurred: "Did not come true",
                       unresolvable: "Could not be resolved"};
const UNRES_WHY = {
  no_public_evidence: "nothing public settles it either way",
  criterion_ambiguous: "the criterion has two readings that disagree",
  criterion_undirected: "the criterion states no direction to test",
  threshold_unmeasurable: "the number named is not publicly reported",
  deadline_incoherent: "the deadline makes no sense against the statement date",
  after_knowledge_cutoff: "the window closed too recently for a public record",
};
/* The Outcome line is the record's STATE, decided once by the builder
   (record_state) and counted by the Predictions column from the same value, so the
   card and the column cannot disagree. The words come from the builder too; this
   only lays them out. A verdict on a record that does not count says so beside it. */
function outcomeRows(r){
  const st = r.state, o = r.outcome;
  let h = `<dt>Outcome</dt><dd${o ? "" : ` class="pending"`}><div class="state">${esc(st.line)}</div>`;
  if (o){
    const cls = o.verdict === "occurred" ? "yes" : o.verdict === "not_occurred" ? "no" : "pending";
    h += `<span class="verdict ${cls}">${esc(OUTCOME_LABEL[o.verdict] || o.verdict)}</span>`;
    if (o.verdict === "unresolvable" && o.why) h += ` <span class="why">&mdash; ${esc(UNRES_WHY[o.why] || o.why)}</span>`;
    if (st.verdict_note) h += ` <span class="why">(${esc(st.verdict_note)})</span>`;
    h += `<div class="why">${esc(o.reasoning)}</div>`;
  }
  h += `</dd>`;
  if (o && o.sources && o.sources.length){
    h += `<dt>Evidence</dt><dd><ul class="ev">` + o.sources.map(x => {
      const m = /\((https?:[^)\s]+)\)\s*$/.exec(x.where) || /^(https?:\S+)$/.exec(x.where);
      const url = m ? m[1] : null;
      // The model writes its source as markdown, [label](url). Strip the url AND the
      // brackets, or every link on the page renders as "[AWS Seoul launch announcement]".
      const label = x.where.replace(/\s*\(https?:[^)\s]+\)\s*$/, "").replace(/^\[|\]$/g, "");
      const head = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label || url)}</a>` : esc(x.where);
      return `<li>${head}${x.date ? ` <span class="why">${esc(x.date)}</span>` : ""}
        <div class="why">${esc(x.what_it_shows)}</div></li>`;
    }).join("") + `</ul></dd>`;
  }
  /* The prior stands on the statement date, which is often an upload date, so the
     price is dated by that date rather than said to be "on the day it was said".
     With no price, the state says why in one line. */
  if (o && o.p != null){
    const pts = o.points == null ? null : (o.points >= 0 ? "+" : "\u2212") + Math.abs(o.points).toFixed(2);
    h += `<dt>Priced at</dt><dd>${esc(pct(o.p))}`
       + (r.statement_date ? ` as of ${esc(r.statement_date)}` : ` (the recording has no known date)`)
       + (o.reference_class ? ` <span class="why">&mdash; ${esc(o.reference_class)}</span>` : "")
       + (pts ? ` &middot; <b class="${o.points >= 0 ? "yes" : "no"}">${pts} points</b>` : "")
       + (st.state !== "scored" ? ` <span class="why">(not scored)</span>` : "")
       + `</dd>`;
  } else if (st.price){
    h += `<dt>Priced at</dt><dd class="pending">${esc(st.price)}</dd>`;
  }
  return h;
}
/* score:end */
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

/* A restatement is the same prediction said again on another day (operator decision,
   2026-09-28). It is shown ONCE, as the cluster's specific member, and each other
   statement is listed beneath it. The builder marks those with restated_by. */
function alsoSaid(r, all){
  const also = all.filter(x => x.restated_by === r.prediction_id)
    .sort((a, b) => (a.statement_date || "").localeCompare(b.statement_date || ""));
  if (!also.length) return "";
  return `<ul class="also">` + also.map(x => {
    const s = SRC[x.transcript_id] || {};
    const where = s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || x.transcript_id)}</a>`
                        : esc(s.title || x.transcript_id);
    const when = x.said.also ? `Also said ${esc(x.said.also)}` : "Also said, date unknown";
    return `<li data-state="${esc(x.state.state)}"><span>${when}: <q>${esc(x.quote)}</q>
      <span class="why">&mdash; ${where}</span></span></li>`;
  }).join("") + `</ul>`;
}
function predCard(r, all){
  const s = SRC[r.transcript_id] || {};
  const link = ytLink(s.video_id, r.t);
  const ts = link ? `<a class="ts" href="${esc(link)}" target="_blank" rel="noopener" aria-label="Open the video at ${esc(r.timestamp_mark)}">${esc(r.timestamp_mark)}</a>`
                  : `<span class="ts">${esc(r.timestamp_mark)}</span>`;
  const conf = r.confidence_type === "explicit_probability" ? `${esc(pct(r.probability))} &mdash; &ldquo;${esc(r.confidence_language)}&rdquo;`
             : r.confidence_type === "qualitative" ? `&ldquo;${esc(r.confidence_language)}&rdquo;` : "not specified";
  /* Said and Target are written by the builder (said_label, target_line): Said
     is labelled by what kind of date it is, and Target shows the speaker's or the
     extractor's words before it ever says "none stated". */
  return `<div class="pred" data-state="${esc(r.state.state)}" data-cat="${esc(r.category)}" data-type="${esc(r.prediction_type)}" data-hor="${esc(r.horizon)}" data-ctrl="${esc(r.subject_control)}">
    <div class="claim">${esc(r.claim)}</div>
    <ul class="quotes"><li>${ts}<q>${esc(r.quote)}</q></li></ul>
    ${alsoSaid(r, all || [])}
    <dl class="kv">
      <dt>Said</dt><dd>${esc(r.said.card)}</dd>
      <dt>Target</dt><dd>${esc(r.target)}</dd>
      <dt>Confidence</dt><dd>${conf}</dd>
      <dt>Category</dt><dd>${esc(CAT[r.category] || r.category)} &middot; ${esc(TYPE[r.prediction_type] || r.prediction_type)} &middot; ${esc(CTRL[r.subject_control] || r.subject_control)}</dd>
      <dt>Resolves if</dt><dd>${esc(r.resolution_criteria)}<br><span class="why">Verifier's reading: ${esc(r.verifier_criteria)}</span></dd>
      ${outcomeRows(r)}
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
  const all = PRED[slug] || [];
  const recs = all.filter(r => !r.restated_by &&
    (!filt.cat || r.category === filt.cat) && (!filt.type || r.prediction_type === filt.type)
    && (!filt.hor || r.horizon === filt.hor) && (!filt.ctrl || r.subject_control === filt.ctrl));
  const groups = new Map();
  for (const r of recs){ if (!groups.has(r.transcript_id)) groups.set(r.transcript_id, []); groups.get(r.transcript_id).push(r); }
  let h = "";
  for (const [tid, rs] of groups){
    const s = SRC[tid] || {};
    h += `<div class="tcard"><div class="hdr"><span class="t">${esc(s.title || tid)}</span>
      <span class="meta">${esc(s.venue || "")}${rs[0].statement_date ? " &middot; " + esc(rs[0].statement_date) : ""}${s.url ? ` &middot; <a href="${esc(s.url)}" target="_blank" rel="noopener">source</a>` : ""}</span></div>`
      + rs.map(r => predCard(r, all)).join("") + `</div>`;
  }
  return {html: h || `<p class="sub">No predictions match these filters.</p>`, n: recs.length};
}

function drawer(slug, person){
  const recs = PRED[slug] || [];
  const c = cards(slug, {});
  const cov = person.tx_attempted != null ? `; extraction ran on ${person.tx_succeeded} of ${person.tx_attempted} of their transcripts` : "";
  const folded = recs.filter(r => r.restated_by).length;
  return `<div class="drawer" data-slug="${esc(slug)}">
    <h3>${esc(person.name)} &mdash; ${recs.length} accepted prediction${recs.length === 1 ? "" : "s"}</h3>
    <div class="sub">from ${person.transcripts} transcript${person.transcripts === 1 ? "" : "s"}${cov};
      ${person.rejected} candidate${person.rejected === 1 ? "" : "s"} rejected by the verifier and not shown.${folded
        ? ` ${folded} of the ${recs.length} ${folded === 1 ? "restates another prediction and is shown under the prediction it repeats."
                                                     : "restate another prediction and are shown under the prediction they repeat."}` : ""}</div>
    <div class="sub">Target date: ${person.h_explicit} named in the quote, ${person.h_inferable} inferred from
      the surrounding transcript, ${person.h_none} open-ended. Likelihood: ${person.p_explicit} where the
      speaker gave a number, ${person.p_qual} where the speaker used words of likelihood.</div>
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

/* Every year gets its label, not just the five-year marks. Three labels floating
   over fifteen squares made a reader count columns to place a shaded one; a label
   on each square answers that directly. The five-year marks stay emphasised so
   the run of years still has anchors. */
document.getElementById("ax").innerHTML = YEARS.map(y => {
  const t = Number(y) % 5 === 0;                      // a tick every five years; YEARS holds strings
  return `<i class="${t ? "tick" : ""}">&rsquo;${y.slice(2)}</i>`;
}).join("");

/* score:start */
/* The opening sort. With a Score column it is Score, highest first; rows with no
   Score follow every scored row, in name order (see the null rule in render).
   Without one it is name order. The builder decides, so the static aria-sort on
   the header and this line can never disagree. */
/* score:end */
let sortKey = __SORT_KEY__, sortDir = __SORT_DIR__;
function render(){
  sqHide();
  const rows = DATA.slice().sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    /* score:start */
    // Two columns can hold nothing at all, and an absence is not a zero. Rows with
    // nothing sort last in BOTH directions, so flipping the arrow never promotes one.
    if (sortKey === "earliest" || sortKey === "score" || sortKey === "hit_rate"){
      if (x == null && y == null) return a.name.localeCompare(b.name);
      if (x == null) return 1;
      if (y == null) return -1;
    }
    /* score:end */
    if (typeof x === "string" && typeof y === "string") return sortDir * x.localeCompare(y);
    return sortDir * ((x || 0) - (y || 0)) || a.name.localeCompare(b.name);
  });
  const tb = document.getElementById("tb");
  tb.innerHTML = rows.map(r => `<tr class="row" tabindex="0" data-slug="${esc(r.slug)}" aria-expanded="false">
    <td class="who"><div class="nm">${esc(r.name)}</div><div class="rl">${esc(r.role || "")}</div></td>
    <td class="org">${esc(r.company || "")}<span class="sector">${esc(r.sector || "")}</span></td>
    ${predCell(r)}
    <td class="spark">${spark(r)}</td>
    ${hitCell(r)}${scoreCell(r)}
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
  const sqc = e.target.closest(".sq i");
  if (sqc && touchTap){ sqShow(sqc, "tap"); return; }  // a tap reads the square; a click still opens the row
  if (sqBy === "tap") sqHide();
  if (e.target.closest("tr.audit")) return;          // links, selects and details inside a drawer never toggle it
  const th = e.target.closest("thead th");
  if (th && th.dataset.k){
    const k = th.dataset.k;
    sortDir = sortKey === k ? -sortDir : (k === "name" || k === "company" || k === "earliest" ? 1 : -1);  // numeric columns open high-first
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
  row.innerHTML = `<td colspan="6"><div class="drawer"><div class="sub">`
    + `Loading ${esc(person.name)}&rsquo;s predictions&hellip;</div></div></td>`;
  tr.after(row);
  tr.setAttribute("aria-expanded", "true");
  const cell = row.firstElementChild;
  if (!PRED_SLUGS.includes(slug)){
    cell.innerHTML = `<div class="drawer"><div class="sub">No accepted predictions yet.</div></div>`;
    return;
  }
  loadPred(slug)
    .then(() => { cell.innerHTML = drawer(slug, person); })
    .catch(err => {
      cell.innerHTML = `<div class="drawer"><h3>${esc(person.name)}</h3>`
        + `<div class="sub">These predictions did not load, so none are shown rather than an empty `
        + `drawer that would read as none existing: ${esc(err.message)}</div></div>`;
    });
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
/* ---------- year-square popover ----------
   What a square encodes: how many of this person's accepted predictions carry a
   statement date in that year. Its colour is a band of that count, blue for 1
   and 2-3, rust for 4-7 and 8 or more, grey for none. The popover says the year
   and the count in words, in the square's own colour, and under it a few words
   saying what the person predicted that year, written by year_summaries.py. */
const AA = 4.5;                                        // WCAG AA for normal text
const sqtip = document.getElementById("sqtip");
let sqCur = null, sqBy = null, touchTap = false;
const rgbOf = s => (s.match(/[\d.]+/g) || []).map(Number);
function lum(c){
  const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}
function contrast(a, b){ const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
function toHsl([r, g, b]){
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}
function fromHsl([h, s, l]){
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
                  : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map(v => Math.round((v + m) * 255));
}
/* The colour itself if it already reads at AA against bg. If not, the same hue
   and saturation, darker on a light popover and lighter on a dark one, stepped
   until it does. Only lightness moves, so a blue stays a blue. */
function readable(fg, bg){
  if (contrast(fg, bg) >= AA) return {rgb: fg, adjusted: false};
  const [h, s, l] = toHsl(fg), down = lum(bg) > lum(fg);
  for (let i = 1; i <= 100; i++){
    const L = down ? l - i / 100 : l + i / 100;
    if (L < 0 || L > 1) break;
    const c = fromHsl([h, s, L]);
    if (contrast(c, bg) >= AA) return {rgb: c, adjusted: true};
  }
  return {rgb: down ? [0, 0, 0] : [255, 255, 255], adjusted: true};
}
function sqHide(){
  if (sqCur){ sqCur.classList.remove("on"); const g = sqCur.closest(".sq"); if (g) g.removeAttribute("aria-describedby"); }
  sqCur = null; sqBy = null; sqtip.hidden = true;
}
function sqShow(cell, by){
  if (sqCur && sqCur !== cell) sqCur.classList.remove("on");
  const n = Number(cell.dataset.n), y = cell.dataset.y;
  const tr = cell.closest("tr.row");
  const person = tr ? DATA.find(d => d.slug === tr.dataset.slug) : null;
  const b = band(n);
  const what = n === 0 ? `No predictions in ${y}` : `${n} prediction${n === 1 ? "" : "s"} in ${y}`;
  sqtip.innerHTML = `<div class="l1"><i class="sw ${b}"></i><span class="tx">${esc(what)}</span></div>`
    + `<div class="l2">${esc(n && person ? (person.ysum || {})[y] || "" : person ? person.name : "")}</div>`;
  sqtip.hidden = false;
  /* The square's colour as it appears on the popover: its fill, at its own
     opacity, over the popover background. That is the swatch's colour too. */
  const cs = getComputedStyle(cell), bg = rgbOf(getComputedStyle(sqtip).backgroundColor).slice(0, 3);
  const fill = rgbOf(cs.backgroundColor), a = Number(cs.opacity) * (fill.length > 3 ? fill[3] : 1);
  const seen = fill.slice(0, 3).map((v, i) => Math.round(v * a + bg[i] * (1 - a)));
  const r = readable(seen, bg);
  const tx = sqtip.querySelector(".tx");
  tx.style.color = `rgb(${r.rgb.join(",")})`;
  tx.dataset.square = `rgb(${seen.join(",")})`;
  tx.dataset.adjusted = r.adjusted ? "yes" : "no";
  const rect = cell.getBoundingClientRect(), t = sqtip.getBoundingClientRect(), pad = 8;
  let left = rect.left + rect.width / 2 - t.width / 2;
  left = Math.max(pad, Math.min(left, window.innerWidth - t.width - pad));
  let top = rect.top - t.height - 8;
  if (top < pad) top = rect.bottom + 8;
  sqtip.style.left = left + "px";
  sqtip.style.top = top + "px";
  cell.classList.add("on");
  const g = cell.closest(".sq");
  if (g) g.setAttribute("aria-describedby", "sqtip");
  sqCur = cell; sqBy = by;
}
document.addEventListener("pointerdown", e => { touchTap = e.pointerType === "touch"; }, true);
document.addEventListener("pointerover", e => {
  if (e.pointerType === "touch") return;               // a tap is handled on click
  const c = e.target.closest && e.target.closest(".sq i");
  if (c) sqShow(c, "hover");
  else if (sqBy === "hover") sqHide();
});
document.addEventListener("focusin", e => {
  const g = e.target.closest && e.target.closest(".sq");
  if (!g){ if (sqBy === "focus") sqHide(); return; }
  if (!g.matches(":focus-visible")) return;            // a mouse click focuses it too; hover already covers that
  if (sqCur && g.contains(sqCur)){ sqBy = "focus"; return; }
  // Open on the newest year that has anything, or the newest year if none do.
  const cells = [...g.querySelectorAll("i")];
  sqShow([...cells].reverse().find(c => Number(c.dataset.n) > 0) || cells[cells.length - 1], "focus");
});
document.addEventListener("focusout", e => {
  if (e.target.classList && e.target.classList.contains("sq") && sqBy === "focus") sqHide();
});
document.addEventListener("keydown", e => {
  if (!(e.target.classList && e.target.classList.contains("sq"))) return;
  if (e.key === "Escape"){ sqHide(); return; }
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  e.preventDefault();
  const cells = [...e.target.querySelectorAll("i")];
  const i = Math.max(0, cells.indexOf(sqCur));
  sqShow(cells[Math.max(0, Math.min(cells.length - 1, i + (e.key === "ArrowRight" ? 1 : -1)))], "focus");
});
window.addEventListener("scroll", () => { if (sqBy !== "focus") sqHide(); }, true);
window.addEventListener("resize", sqHide);

document.getElementById("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const dark = cur ? cur === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
  sqHide();
});
render();
</script>
</body>
</html>
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


# Happy Scribe serves its transcript text HTML-escaped, and the fetcher stored it
# that way, so its quotes read "it&#39;s" on the page: the page escapes "&" once
# more and prints the entity. MEASURED 2026-09-29 (C8): 18 accepted records, all
# Happy Scribe, 47 field hits, all in the four fields shown_text decodes, and none
# from any other source. Only that source is decoded. Every other source is shown
# byte for byte, so a caption that really says "&amp;" is never silently changed.
# This decodes what the page SHOWS only. The fetcher, and the transcript text that
# quote offsets are counted in, are separate work (root-cause design, 1.3 and 4.5).
HS_SOURCE_PREFIX = "hs-"


def shown_text(rec: dict, s: "str | None") -> "str | None":
    """A transcript-derived text field as a reader should see it."""
    if s is None or not str(rec["source_id"]).startswith(HS_SOURCE_PREFIX):
        return s
    return html.unescape(s)


# What each date basis says about when the words were said. Only a date the source
# states, or one a reviewed override sourced, IS that day. An upload or publication
# date is an upper bound, and until the dating stage exists nothing has checked an
# upload against the event, so the card says that as well.
SAID_BOUND = {"youtube_upload_date": "YouTube upload; not checked against the event",
              "publication_date": "publication date"}
REPLACED_DATE = {"youtube_upload_date": "YouTube upload", "publication_date": "publication date"}


def said_label(src: dict, where: str) -> dict:
    """The card's "Said" line and the "Also said" line, labelled by the date's basis."""
    d, basis = src["statement_date"], src["statement_date_basis"]
    if not d:
        if basis != "unknown":
            raise SystemExit(f"REFUSING: {where} has no statement date but basis {basis!r}")
        return {"card": "date unknown", "also": None}
    if basis == "stated_in_page":
        return {"card": d, "also": f"on {d}"}
    if basis == L.OVERRIDE_DATE_BASIS:
        blk = src.get("statement_date_override") or {}
        old, was = blk.get("replaced_date"), blk.get("replaced_basis")
        if old and was not in REPLACED_DATE:
            raise SystemExit(f"REFUSING: {where}'s override replaced a {was!r} date, which the Said line cannot name")
        return {"card": f"{d} (sourced; the {REPLACED_DATE[was]} is {old})" if old else f"{d} (sourced)",
                "also": f"on {d}"}
    if basis in SAID_BOUND:
        return {"card": f"on or before {d} ({SAID_BOUND[basis]})", "also": f"on or before {d}"}
    raise SystemExit(f"REFUSING: {where} has statement_date_basis {basis!r}, and the Said line has no label for it")


def target_line(p: dict) -> str:
    """The card's "Target": the date with the speaker's words for it, else the words
    alone, else the extractor's inferred horizon and the words it rests on. "none
    stated" only when the record holds none of these."""
    yrs, text = p["horizon_years_inferred"], p["target_date_text"]
    inferred = f"about {yrs:g} years, inferred" if yrs is not None else None
    if p["target_date"] or text:
        t = (p["target_date"] + (f" — “{text}”" if text else "")) if p["target_date"] else f"“{text}”"
        return t + (f" · {inferred}" if inferred else "")
    if inferred:
        return f"{inferred} from: {p['horizon_evidence']}" if p["horizon_evidence"] else inferred
    return "none stated"


def trim(rec: dict) -> dict:
    """What the page needs and nothing else. Dropped: char offsets, status, accepted, telemetry, per-gate verifier booleans, harness/run internals."""
    s, p, c, x, v = rec["source"], rec["prediction"], rec["confidence"], rec["extraction"], rec["verification"]
    return {
        "prediction_id": rec["prediction_id"], "transcript_id": rec["transcript_id"],
        "statement_date": s["statement_date"], "statement_date_basis": s["statement_date_basis"],
        "said": said_label(s, f"{rec['leader_slug']}'s prediction {rec['prediction_id']}"),
        "quote": shown_text(rec, s["quote_original"]), "timestamp_mark": s["timestamp_mark"], "t": ts_seconds(s["timestamp_mark"]),
        "context_before": shown_text(rec, s["context_before"]), "context_after": shown_text(rec, s["context_after"]),
        "claim": p["normalized_claim"], "category": p["category"], "prediction_type": p["prediction_type"],
        "target_date": p["target_date"], "target_date_text": p["target_date_text"], "horizon": p["horizon"],
        "horizon_years_inferred": p["horizon_years_inferred"], "target": target_line(p),
        "resolution_criteria": p["resolution_criteria"],
        "specificity": p["specificity"], "subject_control": p["subject_control"],
        "confidence_type": c["type"], "probability": c["probability"],
        "confidence_language": shown_text(rec, c["verbatim_confidence_language"]),
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


def statement_years(by_slug: dict[str, list[dict]]) -> tuple[dict[str, dict], list[str]]:
    """Per leader, how many accepted predictions carry a statement date in each year, plus the undated count.

    The year span is derived from the records, never hardcoded, so a recording older than
    2009 or a corpus that grows past 2026 widens the axis instead of falling off it. A
    record with no statement date is COUNTED as undated and never placed in a year.
    """
    per: dict[str, dict] = {}
    seen: set[int] = set()
    for slug, recs in by_slug.items():
        years: dict[str, int] = {}
        undated = 0
        for r in recs:
            d = r["source"]["statement_date"]
            if not d:
                undated += 1
                continue
            y = str(datetime.strptime(d[:10], "%Y-%m-%d").year)   # malformed raises; never sliced and hoped for
            years[y] = years.get(y, 0) + 1
            seen.add(int(y))
        per[slug] = {"years": years, "undated": undated}
    if not seen:
        return per, []

    # TRIM A DEAD LEFT EDGE. The span used to run from the single earliest
    # statement in the corpus, and on this data that is one 2009 prediction with
    # nothing at all in 2010 or 2011: three columns carrying one prediction
    # between them, on every one of forty rows.
    #
    # The axis therefore starts at the first year that clears MIN_YEAR_COUNT, and
    # anything earlier is COUNTED rather than dropped, reported per person beside
    # the squares the way undated predictions already are. Trimming the right edge
    # is deliberately not done: the newest years are the point of the chart.
    total = collections.Counter()
    for v in per.values():
        total.update({int(y): n for y, n in v["years"].items()})
    start = min(seen)
    for y in sorted(total):
        if total[y] >= MIN_YEAR_COUNT:
            start = y
            break
    span = [str(y) for y in range(start, max(seen) + 1)]

    for v in per.values():
        early = sum(n for y, n in v["years"].items() if int(y) < start)
        v["early"] = early
        v["years"] = {y: n for y, n in v["years"].items() if int(y) >= start}
    return per, span


# A person appears only if at least one of their predictions has come due. The
# board reports resolved foresight, and a row for somebody with nothing to resolve
# says nothing: five of the fifty have no accepted prediction and no transcript at
# all, and five more have predictions whose deadlines are still in the future.
# Their records stay in the corpus and in the drawers of the aggregate counts;
# they simply do not get a line on a leaderboard. Set to 0 to show everyone.
MIN_PAST_DUE_TO_LIST = 1

# A person needs this many ACCEPTED predictions for a row. Asked for on
# 2026-09-27: Clem Delangue (1), Tobi Lütke (2) and Sergey Brin (3) had so few
# that a row for them read as a finding about them rather than about the
# corpus, and the operator kept Alex Karp, the next up, at 4. It is a rule and
# not a list of names, so a person who later gains predictions reappears on the
# next render with no edit. It applies with or without a scores file, because
# it needs no outcome. Everyone it removes is NAMED under the table.
MIN_PREDICTIONS_TO_LIST = 4


def unlisted_reason(l: dict, sc: "dict | None", scores: dict) -> "str | None":
    """Why this person has no row, or None when they have one. The count floor is
    checked first, so a person with too few predictions is reported under that
    reason whatever their past-due count is."""
    if l["accepted"] < MIN_PREDICTIONS_TO_LIST:
        return "few"
    if scores and (sc or {}).get("past_due", 0) < MIN_PAST_DUE_TO_LIST:
        return "none_due"
    return None


def default_order(rows: list[dict], scored: bool) -> list[dict]:
    """The order the page opens in, which is also the order DATA is emitted in.

    With scores: highest Score first; rows with no Score after every scored row;
    ties and unscored rows in name order. Without: name order. render() in the
    page applies the same rule, and the test pins both."""
    if not scored:
        return sorted(rows, key=lambda r: r["name"])
    return sorted(rows, key=lambda r: (r["score"] is None, -(r["score"] or 0), r["name"]))


def omitted_people(index: dict, scores: dict) -> dict:
    """Everyone in the index without a row, grouped by reason, with what they said."""
    few, none_due, accepted = [], [], 0
    for l in index["leaders"]:
        why = unlisted_reason(l, scores.get(l["slug"]), scores)
        if why is None:
            continue
        accepted += l["accepted"]
        (few if why == "few" else none_due).append(l)
    return {"few": sorted(few, key=lambda l: (l["accepted"], l["name"])),
            "none_due": sorted(none_due, key=lambda l: l["name"]), "accepted": accepted}


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def omitted_note(om: dict) -> str:
    """The line under the table that names who is not in it, and why.

    "Deliberately not listed" and "missing" are different facts, so the page
    states the first rather than leaving a reader to infer the second."""
    e = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    parts = []
    if om["few"]:
        parts.append(f"{_names([f'{e(l['name'])} ({l['accepted']})' for l in om['few']])} "
                     f"{'has' if len(om['few']) == 1 else 'have'} fewer than {MIN_PREDICTIONS_TO_LIST} "
                     f"accepted predictions, too few for a row.")
    if om["none_due"]:
        parts.append(f"{_names([e(l['name']) for l in om['none_due']])} "
                     f"{'has' if len(om['none_due']) == 1 else 'have'} no prediction whose deadline "
                     f"has passed yet.")
    if not parts:
        return ""
    n = om["accepted"]
    parts.append("A person returns to the table as soon as they pass these limits.")
    if n:
        parts.append(f"Their {n} prediction{' still counts' if n == 1 else 's still count'} in the "
                     f"totals at the top of the page.")
    return f'<p class="omitted" id="omitted"><b>Not listed.</b> {" ".join(parts)}</p>'


def listed_corpus(scores_doc: dict, listed: set[str]) -> dict:
    """The score figures for the people the table LISTS, from scores.json's own rows.

    The corpus block counts everyone the scorer saw, including people under the
    list floor, so printing it over the table would describe rows that are not
    there. Before the per-person rows are trusted for that, they must add up to
    the corpus block exactly: if they do not, the two halves of the file were
    computed differently and neither can be printed."""
    c, L = scores_doc["corpus"], scores_doc["leaders"]
    unres_rows = collections.Counter(
        (row["leader_slug"], row["unresolvable_reason"]) for row in scores_doc.get("predictions", [])
        if row.get("outcome") == "unresolvable")
    whole = {
        "past_due": (sum(l["past_due"] for l in L), c["past_due"]),
        "eligible": (sum(l["eligible"] for l in L), c["eligible"]),
        "scored": (sum(l["n_scored"] for l in L), c["scored"]),
        "leaders_ranked": (sum(1 for l in L if l["ranked"]), c["leaders_ranked"]),
        "unresolvable": (sum(l["unresolvable"] for l in L), c["by_outcome"].get("unresolvable", 0)),
        "unresolvable_reasons": (_by_reason(unres_rows, None), dict(c.get("unresolvable_reasons") or {})),
    }
    if "restated" in c:
        lacking = [l["slug"] for l in L if "restated" not in l]
        if lacking:
            raise SystemExit(f"REFUSING: scores.json counts restatements for the corpus but not for "
                             f"{lacking[:5]}; re-run score_predictions.py")
        whole["restated"] = (sum(l["restated"] for l in L), c["restated"])
    bad = {k: v for k, v in whole.items() if v[0] != v[1]}
    if bad:
        raise SystemExit("REFUSING: scores.json's per-person figures do not add up to its corpus block "
                         + ", ".join(f"{k}: people sum to {a}, corpus says {b}" for k, (a, b) in bad.items())
                         + "; re-run score_predictions.py")
    mine = [l for l in L if l["slug"] in listed]
    reasons = _by_reason(unres_rows, listed)
    restated = sum(l.get("restated", 0) for l in mine)
    return {
        # A restated statement is the same prediction as the one it repeats, so the
        # prose counts each past-due prediction once and names the restatements apart.
        "past_due": sum(l["past_due"] for l in mine) - restated,
        "restated": restated,
        "eligible": sum(l["eligible"] for l in mine),
        "scored": sum(l["n_scored"] for l in mine),
        "leaders_ranked": sum(1 for l in mine if l["ranked"]),
        "by_outcome": {"unresolvable": sum(l["unresolvable"] for l in mine)},
        "unresolvable_reasons": dict(reasons),
    }


def _by_reason(unres_rows: collections.Counter, slugs: "set[str] | None") -> dict:
    """Unresolvable counts by reason, over the given people or over everyone."""
    out = collections.Counter()
    for (slug, why), n in unres_rows.items():
        if slugs is None or slug in slugs:
            out[why] += n
    return dict(out)


def _run_path(d: str, scores_path: str) -> Path:
    root = Path(scores_path).resolve().parent.parent          # <data>/predictions/scores.json
    q = Path(d)
    if not q.is_absolute():
        q = root.joinpath(*(q.parts[1:] if q.parts[0] == "data" else q.parts))
    return q


def run_dirs(scores_doc: dict, scores_path: str) -> list[Path]:
    """The run directories scores.json was computed from, on this disk.

    A relative entry is resolved inside the checkout that holds this
    scores.json, never against the current directory: a clone's own `data` link
    may point at an experiment checkout rather than the one being published.
    Two relative forms exist. Until data a5525e31 an entry was written from a
    clone's root, as data/predictions/...; since then it is written from the
    data checkout's root, as predictions/.... Both name the same directory."""
    dirs = scores_doc.get("run_dirs") or ([scores_doc["run_dir"]] if scores_doc.get("run_dir") else [])
    if not dirs:
        raise SystemExit(f"REFUSING: {scores_path} names no run_dirs, so the page cannot read which "
                         "model set each prior; re-run score_predictions.py")
    out = []
    for d in dirs:
        q = _run_path(d, scores_path)
        if not q.is_dir():
            raise SystemExit(f"REFUSING: run directory {d} from {scores_path} is not at {q}; the page "
                             "names the models that set each prior and decided each outcome, and reads "
                             "them from there")
        out.append(q)
    return out


def stage_models(scores_doc: dict, scores_path: str) -> dict:
    """Which model set the prior, and which decided the outcome, for every SCORED prediction.

    Read from the sidecars the scorer joined, never typed here. The prior's p
    must equal the p in scores.json, or these are not the records it scored.
    A prior model counts as served, not merely requested, only when the call's
    own telemetry lists it."""
    dirs = run_dirs(scores_doc, scores_path)
    # Sidecars a statement-date override made stale (priced or resolved under the
    # old date) were dropped by the scorer, and are dropped here the same way.
    stale = (scores_doc.get("date_overrides") or {}).get("stale_sidecars_dropped", [])
    stale_drop = {st: {(_run_path(x["run"], scores_path), x["prediction_id"]) for x in stale if x["stage"] == st}
                  for st in ("prior", "resolve")}
    priors = SP.load_across(dirs, lambda d: R.load_sidecars(d, "prior"), drop=stale_drop["prior"])
    # The resolutions a restatement manifest superseded were left out by the scorer,
    # and are left out here the same way; each must still be on disk.
    drop = {(_run_path(x["run"], scores_path), x["prediction_id"])
            for x in (scores_doc.get("restatements") or {}).get("superseded_resolutions", [])}
    resol = SP.load_across(dirs, lambda d: R.load_sidecars(d, "resolve"), drop=drop | stale_drop["resolve"])
    prior_m, resolve_m, unverified = collections.Counter(), collections.Counter(), 0
    for row in scores_doc.get("predictions", []):
        if not row.get("scored"):
            continue
        pid = row["prediction_id"]
        pri, res = priors.get(pid), resol.get(pid)
        if pri is None or res is None:
            raise SystemExit(f"REFUSING: scored prediction {pid} has no "
                             f"{'prior' if pri is None else 'resolution'} record in {[str(d) for d in dirs]}")
        if pri["p"] != row["p"]:
            raise SystemExit(f"REFUSING: scored prediction {pid} has p {row['p']} in {scores_path} but "
                             f"{pri['p']} in its prior record; these are not the records it was scored from")
        t = pri.get("telemetry") or {}
        m = t.get("canonical_model") or t.get("requested_model")
        if not m:
            raise SystemExit(f"REFUSING: the prior record for {pid} names no model")
        unverified += m not in (t.get("telemetry_models") or [])
        prior_m[model_label(m)] += 1
        rt = res.get("telemetry") or {}
        rm = rt.get("served_model") or rt.get("requested_model")
        if not rm:
            raise SystemExit(f"REFUSING: the resolution record for {pid} names no model")
        resolve_m[model_label(rm)] += 1
    return {"prior": prior_m, "resolve": resolve_m, "prior_unverified": unverified}


def _model_phrase(c: collections.Counter) -> str:
    if len(c) == 1:
        return next(iter(c))
    return _names([f"{m} ({n})" for m, n in c.most_common()])


def signed(x: float) -> str:
    return ("+" if x >= 0 else "\u2212") + f"{abs(x):.2f}"


def howscore(models: dict, n_scored: int) -> str:
    """How a single prediction is scored, with numbers from prediction_score itself.

    The model names come from the sidecars (stage_models), and every number in
    the worked example is computed here by the function that computes the real
    scores. The example also checks, at render time, the property the prose
    claims: at each p the expected points are zero."""
    rows = []
    for p, label in ((0.9, "a near-certainty"), (0.1, "a long shot")):
        hit, miss = PS.score(True, p)["points"], PS.score(False, p)["points"]
        if abs(p * hit + (1 - p) * miss) > 1e-9:
            raise SystemExit(f"REFUSING: at p={p} the expected points are {p * hit + (1 - p) * miss}, not "
                             "zero, so the page's explanation of the rule would be false")
        rows.append(f"<tr><td>p = {p}, {label}</td><td class=\"n\"><span class=\"pos\">{signed(hit)}</span></td>"
                    f"<td class=\"n\"><span class=\"neg\">{signed(miss)}</span></td></tr>")
    served = ("" if not models["prior_unverified"] else
              f" For {models['prior_unverified']} of these calls the reply did not confirm the model, so "
              "that name is the one requested.")
    return (
        '<div class="howscore" id="howscore">'
        "<h3>How one prediction is scored</h3>"
        "<p>Every scored prediction has a number <b>p</b>: the chance the event would happen, judged as "
        "if on the day the words were said. A separate model call sets p "
        f"({e_html(_model_phrase(models['prior']))}, for all {n_scored} scored predictions). That call "
        "sees the quote, the date and the words around it. It does not see what happened. It can "
        "still remember some events from its training, and nothing here removes that. A different "
        f"model ({e_html(_model_phrase(models['resolve']))}) searches the web, decides what happened "
        f"and must cite a source.{served}</p>"
        "<p>A prediction that came true earns <span class=\"f\">&minus;log&#8322;(p)</span> points. One "
        "that did not costs <span class=\"f\">(p/(1&minus;p))&middot;log&#8322;(1/p)</span> points. The "
        "two are set so that a person who only repeats the odds of the day averages zero, whatever "
        "they predict. Calling a near-certainty earns little; calling a long shot earns a lot.</p>"
        "<table><tr><th>If p was</th><th>Came true</th><th>Did not</th></tr>"
        + "".join(rows) + "</table></div>")


def e_html(x) -> str:
    return str(x).replace("&", "&amp;").replace("<", "&lt;")


# Where a prediction stands, in the order the Predictions cell lists them. Short
# plain labels; the column's (?) help defines each one.
BUCKETS = (("scored", "Scored"), ("not_due", "Not yet due"), ("no_deadline", "No deadline"),
           ("awaiting", "Awaiting check"), ("not_testable", "Not testable"),
           ("unresolvable", "Couldn't check"), ("restated", "Restated"))
UNRES_SHORT = {"no_public_evidence": "no public evidence", "criterion_ambiguous": "ambiguous criterion",
               "criterion_undirected": "no direction to test", "threshold_unmeasurable": "number not reported",
               "deadline_incoherent": "deadline makes no sense", "after_knowledge_cutoff": "too recent to check"}


def restated_members(scores_doc: dict, by_slug: dict[str, list[dict]]) -> dict[str, str]:
    """Each restated record on this page, mapped to its cluster's specific member.

    Read from scores.json's `restatements` block, which the scorer wrote from the
    manifest it applied, so the page and the score use one membership. A cluster
    partly on this page refuses the render, because the drawer would show half of
    one prediction. A row the scorer marked `restated:<id>` must agree with the
    block, or the two halves of scores.json describe different manifests."""
    page = {r["prediction_id"] for recs in by_slug.values() for r in recs}
    out: dict[str, str] = {}
    for c in (scores_doc.get("restatements") or {}).get("clusters", []):
        on = [m for m in c["members"] if m in page]
        if not on:
            continue
        if len(on) != len(c["members"]):
            raise SystemExit(f"REFUSING: restatement cluster {c['cluster_id']} has members "
                             f"{sorted(set(c['members']) - page)} that are no record on this page, so its "
                             "drawer would show part of one prediction; render every corpus the scores cover")
        out.update({m: c["specific_member"] for m in c["members"] if m != c["specific_member"]})
    for row in scores_doc.get("predictions", []):
        why = str(row.get("not_scored_because") or "")
        pid = row["prediction_id"]
        if why.startswith("restated:") and out.get(pid) != why.split(":", 1)[1]:
            raise SystemExit(f"REFUSING: scores.json says {pid} is {why}, but its restatements block "
                             + (f"maps it to {out[pid]}" if pid in out else "does not list it")
                             + "; re-run score_predictions.py")
        if pid in out and not why.startswith("restated:"):
            raise SystemExit(f"REFUSING: {pid} is restated in scores.json's restatements block but its row "
                             f"says {why or 'scored'}; re-run score_predictions.py")
    return out


# ---------------------------------------------------------------------------
# One state per record
# ---------------------------------------------------------------------------
#
# FOUND 2026-09-29 (rescue round 4): the Predictions column and the card under it
# answered "where does this prediction stand" separately, and disagreed. The
# column read scores.json. The card read only whether an outcome was attached,
# and printed "Not yet resolved" for every record without one. On the live data
# that was 206 cards, 173 with no deadline and 33 under the lead floor, and no
# stage will ever resolve any of them. record_state now decides once, here, and
# the column counts what it decided and the card prints it.

# The eligibility clauses, in the order the card names them when a record fails
# more than one. A deadline before the statement date also gives a negative lead
# time, and "said -244 days before its own deadline" is not a sentence, so that
# clause comes first. The order is the page's, so the scorer's old strings and its
# new not_eligible:<reason> strings give one card.
NOT_ELIGIBLE_REASONS = ("deadline_before_statement", "undated", "lead_under_floor", "specificity")
FLAG_KEYS = ("deadline_before_statement", "lead_days", "lead_ok", "specificity_ok")
# Every reason the scorer writes for a past-due row it did not score, before and
# after the funnel change that names the eligibility clause (design section 3.5).
ROW_REASONS = ("no_resolution", "no_prior", "not_eligible")
ROW_REASON_PREFIXES = ("unresolvable:", "not_eligible:")


def ineligible_reason(flags: dict, why: str, where: str) -> str:
    """Which eligibility clause an ineligible row fails, read off its funnel flags.

    Before the funnel change the scorer named `no_resolution`, `not_eligible` or
    `unresolvable:<x>` for such a row; after it, `not_eligible:<clause>`. The card
    must not depend on which, so it is decided by the flags, and a named clause
    the flags do not show failing refuses the render rather than being believed."""
    missing = [k for k in FLAG_KEYS if k not in flags]
    if missing:
        raise SystemExit(f"REFUSING: {where} is not eligible, but its scores.json flags lack {missing}, so the "
                         "page cannot say why; re-run score_predictions.py")
    named = why.split(":", 1)[1] if why.startswith("not_eligible:") else None
    if named is not None and named not in NOT_ELIGIBLE_REASONS:
        raise SystemExit(f"REFUSING: {where} is {why!r} in scores.json, a clause the page does not know")
    failing = [c for c, bad in (("deadline_before_statement", flags["deadline_before_statement"]),
                                ("undated", flags["lead_days"] is None),
                                ("lead_under_floor", flags["lead_days"] is not None and not flags["lead_ok"]),
                                ("specificity", not flags["specificity_ok"])) if bad]
    if not failing:
        raise SystemExit(f"REFUSING: {where} is not eligible, but none of its flags fails a clause: {flags}")
    if named is not None and named not in failing:
        raise SystemExit(f"REFUSING: scores.json says {where} is {why}, but its flags fail only "
                         f"{', '.join(failing)}; the two halves of the file disagree")
    return failing[0]


def _date_is_all_it_lacks(rec: dict) -> bool:
    """True when the record's own horizon words would give a deadline if the recording had a date.

    Asked of phase2_resolvability.derived_deadline itself with a stand-in date, so
    the page never parses a horizon a second way. The stand-in is never shown."""
    probe = {**rec, "source": {**rec["source"], "statement_date": "2000-01-01"}}
    return P2.derived_deadline(probe)[0] is not None


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def state_words(st: dict, rec: dict, row: "dict | None", scored_page: bool) -> dict:
    """The card's words for a state: the Outcome line, the note beside a verdict
    that does not count, and, when there is no price, why. Plain text; the page
    escapes it."""
    s, why, d = st["state"], st["reason"], st["deadline"]
    said, p = rec["source"]["statement_date"], rec["prediction"]
    outcome = bool(row and row.get("outcome"))
    past = (f"Judged as a trend over the {st['trend_years']} years from its statement date to {d}"
            if st["trend_years"] is not None else f"Past its {d} deadline")
    line = note = price = None
    if s == "unchecked":
        line = f"Deadline {d}. Not checked: this page was built without a scoring run."
    elif s == "not_due":
        line, price = f"Open until {d}. It is checked after that date.", "Not priced yet: a price is set when it is checked."
    elif s == "no_deadline" and why == "undated":
        words = (f"“{p['target_date_text']}”" if p["target_date_text"]
                 else f"its inferred horizon of about {p['horizon_years_inferred']:g} years")
        line = f"Never checked: the recording has no known date, so no deadline can be computed from {words}."
        price = "Not priced: it never entered the scoring funnel, because the recording has no known date."
    elif s == "no_deadline":
        line = "Never checked: it names no date this pipeline can read."
        price = "Not priced: it never entered the scoring funnel, because it has no deadline."
    elif s == "awaiting" and why == "not_priced":
        line = f"{past} and checked, but not priced yet, so it is not scored yet."
        note, price = "not scored until it is priced", "Not priced yet."
    elif s == "awaiting":
        line, price = f"{past}; not checked yet.", "Not priced yet: a price is set when it is checked."
    elif s == "scored":
        line = f"{past}; checked and scored."
    elif s == "unresolvable":
        line = f"{past}; checked, but it could not be settled, so it is not scored."
        price = "Not priced: it could not be settled, so it is not scored."
    elif s == "not_testable":
        m = st["min_lead"]
        if why == "lead_under_floor":
            line = f"Not scored: said {_days(st['lead_days'])} before its own deadline, {d}, under the {m}-day floor."
            price = "Not priced: it is under the lead floor, so it is never scored."
        elif why == "deadline_before_statement":
            line = f"Not scored: its deadline, {d}, is earlier than the date it is recorded as said, {said}."
            price = "Not priced: its deadline is before its statement date, so it is never scored."
        elif why == "undated":
            line = (f"Not scored: the recording has no known date, so it cannot be shown to have been said at "
                    f"least {m} days before its {d} deadline.")
            price = "Not priced: the recording has no known date, so it is never scored."
        else:
            line = (f"Not scored: rated too vague to test (specificity {p['specificity']}); a scored prediction "
                    f"must be {P2.SPECIFICITY_LABEL}.")
            price = "Not priced: it is too vague to score."
        note = "checked anyway; it does not count toward the score" if outcome else None
    elif s != "restated":
        raise SystemExit(f"REFUSING: the page has no words for state {s!r}")
    p_row = (row or {}).get("p")
    if p_row is not None:
        # A price the card shows beside its verdict needs no reason. One on a record
        # with no verdict to sit beside is said here, in the same line.
        price = None if outcome else (f"Priced at {round(p_row * 100)}%"
                                      + (f" as of {said}" if said else " (the recording has no known date)")
                                      + ", but not checked, so not scored.")
    return {"line": line, "verdict_note": note, "price": price if scored_page else None}


def record_state(rec: dict, row: "dict | None", as_of: "date | None", min_lead: "int | None",
                 restated_to: "str | None" = None) -> dict:
    """Where one accepted prediction stands, decided once, with the card's words for it.

    `rec` carries `_deadline` and `_why_none` from phase2_resolvability.attach_deadlines,
    the code that chose the past-due set. `row` is its scores.json row, or None
    when the scorer did not carry it. `as_of` is the scoring run's as-of date, or
    None when the page is built without a scores file. The state is one of the
    Predictions column's bucket keys, or `unchecked` on a page with no scoring run.
    """
    pid, slug = rec["prediction_id"], rec["leader_slug"]
    where = f"{slug}'s prediction {pid}"
    said = P2.iso(rec["source"]["statement_date"])
    st = {"state": None, "reason": None, "deadline": None, "lead_days": None, "min_lead": min_lead,
          "trend_years": None}
    if restated_to:
        # Shown under its specific member and scored as that one, whether or not it
        # was itself past due: one prediction, one line.
        st.update(state="restated", reason=restated_to)
    elif row is None:
        d = rec["_deadline"]
        if d is None:
            undated = said is None and rec["_why_none"] == "no_statement_date" and _date_is_all_it_lacks(rec)
            st.update(state="no_deadline", reason="undated" if undated else "no_window")
        else:
            st.update(deadline=d.isoformat(), lead_days=P2.lead_days(rec))
            # Past due at the as-of yet absent from scores.json: the corpus grew
            # after the scoring run. It is awaiting a check, which is what it is.
            st.update(state="unchecked" if as_of is None else "not_due" if d > as_of else "awaiting",
                      reason="after_scoring" if as_of is not None and d <= as_of else None)
    else:
        if row.get("leader_slug") != slug:
            raise SystemExit(f"REFUSING: prediction {pid} is {slug}'s on the page "
                             f"but {row.get('leader_slug')}'s in scores.json")
        if not row.get("deadline"):
            raise SystemExit(f"REFUSING: {where} is past due in scores.json, which records no deadline for it")
        flags = row.get("flags")
        st.update(deadline=row["deadline"], lead_days=(flags or {}).get("lead_days"))
        if (flags or {}).get("trend") and said:
            st["trend_years"] = round((date.fromisoformat(row["deadline"]) - said).days / 365.25, 1)
        why = row.get("not_scored_because")
        if row.get("scored"):
            st["state"] = "scored"
        elif not isinstance(why, str) or not (why in ROW_REASONS or why.startswith(ROW_REASON_PREFIXES)):
            raise SystemExit(f"REFUSING: {where} is not scored because {why!r}, and the Predictions column "
                             f"has no bucket for that")
        elif not isinstance((flags or {}).get("eligible"), bool):
            # Read, never assumed: the scorer names a missing resolution before it
            # checks eligibility, so `no_resolution` alone cannot say which it is.
            raise SystemExit(f"REFUSING: {where} is not scored ({why}) and scores.json carries no eligibility "
                             f"flag for it, so the page cannot say whether it is awaiting a check or not testable")
        elif not flags["eligible"]:
            st.update(state="not_testable", reason=ineligible_reason(flags, why, where))
        elif why.startswith("not_eligible"):
            raise SystemExit(f"REFUSING: {where} is {why!r} in scores.json, but its flags say it is eligible; "
                             f"the two halves of the file disagree")
        elif why in ("no_resolution", "no_prior"):
            st.update(state="awaiting", reason="not_checked" if why == "no_resolution" else "not_priced")
        else:
            st.update(state="unresolvable", reason=why.split(":", 1)[1])
    return {**st, **state_words(st, rec, row, scored_page=as_of is not None)}


def record_states(by_slug: dict[str, list[dict]], scores_doc: "dict | None") -> tuple[dict[str, dict], int]:
    """Every accepted record's state at the scoring as-of, keyed by prediction_id.

    A prediction scores.json carries was past due at its as-of, and its row
    decides. One it does not carry was not, and its deadline decides. The
    deadline comes from phase2_resolvability, the same code that chose the
    past-due set, never from a second parser here.

    Returns the states and how many predictions were past due at the as-of yet
    absent from scores.json, which is printed.
    """
    as_of = date.fromisoformat(scores_doc["as_of"]) if scores_doc else None
    min_lead = scores_doc["rule"]["min_lead_days"] if scores_doc else None
    rows = {r["prediction_id"]: r for r in (scores_doc or {}).get("predictions", [])}
    page = {r["prediction_id"] for recs in by_slug.values() for r in recs}
    stray = [(r.get("leader_slug"), pid) for pid, r in rows.items() if pid not in page]
    if stray:
        raise SystemExit(f"REFUSING: scores.json carries {len(stray)} prediction(s) that are no record on "
                         f"this page, e.g. {stray[:3]}, so a person's buckets would not describe their "
                         "drawer; score only the corpus being rendered")
    restated = restated_members(scores_doc, by_slug) if scores_doc else {}
    out, late = {}, 0
    for recs in by_slug.values():
        copies = [dict(r) for r in recs]
        P2.attach_deadlines(copies, derive=True)
        for r in copies:
            st = record_state(r, rows.get(r["prediction_id"]), as_of, min_lead, restated.get(r["prediction_id"]))
            out[r["prediction_id"]] = st
            late += st["reason"] == "after_scoring"
    return out, late


def prediction_buckets(by_slug: dict[str, list[dict]], states: dict[str, dict]) -> dict:
    """Per person, how many accepted predictions sit in each bucket: a count of
    their records' states, so the column and the cards cannot disagree."""
    keys = dict(BUCKETS)
    out = {}
    for slug, recs in by_slug.items():
        b, unres = collections.Counter(), collections.Counter()
        for r in recs:
            st = states[r["prediction_id"]]
            if st["state"] not in keys:
                raise SystemExit(f"REFUSING: {slug}'s prediction {r['prediction_id']} is {st['state']!r}, "
                                 "which the Predictions column has no bucket for")
            b[st["state"]] += 1
            if st["state"] == "unresolvable":
                unres[st["reason"]] += 1
        out[slug] = {"buckets": {k: b[k] for k, _ in BUCKETS if b[k]}, "unres": dict(unres)}
    return out


# What the page embeds of a state: the card reads these, and nothing else of it.
STATE_KEYS = ("state", "reason", "deadline", "lead_days", "min_lead", "line", "verdict_note", "price")


def page_record(rec: dict, st: dict) -> dict:
    """One record as the drawer receives it: its trimmed fields and its state."""
    out = trim(rec)
    out["state"] = {k: st[k] for k in STATE_KEYS}
    if st["state"] == "restated":
        out["restated_by"] = st["reason"]
    return out


# A decodable HTML character reference. The semicolon is required, so "AT&T" and
# "R&D" never match, and html.unescape must actually change it, so "&T;" does not.
ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")


def check_no_entities(pred: dict, src: dict, rows: list[dict]) -> None:
    """Refuse the build when any page-visible text still holds an HTML entity.

    The page escapes "&" before it prints anything, so an entity in the data is
    printed as itself, "it&#39;s", under a person's name as their words. It is
    checked here, in the style of MAX_PAGE_BYTES, over every string the page or
    its record files carry, so a new source that stores escaped text is caught at
    render rather than by a reader."""
    hits: list[str] = []

    def walk(o, where: str) -> None:
        if isinstance(o, str):
            found = [m.group(0) for m in ENTITY.finditer(o) if html.unescape(m.group(0)) != m.group(0)]
            if found:
                hits.append(f"{where} holds {found[0]}")
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{where}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{where}[{i}]")

    for slug, recs in pred.items():
        for r in recs:
            walk(r, f"{slug} {r['prediction_id']}")
    walk(src, "SRC")
    walk(rows, "DATA")
    if hits:
        raise SystemExit(f"REFUSING: {len(hits)} page-visible text field(s) hold an HTML entity, which the page "
                         f"would print literally: {'; '.join(hits[:5])}. Decode it at its source, or in "
                         f"shown_text if the source serves escaped text.")


def check_buckets_sum(rows: list[dict]) -> None:
    """The lines under a total must add up to it, or the cell contradicts itself."""
    bad = [f"{r['name']} ({sum(r['buckets'].values())} in buckets, {r['accepted']} total)"
           for r in rows if r.get("buckets") is not None and sum(r["buckets"].values()) != r["accepted"]]
    if bad:
        raise SystemExit("REFUSING: the Predictions breakdown does not add up to the total for "
                         + "; ".join(bad))


def accepted_info(u: dict, as_of: str, min_lead_days: int) -> str:
    """The Predictions column's (?) panel once there is a scoring run to date it by.

    `u` is the Couldn't-check split over the listed people, summed from the same
    buckets the column shows. The scorer's corpus-wide split also counts records
    that were checked but are not testable, which the column files under Not testable."""
    split = ", ".join(f"{n} {UNRES_SHORT.get(k, k.replace('_', ' '))}"
                      for k, n in sorted(u.items(), key=lambda kv: (-kv[1], kv[0])))
    lab = dict(BUCKETS)
    return (
        "<p><b>Predictions.</b> The total is how many forward-looking claims the pipeline accepted "
        "from this person: the extractor proposed each one and an independent verifier agreed. It is "
        "a count of what was said. Sorting this column sorts by the total.</p>"
        f"<p>The lines under it say where each prediction stood as of {as_of}, the date of the last "
        "scoring run. They always add up to the total, and a line at zero is left out.</p>"
        f"<p><b>{lab['scored']}</b>: past due, checked against a cited source, and given points. "
        f"<b>{lab['not_due']}</b>: its deadline is after {as_of}. "
        f"<b>{lab['no_deadline']}</b>: it names no date this pipeline can read, or the recording has no "
        "known date to count from, so it never falls due. "
        f"<b>{lab['awaiting']}</b>: past due, but not checked yet. "
        f"<b>{lab['not_testable']}</b>: past due, but too vague, said less than {min_lead_days} days "
        "before its own deadline, from a recording with no known date, or with a deadline before the day "
        "it was said. Some were checked anyway; the card says what happened, and it does not count. "
        f"<b>{lab['unresolvable']}</b>: past due, testable and looked at, but nothing public settles it"
        + (f" (for the people listed: {split})" if split else "")
        + ". Hover that line for one person's split. "
        f"<b>{lab['restated']}</b>: the same prediction said again on another day. It is shown once, "
        "under the earliest statement specific enough to settle it, with the others listed beneath it, "
        "and it is scored once, as that statement.</p>")


def person_rows(index: dict, roster: dict, hist: dict[str, dict], scores: dict,
                min_lead_days: int | None = None, buckets: "dict | None" = None) -> list[dict]:
    """One table row per person with enough predictions and, with scores, something due.

    `scores` is keyed by slug and may be empty, in which case every row shows an
    em dash and the page says why. When it is empty the past-due rule hides
    nobody, because without it there is no evidence about who has come due; the
    count floor, MIN_PREDICTIONS_TO_LIST, still applies. Rows come back in the
    page's opening order, default_order.
    """
    rows = []
    for l in index["leaders"]:
        entry = roster.get(l["slug"], {})
        h = hist.get(l["slug"], {"years": {}, "undated": 0})
        sc = scores.get(l["slug"])
        if unlisted_reason(l, sc, scores):
            continue
        rows.append({
            # A person below the floor carries no Score and says so on hover. Never
            # a 0: an absent score and a score of zero mean opposite things here, and
            # zero is a real and meaningful value under this rule.
            "score": (sc["mean_points"] if sc and sc["ranked"] else None),
            "n_scored": (sc["n_scored"] if sc else 0),
            # The fraction has NO floor. It is a plain count, so 0/2 is as honest as
            # 4/6, and the floor protects only the mean, which is noisy at small n.
            # Until 2026-09-27 both cells went blank together, and Bill Gurley's row
            # read as "nothing checked" over a drawer holding two resolved misses.
            # Absent only when nothing was scored, because 0/0 is not a count.
            "score_hits": (sc["scored_occurred"] if sc and sc["n_scored"] else None),
            "hit_rate": (sc["hit_rate"] if sc and sc["n_scored"] else None),
            "ranked": bool(sc and sc["ranked"]),
            "score_why": score_why(sc, min_lead_days),
            "years": h["years"], "undated": h["undated"], "early": h.get("early", 0),
            "slug": l["slug"], "name": l["name"], "role": entry.get("role") or l.get("role"), "company": l.get("company") or entry.get("company"),
            "sector": l.get("sector") or entry.get("sector"),
            "accepted": l["accepted"], "rejected": l["rejected_by_verifier"],
            "buckets": (buckets[l["slug"]]["buckets"] if buckets is not None else None),
            "unres": (buckets[l["slug"]]["unres"] if buckets is not None else None),
            "h_explicit": l["by_horizon"].get("explicit", 0), "h_inferable": l["by_horizon"].get("inferable", 0), "h_none": l["by_horizon"].get("none", 0),
            "p_explicit": l["explicit_probability"], "p_qual": l["qualitative_confidence"],
            "transcripts": l["transcripts_with_accepted"], "earliest": l["earliest_statement_date"],
            "tx_attempted": l["transcripts_on_disk"] or None, "tx_succeeded": l["transcripts_extracted_in_corpus"],
            "by_category": l["by_category"], "by_type": l["by_prediction_type"],
        })
    return default_order(rows, scored=bool(scores))


# Mirrors score_predictions.MIN_SCORED_TO_RANK. Imported rather than typed, so the
# page and the aggregation can never disagree about who gets a number.
MIN_SCORED = SP.MIN_SCORED_TO_RANK

# A year needs this many predictions across the WHOLE corpus before the timeline
# gives it a column. Below it the column is visual noise on every row.
MIN_YEAR_COUNT = 3

CAME_TRUE_HEADER_EMPTY = '<th class="nosort">Came true</th>'
CAME_TRUE_HEADER_LIVE = ('<th data-k="hit_rate">Came true<button class="info" type="button" '
                         'data-info="cametrue" aria-expanded="false" '
                         'aria-label="What does Came true mean?">?</button>'
                         '<span class="arrow">&#9650;</span></th>')

SCORE_HEADER_EMPTY = ('<th class="nosort">Score<button class="info" type="button" data-info="score" '
                      'aria-expanded="false" aria-label="Why is this column empty?">?</button></th>')
SCORE_HEADER_LIVE = ('<th data-k="score" aria-sort="descending">Score<button class="info" type="button" data-info="score" '
                     'aria-expanded="false" aria-label="What does Score mean?">?</button>'
                     '<span class="arrow">&#9650;</span></th>')

# The masthead has to change when the column fills. Saying "every item pending"
# over a table with numbers in it would be the page contradicting itself, and it
# is the sentence a reader takes on trust before looking at anything else.
EYEBROW_EMPTY = "Every item pending"
DISCLAIMER_EMPTY = ("<strong>This is an index of what was said. It is not a ranking of who predicts "
                    "well.</strong> Nothing here has been checked against what happened; every item "
                    "is pending, and the table is alphabetical.")


def eyebrow_status(c: dict) -> str:
    return f"{c['scored']} of {c['past_due']} due predictions resolved"


THESIS_EMPTY = (
    "Forward-looking claims that __N_PEOPLE__ technology leaders made in public, quoted\n"
    "    <strong>verbatim</strong> from transcripts of their own recorded speech, with the date they said\n"
    "    it and the date it refers to. <!-- disclaimer:start -->" + DISCLAIMER_EMPTY + "<!-- disclaimer:end -->")

REPO_URL = "https://github.com/tonygwu/verbatim-index"


def thesis(c: dict, n_people: int) -> str:
    """The intro once the page carries a number, for a general reader.

    Every figure describes the LISTED people (listed_corpus), the same rows the
    table shows. It says what the score covers and what it leaves out, because
    the gap is a large part of the corpus."""
    k = c["leaders_ranked"]
    return (f"<!-- score:start -->Who in tech or finance is best at predicting the future? We track what {n_people} "
            f"tech leaders predicted in public, quoted <strong>word for word</strong> from their own talks "
            f"and interviews. When a deadline passes, we check what happened and score the call against "
            f"how likely it looked on the day it was said. A long shot that comes true earns far more "
            f"than a safe bet. So far {c['scored']} of {c['past_due']} past-due predictions could be "
            f"checked and scored, and {k} {'person has' if k == 1 else 'people have'} enough of them to "
            f'carry a Score. The method and the code are open on <a href="{REPO_URL}">GitHub</a>.'
            f"<!-- score:end -->")


SORT_NOTE_EMPTY = "Every column sorts; the default is alphabetical."
ACCEPTED_INFO_EMPTY = (
    "<p><b>Predictions.</b> How many forward-looking claims the pipeline accepted from this\n"
    "    person's transcripts: the extractor proposed each one and an independent verifier agreed.</p>\n"
    "    <p>A count of what was said, <b>not a measure of foresight</b>. Someone with more long-form\n"
    "    appearances says more things. Nothing here has been checked against what happened.</p>\n"
    "    <p>Open the row to read each one, and to filter by whether it carries a target date and by\n"
    "    what the speaker said about likelihood.</p>")
SORT_NOTE_SCORED = ("<!-- score:start -->Every column sorts. The table opens sorted by Score, highest "
                    "first. People without a Score come after everyone with one, in name order."
                    "<!-- score:end -->")


SCORE_LEGEND_EMPTY = ("<b>Score is empty on every row</b>, and stays empty until outcomes are "
                      "resolved: nothing here has been checked against what happened.")

CAME_TRUE_INFO_EMPTY = (
    "cametrue: `<p><b>Came true</b> is empty until outcomes are resolved.</p>`,")


def came_true_info(c: dict) -> str:
    return (
        "cametrue: `<p><b>How many of a person's scored predictions came true</b>, "
        "out of how many were scored. A plain count, not a rate.</p>"
        "<p>It sits next to Score because the two often disagree, and the disagreement "
        "is the point. Somebody can be right about everything and still score close to "
        "zero, if the things they called were near-certainties. Somebody can be wrong "
        "more often than not and score better, if what they missed were long shots "
        "nobody expected. The fraction is the raw record; Score is what the record was "
        "worth against how likely each call looked at the time.</p>"
        "<p>Only scored predictions are counted. The ones that could not be resolved, "
        "or that were too vague or too close to their own deadline to test, are in "
        "neither number.</p>"
        f"<p>The fraction has no floor: it appears for anyone with at least one scored "
        f"prediction, greyed when there are fewer than {MIN_SCORED}. Score needs the "
        f"{MIN_SCORED}, because a mean over one or two calls says more about the calls "
        f"than the caller.</p>`,")


SCORE_INFO_EMPTY = (
    "score: `<p><b>Score is empty on every row, and that is not a bug.</b> No prediction on this "
    "page has been resolved against what happened, so there is nothing to score. The column is here "
    "to name the gap rather than hide it.</p>"
    "<p>Resolution is separate work. When it runs it will fill each outcome first, and only then "
    "can a column like this hold anything.</p>`,")


def score_legend(c: dict) -> str:
    """The one-sentence description of the column, built from the run's own numbers."""
    return (f"<b>Score</b> is the mean points per resolved prediction, over the "
            f"{c['scored']} of {c['past_due']} past-due predictions that could be resolved against a "
            f"cited source and were specific enough to test. Getting a likely thing right earns "
            f"little and getting an unlikely thing right earns a lot, so the expected score of "
            f"someone with no foresight is zero, whatever they predict. A row shows no number "
            f"below {MIN_SCORED} resolved predictions.")


def score_info(c: dict, rule: dict) -> str:
    """The "?" panel. Every number in it comes from scores.json, never typed here."""
    u = c.get("unresolvable_reasons") or {}
    top = ", ".join(f"{k.replace('_', ' ')} ({v})"
                    for k, v in sorted(u.items(), key=lambda kv: -kv[1])[:3])
    unres = c["by_outcome"].get("unresolvable", 0)
    return (
        "score: `<p><b>Score is the mean points a person earned per resolved prediction.</b> Zero is "
        "the score of someone with no foresight at all, not the bottom of a range. A negative number "
        "means the person did worse than the base rate of the things they were predicting.</p>"
        "<p>Each prediction is worth <b>&minus;log&#8322;(p)</b> points when it came true, where p is "
        "how likely it looked on the day it was said. Calling a 50/50 right earns 1 point; calling a "
        "1-in-20 right earns 4.3. Getting it wrong costs (p/(1&minus;p))&middot;log&#8322;(p), which "
        "is small for a long shot and large for a near-certainty. The two are chosen so that the "
        "expected points are exactly zero at every p, which is why predicting lots of safe things "
        "cannot lift the number and spraying long shots cannot either.</p>"
        "<p>Two separate passes produce each score, and neither sees the other. One decides what "
        "happened and must cite a source for it; it can also answer that the claim cannot be "
        f"resolved, and for the people listed here it did so {unres} time{'' if unres == 1 else 's'}"
        f"{f' (most often {top})' if top else ''}. The other estimates p from the quote, the date and "
        "the surrounding words, and is never told what happened.</p>"
        f"<p>{c['scored']} of {c['past_due']} past-due predictions carry a score. A prediction is left "
        "out when it could not be resolved, when it is too vague to test, or when it was said less "
        f"than {rule['min_lead_days']} days before its own deadline, which the pipeline treats as an "
        "announcement; a few are real forecasts and are excluded by the same rule. "
        f"{c['leaders_ranked']} people have the {MIN_SCORED} resolved predictions a number needs.</p>"
        + (f"<p>{c['restated']} more past-due statement{'s restate' if c['restated'] != 1 else ' restates'} "
           "a prediction already counted: the same claim, said again on another day. Each prediction is "
           "counted and scored once, as the earliest statement specific enough to settle it.</p>"
           if c.get("restated") else "")
        + f"<p>The rule is {rule['baseline_only']}, with p held inside [{rule['clamp']}, "
        f"{1 - rule['clamp']:.2f}] so a stated certainty cannot score infinitely.</p>`,")


def score_why(sc: "dict | None", min_lead_days: int) -> str:
    """What to say on hover when a row carries no number. Never "no data": the
    reasons differ and the difference is the interesting part.

    min_lead_days comes from scores.json's own `rule`, never from
    phase2_resolvability.MIN_LEAD_DAYS. That constant is only a default:
    phase2_resolvability.py exposes --min-lead-days, so a run may not have used
    it. This text was typed as a fixed figure and went stale the day the operator
    lowered the floor, while {MIN_SCORED} four characters away stayed correct
    because it was interpolated."""
    if sc is None:
        return "no prediction of this person's has come due and been resolved"
    if sc["n_scored"] == 0:
        if sc["eligible"] == 0:
            return (f"{sc['past_due']} past due, none eligible: a scored prediction must be specific, "
                    f"reach at least {min_lead_days} days out, and have a coherent window")
        return f"{sc['eligible']} eligible and past due, {sc['unresolvable']} of them could not be resolved"
    return (f"{sc['n_scored']} scored, below the floor of {MIN_SCORED}; "
            f"a number on so few is a placeholder, not a score")


def attach_outcomes(pred: dict, scores_doc: dict | None) -> int:
    """Put each prediction's outcome on the record the page embeds.

    Only the fields a reader needs to check the number: the verdict, the reasoning,
    the cited sources, the probability it was priced at and the points it earned.
    The model telemetry, the run ids and the raw prompt hashes stay in the sidecar,
    the same way the TRIM rule already keeps harness internals off the page. Why a
    record is not scored is its state, which record_state decided; the scorer's own
    string for it is not embedded, because it changed form and the state did not.
    """
    if not scores_doc:
        return 0
    by_id = {r["prediction_id"]: r for r in scores_doc.get("predictions", [])}
    n = 0
    for recs in pred.values():
        for r in recs:
            row = by_id.get(r["prediction_id"])
            if not row or not row.get("outcome"):
                continue
            r["outcome"] = {
                "verdict": row["outcome"],
                "why": row.get("unresolvable_reason"),
                "reasoning": row.get("resolution_reasoning"),
                "sources": row.get("sources") or [],
                "p": row.get("p"),
                "reference_class": row.get("reference_class"),
                "points": row.get("points"),
            }
            n += 1
    return n


def check_scores_are_renderable(scores_doc: dict, pred: dict) -> None:
    """Every SCORED prediction must be one the page can actually show.

    `pred` is the page's records by person, raw or trimmed: only their ids are read.

    `scores.json` can be computed over several corpora, and the page embeds only
    the records under `--predictions`. Score a corpus the page does not carry and
    a person's number is averaged over predictions their own drawer cannot show.
    That is the render-integrity failure this file already guards against for
    counts, in check_index_matches_disk, arriving through the scoring column.

    MEASURED 2026-09-16: scoring the main corpus together with repo-1's
    supplemental web sources put Patrick Collison at 4 scored predictions while
    his drawer held 2. It was invisible only because 4 is below the rank floor,
    so no number was shown. Brian Chesky sat at 4 as well.
    """
    if not scores_doc:
        return
    have = {r["prediction_id"] for recs in pred.values() for r in recs}
    missing: dict[str, int] = {}
    for row in scores_doc.get("predictions", []):
        if row.get("scored") and row["prediction_id"] not in have:
            missing[row["leader_slug"]] = missing.get(row["leader_slug"], 0) + 1
    if missing:
        worst = ", ".join(f"{k} ({v})" for k, v in sorted(missing.items(), key=lambda kv: -kv[1])[:5])
        raise SystemExit(
            f"{sum(missing.values())} scored predictions are not among the records this page "
            f"embeds, so those people's scores would be averaged over predictions their drawer "
            f"cannot show: {worst}. Either pass every corpus the scores cover through "
            f"--predictions, or score only the corpus being rendered.")


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


# The leaderboard's own budget, for the same reason and with the same evidence:
# scripts/build_site.py MAX_PAGE_BYTES. Repeated rather than imported because
# the two pages are built by two scripts and neither should quietly follow the
# other's number.
# VI_MAX_PAGE_BYTES is a test seam only.
MAX_PAGE_BYTES = int(os.environ.get("VI_MAX_PAGE_BYTES") or 2_000_000)


def predictions_payload(pred: dict[str, list]) -> tuple[str, dict[str, str]]:
    """The file each person's records will be published as, and its version key.

    Nothing is written here. The page is built and size-checked first, so a
    refused render leaves the site's records exactly as the last good render
    left them rather than newer than the page that points at them.

    The key is the sha256 of every body, so a browser holding an older copy of
    one person re-fetches it exactly when their records change.
    """
    digest = hashlib.sha256()
    bodies: dict[str, str] = {}
    for slug in sorted(pred):
        recs = pred[slug]
        if not recs:
            continue
        body = json.dumps(recs, ensure_ascii=False, sort_keys=True)
        digest.update(f"{slug}\n{body}\n".encode())
        bodies[slug] = body
    return digest.hexdigest()[:12], bodies


def write_predictions(pred_dir: Path, bodies: dict[str, str]) -> None:
    """Publish each person's accepted predictions as their own file.

    Files from an earlier render that this one did not write are DELETED. A
    person dropped from the index would otherwise keep a reachable file under
    a row that no longer exists.
    """
    pred_dir.mkdir(parents=True, exist_ok=True)
    for slug, body in bodies.items():
        write_atomic(pred_dir / f"{slug}.json", body)
    stale = sorted(f.name for f in pred_dir.glob("*.json") if f.stem not in bodies)
    for name in stale:
        (pred_dir / name).unlink()
    print(f"wrote {len(bodies)} prediction files to {pred_dir} "
          f"({sum(map(len, bodies.values()))/1024/1024:.1f} MB, "
          f"largest {max(map(len, bodies.values()))/1024:.0f} KB)"
          if bodies else f"wrote no prediction files to {pred_dir}")
    if stale:
        print(f"  removed {len(stale)} file(s) no longer in the index: {', '.join(stale)}")


def _iso_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a YYYY-MM-DD date")


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
    pairs = c.get("verifier_acceptance_by_contract_pair", [])
    if pairs:
        descriptions = [
            f"{e(p['extraction_policy_release'] or 'legacy')} / "
            f"{e(p['verification_policy_release'] or 'legacy')} "
            f"(<code>{e(p['extraction_contract'])} / {e(p['verification_contract'])}</code>): "
            f"{e(p['accepted'])} of {e(p['reviewed'])} ({e(round(p['acceptance_rate'] * 100))}%)"
            for p in pairs
        ]
        parts.append("<h3>Verifier acceptance by policy pair</h3><p>"
                     + "; ".join(descriptions) + ".</p>")
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
    # The page's date is the DATA's date, passed in explicitly. The deploy reads it
    # from the published data revision's commit time in UTC. It used to come from
    # index.json's generated_at_utc, which made the index change on every rebuild
    # and conflict on every concurrent push; see test_derived_determinism.py.
    ap.add_argument("--data-date", required=True, type=_iso_date,
                    help="YYYY-MM-DD, the UTC date of the data revision being published")
    ap.add_argument("--year-summaries", default=None,
                    help="the year-square labels from year_summaries.py; default "
                         "<predictions>/year_summaries.json. Required: a cell with no current "
                         "label refuses the build rather than showing a stale one")
    ap.add_argument("--scores", default=None,
                    help="scores.json from score_predictions.py; without it the Score column "
                         "renders empty and the page says why, which is the honest default")
    args = ap.parse_args(argv)

    index = json.loads(Path(args.index).read_text())
    for k in ("run_ids_seen", "contracts_seen", "leaders", "corpus", "coverage", "files_read", "records_read"):
        if k not in index:
            raise SystemExit(f"index.json lacks {k}; re-run aggregate_predictions.py")
    if any("transcripts_extracted_in_corpus" not in l for l in index["leaders"]):
        raise SystemExit("index.json predates transcripts_extracted_in_corpus; re-run aggregate_predictions.py")
    check_og_card(index)
    roster = {r["slug"]: r for r in json.loads(Path(args.roster).read_text())["roster"]}
    loaded = load_records(Path(args.predictions))
    by_slug: dict[str, list[dict]] = {}
    for r in loaded["accepted"]:
        by_slug.setdefault(r["leader_slug"], []).append(r)
    check_index_matches_disk(index, by_slug)
    hist, span = statement_years(by_slug)
    try:
        ysum = YS.summaries_for_page(by_slug, Path(args.year_summaries) if args.year_summaries
                                     else Path(args.predictions) / YS.SUMMARIES_FILE.name)
    except YS.SummaryError as exc:
        raise SystemExit(f"REFUSING: {exc}")
    scores_doc = json.loads(Path(args.scores).read_text()) if args.scores else None
    if scores_doc is not None:
        for k in ("corpus", "leaders", "rule", "as_of"):
            if k not in scores_doc:
                raise SystemExit(f"{args.scores} lacks {k}; re-run score_predictions.py")
        if "min_lead_days" not in scores_doc["rule"]:
            raise SystemExit(
                f"REFUSING: {args.scores} records no rule.min_lead_days, so the page cannot state "
                "the lead-time rule this run used. score_predictions.py writes it; re-run the "
                "scorer rather than letting the page assert a number nobody measured.")
        # A score for somebody not on this page is a mismatched pair of inputs, and it
        # would show up as a silently missing row rather than an error.
        known = {l["slug"] for l in index["leaders"]}
        strays = sorted({l["slug"] for l in scores_doc["leaders"]} - known)
        if strays:
            raise SystemExit(f"{args.scores} scores {strays} who are not in index.json; "
                             f"the two inputs describe different corpora")
    scores = {l["slug"]: l for l in scores_doc["leaders"]} if scores_doc else {}
    check_scores_are_renderable(scores_doc, by_slug)
    # One state per record, decided here and nowhere else: the card prints it and the
    # Predictions column counts it. A restated record carries restated_by, so the
    # drawer shows it under its specific member, never as a card of its own.
    states, late = record_states(by_slug, scores_doc)
    pred = {slug: [page_record(r, states[r["prediction_id"]])
                   for r in sorted(rs, key=lambda r: (r["source"]["statement_date"] or "", r["transcript_id"], L.record_sort_key(r)))]
            for slug, rs in sorted(by_slug.items())}
    buckets = prediction_buckets(by_slug, states) if scores_doc else None
    rows = person_rows(index, roster, hist, scores,
                       scores_doc["rule"]["min_lead_days"] if scores_doc else None, buckets)
    check_buckets_sum(rows)
    couldnt_check = collections.Counter()
    for r in rows:
        couldnt_check.update(r["unres"] or {})
    # Only the years the axis shows; a label for a trimmed early year would never be read.
    for r in rows:
        r["ysum"] = {y: ysum[r["slug"]][y] for y in r["years"]}
    if late:
        print(f"NOTE: {late} prediction(s) were past due on {scores_doc['as_of']} but are not in "
              f"{args.scores}; the corpus grew after scoring, so they show as Awaiting check",
              file=sys.stderr)
    omitted = omitted_people(index, scores)
    # Every score figure the page prints describes the people it LISTS. The
    # corpus-wide totals in the strip (predictions, transcripts) describe
    # everything the pipeline read, and the omitted note says so.
    cl = listed_corpus(scores_doc, {r["slug"] for r in rows}) if scores_doc else None
    models = stage_models(scores_doc, args.scores) if scores_doc else None
    n_outcomes = attach_outcomes(pred, scores_doc)
    src = src_map(loaded["accepted"])
    check_no_entities(pred, src, rows)
    c = index["corpus"]
    ex = " / ".join(model_label(m) for m in c["extractor_models"]) or "none yet"
    ve = " / ".join(model_label(m) for m in c["verifier_models"]) or "none yet"
    dated = c["accepted"] - c["statement_date_unknown"]
    contracts = ", ".join(sorted(set(index["contracts_seen"]["extraction"]) | set(index["contracts_seen"]["verification"]))) or "none"
    data_js, src_js = safe_json(rows), safe_json(src)
    # The records go beside the page, and must be written BEFORE the page that
    # points at them.
    pred_dir = Path(args.out).resolve().parent / "predictions"
    pred_version, pred_bodies = predictions_payload(pred)
    pred_slugs = sorted(pred_bodies)
    html_out = (TEMPLATE
        .replace("__FONTS__", FONT_LINKS)
        .replace("__THEME__", THEME_CSS)
        .replace("__SOCIAL_TITLE__", SOCIAL_TITLE)
        .replace("__SOCIAL_DESC__", SOCIAL_DESC_SCORED if scores_doc else SOCIAL_DESC)
        .replace("__THESIS__", thesis(cl, len(rows)) if scores_doc else THESIS_EMPTY)
        .replace("__SORT_NOTE__", SORT_NOTE_SCORED if scores_doc else SORT_NOTE_EMPTY)
        .replace("__SORT_KEY__", '"score"' if scores_doc else '"name"')
        .replace("__SORT_DIR__", "-1" if scores_doc else "1")
        .replace("__NAME_ARIA__", "" if scores_doc else ' aria-sort="ascending"')
        .replace("__HOWSCORE__", howscore(models, cl["scored"]) if scores_doc else "")
        .replace("__OMITTED__", omitted_note(omitted))
        .replace("__BUCKETS__", safe_json([list(b) for b in BUCKETS]))
        .replace("__UNRES_SHORT__", safe_json(UNRES_SHORT))
        .replace("__ACCEPTED_INFO__", accepted_info(dict(couldnt_check), scores_doc["as_of"], scores_doc["rule"]["min_lead_days"])
                 if scores_doc else ACCEPTED_INFO_EMPTY)
        .replace("__REPO_URL__", REPO_URL)
        .replace("__SITE_URL__", SITE_URL)
        .replace("__OG_VERSION__", og_version())
        .replace("__DATA__", data_js)
        .replace("__SRC__", src_js)
        .replace("__MIN_SCORED__", str(MIN_SCORED))
        .replace("__PRED_VERSION__", pred_version)
        .replace("__PRED_SLUGS__", safe_json(pred_slugs))
        .replace("__YEARS__", safe_json(span))
        .replace("__Y0__", span[0] if span else "n/a")
        .replace("__Y1__", span[-1] if span else "n/a")
        .replace("__EYEBROW_STATUS__", eyebrow_status(cl) if scores_doc else EYEBROW_EMPTY)
        .replace("__CAME_TRUE_HEADER__", CAME_TRUE_HEADER_LIVE if scores_doc else CAME_TRUE_HEADER_EMPTY)
        .replace("__CAME_TRUE_INFO__", came_true_info(cl) if scores_doc
                 else CAME_TRUE_INFO_EMPTY)
        .replace("__SCORE_HEADER__", SCORE_HEADER_LIVE if scores_doc else SCORE_HEADER_EMPTY)
        .replace("__SCORE_LEGEND__", score_legend(cl) if scores_doc else SCORE_LEGEND_EMPTY)
        .replace("__SCORE_INFO__", score_info(cl, scores_doc["rule"]) if scores_doc
                 else SCORE_INFO_EMPTY)
        .replace("__METHOD__", build_method(index, loaded))
        .replace("__GENDATE__", nice_date(args.data_date))
        .replace("__N_PEOPLE__", str(len(rows)))
        .replace("__N_TX__", str(index["coverage"]["extract"].get("ok", 0)))
        .replace("__N_ACCEPTED__", str(c["accepted"]))
        .replace("__PCT_DATED__", str(round(100 * dated / c["accepted"])) if c["accepted"] else "0")
        .replace("__N_PROB__", str(c["explicit_probability"]))
        .replace("__EXTRACTOR__", ex)
        .replace("__VERIFIER__", ve)
        .replace("__RUN_ID__", ", ".join(index["run_ids_seen"][-3:]) or "none")
        .replace("__CONTRACT_ID__", contracts))
    size = len(html_out.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        raise SystemExit(f"REFUSING: the page is {size:,} bytes, over the {MAX_PAGE_BYTES:,} "
                         f"budget a link crawler will fetch. Something large is inlined again; "
                         f"the prediction records belong in {pred_dir}, not in the document.")
    write_predictions(pred_dir, pred_bodies)
    write_atomic(args.out, html_out)
    if scores_doc:
        sc = scores_doc["corpus"]
        print(f"scores: {sc['scored']} of {sc['past_due']} past due scored, "
              f"{sc['leaders_ranked']} people ranked, {n_outcomes} outcomes attached to drawers, "
              f"as of {scores_doc['as_of']}")
        print(f"listed: {len(rows)} people; the page prints {cl['scored']} of {cl['past_due']} past due "
              f"scored and {cl['leaders_ranked']} people ranked; prior model "
              f"{dict(models['prior'])}, resolver {dict(models['resolve'])}")
    else:
        print("scores: none supplied; the Score column renders empty")
    ctx = [len(r["context_before"]) + len(r["context_after"]) for rs in pred.values() for r in rs]
    print(f"wrote {args.out}  ({len(html_out) // 1024} KB; DATA {len(data_js) // 1024} KB, SRC {len(src_js) // 1024} KB, "
          f"records in {len(pred_slugs)} files beside it; {len(rows)} people listed, "
          f"{len(omitted['few'])} under the floor of {MIN_PREDICTIONS_TO_LIST} and "
          f"{len(omitted['none_due'])} with nothing due not listed; {c['accepted']} accepted, "
          f"{loaded['rejected']} rejected not embedded; "
          f"context chars median {int(statistics.median(ctx)) if ctx else 0} max {max(ctx) if ctx else 0})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
