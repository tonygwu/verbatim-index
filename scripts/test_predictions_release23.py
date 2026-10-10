#!/usr/bin/env python3
"""Release predictions-2.3: the statement date says how it is known, and a doubt holds.

Why this exists (rescue round 4, design section 2, operator audit 2026-09-29).
Every date that was not an override reached the extractor labelled "YouTube upload
date", including a shareholder letter's own printed date and an undated Happy
Scribe page. The extractor then resolved "next year" against a 2019 re-upload of a
2012 talk, wrote "the statement year" into claims about a recording it could not
date, and wrote its doubts into notes that nothing reads. These tests pin, with no
model call:

  HEADER   one date line per basis, from a template file the release pins
  PIN      editing the header template is a policy_release_mismatch
  SPEC     the 2.3 rules are in the specs the models read
  SCHEMA   the new fields are required of the models and optional on records,
           so every 2.2 record still validates
  HOLD     statement_date_doubt, a placeholder year and a relative year that the
           funnel's own parser disagrees with each hold the record from acceptance
  STALE    a 2.2 extraction under the 2.3 release is refused without a call

  .venv/bin/python scripts/test_predictions_release23.py
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402
import extract_predictions as D  # noqa: E402
import validate_predictions as V  # noqa: E402
from test_predictions_driver import REC, ROSTER, cand  # noqa: E402

UPLOAD = {"leader_slug": "ada", "source_id": "s1", "yt_upload_date": "20190227", "url": "https://www.youtube.com/watch?v=vid00000001",
          "video_id": "vid00000001", "yt_title": "Ada at D10 2012", "declared_venue": "Re-uploads", "declared_kind": "interview",
          "word_count": 30, "duration_sec": 600, "text": REC["text"]}
STATED = {"leader_slug": "ada", "source_id": "letter", "statement_date": "2025-02-27",
          "statement_date_basis": "stated_in_page", "url": "https://example.com/letter", "declared_title": "Annual letter",
          "word_count": 30, "duration_sec": None, "text": REC["text"]}
PUBLISHED = {"leader_slug": "ada", "source_id": "hs-pod", "statement_date": "2025-09-17",
             "statement_date_basis": "publication_date", "url": "https://podcasts.example.com/show/ep",
             "declared_title": "Ada on the pod", "word_count": 30, "duration_sec": 900, "text": REC["text"]}
UNDATED = {"leader_slug": "ada", "source_id": "hs-old", "url": "https://podcasts.example.com/show/old",
           "declared_title": "Ada, undated", "word_count": 30, "duration_sec": 900, "text": REC["text"]}


def operator_entry(date, **extra):
    return {"statement_date": date, "basis": "D10 session with Kara Swisher", "source_url": "https://example.com/liveblog",
            "verbatim_evidence": "May 30, 2012 at 4:26 pm PT", "confirmed_by": "operator",
            "confirmed_at_utc": "2026-09-29T00:00:00Z", **extra}


def with_override(rec, entry):
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    return L.apply_statement_date_override(copy.deepcopy(rec), {tid: entry})


def with_check(rec, entry):
    tid = f"{rec['leader_slug']}/{rec['source_id']}"
    return L.apply_statement_date_check(copy.deepcopy(rec), {tid: entry})


def agent_check(date, verdict, **extra):
    """A dating-stage entry that CONFIRMS the transcript's own date (review item 14)."""
    return {**operator_entry(date, basis="podcast episode page"), "confirmed_by": "agent_plus_source_check",
            "earliest_evidenced": True, "confirmation": {"verdict": verdict, "kind": "check"}, **extra}


def date_line(header: str) -> str:
    lines = [x for x in header.splitlines() if x.startswith("Statement date:")]
    assert len(lines) == 1, header
    return lines[0]


PROV = L.normalise_provenance("astra", {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}, None, "codex")
QUOTE = "I think by 2030 most code will be written by AI"
NO_DOUBT = {"doubt": "none", "evidence": None, "evidence_year": None}
OLDER = {"doubt": "recording_older_than_stated", "evidence": "D10 2012", "evidence_year": 2012}


def record(rec, doubt=NO_DOUBT, **over):
    c = cand(QUOTE, claim_form="simple", **over)
    loc = L.locate_quote(rec["text"], QUOTE, "[00:01:00]")
    return L.make_record(rec, ROSTER, c, loc, PROV, "c" * 12, "run", "2026-09-29T00:00:00Z", {},
                         statement_date_doubt=doubt)


