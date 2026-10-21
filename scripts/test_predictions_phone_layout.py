#!/usr/bin/env python3
"""The predictions page must fit a phone screen: board rows, sorting, the THEME
button and the opened person view.

Operator request 2026-10-21, before the page was announced on Twitter. On an
iPhone 12 (390 px wide) the board was a 1100 px table inside a 340 px card that
scrolled sideways with nothing saying so: a reader saw each name and half its
organisation, and never Came true or Score. A person's predictions opened inside
that same 1100 px row, so every line of every card was cut at the screen edge,
and the fixed THEME button sat over the board's header.

What this proves, at 390 px and at 360 px wide, in headless Chrome:
  ROWS      no element or line of text in any board row extends past the
            viewport or out of its own cell, and every row shows its name,
            Came true and Score on screen;
  SORT      the Came true and Score headers are on screen, not covered by
            anything, and a click on each sorts the rows by it, both ways;
  THEME     the THEME button covers no text at the top of the page, with the
            board's header at the top of the screen, or with the person view there;
  PERSON    a person's opened view, every transcript expanded, has no element or
            line of text past the viewport, filters included;
  PAGE      the document never scrolls sideways, before or after the view opens.

The fixture is test_predictions_site.py's, with one person whose name and
organisation each hold a word too long for the screen, a long role, a scored
prediction whose evidence is a 260-character URL with no break in it, and a
prediction whose Control filter option is the longest label the page has, so a
layout that only fits short words fails here.

Headless Chrome will not open a window narrower than 500 px (measured
2026-10-21: --window-size=360,740 gave innerWidth 500), so the page is loaded in
a same-origin iframe of exactly the width under test, where media queries and
innerWidth follow the iframe. Every run checks that width before it checks
anything else. Google Fonts is unreachable on purpose (no network in tests), so
the text is set in the fallback fonts; scripts/check_predictions_site_ui.py and
agent-browser cover the page with its real fonts.

No Chrome is a FAIL, never a skip. No data, no network, no quota.

  .venv/bin/python scripts/test_predictions_phone_layout.py
  .venv/bin/python scripts/test_predictions_phone_layout.py --site site-predictions --person michael-dell
"""

from __future__ import annotations

