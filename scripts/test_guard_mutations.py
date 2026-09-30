#!/usr/bin/env python3
"""A test for each guard whose mutation failed no test (final review of the combined branch, item 9).

The reviewer broke each guard below once and the whole suite still passed. Each
test here fails when its guard is removed or weakened, and names the line it
guards as it stood at 5119b03, the reviewed revision. No model, no network, no
quota: fakes and temporary directories only.

  dating_lib ~862    an agent CHECK placed in the overrides file is refused, not
                     loaded as an override that supersedes records
  dating_lib ~350    a stored check whose redirect landed on a YouTube page never
                     confirms, although its own url is an ordinary page
  dating_lib ~783    only dates wholly inside the proposal's range source the
                     statement date and the first day
  dating_lib ~393    generic event words ("conference keynote session") do not make
                     a page about another occasion name this one
  dating_lib ~222    a Wayback address with a scheme-less inner url is still unwrapped
  dating_lib ~535    a malformed fetched_at_utc bounds nothing
  extract ~598       the verifier's date doubt is kept in the run's meta
  extract ~749       an override and a check for one transcript stop the run first
  plib ~658          the checks loader refuses a check that is not the own date
  plib ~1348         a check block's range across New Year holds the relative year
                     (the reader is now predictions_lib.statement_date_earliest)
  score ~1147        an early call is paired with a prior priced on today's prompt
  site clause_words  an implied row's lead clause is the lead rule, never "said N
                     days before its own deadline"

  .venv/bin/python scripts/test_guard_mutations.py
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
import extract_predictions as D  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402
from test_dating import D10, LIVEBLOG, PODCAST, POD_PAGE, checks_for, doc_for, proposal, write_run  # noqa: E402
from test_predictions_driver import REC, ROSTER, cand  # noqa: E402
from test_predictions_release23 import UPLOAD, agent_check, operator_entry, record, with_check  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class OverridesFileRefusesACheck(unittest.TestCase):
    """dating_lib ~862: the re-merge's kind must match the file the entry sits in."""

    def test_an_agent_check_in_the_overrides_file_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = {"url": "https://thepod.example.com/episodes/ada", "publisher": "The Pod",
                   "date_on_source": "2025-09-12", "verbatim_excerpt": "Episode released September 12, 2025 in full",
                   "kind": "primary"}
            obj = proposal(verdict="publication_only", e="2025-09-12", l="2025-09-12", sources=[src],
                           tid="ada/pod-ep-xyz789", reupload="no")
            checks_path, entry = write_run(root, PODCAST, obj, {src["url"]: POD_PAGE}, kind="check")
            wrong = checks_path.parent / "overrides.json"
            wrong.write_text(json.dumps({"schema_version": 1, "overrides": {"ada/pod-ep-xyz789": entry}}))
            with self.assertRaisesRegex(L.PredictionError, "sits in the overrides file"):
                L.load_statement_date_overrides(wrong, [root / "transcripts_open"])


class RedirectIsRechecked(unittest.TestCase):
    """dating_lib ~350: the stored final_url is re-checked, not only the cited url."""

    def test_a_redirect_to_youtube_never_confirms(self):
        src = proposal()["sources"][0]
        c = DL.check_source(src, D10, {"status": 200, "final_url": src["url"], "body": LIVEBLOG.encode(),
                                       "via": "direct", "error": None})
        self.assertTrue(DL.confirms(c, proposal(), D10)[0])
        c = {**c, "final_url": "https://www.youtube.com/watch?v=someOtherVid"}
        ok, why = DL.confirms(c, proposal(), D10)
        self.assertFalse(ok)
        self.assertIn("youtube.com/watch", why)


