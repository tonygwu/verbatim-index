#!/usr/bin/env python3
"""The dating stage: one agent proposes when a recording was made, a script checks the page.

Why this exists (rescue round 4, operator decision VD-8 (c), 2026-09-29). No stage
ever tried to find out when a recording was made: code copied the upload date, or
nothing, into the date the card prints as "Said". The fix is one agent that names
the event and its date range with sources, and a script with no model that must
find each cited excerpt on the fetched page, with a date inside the agent's range.
The recording's own page never counts. These tests pin the rules with synthetic
recordings and pages, and spend nothing:

  DATES    dates in text, with the time zone rule: a speech keeps its local date,
           a publication is read in UTC
  OWN      the recording's own video page, its channel, the transcript's url and
           a Wayback copy of any of them are refused before any fetch
  CHECK    an excerpt must be on the page and show a date inside the range
  MERGE    exact day; a range; cannot_date queued; after the upper bound queued
           (the Singju "Sep 13" against a Sep 12 upload); a strong title year the
           range misses queued; a check on the own date; transcript evidence found
  LOADER   an agent entry re-verifies from its stored proposal and windows; a
           tampered proposal, window or version is refused; the operator's
           Andreessen-shaped entry still loads unchanged
  LEADS    only sentences that name a date, with claim and outcome text removed
  PROMPT   opening, closing and dated passages only, with the cap reported

  .venv/bin/python scripts/test_dating.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402

WORDS = " ".join(f"w{i}" for i in range(2000))
D10 = {"leader_slug": "ada", "source_id": "re-upload-abc123", "video_id": "vid0000000A",
       "url": "https://www.youtube.com/watch?v=vid0000000A", "yt_upload_date": "20190227",
       "yt_title": "Ada interview at DX - Digital Conference 2012 (Full Video)", "yt_channel": "Re Uploads",
       "yt_description": "The tenth DX conference.", "declared_venue": "Re Uploads", "declared_kind": "interview",
       "word_count": 2010, "duration_sec": 3000,
       "text": "[00:00:01] welcome to the tenth DX conference here at the resort " + WORDS + " thank you all"}
PODCAST = {"leader_slug": "ada", "source_id": "pod-ep-xyz789", "video_id": "vid0000000B",
           "url": "https://www.youtube.com/watch?v=vid0000000B", "yt_upload_date": "20250912",
           "yt_title": "Ada on the pod", "yt_channel": "The Pod", "yt_description": "", "declared_kind": "podcast",
           "word_count": 2000, "duration_sec": 3600, "text": "[00:00:01] welcome back " + WORDS}
LIVEBLOG = ("<html><head><title>Ada live at DX</title><script>var x = 1;</script></head><body>"
            "<p>Posted May 30, 2012 at 4:26 pm PT by a reporter</p><p>Ada takes the stage at the resort.</p>"
            "</body></html>")
SCHEDULE = ("<html><body><h1>Summit 2025</h1><p>The summit runs September 7-9, 2025 in Los Angeles.</p>"
            "</body></html>")


def proposal(verdict="dated", e="2012-05-30", l="2012-05-30", sources=None, tid="ada/re-upload-abc123", **over):
    obj = {"transcript_id": tid, "verdict": verdict, "event": "DX 2012, Ada session", "event_kind": "interview",
           "speech_date_earliest": e, "speech_date_latest": l,
           "sources": sources if sources is not None else [
               {"url": "https://liveblog.example.com/2012/05/30/ada-live", "publisher": "Liveblog",
                "date_on_source": "2012-05-30", "verbatim_excerpt": "Posted May 30, 2012 at 4:26 pm PT",
                "kind": "primary"}],
           "transcript_evidence": None, "reupload": "yes", "reasoning": "The liveblog is dated."}
    obj.update(over)
    return obj


def doc_for(obj, rec=D10):
    own, basis = L.own_statement_date(rec)
    return {"schema_version": 1, "transcript_id": obj["transcript_id"], "harness": "gemini",
            "requested_model": "gemini-3.8-flash-high", "served_model": "gemini-3.8-flash-high",
            "served_model_verified": True, "identity": "a@example.com", "own_date": own, "own_basis": basis,
            "prompt_sha256": "p" * 64, "proposal": obj}


def page_check(src, html, rec=D10, verdict="dated", via="direct"):
    return DL.check_source(src, rec, {"status": 200, "final_url": src["url"], "body": html.encode(), "via": via,
                                      "error": None})


def checks_for(obj, pages, rec=D10):
    out = []
    for s in obj["sources"]:
        reason = DL.own_page_reason(s["url"], rec)
        out.append(DL.refused_check(s, reason) if reason else page_check(s, pages[s["url"]], rec))
    return out


class Dates(unittest.TestCase):
    def test_forms(self):
        got = [(d["lo"], d["hi"]) for d in DL.dates_in_text("On May 30, 2012; 7 June 2013; 2014-02-03; "
                                                              "September 7-9, 2025; in August 2023.")]
        self.assertEqual(got, [(date(2012, 5, 30),) * 2, (date(2013, 6, 7),) * 2, (date(2014, 2, 3),) * 2,
                               (date(2025, 9, 7), date(2025, 9, 9)), (date(2023, 8, 1), date(2023, 8, 31))])

    def test_a_speech_keeps_its_local_date(self):
        """Critique 3 C2: 'May 30, 2012 at 9:30 pm PT' is May 31 in UTC, and a speech is dated where it happened."""
        d = DL.dates_in_text("May 30, 2012 at 9:30 pm PT")[0]
        self.assertEqual(DL.date_for_verdict(d, "dated"), (date(2012, 5, 30), date(2012, 5, 30)))
        self.assertEqual(DL.date_for_verdict(d, "publication_only"), (date(2012, 5, 31), date(2012, 5, 31)))

    def test_a_publication_is_read_in_utc(self):
        d = DL.dates_in_text("datePublished 2025-09-18T01:30:00+02:00")[0]
        self.assertEqual(DL.date_for_verdict(d, "publication_only"), (date(2025, 9, 17), date(2025, 9, 17)))
        self.assertEqual(DL.date_for_verdict(d, "dated"), (date(2025, 9, 18), date(2025, 9, 18)))

    def test_a_bare_year_or_a_month_without_a_year_is_not_a_date(self):
        self.assertEqual(DL.dates_in_text("in 2012 and on Sep 13 and in May"), [])


class OwnPage(unittest.TestCase):
    def test_refusals(self):
        for url in ("https://www.youtube.com/watch?v=vid0000000A", "https://youtu.be/vid0000000A",
                    "https://www.youtube.com/@ReUploads", "https://www.youtube.com/channel/UCabc",
                    "http://web.archive.org/web/2019id_/https://www.youtube.com/watch?v=vid0000000A",
                    "https://m.youtube.com/watch?v=someOtherVid"):
            self.assertIsNotNone(DL.own_page_reason(url, D10), url)
        self.assertIsNone(DL.own_page_reason("https://liveblog.example.com/2012/05/30/ada-live", D10))
        web = {**D10, "url": "https://ir.example.com/letters/2025", "video_id": None}
        self.assertIsNotNone(DL.own_page_reason("https://ir.example.com/letters/2025/", web))
        hs = {**D10, "url": "https://podcasts.happyscribe.com/the-pod/ep-12", "video_id": None}
        self.assertIsNotNone(DL.own_page_reason("https://podcasts.happyscribe.com/the-pod/ep-13", hs))
        self.assertIsNone(DL.own_page_reason("https://podcasts.happyscribe.com/other-show/ep-1", hs))

    def test_own_video_page_never_confirms_even_with_a_matching_excerpt(self):
        """Critique 3 C2: the most common error, the re-upload's own page, must not confirm its own date."""
        src = {"url": "https://www.youtube.com/watch?v=vid0000000A", "publisher": "YouTube",
               "date_on_source": "2019-02-27", "verbatim_excerpt": "Uploaded on Feb 27, 2019 by Re Uploads",
               "kind": "secondary"}
        obj = proposal(verdict="publication_only", e="2019-02-27", l="2019-02-27", sources=[src])
        chk = checks_for(obj, {}, D10)
        self.assertFalse(chk[0]["fetched"])
        self.assertIn("recording's own video id", chk[0]["refused"])
        out = DL.merge_one(D10, doc_for(obj), chk)
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "no_confirming_source"))


