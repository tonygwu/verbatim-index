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



# The leaderboard's own card. It shows the top of the real table, because a
# card that only carries a wordmark says nothing about what is behind the link.
# The palette and type are the site's light theme, restated rather than
# imported for the same reason CARD restates them: site_theme.THEME_CSS carries
# both themes and a card has exactly one appearance.
#
# Everything drawn here comes out of results.json. The rows are the published
# ranking, so the sidecar records them and build_site.py warns when the board
# moves under a card drawn from an older one.
BOARD_CARD = """<!DOCTYPE html>
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
    padding:44px 56px 40px; display:flex; flex-direction:column;
    -webkit-font-smoothing:antialiased;
  }
  .top{display:flex; align-items:flex-end; justify-content:space-between; gap:40px}
  h1{
    font-family:"Instrument Serif",Georgia,serif; font-weight:400;
    font-size:74px; line-height:.92; letter-spacing:-.018em;
  }
  h1 em{font-style:italic; color:#BA5416}
  .eyebrow{
    font-family:"IBM Plex Mono",monospace; font-size:17px; letter-spacing:.15em;
    text-transform:uppercase; color:#5B646F; margin-bottom:14px;
  }
  .thesis{font-size:25px; line-height:1.3; color:#3C4450; max-width:20ch; text-align:right}
  .thesis b{color:#15181D; font-weight:600}

  table{width:100%; border-collapse:collapse; margin-top:30px}
  th{
    font-family:"IBM Plex Mono",monospace; font-size:14px; font-weight:500;
    letter-spacing:.11em; text-transform:uppercase; color:#8A929C;
    text-align:left; padding:0 0 10px; border-bottom:1px solid #C3C8D1;
  }
  th.n{text-align:right}
  td{padding:17px 0; border-bottom:1px solid #DCDFE5; vertical-align:middle}
  tr:last-child td{border-bottom:none}
  .rk{
    width:46px; font-family:"IBM Plex Mono",monospace; font-size:21px; color:#8A929C;
    font-variant-numeric:tabular-nums;
  }
  .nm{font-size:31px; font-weight:600; letter-spacing:-.01em; line-height:1.1}
  .rl{font-size:17px; color:#5B646F; margin-top:4px}
  .org{font-size:21px; color:#3C4450; width:250px; padding-right:24px}
  .sec{
    display:block; font-family:"IBM Plex Mono",monospace; font-size:13px;
    letter-spacing:.09em; text-transform:uppercase; color:#8A929C; margin-top:5px;
  }
  td.ov{background:#E9EBEF; width:118px; padding-left:22px}
  .ov b{font-family:"IBM Plex Mono",monospace; font-size:35px; font-weight:600;
        font-variant-numeric:tabular-nums; letter-spacing:-.02em}
  td.d{width:132px; padding-left:22px}
  .d b{font-family:"IBM Plex Mono",monospace; font-size:24px; font-weight:500;
       font-variant-numeric:tabular-nums; display:block}
  .bar{display:block; width:78px; height:6px; border-radius:3px; background:#DCDFE5;
       overflow:hidden; margin-top:7px}
  .bar i{display:block; height:100%; border-radius:3px}
  .k2 i{background:#BA5416} .k3 i{background:#00875A} .k1 i{background:#2E6FC9}

  .strip{
    margin-top:auto; padding-top:20px; display:flex; justify-content:space-between;
    align-items:baseline; font-family:"IBM Plex Mono",monospace; font-size:17px;
    letter-spacing:.06em; color:#5B646F; border-top:1px solid #C3C8D1;
  }
  .strip b{color:#15181D; font-weight:600}
  .strip .more{color:#8A929C}
</style>
</head>
<body>
  <div class="top">
    <div>
      <div class="eyebrow">__DOMAIN__</div>
      <h1>Verbatim <em>__WORDMARK__</em></h1>
    </div>
    <p class="thesis">__TAGLINE__</p>
  </div>
  <table>
    <thead><tr>
      <th></th><th>Leader</th><th>Organisation</th>
      <th style="padding-left:22px">Overall</th>
      <th style="padding-left:22px">Insight</th>
      <th style="padding-left:22px">Technical</th>
      <th style="padding-left:22px">Clarity</th>
    </tr></thead>
    <tbody>__ROWS__</tbody>
  </table>
  <div class="strip"><div>__STRIP__</div><div class="more">__MORE__</div></div>
</body>
</html>
"""

# Three rows, because a fourth costs the type size that keeps the card legible
# where it is shown small. A timeline card is about 500px wide, so everything
# here is read at roughly two-fifths of the size it is drawn at.
BOARD_ROWS = 3


def meter(value: float, cls: str) -> str:
    """The site's own meter: the number, and a bar filled to it on a 0-100 scale."""
    w = max(0.0, min(100.0, float(value)))
    return (f'<td class="d"><b>{value:.1f}</b>'
            f'<span class="bar {cls}"><i style="width:{w:.0f}%"></i></span></td>')


def board_rows(results: dict) -> tuple[str, list[dict]]:
    """The published top rows, drawn exactly as the page ranks them."""
    scored = [l for l in results["leaders"] if l["status"] == "scored"]
    scored.sort(key=lambda l: (l.get("rank") or 10**6, -l["blinded"]["overall"]))
    top = scored[:BOARD_ROWS]
    if len(top) < BOARD_ROWS:
        sys.exit(f"REFUSING: results.json has {len(top)} scored leaders, "
                 f"fewer than the {BOARD_ROWS} the card draws")
    html, drawn = [], []
    for l in top:
        b = l["blinded"]
        html.append(
            f'<tr><td class="rk">{l["rank"]}</td>'
            f'<td><div class="nm">{esc(l["name"])}</div>'
            f'<div class="rl">{esc(short_role(l["role"]))}</div></td>'
            f'<td class="org">{esc(l["company"])}<span class="sec">{esc(l["sector"])}</span></td>'
            f'<td class="ov"><b>{b["overall"]:.1f}</b></td>'
            + meter(b["d2_insight"], "k2")
            + meter(b["d3_technical_depth"], "k3")
            + meter(b["d1_clarity"], "k1")
            + "</tr>")
        drawn.append({"rank": l["rank"], "slug": l["slug"],
                      "overall": round(b["overall"], 1)})
    return "".join(html), drawn


def short_role(role: str) -> str:
    """One clause. Full roles run to 80 characters and wrap to three lines here."""
    cut = role.split(";")[0].split(" (")[0].strip()
    return cut if len(cut) <= 44 else cut[:43].rstrip(" ,") + "\u2026"


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


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
        # Shorter than the page's own line: it sits in a narrow column beside
        # the wordmark, above the rows that now carry the rest of the message.
        "tagline": ("Ranked on the thinking their <b>public speech</b> "
                    "actually demonstrates."),
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
    if args.site == "leaderboard":
        # The board's card shows the top of the real table. The rows go in the
        # sidecar too, so build_site.py can say when the ranking has moved
        # under a card drawn from an older one.
        rows_html, counts["top"] = board_rows(json.loads(Path(args.results).read_text()))
        strip = " &middot; ".join(f"<b>{value}</b> {label.lower()}" for label, value in stats)
        more = counts["leaders"] - BOARD_ROWS
        html = (BOARD_CARD
                .replace("__DOMAIN__", site["domain"])
                .replace("__WORDMARK__", site["wordmark"])
                .replace("__TAGLINE__", site["tagline"])
                .replace("__ROWS__", rows_html)
                .replace("__STRIP__", strip)
                .replace("__MORE__", f"and {more} more &rarr;"))
    else:
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
