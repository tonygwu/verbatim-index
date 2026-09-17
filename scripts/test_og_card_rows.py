#!/usr/bin/env python3
"""The social card draws the real top of the board, and says when it has moved.

The card used to carry a wordmark and four counts. A count goes stale slowly;
the ranking it now draws goes stale the moment a leader passes another, and
nothing else on the site would notice, because the card is a committed image
rather than something the render pipeline draws.

So the sidecar records the rows that were drawn, and build_site.py compares
them to the board it is about to publish. That warning is what these checks
exercise, plus the row builder itself. Drawing the picture needs Chrome and is
not done here.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_og_card_rows.py
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


card = load("build_og_card")
bs = load("build_site")


def a_leader(rank: int, slug: str, overall: float, name: str | None = None) -> dict:
    return {
        "rank": rank, "slug": slug, "name": name or slug.replace("-", " ").title(),
        "role": "Co-founder and Executive Chairman, Some Labs (former Chief Scientist)",
        "company": "Some Labs", "sector": "AI Labs", "status": "scored",
        "blinded": {"overall": overall, "d1_clarity": 70.0, "d2_insight": 60.0,
                    "d3_technical_depth": 80.0},
    }


RESULTS = {"leaders": [a_leader(1, "first", 75.7), a_leader(2, "second", 72.9),
                       a_leader(3, "third", 71.7), a_leader(4, "fourth", 70.1),
                       {"rank": None, "slug": "unranked", "name": "Un Ranked",
                        "status": "unranked", "blinded": {"overall": 99.0}}]}

print("== the card draws the published order ==")
html, drawn = card.board_rows(RESULTS)
check("it draws exactly BOARD_ROWS rows", len(drawn) == card.BOARD_ROWS, f"{drawn}")
check("in the board's own order",
      [d["slug"] for d in drawn] == ["first", "second", "third"], f"{drawn}")
check("an unranked leader never reaches the card",
      "unranked" not in html and all(d["slug"] != "unranked" for d in drawn))
check("each row carries the name, the organisation and the overall score",
      "First" in html and "Some Labs" in html and "75.7" in html)
check("the three dimensions are drawn with their own bars",
      html.count('class="bar') == 3 * card.BOARD_ROWS
      and "k1" in html and "k2" in html and "k3" in html)
check("a bar is filled to its score",
      'style="width:60%"' in html and 'style="width:80%"' in html)
check("a long role is cut to one clause",
      "Co-founder and Executive Chairman" in html and "former Chief Scientist" not in html)

print("\n== too few scored leaders is a refusal, not a short card ==")
proc = subprocess.run(
    [sys.executable, "-c",
     "import importlib.util,sys,json;"
     f"spec=importlib.util.spec_from_file_location('c', {str(REPO / 'scripts' / 'build_og_card.py')!r});"
     "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
     "m.board_rows({'leaders': [{'rank':1,'slug':'a','name':'A','role':'r','company':'c',"
     "'sector':'s','status':'scored','blinded':{'overall':1.0,'d1_clarity':1.0,"
     "'d2_insight':1.0,'d3_technical_depth':1.0}}]})"],
    capture_output=True, text=True)
check("it refuses rather than drawing a gap", proc.returncode != 0, f"exit {proc.returncode}")
check("the refusal gives both numbers",
      "1 scored leaders" in proc.stderr and str(card.BOARD_ROWS) in proc.stderr,
      proc.stderr[-200:])

print("\n== the page says when the board has moved under the card ==")
with tempfile.TemporaryDirectory() as td:
    png = Path(td) / "og.png"
    png.write_bytes(b"\x89PNG" + b"0" * 6000)
    meta = png.with_suffix(".meta.json")
    bs.OG_CARD, bs.OG_CARD_META = png, meta
    counts = {"leaders": 4, "transcripts": 10, "judges": 3, "top": drawn}
    results = dict(RESULTS)
    results["diagnostics"] = {"transcripts_with_blinded_consensus": 10}
    bs.published_judges = lambda r: ["fable", "astra", "gemini"]

    meta.write_text(json.dumps({"counts": counts}))
    err = io.StringIO()
    with redirect_stderr(err):
        bs.check_og_card(results)
    check("an up-to-date card draws no warning", err.getvalue() == "", err.getvalue())

    # Second and third swap places: every count above is still right.
    moved = json.loads(json.dumps(results))
    moved["leaders"][1]["rank"], moved["leaders"][2]["rank"] = 3, 2
    moved["leaders"][1]["blinded"]["overall"] = 71.7
    moved["leaders"][2]["blinded"]["overall"] = 72.9
    err = io.StringIO()
    with redirect_stderr(err):
        bs.check_og_card(moved)
    out = err.getvalue()
    check("a changed ranking warns", "og.png" in out and "re-run" in out, f"stderr={out!r}")
    check("the warning shows both orders",
          "'slug': 'second'" in out and "'slug': 'third'" in out, f"stderr={out!r}")

    # A card drawn before the rows were recorded must not warn on every render.
    meta.write_text(json.dumps({"counts": {k: v for k, v in counts.items() if k != "top"}}))
    err = io.StringIO()
    with redirect_stderr(err):
        bs.check_og_card(results)
    check("a sidecar with no rows recorded is silent about rows",
          "draws" not in err.getvalue(), err.getvalue())

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
raise SystemExit(1 if FAIL else 0)
