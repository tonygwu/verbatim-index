#!/usr/bin/env python3
"""The recording's own description counts when it states the event's date (operator, 2026-10-01).

FOUND by the operator on 2026-10-01. The rule "the recording's own page never
counts" stopped Gemini from using the strongest evidence it had: the YouTube
description of bill-gates/techno-optimism-t3p9ko says "Bill Gates, Mehtap Ozkan,
Saturday, February 25, 2023", the upload is 2023-04-02, and Gemini answered
cannot_date, quoting that rule. The rule exists to stop an agent passing off the
UPLOAD date as the event date. It must not block a date the description STATES
about the event. These tests pin, with synthetic records and no quota:

  CITED    description_evidence is checked against the stored description as an
           excerpt is checked on a page: a normalised match, a date with its year
           inside the agent's range, never later than the upload; a pass is a
           confirming source recorded with route "description"
  TIER0    a description holding exactly one full day date with its year, on or
           before the upload, confirms an agent's range that contains that day,
           even when the agent did not cite it
  GUARDS   two different days in the description: no Tier 0; a month or a year is
           not a day; the TITLE never counts ("What Aaron Levie Saw in 2004",
           aaron-levie/hd-in-hd-podcast--u5-zt, the C1 sizing's false positive);
           a day after the upload never counts
  LOADER   a description-confirmed entry re-verifies on load from the transcript's
           stored description, and refuses when that description changed

  .venv/bin/python scripts/test_dating_description.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import WORDS, doc_for, proposal, write_run  # noqa: E402

# The stored description of bill-gates/techno-optimism-t3p9ko, its first lines verbatim.
TECHNO_DESC = ("Fireside chat with Bill Gates on The Future:  AI, Energy, Next Generation Institutions and Mentorship "
               "for Techno Optimism\nBill Gates, Mehtap Ozkan, Saturday, February 25, 2023\n\nOUTLINE:\n"
               "0:00     What gets Bill up in the morning?\n0:1:08  The most impactful tech - AI and the future "
               "implications\n")
TECHNO = {"leader_slug": "bill-gates", "source_id": "techno-optimism-t3p9ko", "video_id": "t3p9Koy98Nw",
          "url": "https://www.youtube.com/watch?v=t3p9Koy98Nw", "yt_upload_date": "20230402",
          "yt_title": "Fireside Chat with Bill Gates on The Future: AI, Energy, Next Generation Institutions and "
                      "Mentorship", "yt_channel": "Techno Optimism", "yt_description": TECHNO_DESC,
          "word_count": 2000, "duration_sec": 3900, "text": "[00:00:01] what gets you up in the morning " + WORDS}
TID = "bill-gates/techno-optimism-t3p9ko"
CITED = "Bill Gates, Mehtap Ozkan, Saturday, February 25, 2023"
# The stored title and the opening of the stored description of aaron-levie/hd-in-hd-podcast--u5-zt.
LEVIE = {"leader_slug": "aaron-levie", "source_id": "hd-in-hd-podcast--u5-zt", "video_id": "_U5-zTOl0lo",
         "url": "https://www.youtube.com/watch?v=_U5-zTOl0lo", "yt_upload_date": "20250707",
         "yt_title": "What Aaron Levie Saw in 2004 That No One Else Did — A $4.8B Enterprise Giant",
         "yt_channel": "HD in HD",
         "yt_description": "With an insatiable appetite for “what’s the new model,” Aaron Levie, Co-founder and CEO "
                           "of Box, grew up chasing ideas without hesitation.\n\nIn this episode of HD in HD, he "
                           "shares how a curious mind from early ages became his greatest strength.",
         "word_count": 2000, "duration_sec": 3900, "text": "[00:00:01] we're here in the office of Box " + WORDS}
LEVIE_TID = "aaron-levie/hd-in-hd-podcast--u5-zt"
# A cited page the script cannot confirm: nothing is fetched, so the check records a failed fetch.
UNREAD = {"url": "https://news.example.com/gates-techno", "publisher": "News", "date_on_source": None,
          "verbatim_excerpt": "Gates spoke to Techno Optimism on February 25, 2023", "kind": "secondary"}


def unread_check(src=UNREAD, rec=TECHNO):
    return DL.check_source(src, rec, {"status": 404, "final_url": src["url"], "body": b"", "via": "direct",
                                      "error": "HTTP 404"})


def techno(e="2023-02-25", l="2023-02-25", sources=None, desc=None, verdict="dated", rec_tid=TID):
    return proposal(verdict=verdict, e=e, l=l, sources=[] if sources is None else sources, tid=rec_tid,
                    event="Techno Optimism fireside chat with Bill Gates", reupload="no", description_evidence=desc)


class Schema(unittest.TestCase):
    def test_description_evidence_is_a_required_nullable_field(self):
        self.assertIn("description_evidence", DL.DATING_SCHEMA["required"])
        self.assertEqual(DL.DATING_SCHEMA["properties"]["description_evidence"]["type"], ["string", "null"])
        self.assertEqual(DL.validate_proposal(techno(desc=CITED), TID), [])

    def test_a_proposal_with_neither_a_source_nor_description_evidence_is_still_invalid(self):
        errs = DL.validate_proposal(techno(desc=None), TID)
        self.assertTrue(any("cites no source" in e for e in errs), errs)

    def test_the_prompt_lets_the_description_count_and_never_the_upload_or_premiere_date(self):
        prompt, _ = DL.build_dating_prompt(TECHNO, [], harness="gemini")
        self.assertIn('"description_evidence"', prompt)
        self.assertIn("THE DESCRIPTION", prompt)
        self.assertIn("premiered", prompt.lower())
        self.assertIn("never count", prompt)
        self.assertIn(CITED, prompt)          # the description itself is in the prompt


class Cited(unittest.TestCase):
    def test_the_techno_optimism_description_confirms_the_cited_day(self):
        obj = techno(desc=CITED)
        out = DL.merge_one(TECHNO, doc_for(obj, TECHNO), [])
        self.assertEqual(out["outcome"], "override", out)
        e = out["entry"]
        self.assertEqual(e["statement_date"], "2023-02-25")
        self.assertEqual(e["source_url"], TECHNO["url"])
        self.assertEqual(e["verbatim_evidence"], CITED)
        routes = [c["route"] for c in e["confirmation"]["source_checks"]]
        self.assertEqual(routes, ["description"])
        self.assertEqual(e["confirmation"]["source_checks"][0]["basis"], "cited")

    def test_the_match_ignores_case_and_punctuation_like_a_page_excerpt(self):
        c = DL.check_description(TECHNO, techno(desc="bill gates mehtap ozkan saturday february 25 2023"))
        self.assertTrue(c["ok"], c)

    def test_words_that_are_not_in_the_description_confirm_nothing(self):
        c = DL.check_description(TECHNO, techno(desc="Bill Gates, Mehtap Ozkan, Sunday, February 26, 2023"))
        self.assertFalse(c["ok"])
        self.assertIn("not in the description", c["why"])

    def test_a_date_outside_the_range_confirms_nothing(self):
        c = DL.check_description(TECHNO, techno(e="2023-03-01", l="2023-03-01", desc=CITED))
        self.assertFalse(c["ok"])
        self.assertIn("outside", c["why"])

    def test_a_cited_date_later_than_the_upload_never_counts(self):
        """The description is checked against the upper bound itself, not only through the merge's range rule."""
        rec = {**TECHNO, "yt_description": TECHNO_DESC + "Premiered Monday, April 3, 2023 on our channel\n"}
        c = DL.check_description(rec, techno(e="2023-04-03", l="2023-04-03",
                                             desc="Premiered Monday, April 3, 2023 on our channel"))
        self.assertFalse(c["ok"], c)
        self.assertIn("not before", c["why"])

    def test_an_excerpt_under_four_words_confirms_nothing(self):
        c = DL.check_description(TECHNO, techno(desc="February 25, 2023"))
        self.assertFalse(c["ok"])
        self.assertIn("words", c["why"])