class SpansInsideTheRange(unittest.TestCase):
    """dating_lib ~783: a date that reaches outside the range sources neither end of it."""

    def merge(self, text, e, lat, excerpt):
        page = f"<html><body><p>{text}</p></body></html>"
        src = {"url": "https://recap.example.com/dx", "publisher": "x", "date_on_source": None,
               "verbatim_excerpt": excerpt, "kind": "secondary"}
        obj = proposal(e=e, l=lat, sources=[src])
        return DL.merge_one(D10, doc_for(obj), checks_for(obj, {src["url"]: page}))

    def test_a_month_does_not_source_the_last_day_it_starts_before(self):
        out = self.merge("Ada spoke at DX in May 2012, first on May 28, 2012 at the resort", "2012-05-28",
                         "2012-05-31", "Ada spoke at DX in May 2012, first on May 28, 2012")
        self.assertEqual((out["outcome"], out.get("reason")), ("queue", "latest_day_unsourced"), out)

    def test_a_month_does_not_source_a_first_day_it_ends_after(self):
        out = self.merge("Ada spoke at DX in May 2012, on May 30, 2012 at the resort", "2012-05-01",
                         "2012-05-30", "Ada spoke at DX in May 2012, on May 30, 2012")
        self.assertEqual(out["outcome"], "override", out)
        self.assertIs(out["entry"]["earliest_evidenced"], False)


class GenericEventWords(unittest.TestCase):
    """dating_lib ~393: stop words never identify the occasion."""

    def test_a_page_that_shares_only_generic_words_is_about_another_occasion(self):
        # In 2012, the title's own year, so nothing but the event words can refuse it.
        src = {"url": "https://liveblog.example.com/2012/06/01/other", "publisher": "x", "date_on_source": None,
               "verbatim_excerpt": "Posted June 1, 2012 at 4:00 pm PT", "kind": "secondary"}
        page = ("<html><body><p>Posted June 1, 2012 at 4:00 pm PT. The keynote session opened the conference."
                "</p></body></html>")
        obj = proposal(e="2012-06-01", l="2012-06-01", sources=[src], event="The Conference Keynote Session")
        out = DL.merge_one(D10, doc_for(obj), checks_for(obj, {src["url"]: page}))
        self.assertEqual(out["outcome"], "queue", out)
        self.assertIn("name neither the speaker nor the event", out["detail"])


class SchemeLessWayback(unittest.TestCase):
    """dating_lib ~222: web.archive.org/web/<t>/www.youtube.com/... is still a YouTube page."""

    def test_refused(self):
        self.assertIsNotNone(DL.own_page_reason("http://web.archive.org/web/2019/www.youtube.com/watch?v=someOtherVid",
                                                D10))
        self.assertIsNotNone(DL.own_page_reason("https://web.archive.org/web/2019id_/youtu.be/someOtherVid", D10))

    def test_an_ordinary_page_is_still_allowed(self):
        self.assertIsNone(DL.own_page_reason("http://web.archive.org/web/2012/liveblog.example.com/2012/05/30/ada-live",
                                             D10))


class FetchBound(unittest.TestCase):
    """dating_lib ~535: only a full UTC stamp read from the record bounds an undated transcript."""

    def test_a_malformed_stamp_bounds_nothing(self):
        for bad in ("2012-06-15", "garbage", "2012-06-15 10:00:00", 20120615):
            undated = {k: v for k, v in D10.items() if k != "yt_upload_date"}
            undated["fetched_at_utc"] = bad
            self.assertIsNone(DL.fetch_bound(undated), bad)
            obj = proposal()
            out = DL.merge_one(undated, doc_for(obj, undated),
                               checks_for(obj, {"https://liveblog.example.com/2012/05/30/ada-live": LIVEBLOG}, undated))
            self.assertEqual((out["outcome"], out["reason"]), ("queue", "no_upper_bound"), bad)

    def test_a_full_stamp_bounds(self):
        self.assertEqual(DL.fetch_bound({"fetched_at_utc": "2012-06-15T10:00:00Z"}), "2012-06-15")


