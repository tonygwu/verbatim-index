#!/usr/bin/env python3
"""A record's date range is read from the blocks a record may carry, by one helper.

Final review of the combined branch, 2026-09-30, item 1. `statement_bound` (the day
an already_public report must precede) and the Said line of every Phase 2 prompt
read `source.statement_date_earliest`, a key the record schema forbids
(prediction_record.schema.json: source has additionalProperties false). A real
record carries its range INSIDE `source.statement_date_override` (a sourced
correction) or `source.statement_date_check` (a dating check that confirmed the
transcript's own date). So on every real ranged record the bound silently fell
back to the LAST day, and a report published inside the range could pass as
"already public before it was said".

These fixtures are built the way production builds records: a transcript, an
override or check entry applied through predictions_lib, and make_record. Each
is asserted to pass the record schema, so a fixture can never again use a key
no real record can carry.

  .venv/bin/python scripts/test_statement_range.py
"""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
from test_predictions_release23 import UPLOAD, agent_check, operator_entry, record, with_check, with_override  # noqa: E402

SCHEMA = L.load_record_schema()
DEADLINE = dt.date(2015, 5, 30)


def ranged_override():
    """Said at D10, known only as 2012-05-28..2012-05-30, through the override path."""
    return record(with_override(UPLOAD, operator_entry("2012-05-30", statement_date_earliest="2012-05-28",
                                                       precision="days")))


def ranged_check():
    """The upload date 2019-02-27 confirmed, with the words up to a week older, through the check path."""
    return record(with_check(UPLOAD, agent_check("2019-02-27", "dated", statement_date_earliest="2019-02-20",
                                                 precision="days")))


def said_line(prompt: str) -> str:
    return next(x for x in prompt.splitlines() if x.startswith("Said on:"))


def public(date):
    return {"prediction_id": "x", "outcome": "occurred", "confidence": "high", "reasoning": "r",
            "sources": [{"what_it_shows": "s", "where": "https://e.example.com", "date": "2012-06-04"}],
            "unresolvable_reason": None, "searched": ["q one", "q two", "q three"],
            "already_public": {"date": date, "where": "https://news.example.com/deal", "what_it_shows": "reported"}}


class RealRecordsPassTheSchema(unittest.TestCase):
    def test_both_fixtures_are_records_production_could_write(self):
        for name, r in (("override", ranged_override()), ("check", ranged_check())):
            self.assertEqual(L.check_schema(r, SCHEMA), [], name)
            self.assertNotIn("statement_date_earliest", r["source"], name)


class OneHelper(unittest.TestCase):
    def test_reads_the_override_block(self):
        self.assertEqual(L.statement_date_earliest(ranged_override()), "2012-05-28")

    def test_reads_the_check_block(self):
        self.assertEqual(L.statement_date_earliest(ranged_check()), "2019-02-20")

    def test_override_first_then_check(self):
        r = ranged_override()
        r["source"]["statement_date_check"] = {"statement_date_earliest": "2001-01-01"}
        self.assertEqual(L.statement_date_earliest(r), "2012-05-28")

    def test_no_range_is_none(self):
        self.assertIsNone(L.statement_date_earliest(record(with_override(UPLOAD, operator_entry("2012-05-30")))))
        self.assertIsNone(L.statement_date_earliest(record(UPLOAD)))

    def test_a_stray_top_level_key_is_not_read(self):
        """The forbidden key is not a third place to look: no real record carries it."""
        r = record(UPLOAD)
        r["source"]["statement_date_earliest"] = "2019-01-01"
        self.assertIsNone(L.statement_date_earliest(r))