class Check(unittest.TestCase):
    SRC = proposal()["sources"][0]

    def test_excerpt_on_the_page_with_a_date_in_range_confirms(self):
        c = page_check(self.SRC, LIVEBLOG)
        self.assertTrue(c["excerpt_found"])
        self.assertEqual(c["page_sha256"], hashlib.sha256(LIVEBLOG.encode()).hexdigest())
        self.assertIn("Posted May 30, 2012 at 4:26 pm PT", c["window"])
        self.assertLess(len(c["window"]), 2 * DL.WINDOW_CHARS + 200)
        self.assertTrue(DL.confirms(c, proposal(), D10)[0])

    def test_excerpt_not_on_the_page_is_refused(self):
        c = page_check({**self.SRC, "verbatim_excerpt": "Posted May 31, 2012 at 4:26 pm PT"}, LIVEBLOG)
        self.assertFalse(c["excerpt_found"])
        ok, why = DL.confirms(c, proposal(), D10)
        self.assertFalse(ok)
        self.assertIn("not on the page", why)

    def test_excerpt_date_outside_the_range_is_refused(self):
        c = page_check(self.SRC, LIVEBLOG)
        ok, why = DL.confirms(c, proposal(e="2012-06-01", l="2012-06-02"), D10)
        self.assertFalse(ok)
        self.assertIn("outside", why)

    def test_a_range_given_in_utc_for_an_evening_speech_is_refused(self):
        """The time zone rule bites: the agent must date a speech where it happened."""
        blog = LIVEBLOG.replace("4:26 pm PT", "9:30 pm PT")
        c = page_check({**self.SRC, "verbatim_excerpt": "Posted May 30, 2012 at 9:30 pm PT"}, blog)
        self.assertFalse(DL.confirms(c, proposal(e="2012-05-31", l="2012-05-31"), D10)[0])
        self.assertTrue(DL.confirms(c, proposal(e="2012-05-30", l="2012-05-30"), D10)[0])

    def test_an_excerpt_must_be_at_least_four_words(self):
        c = page_check({**self.SRC, "verbatim_excerpt": "May 30, 2012"}, LIVEBLOG)
        ok, why = DL.confirms(c, proposal(), D10)
        self.assertFalse(ok)
        self.assertIn("words", why)

    def test_a_failed_fetch_never_confirms(self):
        c = DL.check_source(self.SRC, D10, {"status": 403, "final_url": self.SRC["url"], "body": b"", "via": "direct",
                                            "error": "HTTP 403"})
        self.assertFalse(c["fetched"])
        self.assertFalse(DL.confirms(c, proposal(), D10)[0])


