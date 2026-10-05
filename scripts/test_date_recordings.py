#!/usr/bin/env python3
"""The dating driver, end to end, with a fake agent and a fake web. No quota, no network.

What this pins (rescue round 4, VD-8 (c); operator changes of 2026-09-29):
  DRYRUN   the default spends nothing and writes nothing; it prints the scope and
           what a real run would spend
  RUN      --run says SPENDS QUOTA first, then proposes, checks and merges into
           the run's own directory; the override file it writes loads through the
           production loader and vouches for itself
  HARNESS  --harness gemini is the default; astra and fable are accepted; the
           served model and the account identity are on every proposal; the help
           says Fable has no working web tools
  EMPTY    Gemini's empty answer (status SUCCESS, empty response) is counted as
           empty_response, writes no proposal, is never cannot_date, and the next
           run retries it
  WHERE    a run directory in production, or outside a dating experiment, is
           refused before anything is read or written
  FETCH    a page that refuses the direct fetch is read from its Wayback copy; the
           recording's own page is never fetched at all
  SCOPE    upload-, publication- and un-dated transcripts with accepted records, and
           held ones, are in; stated_in_page and operator-overridden ones are out,
           and every exclusion is counted

  .venv/bin/python scripts/test_date_recordings.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import date_recordings as DR  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import D10, LIVEBLOG, PODCAST, proposal  # noqa: E402

LIVE_URL = "https://liveblog.example.com/2012/05/30/ada-live"


def rec_line(tid, pid, basis, date, accepted=True, hold=None):
    slug, sid = tid.split("/")
    r = {"prediction_id": pid, "transcript_id": tid, "leader_slug": slug, "source_id": sid, "accepted": accepted,
         "source": {"statement_date": date, "statement_date_basis": basis, "quote": "we will ship it next year for sure"},
         "prediction": {"normalized_claim": "It ships.", "resolution_criteria": "By 2013, it ships."},
         "extraction": {"gate_notes": "The title says DX 2012.", "qualifies": True},
         "verification": {"notes": None, "qualifies": True}}
    if hold is not None:
        r["date_hold"] = hold
    return json.dumps(r)


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        tx = self.data / "transcripts_open" / "ada"
        tx.mkdir(parents=True)
        stated = {**PODCAST, "source_id": "letter-2025", "statement_date": "2025-02-27",
                  "statement_date_basis": "stated_in_page"}
        stated.pop("yt_upload_date")
        held = {**PODCAST, "source_id": "held-ep"}
        for rec in (D10, PODCAST, stated, held, {**PODCAST, "source_id": "operator-done"}):
            (tx / f"{rec['source_id']}.json").write_text(json.dumps(rec))
        pred = self.data / "predictions" / "ada"
        pred.mkdir(parents=True)
        (pred / "re-upload-abc123.jsonl").write_text(rec_line("ada/re-upload-abc123", "p1", "youtube_upload_date", "2019-02-27") + "\n")
        (pred / "pod-ep-xyz789.jsonl").write_text(rec_line("ada/pod-ep-xyz789", "p2", "youtube_upload_date", "2025-09-12") + "\n")
        (pred / "letter-2025.jsonl").write_text(rec_line("ada/letter-2025", "p3", "stated_in_page", "2025-02-27") + "\n")
        (pred / "held-ep.jsonl").write_text(rec_line("ada/held-ep", "p4", "youtube_upload_date", "2025-09-12", accepted=False,
                                                     hold=[{"check": "statement_date_doubt:extraction", "detail": "x"}]) + "\n")
        (pred / "operator-done.jsonl").write_text(rec_line("ada/operator-done", "p5", "sourced_override", "2025-09-01") + "\n")
        (self.data / "predictions" / "statement_date_overrides.json").write_text(json.dumps({"schema_version": 1, "overrides": {
            "ada/operator-done": {"statement_date": "2025-09-01", "basis": "b", "source_url": "https://e.example.com/x",
                                  "verbatim_evidence": "v", "confirmed_by": "operator", "confirmed_at_utc": "2026-09-28T00:00:00Z"}}}))
        (self.data / "roster").mkdir()
        (self.data / "roster" / "final.json").write_text(json.dumps({"roster": [
            {"slug": "ada", "name": "Ada", "company": "Fixture Holdings"}]}))
        self.run = self.data / "predictions" / "_experiments" / "dating-test"

    def argv(self, *extra):
        return ["--run-dir", str(self.run), "--data-root", str(self.data), "--predictions", str(self.data / "predictions"),
                "--transcripts", str(self.data / "transcripts_open"),
                "--production-overrides", str(self.data / "predictions" / "statement_date_overrides.json"), *extra]


MODELS = {"gemini": "gemini-3.8-flash-high", "fable": "claude-fable-5-1", "astra": "gpt-6-astra",
          "fable_web": "claude-fable-5-1"}


class FakeAgent:
    """Answers by (harness, transcript id), else by transcript id; an entry may be an exception to raise once."""

    def __init__(self, answers):
        self.answers = {k: list(v) if isinstance(v, list) else [v] for k, v in answers.items()}
        self.calls = []

    def __call__(self, harness, prompt, timeout, workdir, args, idx):
        tid = prompt.split("transcript_id must be exactly: ")[1].split("\n")[0]
        self.calls.append((harness, tid))
        q = self.answers[(harness, tid)] if (harness, tid) in self.answers else self.answers[tid]
        ans = q.pop(0) if len(q) > 1 else q[0]
        if isinstance(ans, Exception):
            raise ans
        tel = {"requested_model": MODELS[harness], "served_model": MODELS[harness],
               "served_model_verified": True, "profile_identity": "a@example.com", "web_search_queries": ["dx 2012"],
               "tool_use_counts": {"search_web": 1}}
        return json.dumps(ans), tel, "a@example.com"


class FakeWeb:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __call__(self, url, timeout):
        self.asked.append(url)
        if url.startswith("https://archive.org/wayback/available"):
            inner = url.split("url=")[1]
            snap = self.pages.get("wayback:" + urllib_unquote(inner))
            return (200, url, json.dumps({"archived_snapshots": {"closest": {"available": True, "status": "200",
                    "url": f"http://web.archive.org/web/20120601000000/{urllib_unquote(inner)}",
                    "timestamp": "20120601000000"}} if snap else {}}).encode(), "application/json")
        if url.startswith("http://web.archive.org/web/20120601000000id_/"):
            return 200, url, self.pages["wayback:" + url.split("id_/", 1)[1]].encode(), "text/html"
        if url in self.pages:
            status = 403 if self.pages[url] == 403 else 200
            return status, url, b"" if status != 200 else self.pages[url].encode(), "text/html"
        return 404, url, b"", "text/html"


def urllib_unquote(s):
    from urllib.parse import unquote
    return unquote(s)


def pod_answer():
    src = {"url": "https://thepod.example.com/episodes/ada", "publisher": "The Pod", "date_on_source": "2025-09-12",
           "verbatim_excerpt": "Episode released September 12, 2025 in full", "kind": "primary"}
    return proposal(verdict="publication_only", e="2025-09-12", l="2025-09-12", sources=[src], tid="ada/pod-ep-xyz789",
                    reupload="no")


def run(argv, agent=None, web=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = DR.main(argv, caller=agent, opener=web, sleep=lambda s: None)
    return rc, out.getvalue()


class DryRun(unittest.TestCase):
    def test_spends_nothing_writes_nothing_and_says_what_a_run_would_cost(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({})
            rc, out = run(fx.argv(), agent, FakeWeb({}))
            self.assertEqual(rc, 0, out)
            self.assertEqual(agent.calls, [])
            self.assertFalse(fx.run.exists())
            self.assertIn("DRY RUN", out)
            self.assertIn("in scope: 3 transcripts", out)
            self.assertIn("stated_in_page (not dated by this stage): 1", out)
            self.assertIn("operator override already present: 1", out)
            self.assertIn("a real run would spend 6 calls: astra 3 (gpt-6-astra), "
                          "fable_web 3 (claude-fable-5-1)", out)


class Run(unittest.TestCase):
    def test_propose_check_merge_into_the_run_directory(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({"ada/re-upload-abc123": proposal(), "ada/pod-ep-xyz789": pod_answer(),
                               "ada/held-ep": proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None,
                                                       event_kind=None, tid="ada/held-ep")})
            web = FakeWeb({LIVE_URL: 403, "wayback:" + LIVE_URL: LIVEBLOG,
                           "https://thepod.example.com/episodes/ada":
                               "<html><body><h1>Ada on the pod</h1><p>Episode released September 12, 2025 in full</p>"
                               "</body></html>"})
            rc, out = run(fx.argv("--run", "--harness", "gemini"), agent, web)
            self.assertEqual(rc, 0, out)
            self.assertTrue(out.lstrip().startswith("SPENDS QUOTA: up to 3 calls (gemini 3"), out[:200])
            self.assertEqual(sorted(t for _, t in agent.calls), ["ada/held-ep", "ada/pod-ep-xyz789", "ada/re-upload-abc123"])
            prop = json.loads((fx.run / "proposals" / "ada" / "re-upload-abc123.gemini.json").read_text())
            self.assertEqual((prop["served_model"], prop["served_model_verified"], prop["identity"]),
                             ("gemini-3.8-flash-high", True, "a@example.com"))
            self.assertEqual(prop["telemetry"]["web_search_queries"], ["dx 2012"])
            chk = json.loads((fx.run / "source_checks" / "ada" / "re-upload-abc123.gemini.json").read_text())
            self.assertEqual(chk["checks"][0]["fetched_via"], "wayback")
            ov = L.load_statement_date_overrides(fx.run / "overrides.json", [fx.data / "transcripts_open"])
            self.assertEqual({k: v["statement_date"] for k, v in ov.items()}, {"ada/re-upload-abc123": "2012-05-30"})
            ck = L.load_statement_date_checks(fx.run / "checks.json", [fx.data / "transcripts_open"])
            self.assertEqual({k: v["statement_date"] for k, v in ck.items()}, {"ada/pod-ep-xyz789": "2025-09-12"})
            queue = json.loads((fx.run / "queue.json").read_text())["queue"]
            self.assertEqual([(q["transcript_id"], q["reason"]) for q in queue], [("ada/held-ep", "cannot_date")])
            self.assertFalse((fx.data / "predictions" / "statement_date_overrides.json").read_text().count("abc123"))
            report = json.loads(next((fx.run / "runs").glob("*.json")).read_text())
            self.assertEqual(report["propose"]["succeeded"], 3)
            self.assertEqual((report["merge"]["confirmed"], report["merge"]["checked"]), (1, 1))
            self.assertEqual(report["merge"]["queued_by_reason"], {"cannot_date": 1})

    def test_a_rerun_spends_nothing_on_what_is_done(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({"ada/re-upload-abc123": proposal(), "ada/pod-ep-xyz789": pod_answer(),
                               "ada/held-ep": proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None,
                                                       event_kind=None, tid="ada/held-ep")})
            web = FakeWeb({LIVE_URL: LIVEBLOG})
            run(fx.argv("--run", "--harness", "gemini"), agent, web)
            n = len(agent.calls)
            rc, out = run(fx.argv("--run", "--harness", "gemini"), agent, web)
            self.assertEqual(len(agent.calls), n, "a proposal on disk is reused, not paid for again")
            self.assertIn("cached 3", out)


    def test_a_remerge_keeps_the_stamp_of_an_unchanged_entry(self):
        """FOUND 2026-10-03: every merge re-stamped confirmed_at_utc on every entry, so an entry already
        promoted to production differed from its own re-merge in the stamp alone, and promotion refused it."""
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({"ada/re-upload-abc123": proposal(), "ada/pod-ep-xyz789": pod_answer(),
                               "ada/held-ep": proposal(verdict="cannot_date", e=None, l=None, sources=[], event=None,
                                                       event_kind=None, tid="ada/held-ep")})
            web = FakeWeb({LIVE_URL: LIVEBLOG, "https://thepod.example.com/episodes/ada":
                           "<html><body><h1>Ada on the pod</h1><p>Episode released September 12, 2025 in full</p>"
                           "</body></html>"})
            with patch.object(DR.DL, "utc_stamp", return_value="2026-01-01T00:00:00Z"):
                run(fx.argv("--run", "--harness", "gemini"), agent, web)
            first = {f: json.loads((fx.run / f).read_text()) for f in ("overrides.json", "checks.json")}
            self.assertEqual(first["overrides.json"]["overrides"]["ada/re-upload-abc123"]["confirmed_at_utc"],
                             "2026-01-01T00:00:00Z")
            with patch.object(DR.DL, "utc_stamp", return_value="2026-02-02T00:00:00Z"):
                rc, out = run(fx.argv("--run", "--harness", "gemini"), agent, web)
            self.assertEqual(rc, 0, out)
            again = {f: json.loads((fx.run / f).read_text()) for f in ("overrides.json", "checks.json")}
            self.assertEqual(again, first, "an unchanged entry keeps the stamp it was first confirmed with")
            # An entry that DID change is stamped again: here the stored one is edited behind the merge's back.
            doc = first["overrides.json"]
            doc["overrides"]["ada/re-upload-abc123"]["basis"] = "edited"
            (fx.run / "overrides.json").write_text(json.dumps(doc))
            with patch.object(DR.DL, "utc_stamp", return_value="2026-03-03T00:00:00Z"):
                run(fx.argv("--run", "--harness", "gemini"), agent, web)
            third = json.loads((fx.run / "overrides.json").read_text())["overrides"]["ada/re-upload-abc123"]
            self.assertEqual(third["confirmed_at_utc"], "2026-03-03T00:00:00Z")
            self.assertNotEqual(third["basis"], "edited")
            self.assertEqual(json.loads((fx.run / "checks.json").read_text())["checks"]["ada/pod-ep-xyz789"]
                             ["confirmed_at_utc"], "2026-01-01T00:00:00Z")


class Harness(unittest.TestCase):
    def test_default_is_astra_and_fable_web_help_says_which_has_web(self):
        """Operator decision of 2026-10-05: production dates with Astra and Fable with its web tools."""
        ap = DR.build_parser()
        self.assertEqual(DR.daters(ap.parse_args(["--run-dir", "x"])), ["astra", "fable_web"])
        for h in ("gemini", "astra", "fable", "fable_web"):
            self.assertEqual(DR.daters(ap.parse_args(["--run-dir", "x", "--harness", h])), [h])
        help_text = " ".join(ap.format_help().split())
        self.assertIn("Default astra,fable_web", help_text)
        self.assertIn("fable (no web tools, answers from memory)", help_text)

    def test_the_harness_reaches_the_caller_and_the_file_name(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            agent = FakeAgent({"ada/re-upload-abc123": proposal()})
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            rc, out = run(fx.argv("--run", "--harness", "fable", "--ids", str(ids), "--stage", "propose"), agent,
                          FakeWeb({}))
            self.assertEqual(rc, 0, out)
            self.assertEqual(agent.calls, [("fable", "ada/re-upload-abc123")])
            self.assertTrue((fx.run / "proposals" / "ada" / "re-upload-abc123.fable.json").exists())

    def test_fable_calls_rotate_over_the_named_accounts(self):
        # FOUND 2026-10-03: every Fable dating call went to the one default account,
        # which ran out of its Fable allowance after about 380 calls; 144 proposals
        # failed auth_or_quota while four other accounts had Fable left.
        import grade as G
        ap = DR.build_parser()
        args = ap.parse_args(["--run-dir", "x", "--fable-config-dir", "/acct/a,/acct/b"])
        used = []
        with patch.object(G, "call_fable", lambda prompt, cfg, *a, **k: (used.append(cfg) or "{}",
                                                                          {"judge_model": "claude-fable-5-1"})):
            for i in range(3):
                DR.call_agent("fable", "p", 10, Path(tempfile.mkdtemp()), args, i)
        self.assertEqual(used, ["/acct/a", "/acct/b", "/acct/a"])
        with self.assertRaises(SystemExit):
            DR.fable_dirs(ap.parse_args(["--run-dir", "x", "--fable-config-dir", "/acct/a,,/acct/b"]))

    def test_cl_is_refused_as_the_fable_binary(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            with self.assertRaises(SystemExit):
                run(fx.argv("--harness", "fable", "--fable-bin", "cl"), FakeAgent({}), FakeWeb({}))


CANNOT = dict(verdict="cannot_date", e=None, l=None, sources=[], event=None, event_kind=None)


class TwoDaters(unittest.TestCase):
    """Operator decision VD-11: a Gemini and a Fable proposal per transcript, merged together."""

    def test_two_proposal_files_per_transcript_and_the_merge_reads_both(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            # Neither answer's page is on the fake web, so only agreement can date them. The podcast's
            # day is two days before its upload; held-ep's is its upload day, which BOTH prompts
            # printed as the upper bound, so the two daters are not independent there (review fix 3).
            pod_unread = {**pod_answer(), "speech_date_earliest": "2025-09-10", "speech_date_latest": "2025-09-10"}
            held_upload = {**pod_answer(), "transcript_id": "ada/held-ep"}
            agent = FakeAgent({("gemini", "ada/re-upload-abc123"): proposal(),
                               ("fable", "ada/re-upload-abc123"): proposal(**CANNOT),
                               "ada/pod-ep-xyz789": pod_unread,
                               "ada/held-ep": held_upload})
            # The daters of VD-11, named: the two-dater mechanics do not depend on which two they are.
            rc, out = run(fx.argv("--run", "--harness", "gemini,fable"), agent, FakeWeb({LIVE_URL: LIVEBLOG}))
            self.assertEqual(rc, 0, out)
            self.assertTrue(out.lstrip().startswith("SPENDS QUOTA: up to 6 calls (gemini 3 gemini-3.8-flash-high, "
                                                    "fable 3 claude-fable-5-1)"), out[:200])
            self.assertEqual(sorted(agent.calls), sorted((h, t) for h in ("gemini", "fable") for t in
                                                         ("ada/held-ep", "ada/pod-ep-xyz789", "ada/re-upload-abc123")))
            for h in ("gemini", "fable"):
                doc = json.loads((fx.run / "proposals" / "ada" / f"re-upload-abc123.{h}.json").read_text())
                self.assertEqual((doc["harness"], doc["served_model"], doc["daters"]),
                                 (h, MODELS[h], ["gemini", "fable"]))
            self.assertTrue((fx.run / "source_checks" / "ada" / "re-upload-abc123.gemini.json").exists())
            roots = [fx.data / "transcripts_open"]
            ov = L.load_statement_date_overrides(fx.run / "overrides.json", roots)
            self.assertEqual(ov["ada/re-upload-abc123"]["confirmation"]["lead"], "gemini")
            self.assertEqual([p["harness"] for p in ov["ada/re-upload-abc123"]["confirmation"]["proposals"]],
                             ["gemini", "fable"])
            self.assertEqual(ov["ada/pod-ep-xyz789"]["confirmation"]["method"], "two_agent_agreement")
            self.assertEqual(ov["ada/pod-ep-xyz789"]["statement_date"], "2025-09-10")
            self.assertEqual(L.load_statement_date_checks(fx.run / "checks.json", roots), {})
            queue = json.loads((fx.run / "queue.json").read_text())["queue"]
            self.assertEqual([(q["transcript_id"], q["reason"]) for q in queue],
                             [("ada/held-ep", "agreement_on_shared_input")])

    def test_a_transcript_missing_one_daters_proposal_is_not_merged(self):
        """A merge without Fable could confirm a day Fable's own page contradicts; it waits for both."""
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            agent = FakeAgent({("gemini", "ada/re-upload-abc123"): proposal(),
                               ("fable", "ada/re-upload-abc123"): RuntimeError("cli_timeout: no answer")})
            rc, out = run(fx.argv("--run", "--ids", str(ids), "--harness", "gemini,fable"), agent,
                          FakeWeb({LIVE_URL: LIVEBLOG}))
            self.assertEqual(rc, 1, out)
            ov = json.loads((fx.run / "overrides.json").read_text())["overrides"]
            self.assertEqual(ov, {})
            report = json.loads(next((fx.run / "runs").glob("*.json")).read_text())
            self.assertEqual(report["merge"]["missing_proposals"], {"ada/re-upload-abc123": ["fable"]})
            self.assertIn("waiting for fable: 1", out)

    def test_each_dater_rotates_its_own_accounts_across_transcripts(self):
        """FOUND 2026-10-05 in dating-merge5-20261005a: every Astra call went to the first Codex home.

        The call index was i * len(daters) + k, so with two daters Astra (k=0) only ever got even
        numbers, and homes[idx % 2] never reached the second home; the same parity pinned a
        --fable-config-dir rotation. Each dater's calls must count transcripts, so its own
        rotation alternates."""
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            seen = []

            class Recording(FakeAgent):
                def __call__(self, harness, prompt, timeout, workdir, args, idx):
                    seen.append((harness, idx))
                    return super().__call__(harness, prompt, timeout, workdir, args, idx)
            agent = Recording({"ada/re-upload-abc123": proposal(**CANNOT), "ada/pod-ep-xyz789": proposal(**CANNOT),
                               "ada/held-ep": proposal(**CANNOT)})
            rc, out = run(fx.argv("--run", "--harness", "astra,fable_web", "--workers", "1"), agent, FakeWeb({}))
            for h in ("astra", "fable_web"):
                idxs = sorted(i for hh, i in seen if hh == h)
                self.assertEqual(len(idxs), 3, (h, seen))
                self.assertEqual({i % 2 for i in idxs}, {0, 1},
                                 f"{h}'s calls never reach a second account: indexes {idxs}")

    def test_an_unknown_or_repeated_dater_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            for bad in ("gemini,gemini", "gemini,codex", ""):
                with self.assertRaises(SystemExit) as cm:
                    run(fx.argv("--harness", bad), FakeAgent({}), FakeWeb({}))
                self.assertIn("--harness", str(cm.exception))


