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
            "speaker_company": "Fixture Holdings", "proposal": obj}


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

        def flaky(rec, docs, checks_by, refs=None, run_rel=None, **kw):
            # **kw: the loader passes the version an entry names (merge-4, 2026-10-04).
            if rec["source_id"] == "pod-ep-xyz789":
                raise IndexError("list index out of range")
            return real(rec, docs, checks_by, refs, run_rel, **kw)
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


class AgreementLabels(unittest.TestCase):
    """Fix 1 (blocking): an agreed date had confirmed_by "agent_plus_source_check", the recording's own URL as
    source_url and a code-written sentence as verbatim_evidence, read as the day of speech by the header and the
    card, and counted as an exact date by the scorer. Now it says what it is everywhere."""

    AGREED = "two dating agents named this day; no source confirms it"

    def agreed(self, e_gemini="2014-06-10"):
        out = merge(rec_with(""), {"gemini": P(e_gemini, "2014-06-10"), "fable": P("2014-06-10", "2014-06-10")})
        self.assertEqual(out["outcome"], "override", out)
        return {**out["entry"], "confirmed_at_utc": "2026-10-01T00:00:00Z"}

    def block(self, entry):
        r = L.apply_statement_date_override(rec_with(""), {TID: entry})
        src = {"statement_date": entry["statement_date"], "statement_date_basis": L.OVERRIDE_DATE_BASIS,
               "statement_date_override": L.override_block(r)}
        return r, src

    def test_the_entry_names_no_source_and_records_the_agents_words(self):
        e = self.agreed()
        self.assertEqual(e["confirmed_by"], L.AGREEMENT_CONFIRMATION)
        self.assertNotEqual(L.AGREEMENT_CONFIRMATION, L.AGENT_CONFIRMATION)
        self.assertNotIn("source_url", e)
        self.assertNotIn("verbatim_evidence", e)
        named = e["agents_named"]
        self.assertEqual([x["agent"] for x in named], ["gemini", "fable"])
        self.assertTrue(all(x["unconfirmed"] is True for x in named))
        self.assertEqual(named[0]["event"], "Ada compute talk")
        self.assertEqual(named[0]["cited"], [{"url": GONE["url"], "verbatim_excerpt": GONE["verbatim_excerpt"]}])
        self.assertEqual(L.check_override_entry(TID, e)["statement_date"], "2014-06-10")

    def test_the_entry_shape_is_enforced(self):
        e = self.agreed()
        with self.assertRaisesRegex(L.PredictionError, "source_url"):
            L.check_override_entry(TID, {**e, "source_url": BASE["url"], "verbatim_evidence": "x"})
        with self.assertRaisesRegex(L.PredictionError, "agents_named"):
            L.check_override_entry(TID, {k: v for k, v in e.items() if k != "agents_named"})

    def test_the_header_says_so_for_a_day_and_a_range(self):
        day, _ = self.block(self.agreed())
        line = L.statement_date_line(day, L.load_header_template())
        self.assertIn(self.AGREED, line)
        self.assertNotIn("the day the words were spoken", line)
        rng, _ = self.block(self.agreed(e_gemini="2014-06-01"))
        line = L.statement_date_line(rng, L.load_header_template())
        self.assertIn(self.AGREED, line)
        self.assertIn("2014-06-01", line)

    def test_the_policy_release_pins_the_new_header(self):
        self.assertEqual(L.load_policy_release()["contracts"]["header"], L.header_contract()["contract_id"])

    def test_the_card_says_so(self):
        import build_predictions_site as B  # noqa: PLC0415
        _, src = self.block(self.agreed())
        card = B.said_label(src, TID)
        self.assertIn(self.AGREED, card["card"])
        self.assertIn(self.AGREED, card["also"])

    def test_the_scorer_never_reads_an_agreed_day_as_exact(self):
        import score_predictions as SP  # noqa: PLC0415
        _, src = self.block(self.agreed())
        self.assertNotIn("statement_date_earliest", src["statement_date_override"])
        self.assertIs(SP.exact_statement_date(src), False)

    def test_the_record_schema_accepts_the_block_and_refuses_a_mixed_one(self):
        schema = L.load_record_schema()
        sub = schema["properties"]["source"]["properties"]["statement_date_override"]
        _, src = self.block(self.agreed())
        self.assertEqual(L.check_schema(src["statement_date_override"], sub, "$", schema), [])
        mixed = {**src["statement_date_override"], "source_url": BASE["url"]}
        self.assertNotEqual(L.check_schema(mixed, sub, "$", schema), [])