class Merge(unittest.TestCase):
    PAGES = {"https://liveblog.example.com/2012/05/30/ada-live": LIVEBLOG}

    def test_exact_day_becomes_an_override(self):
        obj = proposal()
        out = DL.merge_one(D10, doc_for(obj), checks_for(obj, self.PAGES))
        self.assertEqual(out["outcome"], "override")
        e = out["entry"]
        self.assertEqual((e["statement_date"], e["confirmed_by"]), ("2012-05-30", L.AGENT_CONFIRMATION))
        self.assertNotIn("statement_date_earliest", e)
        self.assertEqual(e["verbatim_evidence"], "Posted May 30, 2012 at 4:26 pm PT")
        self.assertEqual(e["confirmation"]["range"], ["2012-05-30", "2012-05-30"])
        self.assertEqual(e["confirmation"]["merge_version"], DL.MERGE_VERSION)
        self.assertEqual(L.check_override_entry("ada/re-upload-abc123", {**e, "confirmed_at_utc": "2026-09-30T00:00:00Z"})
                         ["statement_date"], "2012-05-30")

    def test_a_range_takes_the_latest_day_and_records_the_first(self):
        src = {"url": "https://summit.example.com/2025", "publisher": "Summit", "date_on_source": None,
               "verbatim_excerpt": "The summit runs September 7-9, 2025 in Los Angeles", "kind": "primary"}
        obj = proposal(e="2025-09-07", l="2025-09-09", sources=[src], tid="ada/pod-ep-xyz789")
        out = DL.merge_one(PODCAST, doc_for(obj, PODCAST), checks_for(obj, {src["url"]: SCHEDULE}, PODCAST))
        self.assertEqual(out["outcome"], "override", out)
        e = out["entry"]
        self.assertEqual((e["statement_date"], e["statement_date_earliest"], e["precision"], e["earliest_evidenced"]),
                         ("2025-09-09", "2025-09-07", "days", True))

    def test_cannot_date_is_queued_never_written(self):
        obj = proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None, event_kind=None)
        out = DL.merge_one(D10, doc_for(obj), [])
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "cannot_date"))

    def test_after_the_upper_bound_is_queued(self):
        """Design 1.5 rule 5, A9: a transcript site's 'Sep 13, 2025' for a video uploaded 2025-09-12."""
        src = {"url": "https://transcripts.example.com/ada-pod", "publisher": "Transcripts",
               "date_on_source": "2025-09-13", "verbatim_excerpt": "Published on Sep 13, 2025 by staff",
               "kind": "secondary"}
        page = "<html><body><p>Published on Sep 13, 2025 by staff</p></body></html>"
        obj = proposal(verdict="publication_only", e="2025-09-13", l="2025-09-13", sources=[src], tid="ada/pod-ep-xyz789")
        out = DL.merge_one(PODCAST, doc_for(obj, PODCAST), checks_for(obj, {src["url"]: page}, PODCAST))
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "after_upper_bound"))
        self.assertIn("2025-09-12", out["detail"])

    def test_a_strong_title_year_the_range_misses_is_queued(self):
        obj = proposal(e="2013-05-30", l="2013-05-30", sources=[{**proposal()["sources"][0],
                       "verbatim_excerpt": "Posted May 30, 2013 at 4:26 pm PT"}])
        page = LIVEBLOG.replace("2012", "2013")
        out = DL.merge_one(D10, doc_for(obj), checks_for(obj, {obj["sources"][0]["url"]: page}))
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "strong_year_conflict"))

    def test_on_the_own_date_it_is_a_check_with_an_honest_first_day(self):
        src = {"url": "https://thepod.example.com/episodes/ada", "publisher": "The Pod", "date_on_source": "2025-09-12",
               "verbatim_excerpt": "Episode released September 12, 2025 in full", "kind": "primary"}
        page = "<html><body><p>Episode released September 12, 2025 in full</p></body></html>"
        obj = proposal(verdict="publication_only", e="2025-09-10", l="2025-09-12", sources=[src], tid="ada/pod-ep-xyz789")
        out = DL.merge_one(PODCAST, doc_for(obj, PODCAST), checks_for(obj, {src["url"]: page}, PODCAST))
        self.assertEqual(out["outcome"], "override", out)
        e = out["entry"]
        self.assertEqual((e["statement_date"], e["earliest_evidenced"]), ("2025-09-12", False))
        rec = L.apply_statement_date_override(copy.deepcopy(PODCAST), {"ada/pod-ep-xyz789": {**e,
                                              "confirmed_at_utc": "2026-09-30T00:00:00Z"}})
        line = [x for x in L.speaker_header(rec, None).splitlines() if x.startswith("Statement date")][0]
        self.assertIn("YouTube upload date. A dating check found no earlier event", line)
        self.assertIn("no source confirms it", line)

    def test_transcript_evidence_must_be_in_the_transcript(self):
        obj = proposal(transcript_evidence="welcome to the tenth DX conference here")
        self.assertEqual(DL.merge_one(D10, doc_for(obj), checks_for(obj, self.PAGES))["outcome"], "override")
        obj = proposal(transcript_evidence="welcome to the eleventh DX conference here")
        out = DL.merge_one(D10, doc_for(obj), checks_for(obj, self.PAGES))
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "transcript_evidence_not_found"))

    def test_an_invalid_proposal_is_queued_with_its_errors(self):
        obj = proposal(e="2012-06-01", l="2012-05-30")
        out = DL.merge_one(D10, doc_for(obj), [])
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "invalid_proposal"))