class EmptyAnswer(unittest.TestCase):
    def test_an_empty_answer_is_counted_retried_and_never_cannot_date(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            empty = RuntimeError("empty_response: status SUCCESS with an empty response. denied_actions=[...]")
            agent = FakeAgent({"ada/re-upload-abc123": [empty, proposal()]})
            web = FakeWeb({LIVE_URL: LIVEBLOG})
            rc, out = run(fx.argv("--run", "--harness", "gemini", "--ids", str(ids)), agent, web)
            self.assertEqual(rc, 1, out)
            report = json.loads(sorted((fx.run / "runs").glob("*.json"))[-1].read_text())
            self.assertEqual(report["propose"]["error_taxonomy"], {"empty_response": 1})
            self.assertFalse((fx.run / "proposals" / "ada" / "re-upload-abc123.gemini.json").exists())
            self.assertEqual(json.loads((fx.run / "queue.json").read_text())["queue"], [])
            self.assertEqual(report["merge"]["not_proposed"], ["ada/re-upload-abc123"])
            rc, out = run(fx.argv("--run", "--harness", "gemini", "--ids", str(ids)), agent, web)
            self.assertEqual(rc, 0, out)
            ov = L.load_statement_date_overrides(fx.run / "overrides.json", [fx.data / "transcripts_open"])
            self.assertEqual(ov["ada/re-upload-abc123"]["statement_date"], "2012-05-30")


class Scope(unittest.TestCase):
    def test_a_doubt_on_the_meta_file_brings_the_transcript_in(self):
        """Review item 18: every candidate refused, but the extractor doubted the date; it is dated anyway."""
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            pred = fx.data / "predictions" / "ada"
            (pred / "pod-ep-xyz789.jsonl").write_text(rec_line("ada/pod-ep-xyz789", "p2", "youtube_upload_date",
                                                               "2025-09-12", accepted=False) + "\n")
            rc, out = run(fx.argv(), FakeAgent({}), FakeWeb({}))
            self.assertIn("in scope: 2 transcripts", out)
            (pred / "pod-ep-xyz789.meta.json").write_text(json.dumps({"extract": {"status": "ok", "statement_date_doubt": {
                "doubt": "recording_older_than_stated", "evidence": "Ada 2019 tour", "evidence_year": 2019}}}))
            rc, out = run(fx.argv(), FakeAgent({}), FakeWeb({}))
            self.assertIn("in scope: 3 transcripts", out)

    def test_an_explicit_production_file_must_exist_and_a_missing_default_is_said(self):
        """Review item 16."""
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            argv = fx.argv()
            argv[argv.index("--production-overrides") + 1] = str(fx.data / "nope.json")
            with self.assertRaises(SystemExit) as cm:
                run(argv, FakeAgent({}), FakeWeb({}))
            self.assertIn("does not exist", str(cm.exception))
            (fx.data / "predictions" / "statement_date_overrides.json").unlink()
            argv = [a for a in fx.argv() if a]
            i = argv.index("--production-overrides")
            del argv[i:i + 2]
            rc, out = run(argv, FakeAgent({}), FakeWeb({}))
            self.assertIn("no production override file at", out)


class Where(unittest.TestCase):
    def test_production_and_non_dating_directories_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            for bad in (fx.data / "predictions", fx.data / "predictions" / "_experiments" / "rescue-x",
                        fx.data / "transcripts_open" / "dating-x"):
                argv = fx.argv("--run")
                argv[argv.index("--run-dir") + 1] = str(bad)
                with self.assertRaises(SystemExit) as cm:
                    run(argv, FakeAgent({}), FakeWeb({}))
                self.assertIn("dating-", str(cm.exception))


class Fetch(unittest.TestCase):
    def test_the_own_page_is_never_fetched(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            own = {"url": "https://www.youtube.com/watch?v=vid0000000A", "publisher": "YouTube", "date_on_source": None,
                   "verbatim_excerpt": "Uploaded on Feb 27, 2019 by Re Uploads", "kind": "secondary"}
            agent = FakeAgent({"ada/re-upload-abc123": proposal(verdict="publication_only", e="2019-02-27",
                                                                 l="2019-02-27", sources=[own], reupload="unclear")})
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            web = FakeWeb({})
            rc, out = run(fx.argv("--run", "--harness", "gemini", "--ids", str(ids)), agent, web)
            self.assertEqual(web.asked, [])
            q = json.loads((fx.run / "queue.json").read_text())["queue"]
            self.assertEqual(q[0]["reason"], "no_confirming_source")

    def test_the_breaker_stops_calling_a_host_that_keeps_throttling(self):
        """Review mutation M40: after five throttles in a row, a host is not called again this run."""
        calls = []

        def opener(url, timeout):
            calls.append(url)
            return 429, url, b"", "text/html"
        f = DR.PoliteFetcher(opener, sleep=lambda s: None, interval=0.0)
        for _ in range(3):
            last = f.fetch("https://slow.example.com/a")
        self.assertEqual(len([c for c in calls if c.startswith("https://slow.example.com")]), 6)
        self.assertIn("breaker open", last["error"])

    def test_throttling_backs_off_then_gives_up_loudly(self):
        calls = []

        def opener(url, timeout):
            calls.append(url)
            return 429, url, b"", "text/html"
        f = DR.PoliteFetcher(opener, sleep=lambda s: None, interval=0.0)
        got = f.fetch("https://slow.example.com/a")
        self.assertIn("429", got["error"])
        self.assertGreaterEqual(len([c for c in calls if "slow.example.com" in c]), 3)


if __name__ == "__main__":
    unittest.main()