class InvalidAnswers(unittest.TestCase):
    """Fix 5: a dater whose answer fails validation every time (Fable's "dated, cites no source") left the
    transcript waiting for ever, though Gemini had confirmed it (the reviewer's strand.py). The answer is stored
    as a proposal the merge reads as invalid_proposal: it neither confirms nor agrees, and the other dater's
    confirmation stands."""

    def test_a_stored_invalid_answer_lets_the_other_daters_confirmation_stand(self):
        from test_date_recordings import Fixture, FakeAgent, FakeWeb, LIVE_URL, run  # noqa: PLC0415
        from test_dating import LIVEBLOG  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            agent = FakeAgent({("gemini", "ada/re-upload-abc123"): proposal(),
                               ("fable", "ada/re-upload-abc123"): proposal(sources=[], description_evidence=None)})
            web = FakeWeb({LIVE_URL: LIVEBLOG})
            # The daters this fix was found with (VD-11); the production pair changed on 2026-10-05.
            rc, out = run(fx.argv("--run", "--ids", str(ids), "--harness", "gemini,fable"), agent, web)
            self.assertEqual(rc, 1, out)                       # the invalid answer is a failure, and named
            fable = json.loads((fx.run / "proposals" / "ada" / "re-upload-abc123.fable.json").read_text())
            self.assertTrue(any("cites no source" in e for e in fable["answer_errors"]), fable)
            ov = L.load_statement_date_overrides(fx.run / "overrides.json", [fx.data / "transcripts_open"])
            self.assertEqual(ov["ada/re-upload-abc123"]["confirmation"]["lead"], "gemini")
            n = len(agent.calls)
            rc, out = run(fx.argv("--run", "--ids", str(ids), "--harness", "gemini,fable"), agent, web)
            self.assertEqual(len(agent.calls), n, "a stored invalid answer is final; it is not re-asked")
            self.assertEqual(rc, 0, out)

    def test_an_unparseable_answer_is_stored_too(self):
        from test_date_recordings import Fixture, FakeAgent, FakeWeb, LIVE_URL, run  # noqa: PLC0415
        from test_dating import LIVEBLOG  # noqa: PLC0415

        class Garbled(FakeAgent):
            def __call__(self, harness, prompt, timeout, workdir, args, idx):
                text, tel, ident = super().__call__(harness, prompt, timeout, workdir, args, idx)
                return ("I could not find it." if harness == "fable" else text), tel, ident
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            rc, out = run(fx.argv("--run", "--ids", str(ids), "--harness", "gemini,fable"),
                          Garbled({"ada/re-upload-abc123": proposal()}), FakeWeb({LIVE_URL: LIVEBLOG}))
            ov = json.loads((fx.run / "overrides.json").read_text())["overrides"]
            self.assertIn("ada/re-upload-abc123", ov, out)

    def test_the_merge_reads_an_invalid_proposal_as_invalid(self):
        out = merge(rec_with(""), {"gemini": P("2014-06-10", "2014-06-10"),
                                   "fable": P("2014-06-10", "2014-06-10", sources=[])})
        self.assertEqual(out["outcome"], "queue", out)
        self.assertEqual(out["by_dater"]["fable"], "invalid_proposal")