import argparse
import functools
import http.server
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []
# The two phone widths the operator named; heights are an iPhone 12 and a
# common 360 px Android screen.
WIDTHS = ((390, 844), (360, 740))
# No hyphen or space anywhere: Chrome breaks a line after a hyphen, so a URL
# with one would wrap on any layout and prove nothing.
LONG_URL = "https://example.com/" + "evidencewithnobreakopportunity" * 8


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n          {detail}" if detail and not ok else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_phonetest", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Runs inside the page, after the page's own script. It writes one JSON result
# into the TOP document, which is what --dump-dom prints.
PROBE = r"""
<script>
(async () => {
  const res = {innerWidth: innerWidth, clientWidth: document.documentElement.clientWidth, errors: []};
  const finish = () => {
    const doc = window.top.document, s = doc.createElement("script");
    s.type = "application/json"; s.id = "phone-fit";
    s.textContent = JSON.stringify(res).replace(/</g, "\\u003c");
    doc.body.appendChild(s);
  };
  try {
    const W = innerWidth;
    const pause = ms => new Promise(r => setTimeout(r, ms));
    // Not requestAnimationFrame: under --virtual-time-budget no frame is drawn, so
    // it never fires. Reading a box forces layout, so a timer is enough.
    const frame = () => pause(30);
    const label = el => {
      let s = el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.trim().replace(/\s+/g, ".") : "");
      const row = el.closest("tr");
      if (row && row.dataset.slug) s += ` in row ${row.dataset.slug}`;
      if (el.closest("tr.audit")) s += " in the person view";
      return s;
    };
    // Every element box and every line of text under root that reaches past
    // either edge of the viewport. A box clipped by a scrolling ancestor still
    // counts: cut off is what a reader sees.
    const past = root => {
      const out = [];
      for (const el of [root, ...root.querySelectorAll("*")]){
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && (r.left < -0.5 || r.right > W + 0.5))
          out.push(`${label(el)} spans x ${Math.round(r.left)} to ${Math.round(r.right)}`);
      }
      const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let t; (t = tw.nextNode());){
        if (!t.textContent.trim()) continue;
        const rg = document.createRange(); rg.selectNodeContents(t);
        for (const r of rg.getClientRects()){
          if (r.width > 0 && (r.left < -0.5 || r.right > W + 0.5)){
            out.push(`text "${t.textContent.trim().slice(0, 40)}" of ${label(t.parentElement)} spans x ${Math.round(r.left)} to ${Math.round(r.right)}`);
            break;
          }
        }
      }
      return out;
    };
    const onScreen = el => { const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.left >= -0.5 && r.right <= W + 0.5; };
    // Vertical scrolling only. scrollIntoView would also scroll the board's card
    // sideways and bring a cut-off column into view, which no reader gets without
    // swiping; so every sideways scroll is put back to zero too.
    const toY = (el, centre) => {
      for (const x of document.querySelectorAll("*")) if (x.scrollLeft) x.scrollLeft = 0;
      const r = el.getBoundingClientRect();
      window.scrollTo(0, scrollY + r.top - (centre ? (innerHeight - r.height) / 2 : 0));
    };
    const hit = el => { // the element itself is what a tap at its centre reaches
      toY(el, true);
      const r = el.getBoundingClientRect(), at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!at && el.contains(at);
    };
    const overlaps = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
    const btn = document.getElementById("themeBtn");
    const covered = () => {               // text the THEME button lies over, at the current scroll
      const b = btn.getBoundingClientRect(), out = [];
      const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let t; (t = tw.nextNode());){
        if (!t.textContent.trim() || btn.contains(t)) continue;
        const rg = document.createRange(); rg.selectNodeContents(t);
        if ([...rg.getClientRects()].some(r => r.width > 0 && overlaps(r, b))) out.push(`"${t.textContent.trim().slice(0, 40)}" (${label(t.parentElement)})`);
      }
      return out;
    };
    await document.fonts.ready;
    await frame();
    toY(document.body);
    res.scrollWidth = document.documentElement.scrollWidth;

    const rows = [...document.querySelectorAll("#tb tr.row")];
    res.rows = rows.length;
    res.rowsPast = rows.flatMap(past);
    // Text that leaves its own cell runs into the next one: a long name over
    // Came true is unreadable even when it stays on screen.
    res.rowsSpill = rows.flatMap(tr => [...tr.children].flatMap(td => {
      const c = td.getBoundingClientRect(), out = [];
      if (!c.width) return out;
      const tw = document.createTreeWalker(td, NodeFilter.SHOW_TEXT);
      for (let t; (t = tw.nextNode());){
        if (!t.textContent.trim()) continue;
        const rg = document.createRange(); rg.selectNodeContents(t);
        if ([...rg.getClientRects()].some(r => r.width > 0 && (r.left < c.left - 0.5 || r.right > c.right + 0.5)))
          out.push(`text "${t.textContent.trim().slice(0, 40)}" leaves ${label(td)}`);
      }
      return out;
    }));
    res.rowsHidden = rows.flatMap(tr => {
      const nm = tr.querySelector(".who .nm"), cells = tr.children;
      return [["name", nm], ["Came true", cells[4]], ["Score", cells[5]]]
        .filter(([, el]) => !el || !onScreen(el)).map(([what]) => `${tr.dataset.slug}: ${what} is not on screen`);
    });

    window.scrollTo(0, 0); await frame();
    res.themeTop = covered();
    toY(document.querySelector("#board thead")); await frame();
    res.themeBoard = covered();

    res.sort = {};
    for (const k of ["score", "hit_rate"]){
      const th = document.querySelector(`#board thead th[data-k="${k}"]`);
      const s = res.sort[k] = {present: !!th};
      if (!th) continue;
      s.onScreen = onScreen(th);
      s.reachable = hit(th);
      s.runs = [];
      for (let i = 0; i < 2; i++){
        th.click(); await frame();
        const dir = th.getAttribute("aria-sort");
        const vals = [...document.querySelectorAll("#tb tr.row")].map(tr => (DATA.find(d => d.slug === tr.dataset.slug) || {})[k]);
        const known = vals.filter(v => v != null);
        const firstNull = vals.findIndex(v => v == null);
        const sorted = known.every((v, j) => j === 0 || (dir === "ascending" ? known[j - 1] <= v : known[j - 1] >= v));
        s.runs.push({dir, vals, sorted, nullsLast: firstNull === -1 || vals.slice(firstNull).every(v => v == null)});
      }
    }

    const slug = new URLSearchParams(location.search).get("open");
    const tr = document.querySelector(`#tb tr.row[data-slug="${CSS.escape(slug)}"]`);
    res.person = {slug, found: !!tr};
    if (tr){
      tr.click();
      let audit = null;
      for (let i = 0; i < 300 && !(audit && audit.querySelector(".drawer h3") && audit.querySelector(".pred")); i++){
        await pause(50);
        audit = tr.nextElementSibling && tr.nextElementSibling.matches("tr.audit") ? tr.nextElementSibling : null;
      }
      res.person.opened = !!(audit && audit.querySelector(".pred"));
      if (res.person.opened){
        audit.querySelectorAll("details").forEach(d => { d.open = true; });
        await frame();
        res.person.preds = audit.querySelectorAll(".pred").length;
        res.person.selects = audit.querySelectorAll("select").length;
        res.person.options = [...audit.querySelectorAll("option")].map(o => o.textContent);
        res.person.textChars = audit.innerText.length;
        res.person.longUrlShown = audit.innerText.replace(/\s+/g, "").includes(__LONG_URL__);
        toY(audit);
        res.person.past = past(audit);
        res.person.scrollWidth = document.documentElement.scrollWidth;
        toY(tr); await frame();
        res.themePerson = covered();
      }
    }
  } catch (e) {
    res.errors.push(String(e && e.stack || e));
  }
  finish();
})();
</script>
"""

