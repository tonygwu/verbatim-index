#!/usr/bin/env python3
"""The pundits page reports plan P5's three sensitivities, which until 2026-10-12 only results.json held.

docs/PUNDITS-PLAN.md, P5: "a leave-one-venue-out sensitivity is reported", "a
sensitivity analysis excludes archival subjects" and "The board reports era as
a covariate". aggregate.py computes all three into diagnostics
(venue_leave_one_out, archival_excluded, era_covariate), and nothing put them on
the page. build_study_site.sensitivity_section() states each one, with every
number read from results.json.

  VENUE      one line per format: recordings dropped, people falling below the
             rank floor, rank changes and the largest shift among the rest
  ARCHIVAL   the archival subject by NAME, the recordings dropped, and what the
             refitted calibration did to everyone else
  ERA        the within-person slope per year with its interval and the date span
  ESCAPING   a person's name and a venue label from the data are HTML-escaped
  ABSENT     an older results.json with none of the keys gets no section, so the
             page never shows an invented zero; an era fit that did not run says
             so instead of disappearing
  PLACE      the section follows Method

No quota, no data.

  .venv/bin/python scripts/test_pundits_sensitivity_page.py
"""
from __future__ import annotations

import copy as _copy
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SENS = {
    "venue_leave_one_out": {
        "full_board_reproduced": True, "recordings_without_venue": 0, "min_transcripts_to_rank": 5,
        "recordings_venue_disputed": 4,
        "by_venue": {
            "debate": {"recordings_dropped": 4, "people_with_venue": 3, "people_still_ranked": 9,
                       "people_below_floor": ["bo"], "people_changing_rank": 0, "rank_correlation": 1.0,
                       "max_abs_shift": 0.6, "max_shift_slug": "ada", "mean_abs_shift": 0.09},
            "talk<i>": {"recordings_dropped": 27, "people_with_venue": 6, "people_still_ranked": 7,
                        "people_below_floor": ["ada", "bo", "cy"], "people_changing_rank": 2,
                        "rank_correlation": 0.964, "max_abs_shift": 2.8, "max_shift_slug": "bo",
                        "mean_abs_shift": 0.91}}},
    "archival_excluded": {"computed": True, "excluded": ["ada"], "recordings_excluded": 5,
                          "calibration_refit": True, "people_ranked": 9, "people_changing_rank": 0,
                          "rank_correlation": 1.0, "max_abs_shift": 0.0, "max_shift_slug": "bo",
                          "mean_abs_shift": 0.0},
    "era_covariate": {"computed": True, "applied": False, "recordings_without_date": [],
                      "people_without_spread": [], "recordings_by_year": {"2022": 5, "2026": 72},
                      "first_upload": "2022-02-04", "last_upload": "2026-08-18", "slope_per_year": 0.63,
                      "ci95": [-1.78, 2.63], "resamples": 20000, "seed": 1, "resample_unit": "person",
                      "recordings_used": 77, "people_used": 10},
}


def main() -> int:
    print("pundits page: P5 sensitivities")
    tss = load("tss_sens", REPO / "scripts" / "test_study_site.py")
    import build_study_site as B
    if not hasattr(B, "sensitivity_section"):
        check("build_study_site.sensitivity_section exists", False)
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    res = tss.results()
    res["diagnostics"].update(_copy.deepcopy(SENS))
    page = B.render(res, tss.profile(), tss.copy(), rundate="12 October 2026")
    sec = page[page.find('id="sensitivity"'):]

    print("\n[VENUE]")
    check("the section exists", 'id="sensitivity"' in page)
    check("it says no published score changes", "These checks change no published score." in sec)
    check("debate: recordings dropped, one person below the floor",
          "Without the 4 debate recordings, 1 person falls below the 5-recording floor." in sec, sec[:600])
    check("debate: no rank changes and the largest shift among the rest",
          "Among the 9 still ranked, 0 change rank, and the largest score shift is 0.6 points." in sec, sec[:600])
    check("the other venue: three people, plural",
          "Without the 27 talk&lt;i&gt; recordings, 3 people fall below the 5-recording floor." in sec, sec[:900])

    check("recordings whose format the judges disputed are said to stay in every run",
          "The 4 recordings whose format the judges disputed stay in every run." in sec, sec[:1200])

    print("\n[ARCHIVAL]")
    check("the archival subject is named, escaped, with the recordings dropped",
          "Without Ada &lt;script&gt;alert(1)&lt;/script&gt; Lovelace, the archival subject (5 recordings), "
          "with calibration refitted on everyone else: 0 of the other 9 ranked people change rank, and the "
          "largest score shift is 0.0 points." in sec, sec[:1500])

    print("\n[ERA]")
    check("the within-person slope per year, its interval and the date span",
          "Upload date: within the same person, a recording uploaded one year later scores +0.6 points "
          "(95% interval -1.8 to +2.6), over 77 recordings uploaded 2022-02-04 to 2026-08-18." in sec, sec[-700:])

    print("\n[ESCAPING]")
    check("no raw markup from the data reaches the section", "<script>" not in sec and "talk<i>" not in sec)

    print("\n[ABSENT]")
    bare = B.render(tss.results(), tss.profile(), tss.copy(), rundate="12 October 2026")
    check("no keys: no section", 'id="sensitivity"' not in bare)
    res2 = tss.results()
    res2["diagnostics"]["era_covariate"] = {"computed": False, "why": "aggregate.py ran without --transcripts"}
    page2 = B.render(res2, tss.profile(), tss.copy(), rundate="12 October 2026")
    check("an era fit that did not run says so, and leaks no internal reason",
          "Upload date: not measured for this build." in page2 and "--transcripts" not in page2)
    res3 = tss.results()
    res3["diagnostics"]["era_covariate"] = dict(SENS["era_covariate"], recordings_without_date=["ada/x", "bo/y"])
    page3 = B.render(res3, tss.profile(), tss.copy(), rundate="12 October 2026")
    check("undated recordings are counted on the page", "2 recordings have no upload date and are left out." in page3)

    print("\n[PLACE]")
    check("the section follows Method", page.find("<h2>Method</h2>") < page.find('id="sensitivity"'))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
