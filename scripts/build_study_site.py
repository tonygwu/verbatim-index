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

import hashlib
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
REQUIRED_COPY = ("study_id", "title", "site_url", "rubric_url", "code_url", "tagline", "interpretation",
                 "blinding_note", "dimensions", "method", "status_label", "status_note", "corrections_url")
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
    for key in ("rubric_url", "code_url"):
        if not copy[key].startswith("https://"):
            raise RuntimeError(f"{key} {copy[key]!r} must be an https URL")
    # Release plan decision 6: null is "no corrections path yet", stated, not omitted.
    cu = copy["corrections_url"]
    if cu is not None and not (isinstance(cu, str) and re.match(r"(https://|mailto:)\S+$", cu)):
        raise RuntimeError(f"corrections_url {cu!r} must be null, an https URL or a mailto: address")
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
details{background:var(--surface); border:1px solid var(--rule); border-radius:8px; padding:8px 14px; margin:6px 0}
summary{cursor:pointer}
ul.recs{margin:8px 0 4px; padding-left:18px; color:var(--ink-2); font-size:.9rem}
ul.recs li{margin:4px 0}
ul.recs a{color:var(--ink)}
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


def card_counts(results: dict) -> dict[str, int]:
    """The three counts the social card draws. build_og_card.py draws them and
    og_card_drift() re-reads them, so the card and its check cannot disagree."""
    d = results.get("diagnostics") or {}
    if not isinstance(results.get("transcripts"), list):
        raise RuntimeError("results.json has no transcripts; the card's recordings cannot be counted")
    ranked = {p.get("slug") for p in results.get("leaders") or [] if p.get("status") == "scored"}
    # The board's recordings, as the page's recordings list counts them: blinded rows
    # of ranked people. transcripts_with_blinded_consensus also counts unranked people.
    return {"people": len(ranked),
            "recordings": sum(1 for t in results.get("transcripts") or []
                              if t.get("mode") == "blinded" and t.get("leader_slug") in ranked),
            "judges": len(d["judge_models"])}


def og_card_drift(results: dict, meta: dict, status_label: str | None = None) -> str | None:
    """A warning naming each count the committed card draws differently from the
    board, or None. The card is an image in git, so nothing else would notice.
    With `status_label` (the page's), the card's recorded label must match too:
    the card says "Pilot board", and a relabelled page must not keep that card."""
    try:
        now = card_counts(results)
    except KeyError as exc:
        # A warning, never a block: say exactly what is missing.
        return f"site-pundits/og.png cannot be checked: results.json lacks diagnostics {exc}"
    except RuntimeError as exc:
        return f"site-pundits/og.png cannot be checked: {exc}"
    drawn = (meta or {}).get("counts") or {}
    moved = [f"{k}: card says {drawn.get(k)}, board has {v}" for k, v in now.items() if drawn.get(k) != v]
    if status_label is not None and (meta or {}).get("status_label") != status_label:
        moved.append(f"status label: card says {(meta or {}).get('status_label')!r}, page says {status_label!r}")
    if not moved:
        return None
    return ("site-pundits/og.png is stale (" + "; ".join(moved) + "); re-run "
            "scripts/build_og_card.py --site pundits --results <results.json> and commit the card")


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
    # The correct rate counts a recording only when a judge named the speaker;
    # the leakage rate counts a judge's own confidence. Say only what was measured.
    correct, leak = d.get("blinding_correct_rate"), d.get("blinding_leakage_rate")
    if isinstance(correct, (int, float)):
        bits.append(f"Blinding removes the name from the transcript and does not make the speaker "
                    f"unknown: a judge still named the speaker correctly on {correct * 100:.0f}% of blinded "
                    f"recordings, so read the blinded score as name-removed rather than anonymous.")
    elif isinstance(leak, (int, float)):
        bits.append(f"Blinding removes the name from the transcript and does not make the speaker "
                    f"unknown: a judge was confident it knew the speaker on {leak * 100:.0f}% of blinded "
                    f"recordings, so read the blinded score as name-removed rather than anonymous.")
    if d.get("venue_adjustment_applied") is False:
        reasons = d.get("venue_support_reasons") or []
        why = f" ({esc('; '.join(reasons))})" if reasons else ""
        bits.append("Scores carry no correction for the format of the appearance. It was fitted and "
                    f"then <b>withheld</b>, because the corpus does not yet support it{why}. A "
                    "reaction stream and a sit-down interview are not equally demanding, and that "
                    "difference sits inside these scores.")
    return '<p class="status">' + " ".join(bits) + "</p>"