def write_run(root: Path, rec: dict, obj: dict, pages: dict) -> tuple[Path, dict]:
    """A data root with one transcript and a dating run holding one proposal; returns the override file."""
    (root / "transcripts_open" / rec["leader_slug"]).mkdir(parents=True)
    (root / "transcripts_open" / rec["leader_slug"] / f"{rec['source_id']}.json").write_text(json.dumps(rec))
    run = root / "predictions" / "_experiments" / "dating-test"
    prop = run / "proposals" / rec["leader_slug"] / f"{rec['source_id']}.gemini.json"
    prop.parent.mkdir(parents=True)
    doc = doc_for(obj, rec)
    prop.write_text(json.dumps(doc, sort_keys=True))
    out = DL.merge_one(rec, doc, checks_for(obj, pages, rec),
                       proposal_ref={"path": str(prop.relative_to(run)), "sha256": hashlib.sha256(prop.read_bytes()).hexdigest()},
                       run_rel="predictions/_experiments/dating-test")
    assert out["outcome"] == "override", out
    entry = {**out["entry"], "confirmed_at_utc": "2026-09-30T00:00:00Z"}
    path = run / "overrides.json"
    path.write_text(json.dumps({"schema_version": 1, "overrides": {obj["transcript_id"]: entry}}))
    return path, entry


