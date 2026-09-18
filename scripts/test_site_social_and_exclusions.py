#!/usr/bin/env python3
"""The page is a real HTML document, unfurls as a link, and cannot contradict itself.

Three defects found on 2026-09-16, all on the published board:

1. The document had no DOCTYPE, no <html>, no <head> and no meta tags at all.
   Browsers therefore rendered it in quirks mode (verified: document.compatMode
   was "BackCompat" on the live site), a phone fell back to a ~980px layout
   viewport because no viewport meta told it otherwise, and Twitter and LinkedIn
   had no title, description or image to unfurl.

2. The exclusion section listed Amjad Masad, who was ranked 29th on the same
   page. The roster seated him on 2026-09-10 and nothing recomputed the derived
   dropped_for_no_transcripts list.

3. "Words graded" summed <own data link>/transcripts: everything FETCHED,
   including transcripts QA withdrew, read from the DEPLOYING clone rather than
   from the production source being published. It showed 9.5M over 720 files
   beside a "Transcripts 653" stat counting graded ones.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_site_social_and_exclusions.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ri = load("test_render_integrity")  # a_grade(), run_aggregate()

LEADERS = ("alpha", "beta", "gamma")
WORDS_PER_GRADED = 1000
WORDS_PER_UNGRADED = 9000  # loud: if the ungraded pile is counted, the number triples


def build_inputs(root: Path, drop_names: list[str]) -> dict[str, Path]:
    """One production-shaped data directory, rendered from exactly as deploy.sh does."""
    grades = root / "grades"
    for li, leader in enumerate(LEADERS):
        for t in range(6):
            for judge in ("fable", "astra"):
                rec = ri.a_grade(leader, f"src{t}", judge, 60 + t, 50 + li * 5 + t)
                d = grades / judge / leader
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(json.dumps(rec))

    roster = {
        "roster": [{"rank": i + 1, "slug": s, "name": s.title(), "role": "CEO",
                    "company": f"C{i}", "sector": "AI"}
                   for i, s in enumerate(LEADERS)],
        "dropped_for_no_transcripts": [{"name": n, "reason": "no retrievable long-form speech"}
                                       for n in drop_names],
    }
    (root / "roster.json").write_text(json.dumps(roster))

    # The graded corpus, which is what "words graded" must count.
    blind = root / "transcripts_blind"
    for leader in LEADERS:
        d = blind / leader
        d.mkdir(parents=True, exist_ok=True)
        for t in range(6):
            # leader_slug is REQUIRED: build_site decides membership from the
            # record, never the path component, so a fixture without it reads
            # as off-board and the words-graded total comes out zero.
            (d / f"src{t}.json").write_text(json.dumps(
                {"leader_slug": leader, "word_count": WORDS_PER_GRADED}))

    # Everything fetched, including material QA withdrew. Must NOT be counted.
    everything = root / "transcripts"
    for leader in LEADERS:
        d = everything / leader
        d.mkdir(parents=True, exist_ok=True)
        for t in range(6):
            (d / f"src{t}.json").write_text(json.dumps(
                {"leader_slug": leader, "word_count": WORDS_PER_UNGRADED}))

    (root / "calibration.json").write_text(json.dumps({"headline": {}}))
    (root / "sources.json").write_text(json.dumps({}))
    results = root / "results.json"
    proc = ri.run_aggregate(REPO / "scripts" / "aggregate.py", grades, root / "roster.json", results)
    if proc.returncode != 0 or not results.exists():
        sys.exit(f"REFUSING: fixture aggregate failed: {proc.stderr[-600:]}")
    return {"results": results, "audit": results.with_name("results_audit.json"),
            "roster": root / "roster.json", "calibration": root / "calibration.json",
            "sources": root / "sources.json"}


def render(paths: dict[str, Path], out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(REPO / "scripts" / "build_site.py"),
         "--results", str(paths["results"]), "--audit", str(paths["audit"]),
         "--roster", str(paths["roster"]), "--calibration", str(paths["calibration"]),
         # build_site reads membership and raises on a slug it has not been
         # told about, so this synthetic roster needs its own file. Derived
         # from the roster by the same seam aggregate uses, never typed.
         "--sources", str(paths["sources"]), "--out", str(out),
         "--membership", str(ri.membership_for(paths["roster"]))],
        capture_output=True, text=True, cwd=REPO)


print("== a self-contradicting roster stops the render ==")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    paths = build_inputs(root, drop_names=["Alpha", "Nobody Seated"])
    out = root / "site.html"
    r = render(paths, out)
    check("render refuses when a seated leader is on the exclusion list", r.returncode != 0,
          f"exit {r.returncode}; stderr={r.stderr[-300:]}")
    check("the refusal names the person", "Alpha" in (r.stderr + r.stdout),
          f"stderr={r.stderr[-300:]}")
    check("nothing is published on refusal", not out.exists())

print("\n== a clean roster renders, and the page is a real document ==")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    paths = build_inputs(root, drop_names=["Nobody Seated", "Also Not Seated"])
    out = root / "site.html"
    r = render(paths, out)
    check("render succeeds", r.returncode == 0, f"stderr={r.stderr[-400:]}")
    h = out.read_text() if out.exists() else ""

    check("starts with a DOCTYPE, so browsers use standards mode",
          h.lstrip().lower().startswith("<!doctype html>"), repr(h[:60]))
    for frag, why in [
        ('<html lang="en">', "declares its language"),
        ('<meta charset="utf-8">', "declares its encoding"),
        ('name="viewport"', "tells a phone to use device width"),
        ("</head>", "closes the head"),
        ("<body>", "opens a body"),
        ("</html>", "closes the document"),
    ]:
        check(f"page {why}", frag in h, f"missing {frag!r}")

    print("\n== the link unfurls on Twitter and LinkedIn ==")
    for prop in ("og:type", "og:url", "og:title", "og:description",
                 "og:image", "og:image:width", "og:image:height"):
        check(f"has {prop}", f'property="{prop}"' in h)
    check("twitter card is the large-image kind",
          'name="twitter:card" content="summary_large_image"' in h)
    for nm in ("twitter:title", "twitter:description", "twitter:image"):
        check(f"has {nm}", f'name="{nm}"' in h)
    check("has a canonical url", 'rel="canonical"' in h)
    check("has a meta description", 'name="description"' in h)

    # A crawler has no page context, so every card URL must be absolute.
    card_urls = re.findall(r'(?:property|name)="(?:og:image|twitter:image|og:url)" content="([^"]+)"', h)
    check("card urls are absolute", bool(card_urls) and all(u.startswith("https://") for u in card_urls),
          f"{card_urls}")
    check("card image carries a cache-busting version",
          any("og.png?v=" in u for u in card_urls), f"{card_urls}")

    # Social text must be rendered from the corpus, never left as a placeholder.
    check("no unrendered placeholder survives in the head",
          not re.search(r"__[A-Z_]+__", h[:h.find("</head>")]),
          re.findall(r"__[A-Z_]+__", h[:h.find("</head>")])[:5])

    print("\n== words graded counts the graded corpus, from the source being published ==")
    m = re.search(r"<dt>Words graded</dt><dd>([^<]*)", h)
    shown = m.group(1).strip() if m else ""
    graded_total = len(LEADERS) * 6 * WORDS_PER_GRADED           # 18,000
    fetched_total = len(LEADERS) * 6 * WORDS_PER_UNGRADED        # 162,000
    check("a words-graded figure is shown", bool(shown), f"got {shown!r}")
    check("it reports the graded corpus", shown == f"{graded_total/1000:.0f}k",
          f"expected {graded_total/1000:.0f}k, page says {shown!r}")
    check("it is not the everything-fetched pile", shown != f"{fetched_total/1000:.0f}k",
          f"page says {shown!r}, which is the ungraded total")

    # AN OFF-BOARD PERSON'S TRANSCRIPTS ADD NO WORDS. This is the P3/P4 path:
    # the seven investors are fetched, their transcripts may land on the leaders
    # shelf, and grade.py's membership gate stops them being graded. But the
    # words-graded total reads the shelf DIRECTLY, not the grades, so without a
    # membership filter there it would count words nobody was scored on. Wired in
    # build_site.py and untested end to end until now.
    off = paths["results"].parent / "transcripts_blind" / "off-board-person"
    off.mkdir(parents=True, exist_ok=True)
    for t in range(4):
        (off / f"src{t}.json").write_text(json.dumps(
            {"leader_slug": "off-board-person", "word_count": 50_000}))
    mem = json.loads(Path(ri.membership_for(paths["roster"])).read_text())
    mem["off-board-person"] = ["predictions"]
    (paths["roster"].parent / "membership.json").write_text(json.dumps(mem))
    out2 = paths["results"].parent / "with-off-board.html"
    r2 = subprocess.run(
        [PY, str(REPO / "scripts" / "build_site.py"),
         "--results", str(paths["results"]), "--audit", str(paths["audit"]),
         "--roster", str(paths["roster"]), "--calibration", str(paths["calibration"]),
         "--sources", str(paths["sources"]), "--out", str(out2),
         "--membership", str(paths["roster"].parent / "membership.json")],
        capture_output=True, text=True)
    check("the render still succeeds with an off-board corpus present",
          r2.returncode == 0, r2.stderr[-300:])
    if r2.returncode == 0:
        h2 = out2.read_text()
        m2 = re.search(r"<dt>Words graded</dt><dd>([^<]*)", h2)
        shown2 = m2.group(1).strip() if m2 else ""
        check("200,000 off-board words change the total by nothing",
              shown2 == shown,
              f"was {shown!r}, now {shown2!r}; the membership filter in the word "
              f"count is what stops the seven inflating the published figure")

print("\n== a missing graded corpus fails loud rather than reporting zero ==")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    paths = build_inputs(root, drop_names=[])
    import shutil
    shutil.rmtree(root / "transcripts_blind")
    out = root / "site.html"
    r = render(paths, out)
    check("render refuses when the graded corpus is absent", r.returncode != 0,
          f"exit {r.returncode}")
    check("the refusal says what is missing", "transcripts_blind" in (r.stderr + r.stdout),
          f"stderr={r.stderr[-300:]}")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
raise SystemExit(1 if FAIL else 0)
