#!/usr/bin/env python3
"""The operator's seven audited recordings, replayed from the evidence on disk, and production's merge-3 entries.

Reads the PRIVATE data checkout through the `data` link and fails loudly without
it: the evidence is private, so this test names only transcript ids and dates.
No model, no network:

  STORED    the gold set cases-20261004-dating replays the proposals and page checks
            the production runs stored (dating-run-20261001: Gemini and Fable;
            dating-astra-20261003: Astra) through the real merge. Under merge-3
            every one of the seven is queued, which is what production did; under
            merge-4 the expected cases confirm the right date (OP3 as a bound) and
            the controls stay queued. Two Gemini page checks were re-made by the
            gold builder because the old matcher discarded the page (see its notes).
  MERGE-3   every merge-3 entry in production's statement_date_overrides.json and
            statement_date_checks.json still loads, re-merged under merge-3, after
            merge-4 became the default (finding g)

  .venv/bin/python scripts/test_dating_operator_cases.py
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import eval_prediction_cases as E  # noqa: E402
import predictions_lib as L  # noqa: E402

DATA = L.REPO / "data"
GOLD = DATA / "predictions" / "_eval" / "cases-20261004-dating"

# Under merge-4, from the stored evidence. OP2's November 2018 is a correct bound wider than the
# truth (the description says "last November"; no stored proposal cited the TechCrunch page that
# narrows it); OP7 has no stored source for its last day; OP2/OP3 Astra and OP4 Gemini+Fable answered
# cannot_date. The controls must stay queued, which the judge reads as PASS for a negative case.
EXPECT_V4 = {
    "OP1-stored:gemini+fable:bill-gates/khosla-ventures-8bosqk": ("PASS", "2012-05-21..2012-05-21"),
    "OP1-stored:astra:bill-gates/khosla-ventures-8bosqk": ("PASS", "2012-05-21..2012-05-21"),
    "OP2-stored:gemini+fable:bill-gates/village-global-w5g4sp": ("FAIL", "2018-11-01..2018-11-30"),
    "OP2-stored:astra:bill-gates/village-global-w5g4sp": ("QUEUED", "cannot_date"),
    "OP3-stored:gemini+fable:dara-khosrowshahi/greylock-fhxo7v": ("PASS", "2021-02-02..2021-03-02; accepted as a bound"),
    "OP3-stored:astra:dara-khosrowshahi/greylock-fhxo7v": ("QUEUED", "cannot_date"),
    "OP4-stored:gemini+fable:michael-dell/citi-z30abb": ("QUEUED", "cannot_date"),
    "OP4-stored:astra:michael-dell/citi-z30abb": ("PASS", "2026-06-08..2026-06-08"),
    "OP5-stored:gemini+fable:tim-sweeney/academy-of-interactive-a-h7tgad": ("PASS", "2020-02-12..2020-02-12"),
    "OP6-stored:gemini+fable:tim-sweeney/bafta-guru-cjxc-u": ("PASS", "2019-06-12..2019-06-12"),
    "OP7-stored:gemini+fable:vlad-tenev/the-knowledge-project-po-0jbbin": ("QUEUED", "no_confirmation"),
    "CTL-i-embed-upload-day:bill-gates/khosla-ventures-8bosqk": ("PASS", "queued: no_confirming_source"),
    "CTL-iii-release-date:tim-sweeney/academy-of-interactive-a-h7tgad": ("PASS", "queued: no_confirming_source"),
    "CTL-iv-bare-date:dara-khosrowshahi/greylock-fhxo7v": ("PASS", "queued: no_confirming_source"),
}
# What production's merge-3 did with the same evidence (the queue reasons in dating-run-20261001 and
# dating-astra-20261003): nothing confirmed.
EXPECT_V3_REASON = {
    "OP1-stored:gemini+fable:bill-gates/khosla-ventures-8bosqk": "no_confirmation",
    "OP1-stored:astra:bill-gates/khosla-ventures-8bosqk": "no_confirming_source",
    "OP2-stored:gemini+fable:bill-gates/village-global-w5g4sp": "no_confirmation",
    "OP3-stored:gemini+fable:dara-khosrowshahi/greylock-fhxo7v": "no_confirmation",
    "OP4-stored:astra:michael-dell/citi-z30abb": "no_confirming_source",
    "OP5-stored:gemini+fable:tim-sweeney/academy-of-interactive-a-h7tgad": "dater_disagreement",
    "OP6-stored:gemini+fable:tim-sweeney/bafta-guru-cjxc-u": "dater_disagreement",
    "OP7-stored:gemini+fable:vlad-tenev/the-knowledge-project-po-0jbbin": "no_confirmation",
}


def need_data() -> None:
    if not (DATA / "predictions").is_dir():
        raise SystemExit(f"FAILED: {DATA} has no predictions/; link the private data checkout (ln -s <data> data). "
                         f"This test reads private evidence and cannot run without it.")
    if not (GOLD / "cases.json").is_file():
        raise SystemExit(f"FAILED: {GOLD / 'cases.json'} is missing; pull data main, which carries the gold set "
                         f"cases-20261004-dating")


class Stored(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = E.Context(DATA, GOLD)
        cls.cases = {c["id"]: c for c in json.loads((GOLD / "cases.json").read_text())["cases"]
                     if c["stage"] == "dating_stored"}

    def test_every_stored_case_is_expected(self):
        self.assertEqual(set(self.cases), set(EXPECT_V4))

    def test_merge4_confirms_the_right_dates_from_the_stored_evidence(self):
        got = {cid: E.run_dating_stored(c, self.ctx) for cid, c in self.cases.items()}
        for cid, (status, words) in EXPECT_V4.items():
            self.assertEqual(got[cid][0], status, (cid, got[cid]))
            self.assertIn(words, got[cid][1], cid)
        self.assertNotIn("HARD_FAIL", Counter(s for s, _ in got.values()))

    def test_merge3_confirmed_none_of_them(self):
        for cid, reason in EXPECT_V3_REASON.items():
            c = copy.deepcopy(self.cases[cid])
            c["input"]["merge_version"] = "merge-3"
            rec, docs, checks = E.stored_inputs(c, self.ctx)
            out = DL.merge(rec, docs, checks, version="merge-3")
            self.assertEqual((out["outcome"], out.get("reason")), ("queue", reason), cid)

    def test_the_controls_stay_queued_under_both_versions(self):
        for cid in [x for x in self.cases if x.startswith("CTL-")]:
            for v in ("merge-3", "merge-4"):
                rec, docs, checks = E.stored_inputs(self.cases[cid], self.ctx)
                self.assertEqual(DL.merge(rec, docs, checks, version=v)["outcome"], "queue", (cid, v))


class ProductionMerge3(unittest.TestCase):
    def test_every_merge3_entry_in_production_still_loads(self):
        roots = [DATA / d for d in L.TRANSCRIPT_DIRS]
        ov = L.load_statement_date_overrides(DATA / L.DATE_OVERRIDES_FILE, roots)
        ck = L.load_statement_date_checks(DATA / L.DATE_CHECKS_FILE, roots)
        versions = Counter((e.get("confirmation") or {}).get("merge_version") for e in [*ov.values(), *ck.values()])
        print(f"\nproduction entries loaded: overrides {len(ov)}, checks {len(ck)}, by merge version "
              f"{dict(sorted(versions.items(), key=str))}")
        self.assertGreater(versions["merge-3"], 0, "no merge-3 entry was exercised")
        self.assertTrue(set(versions) <= {None, *DL.MERGE_VERSIONS}, versions)


if __name__ == "__main__":
    need_data()
    unittest.main()
