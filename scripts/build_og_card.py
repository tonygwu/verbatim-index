#!/usr/bin/env python3
"""Draw the 1200x630 image Twitter and LinkedIn show for a link to one of the sites.

Serves both published sites, named by --site: `leaderboard` draws site/og.png
from results.json, and `predictions` draws site-predictions/og.png from the
predictions index.json. The card carries counts, so it is rendered from the
corpus rather than from numbers typed here, and it writes a sidecar recording
what it drew. Each site's builder reads that sidecar and warns when the drawn
counts no longer match the corpus.

The card is a committed asset rather than something the render pipeline draws on
every cycle. Drawing it needs a browser, and putting a browser in the grading
loop's publication path would make a deploy fail for a reason unrelated to the
data. Re-run this by hand when the roster or the corpus moves.

Usage:
  build_og_card.py --site leaderboard --results ../data/results.json --transcripts ../data/transcripts_blind
  build_og_card.py --site predictions --index ../data/predictions/index.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
)

# The site's own light palette, restated here rather than imported, because
# site_theme.THEME_CSS carries both themes plus the dark-mode media queries and
# a social card has exactly one appearance.
CARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  *{box-sizing:border-box; margin:0; padding:0}
  html,body{width:1200px; height:630px}
  body{
    background:#F2F3F5; color:#15181D;
    font-family:"IBM Plex Sans",-apple-system,sans-serif;
    padding:74px 84px; display:flex; flex-direction:column;
    justify-content:space-between; -webkit-font-smoothing:antialiased;
  }
  .eyebrow{
    font-family:"IBM Plex Mono",monospace; font-size:19px; letter-spacing:.15em;
    text-transform:uppercase; color:#5B646F;
  }
  h1{
    font-family:"Instrument Serif",Georgia,serif; font-weight:400;
    font-size:132px; line-height:.98; letter-spacing:-.018em; margin-top:26px;
  }
  h1 em{font-style:italic; color:#BA5416}
  .thesis{
    margin-top:30px; font-size:31px; line-height:1.34; color:#3C4450;
    max-width:23ch;
  }
  .thesis b{color:#15181D; font-weight:600}
  .strip{
    display:flex; border-top:1px solid #C3C8D1; padding-top:22px; gap:0;
  }
  .strip div{flex:1; border-right:1px solid #DCDFE5; padding-right:26px}
  .strip div + div{padding-left:34px}
  .strip div:last-child{border-right:none}
  dt{
    font-family:"IBM Plex Mono",monospace; font-size:16px; letter-spacing:.11em;
    text-transform:uppercase; color:#8A929C; margin-bottom:9px;
  }
  dd{
    font-family:"IBM Plex Mono",monospace; font-size:40px; font-weight:500;
    font-variant-numeric:tabular-nums; letter-spacing:-.02em;
  }
</style>
</head>
<body>
  <div>
    <div class="eyebrow">__DOMAIN__</div>
    <h1>Verbatim <em>__WORDMARK__</em></h1>
    <p class="thesis">__TAGLINE__</p>
  </div>
  <dl class="strip">__STATS__</dl>
</body>
</html>
"""


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).is_file():
            return c
        found = shutil.which(c)
        if found:
            return found
    sys.exit("REFUSING: no Chrome or Chromium found to render the card")


def leaderboard_counts(args) -> tuple[dict, list[tuple[str, str]]]:
    from build_site import published_judges
    results = json.loads(Path(args.results).read_text())
    d = results["diagnostics"]
    counts = {
        "leaders": len([l for l in results["leaders"] if l["status"] == "scored"]),
        "transcripts": d.get("transcripts_with_blinded_consensus", 0),
        "judges": len(published_judges(results)),
    }
    # Summed the same way build_site.py sums it, so the card and the page
    # cannot disagree about the one number that appears on both.
    words = 0
    tdir = Path(args.transcripts)
    for f in tdir.rglob("*.json"):
        try:
            words += json.loads(f.read_text()).get("word_count", 0)
        except Exception:
            pass
    if not words:
        sys.exit(f"REFUSING: no word counts under {tdir}")
    counts["words_graded"] = words
    stats = [("Leaders", str(counts["leaders"])),
             ("Transcripts", str(counts["transcripts"])),
             ("Judges", str(counts["judges"])),
             ("Words graded", f"{words / 1e6:.1f}M")]
    return counts, stats


