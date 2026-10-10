#!/usr/bin/env python3
"""merge-6: two daters whose last days are at most 7 days apart agree on the later day (ledger VD-16).

Operator decision of 2026-10-09: a date two daters agree on is promoted without a source, and so is
one where their last days are "within X days of each other", provided the date is not after the
upload. X = 7 was measured, not guessed: on the 69 production recordings of dating-merge5-20261005a/b
that a source confirmed, the 62 exact agreements all equal the source's day, and the 4 further pairs
within 7 days give a later day 1 to 6 days after it, never before; at 14 days one pair is 11 days
late. The LATER day is taken, so the statement date can err late (understating a forecast's lead)
but never early. Kept from merge-5: an agreed day that both prompts showed (the upper bound, a lead,
a page date) is not independent and does not count; a range after the upper bound is never eligible.

Also here:
  VERSION   merge-3, -4 and -5 entries re-merge under their own rules: one day apart still queues
            under merge-5, so no production entry changes meaning
  HEADER    a near agreement gets its own line in release predictions-2.4, which says the two days
            differ; "two dating agents named this day" would be false for it
  STICKY    a dating run re-merged under merge-6 keeps every entry an earlier version confirmed,
            byte for byte, so promotion never meets its own run's entries as conflicts

Synthetic records and pages only, no quota.
  .venv/bin/python scripts/test_dating_merge6.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import date_recordings as DR  # noqa: E402
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import D10, PODCAST, proposal  # noqa: E402
from test_dating_two_daters import GONE, dd, write_run2  # noqa: E402

PAIR = ("astra", "fable_web")


def near(a_last: str, f_last: str, rec=D10, version=DL.MERGE_VERSION, a_first=None, f_first=None, **over):
    """Astra and Fable (web) proposals with these last days, neither confirmed by a page."""
    objs = {"astra": proposal(e=a_first or a_last, l=a_last, sources=[GONE], tid=f"{rec['leader_slug']}/"
                              f"{rec['source_id']}", **over),
            "fable_web": proposal(e=f_first or f_last, l=f_last, sources=[GONE], tid=f"{rec['leader_slug']}/"
                                  f"{rec['source_id']}", **over)}
    docs = [{**dd(o, "gemini", rec, daters=list(PAIR)), "harness": h} for h, o in objs.items()]
    return DL.merge(rec, docs, {h: [] for h in objs}, version=version)


class Near(unittest.TestCase):
    def test_merge6_is_the_version_a_new_run_writes(self):
        self.assertEqual(DL.MERGE_VERSION, "merge-6")
        self.assertEqual(DL.MERGE_VERSIONS, ("merge-3", "merge-4", "merge-5", "merge-6"))
        self.assertEqual(DL.NEAR_AGREEMENT_DAYS, 7)

    def test_one_day_apart_agrees_on_the_later_day(self):
        out = near("2012-05-30", "2012-05-31", a_first="2012-05-28")
        self.assertEqual(out["outcome"], "override", out)
        e, c = out["entry"], out["entry"]["confirmation"]
        self.assertEqual((e["statement_date"], e["statement_date_earliest"]), ("2012-05-31", "2012-05-28"))
        self.assertEqual((c["method"], c["merge_version"], e["confirmed_by"]),
                         (DL.AGREEMENT_METHOD, "merge-6", L.AGREEMENT_CONFIRMATION))
        self.assertEqual(c["near_agreement"], {"days_apart": 1, "earlier_last_day": "2012-05-30",
                                               "last_days": {"astra": "2012-05-30", "fable_web": "2012-05-31"}})
        self.assertIs(e["earliest_evidenced"], False)
        self.assertNotIn("source_url", e)
        self.assertEqual(c["rule"], DL.AGREEMENT_RULES["merge-6"])

    def test_the_later_day_wins_whichever_dater_named_it(self):
        out = near("2012-05-31", "2012-05-30")
        self.assertEqual(out["entry"]["statement_date"], "2012-05-31", out)

    def test_seven_days_apart_agrees_and_eight_do_not(self):
        self.assertEqual(near("2012-05-23", "2012-05-30")["outcome"], "override")
        out = near("2012-05-22", "2012-05-30")
        self.assertEqual(out["outcome"], "queue", out)
        self.assertEqual(out["by_dater"], {"astra": "no_confirming_source", "fable_web": "no_confirming_source"})

    def test_an_exact_agreement_carries_no_near_agreement_field(self):
        """So its header stays the merge-5 line, which is true of it."""
        out = near("2012-05-30", "2012-05-30")
        self.assertEqual(out["outcome"], "override", out)
        self.assertNotIn("near_agreement", out["entry"]["confirmation"])

    def test_a_later_day_both_prompts_showed_does_not_count(self):
        """PODCAST's upload, 2025-09-12, is the upper bound both prompts printed."""
        out = near("2025-09-09", "2025-09-12", rec=PODCAST, reupload="no")
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "agreement_on_shared_input"), out)

    def test_a_range_after_the_upper_bound_is_never_eligible(self):
        """The operator's sanity check (no date after the upload) holds before any agreement is read."""
        out = near("2025-09-11", "2025-09-13", rec=PODCAST, reupload="no")
        self.assertEqual(out["outcome"], "queue", out)
        self.assertIn("after_upper_bound", json.dumps(out))

    def test_a_strong_title_year_the_union_misses_is_queued(self):
        out = near("2013-05-28", "2013-05-30")
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "strong_year_conflict"), out)


