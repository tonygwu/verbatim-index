#!/usr/bin/env python3
"""The date-evidence tool must be right or silent, never confidently wrong.

VP-16: eleven past-due predictions target a date before their own statement date,
because the upload date stands in for the date of speech. A statement date is an
input to whether a prediction came true, so a wrong one does not lose a record,
it flips a verdict. That makes a false positive here worse than no tool.

EVERY FIXTURE BELOW IS A REAL RECORD from this corpus, quoted verbatim, including
the one that made the tool wrong. The first design let a bare year in the
description decide, and proposed 1998... correctly for Bezos, and 2014 for a live
2026 Lisa Su show whose description is a timestamped chapter list about other
guests. That case is fixture-ised here so the rule cannot drift back.

No quota, no network, no writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    return ok


# Verbatim from data/transcripts_open. upload year, title, description, slug.
REAL = {
    "bezos_1998": dict(
        leader_slug="jeff-bezos", source_id="src-pnsjkt", yt_upload_date="20190306",
        yt_title="Jeff Bezos – March 1998, earliest long speech",
        yt_description="Amazon CEO & Founder Jeff Bezos share his wisdom to us",
        text="good evening and welcome to the annual lecture on entrepreneurship"),
    "gates_pdc_1996": dict(
        leader_slug="bill-gates", source_id="thurrott-com--sfi3q", yt_upload_date="20230929",
        yt_title="Microsoft PDC 1996 Keynote with Bill Gates",
        yt_description="Microsoft CEO Bill Gates provided a keynote address at the "
                       "company's 1996 Professional Developers Conference (PDC).",
        text="a great big San Francisco welcome to the Microsoft professional developers conference"),
    "gates_ces_2006_bad_slug": dict(
        leader_slug="bill-gates", source_id="microsoftces2005-4ch1ow", yt_upload_date="20131229",
        yt_title="CES 2006 - Microsoft Keynote - Bill Gates",
        yt_description="Microsoft Keynote at the Consumer Electronics Show 2006.",
        text="welcome to the consumer electronics show"),
    # THE CASE THAT BROKE THE FIRST DESIGN. A live 2026 show whose description is
    # a timestamped chapter list. A bare-year rule read 2014 out of it.
    "lisa_su_live_2026": dict(
        leader_slug="lisa-su", source_id="tbpn-8jqi1y", yt_upload_date="20260723",
        yt_title="AMD CEO Lisa Su Live on TBPN",
        yt_description="00:07:58 Oliver Cameron discusses world models. Earlier work from "
                       "2014 is referenced throughout the conversation.",
        text="You're surrounded by journalists. Hold your position."),
    # A description year that is the prediction's TARGET, after the upload year.
    "gates_target_2028": dict(
        leader_slug="bill-gates", source_id="jay-shetty-podcast-pbrszb", yt_upload_date="20250110",
        yt_title="Bill Gates on the next decade",
        yt_description="He explains what he expects to be true by 2028.",
        text="so the thing about the next few years"),
}


def main() -> int:
    import statement_date_evidence as SDE

    print("[1] a year in the TITLE decides, because a title labels the event")
    for key, want in (("bezos_1998", 1998), ("gates_pdc_1996", 1996)):
        ev = SDE.evidence_for(REAL[key])
        check(f"{key}: verdict agreed", ev["verdict"] == "agreed", str(ev["years_seen"]))
        check(f"{key}: the year is {want}", list(ev["years_seen"]) == [want],
              str(ev["years_seen"]))
        check(f"{key}: it differs from the upload year", ev["upload_year"] != want)

    print("\n[2] a BARE year in a description decides nothing")
    ev = SDE.evidence_for(REAL["lisa_su_live_2026"])
    check("the live 2026 show is not given a 2014 statement date",
          2014 not in ev["years_seen"],
          f"got {ev['years_seen']}; a chapter list is prose, not an event label")
    check("... and it does not reach 'agreed' on description alone",
          ev["verdict"] != "agreed", str(ev))

    print("\n[3] a full date in a description DOES decide, because prose rarely has one")
    full = dict(REAL["lisa_su_live_2026"],
                yt_description="Recorded on May 9, 2019 at the annual summit.",
                yt_title="AMD CEO Lisa Su", yt_upload_date="20200101")
    ev = SDE.evidence_for(full)
    check("a month-day-year in the description is trusted",
          list(ev["years_seen"]) == [2019], str(ev["years_seen"]))

    print("\n[4] a year AFTER the upload year is impossible and is discarded")
    ev = SDE.evidence_for(REAL["gates_target_2028"])
    check("2028 is not proposed for a 2025 upload", 2028 not in ev["years_seen"],
          str(ev["years_seen"]))
    check("... and it is REPORTED as discarded rather than dropped in silence",
          any(d["year"] == 2028 for d in ev["discarded_after_upload"]),
          str(ev.get("discarded_after_upload")))

    print("\n[5] title against slug is a CONFLICT, not a coin toss")
    # Two Bill Gates CES keynotes a year apart share a slug prefix, because the
    # slug is derived and lossy. Picking one would be guessing.
    ev = SDE.evidence_for(REAL["gates_ces_2006_bad_slug"])
    check("the disagreement is reported as a conflict", ev["verdict"] == "conflict",
          str(ev["years_seen"]))
    check("... and BOTH years are shown", set(ev["years_seen"]) == {2005, 2006},
          str(ev["years_seen"]))

    print("\n[6] the transcript opening is context and never votes")
    noisy = dict(REAL["bezos_1998"],
                 text="I was vice president from January 2005 to April 2006 and then "
                      "from September 2003 I led the group")
    ev = SDE.evidence_for(noisy)
    check("biographical years in the transcript do not create a conflict",
          ev["verdict"] == "agreed" and list(ev["years_seen"]) == [1998],
          str(ev["years_seen"]))
    check("... but they are still reported as signals",
          any(s["source"] == "transcript_opening" for s in ev["signals"]),
          "context an operator may want is kept, it just does not decide")

    print("\n[7] no evidence is 'none', never a guess")
    bare = dict(leader_slug="x", source_id="abc-def", yt_upload_date="20200101",
                yt_title="A conversation", yt_description="Two people talk.",
                text="hello there")
    ev = SDE.evidence_for(bare)
    check("a record with no year anywhere gets verdict 'none'", ev["verdict"] == "none",
          str(ev))
    check("... and proposes nothing", ev["best_guess"] is None, str(ev["best_guess"]))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
