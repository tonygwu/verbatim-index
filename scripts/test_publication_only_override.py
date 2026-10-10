#!/usr/bin/env python3
"""A publication date is never the day of speech, whichever block carries it.

Final review of the combined branch, 2026-09-30, item 2. The dating stage turns a
`publication_only` verdict earlier than the upload into an OVERRIDE
(dating_lib.merge_one: kind is "override" whenever the date is not the transcript's
own). The override header branch never read the verdict, so a podcast episode's
publication day reached the extractor as "the day the words were spoken", and the
scorer counted every sourced_override as an exact day of speech. An exact day is
what lets an already_public report EXCLUDE a record outright; against a publication
day or a range the report proves nothing about the speech, so the record is scored
and sent to review instead (review 2026-09-30, the Buddy Media upload).

Pinned here, on records built the way production builds them:
  HEADER  a publication_only override reads "published on ... spoken on or before";
          a dated one still reads as the day of speech
  RECORD  the override block carries the verdict, and still passes the schema; an
          operator entry (no verdict) is byte-identical to before
  SCORE   sourced_override is exact only with no range and a verdict that is not
          publication_only; an exact one is excluded as already_public, the others
          are scored and reviewed

  .venv/bin/python scripts/test_publication_only_override.py
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402
import score_predictions as S  # noqa: E402
from test_predictions_release23 import ROSTER, UPLOAD, date_line, operator_entry, record, with_override  # noqa: E402

SCHEMA = L.load_record_schema()


def agent_override(date, verdict, **extra):
    """A dating-stage entry that MOVES the date earlier than the upload (an override)."""
    return {**operator_entry(date, basis="Ada on the pod (podcast" + ("; publication date)" if verdict ==
                                                                       "publication_only" else ")")),
            "confirmed_by": L.AGENT_CONFIRMATION, "earliest_evidenced": True,
            "confirmation": {"verdict": verdict, "kind": "override"}, **extra}


def built(entry, **over):
    return record(with_override(UPLOAD, entry), target_date="2015", target_date_text="by 2015", **over)


def scored_row(r, already_public="2012-05-20"):
    """The row score_predictions.join makes for r, resolved occurred with an already_public report."""
    r = copy.deepcopy(r)
    P2.attach_deadlines([r], derive=True)
    r["_flags"] = P2.funnel_flags(r, P2.MIN_LEAD_DAYS)
    res = {"prediction_id": r["prediction_id"], "outcome": "occurred", "confidence": "high", "reasoning": "r",
           "unresolvable_reason": None, "sources": [{"where": "u", "what_it_shows": "w", "date": "2013-01-01"}],
           "already_public": {"date": already_public, "where": "https://n.example.com", "what_it_shows": "agreed"}}
    pri = {"prediction_id": r["prediction_id"], "p": 0.5, "p_raw": 0.5, "clamped": False, "reference_class": "rc",
           "reasoning": "r"}
    rows, _ = S.join([r], {r["prediction_id"]: res}, {r["prediction_id"]: pri})
    return rows[0]


class Header(unittest.TestCase):
    def test_a_publication_only_override_is_not_the_day_of_speech(self):
        tr = with_override(UPLOAD, agent_override("2012-06-01", "publication_only"))
        line = date_line(L.speaker_header(tr, ROSTER))
        self.assertNotIn("the day the words were spoken", line)
        self.assertIn("published on this date", line)
        self.assertIn("spoken on this date or before it", line)
        self.assertIn("The YouTube upload date, 2019-02-27, is later", line)

    def test_a_dated_override_still_reads_as_the_day_of_speech(self):
        for entry in (agent_override("2012-05-30", "dated"), operator_entry("2012-05-30")):
            line = date_line(L.speaker_header(with_override(UPLOAD, entry), ROSTER))
            self.assertIn("Statement date: 2012-05-30 (the day the words were spoken", line)

    def test_the_template_is_pinned_by_the_release(self):
        self.assertEqual(L.load_policy_release()["release"], "predictions-2.4")   # 2.3 + the near-agreement line


class Page(unittest.TestCase):
    """The card's Said line is the third reader of the same block."""

    def test_a_publication_only_override_reads_on_or_before(self):
        import build_predictions_site as B  # noqa: PLC0415
        said = B.said_label(built(agent_override("2012-06-01", "publication_only"))["source"], "x")
        self.assertTrue(said["card"].startswith("on or before 2012-06-01"), said)
        self.assertIn("sourced publication date", said["card"])
        self.assertEqual(said["also"], "on or before 2012-06-01")

    def test_a_dated_override_still_reads_as_the_day(self):
        import build_predictions_site as B  # noqa: PLC0415
        said = B.said_label(built(operator_entry("2012-05-30"))["source"], "x")
        self.assertEqual(said, {"card": "2012-05-30 (sourced; the YouTube upload is 2019-02-27)", "also": "on 2012-05-30"})


class Record(unittest.TestCase):
    def test_the_override_block_carries_the_verdict_and_passes_the_schema(self):
        r = built(agent_override("2012-06-01", "publication_only"))
        self.assertEqual(r["source"]["statement_date_override"].get("verdict"), "publication_only")
        self.assertEqual(L.check_schema(r, SCHEMA), [])

    def test_an_operator_entry_carries_no_verdict(self):
        r = built(operator_entry("2012-05-30"))
        self.assertNotIn("verdict", r["source"]["statement_date_override"])
        self.assertEqual(L.check_schema(r, SCHEMA), [])


class Exactness(unittest.TestCase):
    def test_the_rule(self):
        exact = S.exact_statement_date
        self.assertTrue(exact(built(operator_entry("2012-05-30"))["source"]))
        self.assertTrue(exact(built(agent_override("2012-05-30", "dated"))["source"]))
        self.assertFalse(exact(built(agent_override("2012-06-01", "publication_only"))["source"]))
        self.assertFalse(exact(built(operator_entry("2012-05-30", statement_date_earliest="2012-05-28",
                                                    precision="days"))["source"]))
        self.assertTrue(exact({"statement_date_basis": "stated_in_page"}))
        self.assertFalse(exact({"statement_date_basis": "youtube_upload_date"}))
        self.assertFalse(exact({"statement_date_basis": "publication_date"}))

    def test_an_exact_sourced_override_is_excluded_as_already_public(self):
        """The sourced_override fixture: dropping it from the exact set fails here."""
        row = scored_row(built(operator_entry("2012-05-30")))
        self.assertEqual(row["not_scored_because"], "already_public")
        self.assertNotIn("already_public_review", row)

    def test_a_publication_only_override_is_scored_and_reviewed(self):
        row = scored_row(built(agent_override("2012-06-01", "publication_only")))
        self.assertTrue(row["scored"], row)
        self.assertTrue(row.get("already_public_review"), row)

    def test_a_ranged_override_is_scored_and_reviewed(self):
        row = scored_row(built(operator_entry("2012-05-30", statement_date_earliest="2012-05-28", precision="days")))
        self.assertTrue(row["scored"], row)
        self.assertTrue(row.get("already_public_review"), row)


if __name__ == "__main__":
    unittest.main()