class Version(unittest.TestCase):
    def test_merge5_still_queues_one_day_apart(self):
        out = near("2012-05-30", "2012-05-31", version="merge-5")
        self.assertEqual(out["outcome"], "queue", out)

    def test_merge5_keeps_its_own_agreement_rule_text(self):
        out = near("2012-05-30", "2012-05-30", version="merge-5")
        self.assertEqual(out["entry"]["confirmation"]["rule"], DL.AGREEMENT_RULE)
        self.assertEqual(DL.AGREEMENT_RULES["merge-5"], DL.AGREEMENT_RULE)


class Header(unittest.TestCase):
    def line(self, entry):
        rec = {**D10, "statement_date_override": entry}
        return L.statement_date_line(rec, L.load_header_template())

    def test_a_near_agreement_says_the_two_days_differ(self):
        e = near("2012-05-30", "2012-05-31", a_first="2012-05-28")["entry"]
        text = self.line({**e, "confirmed_at_utc": "2026-10-09T00:00:00Z"})
        self.assertIn("Statement date: 2012-05-31", text)
        self.assertIn("2012-05-30 and 2012-05-31", text)
        self.assertIn("no source confirms either", text)
        self.assertNotIn("named this day", text)

    def test_an_exact_agreement_keeps_its_line(self):
        e = near("2012-05-30", "2012-05-30")["entry"]
        self.assertIn("two dating agents named this day", self.line({**e, "confirmed_at_utc": "x"}))

    def test_the_release_is_2_4(self):
        self.assertEqual(L.load_policy_release()["release"], "predictions-2.4")

    def block(self, a_last, f_last):
        e = {**near(a_last, f_last)["entry"], "confirmed_at_utc": "2026-10-09T00:00:00Z"}
        return L.override_block({**D10, "statement_date_override": e})

    def test_the_record_block_names_the_other_day_only_for_a_near_agreement(self):
        self.assertEqual(self.block("2012-05-30", "2012-05-31")["near_agreement_other_day"], "2012-05-30")
        self.assertNotIn("near_agreement_other_day", self.block("2012-05-30", "2012-05-30"))

    def test_the_card_says_the_two_days_differ(self):
        import build_predictions_site as S
        src = {"statement_date": "2012-05-31", "statement_date_basis": L.OVERRIDE_DATE_BASIS,
               "statement_date_override": self.block("2012-05-30", "2012-05-31")}
        card = S.said_label(src, "test")["card"]
        self.assertIn("within 7 days of each other, 2012-05-30 and 2012-05-31", card)
        self.assertNotIn("named this day", card)
        same = {**src, "statement_date_override": self.block("2012-05-31", "2012-05-31")}
        self.assertIn("two dating agents named this day", S.said_label(same, "test")["card"])

    def test_the_record_schema_admits_the_near_agreement_block(self):
        schema = L.load_record_schema()
        sub = schema["properties"]["source"]["properties"]["statement_date_override"]
        self.assertEqual(L.check_schema(self.block("2012-05-30", "2012-05-31"), sub, root=schema), [])
        bad = {**self.block("2012-05-30", "2012-05-31"), "near_agreement_other_day": "soon"}
        self.assertNotEqual(L.check_schema(bad, sub, root=schema), [])