class AlreadyPublicBound(unittest.TestCase):
    def test_the_bound_is_the_first_day_of_an_override_range(self):
        r = ranged_override()
        self.assertEqual(R.statement_bound(r), "2012-05-28")
        # AllThingsD on 2012-05-29 is inside the range, so it cannot show the thing was public first.
        errs = R.validate_resolution(dict(public("2012-05-29"), prediction_id=r["prediction_id"]),
                                     r["prediction_id"], R.statement_bound(r))
        self.assertTrue(any("already_public" in e for e in errs), errs)
        ok = R.validate_resolution(dict(public("2012-05-27"), prediction_id=r["prediction_id"]),
                                   r["prediction_id"], R.statement_bound(r))
        self.assertEqual(ok, [])

    def test_the_bound_is_the_first_day_of_a_check_range(self):
        self.assertEqual(R.statement_bound(ranged_check()), "2019-02-20")

    def test_without_a_range_the_bound_is_the_statement_date(self):
        self.assertEqual(R.statement_bound(record(with_override(UPLOAD, operator_entry("2012-05-30")))), "2012-05-30")

    def test_a_malformed_first_day_in_a_block_is_refused(self):
        r = ranged_override()
        r["source"]["statement_date_override"]["statement_date_earliest"] = "May 2012"
        with self.assertRaises(ValueError) as cm:
            R.statement_bound(r)
        self.assertIn("May 2012", str(cm.exception))

    def test_the_early_stage_uses_the_same_bound(self):
        r = ranged_override()
        early = {"prediction_id": r["prediction_id"], "outcome": "still_open", "not_occurred_basis": None,
                 "confidence": "high", "sources": [], "searched": ["a", "b", "c"], "reasoning": "r",
                 "already_public": {"date": "2012-05-29", "where": "https://n.example.com", "what_it_shows": "w"}}
        errs = R.validate_early(early, r["prediction_id"], r["source"]["statement_date"], "2026-09-30",
                                earliest=R.statement_bound(r))
        self.assertTrue(any("already_public" in e for e in errs), errs)


class SaidLine(unittest.TestCase):
    def test_every_prompt_shows_an_override_range(self):
        r = ranged_override()
        for build in (lambda: R.build_resolver_prompt(r, DEADLINE, "2026-09-30"),
                      lambda: R.build_early_prompt(r, DEADLINE, "2026-09-30"),
                      lambda: R.build_prior_prompt(r, DEADLINE)):
            self.assertEqual(said_line(build()), "Said on:         between 2012-05-28 and 2012-05-30")

    def test_a_check_range_is_shown(self):
        self.assertEqual(said_line(R.build_resolver_prompt(ranged_check(), DEADLINE, "2026-09-30")),
                         "Said on:         between 2019-02-20 and 2019-02-27")

    def test_no_range_reads_as_before(self):
        r = record(with_override(UPLOAD, operator_entry("2012-05-30")))
        self.assertEqual(said_line(R.build_resolver_prompt(r, DEADLINE, "2026-09-30")), "Said on:         2012-05-30")


class NewYearUsesTheSameHelper(unittest.TestCase):
    """predictions_lib.relative_phrase_crosses_new_year reads the range the same way."""

    def crossing(self, block_path):
        rec = copy.deepcopy(UPLOAD)
        if block_path == "check":
            r = record(with_check(rec, agent_check("2019-02-27", "dated", statement_date_earliest="2018-12-28",
                                                   precision=L.date_precision("2018-12-28", "2019-02-27"))),
                       target_date="2019", target_date_text="next year")
        else:
            r = record(with_override(rec, operator_entry("2013-01-03", statement_date_earliest="2012-12-28",
                                                         precision="days")), target_date="2013",
                       target_date_text="next year")
        return r

    def test_a_check_range_across_new_year_is_named(self):
        self.assertIsNotNone(L.relative_phrase_crosses_new_year(self.crossing("check")))

    def test_an_override_range_across_new_year_is_named(self):
        self.assertIsNotNone(L.relative_phrase_crosses_new_year(self.crossing("override")))


class EvalHarnessInheritsIt(unittest.TestCase):
    """eval_prediction_cases judges already_public with R.statement_bound on the record
    with the case's own date. A range block stored on the record describes the OLD date,
    so a case that sets the statement date must not inherit it."""

    def test_a_case_date_replaces_a_stored_range(self):
        import eval_prediction_cases as E  # noqa: PLC0415
        r = E._set(ranged_check(), {"source.statement_date": "2012-05-30"})
        self.assertEqual(R.statement_bound(r), "2012-05-30")
        self.assertNotIn("statement_date_check", r["source"])

    def test_a_case_that_leaves_the_date_keeps_the_range(self):
        import eval_prediction_cases as E  # noqa: PLC0415
        self.assertEqual(R.statement_bound(E._set(ranged_check(), {})), "2019-02-20")


if __name__ == "__main__":
    unittest.main()
