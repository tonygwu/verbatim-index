#!/usr/bin/env python3
"""A source that states its own date (stated_in_page) gets no dating CHECK (2026-10-18).

FOUND on dating-thin-supplement-20261018: 16 of its 22 recordings, earnings-call transcripts from
fool.com and q4cdn.com, carry `statement_date_basis: stated_in_page`. For
evan-spiegel/web-fool-com-e6be4392 the daters confirmed 2019-10-22, the day the page itself
states, and the merge labelled the entry a check. `predictions_lib.load_statement_date_checks`
refuses a check on any basis but an upload or publication date (CHECKABLE_BASES), so the staged
checks file failed to load and the whole run's merge died with 41 proposals on disk and nothing
written for the other 21 recordings.

A stated date already counts as exact (`score_predictions.EXACT_DATE_BASES`) and the header says
"stated in the source itself", so a same-day confirmation has nothing to promote: the merge now
queues it as `own_date_stated`, never an entry. Nor can such a source take an OVERRIDE:
`check_override_against_transcript` refuses one that contradicts a stated date (decision D9, not
taken), so the review of the first fix found an earlier confirmed day would have died the same
way at the overrides file. Any other confirmed day is queued as `stated_date_contradicted`, on
the page-confirmed path and the two-agent-agreement path alike. A same-day confirmation of a
publication or upload date is still a check, and an earlier day on one is still an override.
`select_scope` leaves stated sources out of an --ids run, counted, as the default scope does, unless
the transcript holds a held record (the verifier's doubt about the stated date, decision D9's case).

Synthetic records and pages only, no quota.
  .venv/bin/python scripts/test_dating_stated_in_page.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import D10, checks_for, proposal  # noqa: E402
from test_dating_two_daters import CANNOT, GONE, PAGES, dd  # noqa: E402

SID = "web-transcripts-abc123"
TID = f"ada/{SID}"
# A web transcript of the same DX 2012 session: no YouTube fields; the page states the date.
WEB = {**{k: v for k, v in D10.items() if not k.startswith("yt_") and k != "video_id"},
       "source_id": SID, "url": "https://transcripts.example.com/ada-dx-2012",
       "declared_title": D10["yt_title"], "source_class": "supplemental_web",
       "statement_date": "2012-05-30", "statement_date_basis": "stated_in_page"}


def merge(objs: dict, rec: dict, version: str = DL.MERGE_VERSION) -> dict:
    """{harness: proposal} in DATERS order, checks fetched from the fixture pages, under `version`'s rules."""
    docs = [dd(o, h, rec, daters=list(objs)) for h, o in objs.items()]
    checks = {h: (checks_for(o, PAGES, rec) if o["sources"] else []) for h, o in objs.items()}
    return DL.merge(rec, docs, checks, version=version)