class Loader(unittest.TestCase):
    PAGES = {"https://liveblog.example.com/2012/05/30/ada-live": LIVEBLOG}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path, self.entry = write_run(self.root, D10, proposal(), self.PAGES)
        self.roots = [self.root / "transcripts_open"]

    def test_an_agent_entry_loads_and_vouches_for_itself(self):
        ov = L.load_statement_date_overrides(self.path, self.roots)
        self.assertEqual(ov["ada/re-upload-abc123"]["statement_date"], "2012-05-30")

    def rewrite(self, entry):
        self.path.write_text(json.dumps({"schema_version": 1, "overrides": {"ada/re-upload-abc123": entry}}))

    def test_a_tampered_proposal_is_refused(self):
        prop = self.path.parent / self.entry["confirmation"]["proposal"]["path"]
        prop.write_text(prop.read_text().replace("2012-05-30", "2012-05-29"))
        with self.assertRaisesRegex(L.PredictionError, "sha256"):
            L.load_statement_date_overrides(self.path, self.roots)

    def test_a_tampered_window_is_refused(self):
        e = copy.deepcopy(self.entry)
        e["confirmation"]["source_checks"][0]["window"] = "nothing here"
        self.rewrite(e)
        with self.assertRaisesRegex(L.PredictionError, "no longer confirms"):
            L.load_statement_date_overrides(self.path, self.roots)

    def test_a_moved_date_is_refused(self):
        e = copy.deepcopy(self.entry)
        e["statement_date"] = "2012-05-29"
        self.rewrite(e)
        with self.assertRaisesRegex(L.PredictionError, "re-merge"):
            L.load_statement_date_overrides(self.path, self.roots)

    def test_an_unknown_merge_version_is_refused(self):
        e = copy.deepcopy(self.entry)
        e["confirmation"]["merge_version"] = "merge-0"
        self.rewrite(e)
        with self.assertRaisesRegex(L.PredictionError, "merge_version"):
            L.load_statement_date_overrides(self.path, self.roots)

    def test_an_agent_entry_without_its_confirmation_is_refused(self):
        e = copy.deepcopy(self.entry)
        del e["confirmation"]
        self.rewrite(e)
        with self.assertRaisesRegex(L.PredictionError, "confirmation block"):
            L.load_statement_date_overrides(self.path, self.roots)

    def test_the_operator_entry_shape_still_loads(self):
        andreessen = {"statement_date": "1996-10-16", "basis": "Opening keynote", "source_url": "http://example.com/pr",
                      "verbatim_evidence": "being held October 16 through 18", "internal_evidence": "x",
                      "confidence": "high (date)", "researched_by": "agent", "confirmed_by": "operator",
                      "confirmed_at_utc": "2026-09-28T05:19:02Z", "confirmation_note": "n", "speaker_check": "s"}
        self.rewrite(andreessen)
        self.assertEqual(L.load_statement_date_overrides(self.path, self.roots)["ada/re-upload-abc123"],
                         andreessen)