def search_sentence(results: dict) -> str:
    """The measured web-search count per judge, from results.json, or nothing.

    The blinding note says search is measured and disclosed; this is the
    disclosure, blinded and open apart, because in an open grade the judge
    already has the name. An older results.json without the split states the
    totals. Nothing is printed when the count is absent, so an older results.json
    cannot show an invented zero, and a count that is not an integer refuses."""
    ws = (results.get("diagnostics") or {}).get("judge_web_search")
    if not ws:
        return ""

    def n(e: dict, key: str) -> int:
        # aggregate.py writes ints; anything else is a corrupt file, never page text.
        v = e.get(key)
        if not isinstance(v, int) or isinstance(v, bool):
            raise RuntimeError(f"judge_web_search holds {key}={v!r}, not a count")
        return v

    parts = []
    for i, (j, e) in enumerate(sorted(ws.items())):
        lead = f"{esc(j.capitalize())} {'searched the web in ' if i == 0 else 'in '}"
        modes = e.get("by_mode") or {}
        if "blinded" in modes and "open" in modes:
            b, o = modes["blinded"], modes["open"]
            parts.append(lead + f"{n(b, 'searched')} of {n(b, 'grades')} blinded"
                         + (" grades and " if i == 0 else " and ")
                         + f"{n(o, 'searched')} of {n(o, 'grades')} open" + (" ones" if i == 0 else ""))
        else:
            parts.append(lead + f"{n(e, 'searched')} of {n(e, 'grades')}" + (" grades" if i == 0 else ""))
    return " Measured: " + ", ".join(parts) + "."


def _count(v, what: str) -> int:
    """A count read from results.json, refused unless it is an integer, so it can go into the page as is."""
    if not isinstance(v, int) or isinstance(v, bool):
        raise RuntimeError(f"{what} holds {v!r}, not a count")
    return v


def _signed(v: float) -> str:
    """One decimal with a sign, where a value that rounds to zero prints +0.0, never -0.0."""
    return num(round(v, 1) + 0.0, signed=True)


def _people(n: int, verb: str, verbs: str) -> str:
    return f"{n} person {verb}" if n == 1 else f"{n} people {verbs}"


def sensitivity_section(results: dict) -> str:
    """Plan P5's three sensitivities, stated from results.json, or nothing.

    aggregate.py writes venue_leave_one_out, archival_excluded and
    era_covariate into the diagnostics of a contract-v2 study. Each item here
    reads one of them and prints only what it holds, so an older results.json
    without them gets no section rather than an invented zero. An era fit that
    did not run says so on the page, because P5 promises the covariate.
    """
    d = results.get("diagnostics") or {}
    names = {p.get("slug"): p.get("name") or p.get("slug")
             for p in (results.get("leaders") or []) + (results.get("unranked") or [])}
    items = []
    loo = d.get("venue_leave_one_out")
    if isinstance(loo, dict):
        floor = _count(loo.get("min_transcripts_to_rank"), "venue_leave_one_out.min_transcripts_to_rank")
        for venue, e in (loo.get("by_venue") or {}).items():
            what = f"venue_leave_one_out.by_venue[{venue!r}]"
            if not isinstance(e.get("people_below_floor"), list):
                raise RuntimeError(f"{what} holds no people_below_floor list")
            below = len(e["people_below_floor"])
            line = (f"Without the {_count(e.get('recordings_dropped'), what)} {esc(venue)} recordings, "
                    f"{_people(below, 'falls', 'fall')} below the {floor}-recording floor.")
            kept = _count(e.get("people_still_ranked"), what)
            if kept:
                if not isinstance(e.get("max_abs_shift"), (int, float)):
                    raise RuntimeError(f"{what} ranks {kept} people but holds no max_abs_shift")
                line += (f" Among the {kept} still ranked, {_count(e.get('people_changing_rank'), what)} change "
                         f"rank, and the largest score shift is {num(e['max_abs_shift'])} points.")
            else:
                line += " Nobody stays ranked."
            items.append(line)
        disputed = _count(loo.get("recordings_venue_disputed"), "venue_leave_one_out.recordings_venue_disputed")
        if disputed:
            items.append(f"The {disputed} recording{'s' if disputed != 1 else ''} whose format the judges "
                         f"disputed stay{'s' if disputed == 1 else ''} in every run.")
    arch = d.get("archival_excluded")
    if isinstance(arch, dict) and arch.get("excluded"):
        who = " and ".join(esc(names.get(s, s)) for s in arch["excluded"])
        plural = len(arch["excluded"]) != 1
        if arch.get("computed"):
            items.append(f"Without {who}, the archival subject{'s' if plural else ''} "
                         f"({_count(arch.get('recordings_excluded'), 'archival_excluded')} recordings), with "
                         f"calibration refitted on everyone else: "
                         f"{_count(arch.get('people_changing_rank'), 'archival_excluded')} of the other "
                         f"{_count(arch.get('people_ranked'), 'archival_excluded')} ranked people change rank, and "
                         f"the largest score shift is {num(arch.get('max_abs_shift'))} points.")
        else:
            items.append(f"The check without {who}, the archival subject{'s' if plural else ''}, did not run "
                         f"for this build.")
    era = d.get("era_covariate")
    if isinstance(era, dict):
        if era.get("computed"):
            lo, hi = era["ci95"]
            line = (f"Upload date: within the same person, a recording uploaded one year later scores "
                    f"{_signed(era['slope_per_year'])} points (95% interval {_signed(lo)} to "
                    f"{_signed(hi)}), over {_count(era.get('recordings_used'), 'era_covariate')} recordings uploaded "
                    f"{esc(era['first_upload'])} to {esc(era['last_upload'])}.")
            undated = len(era.get("recordings_without_date") or [])
            if undated:
                line += f" {undated} recording{'s have' if undated != 1 else ' has'} no upload date and {'are' if undated != 1 else 'is'} left out."
            items.append(line)
        else:
            items.append("Upload date: not measured for this build.")
    if not items:
        return ""
    return ('<h2 id="sensitivity">Sensitivity</h2>\n<p>These checks change no published score. Each one shows '
            'how much the board depends on one choice.</p>\n<ul class="sens">'
            + "".join(f"<li>{x}</li>" for x in items) + "</ul>")