def verify(r, doubt=NO_DOUBT, criterion="By 2030-12-31, most code is AI-written."):
    verdict = {"prediction_id": r["prediction_id"], "attribution": "subject", "gates": {g: True for g in L.GATES},
               "claim_faithful": True, "confidence_type_seen": "none", "qualifies": True,
               "resolution_criteria": criterion, "notes": None}
    fprov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}, "d", "claude")
    D.apply_verdicts([r], [verdict], fprov, "v" * 12, "vrun", "2026-09-29T00:00:00Z", {}, statement_date_doubt=doubt)
    return r


class HeaderLabels(unittest.TestCase):
    """Design 2.1: the date line names its basis. Critique 3 B2: it ships with 2.3."""

    def test_stated_in_page_is_not_called_an_upload(self):
        line = date_line(L.speaker_header(STATED, ROSTER))
        self.assertEqual(line, "Statement date: 2025-02-27 (stated in the source itself; this is when the words "
                               "were written or spoken.)")

    def test_unchecked_publication_date_is_an_upper_bound_and_never_youtube(self):
        line = date_line(L.speaker_header(PUBLISHED, ROSTER))
        self.assertEqual(line, "Statement date: no later than 2025-09-17 (publication date, NOT checked against the "
                               "event. The words may have been spoken earlier; see section 1a of the specification.)")
        self.assertNotIn("YouTube", line)

    def test_unchecked_upload_date(self):
        line = date_line(L.speaker_header(UPLOAD, ROSTER))
        self.assertEqual(line, "Statement date: no later than 2019-02-27 (YouTube upload date, NOT checked against the "
                               "event. The recording may be years older; see section 1a of the specification.)")

    def test_unknown(self):
        self.assertEqual(date_line(L.speaker_header(UNDATED, ROSTER)),
                         "Statement date: unknown (no date for this recording could be established.)")

    def test_override_one_day(self):
        line = date_line(L.speaker_header(with_override(UPLOAD, operator_entry("2012-05-30")), ROSTER))
        self.assertEqual(line, "Statement date: 2012-05-30 (the day the words were spoken, from a sourced correction: "
                               "D10 session with Kara Swisher. The YouTube upload date, 2019-02-27, is later and is NOT "
                               "when the words were said.)")

    def test_override_range(self):
        entry = operator_entry("2025-09-09", statement_date_earliest="2025-09-07", precision="days",
                               basis="All-In Summit 2025, Los Angeles")
        line = date_line(L.speaker_header(with_override(PUBLISHED, entry), ROSTER))
        self.assertEqual(line, "Statement date: 2025-09-09 (the latest day the words could have been spoken, from a "
                               "sourced correction: All-In Summit 2025, Los Angeles. They were spoken between 2025-09-07 "
                               "and 2025-09-09. The publication date, 2025-09-17, is later and is NOT when the words "
                               "were said.)")

    def test_override_of_an_undated_source(self):
        line = date_line(L.speaker_header(with_override(UNDATED, operator_entry("2025-09-08")), ROSTER))
        self.assertTrue(line.endswith("The source carries no date of its own.)"), line)
        self.assertNotIn("YouTube", line)

    def test_check_on_the_own_date(self):
        """An agent entry whose date IS the publication date confirms the bound, and says so."""
        day = operator_entry("2025-09-17", basis="podcast episode page")
        self.assertEqual(date_line(L.speaker_header(with_override(PUBLISHED, day), ROSTER)),
                         "Statement date: 2025-09-17 (publication date. A dating check found the words were spoken on "
                         "this date: podcast episode page.)")
        sourced = {**day, "statement_date_earliest": "2025-09-14", "precision": "days", "earliest_evidenced": True}
        self.assertEqual(date_line(L.speaker_header(with_override(PUBLISHED, sourced), ROSTER)),
                         "Statement date: 2025-09-17 (publication date. A dating check found no earlier event: podcast "
                         "episode page. The words were spoken on this date or up to 3 days before it.)")
        unsourced = {**sourced, "earliest_evidenced": False}
        self.assertEqual(date_line(L.speaker_header(with_override(PUBLISHED, unsourced), ROSTER)),
                         "Statement date: 2025-09-17 (publication date. A dating check found no earlier event: podcast "
                         "episode page. This date is an upper bound; that the words were spoken no earlier than "
                         "2025-09-14 is the dating agent's estimate, and no source confirms it.)")

    def test_a_check_confirms_the_own_date_without_replacing_it(self):
        """Review item 14: a confirmation of the transcript's own date is a CHECK. The date and its basis
        stay the transcript's own, so no record is superseded, and the header says it was checked."""
        rec = with_check(PUBLISHED, agent_check("2025-09-17", "dated"))
        self.assertEqual(L.derive_statement_date(rec), ("2025-09-17", "publication_date"))
        self.assertEqual(date_line(L.speaker_header(rec, ROSTER)),
                         "Statement date: 2025-09-17 (publication date. A dating check found the words were spoken on "
                         "this date: podcast episode page.)")
        with self.assertRaisesRegex(L.PredictionError, "own date"):
            with_check(PUBLISHED, agent_check("2025-09-16", "dated"))
        with self.assertRaisesRegex(L.PredictionError, "both"):
            L.apply_statement_date_check(with_override(PUBLISHED, operator_entry("2025-09-10")),
                                         {"ada/hs-pod": agent_check("2025-09-17", "dated")})

    def test_a_published_day_is_not_called_the_day_of_speech(self):
        """Review item 4: publication_only says published on that day and spoken on or before it."""
        line = date_line(L.speaker_header(with_check(PUBLISHED, agent_check("2025-09-17", "publication_only")), ROSTER))
        self.assertEqual(line, "Statement date: 2025-09-17 (publication date. A dating check found the recording was "
                               "published on this date: podcast episode page. The words were spoken on this date or "
                               "before it.)")
        self.assertNotIn("were spoken on this date:", line)

    def test_a_range_with_an_unsourced_first_day_says_so(self):
        """Review item 11: like check_unsourced, an estimate is labelled as an estimate."""
        entry = {**operator_entry("2025-09-09", statement_date_earliest="2025-09-07", precision="days",
                                  basis="All-In Summit 2025, Los Angeles"), "earliest_evidenced": False}
        self.assertEqual(date_line(L.speaker_header(with_override(PUBLISHED, entry), ROSTER)),
                         "Statement date: 2025-09-09 (the latest day the words could have been spoken, from a sourced "
                         "correction: All-In Summit 2025, Los Angeles. The first possible day, 2025-09-07, is the "
                         "dating agent's estimate, and no source confirms it. The publication date, 2025-09-17, is "
                         "later and is NOT when the words were said.)")

    def test_a_check_travels_onto_the_record(self):
        rec = with_check(PUBLISHED, agent_check("2025-09-17", "publication_only",
                                                statement_date_earliest="2025-09-14", precision="days"))
        r = record(rec)
        blk = r["source"]["statement_date_check"]
        self.assertEqual((blk["verdict"], blk["statement_date_earliest"], blk["earliest_evidenced"]),
                         ("publication_only", "2025-09-14", True))
        self.assertEqual(r["source"]["statement_date_basis"], "publication_date")
        self.assertEqual(L.check_schema(r, L.load_record_schema()), [])

    def test_only_the_date_line_varies(self):
        others = {tuple(x for x in L.speaker_header(r, ROSTER).splitlines() if not x.startswith("Statement date:"))
                  for r in (UPLOAD, {**STATED, "word_count": 30, "yt_title": "Ada at D10 2012", "declared_venue": "Re-uploads",
                                     "declared_kind": "interview", "duration_sec": 600})}
        self.assertEqual(len(others), 1, others)

    def test_the_template_file_is_what_renders(self):
        """The date lines live in a skill file, so a wording change is a file change the release pins."""
        with tempfile.TemporaryDirectory() as td:
            sk = Path(td) / "skill"
            shutil.copytree(L.SKILL, sk)
            t = json.loads((sk / L.HEADER_TEMPLATE_FILE).read_text())
            t["date_lines"]["unknown"] = "Statement date: unknown (EDITED)"
            (sk / L.HEADER_TEMPLATE_FILE).write_text(json.dumps(t))
            self.assertEqual(date_line(L.speaker_header(UNDATED, ROSTER, L.load_header_template(sk))),
                             "Statement date: unknown (EDITED)")

    def test_a_template_missing_a_line_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            sk = Path(td) / "skill"
            shutil.copytree(L.SKILL, sk)
            t = json.loads((sk / L.HEADER_TEMPLATE_FILE).read_text())
            del t["date_lines"]["stated_in_page"]
            (sk / L.HEADER_TEMPLATE_FILE).write_text(json.dumps(t))
            with self.assertRaisesRegex(L.PredictionError, "stated_in_page"):
                L.load_header_template(sk)


