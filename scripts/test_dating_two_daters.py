#!/usr/bin/env python3
"""Fable as a second dater: the merge of two proposals (operator decision VD-11, 2026-10-01).

Each in-scope recording gets two proposals, Gemini's and Fable's. The merge
confirms a date when EITHER proposal's cited page or description check passes the
rules for that proposal, OR when both proposals independently name the same
latest day (exactly that day, not a near one) and neither contradicts the upper
bound: the agreed day is then the statement date, with confirmation method
"two_agent_agreement" and both proposal files' sha256. Two proposals confirmed by
checks on DIFFERENT days are queued as a disagreement. Synthetic records and
pages only, no quota:

  EITHER     Gemini confirms and Fable cannot date; Fable confirms and Gemini's
             page fails; both confirm the same day
  AGREE      both name the same last day with nothing confirmed: two_agent_agreement;
             one day apart is not agreement; a day after the upload is never
             agreed; a re-upload's publication date never takes part; a strong
             title year the agreed range misses is queued
  DISAGREE   two days each confirmed by its own page: queued, never one of them
  LOADER     a two-proposal entry re-verifies from BOTH proposal files; a tampered
             second file, or an entry that drops a dater, is refused

  .venv/bin/python scripts/test_dating_two_daters.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import D10, LIVEBLOG, PODCAST, checks_for, doc_for, proposal  # noqa: E402

MODELS = {"gemini": "gemini-3.8-flash-high", "fable": "claude-fable-5-1"}
LIVE = "https://liveblog.example.com/2012/05/30/ada-live"
OTHER = "https://recap.example.com/dx-day-one"
OTHER_PAGE = "<html><body><p>Posted May 29, 2012 at 4:26 pm PT: Ada opened DX</p></body></html>"
OTHER_SRC = {"url": OTHER, "publisher": "Recap", "date_on_source": "2012-05-29",
             "verbatim_excerpt": "Posted May 29, 2012 at 4:26 pm PT", "kind": "secondary"}
GONE = {"url": "https://gone.example.com/ada", "publisher": "x", "date_on_source": None,
        "verbatim_excerpt": "Ada at DX on May 30, 2012 in full", "kind": "secondary"}
PAGES = {LIVE: LIVEBLOG, OTHER: OTHER_PAGE, GONE["url"]: "<html><body>moved</body></html>"}
CANNOT = dict(verdict="cannot_date", e=None, l=None, sources=[], event=None, event_kind=None)


def dd(obj, harness, rec=D10, daters=DL.DATERS):
    return {**doc_for(obj, rec), "harness": harness, "daters": list(daters), "leads": [], "requested_model": MODELS[harness],
            "served_model": MODELS[harness]}


def merge(objs: dict, rec=D10):
    """objs: {harness: proposal}, in DATERS order; checks fetched from PAGES."""
    docs = [dd(o, h, rec, daters=list(objs)) for h, o in objs.items()]
    checks = {h: (checks_for(o, PAGES, rec) if o["sources"] else []) for h, o in objs.items()}
    return DL.merge(rec, docs, checks)


class Either(unittest.TestCase):
    def test_the_daters_are_gemini_then_fable(self):
        self.assertEqual(DL.DATERS, ("gemini", "fable"))

    def test_gemini_confirms_and_fable_cannot_date(self):
        out = merge({"gemini": proposal(), "fable": proposal(**CANNOT)})
        self.assertEqual(out["outcome"], "override", out)
        c = out["entry"]["confirmation"]
        self.assertEqual((out["entry"]["statement_date"], c["method"], c["lead"]),
                         ("2012-05-30", DL.METHOD, "gemini"))
        self.assertEqual([p["harness"] for p in c["proposals"]], ["gemini", "fable"])

    def test_fable_confirms_when_geminis_page_fails(self):
        out = merge({"gemini": proposal(sources=[GONE]), "fable": proposal()})
        self.assertEqual(out["outcome"], "override", out)
        self.assertEqual(out["entry"]["confirmation"]["lead"], "fable")
        self.assertEqual({c["proposal"] for c in out["entry"]["confirmation"]["source_checks"]}, {"fable"})

    def test_both_confirm_the_same_day(self):
        out = merge({"gemini": proposal(), "fable": proposal()})
        self.assertEqual(out["outcome"], "override", out)
        got = [(c["proposal"], c["route"]) for c in out["entry"]["confirmation"]["source_checks"]]
        self.assertEqual(got, [("gemini", "page"), ("fable", "page")])


class Agree(unittest.TestCase):
    def test_the_same_last_day_with_nothing_confirmed_is_two_agent_agreement(self):
        out = merge({"gemini": proposal(e="2012-05-28", sources=[GONE]),
                     "fable": proposal(e="2012-05-30", sources=[GONE])})
        self.assertEqual(out["outcome"], "override", out)
        e = out["entry"]
        c = e["confirmation"]
        self.assertEqual((e["statement_date"], c["method"], c["lead"]), ("2012-05-30", DL.AGREEMENT_METHOD, None))
        self.assertEqual(e["statement_date_earliest"], "2012-05-28")
        self.assertIs(e["earliest_evidenced"], False)
        self.assertEqual(c["source_checks"], [])
        self.assertEqual(e["confirmed_by"], L.AGENT_CONFIRMATION)

    def test_one_day_apart_is_not_agreement(self):
        out = merge({"gemini": proposal(sources=[GONE]),
                     "fable": proposal(e="2012-05-31", l="2012-05-31", sources=[GONE])})
        self.assertEqual(out["outcome"], "queue", out)
        self.assertEqual(out.get("by_dater"), {"gemini": "no_confirming_source", "fable": "no_confirming_source"})

    def test_a_day_after_the_upload_is_never_agreed(self):
        late = dict(e="2019-03-01", l="2019-03-01", sources=[GONE])
        out = merge({"gemini": proposal(**late), "fable": proposal(**late)})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "after_upper_bound"), out)

    def test_a_reupload_publication_date_takes_no_part(self):
        """On a recording with no title year, so only the re-upload rule can refuse it."""
        pub = dict(verdict="publication_only", e="2025-09-12", l="2025-09-12", sources=[GONE], tid="ada/pod-ep-xyz789")
        self.assertEqual(DL.strong_years(PODCAST), set())
        out = merge({"gemini": proposal(**pub, reupload="yes"), "fable": proposal(**pub, reupload="no")}, PODCAST)
        self.assertEqual(out["outcome"], "queue", out)
        self.assertEqual(out["by_dater"], {"gemini": "reupload_publication_only", "fable": "no_confirming_source"})

    def test_a_strong_title_year_the_agreed_range_misses_is_queued(self):
        other_year = dict(e="2013-05-30", l="2013-05-30", sources=[GONE])
        out = merge({"gemini": proposal(**other_year), "fable": proposal(**other_year)})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "strong_year_conflict"), out)

    def test_one_proposal_never_agrees_with_itself(self):
        out = merge({"gemini": proposal(sources=[GONE])})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "no_confirming_source"), out)


class Disagree(unittest.TestCase):
    def test_two_days_each_confirmed_by_a_page_are_queued(self):
        out = merge({"gemini": proposal(),
                     "fable": proposal(e="2012-05-29", l="2012-05-29", sources=[OTHER_SRC])})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "dater_disagreement"), out)
        self.assertIn("2012-05-30", out["detail"])
        self.assertIn("2012-05-29", out["detail"])


def write_run2(root: Path, objs: dict, rec=D10) -> tuple[Path, dict, Path]:
    (root / "transcripts_open" / rec["leader_slug"]).mkdir(parents=True)
    (root / "transcripts_open" / rec["leader_slug"] / f"{rec['source_id']}.json").write_text(json.dumps(rec))
    run = root / "predictions" / "_experiments" / "dating-two"
    docs, checks, refs = [], {}, {}
    for h, o in objs.items():
        p = run / "proposals" / rec["leader_slug"] / f"{rec['source_id']}.{h}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = dd(o, h, rec)
        p.write_text(json.dumps(doc, sort_keys=True))
        docs.append(doc)
        checks[h] = checks_for(o, PAGES, rec) if o["sources"] else []
        refs[h] = {"path": str(p.relative_to(run)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    out = DL.merge(rec, docs, checks, refs, run_rel="predictions/_experiments/dating-two")
    assert out["outcome"] == "override", out
    entry = {**out["entry"], "confirmed_at_utc": "2026-10-01T00:00:00Z"}
    path = run / "overrides.json"
    path.write_text(json.dumps({"schema_version": 1, "overrides": {f"{rec['leader_slug']}/{rec['source_id']}": entry}}))
    return path, entry, run


class Loader(unittest.TestCase):
    TID = "ada/re-upload-abc123"

    def roots(self, root):
        return [root / "transcripts_open"]

    def test_a_two_proposal_entry_reverifies_from_both_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, run = write_run2(root, {"gemini": proposal(), "fable": proposal(**CANNOT)})
            self.assertEqual(L.load_statement_date_overrides(path, self.roots(root))[self.TID]["statement_date"],
                             "2012-05-30")
            self.assertEqual([p["sha256"] is not None for p in entry["confirmation"]["proposals"]], [True, True])
            fable = run / entry["confirmation"]["proposals"][1]["path"]
            fable.write_text(fable.read_text().replace("cannot_date", "cannot_date "))
            with self.assertRaisesRegex(L.PredictionError, "sha256"):
                L.load_statement_date_overrides(path, self.roots(root))

    def test_an_agreement_entry_reverifies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, _ = write_run2(root, {"gemini": proposal(sources=[GONE]), "fable": proposal(sources=[GONE])})
            self.assertEqual(entry["confirmation"]["method"], DL.AGREEMENT_METHOD)
            self.assertEqual(L.load_statement_date_overrides(path, self.roots(root))[self.TID]["statement_date"],
                             "2012-05-30")

    def test_an_entry_that_drops_a_dater_is_refused(self):
        """With Fable's proposal gone, a disagreement could hide; the re-merge must see what the merge saw."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, _ = write_run2(root, {"gemini": proposal(), "fable": proposal(**CANNOT)})
            e = copy.deepcopy(entry)
            e["confirmation"]["proposals"] = e["confirmation"]["proposals"][:1]
            path.write_text(json.dumps({"schema_version": 1, "overrides": {self.TID: e}}))
            with self.assertRaisesRegex(L.PredictionError, "a dater's proposal is missing"):
                L.load_statement_date_overrides(path, self.roots(root))

    def test_a_proposal_file_of_another_harness_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, _ = write_run2(root, {"gemini": proposal(), "fable": proposal(**CANNOT)})
            e = copy.deepcopy(entry)
            ps = e["confirmation"]["proposals"]
            ps[0]["path"], ps[1]["path"] = ps[1]["path"], ps[0]["path"]
            ps[0]["sha256"], ps[1]["sha256"] = ps[1]["sha256"], ps[0]["sha256"]
            path.write_text(json.dumps({"schema_version": 1, "overrides": {self.TID: e}}))
            with self.assertRaisesRegex(L.PredictionError, "harness"):
                L.load_statement_date_overrides(path, self.roots(root))


if __name__ == "__main__":
    unittest.main()
