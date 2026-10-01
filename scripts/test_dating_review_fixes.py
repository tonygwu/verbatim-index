#!/usr/bin/env python3
"""The review of dating/description-and-second-dater, 2026-10-01: one class per fix. No quota, no network.

Each class names the reviewer's finding it pins (probes in the review's
/private/tmp/rev-dating2-work). Synthetic records and fake agents only.

  .venv/bin/python scripts/test_dating_review_fixes.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import date_recordings as DR  # noqa: E402
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import WORDS, checks_for, proposal  # noqa: E402

# A re-upload whose TITLE names no year, so strong_year_conflict cannot rescue a wrong date.
BASE = {"leader_slug": "ada", "source_id": "reup-q1w2e3", "video_id": "vidQQQQQQQA",
        "url": "https://www.youtube.com/watch?v=vidQQQQQQQA", "yt_upload_date": "20190227",
        "yt_title": "Ada on the future of compute (full talk)", "yt_channel": "Talks Archive",
        "yt_description": "", "word_count": 2010, "duration_sec": 3000,
        "text": "[00:00:01] thank you for having me " + WORDS}
TID = "ada/reup-q1w2e3"
GONE = {"url": "https://gone.example.com/ada", "publisher": "x", "date_on_source": None,
        "verbatim_excerpt": "Ada spoke about compute in full", "kind": "secondary"}
PAGES = {GONE["url"]: "<html><body>moved</body></html>"}
MODELS = {"gemini": "gemini-3.8-flash-high", "fable": "claude-fable-5-1"}


def rec_with(desc, **over):
    return {**BASE, "yt_description": desc, **over}


def P(e, l, verdict="dated", sources=None, desc=None, reupload="unclear", event="Ada compute talk"):
    return proposal(verdict=verdict, e=e, l=l, sources=[GONE] if sources is None else sources, tid=TID,
                    event=event, reupload=reupload, description_evidence=desc)


def doc(obj, h, rec, daters, leads=()):
    own, basis = L.own_statement_date(rec)
    return {"schema_version": 1, "transcript_id": TID, "harness": h, "daters": list(daters), "leads": list(leads),
            "requested_model": MODELS[h], "served_model": MODELS[h], "served_model_verified": True,
            "identity": "a@example.com", "own_date": own, "own_basis": basis, "prompt_sha256": "p" * 64,
            "proposal": obj}


def merge(rec, objs, pages=PAGES, leads=()):
    hs = list(objs)
    docs = [doc(o, h, rec, hs, leads) for h, o in objs.items()]
    checks = {h: (checks_for(o, pages, rec) if o.get("sources") else []) for h, o in objs.items()}
    return DL.merge(rec, docs, checks)


class TierZeroNeverCrashes(unittest.TestCase):
    """Fix 4: tier0_check matched on the local day while tier0_day read the verdict's day, and built its
    fallback eagerly from found[0], so a publication_only verdict on an offset timestamp raised IndexError."""

    def test_a_publication_day_read_in_utc_confirms_without_a_crash(self):
        rec = rec_with("Recorded 2019-02-20T23:30:00-08:00 at the studio for the archive.")
        self.assertEqual(DL.tier0_day(rec, "publication_only")[0], "2019-02-21")
        out = merge(rec, {"gemini": P("2019-02-21", "2019-02-21", verdict="publication_only", reupload="no")})
        self.assertEqual(out["outcome"], "override", out)
        self.assertEqual(out["entry"]["statement_date"], "2019-02-21")
        self.assertEqual(out["entry"]["confirmation"]["source_checks"][0]["basis"], "tier0")

    def test_the_merge_stage_never_dies_on_one_transcript(self):
        from test_date_recordings import Fixture, FakeAgent, FakeWeb, LIVE_URL, run  # noqa: PLC0415
        from test_dating import LIVEBLOG  # noqa: PLC0415
        real = DL.merge

        def flaky(rec, docs, checks_by, refs=None, run_rel=None):
            if rec["source_id"] == "pod-ep-xyz789":
                raise IndexError("list index out of range")
            return real(rec, docs, checks_by, refs, run_rel)
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({"ada/re-upload-abc123": proposal(), "ada/pod-ep-xyz789": proposal(tid="ada/pod-ep-xyz789"),
                               "ada/held-ep": proposal(tid="ada/held-ep")})
            with patch.object(DR.DL, "merge", flaky):
                rc, out = run(fx.argv("--run", "--harness", "gemini"), agent, FakeWeb({LIVE_URL: LIVEBLOG}))
            self.assertEqual(rc, 1, out)
            queue = {q["transcript_id"]: q for q in json.loads((fx.run / "queue.json").read_text())["queue"]}
            self.assertEqual(queue["ada/pod-ep-xyz789"]["reason"], "merge_error")
            self.assertIn("IndexError", queue["ada/pod-ep-xyz789"]["detail"])
            ov = L.load_statement_date_overrides(fx.run / "overrides.json", [fx.data / "transcripts_open"])
            self.assertIn("ada/re-upload-abc123", ov)
            self.assertIn("merge errors: 1", out)


class DescriptionDayBeforeOwnDate(unittest.TestCase):
    """Fix 2: a description day ON the upload day gave a CHECK of the upload date (probes 1e, 1f, 2b). The day
    must be STRICTLY before the transcript's own date, on both routes. No cue word here, so only this rule bites."""

    DESC = "Ada at the archive studio, February 27, 2019, with the whole team."

    def test_a_cited_description_day_on_the_upload_day_confirms_nothing(self):
        rec = rec_with(self.DESC)
        out = merge(rec, {"gemini": P("2019-02-27", "2019-02-27", sources=[],
                                      desc="Ada at the archive studio, February 27, 2019")})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "no_confirming_source"), out)
        self.assertIn("not before", out["detail"])

    def test_tier0_skips_a_day_on_the_upload_day(self):
        rec = rec_with(self.DESC)
        day, why = DL.tier0_day(rec, "dated")
        self.assertIsNone(day)
        self.assertIn("not before", why)
        out = merge(rec, {"gemini": P("2019-02-20", "2019-02-27")})
        self.assertEqual(out["outcome"], "queue", out)

    def test_the_day_before_the_upload_still_counts(self):
        rec = rec_with(self.DESC.replace("February 27", "February 26"))
        out = merge(rec, {"gemini": P("2019-02-26", "2019-02-26", sources=[],
                                      desc="Ada at the archive studio, February 26, 2019")})
        self.assertEqual(out["outcome"], "override", out)