class Tier0(unittest.TestCase):
    def test_one_day_in_the_description_confirms_an_uncited_range_ending_on_it(self):
        obj = techno(e="2023-02-20", l="2023-02-25", sources=[UNREAD])
        out = DL.merge_one(TECHNO, doc_for(obj, TECHNO), [unread_check()])
        self.assertEqual(out["outcome"], "override", out)
        e = out["entry"]
        self.assertEqual(e["statement_date"], "2023-02-25")
        self.assertEqual(e["verbatim_evidence"], CITED)
        chk = e["confirmation"]["source_checks"]
        self.assertEqual([(c["route"], c["basis"]) for c in chk], [("description", "tier0")])

    def test_a_range_that_ends_after_the_description_day_still_needs_its_last_day_sourced(self):
        obj = techno(e="2023-02-25", l="2023-04-02", sources=[UNREAD])
        out = DL.merge_one(TECHNO, doc_for(obj, TECHNO), [unread_check()])
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "latest_day_unsourced"), out)

    def test_two_different_full_dates_give_no_tier0(self):
        rec = {**TECHNO, "yt_description": "Recorded Saturday, February 25, 2023 at the Golden Horn office.\n"
                                           "Second session Sunday, March 5, 2023."}
        obj = techno(e="2023-02-20", l="2023-02-25", sources=[UNREAD])
        out = DL.merge_one(rec, doc_for(obj, rec), [unread_check(rec=rec)])
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "no_confirming_source"), out)
        self.assertIn("2 different days", out["detail"])

    def test_the_same_day_written_twice_is_one_day(self):
        rec = {**TECHNO, "yt_description": TECHNO_DESC + "Recorded 2023-02-25 in Menlo Park.\n"}
        self.assertEqual(DL.tier0_day(rec, "dated")[0], "2023-02-25")

    def test_a_month_is_not_a_day(self):
        rec = {**TECHNO, "yt_description": "We talked with Bill in February 2023 about energy."}
        self.assertIsNone(DL.tier0_day(rec, "dated")[0])
        obj = techno(e="2023-01-15", l="2023-02-01", sources=[UNREAD])
        out = DL.merge_one(rec, doc_for(obj, rec), [unread_check(rec=rec)])
        self.assertEqual(out["outcome"], "queue", out)

    def test_a_day_after_the_upload_gives_no_tier0(self):
        rec = {**TECHNO, "yt_description": "Ada at the studio on Monday, April 3, 2023 with the team"}
        day, why = DL.tier0_day(rec, "dated")
        self.assertIsNone(day)
        self.assertIn("not before", why)


