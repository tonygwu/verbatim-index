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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_theme import FONT_LINKS, THEME_CSS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REQUIRED_COPY = ("study_id", "title", "tagline", "interpretation", "blinding_note", "dimensions", "method")
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
.ci{color:var(--faint); font-size:.85rem}
footer{color:var(--faint); font-size:.85rem; margin-top:40px}
"""


def render(results: dict, profile: dict, copy: dict, rundate: str) -> str:
    validate_copy(profile, copy)
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

    rows = []
    for p in sorted(results.get("leaders", []), key=lambda x: x.get("rank") or 10 ** 9):
        b = p.get("blinded") or {}
        o = p.get("open") or {}
        halo = (p.get("halo") or {}).get("overall")
        rows.append(
            "<tr>"
            f'<td class="num">{esc(p.get("rank", ""))}</td>'
            f'<td class="person"><b>{esc(p.get("name", p.get("slug", "")))}</b>'
            f'<span>{esc(p.get("role", ""))}</span></td>'
            f'<td class="num">{num(b.get("overall"))} '
            f'<span class="ci">[{num(b.get("ci_low"))}, {num(b.get("ci_high"))}]</span></td>'
            + "".join(f'<td class="num">{num(b.get(d["key"]))}</td>' for d in dims)
            + f'<td class="num">{num(o.get("overall"))}</td>'
            f'<td class="num">{num(halo, signed=True)}</td>'
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
    return f"""<title>{esc(copy["title"])}</title>
{FONT_LINKS}
<style>
{theme}
{CSS}
</style>
<main>
<h1>{esc(copy["title"])}</h1>
<p class="tagline">{esc(copy["tagline"])}</p>
<p class="note">{esc(copy["interpretation"])}</p>
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
<footer>Built {esc(rundate)} from {esc(grades if grades is not None else "an unknown number of")} judge grades.</footer>
</main>
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
                      rundate=datetime.now(timezone.utc).strftime("%d %B %Y"))
    except RuntimeError as exc:
        raise SystemExit(f"REFUSING: {exc}") from None
    write_atomic(args.out, page)
    print(f"wrote {args.out}  ({len(page) / 1024:.0f} KB, study {args.study})")
    return 0
