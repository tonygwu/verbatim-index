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
         "halo": {"overall": 2.8}},
        {"rank": 2, "slug": "bo", "name": "Bo Diddley", "role": "columnist", "status": "scored",
         "n_transcripts": 6, "confidence": "medium", "blinded": block(48.5, 41.0, 55.9), "open": {}, "halo": {}},
    ]
    unranked = [{"slug": "cy", "name": "Cy Unranked", "role": "streamer", "status": "scored", "n_transcripts": 2,
                 "confidence": "low", "blinded": block(70.0, 50.0, 90.0), "open": {}, "halo": {},
                 "unranked_reason": "2 included transcripts, below the floor of 5"}]
    return {"leaders": ranked, "unranked": unranked,
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

    print("\n[NOTES]")
    check("the interpretation note appears", html.escape(cp["interpretation"]) in page)
    check("the blinding note appears", html.escape(cp["blinding_note"]) in page)

    print("\n[ESCAPING]")
    check("markup in a name is escaped", "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page)

    print("\n[SCORES]")
    check("the blinded score and its interval render", "61.2" in page and "55.0" in page and "67.4" in page)
    check("the open score renders", "64.0" in page)
    check("the halo renders with its sign", "+2.8" in page)
    row_bo = page[page.find("Bo Diddley"):]
    row_bo = row_bo[:row_bo.find("</tr>")]
    check("a missing open score and halo show a dash, not a zero",
          "&ndash;" in row_bo and ">0.0<" not in row_bo, row_bo[:300])

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