def predictions_counts(args) -> tuple[dict, list[tuple[str, str]]]:
    """Every figure comes straight out of index.json.

    The page's own "People" stat is deliberately NOT drawn here. That number is
    person_rows()'s output, which filters the index against the roster and a
    listing floor, so index.json alone cannot reproduce it and a card drawn
    from the index would quietly disagree with the page beside it. The people
    count goes in the card's DESCRIPTION instead, where the page substitutes
    its own __N_PEOPLE__.
    """
    index = json.loads(Path(args.index).read_text())
    c = index["corpus"]
    accepted = c["accepted"]
    if not accepted:
        sys.exit(f"REFUSING: {args.index} reports no accepted predictions")
    dated = accepted - c["statement_date_unknown"]
    counts = {
        "predictions": accepted,
        "transcripts_scanned": index["coverage"]["extract"].get("ok", 0),
        "pct_dated": round(100 * dated / accepted),
    }
    stats = [("Predictions", str(counts["predictions"])),
             ("Transcripts scanned", str(counts["transcripts_scanned"])),
             ("With a date said", f"{counts['pct_dated']}%")]
    return counts, stats


SITES = {
    "leaderboard": {
        "out": REPO / "site" / "og.png",
        "domain": "verbatim-index.tonygwu.com",
        "wordmark": "Index",
        "tagline": ("Tech leaders, ranked on the thinking their "
                    "<b>public speech</b> actually demonstrates."),
        "counts": leaderboard_counts,
        "requires": ("results", "transcripts"),
    },
    "predictions": {
        "out": REPO / "site-predictions" / "og.png",
        "domain": "verbatim-predictions.tonygwu.com",
        "wordmark": "Predictions",
        "tagline": ("Forward-looking claims, quoted <b>verbatim</b> from "
                    "what tech leaders said on the record, with the date."),
        "counts": predictions_counts,
        "requires": ("index",),
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", choices=sorted(SITES), default="leaderboard")
    ap.add_argument("--results")
    ap.add_argument("--transcripts",
                    help="blinded transcripts dir; word count is summed exactly as build_site.py sums it")
    ap.add_argument("--index", help="predictions index.json")
    ap.add_argument("--out")
    args = ap.parse_args()

    site = SITES[args.site]
    missing = [f"--{r}" for r in site["requires"] if not getattr(args, r)]
    if missing:
        sys.exit(f"REFUSING: --site {args.site} needs {', '.join(missing)}")

    counts, stats = site["counts"](args)
    cells = "".join(f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in stats)
    html = (CARD
            .replace("__DOMAIN__", site["domain"])
            .replace("__WORDMARK__", site["wordmark"])
            .replace("__TAGLINE__", site["tagline"])
            .replace("__STATS__", cells))

    out = Path(args.out) if args.out else site["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "card.html"
        src.write_text(html)
        subprocess.run(
            [find_chrome(), "--headless", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=1", "--window-size=1200,630",
             "--virtual-time-budget=20000",
             f"--screenshot={out}", src.as_uri()],
            check=True, capture_output=True,
        )
    if not out.is_file() or out.stat().st_size < 5000:
        sys.exit(f"REFUSING: {out} was not written, or is too small to be the card")

    meta = out.with_suffix(".meta.json")
    meta.write_text(json.dumps(
        {"site": args.site, "counts": counts,
         "drawn_by": "scripts/build_og_card.py",
         "note": "The site builder warns when these counts drift from the corpus."},
        indent=1) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes) and {meta.name}")
    print(f"  site {args.site}, counts: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
