#!/usr/bin/env python3
"""The predictions site's social card draws the top of the page's own board, and
the page says when the two disagree.

Operator request 2026-10-20: the card said only "1289 predictions, 1278
transcripts scanned, 99% with a date said". It named nobody and showed no result,
so it now draws the top three people of the page's ranking, each with the Score
and the Came true fraction exactly as the board prints them, and a strip of the
page's totals. The page head also carries the two `@tonygwu` twitter tags the
leaderboard page has.

What this proves:
  - the card's rows and totals are the page's ranking and totals on one fixture,
    whichever of the two paths computes them (the page's main(), with every
    input, or the card builder, which reads no prediction records);
  - the card prints Score and Came true exactly as the page's own JavaScript
    does, an exact half and a negative included;
  - the page warns when the card's names, ranks, scores or counts drift from the
    page, and stays silent when they match;
  - the page head carries twitter:site and twitter:creator;
  - og:image:alt and twitter:image:alt describe the ranked card, written from
    the figures og.meta.json records it was drawn with: every figure in the
    card's order, no number that is not one of them, two sentences, at most
    twitter:image:alt's 420 characters (operator request 2026-10-21).

Drawing the PNG needs Chrome and is not done here. No data, no network, no quota.

  .venv/bin/python scripts/test_predictions_og_card.py
"""

from __future__ import annotations