class StatedInPage(unittest.TestCase):
    def test_the_basis_is_declared_but_not_checkable(self):
        self.assertIn("stated_in_page", L.DECLARED_DATE_BASES)
        self.assertNotIn("stated_in_page", L.CHECKABLE_BASES)
        self.assertEqual(L.own_statement_date(WEB), ("2012-05-30", "stated_in_page"))

    def test_a_same_day_page_confirmation_is_queued_not_a_check(self):
        for version in DL.MERGE_VERSIONS:
            with self.subTest(version=version):
                out = merge({"gemini": proposal(tid=TID), "fable": proposal(tid=TID, **CANNOT)}, rec=WEB,
                            version=version)
                self.assertEqual(out["outcome"], "queue", out)
                self.assertEqual(out["reason"], DL.OWN_DATE_STATED)
                self.assertIn("stated_in_page", out["detail"])
                self.assertIn("2012-05-30", out["detail"])
                self.assertEqual(out["by_dater"], {"gemini": "confirmed", "fable": "cannot_date"})
                self.assertTrue(out["checks"], "the confirming check is kept on the queue row for a person")
                self.assertNotIn("entry", out)

    def test_an_earlier_page_confirmed_day_is_queued_as_a_contradiction_not_an_override(self):
        """The loader refuses any override of a stated date, so the merge must not make one."""
        later = {**WEB, "statement_date": "2012-05-31"}
        for version in DL.MERGE_VERSIONS:
            with self.subTest(version=version):
                out = merge({"gemini": proposal(tid=TID), "fable": proposal(tid=TID, **CANNOT)}, rec=later,
                            version=version)
                self.assertEqual(out["outcome"], "queue", out)
                self.assertEqual(out["reason"], DL.STATED_DATE_CONTRADICTED)
                self.assertIn("2012-05-30", out["detail"])
                self.assertIn("2012-05-31", out["detail"])
                self.assertEqual(out["by_dater"], {"gemini": "confirmed", "fable": "cannot_date"})
                self.assertTrue(out["checks"])
        with self.assertRaises(L.PredictionError) as cm:
            L.check_override_against_transcript(TID, "2012-05-30", later)
        self.assertIn("stated_in_page", str(cm.exception))

    def test_two_agents_agreeing_on_an_earlier_day_are_queued_too(self):
        """The agreement path makes overrides as well; both daters name a day before the stated one."""
        later = {**WEB, "statement_date": "2012-05-31"}
        out = merge({"gemini": proposal(tid=TID, sources=[GONE]), "fable": proposal(tid=TID, sources=[GONE])},
                    rec=later)
        self.assertEqual(out["outcome"], "queue", out)
        self.assertEqual(out["reason"], DL.STATED_DATE_CONTRADICTED)
        self.assertEqual(out["checks"], [])
        self.assertEqual(set(out["by_dater"]), {"gemini", "fable"})

    def test_a_same_day_confirmation_of_a_publication_date_is_still_a_check(self):
        pub = {**WEB, "statement_date_basis": "publication_date"}
        out = merge({"gemini": proposal(tid=TID), "fable": proposal(tid=TID, **CANNOT)}, rec=pub)
        self.assertEqual(out["outcome"], "check", out)
        self.assertEqual(out["entry"]["confirmation"]["kind"], "check")
        self.assertEqual(out["entry"]["statement_date"], "2012-05-30")

    def test_an_earlier_day_on_a_publication_date_is_still_an_override(self):
        pub = {**WEB, "statement_date": "2012-05-31", "statement_date_basis": "publication_date"}
        out = merge({"gemini": proposal(tid=TID), "fable": proposal(tid=TID, **CANNOT)}, rec=pub)
        self.assertEqual(out["outcome"], "override", out)
        self.assertEqual(out["entry"]["statement_date"], "2012-05-30")

    def test_a_youtube_upload_day_confirmed_is_still_a_check(self):
        """With the upload day moved onto the confirmed day, a page confirming it is the ordinary check."""
        rec = {**D10, "yt_upload_date": "20120530"}
        out = merge({"gemini": proposal(), "fable": proposal(**CANNOT)}, rec=rec)
        self.assertEqual(out["outcome"], "check", out)


class IdsScope(unittest.TestCase):
    def test_an_ids_run_leaves_a_stated_source_out_and_counts_it(self):
        """--ids used to take exactly the named transcripts; a 22-id run spent 32 of 44 calls on stated dates."""
        import date_recordings as DR  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pub = {**WEB, "source_id": "web-pub-000001", "statement_date_basis": "publication_date"}
            (root / "transcripts_web" / "ada").mkdir(parents=True)
            for rec in (WEB, pub):
                (root / "transcripts_web" / "ada" / f"{rec['source_id']}.json").write_text(json.dumps(rec))
            (root / "predictions").mkdir()
            ids = root / "ids.txt"
            ids.write_text(f"ada/{WEB['source_id']}\nada/{pub['source_id']}\n")
            jobs, excluded, missing = DR.select_scope([root / "predictions"], [root / "transcripts_web"], ids, {}, None)
            self.assertEqual([j["tid"] for j in jobs], [f"ada/{pub['source_id']}"])
            self.assertEqual(dict(excluded), {DR.STATED_EXCLUSION: 1})
            self.assertEqual(DR.STATED_EXCLUSION, "stated_in_page (not dated by this stage)")
            self.assertEqual(missing, [])

    def test_a_held_stated_source_is_still_dated_under_ids(self):
        """A date_hold record is the verifier's doubt about the stated date; the default scope dates it."""
        import date_recordings as DR  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "transcripts_web" / "ada").mkdir(parents=True)
            (root / "transcripts_web" / "ada" / f"{WEB['source_id']}.json").write_text(json.dumps(WEB))
            (root / "predictions" / "ada").mkdir(parents=True)
            (root / "predictions" / "ada" / f"{WEB['source_id']}.jsonl").write_text(
                json.dumps({"prediction_id": "0" * 16, "accepted": False,
                            "date_hold": [{"check": "relative_year_mismatch"}]}) + "\n")
            ids = root / "ids.txt"
            ids.write_text(f"ada/{WEB['source_id']}\n")
            jobs, excluded, missing = DR.select_scope([root / "predictions"], [root / "transcripts_web"], ids, {}, None)
            self.assertEqual([j["tid"] for j in jobs], [TID])
            self.assertEqual(dict(excluded), {})


if __name__ == "__main__":
    unittest.main(verbosity=1)