class CueWords(unittest.TestCase):
    """Fixes 6 and 7: a description day next to a word that dates something else is not the event's, on both
    routes: born, founded, released, premiered, streamed, launched, "originally", sponsor or promo wording, the
    next event, and any date inside a link (the reviewer's probes 1a, 1b, 1d, 2a, 2c)."""

    def refused_both_ways(self, desc, cited, day, cue):
        rec = rec_with(desc)
        d, why = DL.tier0_day(rec, "dated")
        self.assertIsNone(d, desc)
        self.assertIn(cue, why)
        c = DL.check_description(rec, P(day, day, sources=[], desc=cited))
        self.assertFalse(c["ok"], c)
        self.assertIn(cue, c["why"])

    def test_a_founding_date(self):
        self.refused_both_ways("Ada founded Compute Labs on March 3, 2004. In this talk she looks back.",
                               "Ada founded Compute Labs on March 3, 2004", "2004-03-03", "founded")

    def test_a_birth_date(self):
        self.refused_both_ways("Ada was born on March 3, 1984 in Leeds and studied there.",
                               "Ada was born on March 3, 1984 in Leeds", "1984-03-03", "born")

    def test_originally_released(self):
        self.refused_both_ways("Originally released March 9, 2018 on our old channel.",
                               "Originally released March 9, 2018 on our old channel", "2018-03-09", "Originally")

    def test_a_sponsor_deadline(self):
        self.refused_both_ways("Use code ADA20 before December 31, 2018 at shop.example.com. Thanks to our sponsor!",
                               "Use code ADA20 before December 31, 2018", "2018-12-31", "code")

    def test_the_next_event(self):
        self.refused_both_ways("Next event: Ada returns to the DX stage on May 30, 2017. Get tickets!",
                               "Ada returns to the DX stage on May 30, 2017", "2017-05-30", "Next event")

    def test_a_date_inside_a_link(self):
        rec = rec_with("Show notes: https://blog.example.com/2018-11-04-ada-episode and more.")
        d, why = DL.tier0_day(rec, "dated")
        self.assertIsNone(d)
        self.assertIn("link", why)
        out = merge(rec, {"gemini": P("2018-11-04", "2018-11-04")})
        self.assertEqual(out["outcome"], "queue", out)

    def test_a_plain_recording_day_still_counts(self):
        rec = rec_with("Recorded live in London on March 3, 2018 with a small audience.")
        self.assertEqual(DL.tier0_day(rec, "dated")[0], "2018-03-03")

    def test_a_cued_day_is_dropped_before_the_days_are_counted(self):
        rec = rec_with("Recorded in London on March 3, 2018. Originally released May 1, 2018 on our channel.")
        self.assertEqual(DL.tier0_day(rec, "dated")[0], "2018-03-03")

    def test_a_cued_day_inside_a_cited_excerpt_never_sources_the_last_day(self):
        """Only the days the check accepted feed the latest-day rule, or the release day would be confirmed."""
        rec = rec_with("Recorded in London on March 3, 2018. Originally released May 1, 2018 on our channel.")
        out = merge(rec, {"gemini": P("2018-03-03", "2018-05-01", sources=[],
                                      desc="Recorded in London on March 3, 2018. Originally released May 1, 2018")})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "latest_day_unsourced"), out)