class ReleasePin(unittest.TestCase):
    def test_release_is_2_4_with_three_pins(self):
        """2.4 (2026-10-09, ledger VD-16) is 2.3 plus one header line for a near agreement (merge-6): the
        extraction and verification contracts are 2.3's, so no 2.3 record changes meaning."""
        rel = L.load_policy_release()
        self.assertEqual(rel["release"], "predictions-2.4")
        self.assertEqual((rel["contracts"]["extract"], rel["contracts"]["verify"]), ("3f2bdd8bec82", "8bfb9da94720"))
        self.assertEqual(sorted(rel["contracts"]), ["extract", "header", "verify"])
        self.assertEqual(rel["contracts"]["header"], L.header_contract()["contract_id"])

    def test_editing_the_header_template_is_a_policy_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            sk = Path(td) / "skill"
            shutil.copytree(L.SKILL, sk)
            L.load_policy_release(sk)
            p = sk / L.HEADER_TEMPLATE_FILE
            p.write_text(p.read_text().replace("stated in the source itself", "stated in the source"))
            with self.assertRaisesRegex(ValueError, "policy_release_mismatch"):
                L.load_policy_release(sk)

    def test_the_driver_passes_the_pinned_template_to_both_stages(self):
        src = Path(D.__file__).read_text()
        self.assertIn('"header_template": header_template', src)
        self.assertIn('job.get("header_template")', src)