class Loader(unittest.TestCase):
    def test_a_near_agreement_entry_reverifies_and_a_tampered_day_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, _ = write_run2(root, {"gemini": proposal(sources=[GONE]),
                                               "fable": proposal(e="2012-05-31", l="2012-05-31", sources=[GONE])})
            self.assertEqual(entry["confirmation"]["near_agreement"]["days_apart"], 1)
            got = L.load_statement_date_overrides(path, [root / "transcripts_open"])
            self.assertEqual(got["ada/re-upload-abc123"]["statement_date"], "2012-05-31")
            doc = json.loads(path.read_text())
            doc["overrides"]["ada/re-upload-abc123"]["statement_date"] = "2012-05-30"
            path.write_text(json.dumps(doc))
            with self.assertRaises(L.PredictionError):
                L.load_statement_date_overrides(path, [root / "transcripts_open"])


class Sticky(unittest.TestCase):
    """date_recordings.merge_keeping: a run re-merged under a newer version keeps its confirmed entries."""

    def test_an_entry_an_earlier_version_confirmed_is_kept_byte_for_byte(self):
        docs = [{**dd(proposal(sources=[GONE]), "gemini", D10, daters=list(PAIR)), "harness": h} for h in PAIR]
        old = DL.merge(D10, docs, {h: [] for h in PAIR}, version="merge-5")
        prior = {("override", "ada/re-upload-abc123"): ({k: v for k, v in old["entry"].items()}, "2026-10-05T00:00:00Z")}
        out = DR.merge_keeping(prior, "ada/re-upload-abc123", D10, docs, {h: [] for h in PAIR}, {}, None, "merge-6")
        self.assertEqual(out, old)
        self.assertEqual(out["entry"]["confirmation"]["merge_version"], "merge-5")

    def test_a_transcript_the_earlier_version_queued_is_merged_under_the_new_one(self):
        docs = [{**dd(proposal(e=d, l=d, sources=[GONE]), "gemini", D10, daters=list(PAIR)), "harness": h}
                for h, d in zip(PAIR, ("2012-05-30", "2012-05-31"))]
        out = DR.merge_keeping({}, "ada/re-upload-abc123", D10, docs, {h: [] for h in PAIR}, {}, None, "merge-6")
        self.assertEqual((out["outcome"], out["entry"]["confirmation"]["merge_version"]), ("override", "merge-6"))

    def test_a_prior_entry_its_own_version_no_longer_gives_is_merged_afresh(self):
        """A proposal file replaced since: the old entry is not kept on trust."""
        docs = [{**dd(proposal(sources=[GONE]), "gemini", D10, daters=list(PAIR)), "harness": h} for h in PAIR]
        old = DL.merge(D10, docs, {h: [] for h in PAIR}, version="merge-5")
        stale = {**old["entry"], "statement_date": "2012-05-29"}
        prior = {("override", "ada/re-upload-abc123"): (stale, "2026-10-05T00:00:00Z")}
        out = DR.merge_keeping(prior, "ada/re-upload-abc123", D10, docs, {h: [] for h in PAIR}, {}, None, "merge-6")
        self.assertEqual(out["entry"]["confirmation"]["merge_version"], "merge-6")


if __name__ == "__main__":
    unittest.main(verbosity=1)
