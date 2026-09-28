#!/usr/bin/env python3
"""Drive a rendered predictions page in a real browser. Requires Playwright + Chromium.

Serves an already rendered site directory on 127.0.0.1 and checks what a static
test cannot: the order the table opens in, who is left out and named, the year
square popover (text, colour, contrast, hover, keyboard and tap), the width of
the Organisation column, no horizontal page scroll, and no console errors.

  python scripts/check_predictions_site_ui.py --site site-predictions \
      --absent "Clem Delangue,Tobi Lütke,Sergey Brin" --shots /tmp/pred-shots

Every check prints PASS or FAIL and the run exits 1 on any FAIL. Measurements
(column widths, colours, contrast ratios) are printed whether or not they pass,
so the script can be pointed at an older render to get a before figure.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

PASS, FAIL = [], []
AA = 4.5


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n          {detail}" if detail and not ok else ""))


def rgb(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"[\d.]+", s)]


def lum(c) -> float:
    f = [v / 255 for v in c[:3]]
    f = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in f]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def contrast(a, b) -> float:
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def hue(c) -> float | None:
    r, g, b = (v / 255 for v in c[:3])
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d < 1e-6:
        return None
    h = ((g - b) / d) % 6 if mx == r else (b - r) / d + 2 if mx == g else (r - g) / d + 4
    return (h * 60) % 360


def serve(site: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    handler = functools.partial(Quiet, directory=str(site))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def popover_state(page) -> dict:
    return page.evaluate("""() => {
      const t = document.getElementById('sqtip');
      if (!t) return {shown: false, text: 'no #sqtip on this page'};
      const tx = t.querySelector('.tx'), sw = t.querySelector('.sw');
      if (t.hidden || !tx) return {shown: false};
      const bg = getComputedStyle(t).backgroundColor;
      const scs = getComputedStyle(sw);
      return {shown: true, text: tx.textContent, sub: t.querySelector('.l2').textContent,
              color: getComputedStyle(tx).color, square: tx.dataset.square, adjusted: tx.dataset.adjusted,
              bg, swatch: scs.backgroundColor, swatchOpacity: scs.opacity};
    }""")


def blend(fill, opacity, bg):
    a = opacity * (fill[3] if len(fill) > 3 else 1)
    return [round(f * a + b * (1 - a)) for f, b in zip(fill[:3], bg[:3])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, help="a rendered site directory holding index.html")
    ap.add_argument("--absent", default="", help="comma-separated names that must have no row and be named")
    ap.add_argument("--shots", required=True, help="directory for screenshots")
    args = ap.parse_args()
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    httpd = serve(Path(args.site))
    url = f"http://127.0.0.1:{httpd.server_port}/"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for scheme in ("light", "dark"):
                print(f"\n== desktop 1400px, {scheme} ==")
                ctx = browser.new_context(viewport={"width": 1400, "height": 1000}, color_scheme=scheme)
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url)
                page.wait_for_load_state("networkidle")
                data = page.evaluate("DATA")

                # ---- opening order
                dom = page.eval_on_selector_all("#tb tr.row", "rs => rs.map(r => r.dataset.slug)")
                by = {d["slug"]: d for d in data}
                scores = [by[s]["score"] for s in dom]
                scored = [x for x in scores if x is not None]
                first_none = next((i for i, x in enumerate(scores) if x is None), len(scores))
                unscored_names = [by[s]["name"] for s in dom[first_none:]]
                check("ORDER: the table opens on Score, highest first",
                      bool(scored) and scored == sorted(scored, reverse=True), str(scored[:6]))
                check("ORDER: every unscored row comes after every scored row, in name order",
                      all(x is None for x in scores[first_none:])
                      and unscored_names == sorted(unscored_names, key=str.casefold),
                      str(unscored_names[:6]))
                aria = page.eval_on_selector_all("thead th[aria-sort]", "t => t.map(x => [x.dataset.k, x.getAttribute('aria-sort')])")
                check("ORDER: only the Score header carries aria-sort, descending", aria == [["score", "descending"]], str(aria))

                # ---- omitted people
                names = [by[s]["name"] for s in dom]
                note = page.locator("#omitted").inner_text() if page.locator("#omitted").count() else ""
                print(f"  note: {note}")
                for nm in [x.strip() for x in args.absent.split(",") if x.strip()]:
                    check(f"OMITTED: {nm} has no row and is named under the table",
                          nm not in names and nm in note, f"row={nm in names} note={nm in note}")

                # ---- Predictions column: total and breakdown
                cells = page.eval_on_selector_all("#tb tr.row", """rs => rs.map(r => { const c = r.querySelector('td.pc');
                  return {slug: r.dataset.slug, name: r.querySelector('.nm').textContent,
                          total: c.querySelector('.tot b') ? Number(c.querySelector('.tot b').textContent) : null,
                          lines: [...c.querySelectorAll('li')].map(li => [li.querySelector('span').textContent, Number(li.querySelector('b').textContent), li.title || '']),
                          align: getComputedStyle(c).textAlign, h: r.getBoundingClientRect().height}; })""")
                order = ["Scored", "Not yet due", "No deadline", "Awaiting check", "Not testable", "Couldn't check"]
                bad_sum = [c["name"] for c in cells if c["total"] != by[c["slug"]]["accepted"]
                           or sum(n for _, n, _ in c["lines"]) != c["total"]]
                check("PREDICTIONS: every row's lines add up to its total, and the total is the row's count",
                      not bad_sum, str(bad_sum[:5]))
                check("PREDICTIONS: lines appear in the fixed order and none is zero",
                      all([l for l, _, _ in c["lines"]] == [o for o in order if o in [l for l, _, _ in c["lines"]]]
                          and all(n > 0 for _, n, _ in c["lines"]) for c in cells))
                th_align = page.eval_on_selector('th[data-k="accepted"]', "e => getComputedStyle(e).textAlign")
                check("PREDICTIONS: header and cells are left-aligned",
                      th_align == "left" and all(c["align"] == "left" for c in cells), f"{th_align}")
                for c in cells:
                    if c["name"] in ("Jensen Huang", "Alex Karp"):
                        print(f"  rendered {c['name']}: Total {c['total']}; "
                              + "; ".join(f"{l} {n}" + (f" [{t}]" if t else "") for l, n, t in c["lines"]))
                hs = sorted(c["h"] for c in cells)
                print(f"  measure: row height median {hs[len(hs) // 2]:.0f}px, max {hs[-1]:.0f}px")
                if scheme == "light":
                    page.click('th[data-k="accepted"]')
                    tots = page.eval_on_selector_all("#tb tr.row", "rs => rs.map(r => Number(r.querySelector('td.pc .tot b').textContent))")
                    check("PREDICTIONS: sorting the column sorts by the total", tots == sorted(tots, reverse=True), str(tots[:8]))
                    page.click('th[data-k="name"]')
                    page.locator("#board").scroll_into_view_if_needed()
                    box = page.locator("#tb tr.row").nth(0).bounding_box()
                    end = page.locator("#tb tr.row").nth(5).bounding_box()
                    page.screenshot(path=str(shots / "breakdown-rows.png"),
                                    clip={"x": 0, "y": box["y"] - 70, "width": 1400, "height": end["y"] + end["height"] - box["y"] + 72})
                    page.locator('#tb tr[data-slug="jensen-huang"]').screenshot(path=str(shots / "breakdown-jensen-huang.png"))
                    page.locator('#tb tr[data-slug="alex-karp"]').screenshot(path=str(shots / "breakdown-alex-karp.png"))
                    page.click('th[data-k="score"]')
                    page.click('th[data-k="score"]')         # back to the opening order, Score descending
                    page.evaluate("window.scrollTo(0, 0)")

                # ---- Organisation column and page width
                org = page.eval_on_selector('th[data-k="company"]', "e => e.getBoundingClientRect().width")
                print(f"  measure: Organisation column {org:.1f}px wide at 1400px")
                sw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                check("WIDTH: no horizontal page scroll at 1400px", sw[0] <= sw[1], str(sw))

                # ---- popover: one square of every band, by hover
                page.locator("#board").scroll_into_view_if_needed()
                page.mouse.wheel(0, 250)
                bands = page.evaluate("""() => { const out = {};
                  for (const i of document.querySelectorAll('#tb .sq i[data-y]')) {
                    const b = i.className || 'empty'; if (!out[b]) out[b] = [i.closest('tr').dataset.slug, i.dataset.y, i.dataset.n]; }
                  return out; }""")
                check("POPOVER: squares exist for every band", set(bands) >= {"q1", "q2", "q3", "q4", "empty"}, str(sorted(bands)))
                for b in ("empty", "q1", "q2", "q3", "q4"):
                    if b not in bands:
                        continue
                    slug, y, n = bands[b]
                    cell = page.locator(f'#tb tr[data-slug="{slug}"] .sq i[data-y="{y}"]')
                    cell.scroll_into_view_if_needed()
                    cell.hover()
                    st = popover_state(page)
                    n = int(n)
                    want = f"No predictions in {y}" if n == 0 else f"{n} prediction{'' if n == 1 else 's'} in {y}"
                    check(f"POPOVER {b}: hover shows '{want}'", st.get("shown") and st["text"] == want,
                          json.dumps(st)[:300])
                    if not st.get("shown"):
                        continue
                    bg, col, sq = rgb(st["bg"]), rgb(st["color"]), rgb(st["square"])
                    sw_seen = blend(rgb(st["swatch"]), float(st["swatchOpacity"]), bg)
                    ratio_text, ratio_square = contrast(col, bg), contrast(sq, bg)
                    print(f"  measure {scheme} {b}: square {st['square']} ({ratio_square:.2f}:1), "
                          f"text {st['color']} ({ratio_text:.2f}:1), adjusted={st['adjusted']}")
                    check(f"POPOVER {b}: the swatch is the square's own colour",
                          all(abs(a - c) <= 2 for a, c in zip(sw_seen, sq)), f"{sw_seen} vs {sq}")
                    check(f"POPOVER {b}: text reads at WCAG AA ({ratio_text:.2f}:1)", ratio_text >= AA - 0.01)
                    if st["adjusted"] == "no":
                        check(f"POPOVER {b}: text is exactly the square's colour",
                              all(abs(a - c) <= 1 for a, c in zip(col, sq)), f"{col} vs {sq}")
                    else:
                        hs, ht = hue(sq), hue(col)
                        same = (hs is None and ht is None) or (hs is not None and ht is not None and min(abs(hs - ht), 360 - abs(hs - ht)) <= 6)
                        check(f"POPOVER {b}: too light at {ratio_square:.2f}:1, so the SAME hue at readable contrast",
                              ratio_square < AA and same, f"hue {hs} -> {ht}")
                    if b == "q4":
                        page.screenshot(path=str(shots / f"popover-desktop-{scheme}.png"))
                page.mouse.move(5, 5)
                check("POPOVER: moving the pointer away closes it", not popover_state(page).get("shown"))

                # ---- keyboard
                g = page.locator("#tb tr.row").first.locator(".sq")
                g.focus()
                s1 = popover_state(page)
                page.keyboard.press("ArrowLeft")
                s2 = popover_state(page)
                check("KEYBOARD: focusing a row's squares opens the popover, and ArrowLeft moves one year back",
                      s1.get("shown") and s2.get("shown") and s1["text"][-4:].isdigit()
                      and int(s2["text"][-4:]) == int(s1["text"][-4:]) - 1, f"{s1.get('text')} -> {s2.get('text')}")
                page.keyboard.press("Escape")
                check("KEYBOARD: Escape closes it", not popover_state(page).get("shown"))
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(shots / f"desktop-{scheme}.png"), full_page=False)
                check(f"CONSOLE: no errors on desktop {scheme}", not errors, str(errors[:3]))
                ctx.close()

            print("\n== phone 390px, touch ==")
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True,
                                      device_scale_factor=2)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_load_state("networkidle")
            sw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            check("WIDTH: no horizontal page scroll at 390px", sw[0] <= sw[1], str(sw))
            org = page.eval_on_selector('th[data-k="company"]', "e => e.getBoundingClientRect().width")
            print(f"  measure: Organisation column {org:.1f}px wide at 390px (the table scrolls inside its card)")
            page.screenshot(path=str(shots / "phone.png"), full_page=False)
            cell = page.locator("#tb tr.row").first.locator(".sq i.q4, .sq i.q3, .sq i.q2, .sq i.q1").first
            cell.scroll_into_view_if_needed()
            cell.tap()
            page.wait_for_timeout(200)
            st = popover_state(page)
            opened = page.locator("tr.audit").count()
            check("TAP: a tap on a square opens the popover and does not open the row",
                  st.get("shown") and opened == 0, f"{st.get('text')} drawers={opened}")
            page.screenshot(path=str(shots / "phone-popover.png"), full_page=False)
            page.locator("h1").tap()
            check("TAP: a tap elsewhere closes it", not popover_state(page).get("shown"))
            check("CONSOLE: no errors on phone", not errors, str(errors[:3]))
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed; screenshots in {shots}")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