import argparse
import collections
import html as H
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str, path: Path | None = None):
    spec = importlib.util.spec_from_file_location(f"{name}_ogtest", path or REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def section(title: str, fn) -> None:
    """A section that raises is a FAIL with its traceback, never a crash that hides
    the sections after it."""
    print(f"\n== {title} ==")
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - SystemExit from a REFUSING path counts too
        check(f"{title}: ran to the end", False, f"{type(exc).__name__}: {exc}\n"
              + "".join(traceback.format_exc().splitlines(True)[-6:]))


B = load("build_predictions_site")
card = load("build_og_card")


# ---------------------------------------------------------------------------
# A board of seven people, built so that every way the card could go wrong
# against the page has a row that shows it:
#   dee  has the highest mean but is off the predictions board;
#   eve  has the second highest but sits under the listing floor;
#   ann, cal and bob are the page's top three, in that order;
#   bob's mean is exactly 0.125, which JavaScript's toFixed(2) prints as 0.13
#        and Python's format prints as 0.12, so a Python-side formatter that is
#        not the page's own rounding fails here;
#   gus  is ranked with a negative mean, so the true minus sign is exercised;
#   fay  is listed below the rank floor and carries no Score.
# ---------------------------------------------------------------------------
PEOPLE = [
    # slug, name, accepted, mean_points, n_scored, hits, ranked, past_due
    ("ann", "Ann Arbor", 9, 0.30, 8, 5, True, 9),
    ("bob", "Bob Bell", 6, 0.125, 4, 3, True, 5),
    ("cal", "Cal Cole", 7, 0.2696, 17, 9, True, 18),
    ("dee", "Dee Dunn", 8, 0.90, 5, 5, True, 6),
    ("eve", "Eve East", 2, 0.80, 3, 3, True, 3),
    ("fay", "Fay Ford", 5, None, 2, 1, False, 3),
    ("gus", "Gus Gray", 6, -0.0012, 6, 2, True, 7),
]
ROLES = {"ann": "Chairman and CEO", "bob": "CEO", "cal": "Co-founder and CEO",
         "dee": "CTO", "eve": "Founder", "fay": "President", "gus": "Partner"}


def index_doc() -> dict:
    leaders = []
    for slug, name, accepted, *_ in PEOPLE:
        leaders.append({
            "slug": slug, "name": name, "role": ROLES[slug], "company": f"{name.split()[0]} Co",
            "sector": "AI Labs", "accepted": accepted, "rejected_by_verifier": 1,
            "by_horizon": {"explicit": accepted}, "explicit_probability": 0, "qualitative_confidence": 0,
            "transcripts_with_accepted": 1, "earliest_statement_date": "2024-01-01",
            "transcripts_on_disk": 1, "transcripts_extracted_in_corpus": 1,
            "by_category": {}, "by_prediction_type": {}})
    total = sum(l["accepted"] for l in leaders)
    return {"leaders": leaders, "corpus": {"accepted": total, "statement_date_unknown": 1},
            "coverage": {"extract": {"ok": 40}}}


def roster_doc() -> dict:
    return {"roster": [{"slug": s, "name": n, "role": ROLES[s], "company": f"{n.split()[0]} Co",
                        "sector": "AI Labs"} for s, n, *_ in PEOPLE]}


def scores_doc() -> dict:
    leaders, preds = [], []
    for slug, name, _acc, mean, n, hits, ranked, past_due in PEOPLE:
        leaders.append({"slug": slug, "name": name, "mean_points": mean, "n_scored": n,
                        "scored_occurred": hits, "hit_rate": round(hits / n, 4) if n else None,
                        # ann has two eligible predictions that were not scored, so
                        # the card's "scored" cannot pass by reading "eligible".
                        "ranked": ranked, "past_due": past_due, "eligible": n + (2 if slug == "ann" else 0),
                        "unresolvable": 0,
                        "restated": 0})
    # One early call for a listed person: scored before its deadline, so the
    # page's "scored in all" figure is larger than its scored-of-past-due figure.
    preds.append({"prediction_id": "early1", "leader_slug": "ann", "early_called": True,
                  "not_due": True, "scored": True, "outcome": "occurred"})
    L = leaders
    return {"as_of": "2026-10-20", "rule": {"min_lead_days": 60}, "predictions": preds,
            "corpus": {"past_due": sum(l["past_due"] for l in L), "eligible": sum(l["eligible"] for l in L),
                       "scored": sum(l["n_scored"] for l in L),
                       "leaders_ranked": sum(1 for l in L if l["ranked"]),
                       "by_outcome": {"unresolvable": 0}, "unresolvable_reasons": {}, "restated": 0},
            "leaders": leaders}


MEMBERSHIP = {s: (["leaders"] if s == "dee" else ["leaders", "predictions"]) for s, *_ in PEOPLE}
EXPECTED_TOP = [("ann", "+0.30", "5/8"), ("cal", "+0.27", "9/17"), ("bob", "+0.13", "3/4")]


def page_path_figures(index: dict, roster: dict, sd: dict, off_board: frozenset) -> dict:
    """The figures as the page's main() computes them: person_rows with every input
    the page passes (a timeline, buckets, sensitivity), then listed_corpus."""
    scores = {l["slug"]: l for l in sd["leaders"]}
    hist = {s: {"years": {"2024": 2}, "undated": 0, "early": 0} for s, *_ in PEOPLE}
    buckets = {s: {"buckets": {"scored": 1}, "unres": {}} for s, *_ in PEOPLE}
    sens = {k: {"complete": True, "leaders": {s: {"mean_points": 0.1, "rank": 1, "n_scored": 1,
                                                    "implied_missing": 0, "complete": True}
                                                for s, *_ in PEOPLE}} for k in ("half", "double")}
    rows = B.person_rows(index, roster, hist, scores, 60, buckets, off_board, sens)
    cl = B.listed_corpus(sd, {r["slug"] for r in rows})
    return B.card_figures(rows, cl, index, sd["as_of"]), rows, cl


def write_fixture(td: Path) -> dict:
    paths = {"index": td / "index.json", "roster": td / "roster.json",
             "scores": td / "scores.json", "membership": td / "membership.json"}
    paths["index"].write_text(json.dumps(index_doc()))
    paths["roster"].write_text(json.dumps(roster_doc()))
    paths["scores"].write_text(json.dumps(scores_doc()))
    paths["membership"].write_text(json.dumps(MEMBERSHIP))
    return paths


def js_cells(rows: list[dict]) -> list[dict]:
    """Score and Came true as the page's own scoreCell() and hitCell() print them,
    run through node from the page template, tags stripped."""
    t = B.TEMPLATE
    esc = re.search(r"^const esc = .*;$", t, re.M)
    hit = t[t.index("function hitCell(r){"):t.index("/* Each person's score at half")]
    sc = t[t.index("function sensWords(r){"):t.index("/* score:end */", t.index("function scoreCell(r){"))]
    probe = ((esc.group(0) if esc else 'const esc = s => String(s);') + "\nconst MIN_SCORED = 3;\n" + hit + sc
             + "\nconst strip = h => h.replace(/<[^>]*>/g, '').trim();\n"
             + "console.log(JSON.stringify(" + json.dumps(rows)
             + ".map(r => ({slug: r.slug, score: strip(scoreCell(r)), came_true: strip(hitCell(r))}))));")
    n = subprocess.run(["node", "-e", probe], capture_output=True, text=True)
    if n.returncode != 0:
        raise RuntimeError(f"node failed: {n.stderr[-600:]}")
    return json.loads(n.stdout)


def card_matches_page() -> None:
    index, roster = index_doc(), {r["slug"]: r for r in roster_doc()["roster"]}
    sd = scores_doc()
    with tempfile.TemporaryDirectory() as td:
        paths = write_fixture(Path(td))
        off = B.off_board_slugs(index, str(paths["membership"]))
        check("the off-board person is read from membership.json", off == frozenset({"dee"}), str(off))
        fig, rows, cl = page_path_figures(index, roster, sd, off)
        top = [(t["slug"], t["score"], t["came_true"]) for t in fig["top"]]
        check("the page's figures are the top three of its own ranking, off-board and unlisted people skipped",
              top == EXPECTED_TOP, str(top))
        check("each row is numbered by its place in the page's order",
              [t["rank"] for t in fig["top"]] == [1, 2, 3], str(fig["top"]))
        check("each row carries the name and role line the page shows",
              [(t["name"], t["role"]) for t in fig["top"]]
              == [(r["name"], r["role"]) for r in rows[:3]], str(fig["top"]))
        ranked_rows = [r for r in rows if r["score"] is not None]
        check("people ranked is the page's count of rows with a Score",
              fig["people_ranked"] == len(ranked_rows) == cl["leaders_ranked"] == 4,
              f"{fig['people_ranked']} vs rows {len(ranked_rows)} vs cl {cl['leaders_ranked']}")
        check("predictions scored is the page's 'scored in all' figure",
              fig["scored"] == cl["scored"] and f"({cl['scored']} scored in all)" in B.score_legend(cl),
              f"{fig['scored']} vs {cl['scored']}: {B.score_legend(cl)[:300]}")
        check("the fixture tells scored from eligible, so the check above can fail",
              cl["scored"] != cl["eligible"], f"scored {cl['scored']} eligible {cl['eligible']}")
        check("predictions extracted is the page's Predictions figure",
              fig["predictions"] == index["corpus"]["accepted"], str(fig["predictions"]))
        check("the as-of date is the scoring run's", fig["as_of"] == "2026-10-20", str(fig["as_of"]))
        check("'and N more' counts the ranked people the card leaves out",
              fig["more"] == len(ranked_rows) - 3 == 1, str(fig.get("more")))

        # The card builder's own path: it reads files and no prediction records.
        args = argparse.Namespace(index=str(paths["index"]), roster=str(paths["roster"]),
                                  scores=str(paths["scores"]), membership=str(paths["membership"]))
        drawn, _ = card.predictions_counts(args)
        check("the card builder computes exactly the page's figures", drawn == fig,
              f"card {json.dumps(drawn)[:400]}\n        page {json.dumps(fig)[:400]}")

        # The board's own JavaScript prints the same Score and Came true strings.
        cells = {c["slug"]: c for c in js_cells(rows)}
        mismatch = [(t["slug"], t["score"], cells[t["slug"]]["score"], t["came_true"], cells[t["slug"]]["came_true"])
                    for t in fig["top"]
                    if (t["score"], t["came_true"]) != (cells[t["slug"]]["score"], cells[t["slug"]]["came_true"])]
        check("Score and Came true are the strings the page's scoreCell and hitCell print", not mismatch,
              str(mismatch))
        neg = [{"slug": "neg", "score": v, "n_scored": 5, "score_hits": 1, "ranked": True}
               for v in (-0.0012, -0.125, -0.3349, 0.005, 0.0)]
        js = [c["score"] for c in js_cells(neg)]
        py = [B.score_text(r["score"]) for r in neg]
        check("score_text matches scoreCell on negatives, exact halves and zero", js == py, f"js {js} py {py}")
        check("a negative Score carries the true minus sign U+2212", py[0] == "−0.00" and py[1] == "−0.13",
              str(py))

        html = card.predictions_card_html(fig)
        # What a reader sees: the markup gone, so 5<span>/</span>8 reads 5/8.
        text = re.sub(r"<[^>]+>", "", html)
        for want in ("Ann Arbor", "Chairman and CEO", "Ann Co", "+0.30", "5/8", "Cal Cole", "9/17",
                     "Bob Bell", "+0.13", "3/4", "Came true", "Score", "Person",
                     "VERBATIM-PREDICTIONS.TONYGWU.COM".lower(), "Predictions",
                     "<b>4</b> people ranked", f"<b>{cl['scored']}</b> predictions scored",
                     f"<b>{index['corpus']['accepted']}</b> extracted",
                     "as of <b>2026-10-20</b>", "and 1 more"):
            check(f"the card's HTML draws {want!r}", want in (html if "<" in want else text))
        check("a positive Score is drawn in the page's positive colour",
              f'<b class="pos">+0.30</b>' in html, html[html.find('class="sc"'):][:120])
        neg_fig = json.loads(json.dumps(fig))
        neg_fig["top"][2]["score"] = "\u22120.50"
        check("a negative Score is drawn in the page's negative colour",
              '<b class="neg">\u22120.50</b>' in card.predictions_card_html(neg_fig))
        check("the card names nobody the page does not rank in its top three",
              not any(n in html for n in ("Dee Dunn", "Eve East", "Fay Ford", "Gus Gray")))

        few = json.loads(json.dumps(sd))
        for l in few["leaders"]:
            if l["slug"] in ("bob", "cal", "gus"):
                l["ranked"] = False
        few["corpus"]["leaders_ranked"] = sum(1 for l in few["leaders"] if l["ranked"])
        paths["scores"].write_text(json.dumps(few))
        err, code = io.StringIO(), None
        with redirect_stderr(err):
            try:
                card.predictions_counts(args)
            except SystemExit as exc:
                code = exc.code
        check("fewer ranked people than rows is a refusal, not a short card",
              code is not None and "REFUSING" in str(code), f"exit {code!r} {err.getvalue()[-200:]}")


def drift_warning() -> None:
    index, roster = index_doc(), {r["slug"]: r for r in roster_doc()["roster"]}
    sd = scores_doc()
    fig, _rows, _cl = page_path_figures(index, roster, sd, frozenset({"dee"}))
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "og.png"
        png.write_bytes(b"\x89PNG" + b"0" * 6000)
        meta = png.with_suffix(".meta.json")
        B.OG_CARD, B.OG_CARD_META = png, meta

        def warns(drawn: dict | None, now: dict | None) -> str:
            if drawn is None:
                meta.unlink(missing_ok=True)
            else:
                meta.write_text(json.dumps(card.card_meta("predictions", drawn)))
            err = io.StringIO()
            with redirect_stderr(err):
                B.check_og_card(now)
            return err.getvalue()

        out = warns(fig, fig)
        check("a card that matches the page draws no warning", out == "", out)

        swapped = json.loads(json.dumps(fig))
        swapped["top"][1], swapped["top"][2] = swapped["top"][2], swapped["top"][1]
        swapped["top"][1]["rank"], swapped["top"][2]["rank"] = 2, 3
        out = warns(swapped, fig)
        check("two people changing places warns", "og.png" in out and "re-run" in out, out)
        check("the warning names both orders", "Bob Bell" in out and "Cal Cole" in out, out)

        for label, mutate in (
                ("a changed Score", lambda f: f["top"][0].update(score="+0.29")),
                ("a changed Came true count", lambda f: f["top"][2].update(came_true="3/5")),
                ("a changed name", lambda f: f["top"][0].update(name="Ann Other")),
                ("a changed people-ranked count", lambda f: f.update(people_ranked=5)),
                ("a changed scored count", lambda f: f.update(scored=f["scored"] + 1)),
                ("a changed predictions count", lambda f: f.update(predictions=f["predictions"] - 1)),
                ("a changed as-of date", lambda f: f.update(as_of="2026-10-19"))):
            old = json.loads(json.dumps(fig))
            mutate(old)
            out = warns(old, fig)
            check(f"{label} warns", "og.png" in out and "stale" in out, out)

        # The card drawn before this change recorded three corpus counts and no rows.
        out = warns({"predictions": 1289, "transcripts_scanned": 1278, "pct_dated": 99}, fig)
        check("the old counts-only card warns that it draws no ranking", "og.png" in out and "top" in out, out)
        out = warns(fig, None)
        check("a ranked card over a page with no Score column warns", "og.png" in out and "Score" in out, out)
        meta.unlink()
        err = io.StringIO()
        with redirect_stderr(err):
            B.check_og_card(fig)
        check("a card with no sidecar says its figures cannot be checked", ".meta.json" in err.getvalue(),
              err.getvalue())


def main_wires_the_check() -> None:
    """The page's main() itself compares its own board with the card, so the
    warning fires on a real render, not only when the function is called by hand."""
    T = load("test_predictions_site")
    L, A = load("predictions_lib"), load("aggregate_predictions")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pr, roster, index = T.build(td, L, A)
        recs = {s: [r for r in B.load_records(pr)["accepted"] if r["leader_slug"] == s] for s in ("ada", "alan")}
        scored_pid = recs["ada"][0]["prediction_id"]
        run1 = td / "run1"
        (run1 / "priors" / "ada").mkdir(parents=True)
        (run1 / "priors" / "ada" / f"{scored_pid}.json").write_text(json.dumps(
            {"prediction_id": scored_pid, "leader_slug": "ada", "stage": "prior", "p": 0.25,
             "telemetry": {"canonical_model": "claude-fable-5-1", "requested_model": "claude-fable-5-1",
                           "telemetry_models": ["claude-fable-5-1"]}}))
        (run1 / "resolutions" / "ada").mkdir(parents=True)
        (run1 / "resolutions" / "ada" / f"{scored_pid}.json").write_text(json.dumps(
            {"prediction_id": scored_pid, "leader_slug": "ada", "stage": "resolve", "outcome": "occurred",
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
                {"slug": "ada", "name": "Ada L", "n_scored": 6, "mean_points": 0.125, "ranked": True,
                 "past_due": 7, "eligible": 7, "unresolvable": 0, "scored_occurred": 4, "hit_rate": 0.6667},
                {"slug": "alan", "name": "Alan T", "n_scored": 2, "mean_points": -0.5, "ranked": True,
                 "past_due": 2, "eligible": 2, "unresolvable": 0, "scored_occurred": 1, "hit_rate": 0.5},
                {"slug": "cleo", "name": "Cleo F", "n_scored": 0, "mean_points": None, "ranked": False,
                 "past_due": 0, "eligible": 0, "unresolvable": 0, "scored_occurred": 0, "hit_rate": None}],
            "predictions": [
                {"prediction_id": scored_pid, "leader_slug": "ada", "outcome": "occurred", "scored": True,
                 "unresolvable_reason": None, "resolution_reasoning": "it shipped",
                 "sources": [{"where": "https://example.com/a", "what_it_shows": "shipped", "date": "2026-01-02"}],
                 "p": 0.25, "reference_class": "things like this", "points": 2.0, "deadline": "2026-06-30",
                 "flags": T.fl(True, 486), "not_scored_because": None}]}))
        membership = T.mem(roster)
        idx = json.loads(index.read_text())
        sd = json.loads(scores.read_text())
        rost = {r["slug"]: r for r in json.loads(roster.read_text())["roster"]}
        expected = B.card_figures_for(idx, rost, sd, B.off_board_slugs(idx, str(membership)))
        check("FIXTURE: the card's figures name the fixture's two ranked people, best first",
              [(t["slug"], t["score"], t["came_true"]) for t in expected["top"]]
              == [("ada", "+0.13", "4/6"), ("alan", "−0.50", "1/2")], str(expected["top"]))

        png = td / "og.png"
        png.write_bytes(b"\x89PNG" + b"0" * 6000)
        meta = png.with_suffix(".meta.json")
        B.OG_CARD, B.OG_CARD_META = png, meta
        argv = ["--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                "--roster", str(roster), "--membership", str(membership), "--scores", str(scores)]

        def render(name: str) -> tuple[str, str]:
            err, out = io.StringIO(), io.StringIO()
            with redirect_stderr(err), redirect_stdout(out):
                B.main(argv + ["--out", str(td / name / "index.html")])
            return err.getvalue(), (td / name / "index.html").read_text()

        meta.write_text(json.dumps(card.card_meta("predictions", expected)))
        err, html = render("same")
        check("a render whose board matches the card prints no card warning", "og.png" not in err, err[-600:])
        check("the rendered page's own rows are the card's rows",
              [r["slug"] for r in T.embedded(html, "DATA") if r["score"] is not None]
              == [t["slug"] for t in expected["top"]])

        head = html[:html.index("</head>")]
        alt = H.escape(B.og_alt(), quote=True)
        check("ALT: the rendered head's og:image:alt is the card's alt text",
              f'<meta property="og:image:alt" content="{alt}">' in head, head[-1200:])
        check("ALT: the rendered head's twitter:image:alt is the card's alt text",
              f'<meta name="twitter:image:alt" content="{alt}">' in head, head[-1200:])
        check("ALT: on the fixture it names the card's two rows with their figures",
              "Ada L of Co, Score +0.13, 4 of 6 came true; and Alan T of Lab, Score \u22120.50, 1 of 2 came true."
              in B.og_alt(), B.og_alt())

        moved = json.loads(json.dumps(expected))
        moved["top"][0]["score"] = "+0.12"
        meta.write_text(json.dumps(card.card_meta("predictions", moved)))
        err, moved_html = render("moved")
        check("a render whose board no longer matches the card warns", "og.png" in err and "stale" in err,
              err[-600:])
        moved_head = moved_html[:moved_html.index("</head>")]
        check("ALT: the alt text describes the card as drawn, even when the board has moved on",
              "Score +0.12" in moved_head and "Score +0.13" not in moved_head, moved_head[-1200:])
        check("the page head carries twitter:site @tonygwu",
              '<meta name="twitter:site" content="@tonygwu">' in head, head[-800:])
        check("the page head carries twitter:creator @tonygwu",
              '<meta name="twitter:creator" content="@tonygwu">' in head, head[-800:])


def fit_check() -> None:
    """card_fits() reads the size the card's own script measured and refuses
    anything larger than 1200x630, or no measurement at all. Chrome is stubbed:
    the measurement itself was checked by hand with real long roles."""
    check("the card's HTML measures itself once the fonts are in",
          "document.body.dataset.fit" in card.PRED_CARD and "document.fonts.ready" in card.PRED_CARD)
    real = card.subprocess
    try:
        for dom, ok in (('<body data-fit="1200x630">', True), ('<body data-fit="1200x653">', False),
                        ('<body data-fit="1210x630">', False), ("<body>", False)):
            card.subprocess = argparse.Namespace(run=lambda *a, _d=dom, **k: argparse.Namespace(stdout=_d))
            code = None
            try:
                card.card_fits("chrome", Path("/tmp/card.html"))
            except SystemExit as exc:
                code = exc.code
            check(f"a measured {dom!r} {'passes' if ok else 'refuses'}",
                  (code is None) if ok else ("REFUSING" in str(code)), repr(code))
    finally:
        card.subprocess = real
    src = Path(card.__file__).read_text()
    check("the predictions card is measured before it is drawn",
          src.index("card_fits(find_chrome(), src)") < src.index('f"--screenshot={out}"'))


def alt_text() -> None:
    """og:image:alt and twitter:image:alt still read "Verbatim Predictions." and
    the page title, which described the old card of three totals. They now
    describe the ranked card, from the figures og.meta.json records it was
    drawn with, so the text and the picture cannot disagree."""
    check("ALT: both alt tags in the template take the generated text",
          B.TEMPLATE.count('content="__OG_ALT__"') == 2
          and '<meta property="og:image:alt" content="__OG_ALT__">' in B.TEMPLATE
          and '<meta name="twitter:image:alt" content="__OG_ALT__">' in B.TEMPLATE)
    saved = B.OG_CARD_META
    try:
        with tempfile.TemporaryDirectory() as td:
            index, roster = index_doc(), {r["slug"]: r for r in roster_doc()["roster"]}
            fig, _rows, _cl = page_path_figures(index, roster, scores_doc(), frozenset({"dee"}))
            meta = Path(td) / "og.meta.json"
            B.OG_CARD_META = meta

            def alt_for(drawn: dict) -> str:
                meta.write_text(json.dumps(card.card_meta("predictions", drawn)))
                return B.og_alt()

            alt = alt_for(fig)
            want = [f"ranks {fig['people_ranked']} people by Score", f"{fig['scored']} predictions scored",
                    f"{fig['predictions']} extracted", f"as of {fig['as_of']}", f"The top {len(fig['top'])} are"]
            for t in fig["top"]:
                hits, n = t["came_true"].split("/")
                want += [f"{t['name']} of {t['company']}", f"Score {t['score']}", f"{hits} of {n} came true"]
            at, missing = 0, []
            for w in want:
                i = alt.find(w, at)
                if i < 0:
                    missing.append(w)
                else:
                    at = i + len(w)
            check("ALT: every figure on the card is in the alt text, in the card's order", not missing,
                  f"missing or out of order {missing}: {alt}")
            figures = [str(fig["people_ranked"]), str(fig["scored"]), str(fig["predictions"]),
                       *fig["as_of"].split("-"), str(len(fig["top"]))]
            for t in fig["top"]:
                figures += [t["score"].lstrip("+\u2212"), *t["came_true"].split("/")]
            nums = collections.Counter(re.findall(r"\d+(?:\.\d+)?", alt))
            check("ALT: every number in the alt text is one of the card's figures, none typed",
                  nums == collections.Counter(figures), f"text {sorted(nums.elements())} card {sorted(figures)}")
            check("ALT: it is two sentences", alt.endswith(".") and len(alt.split(". ")) == 2, alt)
            check("ALT: it fits twitter:image:alt's 420 characters", len(alt) <= B.OG_ALT_MAX == 420, str(len(alt)))

            moved = json.loads(json.dumps(fig))
            moved["top"][0].update(score="+0.29", came_true="6/9")
            moved.update(people_ranked=41, scored=777)
            alt2 = alt_for(moved)
            check("ALT: a figure that changes on the card changes in the alt text",
                  "Score +0.29, 6 of 9 came true" in alt2 and "ranks 41 people" in alt2
                  and "777 predictions scored" in alt2 and "+0.30" not in alt2, alt2)
            neg = json.loads(json.dumps(fig))
            neg["top"][2]["score"] = "\u22120.50"
            check("ALT: a negative Score keeps the card's true minus sign",
                  "Score \u22120.50" in alt_for(neg))

            long = json.loads(json.dumps(fig))
            long["top"][0]["company"] = "Co " * 140
            code = None
            try:
                alt_for(long)
            except SystemExit as exc:
                code = exc.code
            check("ALT: text over 420 characters refuses the render rather than being cut off",
                  code is not None and "REFUSING" in str(code), repr(code)[:200])

            meta.write_text(json.dumps({"counts": {"predictions": 1289, "transcripts_scanned": 1278}}))
            check("ALT: a card with no ranking on record keeps the old text", B.og_alt() == B.OG_ALT_UNRANKED,
                  B.og_alt())
            meta.unlink()
            check("ALT: a card with no sidecar keeps the old text", B.og_alt() == B.OG_ALT_UNRANKED, B.og_alt())

        B.OG_CARD_META = REPO / "site-predictions" / "og.meta.json"
        drawn = json.loads(B.OG_CARD_META.read_text())["counts"]
        alt = B.og_alt()
        rows = [f"{t['name']} of {t['company']}, Score {t['score']}, "
                f"{t['came_true'].split('/')[0]} of {t['came_true'].split('/')[1]} came true" for t in drawn["top"]]
        check("ALT: the committed card's alt text names its rows and totals",
              all(r in alt for r in rows) and f"ranks {drawn['people_ranked']} people" in alt
              and f"{drawn['scored']} predictions scored" in alt and f"{drawn['predictions']} extracted" in alt
              and f"as of {drawn['as_of']}" in alt and len(alt) <= 420, alt)
    finally:
        B.OG_CARD_META = saved


def head_tags() -> None:
    head = B.TEMPLATE[:B.TEMPLATE.index("</head>")]
    check("the template's head carries twitter:site @tonygwu",
          '<meta name="twitter:site" content="@tonygwu">' in head)
    check("the template's head carries twitter:creator @tonygwu",
          '<meta name="twitter:creator" content="@tonygwu">' in head)


section("the card's rows and totals are the page's", card_matches_page)
section("the page warns when the card drifts from it", drift_warning)
section("the page's main() runs the check on a real render", main_wires_the_check)
section("the card refuses content that does not fit", fit_check)
section("the page head carries both twitter tags", head_tags)
section("the alt text describes the ranked card from its drawn figures", alt_text)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
raise SystemExit(1 if FAIL else 0)
