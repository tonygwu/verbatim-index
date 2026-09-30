#!/usr/bin/env python3
"""A date range across New Year gets no implied window for "this year" or "next year".

Final review of the combined branch, 2026-09-30, item 4. The coordinator decided on
2026-09-30 (review item 8) that a relative year said on a date known only as a range
of days that crosses 31 December names a different year for each end, so the funnel
derives NO deadline from it (phase2_resolvability.derived_deadline refuses with
predictions_lib.RANGE_CROSSES_NEW_YEAR). With implied windows on, attach_deadlines
then fell through to the implied table, which gave the record a window anyway:
`range_crosses_new_year` is not in IMPLIED_TABLE["no_window_refusals"]. The fix
refuses it in attach_deadlines, in code, so the table and its pinned sha256 (which
every scoring config names) do not change.

  .venv/bin/python scripts/test_new_year_range_window.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_predictions_release23 import UPLOAD, operator_entry, record, with_override  # noqa: E402
from test_implied_windows import PINNED_TABLE_SHA256  # noqa: E402


def crossing(tdt="next year", earliest="2012-12-28", said="2013-01-03", quote_words=None):
    """Said between 2012-12-28 and 2013-01-03: "next year" is 2013 from one end and 2014 from the other."""
    over = {"target_date": None, "target_date_text": tdt, "horizon": "inferable",
            "category": "technology_product", "subject_control": "external"}
    r = record(with_override(UPLOAD, operator_entry(said, statement_date_earliest=earliest,
                                                    precision=L.date_precision(earliest, said))), **over)
    if quote_words:
        r["source"]["quote"] = quote_words
    r["accepted"] = True
    return r


class NoImpliedWindow(unittest.TestCase):
    def test_the_crossing_record_gets_no_window_with_implied_on(self):
        for scale in P2.IMPLIED_SCALES:
            r = crossing()
            P2.attach_deadlines([r], derive=True, implied=scale)
            self.assertIsNone(r["_deadline"], (scale, r.get("_basis"), r.get("_implied")))
            self.assertEqual(r["_why_none"], L.RANGE_CROSSES_NEW_YEAR)
            self.assertNotIn("_implied", r)

    def test_this_year_too(self):
        r = crossing(tdt="later this year")
        P2.attach_deadlines([r], derive=True, implied=1.0)
        self.assertEqual((r["_deadline"], r["_why_none"]), (None, L.RANGE_CROSSES_NEW_YEAR))

    def test_a_phrase_row_beside_the_year_word_gets_none_either(self):
        """"soon, next year": the table would decide outright, before the funnel's reading."""
        r = crossing(tdt="soon, next year")
        P2.attach_deadlines([r], derive=True, implied=1.0)
        self.assertEqual((r["_deadline"], r["_why_none"]), (None, L.RANGE_CROSSES_NEW_YEAR))

    def test_the_refusal_is_counted(self):
        r = crossing()
        _, refusals, _ = P2.attach_deadlines([r], derive=True, implied=1.0)
        self.assertEqual(refusals.get(L.RANGE_CROSSES_NEW_YEAR), 1, dict(refusals))

    def test_implied_off_is_unchanged(self):
        r = crossing()
        P2.attach_deadlines([r], derive=True)
        self.assertEqual((r["_deadline"], r["_why_none"]), (None, L.RANGE_CROSSES_NEW_YEAR))


class Controls(unittest.TestCase):
    def test_a_range_inside_one_year_still_derives(self):
        r = crossing(earliest="2013-01-02", said="2013-01-03")
        P2.attach_deadlines([r], derive=True, implied=1.0)
        self.assertEqual(str(r["_deadline"]), "2014-12-31", r.get("_basis"))

    def test_a_crossing_record_with_no_year_word_keeps_its_implied_window(self):
        """Only a relative YEAR has two answers; "soon" from the last day is one window."""
        r = crossing(tdt="soon")
        P2.attach_deadlines([r], derive=True, implied=1.0)
        self.assertIsNotNone(r["_deadline"])
        self.assertIn("_implied", r)

    def test_the_table_hash_did_not_move(self):
        self.assertEqual(P2.implied_table_sha256(), PINNED_TABLE_SHA256)


if __name__ == "__main__":
    unittest.main()