class TitleNeverCounts(unittest.TestCase):
    """The C1 sizing's false positive: a year that is the SUBJECT of a title, not the event."""

    def test_the_levie_title_year_never_dates_the_recording(self):
        src = {"url": "https://box.example.com/history", "publisher": "x", "date_on_source": None,
               "verbatim_excerpt": "Box was founded in 2004 by Levie", "kind": "secondary"}
        obj = proposal(verdict="dated", e="2004-01-01", l="2004-12-31", sources=[src], tid=LEVIE_TID,
                       event="Box founding", reupload="no", description_evidence=None)
        chk = DL.check_source(src, LEVIE, {"status": 404, "final_url": src["url"], "body": b"", "via": "direct",
                                           "error": "HTTP 404"})
        out = DL.merge_one(LEVIE, doc_for(obj, LEVIE), [chk])
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "no_confirming_source"), out)
        self.assertIsNone(DL.tier0_day(LEVIE, "dated")[0])

    def test_a_full_date_in_the_title_is_not_read_either(self):
        rec = {**LEVIE, "yt_title": "Aaron Levie on Saturday, May 15, 2004: the day Box began"}
        self.assertIsNone(DL.tier0_day(rec, "dated")[0])
        obj = proposal(verdict="dated", e="2004-05-15", l="2004-05-15", sources=[], tid=LEVIE_TID,
                       event="Box founding", reupload="no",
                       description_evidence="Aaron Levie on Saturday, May 15, 2004: the day Box began")
        out = DL.merge_one(rec, doc_for(obj, rec), [])
        self.assertEqual(out["outcome"], "queue", out)
        self.assertIn("not in the description", out["detail"])


class Loader(unittest.TestCase):
    def test_a_description_entry_reverifies_and_refuses_a_changed_description(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry = write_run(root, TECHNO, techno(desc=CITED), {})
            roots = [root / "transcripts_open"]
            self.assertEqual(L.load_statement_date_overrides(path, roots)[TID]["statement_date"], "2023-02-25")
            tx = roots[0] / "bill-gates" / "techno-optimism-t3p9ko.json"
            rec = json.loads(tx.read_text())
            rec["yt_description"] = rec["yt_description"].replace("February 25", "February 26")
            tx.write_text(json.dumps(rec))
            with self.assertRaisesRegex(L.PredictionError, "no longer confirms"):
                L.load_statement_date_overrides(path, roots)

    def test_a_tier0_entry_reverifies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            obj = techno(e="2023-02-20", l="2023-02-25", sources=[UNREAD])
            path, _ = write_run(root, TECHNO, obj, {UNREAD["url"]: "<html><body>gone</body></html>"})
            got = L.load_statement_date_overrides(path, [root / "transcripts_open"])
            self.assertEqual(got[TID]["statement_date"], "2023-02-25")


if __name__ == "__main__":
    unittest.main()