WRAPPER = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>html,body{margin:0}iframe{border:0;display:block}</style></head>
<body><iframe src="__SRC__" style="width:__W__px;height:__H__px"></iframe></body></html>
"""


def serve(site: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def measure(chrome: str, site: Path, slug: str, width: int, height: int, long_url: str | None) -> dict:
    """Load the page at width x height in a same-origin iframe and return the
    probe's result. The probed copy and the wrapper are written beside the page,
    so the page's relative fetches of predictions/<slug>.json still resolve."""
    page = (site / "index.html").read_text()
    if "</body>" not in page:
        raise SystemExit(f"REFUSING: {site / 'index.html'} has no </body> to put the probe before")
    probe = PROBE.replace("__LONG_URL__", json.dumps(long_url))
    (site / "_phone_probe.html").write_text(page.replace("</body>", probe + "</body>", 1))
    (site / "_phone_wrap.html").write_text(WRAPPER.replace("__SRC__", f"_phone_probe.html?open={slug}")
                                           .replace("__W__", str(width)).replace("__H__", str(height)))
    srv = serve(site)
    try:
        with tempfile.TemporaryDirectory() as profile:
            dom = subprocess.run(
                [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                 "--window-size=600,900", f"--user-data-dir={profile}", "--virtual-time-budget=60000",
                 # No network: everything but the local server fails to resolve.
                 "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
                 "--dump-dom", f"http://127.0.0.1:{srv.server_address[1]}/_phone_wrap.html"],
                check=True, capture_output=True, text=True, timeout=180).stdout
    finally:
        srv.shutdown()
        for f in ("_phone_probe.html", "_phone_wrap.html"):
            (site / f).unlink(missing_ok=True)
    m = re.search(r'<script type="application/json" id="phone-fit">(.*?)</script>', dom, re.S)
    if not m:
        raise SystemExit("REFUSING: the probe wrote no result, so the layout was not measured")
    return json.loads(m.group(1))