def recordings_section(results: dict, recordings: dict) -> str:
    """Every board recording of every ranked person, so the board can be checked.

    `recordings` maps (slug, source_id) to the recording's public metadata, read
    from the open transcripts: url, yt_title, yt_channel, yt_upload_date. Only an
    https URL becomes a link. A recording with no metadata shows its source id
    rather than disappearing, so the count always matches the board.
    """
    rows: dict[str, list[dict]] = {}
    for t in results.get("transcripts") or []:
        if t.get("mode") == "blinded":
            rows.setdefault(t.get("leader_slug"), []).append(t)
    out = ['<h2 id="recordings">Recordings</h2>',
           '<p>Every recording behind a ranked score, with its format and its blinded score after calibration. '
           'Follow a link to hear what the judges read.</p>']
    for p in sorted(results.get("leaders", []), key=lambda x: x.get("rank") or 10 ** 9):
        mine = rows.get(p.get("slug")) or []
        items = []
        for t in mine:
            m = recordings.get((p.get("slug"), t.get("source_id"))) or {}
            title = m.get("yt_title") or m.get("declared_title") or t.get("source_id")
            url = m.get("url") or ""
            head = (f'<a href="{esc(url)}" rel="noopener">{esc(title)}</a>' if url.startswith("https://")
                    else esc(title))
            d = str(m.get("yt_upload_date") or "")
            date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else ""
            bits = [x for x in (esc(m.get("yt_channel") or ""), date, esc(venue_label(t)),
                                num(t.get("cal_overall"))) if x]
            items.append((d or "0", t.get("source_id") or "", f"<li>{head} &middot; " + " &middot; ".join(bits) + "</li>"))
        items.sort(key=lambda x: (x[0], x[1]), reverse=True)
        out.append(f'<details><summary><b>{esc(p.get("name", p.get("slug", "")))}</b> &mdash; '
                   f'{len(items)} recording{"s" if len(items) != 1 else ""}</summary><ul class="recs">'
                   + "".join(x[2] for x in items) + "</ul></details>")
    return "\n".join(out)


def venue_label(t: dict) -> str:
    """A row's format as the page states it. A 1-1 judge tie leaves venue_agreed
    False and an alphabetically chosen label, so the page says "format disputed"
    rather than presenting that label as known."""
    if t.get("venue_type") and t.get("venue_agreed") is False:
        return "format disputed"
    return t.get("venue_type") or ""