class SpecText(unittest.TestCase):
    def setUp(self):
        self.ext = L.read_spec(L.SKILL / L.EXTRACTION_SPEC)
        self.ver = L.read_spec(L.SKILL / L.VERIFICATION_SPEC)
        self.pol = (L.SKILL / L.POLICY_SPEC).read_text()

    def test_section_1a_reads_the_label(self):
        for needle in ("## 1a. The statement date, and what you may compute from it",
                       '"NOT checked against the event"', "recording_older_than_stated",
                       "leave\n       `target_date` null", "whole range lies inside one calendar year",
                       'never write a placeholder such as "the statement year"',
                       "If nothing shows an older recording, resolve relative time words against it as the latest"):
            self.assertIn(needle, self.ext, needle)

    def test_period_results_name_the_period(self):
        self.assertIn("A CLAIM ABOUT A PERIOD'S RESULT", self.ext)
        self.assertIn('Never write\n"By <period end>, X will report ..."', self.ext)
        self.assertIn('"For fiscal year <year>, reported revenue will be about 140 billion, as reported at any time."',
                      self.ext)
        self.assertNotIn("By fiscal year end <year>, reported revenue will be about 140 billion", self.ext)

    def test_vague_words_and_next_year(self):
        self.assertIn("go into `target_date_text` exactly as said", self.ext)
        self.assertIn("'Next year' means the whole following calendar year", self.ext)
        self.assertNotIn("remember that the\n  statement date is an upper bound", self.ext)

    def test_shared_policy(self):
        # Coordinator's decision (review item 8): an unchecked date still resolves relative words, as the
        # card labels it "not checked"; a doubt or a range across New Year stops the resolution.
        self.assertIn("Resolve relative dates against the statement date.", self.pol)
        self.assertIn("range of days that crosses 31 December", self.pol)
        self.assertNotIn("Resolve relative dates only against", self.pol)
        self.assertIn("A note is not read by anything.", self.pol)
        self.assertIn("A stated pace or schedule", self.pol)
        self.assertNotIn("do not reject a correctly resolved relative\ndate for following the supplied metadata", self.pol)
        self.assertIn("release 2.3", self.pol)

    def test_verifier_rules(self):
        self.assertIn("statement_date_doubt", self.ver)
        self.assertIn("calendar year the speaker did not say", self.ver)
        self.assertIn("dates the REPORT of a period's figure", self.ver)

    def test_skill_readme_no_longer_says_every_date_is_an_upload(self):
        text = (L.SKILL / "SKILL.md").read_text()
        self.assertNotIn("The statement date is the YouTube upload date", text)
        self.assertNotIn("only against a date known to be the day of speech", text)
        self.assertIn("Relative time words resolve against the statement date", text)