class Leads(unittest.TestCase):
    def test_only_dated_sentences_without_claim_or_outcome_text(self):
        rec = {"prediction_id": "p1", "source": {"statement_date": "2019-02-27", "quote": "I think Oracle hardware will grow next year"},
               "prediction": {"normalized_claim": "Oracle hardware will grow in 2020.", "resolution_criteria": "By 2020, it grows."},
               "extraction": {"gate_notes": "Said at DX on May 30, 2012 according to the title. Oracle hardware will grow "
                                            "next year is the claim. The quote is forward looking.",
                              "statement_date_doubt": {"doubt": "recording_older_than_stated",
                                                       "evidence": "Title: DX Digital Conference 2012", "evidence_year": 2012}},
               "verification": {"notes": "This came true in 2013. Recorded in 2019 per metadata. The session was held in 2012."}}
        leads, dropped = DL.leads_from_records([rec], {"extract": {"attribution_notes": "Interview at DX in 2012 with a host."}})
        self.assertEqual(leads, ["Said at DX on May 30, 2012 according to the title.", "Title: DX Digital Conference 2012",
                                 "The session was held in 2012.", "Interview at DX in 2012 with a host."])
        self.assertEqual(dropped["claim_or_outcome_words"], 2)
        self.assertEqual(dropped["same_as_statement_date"], 1)
        self.assertEqual(dropped["no_date"], 1)


class Prompt(unittest.TestCase):
    def test_opening_closing_passages_and_the_cap(self):
        # 60 dated remarks, each 70 filler words apart, so each is its own 61-word passage.
        text = "[00:00:01] " + " ".join(f"w{i}" for i in range(1000)) + " " + \
               " ".join(f"back in 20{i % 30:02d} we did it " + " ".join(f"f{i}x{j}" for j in range(70))
                        for i in range(60)) + " " + WORDS
        rec = {**D10, "text": text}
        prompt, meta = DL.build_dating_prompt(rec, ["Said at DX on May 30, 2012."])
        self.assertIn("UPPER BOUND: 2019-02-27 (YouTube upload date)", prompt)
        self.assertIn("THE RECORDING'S OWN PAGE NEVER COUNTS", prompt)
        self.assertIn("TIME ZONE", prompt)
        self.assertIn("LEADS FROM EARLIER STAGES (unverified; use them to search, never cite them)", prompt)
        self.assertEqual(meta["passages_shown"], DL.MAX_PASSAGES)
        self.assertGreater(meta["passages_cut"], 0)
        self.assertIn(f"{meta['passages_cut']} more cut by the cap of {DL.MAX_PASSAGES}", prompt)
        self.assertLess(len(prompt.split()), 800 + 300 + DL.MAX_PASSAGES * 70 + 1500)
        self.assertNotIn("w1500 ", prompt)       # the middle of the transcript is not sent

    def test_undated_source_says_so(self):
        rec = {k: v for k, v in PODCAST.items() if k != "yt_upload_date"}
        prompt, _ = DL.build_dating_prompt(rec, [])
        self.assertIn("UPPER BOUND: none (the source carries no date)", prompt)
        self.assertIn("LEADS FROM EARLIER STAGES: none", prompt)


if __name__ == "__main__":
    unittest.main()
