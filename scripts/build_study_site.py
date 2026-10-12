#!/usr/bin/env python3
"""Render a study's public page from its profile. Used for every study except leaders.

build_site.py keeps its hand-written leaders template, whose copy carries
measured leaders-specific numbers. Any other study is handed here by
build_site.py, and nothing on this page is typed for one rubric:

  - dimensions, labels and weights come from profiles/<study>.json;
  - every sentence of prose comes from the file named by the profile's
    `site_copy`, which is checked against the profile before rendering;
  - percentages are computed from the weights. Copy that types a percentage is
    refused, because a typed number is the one that goes stale when a weight
    changes, which is how the leaders page once disagreed with its own score.

Every value from results.json and every string from the copy file is
HTML-escaped. A missing score renders as a dash, never as zero.

Called through build_site.py:
  build_site.py --study pundits --results ... --audit ... --roster ... \
      --calibration ... --out site-pundits/index.html
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_theme import FONT_LINKS, THEME_CSS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REQUIRED_COPY = ("study_id", "title", "site_url", "tagline", "interpretation", "blinding_note", "dimensions",
                 "method", "status_label", "status_note")
# The tab and bookmark icon, inline so the page needs no second file: the
# study's initial in the page's ink and surface colours.
ICON_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
            "<rect width='32' height='32' rx='6' fill='#15181D'/>"
            "<text x='16' y='23' font-family='Georgia,serif' font-size='22' text-anchor='middle' "
            "fill='#FCFCFB'>{initial}</text></svg>")
_TYPED_PERCENT = re.compile(r"\d+\s*%")


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def load_copy(profile: dict) -> dict:
    ref = profile.get("site_copy")
    if not ref:
        raise RuntimeError(f"profile {profile.get('study_id')!r} names no site_copy file")
    path = Path(ref) if Path(ref).is_absolute() else REPO / ref
    if not path.is_file():
        raise RuntimeError(f"site copy {path} does not exist")
    return json.loads(path.read_text())


def validate_copy(profile: dict, copy: dict) -> None:
    missing = [k for k in REQUIRED_COPY if k not in copy]
    if missing:
        raise RuntimeError(f"site copy is missing {missing}")
    if not re.fullmatch(r"https://[a-z0-9.-]+/", copy["site_url"]):
        raise RuntimeError(f"site_url {copy['site_url']!r} must be https://<host>/")
    if copy["study_id"] != profile["study_id"]:
        raise RuntimeError(f"site copy is for study {copy['study_id']!r}, not {profile['study_id']!r}")
    keys = [d["key"] for d in profile["scoring"]["dimensions"]]
    for k in keys:
        entry = copy["dimensions"].get(k)
        if not isinstance(entry, dict) or not entry.get("question") or not entry.get("explainer"):
            raise RuntimeError(f"site copy has no question and explainer for dimension {k}")
    extra = sorted(set(copy["dimensions"]) - set(keys))
    if extra:
        raise RuntimeError(f"site copy explains dimensions the profile does not score: {extra}")
    typed = _TYPED_PERCENT.findall(json.dumps(copy))
    if typed:
        raise RuntimeError(f"site copy types a percentage ({typed}); weights are rendered from the profile, "
                           f"so a typed % would go stale when a weight changes")


def num(v, signed: bool = False) -> str:
    if not isinstance(v, (int, float)):
        return "&ndash;"
    return f"{v:+.1f}" if signed else f"{v:.1f}"


def interval(block: dict, signed: bool = False) -> str:
    """A block's bootstrap interval as "[lo, hi]", or nothing when it has none.

    Nothing rather than a pair of dashes: a score whose interval was never
    computed is a different fact from a score whose interval is unknown, and
    the plan wants every published interval to be a real one.
    """
    lo, hi = block.get("ci_low"), block.get("ci_high")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lo, hi)):
        return ""
    return f' <span class="ci">[{num(lo, signed)}, {num(hi, signed)}]</span>'


CSS = r"""
*{box-sizing:border-box}
body{background:var(--ground); color:var(--ink); margin:0;
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.5}
main{max-width:1080px; margin:0 auto; padding-block:32px 64px; padding-inline:20px}
h1{font-family:"Instrument Serif",Georgia,serif; font-weight:400; font-size:clamp(2.2rem,5vw,3.4rem); margin:0}
h2{font-family:"Instrument Serif",Georgia,serif; font-weight:400; font-size:1.6rem; margin:40px 0 8px}
.tagline{color:var(--ink-2); font-size:1.1rem; margin:6px 0 20px}
.note{background:var(--surface); border:1px solid var(--rule); border-radius:8px; padding:12px 16px; margin:10px 0;
  color:var(--ink-2)}