class Schemas(unittest.TestCase):
    def test_models_must_report_a_doubt_and_a_claim_form(self):
        ex = json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text())
        ve = json.loads((L.SKILL / L.VERIFIER_SCHEMA).read_text())
        for s in (ex, ve):
            self.assertIn("statement_date_doubt", s["required"])
            self.assertEqual(s["properties"]["statement_date_doubt"]["properties"]["doubt"]["enum"],
                             ["none", "recording_older_than_stated", "cannot_tell"])
        item = ex["properties"]["candidates"]["items"]
        self.assertIn("claim_form", item["required"])
        self.assertEqual(item["properties"]["claim_form"]["enum"], ["simple", "conditional", "ordering", "recurring"])

    def test_a_2_2_record_still_validates_and_a_2_3_record_validates(self):
        schema = L.load_record_schema()
        new = verify(record(UPLOAD))
        self.assertEqual(L.check_schema(new, schema), [])
        old = copy.deepcopy(new)
        del old["date_hold"], old["extraction"]["statement_date_doubt"], old["prediction"]["claim_form"]
        del old["verification"]["statement_date_doubt"]
        self.assertEqual(L.check_schema(old, schema), [])
        bad = copy.deepcopy(new)
        bad["extraction"]["statement_date_doubt"]["doubt"] = "maybe"
        self.assertTrue(L.check_schema(bad, schema))

    def test_a_range_override_block_validates(self):
        entry = operator_entry("2025-09-09", statement_date_earliest="2025-09-07", precision="days",
                               earliest_evidenced=True)
        r = record(with_override(PUBLISHED, entry))
        blk = r["source"]["statement_date_override"]
        self.assertEqual((blk["statement_date_earliest"], blk["precision"], blk["earliest_evidenced"]),
                         ("2025-09-07", "days", True))
        self.assertEqual(L.check_schema(r, L.load_record_schema()), [])
        andreessen_shape = record(with_override(UPLOAD, operator_entry("2012-05-30")))["source"]["statement_date_override"]
        self.assertNotIn("statement_date_earliest", andreessen_shape)