def venue_mix(results: dict) -> dict[str, str]:
    """Each person's formats, as "5 conversation, 2 reaction, 1 debate".

    Plan P5 dropped the venue caps and handles format partly by showing this mix.
    It counts each scored recording once, from its blinded row, because the open
    row is the same recording. Largest first; equal counts in name order, so the
    text is the same on every build. A recording with no venue, or one whose
    format the judges disputed, says so rather than being dropped or relabelled.
    """
    seen: dict[str, dict[str, str]] = {}
    for t in results.get("transcripts") or []:
        if t.get("mode") != "blinded":
            continue
        seen.setdefault(t.get("leader_slug"), {})[t.get("source_id")] = venue_label(t) or "format not recorded"
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
           data_revision: str | None = None, data_date: str | None = None, data_uncommitted: bool = False,
           recordings: dict | None = None, og_card: Path | None = None) -> str:
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
    # The card's URL carries a key from its own bytes: Twitter and LinkedIn cache
    # a card by URL for days, so a redrawn card at the same URL would not show.
    if og_card is not None and Path(og_card).is_file():
        img = f'{copy["site_url"]}og.png?v={hashlib.sha256(Path(og_card).read_bytes()).hexdigest()[:12]}'
        card_tags = (f'<meta property="og:image" content="{esc(img)}">\n'
                     '<meta property="og:image:type" content="image/png">\n'
                     '<meta property="og:image:width" content="1200">\n'
                     '<meta property="og:image:height" content="630">\n'
                     f'<meta property="og:image:alt" content="{esc(copy["title"])}">\n'
                     '<meta name="twitter:card" content="summary_large_image">\n'
                     f'<meta name="twitter:image" content="{esc(img)}">')
    else:
        card_tags = '<meta name="twitter:card" content="summary">'
    stamp = ""
    if data_revision:
        stamp = (f", data revision {data_revision[:12]}" + (f" of {esc(data_date)}" if data_date else "")
                 + (" plus uncommitted changes" if data_uncommitted else ""))
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
{card_tags}
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
{"" if recordings is None else recordings_section(results, recordings)}
<h2>What the scores mean</h2>
<p class="note">{esc(copy["blinding_note"])}{search_sentence(results)}</p>
{explainers}
<h2>Method</h2>
<p>{esc(copy["method"])}</p>
<p>Read <a href="{esc(copy["rubric_url"])}">the rubric the judges apply</a>, and the
<a href="{esc(copy["code_url"])}">code and tests</a>.</p>
{"" if copy["corrections_url"] is None else
 f'<p><a href="{esc(copy["corrections_url"])}">Report an error</a> in a score or a recording.</p>'}
{sensitivity_section(results)}
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
    recordings = None
    if getattr(args, "transcripts_meta", None):
        SP.guard(args.study, args.transcripts_meta)
        meta_dir = Path(args.transcripts_meta)
        if not meta_dir.is_dir():
            raise SystemExit(f"REFUSING: --transcripts-meta {meta_dir} is not a directory")
        # Public fields only: the transcript text never reaches the page.
        keep = ("url", "yt_title", "declared_title", "yt_channel", "yt_upload_date")
        recordings = {}
        for f in sorted(meta_dir.glob("*/*.json")):
            rec = json.loads(f.read_text())
            recordings[(f.parent.name, f.stem)] = {k: rec[k] for k in keep if k in rec}
    results = json.loads(Path(args.results).read_text())
    card = REPO / "site-pundits" / "og.png"
    if not card.is_file():
        print(f"WARNING: {card.relative_to(REPO)} is missing; social cards will show no image", file=sys.stderr)
    elif card.with_suffix(".meta.json").is_file():
        drift = og_card_drift(results, json.loads(card.with_suffix(".meta.json").read_text()),
                              status_label=load_copy(profile).get("status_label"))
        if drift:
            print(f"WARNING: {drift}", file=sys.stderr)
    try:
        copy = load_copy(profile)
        page = render(results, profile, copy,
                      rundate=datetime.now(timezone.utc).strftime("%d %B %Y"),
                      data_revision=args.data_revision, data_date=args.data_date,
                      data_uncommitted=bool(getattr(args, "data_uncommitted", False)), recordings=recordings,
                      og_card=card)
    except RuntimeError as exc:
        raise SystemExit(f"REFUSING: {exc}") from None
    write_atomic(args.out, page)
    print(f"wrote {args.out}  ({len(page) / 1024:.0f} KB, study {args.study})")
    return 0