def judge(res: dict, width: int, slug: str, long_url: str | None) -> None:
    at = f"{width}px"
    check(f"{at}: the page under test is exactly {width} px wide",
          res.get("innerWidth") == width and res.get("clientWidth") == width,
          f"innerWidth {res.get('innerWidth')}, clientWidth {res.get('clientWidth')}")
    check(f"{at}: the probe ran without an error", not res["errors"], "; ".join(res["errors"])[:800])
    if res["errors"]:
        return
    check(f"{at} PAGE: the document does not scroll sideways",
          res["scrollWidth"] <= width, f"scrollWidth {res['scrollWidth']}")
    check(f"{at} ROWS: the board has rows to measure", res["rows"] >= 2, f"{res['rows']} rows")
    check(f"{at} ROWS: nothing in a board row extends past the viewport", not res["rowsPast"],
          f"{len(res['rowsPast'])} boxes or lines, e.g. " + "; ".join(res["rowsPast"][:6]))
    check(f"{at} ROWS: no text in a board row runs out of its own cell", not res["rowsSpill"],
          f"{len(res['rowsSpill'])} lines, e.g. " + "; ".join(res["rowsSpill"][:6]))
    check(f"{at} ROWS: every row shows its name, Came true and Score on screen", not res["rowsHidden"],
          "; ".join(res["rowsHidden"][:6]))
    for k, lab in (("score", "Score"), ("hit_rate", "Came true")):
        s = res["sort"][k]
        check(f"{at} SORT: the {lab} header is on screen and nothing covers it",
              s["present"] and s.get("onScreen") and s.get("reachable"), json.dumps(s)[:400])
        if s["present"]:
            runs = s["runs"]
            check(f"{at} SORT: clicking {lab} sorts the rows by it, both directions",
                  {r["dir"] for r in runs} == {"ascending", "descending"}
                  and all(r["sorted"] and r["nullsLast"] for r in runs), json.dumps(runs)[:600])
    check(f"{at} THEME: the button covers no text at the top of the page", not res["themeTop"],
          "; ".join(res["themeTop"][:6]))
    check(f"{at} THEME: the button covers no text with the board header at the top of the screen",
          not res["themeBoard"], "; ".join(res["themeBoard"][:6]))
    p = res["person"]
    check(f"{at} PERSON: {slug}'s view opens with predictions in it", p["found"] and p.get("opened"), json.dumps(p)[:300])
    if not p.get("opened"):
        return
    if long_url:
        check(f"{at} PERSON: the fixture's unbroken URL is on the page to be measured", p["longUrlShown"])
        check(f"{at} PERSON: the longest filter option is on the page to be measured",
              "Partly under the speaker's control" in p["options"], str(p["options"]))
    check(f"{at} PERSON: nothing in the opened view extends past the viewport", not p["past"],
          f"{len(p['past'])} boxes or lines, e.g. " + "; ".join(p["past"][:6]))
    check(f"{at} PERSON: the document does not scroll sideways with the view open",
          p["scrollWidth"] <= width, f"scrollWidth {p['scrollWidth']}")
    check(f"{at} THEME: the button covers no text with the person view at the top of the screen",
          not res["themePerson"], "; ".join(res["themePerson"][:6]))