class Holds(unittest.TestCase):
    """Design 2.5, S13: the pipeline acts on the date, it does not only note it."""

    def test_a_doubt_from_the_extractor_holds_the_record(self):
        r = verify(record(UPLOAD, OLDER))
        self.assertEqual([h["check"] for h in r["date_hold"]], ["statement_date_doubt:extraction"])
        self.assertTrue(r["extraction"]["qualifies"] and r["verification"]["qualifies"])
        self.assertFalse(r["accepted"])

    def test_a_doubt_from_the_verifier_holds_the_record(self):
        r = verify(record(UPLOAD), OLDER)
        self.assertEqual(r["verification"]["statement_date_doubt"], OLDER)
        self.assertEqual([h["check"] for h in r["date_hold"]], ["statement_date_doubt:verification"])
        self.assertFalse(r["accepted"])

    def test_no_doubt_and_cannot_tell_do_not_hold(self):
        self.assertTrue(verify(record(UPLOAD))["accepted"])
        tell = {"doubt": "cannot_tell", "evidence": None, "evidence_year": None}
        self.assertTrue(verify(record(UPLOAD, tell), tell)["accepted"])

    def test_placeholder_with_a_known_date_holds(self):
        r = verify(record(UPLOAD, normalized_claim="Oracle hardware grows in the year following the recording."))
        self.assertEqual([h["check"] for h in r["date_hold"]], ["placeholder_date:normalized_claim"])
        self.assertFalse(r["accepted"])
        r = verify(record(UPLOAD), criterion="By the end of the statement year, X happens.")
        self.assertEqual([h["check"] for h in r["date_hold"]], ["placeholder_date:verifier_resolution_criteria"])

    def test_a_placeholder_beside_the_year_itself_is_not_a_missing_year(self):
        """MEASURED on the corpus: 'within the year following the recording, no later than 2020-07-16'
        names its year; only a field with NO year has lost it."""
        r = verify(record(UPLOAD, normalized_claim="Stripe launches two products within the year following the "
                                                   "recording, no later than 2020-07-16."))
        self.assertEqual(r["date_hold"], [])
        self.assertEqual(verify(record(UPLOAD), criterion="Within roughly one year of the recording, X.")["date_hold"], [])

    def test_placeholder_with_an_unknown_date_is_not_a_date_problem(self):
        r = verify(record(UNDATED, resolution_criteria="By the end of the statement year, X happens.",
                          target_date=None, target_date_text="this year"))
        self.assertEqual(r["date_hold"], [])

    def test_relative_year_recomputed_with_the_funnels_parser(self):
        ces = {**UPLOAD, "yt_upload_date": "20130108"}
        wrong = record(ces, target_date="2006", target_date_text="this year")
        self.assertEqual([h["check"] for h in wrong["date_hold"]], ["relative_year_mismatch"])
        self.assertIn("2013", wrong["date_hold"][0]["detail"])
        self.assertEqual(record(ces, target_date="2013", target_date_text="this year")["date_hold"], [])
        self.assertEqual(record(UPLOAD, target_date="2020", target_date_text="next year")["date_hold"], [])
        self.assertEqual([h["check"] for h in record(UPLOAD, target_date="2013", target_date_text="next year")["date_hold"]],
                         ["relative_year_mismatch"])
        self.assertEqual(record(UPLOAD, target_date="2026", target_date_text="for the next 5-7 years")["date_hold"], [])
        self.assertEqual([h["check"] for h in record(UPLOAD, target_date="2020", target_date_text="in 5 years")["date_hold"]],
                         ["relative_year_mismatch"])
        # LATER than the parser's year is often right: the parser reads the first of two alternatives
        # ("a year or two", "10 years or 20 years") and knows no fiscal year. MEASURED on the corpus.
        self.assertEqual(record(UPLOAD, target_date="2021", target_date_text="in the next year or two")["date_hold"], [])
        self.assertEqual(record({**UPLOAD, "yt_upload_date": "20161011"}, target_date="2017-01-31",
                                target_date_text="this year")["date_hold"], [])
        # ...but not more than a year later for "this year" or "next year": no fiscal year explains that.
        self.assertEqual([h["check"] for h in record({**UPLOAD, "yt_upload_date": "20161011"}, target_date="2019",
                                                     target_date_text="this year")["date_hold"]],
                         ["relative_year_mismatch"])
        # One year earlier is already a different year (review mutation M04).
        self.assertEqual([h["check"] for h in record(ces, target_date="2012", target_date_text="this year")["date_hold"]],
                         ["relative_year_mismatch"])
        # A year in the speaker's own words is the extractor's to use; no recomputation.
        self.assertEqual(record(UPLOAD, target_date="2030", target_date_text="in 10 years, by 2030")["date_hold"], [])

    def test_relative_year_on_a_range_that_crosses_new_year_holds(self):
        """Critique 1 point 13: 'next year' from a range across 31 December names two years."""
        late = {**UPLOAD, "yt_upload_date": "20250125"}
        entry = operator_entry("2025-01-03", statement_date_earliest="2024-12-20", precision="days")
        r = record(with_override(late, entry), target_date="2026", target_date_text="next year")
        self.assertEqual([h["check"] for h in r["date_hold"]], ["relative_year_on_ambiguous_range"])
        inside = operator_entry("2025-01-20", statement_date_earliest="2025-01-03", precision="days")
        self.assertEqual(record(with_override(late, inside), target_date="2026", target_date_text="next year")["date_hold"], [])

    def test_a_range_across_new_year_holds_even_with_no_target(self):
        """Review probe P8: an extractor that obeys 1a leaves target_date null, and the funnel would then
        derive 'next year' from the LAST day of a range that began the year before."""
        late = {**UPLOAD, "yt_upload_date": "20250125"}
        entry = operator_entry("2025-01-03", statement_date_earliest="2024-12-28", precision="days")
        r = record(with_override(late, entry), target_date=None, target_date_text="next year")
        self.assertEqual([h["check"] for h in r["date_hold"]], ["relative_year_on_ambiguous_range"])
        self.assertIsNotNone(L.relative_phrase_crosses_new_year(r))
        import phase2_resolvability as P2
        self.assertEqual(P2.derived_deadline(r), (None, L.RANGE_CROSSES_NEW_YEAR))

    def test_an_unchecked_upload_with_no_doubt_keeps_deriving(self):
        """Review probe P9, coordinator's decision: the card already labels the date 'not checked'."""
        r = record(UPLOAD, target_date=None, target_date_text="next year")
        self.assertEqual(r["date_hold"], [])
        import phase2_resolvability as P2
        self.assertEqual(P2.derived_deadline(r)[0].isoformat(), "2020-12-31")

    def test_a_placeholder_on_a_legacy_record_does_not_move_the_published_board(self):
        """Review mutation M02: a 2.2 record's accepted flag is kept even when a 2.3 check would hold it."""
        r = verify(record(UPLOAD, normalized_claim="Oracle hardware grows in the year following the recording."))
        del r["date_hold"], r["extraction"]["statement_date_doubt"], r["verification"]["statement_date_doubt"]
        self.assertTrue(L.date_hold_reasons(r))
        self.assertTrue(L.compute_accepted(r))

    def test_the_holding_doubt_wins_the_merge(self):
        """Review mutation M10."""
        tell = {"doubt": "cannot_tell", "evidence": None, "evidence_year": None}
        self.assertEqual(L.merge_doubts([tell, OLDER, NO_DOUBT]), OLDER)
        self.assertEqual(L.merge_doubts([NO_DOUBT, tell]), tell)

    def test_a_precision_that_is_not_the_span_is_refused(self):
        """Review mutation M12."""
        with self.assertRaisesRegex(L.PredictionError, "precision"):
            L.check_override_entry("ada/s1", operator_entry("2025-09-09", statement_date_earliest="2025-09-07",
                                                            precision="months"))

    def test_the_validator_refuses_a_doubt_without_a_hold(self):
        """Review mutation M17."""
        r = verify(record(UPLOAD))
        del r["date_hold"]
        out = []
        V.check_record(r, UPLOAD["text"], Path("/x/ada/s1.jsonl"), 1, {}, L.load_record_schema(),
                       {"c" * 12, "v" * 12}, out)
        self.assertEqual([f["invariant"] for f in out], ["date_hold"])

    def test_the_hold_needs_no_checkout(self):
        """Review item 19: compute_accepted imported phase2_resolvability, which runs git rev-parse in the
        working directory, so any caller outside a checkout crashed."""
        code = ("import sys; sys.path.insert(0, %r); import predictions_lib as L; "
                "r = {'source': {'statement_date': '2019-02-27'}, 'prediction': {'target_date': '2013', "
                "'target_date_text': 'next year'}}; print([h['check'] for h in L.date_hold_reasons(r)])"
                % str(Path(L.__file__).parent))
        with tempfile.TemporaryDirectory() as td:
            out = subprocess.run([sys.executable, "-c", code], cwd=td, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr[-600:])
        self.assertEqual(out.stdout.strip(), "['relative_year_mismatch']")

    def test_the_relative_parser_agrees_with_the_funnel(self):
        """predictions_lib keeps its own copy so the hold needs no checkout; this pins it to the funnel's."""
        import phase2_resolvability as P2
        for said in ("2019-02-27", "2020-11-19", "2024-12-31", "2016-02-29"):
            for text in ("this year", "next year", "the next year", "this time next year", "by the middle of next year",
                         "in 5 years", "for the next 5-7 years", "in 18 months", "in two years", "within 3 weeks",
                         "10 years from now or 20 years from now", "end of the year", "second half of this year",
                         "sometime next year", "eventually", "every year", "at least 10 years", "in a few years"):
                rec = {"source": {"statement_date": said}, "prediction": {"target_date": None,
                                                                          "target_date_text": text,
                                                                          "horizon_years_inferred": None}}
                want = P2.derived_deadline(rec)[0]
                got = L.relative_phrase_deadline(said, text)
                self.assertEqual(got, want, (said, text))

    def test_a_legacy_record_is_judged_by_its_own_rules(self):
        """A 2.2 record carries no date_hold; its accepted flag is the published board and stays."""
        r = verify(record(UPLOAD, OLDER))
        legacy = copy.deepcopy(r)
        del legacy["date_hold"], legacy["extraction"]["statement_date_doubt"], legacy["verification"]["statement_date_doubt"]
        self.assertTrue(L.compute_accepted(legacy))

    def test_validator_recomputes_the_hold(self):
        r = verify(record(UPLOAD, OLDER))
        tampered = copy.deepcopy(r)
        tampered["date_hold"] = []
        tampered["accepted"] = True
        out = []
        V.check_record(tampered, UPLOAD["text"], Path("/x/ada/s1.jsonl"), 1, {}, L.load_record_schema(),
                       {"c" * 12, "v" * 12}, out)
        self.assertEqual(sorted({f["invariant"] for f in out}), ["date_hold", "gates_and_qualifies"], out)
        out = []
        V.check_record(r, UPLOAD["text"], Path("/x/ada/s1.jsonl"), 1, {}, L.load_record_schema(),
                       {"c" * 12, "v" * 12}, out)
        self.assertEqual(out, [])

    def test_validator_reports_what_a_2_3_check_would_hold_in_the_legacy_corpus(self):
        r = verify(record(UPLOAD, normalized_claim="X grows in the year following the recording."))
        del r["date_hold"], r["extraction"]["statement_date_doubt"], r["verification"]["statement_date_doubt"]
        self.assertEqual([h["check"] for h in V.legacy_date_checks(r)], ["placeholder_date:normalized_claim"])