class VerifyMetaKeepsTheDoubt(unittest.TestCase):
    """extract_predictions ~598: the verifier's doubt reaches the run's meta, beside the records."""

    def test_the_doubt_is_in_the_verify_meta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tx = root / "transcripts" / "ada" / "s1.json"
            tx.parent.mkdir(parents=True)
            tx.write_text(json.dumps(REC))
            out = root / "predictions"
            args = D.build_parser().parse_args([])
            args.extractor, args.verifier, args.force = "astra", "fable", False
            job = {"args": args, "path": str(tx), "out": out, "roster": {"ada": ROSTER}, "exclusions": {},
                   "router": Mock(), "run_id": "r", "workroot": root / "work", "release": L.load_policy_release(),
                   "code_revision": "c", "contract": L.extraction_contract(),
                   "spec": L.read_spec(L.SKILL / L.EXTRACTION_SPEC),
                   "schema": json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()),
                   "schema_text": (L.SKILL / L.EXTRACTOR_SCHEMA).read_text()}
            job["router"].pick.return_value = {"harness": "astra", "account_id": "codex"}
            none = {"doubt": "none", "evidence": None, "evidence_year": None}
            ext = {"schema_version": "1", "transcript_id": "ada/s1", "attribution_notes": "",
                   "subject_speech_share_estimate_pct": 100, "candidates_considered": 1, "cap_hit": False,
                   "estimated_total_qualifying": 1, "statement_date_doubt": none,
                   "candidates": [cand("I think by 2030 most code will be written by AI", claim_form="simple")]}
            with patch.object(D, "call_harness", return_value=(json.dumps(ext), {"requested_model": "gpt-6-astra",
                                                                                 "served_model": "gpt-6-astra"}, "c")):
                self.assertEqual(D.extract_one(job)["status"], "ok")
            rp, mp = D.paths_for(out, "ada", "s1")
            rec = L.parse_lines(rp.read_text(), str(rp))[0]
            older = {"doubt": "recording_older_than_stated", "evidence": "at DX 2012", "evidence_year": 2012}
            verdict = {"prediction_id": rec["prediction_id"], "attribution": "subject",
                       "gates": {g: True for g in L.GATES}, "claim_faithful": True, "confidence_type_seen": "none",
                       "qualifies": True, "resolution_criteria": "By 2030, most code is AI-written.", "notes": None}
            vjob = {**job, "contract": L.verification_contract(), "extraction_spec": job["spec"],
                    "extraction_schema_text": job["schema_text"], "spec": L.read_spec(L.SKILL / L.VERIFICATION_SPEC),
                    "schema": json.loads((L.SKILL / L.VERIFIER_SCHEMA).read_text()),
                    "schema_text": (L.SKILL / L.VERIFIER_SCHEMA).read_text(), "router": Mock()}
            vjob["router"].pick.return_value = {"harness": "fable", "account_id": "claude"}
            ver = {"schema_version": "1", "transcript_id": "ada/s1", "verdicts": [verdict], "statement_date_doubt": older}
            with patch.object(D, "call_harness", return_value=(json.dumps(ver), {"requested_model": "claude-fable-5-1",
                                                                                 "judge_model": "claude-fable-5-1"}, "t")):
                self.assertEqual(D.verify_one(vjob)["status"], "ok")
            self.assertEqual(json.loads(mp.read_text())["verify"].get("statement_date_doubt"), older)