def fixture_site(td: Path) -> tuple[Path, str]:
    """Render test_predictions_site.py's fixture with a scored person whose name,
    role, organisation and evidence are long, through the page's own main()."""
    T, L, A = load("test_predictions_site"), load("predictions_lib"), load("aggregate_predictions")
    B = load("build_predictions_site")
    pr, roster, index = T.build(td, L, A)
    long = {"name": "Alexandria Konstantinopouloupapadopoulos", "company": "TaiwanSemiconductorManufacturingCompanyLimited",
            "role": "Executive Vice President and Chief Executive Officer, Artificial Intelligence and Research",
            "sector": "Hardware & Mobility"}
    idx = json.loads(index.read_text())
    for l in idx["leaders"]:
        if l["slug"] == "ada":
            l.update(long)
    index.write_text(json.dumps(idx, indent=1, sort_keys=True))
    rost = json.loads(roster.read_text())
    for r in rost["roster"]:
        if r["slug"] == "ada":
            r.update(long)
    roster.write_text(json.dumps(rost))
    # The longest filter option the page has, "Partly under the speaker's control".
    s1 = pr / "ada" / "s1.jsonl"
    lines = L.parse_lines(s1.read_text(), str(s1))
    lines[2]["prediction"]["subject_control"] = "partial"
    s1.write_text(L.serialise_lines(lines))
    recs = {s: [r for r in B.load_records(pr)["accepted"] if r["leader_slug"] == s] for s in ("ada", "alan")}
    pid = recs["ada"][0]["prediction_id"]
    run1 = td / "run1"
    (run1 / "priors" / "ada").mkdir(parents=True)
    (run1 / "priors" / "ada" / f"{pid}.json").write_text(json.dumps(
        {"prediction_id": pid, "leader_slug": "ada", "stage": "prior", "p": 0.25,
         "telemetry": {"canonical_model": "claude-fable-5-1", "requested_model": "claude-fable-5-1",
                       "telemetry_models": ["claude-fable-5-1"]}}))
    (run1 / "resolutions" / "ada").mkdir(parents=True)
    (run1 / "resolutions" / "ada" / f"{pid}.json").write_text(json.dumps(
        {"prediction_id": pid, "leader_slug": "ada", "stage": "resolve", "outcome": "occurred",
         "harness": "astra", "telemetry": {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}}))
    scores = td / "scores.json"
    scores.write_text(json.dumps({
        "as_of": "2026-09-14", "run_dirs": [str(run1)],
        "settings": {"as_of": "2026-09-14", "trend": True, "min_lead_days": 60},
        "rule": {"clamp": 0.01, "min_scored_to_rank": 5, "min_lead_days": 60,
                 "baseline_only": "points = -log2(p) if it happened, else (p/(1-p))*log2(p)"},
        "corpus": {"past_due": 9, "eligible": 9, "scored": 8, "leaders_ranked": 2,
                   "by_outcome": {"occurred": 5, "not_occurred": 3, "unresolvable": 0},
                   "unresolvable_reasons": {}},
        "leaders": [
            {"slug": "ada", "name": long["name"], "n_scored": 6, "mean_points": 0.125, "ranked": True,
             "past_due": 7, "eligible": 7, "unresolvable": 0, "scored_occurred": 4, "hit_rate": 0.6667},
            {"slug": "alan", "name": "Alan T", "n_scored": 2, "mean_points": -0.5, "ranked": True,
             "past_due": 2, "eligible": 2, "unresolvable": 0, "scored_occurred": 1, "hit_rate": 0.5},
            {"slug": "cleo", "name": "Cleo F", "n_scored": 0, "mean_points": None, "ranked": False,
             "past_due": 0, "eligible": 0, "unresolvable": 0, "scored_occurred": 0, "hit_rate": None}],
        "predictions": [
            {"prediction_id": pid, "leader_slug": "ada", "outcome": "occurred", "scored": True,
             "unresolvable_reason": None,
             "resolution_reasoning": "It shipped, as the filing at " + LONG_URL + " records in its second table.",
             "sources": [{"where": LONG_URL, "what_it_shows": "the launch, announced in a press release",
                          "date": "2026-01-02"}],
             "p": 0.25, "reference_class": "launches announced a year ahead", "points": 2.0,
             "deadline": "2026-06-30", "flags": T.fl(True, 486), "not_scored_because": None}]}))
    site = td / "site"
    argv = ["--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr), "--roster", str(roster),
            "--membership", str(T.mem(roster)), "--scores", str(scores), "--out", str(site / "index.html")]
    err, out = io.StringIO(), io.StringIO()
    with redirect_stderr(err), redirect_stdout(out):
        B.main(argv)
    return site, "ada"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", help="a rendered site directory to measure instead of the fixture; it is copied first")
    ap.add_argument("--person", help="the slug whose view is opened (required with --site)")
    args = ap.parse_args()
    card = load("build_og_card")
    try:
        chrome = card.find_chrome()
    except SystemExit as exc:
        check("Chrome or Chromium is installed to measure the layout", False, str(exc))
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
        return 1
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if args.site:
            if not args.person:
                raise SystemExit("REFUSING: --site needs --person, the row whose view is opened")
            site, slug, long_url = td / "site", args.person, None
            shutil.copytree(args.site, site)
            print(f"measuring {args.site} (copied), opening {slug}")
        else:
            site, slug = fixture_site(td)
            long_url = LONG_URL
        for w, h in WIDTHS:
            print(f"\n== {w} x {h} ==")
            try:
                judge(measure(chrome, site, slug, w, h, long_url), w, slug, long_url)
            except BaseException as exc:  # noqa: BLE001 - a REFUSING or a Chrome failure is a FAIL
                check(f"{w}px: the layout was measured", False, f"{type(exc).__name__}: {exc}"[:800])
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
