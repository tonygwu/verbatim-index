#!/usr/bin/env python3
"""The pundits page is rendered from its profile, and the leaders page is left alone.

Pundits plan, P4b. build_site.py keeps its hand-written leaders template.
Any other study is handed to build_study_site.py, which takes every dimension,
label and weight from the study profile and all prose from the profile's
site-copy file. Percentages are computed from the weights, never typed, so the
page cannot disagree with the score.

  DIMENSIONS   each dimension's label, question and computed weight appear, in
               weight order; no leaders wording appears
  NOTES        the interpretation note and the blinding note appear
  ESCAPING     a person's name containing markup is escaped, not executed
  SCORES       blinded score with its interval, open score and halo render; a
               missing value shows a dash, never a zero
  UNRANKED     a person below the rank floor is kept off the ranked table
  COPY         copy lacking a dimension explainer, or typing a percentage, is refused
  DISPATCH     build_site.py --study pundits writes the pundits page

No quota, no live data.

  .venv/bin/python scripts/test_study_site.py
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def profile() -> dict:
    return json.loads((REPO / "profiles" / "pundits.json").read_text())


def copy() -> dict:
    return json.loads((REPO / "profiles" / "pundits.site.json").read_text())


def results() -> dict:
    dims = [d["key"] for d in profile()["scoring"]["dimensions"]]

    def block(base: float, low: float, high: float) -> dict:
        return {"overall": base, "ci_low": low, "ci_high": high, **{d: base + i for i, d in enumerate(dims)}}

    ranked = [
        {"rank": 1, "slug": "ada", "name": "Ada <script>alert(1)</script> Lovelace", "role": "host",
         "status": "scored", "n_transcripts": 8, "confidence": "high",
         "blinded": block(61.2, 55.0, 67.4), "open": block(64.0, 58.1, 70.2),
         "halo": {"overall": 2.8, "ci_low": 0.4, "ci_high": 5.1, "n_pairs": 16}},
        {"rank": 2, "slug": "bo", "name": "Bo Diddley", "role": "columnist", "status": "scored",
         "n_transcripts": 6, "confidence": "medium", "blinded": block(48.5, 41.0, 55.9), "open": {}, "halo": {}},
    ]
    unranked = [{"slug": "cy", "name": "Cy Unranked", "role": "streamer", "status": "scored", "n_transcripts": 2,
                 "confidence": "low", "blinded": block(70.0, 50.0, 90.0), "open": {}, "halo": {},
                 "unranked_reason": "2 included transcripts, below the floor of 5"}]
    # Ada's recordings in both modes. The venue mix counts recordings, so the
    # open rows must not double it: 5 conversation, 2 reaction, 1 debate.
    venues = ["conversation"] * 5 + ["reaction"] * 2 + ["debate"]
    transcripts = [{"leader_slug": "ada", "source_id": f"ada-{i}", "mode": mode, "venue_type": v}
                   for i, v in enumerate(venues) for mode in ("blinded", "open")]
    return {"leaders": ranked, "unranked": unranked, "transcripts": transcripts,
            "diagnostics": {"weights": {d["key"]: d["weight"] for d in profile()["scoring"]["dimensions"]},
                            "grades_used": 90}}


def main() -> int:
    print("profile-driven study site")
    try:
        import build_study_site as B
    except Exception as exc:
        check("build_study_site is importable", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    prof, cp = profile(), copy()
    page = B.render(results(), prof, cp, rundate="14 September 2026")

    print("\n[DIMENSIONS]")
    dims = sorted(prof["scoring"]["dimensions"], key=lambda d: -d["weight"])
    for d in dims:
        check(f"{d['label']} appears with its computed weight {round(d['weight'] * 100)}%",
              html.escape(d["label"]) in page and f"{round(d['weight'] * 100)}%" in page)
        check(f"its question appears", html.escape(cp["dimensions"][d["key"]]["question"]) in page)
    positions = [page.find(html.escape(d["label"])) for d in dims]
    check("dimensions are listed in weight order", positions == sorted(positions), str(positions))
    for word in ("Clarity", "Technical", "Insight", "Verbatim Index"):
        check(f"no leaders wording: {word!r}", word not in page)

    print("\n[DOCUMENT]")
    # FOUND 2026-10-12 on the live page: no doctype, no charset and no viewport,
    # so a phone laid the table out at desktop width and the encoding of every
    # em dash was left to the browser's guess (the server sends bare text/html).
    check("the page opens with a doctype", page.lstrip().lower().startswith("<!doctype html>"), page[:80])
    check("the html element names its language", re.search(r'<html lang="en(-GB)?">', page) is not None)
    charset = page.lower().find('<meta charset="utf-8">')
    check("it declares utf-8 before the title, inside the first 1024 bytes",
          0 <= charset < page.find("<title>") and charset < 1024, str(charset))
    check("it carries a viewport, so a phone does not lay it out at desktop width",
          '<meta name="viewport" content="width=device-width, initial-scale=1">' in page)
    desc = re.search(r'<meta name="description" content="([^"]*)">', page)
    check("it carries a description built from the copy and the board",
          desc is not None and html.escape(cp["tagline"]) in desc.group(1)
          and "2 of 3 people" in desc.group(1), desc.group(0) if desc else "no description")

    # The layout itself is proven in a browser by check_pundits_phone_layout.py;
    # this guards the rule that made it pass from being deleted unnoticed.
    check("a narrow-screen rule wraps the person cell and drops intervals below their scores",
          "@media (max-width:600px)" in page and "td.person{white-space:normal" in page
          and "td.num .ci{display:block" in page)

    print("\n[SOCIAL]")
    # A link to the board on Twitter, LinkedIn or Slack showed a bare URL: the page
    # carried no Open Graph or Twitter tags (FOUND 2026-10-12).
    url = cp.get("site_url", "")
    check("the copy names the canonical site URL", url.startswith("https://") and url.endswith("/"), url)
    check("a canonical link names it", f'<link rel="canonical" href="{url}">' in page)
    check("og:url names it", f'<meta property="og:url" content="{url}">' in page)
    check("og:title is the copy title", f'<meta property="og:title" content="{html.escape(cp["title"])}">' in page)
    check("og:description repeats the derived description",
          desc is not None and f'<meta property="og:description" content="{desc.group(1)}">' in page)
    check("a text-only Twitter card, since no image is drawn yet",
          '<meta name="twitter:card" content="summary">' in page and "og:image" not in page)
    check("an inline icon, so the tab and bookmarks show one without a file",
          re.search(r'<link rel="icon" href="data:image/svg\+xml,[^"]+">', page) is not None)

    print("\n[SOURCES]")
    # The leaders page links "Code, rubric and tests on GitHub"; the pundits page
    # linked nothing, so a reader could not see the rubric the judges apply.
    check("the copy names an https rubric URL and code URL",
          cp.get("rubric_url", "").startswith("https://") and cp.get("code_url", "").startswith("https://"))
    check("the method section links the rubric", f'<a href="{html.escape(cp.get("rubric_url", "?"))}">' in page)
    check("and the code and tests", f'<a href="{html.escape(cp.get("code_url", "?"))}">' in page)

    print("\n[NOTES]")
    check("the interpretation note appears", html.escape(cp["interpretation"]) in page)
    check("the blinding note appears", html.escape(cp["blinding_note"]) in page)

    print("\n[ESCAPING]")
    check("markup in a name is escaped", "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page)

    print("\n[SCORES]")
    check("the blinded score and its interval render", "61.2" in page and "55.0" in page and "67.4" in page)
    check("the open score renders", "64.0" in page)
    check("the halo renders with its sign", "+2.8" in page)
    # Plan P5: "Published per person: blinded score, open score, halo, each with
    # an interval, and the paired count." FOUND 2026-10-12: only the blinded
    # score carried its interval.
    row_ada_s = page[page.find("Ada &lt;script"):]
    row_ada_s = row_ada_s[:row_ada_s.find("</tr>")]
    check("the open score carries its interval", "[58.1, 70.2]" in row_ada_s, row_ada_s[:600])
    check("the halo carries its signed interval", "[+0.4, +5.1]" in row_ada_s, row_ada_s[:600])
    check("the halo states its paired count", "16 pairs" in row_ada_s, row_ada_s[:600])
    row_bo = page[page.find("Bo Diddley"):]
    row_bo = row_bo[:row_bo.find("</tr>")]
    check("a missing open score and halo show a dash, not a zero",
          "&ndash;" in row_bo and ">0.0<" not in row_bo, row_bo[:300])

    print("\n[VENUE MIX]")
    # Plan P5, "Sampling rules": with no venue caps, format is handled in part by
    # showing each person's venue mix on the page. FOUND 2026-10-12: it was not shown.
    row_ada = page[page.find("Ada &lt;script"):]
    row_ada = row_ada[:row_ada.find("</tr>")]
    check("a person's venue mix appears in their row, largest first, counting each recording once",
          "5 conversation, 2 reaction, 1 debate" in row_ada, row_ada[:400])
    check("a person with no recorded venues shows no invented mix",
          "conversation" not in row_bo and "reaction" not in row_bo, row_bo[:300])
    # FOUND 2026-10-12 by review: with two judges a venue disagreement is a 1-1 tie,
    # aggregate.py marks it venue_agreed=False and keeps the alphabetically first
    # label, and the page showed that label as if it were known.
    tie = results()
    for t in tie["transcripts"]:
        if t["source_id"] == "ada-7":
            t["venue_agreed"] = False
    tp = B.render(tie, prof, cp, rundate="x")
    trow = tp[tp.find("Ada &lt;script"):]
    trow = trow[:trow.find("</tr>")]
    check("a recording whose format the judges disputed counts as disputed, not as its label",
          "5 conversation, 2 reaction, 1 format disputed" in trow, trow[:400])
    for t in tie["transcripts"]:
        t["cal_overall"] = 60.0
    tr = B.render(tie, prof, cp, rundate="x", recordings={})
    tsec = tr[tr.find('id="recordings"'):]
    check("and the recordings list says the format is disputed", "format disputed" in tsec
          and tsec.count("debate") == 0, tsec[:800])

    print("\n[RECORDINGS]")
    # The page says the method can be checked in the open, yet listed no recording
    # (FOUND 2026-10-12; the leaders page links every graded transcript). Each
    # ranked person gets a list of their board recordings: title linked to the
    # source, channel, upload date, venue and the recording's blinded score.
    meta = {("ada", "ada-0"): {"url": "https://www.youtube.com/watch?v=abc123",
                               "yt_title": "Ada <b>debates</b> Bo", "yt_channel": "Some Show",
                               "yt_upload_date": "20250507"},
            ("ada", "ada-1"): {"url": "javascript:alert(1)", "yt_title": "Bad link", "yt_channel": "X",
                               "yt_upload_date": "20240101"}}
    res = results()
    for t in res["transcripts"]:
        t["cal_overall"] = 60.0 + int(t["source_id"].split("-")[1])
    rp = B.render(res, prof, cp, rundate="x", recordings=meta)
    sec = rp[rp.find('id="recordings"'):]
    check("a recordings section follows the board", 'id="recordings"' in rp and rp.find('id="recordings"') > rp.find('id="board"'))
    ada = sec[sec.find("Ada &lt;script"):]
    ada = ada[:ada.find("</details>")]
    check("each ranked person lists every board recording once", ada.count("<li>") == 8, ada[:500])
    check("a title links to its source, escaped",
          '<a href="https://www.youtube.com/watch?v=abc123" rel="noopener">Ada &lt;b&gt;debates&lt;/b&gt; Bo</a>' in ada, ada[:600])
    check("with channel, upload date, venue and the recording's blinded score",
          "Some Show" in ada and "2025-05-07" in ada and "conversation" in ada and "60.0" in ada, ada[:600])
    check("a link that is not https is not rendered as a link", "javascript:" not in rp and "Bad link" in ada)
    check("a recording with no metadata shows its source id, unlinked", "ada-7" in ada)
    check("without metadata the section is not rendered", 'id="recordings"' not in page)

    print("\n[METHOD CLAIMS]")
    # FOUND 2026-10-12 reading the pilot page as a visitor: the Method section said a
    # dimension marked not observed "does not count", which reads as "the rest of the
    # recording still counts". The code drops that grade, so the recording loses a
    # judge and leaves the board (asmongold-tv-ks77-g on the pilot). Until the
    # operator settles plan P5's two rules (docs/PUNDITS-RELEASE-PLAN.md, decision 5),
    # the page says what the code does.
    method = cp["method"]
    check("the method copy says a recording with a dimension marked not observed is left out",
          "left out of the score" in method and "does not count" not in method, method)
    # board_overall() and agg() weight each recording by its coverage (floored at
    # 0.05), so a plain "mean" understates what the score is.
    check("and that a person's score weights each recording by how much of it could be scored",
          "weighted by how much of it the judges could score" in method, method)

    print("\n[UNRANKED]")
    ranked_table = page[page.find('id="board"'):page.find("</table>", page.find('id="board"'))]
    check("an unranked person is not in the ranked table", "Cy Unranked" not in ranked_table)
    check("but is listed with the reason", "Cy Unranked" in page and "below the floor" in page)

    print("\n[COPY]")
    bad = json.loads(json.dumps(cp))
    del bad["dimensions"]["d2_epistemic_rigor"]
    try:
        B.render(results(), prof, bad, rundate="x")
        refused = False
    except RuntimeError as exc:
        refused = "d2_epistemic_rigor" in str(exc)
    check("copy missing a dimension explainer is refused, naming the dimension", refused)
    bad = json.loads(json.dumps(cp))
    bad["dimensions"]["d1_steelmanning"]["explainer"] += " It is 35% of the score."
    try:
        B.render(results(), prof, bad, rundate="x")
        refused = False
    except RuntimeError as exc:
        refused = "%" in str(exc)
    check("copy that types a percentage is refused", refused)
    check("the shipped copy types no percentage", not re.search(r"\d+\s*%", json.dumps(cp)))

    print("\n[DISPATCH]")
    with tempfile.TemporaryDirectory(prefix="p4b-") as td:
        tmp = Path(td).resolve()
        root = tmp / "pundits-data"
        root.mkdir()
        for args in (("init", "-q", "-b", "main"),
                     ("config", "remote.origin.url", "git@github.com:tonygwu/verbatim-pundits-data.git")):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        (root / ".study").write_text("pundits\n")
        (root / "results.json").write_text(json.dumps(results()))
        (root / "results_audit.json").write_text("{}")
        (root / "roster").mkdir()
        (root / "roster" / "final.json").write_text(json.dumps({"roster": []}))
        (root / "logs").mkdir()
        (root / "logs" / "calibration.json").write_text("{}")
        out = tmp / "site-pundits" / "index.html"
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        r = subprocess.run([PY, REPO / "scripts" / "build_site.py", "--study", "pundits",
                            "--results", root / "results.json", "--audit", root / "results_audit.json",
                            "--roster", root / "roster" / "final.json",
                            "--calibration", root / "logs" / "calibration.json", "--out", out],
                           env=env, capture_output=True, text=True)
        written = out.read_text() if out.exists() else ""
        check("build_site.py --study pundits exits 0", r.returncode == 0, r.stderr[-400:])
        check("and writes the pundits page", "Verbatim Pundits" in written and "Verbatim Index" not in written)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
