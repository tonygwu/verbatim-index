#!/usr/bin/env python3
"""Implied windows for predictions with no stated deadline (VD-6 (a), operator 2026-09-29).

The operator's table, committed before any record is judged over it:
  words "coming weeks" 3 months; "coming months", "next several months", "in a
  few months" 12 months; "soon", "shortly", "near term" 1 year; "eventually",
  "someday", "over time" 5 years; otherwise by claim: the speaker's own company
  or product 1 year; another company, or policy and regulation, 3 years;
  everything else 5 years, the cap. "In my lifetime", "decades" and "at least N
  years" beyond the cap get no window.

What this pins, with the critiques of the rescue round-4 design applied:
  - the table is pinned by a sha256, so an edit after records are judged over it
    is a visible, deliberate change (critique 1 point 3);
  - the phrase rows read the verbatim quote as well as target_date_text, and a
    record whose words sit only in the quote (release 2.2) gets the SAME window
    as one whose extractor copied them into target_date_text (release 2.3)
    (critique 1 point 4);
  - lead comes from the SHORTEST reading of the words, so "coming weeks" stays
    under the 60-day floor, and words with no lower bound are not a lead when the
    speaker controls the outcome (critique 1 point 2);
  - a conditional or ordering claim is screened out mechanically BEFORE any
    resolver runs, from the pipeline's own claim text, never by a resolver that
    has seen what happened (critique 1 point 5);
  - "eventually" gets 5 years, while "in my lifetime" and "at least 10 years" get
    none (critique 3 E4);
  - with the policy off, nothing changes;
  - a trend record already RESOLVED keeps its frozen trend window when the policy
    is switched on, so no scored row moves by accident;
  - the half and double windows the sensitivity report needs come from the same
    function, with the shortest reading unchanged.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import phase2_resolvability as P2  # noqa: E402

FAILED = []

# The sha256 of the committed table. Changing the table changes this, and a
# scoring config that names the old value refuses (test_implied_scoring.py).
PINNED_TABLE_SHA256 = "2b44127153bf6dcae40c78e254f9076730d3bbd9ef64d5628e571949e4a671df"


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, *, said="2025-01-15", tdt=None, quote="we will do it", claim=None, crit=None,
        cat="market_industry", ctrl="external", target=None, spec="medium", ptype="milestone"):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "prediction": {"target_date": target, "target_date_text": tdt, "horizon_years_inferred": None,
                       "specificity": spec, "subject_control": ctrl, "category": cat,
                       "prediction_type": ptype, "horizon": "none",
                       "normalized_claim": claim or f"claim {pid}", "resolution_criteria": crit or f"crit {pid}"},
        "source": {"statement_date": said, "quote": quote},
        "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None},
    }


def deadline(r, scale=1.0, trend_cutoff=None):
    rows = [json.loads(json.dumps(r))]
    P2.attach_deadlines(rows, derive=True, trend_cutoff=trend_cutoff, implied=scale)
    return rows[0]


def plain(r, trend_cutoff=None):
    rows = [json.loads(json.dumps(r))]
    P2.attach_deadlines(rows, derive=True, trend_cutoff=trend_cutoff)
    return rows[0]


def main() -> int:
    print("the table is pinned")
    sha = P2.implied_table_sha256()
    check("PIN: the implied-window table hashes to the committed value", sha == PINNED_TABLE_SHA256,
          f"now {sha}")
    t = P2.IMPLIED_TABLE
    check("PIN: the cap is five years", t["cap_years"] == 5, str(t.get("cap_years")))

    print("the operator's phrase rows")
    cases = [
        ("weeks", dict(tdt="in the coming weeks"), dt.date(2025, 4, 15)),
        ("months", dict(tdt="in the coming months"), dt.date(2026, 1, 15)),
        ("several", dict(tdt="over the next several months"), dt.date(2026, 1, 15)),
        ("few", dict(tdt="in a few months"), dt.date(2026, 1, 15)),
        ("soon", dict(tdt="soon"), dt.date(2026, 1, 15)),
        ("shortly", dict(tdt="shortly"), dt.date(2026, 1, 15)),
        ("near", dict(tdt="in the near term"), dt.date(2026, 1, 15)),
        ("eventually", dict(tdt="eventually"), dt.date(2030, 1, 15)),
        ("someday", dict(tdt="someday"), dt.date(2030, 1, 15)),
        ("overtime", dict(tdt="over time"), dt.date(2030, 1, 15)),
    ]
    for pid, kw, want in cases:
        r = deadline(rec(pid, **kw))
        check(f"PHRASE: {kw['tdt']!r} said 2025-01-15 closes {want}",
              r["_deadline"] == want and str(r["_basis"]).startswith("implied:"),
              f"{r['_deadline']} {r['_basis']} {r['_why_none']}")
    r = deadline(rec("few2", tdt="in a few months"))
    check("PHRASE: the operator's 12-month row beats the funnel's word count (few = 3 months) for "
          "'in a few months'", r["_deadline"] == dt.date(2026, 1, 15), str(r["_deadline"]))
    r = deadline(rec("digit", tdt="in 2 weeks, in the coming weeks"))
    check("PHRASE: words that carry a number keep the funnel's own reading (2 weeks), never the vague row",
          r["_deadline"] == dt.date(2025, 1, 29) and str(r["_basis"]).startswith("derived"),
          f"{r['_deadline']} {r['_basis']}")

    print("release 2.2 (words only in the quote) and 2.3 (words copied to target_date_text) agree")
    for words in ("soon", "in a few months", "in the coming weeks", "eventually"):
        a = deadline(rec("v22", tdt=None, quote=f"we will ship it {words}, I think"))
        b = deadline(rec("v23", tdt=words, quote=f"we will ship it {words}, I think"))
        check(f"2.2 = 2.3: {words!r} gives one deadline whichever field holds it",
              a["_deadline"] == b["_deadline"] is not None, f"{a['_deadline']} vs {b['_deadline']}")
    a = deadline(rec("q", quote="it will happen soon"))
    check("QUOTE: the phrase is read from the verbatim quote", a["_implied"]["matched_in"] == "quote",
          str(a.get("_implied")))

    print("the claim rows")
    own = deadline(rec("own", cat="company_business", ctrl="own"))
    check("CLASS: the speaker's own company or product closes in 1 year", own["_deadline"] == dt.date(2026, 1, 15),
          str(own["_deadline"]))
    ext = deadline(rec("acq", cat="company_business", ctrl="external",
                       claim="Salesforce will acquire Buddy Media at an unspecified future date."))
    check("CLASS: another company (an acquisition) closes in 3 years", ext["_deadline"] == dt.date(2028, 1, 15),
          str(ext["_deadline"]))
    part = deadline(rec("part", cat="technology_product", ctrl="partial"))
    check("CLASS: partial control is not the speaker's own, so 3 years", part["_deadline"] == dt.date(2028, 1, 15),
          str(part["_deadline"]))
    pol = deadline(rec("pol", cat="policy_regulation", ctrl="own"))
    check("CLASS: policy and regulation close in 3 years, whoever speaks", pol["_deadline"] == dt.date(2028, 1, 15),
          str(pol["_deadline"]))
    mac = deadline(rec("mac", cat="macro_economy"))
    check("CLASS: everything else closes at the 5-year cap", mac["_deadline"] == dt.date(2030, 1, 15),
          str(mac["_deadline"]))
    sacks = deadline(rec("a11", said="2022-05-05", cat="policy_regulation",
                         claim="Chesa Boudin will be recalled and Mayor Breed will appoint a new district attorney.",
                         crit="By an unspecified date, Boudin will be recalled and Breed will appoint his successor."))
    check("A11 SHAPE: a recall-and-appointment claim is not screened as conditional, and closes in 3 years",
          sacks["_deadline"] == dt.date(2025, 5, 5), f"{sacks['_deadline']} {sacks['_why_none']}")

    print("no window: the speaker's own horizon is longer than the cap")
    for pid, kw in (("life", dict(quote="in my lifetime we will see it")),
                    ("dec", dict(tdt="over the coming decades")),
                    ("atleast", dict(tdt="at least 10 years")),
                    ("decade", dict(claim="Within a decade fusion will power a city."))):
        r = deadline(rec(pid, **kw))
        check(f"NONE: {pid} gets no window, reason speaker_horizon_longer",
              r["_deadline"] is None and r["_why_none"] == "speaker_horizon_longer",
              f"{r['_deadline']} {r['_why_none']}")
    r = deadline(rec("short", tdt="at least 2 years"))
    check("NONE: 'at least 2 years' is inside the cap, so it is not refused as longer",
          r["_why_none"] != "speaker_horizon_longer", f"{r['_deadline']} {r['_why_none']}")

    print("screened BEFORE any resolver runs, from the pipeline's own claim text")
    cond = deadline(rec("cond", claim="If regulators approve it, the merger will close.", tdt="soon"))
    check("SCREEN: a conditional claim gets no window, reason conditional_claim",
          cond["_deadline"] is None and cond["_why_none"] == "conditional_claim", f"{cond['_why_none']}")
    when = deadline(rec("when", claim="Mistral's third AI model will be closed source when released."))
    check("SCREEN: 'when released' is a condition too", when["_why_none"] == "conditional_claim", str(when["_why_none"]))
    order = deadline(rec("ord", claim="A Republican woman will be elected president before a Democratic woman."))
    check("SCREEN: an ordering claim gets no window, reason ordering_claim",
          order["_deadline"] is None and order["_why_none"] == "ordering_claim", str(order["_why_none"]))
    bydate = deadline(rec("bydate", claim="Revenue will double before the end of the year."))
    check("SCREEN: 'before the end of' is a date, not an ordering, so the record keeps a window",
          bydate["_deadline"] is not None and bydate["_why_none"] is None, f"{bydate['_deadline']} {bydate['_why_none']}")
    amb = deadline(rec("amb", quote="it will come soon and eventually everyone will use it"))
    check("SCREEN: two phrase rows in one field are refused, never guessed between",
          amb["_deadline"] is None and amb["_why_none"] == "implied_ambiguous_words", str(amb["_why_none"]))
    und = deadline(rec("und", said=None, tdt="soon"))
    check("SCREEN: no statement date, no anchor", und["_deadline"] is None and und["_why_none"] == "no_statement_date",
          str(und["_why_none"]))

    print("lead from the shortest reading of the words")
    wk = deadline(rec("wk", tdt="in the coming weeks", ctrl="external"))
    f = P2.funnel_flags(wk, 60)
    check("LEAD: 'coming weeks' reads as 14 days at the shortest, under the 60-day floor",
          f["implied"]["shortest_reading_days"] == 14 and not f["lead_ok"] and not f["eligible"]
          and P2.ineligible_reason("wk", f) == "lead_under_floor", json.dumps(f))
    mo = deadline(rec("mo", tdt="in the coming months", ctrl="own", cat="company_business"))
    f = P2.funnel_flags(mo, 60)
    check("LEAD: 'coming months' reads as 61 days at the shortest, over the floor even when the speaker controls it",
          f["implied"]["shortest_reading_days"] == 61 and f["lead_ok"] and f["eligible"], json.dumps(f))
    s_own = P2.funnel_flags(deadline(rec("so", tdt="soon", ctrl="own", cat="company_business")), 60)
    s_ext = P2.funnel_flags(deadline(rec("se", tdt="soon", ctrl="external")), 60)
    check("LEAD: 'soon' has no lower bound; about the speaker's own plans it is not a lead",
          s_own["implied"]["shortest_reading_days"] is None and not s_own["lead_ok"], json.dumps(s_own))
    check("LEAD: 'soon' about something the speaker does not control is eligible",
          s_ext["lead_ok"] and s_ext["eligible"], json.dumps(s_ext))
    c_own = P2.funnel_flags(own, 60)
    check("LEAD: a class row about the speaker's own company has no words to read, so it is not a lead",
          not c_own["lead_ok"] and P2.ineligible_reason("own", c_own) == "lead_under_floor", json.dumps(c_own))
    c_ext = P2.funnel_flags(ext, 60)
    check("LEAD: a class row about another company is eligible", c_ext["eligible"], json.dumps(c_ext))
    check("LEAD: lead_days still counts statement to deadline, like every other row",
          c_ext["lead_days"] == (dt.date(2028, 1, 15) - dt.date(2025, 1, 15)).days, str(c_ext["lead_days"]))

    print("with the policy off, nothing changes")
    for r in (rec("x1", tdt="soon"), rec("x2", tdt="in the coming weeks"), rec("x3", cat="company_business", ctrl="own"),
              rec("x4", tdt="eventually"), rec("x5", tdt="in a few months")):
        off = plain(r)
        again = [json.loads(json.dumps(r))]
        P2.attach_deadlines(again, derive=True)
        check(f"OFF: {r['prediction_id']} keeps today's answer ({off['_deadline']}, {off['_why_none']}) and "
              "carries no implied field", "_implied" not in off and off["_deadline"] == again[0]["_deadline"]
              and (off["_deadline"] is None or not str(off["_basis"]).startswith("implied")),
              str(off.get("_basis")))
    check("OFF: 'in a few months' keeps the funnel's 3 months when the policy is off",
          plain(rec("x5", tdt="in a few months"))["_deadline"] == dt.date(2025, 4, 15))
    check("OFF: funnel_flags of a record with no implied window carries no implied key",
          "implied" not in P2.funnel_flags(plain(rec("x6", target="2026-12-31")), 60))

    print("half and double the windows, for the sensitivity report")
    h, d2 = deadline(rec("hs", tdt="soon"), 0.5), deadline(rec("ds", tdt="soon"), 2.0)
    check("SCALE: 'soon' at half is 6 months (183 days), at double 2 years",
          h["_deadline"] == dt.date(2025, 1, 15) + dt.timedelta(days=183) and d2["_deadline"] == dt.date(2027, 1, 15),
          f"{h['_deadline']} {d2['_deadline']}")
    hw = P2.funnel_flags(deadline(rec("hw", tdt="in the coming weeks"), 0.5), 60)
    check("SCALE: the shortest reading does not scale with the window",
          hw["implied"]["shortest_reading_days"] == 14, json.dumps(hw))
    check("SCALE: the basis names the scale", "at 0.5x" in h["_basis"] and "at 2x" in d2["_basis"],
          f"{h['_basis']} | {d2['_basis']}")
    try:
        deadline(rec("bad", tdt="soon"), 3.0)
        check("SCALE: a scale other than half, one or double is refused", False)
    except SystemExit as e:
        check("SCALE: a scale other than half, one or double is refused", "scale" in str(e), str(e))

    print("a trend record already resolved keeps its frozen trend window")
    import resolve_predictions as RP  # noqa: E402
    with tempfile.TemporaryDirectory() as td:
        corpus = pathlib.Path(td) / "predictions"
        (corpus / "ada").mkdir(parents=True)
        tr = rec("tr1", said="2021-02-01", claim="Margins will continue to go up.", cat="company_business",
                 ctrl="own", quote="margins will continue to go up")
        fresh = rec("tr2", said="2021-02-01", claim="Margins will continue to go up.", cat="company_business",
                    ctrl="external", quote="margins will continue to go up")
        (corpus / "ada" / "t1.jsonl").write_text(json.dumps(tr) + "\n" + json.dumps(fresh) + "\n")
        res = {"tr1": {"deadline": "2025-09-16", "funnel_flags": {"basis": "trend: trend over 4.6y since the statement",
                                                                  "trend": True}}}
        rows = {r["prediction_id"]: r for r in RP.select(corpus, dt.date(2026, 9, 28), 60, trend=True,
                                                         resolutions=res, implied=1.0)}
        check("GRANDFATHER: the resolved trend record keeps its first window, 2025-09-16",
              rows.get("tr1", {}).get("_deadline") == dt.date(2025, 9, 16)
              and str(rows["tr1"]["_basis"]).startswith("trend"), str(rows.get("tr1", {}).get("_basis")))
        check("GRANDFATHER: an unresolved directional record gets an implied window instead of a trend window",
              str(rows.get("tr2", {}).get("_basis", "")).startswith("implied")
              and rows["tr2"]["_deadline"] == dt.date(2024, 2, 1), str(rows.get("tr2", {}).get("_basis")))
        miss = rec("miss", said="2022-01-15", cat="technology_product", ctrl="external",
                   claim="Level 4 trucks will be deployed commercially.")
        (corpus / "ada" / "t1.jsonl").write_text(json.dumps(miss) + "\n")
        picked = [r["prediction_id"] for r in RP.select(corpus, dt.date(2026, 9, 28), 60, implied=1.0)]
        check("SYMMETRY: an implied record is selected at its deadline whatever happened, so a miss can score",
              picked == ["miss"], str(picked))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