class OverrideAndCheckStopTheRun(unittest.TestCase):
    """extract_predictions ~749: refused in main, before any transcript is read for a job."""

    def test_refused_before_any_job(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tx = root / "tx" / "ada"
            tx.mkdir(parents=True)
            (tx / "s1.json").write_text(json.dumps(UPLOAD))
            roster = root / "roster.json"
            roster.write_text(json.dumps({"roster": [{"slug": "ada", **ROSTER}]}))
            ov, ck = root / "overrides.json", root / "checks.json"
            ov.write_text(json.dumps({"schema_version": 1, "overrides": {"ada/s1": operator_entry("2012-05-30")}}))
            ck.write_text(json.dumps({"schema_version": 1, "checks": {"ada/s1": operator_entry("2019-02-27")}}))
            no_call = Mock(side_effect=AssertionError("no job may run"))
            with patch.object(D, "extract_one", no_call), patch.object(D, "verify_one", no_call), \
                    patch.object(D, "call_harness", no_call), patch.dict("os.environ", {"TMPDIR": td}), \
                    contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    D.main(["--single", str(tx / "s1.json"), "--transcripts", str(root / "tx"), "--roster",
                            str(roster), "--out", str(root / "out"), "--stage", "both", "--dry-run", "--no-exclude",
                            "--date-overrides", str(ov), "--date-checks", str(ck)])
            self.assertIn("carry both an override and a check", str(cm.exception))
            no_call.assert_not_called()


class ChecksLoaderMatchesTheOwnDate(unittest.TestCase):
    """predictions_lib ~658: a check that moves the date is refused at load, before any stage runs."""

    def test_a_check_on_another_date_is_refused_at_load(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "transcripts_open"
            (root / "ada").mkdir(parents=True)
            (root / "ada" / "s1.json").write_text(json.dumps(UPLOAD))
            path = Path(td) / "checks.json"
            path.write_text(json.dumps({"schema_version": 1, "checks": {"ada/s1": operator_entry("2019-02-20")}}))
            with self.assertRaisesRegex(L.PredictionError, "is not the transcript's own date"):
                L.load_statement_date_checks(path, [root])
            path.write_text(json.dumps({"schema_version": 1, "checks": {"ada/s1": operator_entry("2019-02-27")}}))
            self.assertIn("ada/s1", L.load_statement_date_checks(path, [root]))


class NewYearFromACheckBlock(unittest.TestCase):
    """predictions_lib ~1348 (now statement_date_earliest): the check block's range is read."""

    def test_a_check_range_across_new_year_holds_next_year(self):
        r = record(with_check(UPLOAD, agent_check("2019-02-27", "dated", statement_date_earliest="2018-12-28",
                                                  precision=L.date_precision("2018-12-28", "2019-02-27"))),
                   target_date=None, target_date_text="next year")
        self.assertIsNotNone(L.relative_phrase_crosses_new_year(r))
        self.assertEqual(P2.derived_deadline(r), (None, L.RANGE_CROSSES_NEW_YEAR))


class EarlyCallPairedWithItsPrior(unittest.TestCase):
    """score_predictions ~1147: an early call under a release needs a prior priced on today's prompt."""

    def test_an_early_call_beside_a_stale_prior_is_not_scored(self):
        import resolve_predictions as RP  # noqa: PLC0415
        from test_early_calls import rec, write  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus = root / "predictions"
            (corpus / "ada").mkdir(parents=True)
            (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (rec("paired"),
                                                                                           rec("unpaired"))))
            (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
            run = corpus / "_experiments" / "run-a"
            import datetime as dt  # noqa: PLC0415
            today = {r["prediction_id"]: hashlib.sha256(R.build_prior_prompt(r, r["_deadline"]).encode()).hexdigest()
                     for r in RP.select(corpus, dt.date(2026, 9, 28), 60, due="not_due")}
            for pid in ("paired", "unpaired"):
                write(run, pid, "early", "2026-12-31")
            write(run, "paired", "prior", "2026-12-31", prompt_sha256=today["paired"])
            write(run, "unpaired", "prior", "2026-12-31", prompt_sha256="0" * 64)
            cfg = corpus / "scoring.json"
            cfg.write_text(json.dumps({"as_of": "2026-09-28", "trend": False, "min_lead_days": 60,
                                       "predictions": ["predictions"], "runs": ["predictions/_experiments/run-a"],
                                       "index": "predictions/index.json", "out": "predictions/scores.json",
                                       "policy_releases": ["legacy", R.POLICY_RELEASE[0]], "early_calls": True}))
            p = subprocess.run([sys.executable, str(REPO / "scripts" / "score_predictions.py"), "--config", str(cfg)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            rows = {r["prediction_id"]: r for r in json.loads((corpus / "scores.json").read_text())["predictions"]}
            self.assertTrue(rows["paired"]["scored"], rows["paired"])
            self.assertEqual(rows["unpaired"]["not_scored_because"], "stale_sidecar:prior_prompt_changed",
                             rows["unpaired"])


class ImpliedLeadClause(unittest.TestCase):
    """build_predictions_site.clause_words: an implied row's lead is the rule, not the window."""

    def test_the_clause_is_the_lead_rule(self):
        import build_predictions_site as B  # noqa: PLC0415
        r = copy.deepcopy(record(UPLOAD, target_date=None, target_date_text=None, horizon="none",
                                 category="company_business", subject_control="external"))
        P2.attach_deadlines([r], derive=True, implied=1.0)
        flags = P2.funnel_flags(r, 60)
        self.assertIn("implied", flags)
        st = {"deadline": r["_deadline"].isoformat(), "min_lead": 60, "lead_days": flags["lead_days"],
              "implied": flags["implied"]}
        clause = B.clause_words("lead_under_floor", st, r)
        self.assertEqual(clause, B.implied_lead_words(st))
        self.assertIn("set no lower bound", clause)
        self.assertNotIn("before its own deadline", clause)


if __name__ == "__main__":
    unittest.main()