class RuleR1(unittest.TestCase):
    """Fix 8, rule R1 (coordinator's decision, reversible): a confirmed dater wins only if every other dater that
    gave a usable dated proposal does not contradict it, meaning its range contains the confirmed day. The
    reviewer's probe 4a is the A9 shape: Fable's page shows the publication day, Gemini named the event's."""

    SUMMIT = ("<html><head><title>Ada keynote recap</title></head><body><p>Published September 12, 2025: "
              "Ada told the summit that compute is the bottleneck</p></body></html>")
    SRC = {"url": "https://recap.example.com/ada-summit", "publisher": "Recap", "date_on_source": "2025-09-12",
           "verbatim_excerpt": "Published September 12, 2025: Ada told the summit", "kind": "secondary"}
    REC = {**BASE, "yt_upload_date": "20250915"}

    def run_with(self, gemini):
        # The event names the summit, so the recap page names this occasion under merge-5 as well.
        return merge(self.REC, {"gemini": gemini, "fable": P("2025-09-12", "2025-09-12", sources=[self.SRC],
                                                             event="Ada at the Compute Summit")},
                     pages={**PAGES, self.SRC["url"]: self.SUMMIT})

    def test_a_usable_other_range_that_misses_the_day_queues(self):
        out = self.run_with(P("2025-09-09", "2025-09-09"))
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "dater_disagreement"), out)
        self.assertIn("2025-09-09", out["detail"])
        self.assertIn("2025-09-12", out["detail"])

    def test_an_other_range_that_contains_the_day_lets_it_stand(self):
        out = self.run_with(P("2025-09-01", "2025-09-12"))
        self.assertEqual(out["outcome"], "override", out)
        self.assertEqual(out["entry"]["statement_date"], "2025-09-12")

    def test_a_dater_that_could_not_date_or_answered_invalidly_contradicts_nothing(self):
        for gemini in (P(None, None, verdict="cannot_date", sources=[], event=None), P("2025-09-09", "2025-09-09", sources=[])):
            if gemini["verdict"] == "cannot_date":
                gemini["event_kind"] = None
            out = self.run_with(gemini)
            self.assertEqual(out["outcome"], "override", (gemini["verdict"], out))


class DaterSetMismatch(unittest.TestCase):
    """Fix 9 (the reviewer's mixed.py): a run with --harness gemini, then one with the default gemini,fable, spent
    the Fable calls and then died in the merge on the Gemini files' dater list. Now the second run refuses before
    its first call; --redo re-proposes them."""

    def test_a_proposal_from_another_dater_set_is_refused_before_any_call(self):
        from test_date_recordings import Fixture, FakeAgent, FakeWeb, LIVE_URL, run  # noqa: PLC0415
        from test_dating import LIVEBLOG  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({"ada/re-upload-abc123": proposal(), "ada/pod-ep-xyz789": proposal(tid="ada/pod-ep-xyz789"),
                               "ada/held-ep": proposal(tid="ada/held-ep")})
            web = FakeWeb({LIVE_URL: LIVEBLOG})
            rc, out = run(fx.argv("--run", "--harness", "gemini"), agent, web)
            self.assertEqual(rc, 0, out)
            n = len(agent.calls)
            with self.assertRaises(SystemExit) as cm:
                run(fx.argv("--run", "--harness", "gemini,fable"), agent, web)
            self.assertEqual(len(agent.calls), n, "no call may be spent before the refusal")
            self.assertIn("daters", str(cm.exception))
            self.assertIn("--redo", str(cm.exception))
            # 2026-10-05: the default daters (astra,fable_web) do not even use the gemini files; --redo cannot
            # replace another dater's file, so the directory is refused outright: a new run uses a new --run-dir.
            with self.assertRaises(SystemExit) as cm:
                run(fx.argv("--run", "--redo"), agent, web)
            self.assertEqual(len(agent.calls), n, "no call may be spent before the refusal")
            self.assertIn("new --run-dir", str(cm.exception))
            rc, out = run(fx.argv("--run", "--redo", "--harness", "gemini,fable"), agent, web)
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(agent.calls), n + 6)


if __name__ == "__main__":
    unittest.main()
