#!/usr/bin/env python3
"""Drive a built pundits page in headless Chrome at phone width and check its layout.

FOUND 2026-10-12: at 390 px the board's first three columns ended at x=508 while
the table's visible box ended near x=369, so a phone showed rank and name but
cut the blinded score off until the reader scrolled sideways. No Python test
lays a page out, so this drives a real browser. It is a check_ script, not a
test_ one, because it needs Google Chrome; run it after any change to the page's
CSS or columns, as AGENTS.md asks for the span editor's check_ script.

Headless Chrome will not open a window narrower than 500 px, so the page is laid
out inside a 390 px iframe, which has its own viewport, and reports back with
postMessage. Asserted:

  NO PAGE SCROLL   the document is no wider than the viewport
  SCORE VISIBLE    rank, person and the blinded overall fit inside the table's
                   visible box without scrolling it

  .venv/bin/python scripts/check_pundits_phone_layout.py --page site-pundits/index.html [--width 390]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium")
PROBE = """<script>addEventListener('load',()=>{const d=document.documentElement,w=document.querySelector('.wrap'),
r=w.getBoundingClientRect(),c=[...document.querySelectorAll('#board tbody tr:first-child td')].slice(0,3);
parent.postMessage(JSON.stringify({vw:innerWidth,doc:d.scrollWidth,wrapRight:Math.floor(r.left+w.clientLeft+w.clientWidth),
cells:c.map(x=>Math.ceil(x.getBoundingClientRect().right))}),'*')})</script>"""
HOST = """<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0"><pre id="m">pending</pre>
<iframe src="page.html" style="width:{w}px;height:2400px;border:0"></iframe>
<script>addEventListener('message',e=>{{document.getElementById('m').textContent=e.data}})</script></body></html>"""


def chrome() -> str:
    for c in CHROME:
        if Path(c).exists() or shutil.which(c):
            return c
    raise SystemExit("REFUSING: no Chrome found; this check needs a real browser")


def measure(page: Path, width: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="phone-") as td:
        tmp = Path(td)
        (tmp / "page.html").write_text(page.read_text() + PROBE)
        (tmp / "host.html").write_text(HOST.format(w=width))
        r = subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--window-size=800,2500",
                            "--virtual-time-budget=8000", "--dump-dom", (tmp / "host.html").as_uri()],
                           capture_output=True, text=True, timeout=120)
    m = re.search(r'<pre id="m">([^<]*)</pre>', r.stdout)
    if not m or m.group(1) == "pending":
        raise SystemExit(f"REFUSING: the page never reported its layout (chrome rc={r.returncode})")
    return json.loads(m.group(1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--page", type=Path, required=True)
    ap.add_argument("--width", type=int, default=390)
    args = ap.parse_args()
    got = measure(args.page, args.width)
    print(json.dumps(got))
    fails = []
    if got["doc"] > got["vw"]:
        fails.append(f"the page scrolls sideways: document {got['doc']} px in a {got['vw']} px viewport")
    if len(got["cells"]) < 3:
        fails.append(f"the board's first row has {len(got['cells'])} cells, expected rank, person and score")
    elif got["cells"][2] > got["wrapRight"]:
        fails.append(f"the blinded score ends at x={got['cells'][2]}, past the table's visible edge at "
                     f"x={got['wrapRight']}, so a phone hides it until the reader scrolls")
    for f in fails:
        print(f"FAIL  {f}")
    print("PASS  phone layout" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