class AgreementOnSharedInput(unittest.TestCase):
    """Fix 3: two daters that copy the same thing they were both SHOWN are not independent (probes 3a, 3b): the
    upper bound printed in both prompts, a day in the shared leads, a day in the page's own dates."""

    def test_both_naming_the_upper_bound_is_refused(self):
        out = merge(rec_with(""), {"gemini": P("2015-01-01", "2019-02-27"), "fable": P("2012-01-01", "2019-02-27")})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "agreement_on_shared_input"), out)
        self.assertIn("upper bound", out["detail"])

    def test_both_copying_a_lead_day_is_refused(self):
        lead = ["Ada spoke at the summit on June 10, 2014 according to the title."]
        out = merge(rec_with(""), {"gemini": P("2014-06-10", "2014-06-10"), "fable": P("2014-06-10", "2014-06-10")},
                    leads=lead)
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "agreement_on_shared_input"), out)
        self.assertIn("leads", out["detail"])

    def test_both_copying_a_page_date_is_refused(self):
        rec = rec_with("", page_dates={"published": "2014-06-10T09:00:00Z"})
        out = merge(rec, {"gemini": P("2014-06-10", "2014-06-10"), "fable": P("2014-06-10", "2014-06-10")})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "agreement_on_shared_input"), out)

    def test_an_agreement_on_a_day_nobody_was_shown_still_confirms(self):
        out = merge(rec_with(""), {"gemini": P("2014-06-10", "2014-06-10"), "fable": P("2014-06-01", "2014-06-10")},
                    leads=["The talk was given in 2014, before the 2019 upload."])
        self.assertEqual(out["outcome"], "override", out)
        self.assertEqual(out["entry"]["confirmation"]["method"], DL.AGREEMENT_METHOD)

    def test_a_proposal_that_does_not_record_its_leads_cannot_agree(self):
        hs = ("gemini", "fable")
        rec = rec_with("")
        docs = [doc(P("2014-06-10", "2014-06-10"), h, rec, hs) for h in hs]
        del docs[1]["leads"]
        out = DL.merge(rec, docs, {h: checks_for(P("2014-06-10", "2014-06-10"), PAGES, rec) for h in hs})
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "agreement_on_shared_input"), out)
        self.assertIn("leads", out["detail"])


if __name__ == "__main__":
    unittest.main()