ul.dims{list-style:none; padding:0; margin:16px 0}
ul.dims li{margin:10px 0}
.sw{display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:8px}
.wrap{overflow-x:auto; background:var(--surface); border:1px solid var(--rule); border-radius:8px}
table{border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums}
th,td{padding:8px 10px; border-bottom:1px solid var(--rule); text-align:left; white-space:nowrap}
th{font-size:.8rem; color:var(--muted); font-weight:600}
td.num,th.num{text-align:right; font-family:"IBM Plex Mono",monospace}
td.person b{font-weight:600}
td.person span{display:block; color:var(--muted); font-size:.85rem}
td.person span.mix{color:var(--faint); font-size:.8rem}
.ci{color:var(--faint); font-size:.85rem}
footer{color:var(--faint); font-size:.85rem; margin-top:40px}
/* A phone must see rank, person and the blinded score without scrolling the
   table (scripts/check_pundits_phone_layout.py): the person cell wraps, and each
   interval drops below its score. */
@media (max-width:600px){
  main{padding-inline:16px}
  th,td{padding:8px 6px}
  th{white-space:normal}
  td.person{white-space:normal; min-width:7.5rem}
  td.num .ci{display:block; font-size:.75rem}
}
"""


def roster_size(results: dict) -> int:
    """Everyone on the roster: ranked, scored below the rank floor, and not yet scored."""
    return sum(len(results.get(k) or []) for k in ("leaders", "unranked", "unscored"))


def status_banner(results: dict, copy: dict) -> str:
    """How much evidence stands behind this board, in figures taken from the run.

    Every number here is DERIVED. None may be typed into the copy file, because a
    typed number goes stale the moment the corpus grows, and this repo has twice
    published copy that had gone stale that way. `status_note` carries the prose
    and `_TYPED_PERCENT` already refuses a percentage inside it.

    Written for a PILOT board, but nothing here is pilot-specific: when the whole
    roster is scored the first clause reads "39 of 39" on its own.
    """
    d = results.get("diagnostics") or {}
    ranked = results.get("leaders") or []
    roster = roster_size(results)
    ns = [p.get("n_transcripts") for p in ranked if isinstance(p.get("n_transcripts"), int)]
    bits = [f"<b>{esc(copy['status_label'])}.</b> {esc(copy['status_note'])}"]
    bits.append(f"It ranks {len(ranked)} of {roster} people on the roster")
    if ns:
        lo, hi = min(ns), max(ns)
        bits[-1] += (f", each on {lo} recordings." if lo == hi
                     else f", each on {lo} to {hi} recordings.")
    else:
        bits[-1] += "."
    leak = d.get("blinding_leakage_rate")
    if isinstance(leak, (int, float)):
        bits.append(f"Blinding removes the name from the transcript and does not make the speaker "
                    f"unknown: the judges still identified them on {leak * 100:.0f}% of blinded "
                    f"recordings, so read the blinded score as name-removed rather than anonymous.")
    if d.get("venue_adjustment_applied") is False:
        reasons = d.get("venue_support_reasons") or []
        why = f" ({esc('; '.join(reasons))})" if reasons else ""
        bits.append("Scores carry no correction for the format of the appearance. It was fitted and "
                    f"then <b>withheld</b>, because the corpus does not yet support it{why}. A "
                    "reaction stream and a sit-down interview are not equally demanding, and that "
                    "difference sits inside these scores.")
    return '<p class="status">' + " ".join(bits) + "</p>"


def venue_mix(results: dict) -> dict[str, str]:
    """Each person's formats, as "5 conversation, 2 reaction, 1 debate".

    Plan P5 dropped the venue caps and handles format partly by showing this mix.
    It counts each scored recording once, from its blinded row, because the open
    row is the same recording. Largest first; equal counts in name order, so the
    text is the same on every build. A recording with no venue says so rather
    than being dropped.
    """
    seen: dict[str, dict[str, str]] = {}
    for t in results.get("transcripts") or []:
        if t.get("mode") != "blinded":
            continue
        seen.setdefault(t.get("leader_slug"), {})[t.get("source_id")] = t.get("venue_type") or "format not recorded"
    out = {}
    for slug, by_source in seen.items():
        counts: dict[str, int] = {}
        for v in by_source.values():
            counts[v] = counts.get(v, 0) + 1
        out[slug] = ", ".join(f"{n} {v}" for v, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return out


_SHA = re.compile(r"[0-9a-f]{40}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def render(results: dict, profile: dict, copy: dict, rundate: str,
           data_revision: str | None = None, data_date: str | None = None) -> str:
    validate_copy(profile, copy)
    if data_revision is not None and not _SHA.fullmatch(data_revision):
        raise RuntimeError(f"data revision {data_revision!r} is not a full 40-hex SHA")
    if data_date is not None and not _DATE.fullmatch(data_date):
        raise RuntimeError(f"data date {data_date!r} is not YYYY-MM-DD")
    by_key = {d["key"]: i + 1 for i, d in enumerate(profile["scoring"]["dimensions"])}
    dims = sorted(profile["scoring"]["dimensions"], key=lambda d: -d["weight"])

    legend = "\n".join(
        f'<li><span class="sw" style="background:var(--d{min(by_key[d["key"]], 3)})"></span>'
        f'<b>{esc(d["label"])}</b> &mdash; {round(d["weight"] * 100)}% of the overall score. '
        f'{esc(copy["dimensions"][d["key"]]["question"])}</li>' for d in dims)

    head = ("<tr><th>Rank</th><th>Person</th><th class=\"num\">Blinded overall</th>"
            + "".join(f'<th class="num">{esc(d["label"])}</th>' for d in dims)
            + '<th class="num">Open overall</th><th class="num">Halo</th>'
              '<th class="num">Recordings</th><th>Confidence</th></tr>')

    mixes = venue_mix(results)
    rows = []
    for p in sorted(results.get("leaders", []), key=lambda x: x.get("rank") or 10 ** 9):
        b = p.get("blinded") or {}
        o = p.get("open") or {}
        hb = p.get("halo") or {}
        halo = hb.get("overall")
        pairs = hb.get("n_pairs")
        pairs_html = (f' <span class="ci">{esc(pairs)} pairs</span>'
                      if isinstance(pairs, int) and not isinstance(pairs, bool) else "")
        rows.append(
            "<tr>"
            f'<td class="num">{esc(p.get("rank", ""))}</td>'
            f'<td class="person"><b>{esc(p.get("name", p.get("slug", "")))}</b>'
            f'<span>{esc(p.get("role", ""))}</span>'
            + (f'<span class="mix">{esc(mixes[p.get("slug")])}</span>' if p.get("slug") in mixes else "")
            + '</td>'
            f'<td class="num">{num(b.get("overall"))}{interval(b)}</td>'
            + "".join(f'<td class="num">{num(b.get(d["key"]))}</td>' for d in dims)
            + f'<td class="num">{num(o.get("overall"))}{interval(o)}</td>'
            f'<td class="num">{num(halo, signed=True)}{interval(hb, signed=True)}{pairs_html}</td>'
            f'<td class="num">{esc(p.get("n_transcripts", ""))}</td>'
            f'<td>{esc(p.get("confidence", ""))}</td>'
            "</tr>")

    unranked = results.get("unranked", [])
    unranked_html = ("" if not unranked else
                     "<h2>Scored but not ranked</h2><ul>" + "".join(
                         f'<li><b>{esc(p.get("name", p.get("slug", "")))}</b> &mdash; '
                         f'{esc(p.get("unranked_reason", "below the rank floor"))}</li>' for p in unranked)
                     + "</ul>")

    explainers = "\n".join(
        f'<h3>{esc(d["label"])} ({round(d["weight"] * 100)}%)</h3>'
        f'<p><i>{esc(copy["dimensions"][d["key"]]["question"])}</i> '
        f'{esc(copy["dimensions"][d["key"]]["explainer"])}</p>' for d in dims)

    grades = (results.get("diagnostics") or {}).get("grades_used")
    # The shared tokens carry design comments written for the leaders page (one
    # names its "Insight" hue). They are stripped here rather than edited in
    # site_theme.py, which would change the leaders and predictions pages' bytes.
    theme = re.sub(r"/\*.*?\*/", "", THEME_CSS, flags=re.S)
    # The description is the tagline plus counts read from the board, so it
    # cannot go stale the way a typed sentence would.
    description = (f'{copy["tagline"]} {copy["status_label"]}: '
                   f'{len(results.get("leaders") or [])} of {roster_size(results)} people ranked.')
    revision_meta = (f'<meta name="verbatim:data-revision" content="{data_revision}">\n'
                     if data_revision else "")
    stamp = ""
    if data_revision:
        stamp = f", data revision {data_revision[:12]}" + (f" of {esc(data_date)}" if data_date else "")
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(copy["title"])}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(copy["site_url"])}">
<link rel="icon" href="data:image/svg+xml,{quote(ICON_SVG.format(initial=esc(copy["title"].split()[-1][0])))}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(copy["title"])}">
<meta property="og:locale" content="en_GB">
<meta property="og:url" content="{esc(copy["site_url"])}">
<meta property="og:title" content="{esc(copy["title"])}">
<meta property="og:description" content="{esc(description)}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(copy["title"])}">
<meta name="twitter:description" content="{esc(description)}">
{revision_meta}{FONT_LINKS}
<style>
{theme}
{CSS}
</style>
</head>
<body>
<main>
<h1>{esc(copy["title"])}</h1>
<p class="tagline">{esc(copy["tagline"])}</p>
<p class="note">{esc(copy["interpretation"])}</p>
{status_banner(results, copy)}
<ul class="dims">
{legend}
</ul>
<div class="wrap"><table id="board">
<thead>{head}</thead>
<tbody>
{"".join(rows)}
</tbody>
</table></div>
{unranked_html}
<h2>What the scores mean</h2>
<p class="note">{esc(copy["blinding_note"])}</p>
{explainers}
<h2>Method</h2>
<p>{esc(copy["method"])}</p>
<footer>Built {esc(rundate)} from {esc(grades if grades is not None else "an unknown number of")} judge grades{stamp}.</footer>
</main>
</body>
</html>
"""


def main_from_args(args) -> int:
    """build_site.py's entry for a non-leaders study; args are build_site.py's parsed arguments."""
    import study_profile as SP
    from atomicio import write_atomic
    SP.guard(args.study, args.results, args.audit, args.roster, args.calibration, args.sources)
    profile = SP.load(args.study)
    try:
        copy = load_copy(profile)
        page = render(json.loads(Path(args.results).read_text()), profile, copy,
                      rundate=datetime.now(timezone.utc).strftime("%d %B %Y"),
                      data_revision=args.data_revision, data_date=args.data_date)
    except RuntimeError as exc:
        raise SystemExit(f"REFUSING: {exc}") from None
    write_atomic(args.out, page)
    print(f"wrote {args.out}  ({len(page) / 1024:.0f} KB, study {args.study})")
    return 0