class StaleNeverPays(unittest.TestCase):
    """A 2.2 result under the 2.3 release fails as stale or mismatched, and no model is called."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tx = root / "transcripts" / "ada" / "s1.json"
        self.tx.parent.mkdir(parents=True)
        self.tx.write_text(json.dumps(REC))
        self.out = root / "predictions"
        args = D.build_parser().parse_args([])
        args.extractor, args.verifier = "astra", "fable"
        self.job = {"args": args, "path": str(self.tx), "out": self.out, "roster": {"ada": ROSTER}, "exclusions": {},
                    "router": Mock(), "run_id": "r", "workroot": root / "work", "release": L.load_policy_release(),
                    "code_revision": "c", "contract": L.extraction_contract(),
                    "spec": L.read_spec(L.SKILL / L.EXTRACTION_SPEC),
                    "schema": json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()),
                    "schema_text": (L.SKILL / L.EXTRACTOR_SCHEMA).read_text(),
                    "header_template": L.load_header_template()}

    def test_2_2_extraction_meta_is_stale_not_rerun(self):
        _, mp = D.paths_for(self.out, "ada", "s1")
        D.write_meta(mp, {"extract": {"status": "ok", "contract_id": "bf5f8441c54f",
                                      "audit": {"policy_release": "predictions-2.2"}}, "verify": {"status": "not_run"}})
        before = mp.read_bytes()
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            res = D.extract_one(self.job)
        self.assertEqual((res["status"], res["error_type"]), ("failed", L.E_CACHE_STALE))
        self.assertEqual(mp.read_bytes(), before)

    def test_2_2_extraction_is_not_verified_under_2_3(self):
        _, mp = D.paths_for(self.out, "ada", "s1")
        jl, _ = D.paths_for(self.out, "ada", "s1")
        L.write_prediction_file(jl, "")
        D.write_meta(mp, {"extract": {"status": "ok", "contract_id": "bf5f8441c54f", "harness": "astra",
                                      "audit": {"policy_release": "predictions-2.2"}}, "verify": {"status": "not_run"}})
        job = {**self.job, "contract": L.verification_contract(), "extraction_spec": self.job["spec"],
               "extraction_schema_text": self.job["schema_text"],
               "spec": L.read_spec(L.SKILL / L.VERIFICATION_SPEC),
               "schema": json.loads((L.SKILL / L.VERIFIER_SCHEMA).read_text()),
               "schema_text": (L.SKILL / L.VERIFIER_SCHEMA).read_text()}
        job["args"].force = True
        with patch.object(D, "call_harness", side_effect=AssertionError("must not call")):
            res = D.verify_one(job)
        self.assertEqual(res["error_type"], L.E_POLICY)

    def test_a_2_3_extraction_carries_the_doubt_and_claim_form_onto_its_records(self):
        self.job["router"].pick.return_value = {"harness": "astra", "account_id": "codex"}
        obj = {"schema_version": "1", "transcript_id": "ada/s1", "attribution_notes": "", "subject_speech_share_estimate_pct": 90,
               "candidates_considered": 1, "cap_hit": False, "estimated_total_qualifying": 1,
               "statement_date_doubt": OLDER, "candidates": [cand(QUOTE, claim_form="simple")]}
        with patch.object(D, "call_harness", return_value=(json.dumps(obj), {"requested_model": "gpt-6-astra",
                                                                             "served_model": "gpt-6-astra"}, "codex")):
            self.assertEqual(D.extract_one(self.job)["status"], "ok")
        jl, _ = D.paths_for(self.out, "ada", "s1")
        r = L.parse_lines(jl.read_text(), str(jl))[0]
        self.assertEqual(r["extraction"]["statement_date_doubt"], OLDER)
        self.assertEqual(r["prediction"]["claim_form"], "simple")
        _, mp = D.paths_for(self.out, "ada", "s1")
        self.assertEqual(json.loads(mp.read_text())["extract"]["statement_date_doubt"], OLDER)
        self.assertEqual([h["check"] for h in r["date_hold"]], ["statement_date_doubt:extraction"])
        self.assertEqual(L.check_schema(r, L.load_record_schema()), [])


if __name__ == "__main__":
    unittest.main()
