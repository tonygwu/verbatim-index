#!/usr/bin/env python3
"""merge-5: the operator's three dating gaps of 2026-10-05, and Fable's account from the quota router.

Each class pins one gap with a synthetic recording shaped like the real one and runs
the SAME input under merge-4 (what production did: the failure) and merge-5 (the
fix), so every merge test here fails on the code before the fix. No private data, no
quota, no network.

  OCCASION   (a) a page confirms only when it names the speaker AND a name of this
             occasion, every word of it, the speaker's company left out
             (vlad-tenev/the-knowledge-project-po-0jbbin r01: a casino.org article about
             Robinhood; arthur-mensch/alex-kantrowitz-xxutdy: a Big Technology post that
             never names Mensch). Control: a dated article about the same speaker on
             another topic never confirms
  YEARLESS   (b) "In February" on a page published 03.02.21 is February 2021; a period
             that ends on the range's last day shows that day. Controls: no anchor, and an
             anchor that is a re-publication, confirm nothing
  CEILING    (b) "we're doing one on December 16th of this year" is a ceiling once a
             cited floor page fixes the year (vlad-tenev OP7). Controls: no floor, a floor
             more than a year back, a past mention, a floor page with nothing tying it to
             the talk, a floor page alone
  R1         (c) a dissenting dater blocks a confirmed day only when a check of its own
             passed or the day is a publication date: pilot case A9 (a podcast feed's
             publication day) stays queued, michael-dell/citi-z30abb r01 (Citi's event page
             against an unsourced June 18) is confirmed, and the overruled dater is named
  LOADER     a merge-5 entry re-verifies from its stored files; a tampered floor window
             is refused; a proposal file without speaker_company cannot be merged
  ROUTER     Fable's account comes from quota_router.select_account per call, over the
             enabled Claude accounts; an exhausted or empty pick is refused as
             router_no_account unless --allow-degraded; --fable-config-dir pins and
             bypasses the router; the pick is recorded in the call's telemetry
  DRIVER     the production daters are astra,fable_web; a proposal file records the
             roster's company; a speaker the roster lacks stops the run before any call

  .venv/bin/python scripts/test_dating_merge5.py
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
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import date_recordings as DR  # noqa: E402
import dating_lib as DL  # noqa: E402
import predictions_lib as L  # noqa: E402
from test_dating import WORDS  # noqa: E402

V4, V5 = "merge-4", "merge-5"


def fetched(html: str, url: str) -> dict:
    return {"status": 200, "final_url": url, "body": html.encode(), "via": "direct", "error": None}


def src(url: str, excerpt: str) -> dict:
    return {"url": url, "publisher": "x", "date_on_source": None, "verbatim_excerpt": excerpt, "kind": "secondary"}


def prop(tid, e, l, sources, verdict="dated", te=None, bounds=None, event="", host=None, interviewer=None):
    return {"transcript_id": tid, "verdict": verdict, "event": event, "event_kind": "podcast_episode",
            "speech_date_earliest": e, "speech_date_latest": l, "sources": sources, "transcript_evidence": te,
            "description_evidence": None, "reupload": "no", "reasoning": "synthetic", "host_organization": host,
            "interviewer": interviewer, "bounds": bounds or []}


def doc(obj, h, daters, company):
    return {"schema_version": 1, "transcript_id": obj["transcript_id"], "harness": h, "daters": list(daters),
            "leads": [], "speaker_company": company, "proposal": obj}


def merge(rec, objs: dict, pages: dict, company: str, version: str) -> dict:
    """objs {harness: proposal}; every cited page is checked from `pages` with today's check_source."""
    docs, checks = [], {}
    for h, o in objs.items():
        docs.append(doc(o, h, list(objs), company))
        checks[h] = [DL.check_source(s, rec, fetched(pages[s["url"]], s["url"]), o) for s in o["sources"]
                     if s["url"] in pages]
    return DL.merge(rec, docs, checks, version=version)


def outcome(out: dict) -> tuple:
    return (out["outcome"], out.get("reason") or out["entry"]["statement_date"])


# ---------------------------------------------------------------------------
# A podcast shaped like vlad-tenev/the-knowledge-project-po-0jbbin
# ---------------------------------------------------------------------------

KP_COMPANY = "Analytical Engines"
KP = {"leader_slug": "ada-lovelace", "source_id": "the-knowledge-project-kp1", "video_id": "vidKP000001",
      "url": "https://www.youtube.com/watch?v=vidKP000001", "yt_upload_date": "20260303",
      "yt_title": "A Conversation with Analytical Engines co-founder and CEO Ada Lovelace",
      "yt_channel": "The Knowledge Project Podcast", "yt_description": "",
      "text": ("[00:00:01] welcome to the show " + WORDS + " product events tend to have themes. So, actually we're "
               "doing one in a couple of weeks. Um well, I should probably be more explicit about the date. We're "
               "doing one on December 16th of this year. So towards the end of the year, and it's called Yes No. "
               "And I heard there was reports of OpenAI calling a code red. " + WORDS)}
KP_TID = "ada-lovelace/the-knowledge-project-kp1"
KP_EVENT = "Shane Parrish interviews Analytical Engines co-founder and CEO Ada Lovelace for The Knowledge Project"
CASINO_URL = "https://www.casino.example/news/analytical-prediction-markets"
CASINO = ("<html><head><title>Analytical Prediction Markets Entry Threatens Bookmakers</title></head><body>"
          "<p>Analytical Prediction Markets Entry Threatens Bookmakers, Says Analyst Posted on: December 15, 2025, "
          "05:11h.</p><p>Analytical Engines plans to unveil its prediction market platform at an investor event.</p>"
          "</body></html>")
NEWS_URL = "https://news.example/analytical-ceo-on-ai"
NEWS = ("<html><head><title>Analytical CEO Ada Lovelace on AI</title></head><body><p>By A Reporter, December 10, 2025."
        " Analytical Engines CEO Ada Lovelace said the company will ship new AI tools next year.</p></body></html>")
SHOW_URL = "https://fs.example/knowledge-project/ada-lovelace"
SHOW = ("<html><head><title>The Knowledge Project</title></head><body><p>Recorded December 10, 2025: Shane Parrish "
        "talks with Ada Lovelace about engines and markets.</p></body></html>")


def kp_prop(l="2025-12-15", e="2025-12-01", sources=(), **kw):
    return prop(KP_TID, e, l, list(sources), event=KP_EVENT, host="The Knowledge Project / Farnam Street",
                interviewer="Shane Parrish", **kw)


class Occasion(unittest.TestCase):
    """(a): the speaker AND a name of this occasion, every word of it, the speaker's company left out."""

    def test_a_page_about_the_speakers_company_no_longer_confirms(self):
        """The OP7 r01 shape: merge-4 read 'Analytical' in the dater's event text as a word of the event."""
        s = src(CASINO_URL, "Analytical Prediction Markets Entry Threatens Bookmakers, Says Analyst Posted on: "
                            "December 15, 2025")
        o = kp_prop(e="2025-12-01", l="2025-12-15", sources=[s])
        c = DL.check_source(s, KP, fetched(CASINO, CASINO_URL), o)
        self.assertEqual(DL.confirms(c, o, KP, V4), (True, "confirms"))
        ok, why = DL.confirms(c, o, KP, V5, company=KP_COMPANY)
        self.assertFalse(ok)
        self.assertIn("do not name the speaker together with this occasion", why)
        self.assertEqual(outcome(merge(KP, {"astra": o}, {CASINO_URL: CASINO}, KP_COMPANY, V4)),
                         ("override", "2025-12-15"))
        self.assertEqual(outcome(merge(KP, {"astra": o}, {CASINO_URL: CASINO}, KP_COMPANY, V5))[0], "queue")

    def test_control_a_dated_article_about_the_speaker_on_another_topic_never_confirms(self):
        s = src(NEWS_URL, "By A Reporter, December 10, 2025. Analytical Engines CEO Ada Lovelace said")
        o = kp_prop(e="2025-12-01", l="2025-12-10", sources=[s])
        c = DL.check_source(s, KP, fetched(NEWS, NEWS_URL), o)
        self.assertTrue(DL.confirms(c, o, KP, V4)[0])
        ok, why = DL.confirms(c, o, KP, V5, company=KP_COMPANY)
        self.assertFalse(ok, why)
        self.assertIn("named in full: none", why)

    def test_a_page_that_names_the_speaker_and_the_show_confirms(self):
        s = src(SHOW_URL, "Recorded December 10, 2025: Shane Parrish talks with Ada Lovelace")
        o = kp_prop(e="2025-12-01", l="2025-12-10", sources=[s])
        c = DL.check_source(s, KP, fetched(SHOW, SHOW_URL), o)
        self.assertEqual(DL.confirms(c, o, KP, V5, company=KP_COMPANY), (True, "confirms"))
        out = merge(KP, {"astra": o}, {SHOW_URL: SHOW}, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-12-10"))
        self.assertEqual(out["entry"]["confirmation"]["merge_version"], V5)

    def test_every_word_of_a_name_must_be_on_the_page(self):
        """'The Knowledge Project' needs both words; 'project' alone is any page's word."""
        page = SHOW.replace("Shane Parrish talks", "A crypto project talks").replace("The Knowledge Project", "News")
        s = src(SHOW_URL, "Recorded December 10, 2025: A crypto project talks with Ada Lovelace")
        o = kp_prop(e="2025-12-01", l="2025-12-10", sources=[s])
        c = DL.check_source(s, KP, fetched(page, SHOW_URL), o)
        ok, why = DL.confirms(c, o, KP, V5, company=KP_COMPANY)
        self.assertFalse(ok, why)
        self.assertIn("'knowledge project'", why)
        self.assertEqual(DL.occasion_names(KP, o, KP_COMPANY)[:3],
                         [("knowledge", "project"), ("farnam", "street"), ("shane", "parrish")])

    def test_a_long_run_cut_to_one_word_and_a_platform_are_no_names(self):
        """FOUND in the merge-5 live run (OP7 r01): 'Inside the Mind of Robinhood Co-Founder Vlad Tenev' left 'mind' and
        'YouTube' stood alone, so Robinhood's own YES/NO page, which says 'mind' and 'YouTube', read as the podcast."""
        o = kp_prop()
        o.update(event="The Knowledge Project podcast with Shane Parrish (released on YouTube as 'Inside the Mind of "
                       "Analytical Engines Co-Founder Ada Lovelace')", host_organization=None, interviewer=None)
        names = DL.occasion_names(KP, o, KP_COMPANY)
        self.assertNotIn(("mind",), names)
        self.assertNotIn(("youtube",), names)
        url = "https://analytical.example/newsroom/yes-no"
        page = ("<html><head><title>Analytical Presents: YES/NO</title></head><body><p>Dec 1, 2025 Analytical "
                "Presents: YES/NO. Keep in mind: Ada Lovelace unveils new engines, livestreamed on YouTube.</p>"
                "</body></html>")
        s = src(url, "Dec 1, 2025 Analytical Presents: YES/NO. Keep in mind")
        o["sources"] = [s]
        o["speech_date_latest"] = "2025-12-01"
        c = DL.check_source(s, KP, fetched(page, url), o)
        ok, why = DL.confirms(c, o, KP, V5, company=KP_COMPANY)
        self.assertFalse(ok, why)
        self.assertIn("named in full: none", why)
        # One word still names an event when the run IS one word ("PandoMonthly", "DX").
        self.assertIn(("pandomonthly",), DL.occasion_names(KP, {**kp_prop(), "event": "PandoMonthly fireside chat"},
                                                            KP_COMPANY))

    def test_a_channel_cut_to_one_ordinary_word_keeps_its_generic_words(self):
        """FOUND reading the merge-5 live run (MENSCH): the channel "Big Technology Podcast" gave the name
        ('technology',), because "big" is a generic word, so any dated page naming Mensch and the word "technology"
        would have passed as about this show. A unit cut to one ordinary word keeps its generic words."""
        rec = {**KP, "yt_channel": "Big Technology Podcast"}
        o = {**kp_prop(), "host_organization": None, "interviewer": None, "event": None}
        names = DL.occasion_names(rec, o, KP_COMPANY)
        self.assertIn(("big", "technology"), names)
        self.assertNotIn(("technology",), names)
        # A unit whose one remaining word is a name as written still stands alone ("BAFTA Special Award").
        self.assertIn(("bafta",), DL.occasion_names({**rec, "yt_channel": "BAFTA Special Award"}, o, KP_COMPANY))
        url = "https://news.example/2025/12/01/engines"
        page = ("<html><head><title>Ada Lovelace on technology</title></head><body><p>December 1, 2025. Ada Lovelace "
                "spoke about technology and engines at a trade fair.</p></body></html>")
        s = src(url, "December 1, 2025. Ada Lovelace spoke about technology")
        o.update(sources=[s], speech_date_earliest="2025-12-01", speech_date_latest="2025-12-01")
        c = DL.check_source(s, rec, fetched(page, url), o)
        ok, why = DL.confirms(c, o, rec, V5, company=KP_COMPANY)
        self.assertFalse(ok, why)

    def test_a_long_run_cut_to_one_word_that_is_a_name_as_written_still_names_the_event(self):
        """FOUND replaying the pilot set after the fix above: 'PandoMonthly Fireside Chat With Elon Musk' is cut to
        'pandomonthly', and Wikipedia's Hyperloop citation 'PandoMonthly Presents: A Fireside Chat with Elon Musk
        (12 July 2012)' is a right confirmation. A word written as a name (PandoMonthly, SXSW, D11) is one; 'Mind' is not."""
        o = kp_prop()
        o.update(event="PandoMonthly Fireside Chat With Ada Lovelace", host_organization=None, interviewer=None)
        self.assertIn(("pandomonthly",), DL.occasion_names(KP, o, KP_COMPANY))
        # "Google I/O 2016" for Sundar Pichai is cut to "I/O" by his company (pilot set, SAMEYEAR-dating).
        for event, name in (("SXSW Keynote With Ada Lovelace", ("sxsw",)), ("D11 Conference Interview", ("d11",)),
                            ("Analytical I/O 2016 opening keynote by Ada Lovelace", ("i o",))):
            self.assertIn(name, DL.occasion_names(KP, {**o, "event": event}, KP_COMPANY))
        # A month or a weekday is a date, never a name (FOUND in the pilot set: Fable's event "VivaTech 2021 (Viva
        # Technology, Paris and online, 16-19 June 2021)" gave the name ('june',)).
        names = DL.occasion_names(KP, {**o, "event": "Fireside Chat at VivaTech 2021 (Viva Technology, Paris and online, "
                                                     "16-19 June 2021), Wednesday"}, KP_COMPANY)
        self.assertIn(("vivatech",), names)
        self.assertNotIn(("june",), names)
        self.assertNotIn(("wednesday",), names)
        for event in ("Inside The Mind Of Analytical Engines Co-Founder Ada Lovelace", "AI Keynote With Ada Lovelace"):
            names = DL.occasion_names(KP, {**o, "event": event}, KP_COMPANY)
            self.assertFalse([n for n in names if len(n) == 1], (event, names))
        url = "https://en.wikipedia.org/wiki/Difference_engine"
        page = ("<html><head><title>Difference engine - Wikipedia</title></head><body><p>References. Lovelace, Ada "
                "(1 December 2025). PandoMonthly Presents: A Fireside Chat with Ada Lovelace. PandoDaily/YouTube.com. "
                "Event occurs at 43:13.</p></body></html>")
        s = src(url, "Lovelace, Ada (1 December 2025). PandoMonthly Presents: A Fireside Chat with Ada Lovelace")
        o["sources"] = [s]
        o["speech_date_earliest"] = o["speech_date_latest"] = "2025-12-01"
        c = DL.check_source(s, KP, fetched(page, url), o)
        ok, why = DL.confirms(c, o, KP, V5, company=KP_COMPANY)
        self.assertTrue(ok, why)

    def test_the_speakers_company_is_never_an_occasion_name(self):
        names = DL.occasion_names(KP, kp_prop(), KP_COMPANY)
        self.assertFalse([n for n in names if {"analytical", "engines"} & set(n)], names)
        self.assertFalse([n for n in names if n == ("ceo",)], names)

    def test_the_pages_own_domain_names_the_host(self):
        """khoslaventures.com is Khosla Ventures' own page, though its window never prints the firm's name."""
        rec = {**KP, "leader_slug": "bill-gates", "source_id": "khosla-kv1", "yt_channel": "Khosla Ventures",
               "yt_title": "Fireside chat"}
        url = "https://www.khoslaventures.example/ceo-summit"
        page = ("<html><head><title>CEO Summit</title></head><body><p>Summit Archives: Fireside Chat with Bill Gates "
                "Bill Gates May 21, 2012</p></body></html>")
        s = src(url, "Fireside Chat with Bill Gates Bill Gates May 21, 2012")
        o = prop("bill-gates/khosla-kv1", "2012-05-21", "2012-05-21", [s], event="Khosla Ventures CEO Summit 2012")
        c = DL.check_source(s, rec, fetched(page, url), o)
        self.assertEqual(DL.confirms(c, o, rec, V5, company="Gates Foundation / Microsoft"), (True, "confirms"))
        moved = {**c, "url": "https://elsewhere.example/ceo-summit", "final_url": "https://elsewhere.example/ceo-summit"}
        self.assertFalse(DL.confirms(moved, o, rec, V5, company="Gates Foundation / Microsoft")[0])

    def test_a_post_by_the_interviewer_that_never_names_the_speaker_does_not_confirm(self):
        """arthur-mensch/alex-kantrowitz-xxutdy (coordinator, 2026-10-05): a Big Technology post by the host,
        'Alex Kantrowitz Jan 16, 2026', has nothing to do with Mensch; merge-4 confirmed it from the host's name."""
        rec = {"leader_slug": "arthur-mensch", "source_id": "alex-kantrowitz-xx1", "video_id": "vidAK000001",
               "url": "https://www.youtube.com/watch?v=vidAK000001", "yt_upload_date": "20260116",
               "yt_title": "Who Wins if AI Models Commoditize? With Mistral CEO Arthur Mensch",
               "yt_channel": "Alex Kantrowitz", "yt_description": "", "text": "[00:00:01] welcome " + WORDS}
        url = "https://www.bigtechnology.example/p/ai-and-the-age-of-individual-empowerment"
        page = ("<html><head><title>AI and the Age of Individual Empowerment</title></head><body><p>Big Technology "
                "AI and the Age of Individual Empowerment. Alex Kantrowitz Jan 16, 2026 Paid. Artificial intelligence "
                "adoption is starting to split into two trajectories.</p></body></html>")
        s = src(url, "Alex Kantrowitz Jan 16, 2026")
        o = prop("arthur-mensch/alex-kantrowitz-xx1", "2026-01-01", "2026-01-16", [s], verdict="publication_only",
                 event="Big Technology Podcast: Who Wins if AI Models Commoditize? With Mistral CEO Arthur Mensch")
        c = DL.check_source(s, rec, fetched(page, url), o)
        self.assertTrue(DL.confirms(c, o, rec, V4)[0])
        ok, why = DL.confirms(c, o, rec, V5, company="Mistral AI")
        self.assertFalse(ok)
        self.assertIn("speaker ['mensch'] named: no", why)

    def test_merge5_needs_the_speakers_company(self):
        s = src(SHOW_URL, "Recorded December 10, 2025: Shane Parrish talks with Ada Lovelace")
        o = kp_prop(e="2025-12-01", l="2025-12-10", sources=[s])
        c = DL.check_source(s, KP, fetched(SHOW, SHOW_URL), o)
        with self.assertRaisesRegex(ValueError, "speaker_company"):
            DL.merge(KP, [{**doc(o, "astra", ["astra"], None)}], {"astra": [c]}, version=V5)
        with self.assertRaisesRegex(ValueError, "speaker_company"):
            DL.confirms(c, o, KP, V5)
        self.assertEqual(outcome(DL.merge(KP, [doc(o, "astra", ["astra"], None)], {"astra": [c]}, version=V4)),
                         ("override", "2025-12-10"))


# ---------------------------------------------------------------------------
# (b) a date without a year, read against the same page's publication date
# ---------------------------------------------------------------------------

GL = {"leader_slug": "dara-khosrowshahi", "source_id": "greylock-gl1", "video_id": "vidGL000001",
      "url": "https://www.youtube.com/watch?v=vidGL000001", "yt_upload_date": "20211201",
      "yt_title": "Uber CEO Dara Khosrowshahi on the Platform", "yt_channel": "Greylock", "yt_description": "",
      "text": "[00:00:01] welcome everyone to our very first greylock iconversations " + WORDS}
GL_TID = "dara-khosrowshahi/greylock-gl1"
GL_URL = "https://greylock.example/greymatter/go-anywhere"


def gl_page(anchor="Published: 03.02.21"):
    return ("<html><head><title>Go Anywhere, Get Anything | Greylock</title></head><body><p>Article written by: Reid "
            f"Hoffman {anchor} Share via: linkedin twitter In February, Greylock kicked off Iconversations, a new "
            "speaker series. We were thrilled to welcome Uber CEO Dara Khosrowshahi as our first guest.</p></body></html>")


def gl_prop(e="2021-02-14", l="2021-02-28"):
    return prop(GL_TID, e, l, [src(GL_URL, "In February, Greylock kicked off Iconversations")],
                event="Greylock Iconversations, first session", host="Greylock", interviewer="Reid Hoffman")


class Yearless(unittest.TestCase):
    def check(self, page, o):
        return DL.check_source(o["sources"][0], GL, fetched(page, GL_URL), o)

    def test_in_february_on_a_page_published_03_02_21_is_february_2021(self):
        """dara-khosrowshahi/greylock-fhxo7v (OP3): merge-4 read no date in 'In February'."""
        o = gl_prop()
        c = self.check(gl_page(), o)
        ok4, why4 = DL.confirms(c, o, GL, V4)
        self.assertFalse(ok4)
        self.assertIn("carries no date with a year", why4)
        ok5, why5, spans = DL.confirming_spans(c, o, GL, V5, company="Uber Technologies")
        self.assertTrue(ok5, why5)
        self.assertEqual(spans, [(date(2021, 2, 1), date(2021, 2, 28))])
        out = merge(GL, {"fable_web": o}, {GL_URL: gl_page()}, "Uber Technologies", V5)
        self.assertEqual(outcome(out), ("override", "2021-02-28"))
        self.assertFalse(out["entry"]["earliest_evidenced"])      # February 14 comes from elsewhere, or nowhere
        self.assertEqual(outcome(merge(GL, {"fable_web": o}, {GL_URL: gl_page()}, "Uber Technologies", V4))[0], "queue")

    def test_an_ambiguous_numeric_anchor_must_give_one_year(self):
        readings = DL._numeric_readings(__import__("re").match(DL._NUMERIC, "03.02.21"))
        self.assertEqual(readings, [date(2021, 2, 3), date(2021, 3, 2)])
        feb = {"month": 2, "day": None}
        self.assertEqual(DL.resolve_yearless(feb, readings), (date(2021, 2, 1), date(2021, 2, 28)))
        # January 3 or March 1, 2021: the latest February not after them is 2020's or 2021's, so no year.
        self.assertIsNone(DL.resolve_yearless(feb, [date(2021, 1, 3), date(2021, 3, 1)]))
        self.assertEqual(DL.resolve_yearless({"month": 12, "day": 16}, [date(2025, 12, 1)]),
                         (date(2024, 12, 16), date(2024, 12, 16)))

    def test_control_a_yearless_date_with_no_anchor_confirms_nothing(self):
        o = gl_prop()
        c = self.check(gl_page(anchor=""), o)
        ok, why = DL.confirms(c, o, GL, V5, company="Uber Technologies")
        self.assertFalse(ok)
        self.assertIn("shows no publication date", why)

    def test_control_an_update_date_is_never_the_anchor(self):
        o = gl_prop()
        ok, why = DL.confirms(self.check(gl_page(anchor="Updated: 03.02.21"), o), o, GL, V5, company="Uber Technologies")
        self.assertFalse(ok)
        self.assertIn("shows no publication date", why)

    def test_control_a_re_publication_does_not_give_the_event_its_year(self):
        """A page re-published in 2024 would put 'In February' in February 2024."""
        o = gl_prop(e="2024-02-01", l="2024-02-29")
        ok, why = DL.confirms(self.check(gl_page(anchor="Republished: 03.02.24"), o), o, GL, V5,
                              company="Uber Technologies")
        self.assertFalse(ok)
        self.assertIn("the page says it is a re-publication", why)
        ok, why = DL.confirms(self.check(gl_page(anchor="Published: 03.02.24 (republished from our archive)"), o), o,
                              GL, V5, company="Uber Technologies")
        self.assertFalse(ok)
        self.assertIn("re-publication", why)
        # With its original date the page anchors on that, never on the later one.
        page = gl_page(anchor="Originally published 03.02.21. Published: 03.02.24 (republished)")
        o21 = gl_prop()
        self.assertTrue(DL.confirms(self.check(page, o21), o21, GL, V5, company="Uber Technologies")[0])
        self.assertFalse(DL.confirms(self.check(page, o), o, GL, V5, company="Uber Technologies")[0])

    def test_a_numeric_date_counts_only_with_one_reading(self):
        """AUSA prints 'Mon, 10/13/2025' (only October 13); the D.I.C.E. schedule '2/12/2020' (February 12 or
        2 December), which is read as no date rather than as the one a claim needs."""
        self.assertEqual([(d["text"], d["lo"]) for d in DL.dates_v5("Mon, 10/13/2025 - 14:00 and 4-18-2024")],
                         [("10/13/2025", date(2025, 10, 13)), ("4-18-2024", date(2024, 4, 18))])
        self.assertEqual(DL.dates_v5("2/12/2020 8:00 AM and 03.02.21"), [])
        self.assertEqual(DL.dates_in_text("Mon, 10/13/2025"), [])          # merge-3 and merge-4 read none

    def test_a_period_ending_on_the_last_day_shows_it_and_a_day_inside_it_is_not_shown(self):
        o = gl_prop(e="2021-02-12", l="2021-02-12")
        ok, why = DL.confirms(self.check(gl_page(), o), o, GL, V5, company="Uber Technologies")
        self.assertFalse(ok)
        self.assertIn("outside the range 2021-02-12..2021-02-12", why)


# ---------------------------------------------------------------------------
# (b) an upcoming day the transcript names is a ceiling
# ---------------------------------------------------------------------------

CODE_URL = "https://news.example/openai-code-red"
CODE_RED = ("<html><head><title>OpenAI declares code red</title></head><body><p>On December 1, 2025, OpenAI CEO Sam "
            "Altman declared a code red across the company.</p></body></html>")
CODE_SRC = src(CODE_URL, "On December 1, 2025, OpenAI CEO Sam Altman declared a code red across the company")
TE = "We're doing one on December 16th of this year."


def floor(day="2025-12-01", url=CODE_URL, evidence="Lovelace mentions reports of OpenAI calling a code red"):
    return {"kind": "floor", "date": day, "evidence": evidence, "source_url": url}


def ceiling_prop(e="2025-12-01", l="2025-12-15", te=TE, bounds=None, sources=(CODE_SRC,)):
    return kp_prop(e=e, l=l, sources=list(sources), te=te,
                   bounds=[floor()] if bounds is None else bounds)


class Ceiling(unittest.TestCase):
    PAGES = {CODE_URL: CODE_RED}

    def test_an_upcoming_day_is_a_ceiling_once_a_floor_page_fixes_its_year(self):
        o = ceiling_prop()
        # merge-4 read the floor page as about this occasion ("CEO" is a word of the dater's event text),
        # but nothing on it shows December 15.
        self.assertEqual(outcome(merge(KP, {"astra": o}, self.PAGES, KP_COMPANY, V4)),
                         ("queue", "latest_day_unsourced"))
        out = merge(KP, {"astra": o}, self.PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-12-15"))
        e = out["entry"]
        self.assertEqual((e["statement_date_earliest"], e["earliest_evidenced"]), ("2025-12-01", True))
        self.assertEqual((e["source_url"], e["verbatim_evidence"]), (KP["url"], TE))
        self.assertIn("the day before 2025-12-16, which the talk names as to come", e["basis"])
        routes = [(c["route"], c.get("role")) for c in e["confirmation"]["source_checks"]]
        self.assertEqual(routes, [("transcript_ceiling", None), ("page", "floor")])
        tc = e["confirmation"]["source_checks"][0]
        self.assertEqual((tc["event_day"], tc["ceiling"], tc["anchor"]),
                         ("2025-12-16", "2025-12-15", {"url": CODE_URL, "day": "2025-12-01"}))

    def test_control_without_a_floor_page_nothing_fixes_the_year(self):
        out = merge(KP, {"astra": ceiling_prop(bounds=[])}, self.PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("queue", "no_confirming_source"))
        self.assertIn("no cited page that passed the check gives a floor", out["detail"])

    def test_control_a_floor_more_than_a_year_back_fixes_no_year(self):
        page = CODE_RED.replace("December 1, 2025", "November 20, 2024")
        s = src(CODE_URL, "On November 20, 2024, OpenAI CEO Sam Altman declared a code red across the company")
        o = ceiling_prop(e="2024-11-20", bounds=[floor(day="2024-11-20")], sources=[s])
        out = merge(KP, {"astra": o}, {CODE_URL: page}, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")
        self.assertIn("could be the 'December 16th'", out["detail"])

    def test_control_a_past_mention_is_no_ceiling(self):
        rec = {**KP, "text": KP["text"].replace("We're doing one on December 16th", "We did one on December 16th")}
        o = ceiling_prop(te="We did one on December 16th of this year.")
        out = merge(rec, {"astra": o}, self.PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("queue", "no_confirming_source"))

    def test_control_a_floor_page_with_nothing_tying_it_to_the_talk_is_no_floor(self):
        page = ("<html><body><p>On December 1, 2025, the city council met to approve the new budget for the "
                "harbour.</p></body></html>")
        s = src(CODE_URL, "On December 1, 2025, the city council met to approve the new budget")
        out = merge(KP, {"astra": ceiling_prop(sources=[s])}, {CODE_URL: page}, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")
        self.assertIn("shares no two-word phrase", out["detail"])

    def test_a_floor_page_alone_confirms_nothing(self):
        o = ceiling_prop(e="2025-12-01", l="2025-12-01", te=None)
        out = merge(KP, {"astra": o}, self.PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("queue", "no_confirming_source"))

    def test_the_last_day_must_be_the_day_before(self):
        out = merge(KP, {"astra": ceiling_prop(l="2025-12-14")}, self.PAGES, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")
        self.assertIn("the day before 2025-12-16 is 2025-12-15, not the proposal's last day 2025-12-14", out["detail"])

    def test_the_month_word_may_in_lower_case_is_no_date(self):
        self.assertEqual(DL.yearless_in_text("we may 2 or 3 of them"), [])
        self.assertEqual([x["text"] for x in DL.yearless_in_text("on march 3rd and In May and December 16th")],
                         ["march 3rd", "In May", "December 16th"])


# ---------------------------------------------------------------------------
# (c) rule R1: who may block a confirmed day
# ---------------------------------------------------------------------------

SUMMIT_REC = {"leader_slug": "ada-lovelace", "source_id": "summit-s1", "video_id": "vidSUMMIT01",
              "url": "https://www.youtube.com/watch?v=vidSUMMIT01", "yt_upload_date": "20250915",
              "yt_title": "Ada Lovelace keynote", "yt_channel": "Summit Talks", "yt_description": "",
              "text": "[00:00:01] thank you all " + WORDS}
S_TID = "ada-lovelace/summit-s1"
FEED_URL = "https://feed.example/episodes"
FEED = ("<html><head><title>The Summit Pod</title></head><body><p>Published September 12, 2025: Ada Lovelace at the "
        "Compute Summit, full episode</p></body></html>")
EVENT_URL = "https://computesummit.example/agenda"
EVENT = ("<html><head><title>Compute Summit agenda</title></head><body><p>Day one, September 12, 2025: Ada Lovelace "
         "opens the Compute Summit</p></body></html>")
OWN_URL = "https://other.example/recap"
OWN = ("<html><body><p>Day one, September 9, 2025: Ada Lovelace opens the Compute Summit in a keynote.</p></body>"
       "</html>")


def s_prop(e, l, sources, verdict="dated"):
    return prop(S_TID, e, l, sources, verdict=verdict, event="Ada Lovelace keynote at the Compute Summit")


class RuleR1(unittest.TestCase):
    PAGES = {FEED_URL: FEED, EVENT_URL: EVENT, OWN_URL: OWN, "https://gone.example/x": "<html>moved</html>"}
    GONE = src("https://gone.example/x", "Ada Lovelace spoke at the summit")

    def run_pair(self, lead_src, other, version):
        return merge(SUMMIT_REC, {"gemini": other, "fable_web": s_prop("2025-09-12", "2025-09-12", [lead_src])},
                     self.PAGES, "Analytical Engines", version)

    def test_a9_a_publication_day_still_yields_to_any_dissent(self):
        """Pilot case A9: a podcast feed's publication day; the other dater's unsupported range held the summit."""
        lead = src(FEED_URL, "Published September 12, 2025: Ada Lovelace at the Compute Summit")
        for v in (V4, V5):
            out = self.run_pair(lead, s_prop("2025-09-07", "2025-09-09", [self.GONE]), v)
            self.assertEqual(outcome(out), ("queue", "dater_disagreement"), v)
        self.assertIn("the confirmed day is a publication date", out["detail"])

    def test_op4_an_unsupported_dissent_no_longer_blocks_an_event_page(self):
        """michael-dell/citi-z30abb r01: Citi's page dates the session; Gemini's June 18 had no check that passed."""
        lead = src(EVENT_URL, "Day one, September 12, 2025: Ada Lovelace opens the Compute Summit")
        other = s_prop("2025-09-14", "2025-09-14", [self.GONE])
        self.assertEqual(outcome(self.run_pair(lead, other, V4)), ("queue", "dater_disagreement"))
        out = self.run_pair(lead, other, V5)
        self.assertEqual(outcome(out), ("override", "2025-09-12"))
        self.assertEqual(out["entry"]["confirmation"]["overruled"],
                         [{"dater": "gemini", "range": ["2025-09-14", "2025-09-14"],
                           "why": "no check of its own passed, and the confirmed day is not a publication date"}])

    def test_a_dissent_a_check_of_its_own_supports_still_blocks(self):
        """The other dater's own page shows September 9 inside its range, though not its last day: supported."""
        lead = src(EVENT_URL, "Day one, September 12, 2025: Ada Lovelace opens the Compute Summit")
        other = s_prop("2025-09-08", "2025-09-10", [src(OWN_URL, "Day one, September 9, 2025: Ada Lovelace opens")])
        out = self.run_pair(lead, other, V5)
        self.assertEqual(outcome(out), ("queue", "dater_disagreement"))
        self.assertIn("a check of its own supports that range", out["detail"])

    def test_a_publication_only_verdict_is_a_publication_day(self):
        lead = src(EVENT_URL, "Day one, September 12, 2025: Ada Lovelace opens the Compute Summit")
        out = merge(SUMMIT_REC, {"gemini": s_prop("2025-09-07", "2025-09-09", [self.GONE]),
                                 "fable_web": s_prop("2025-09-12", "2025-09-12", [lead], verdict="publication_only")},
                    self.PAGES, "Analytical Engines", V5)
        self.assertEqual(outcome(out), ("queue", "dater_disagreement"))


# ---------------------------------------------------------------------------
# The loader re-verifies a merge-5 entry from its stored files
# ---------------------------------------------------------------------------

class Loader(unittest.TestCase):
    def write(self, root: Path):
        (root / "transcripts_open" / "ada-lovelace").mkdir(parents=True)
        (root / "transcripts_open" / "ada-lovelace" / "the-knowledge-project-kp1.json").write_text(json.dumps(KP))
        run = root / "predictions" / "_experiments" / "dating-m5"
        o = ceiling_prop()
        pp = run / "proposals" / "ada-lovelace" / "the-knowledge-project-kp1.astra.json"
        pp.parent.mkdir(parents=True)
        pp.write_text(json.dumps(doc(o, "astra", ["astra"], KP_COMPANY)))
        ref = {"astra": {"path": str(pp.relative_to(run)), "sha256": hashlib.sha256(pp.read_bytes()).hexdigest()}}
        checks = {"astra": [DL.check_source(CODE_SRC, KP, fetched(CODE_RED, CODE_URL), o)]}
        out = DL.merge(KP, [json.loads(pp.read_text())], checks, ref, run_rel="predictions/_experiments/dating-m5",
                       version=V5)
        self.assertEqual(outcome(out), ("override", "2025-12-15"))
        entry = {**out["entry"], "confirmed_at_utc": "2026-10-05T00:00:00Z"}
        path = run / "overrides.json"
        path.write_text(json.dumps({"schema_version": 1, "overrides": {KP_TID: entry}}))
        return path, entry, pp

    def test_a_merge5_entry_re_verifies_and_a_tampered_floor_window_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, _ = self.write(root)
            roots = [root / "transcripts_open"]
            got = L.load_statement_date_overrides(path, roots)
            self.assertEqual(got[KP_TID]["confirmation"]["merge_version"], V5)
            bad = copy.deepcopy(entry)
            floor_check = next(c for c in bad["confirmation"]["source_checks"] if c.get("role") == "floor")
            floor_check["window"] = floor_check["window"].replace("code red", "budget")
            path.write_text(json.dumps({"schema_version": 1, "overrides": {KP_TID: bad}}))
            with self.assertRaisesRegex(L.PredictionError, "no longer confirms|differs from its re-merge"):
                L.load_statement_date_overrides(path, roots)

    def test_a_proposal_file_without_the_company_cannot_be_re_merged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, entry, pp = self.write(root)
            d = json.loads(pp.read_text())
            d.pop("speaker_company")
            pp.write_text(json.dumps(d))
            e = copy.deepcopy(entry)
            e["confirmation"]["proposals"][0]["sha256"] = hashlib.sha256(pp.read_bytes()).hexdigest()
            path.write_text(json.dumps({"schema_version": 1, "overrides": {KP_TID: e}}))
            with self.assertRaisesRegex(L.PredictionError, "speaker_company"):
                L.load_statement_date_overrides(path, [root / "transcripts_open"])


# ---------------------------------------------------------------------------
# Fable's account, picked by the quota router per call
# ---------------------------------------------------------------------------

ACCOUNTS = [("claude", "claude", "/h/.claude", True), ("claude_d", "claude", "/h/.claude-d", False),
            ("codex", "codex", "/h/.codex", False)]


def payload(account, fits=True, reason="wins", degraded=(), provider="claude"):
    return {"decision": {"account": account, "provider": provider, "fits": fits, "reason": reason},
            "degraded": list(degraded), "excluded": [], "warnings": []}


class FakeSelect:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(to_dict=lambda: self.answers.pop(0))


def args(**over):
    base = dict(fable_config_dir=None, allow_degraded=False, fable_bin="claude", fable_router=None)
    return SimpleNamespace(**{**base, **over})


class Router(unittest.TestCase):
    def test_the_router_picks_among_the_claude_accounts_and_its_dir_reaches_the_call(self):
        sel = FakeSelect(payload("claude_d", reason="claude_d wins: 1.9 PSE"), payload("claude"))
        a = args(fable_router=DR.FableRouter(False, select=sel, accounts=ACCOUNTS))
        seen = []

        def fake_web(prompt, cfg, timeout, binary="claude", workdir=None):
            seen.append(cfg)
            return "{}", {"judge_model": "claude-fable-5-1", "requested_model": "claude-fable-5-1"}
        real, DR.call_fable_web = DR.call_fable_web, fake_web
        try:
            with tempfile.TemporaryDirectory() as td:
                _, tel, _ = DR.call_agent("fable_web", "p", 10, Path(td) / "w", a, 0)
                DR.call_agent("fable_web", "p", 10, Path(td) / "w2", a, 1)
        finally:
            DR.call_fable_web = real
        self.assertEqual(seen, ["/h/.claude-d", "__DEFAULT__"])
        self.assertEqual(sel.calls[0], {"model": "fable", "only": ["claude", "claude_d"], "record": True,
                                        "no_sticky": True})
        self.assertEqual((tel["router"]["account_id"], tel["router"]["reason"], tel["router"]["pinned"]),
                         ("claude_d", "claude_d wins: 1.9 PSE", False))
        self.assertEqual(tel["served_model"], "claude-fable-5-1")

    def test_an_exhausted_pick_is_refused_unless_allowed(self):
        exhausted = payload("claude", fits=False, reason="every candidate is out of quota")
        r = DR.FableRouter(False, select=FakeSelect(exhausted), accounts=ACCOUNTS)
        with self.assertRaisesRegex(Exception, "^router_no_account"):
            r.pick()
        self.assertEqual(L.classify_exception_detail(f"{L.E_ROUTER}: x"), "router_no_account")
        cfg, route = DR.FableRouter(True, select=FakeSelect(exhausted), accounts=ACCOUNTS).pick()
        self.assertEqual((cfg, route["fits"]), ("__DEFAULT__", False))

    def test_a_degraded_unfit_pick_is_refused_and_no_pick_is_always_refused(self):
        degraded = payload("claude_d", fits=False, degraded=[{"account": "claude_d", "why": "stale snapshot"}])
        with self.assertRaisesRegex(Exception, "^router_no_account"):
            DR.FableRouter(False, select=FakeSelect(degraded), accounts=ACCOUNTS).pick()
        for allow in (False, True):
            with self.assertRaisesRegex(Exception, "^router_no_account: router picked no account"):
                DR.FableRouter(allow, select=FakeSelect(payload(None)), accounts=ACCOUNTS).pick()

    def test_a_pick_outside_the_claude_accounts_is_refused(self):
        with self.assertRaisesRegex(Exception, "^router_no_account"):
            DR.FableRouter(True, select=FakeSelect(payload("codex", provider="codex")), accounts=ACCOUNTS).pick()

    def test_router_exclude_keeps_named_accounts_out_of_every_pick(self):
        """FOUND 2026-10-05 in dating-merge5-20261005a: the router sent half the Fable calls to
        claude_b, the account the coordinating session runs on, and its 5-hour window fell 16
        points in 25 minutes. --router-exclude keeps such an account out of `only`, the way
        extract_predictions' --router-exclude does; excluding every Claude account is refused."""
        sel = FakeSelect(payload("claude_d"))
        DR.FableRouter(False, select=sel, accounts=ACCOUNTS, exclude=["claude"]).pick()
        self.assertEqual(sel.calls[0]["only"], ["claude_d"])
        with self.assertRaisesRegex(RuntimeError, "^router_no_account"):
            DR.FableRouter(False, select=FakeSelect(), accounts=ACCOUNTS, exclude=["claude", "claude_d"])
        a = args(router_exclude="claude_d")
        real = DR.FableRouter
        made = []

        class Spy(real):
            def __init__(self, allow_degraded, select=None, accounts=None, exclude=()):
                made.append(list(exclude))
                super().__init__(allow_degraded, select=FakeSelect(payload("claude")), accounts=ACCOUNTS,
                                 exclude=exclude)
        DR.FableRouter = Spy
        try:
            cfg, route = DR.fable_account(a, 0)
        finally:
            DR.FableRouter = real
        self.assertEqual((made, cfg, route["excluded"]), ([["claude_d"]], "__DEFAULT__", ["claude_d"]))

    def test_no_claude_account_in_the_config_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "^router_no_account"):
            DR.FableRouter(False, select=FakeSelect(), accounts=[ACCOUNTS[2]])

    def test_a_pin_bypasses_the_router(self):
        class Boom:
            def __call__(self, **kw):
                raise AssertionError("the router was asked although --fable-config-dir pins the accounts")
        a = args(fable_config_dir="/x/a,/x/b", fable_router=DR.FableRouter(False, select=Boom(), accounts=ACCOUNTS))
        self.assertEqual(DR.fable_account(a, 0), ("/x/a", {"account_id": None, "config_dir": "/x/a",
                                                           "reason": "pinned by --fable-config-dir", "pinned": True}))
        self.assertEqual(DR.fable_account(a, 1)[0], "/x/b")


# ---------------------------------------------------------------------------
# The driver: production daters and the speaker's company
# ---------------------------------------------------------------------------

class Driver(unittest.TestCase):
    def test_the_production_daters_and_merge_version(self):
        self.assertEqual(DL.DATERS, ("astra", "fable_web"))
        # merge-6 (2026-10-09) followed; it confirms by source exactly as merge-5 (test_dating_merge6).
        self.assertEqual(DL.MERGE_VERSION, "merge-6")
        self.assertIn(V5, DL.MERGE_VERSIONS)
        self.assertEqual(DR.build_parser().parse_args(["--run-dir", "x"]).harness, "astra,fable_web")

    def test_a_proposal_file_records_the_rosters_company(self):
        from test_date_recordings import FakeAgent, FakeWeb, Fixture, LIVE_URL, run  # noqa: PLC0415
        from test_dating import LIVEBLOG, proposal  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            ids = Path(td) / "ids.txt"
            ids.write_text("ada/re-upload-abc123\n")
            agent = FakeAgent({"ada/re-upload-abc123": proposal()})
            rc, out = run(fx.argv("--run", "--ids", str(ids)), agent, FakeWeb({LIVE_URL: LIVEBLOG}))
            self.assertEqual(sorted(h for h, _ in agent.calls), ["astra", "fable_web"])
            for h in ("astra", "fable_web"):
                d = json.loads((fx.run / "proposals" / "ada" / f"re-upload-abc123.{h}.json").read_text())
                self.assertEqual((d["speaker_company"], d["daters"]), ("Fixture Holdings", ["astra", "fable_web"]))

    def test_a_speaker_the_roster_lacks_stops_the_run_before_any_call(self):
        from test_date_recordings import FakeAgent, FakeWeb, Fixture, run  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(Path(td))
            (fx.data / "roster" / "final.json").write_text(json.dumps({"roster": [{"slug": "bob", "company": "B"}]}))
            agent = FakeAgent({})
            with self.assertRaisesRegex(SystemExit, "roster .* has no entry for \\['ada'\\]"):
                run(fx.argv("--run"), agent, FakeWeb({}))
            self.assertEqual(agent.calls, [])


# ---------------------------------------------------------------------------
# The operator's release rule (2026-10-05): the podcaster's own episode, dated by its release
# ---------------------------------------------------------------------------

DW = {"leader_slug": "ada-lovelace", "source_id": "dwarkesh-patel-dw1", "video_id": "vidDW000001",
      "url": "https://www.youtube.com/watch?v=vidDW000001", "yt_upload_date": "20240418",
      "yt_title": "Ada Lovelace — engines, Caesar Augustus, & 1 GW datacenters", "yt_channel": "Dwarkesh Patel",
      "yt_description": "", "text": "[00:00:01] today I am chatting with Ada " + WORDS}
DW_TID = "ada-lovelace/dwarkesh-patel-dw1"
DW_URL = "https://www.dwarkesh.example/p/ada-lovelace"
DW_PAGE = ('<html><head><title>Ada Lovelace — engines and datacenters</title></head><body><p>Dwarkesh Patel Apr 18, '
           '2024</p><iframe src="https://www.youtube.com/embed/vidDW000001"></iframe><p>Ada Lovelace on engines, '
           'Caesar Augustus and datacenters.</p></body></html>')


def dw_prop(verdict="publication_only", kind="podcast_episode", e="2024-01-18", l="2024-04-18", reupload="no"):
    o = prop(DW_TID, e, l, [src(DW_URL, "Dwarkesh Patel Apr 18, 2024")], verdict=verdict,
             event="Dwarkesh Podcast episode with Ada Lovelace about engines", host="Dwarkesh Podcast",
             interviewer="Dwarkesh Patel")
    o.update(event_kind=kind, reupload=reupload)
    return o


class Release(unittest.TestCase):
    def test_the_podcasters_own_episode_is_dated_by_its_release(self):
        """mark-zuckerberg/dwarkesh-patel-bc6ufv: the show's own page shows the release, the upload day."""
        o = dw_prop()
        self.assertEqual(outcome(merge(DW, {"fable_web": o}, {DW_URL: DW_PAGE}, KP_COMPANY, V4)),
                         ("queue", "no_confirming_source"))
        out = merge(DW, {"fable_web": o}, {DW_URL: DW_PAGE}, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("check", "2024-04-18"))
        self.assertTrue(DL.own_channel(DW, o, KP_COMPANY))

    def test_controls_a_re_upload_channel_an_event_recording_or_a_speech_verdict_is_not_released(self):
        for rec, o in (({**DW, "yt_channel": "Talks Archive"}, dw_prop()),
                       (DW, dw_prop(kind="interview")),
                       (DW, dw_prop(reupload="unclear")),
                       (DW, dw_prop(verdict="dated"))):
            out = merge(rec, {"fable_web": o}, {DW_URL: DW_PAGE}, KP_COMPANY, V5)
            self.assertEqual(out["outcome"], "queue", (rec["yt_channel"], o["event_kind"], o["verdict"]))

    def test_another_daters_earlier_range_still_blocks_a_release_day(self):
        """No tighter earlier ceiling may be found: a release day is a publication day, and rule R1 holds in full."""
        other = dw_prop(e="2024-04-01", l="2024-04-10")
        other["sources"] = [src("https://gone.example/x", "Ada Lovelace spoke with Dwarkesh")]
        out = merge(DW, {"astra": other, "fable_web": dw_prop()}, {DW_URL: DW_PAGE}, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("queue", "dater_disagreement"))


# ---------------------------------------------------------------------------
# A day word in the talk pins the day of speech (operator decision, 2026-10-05)
# ---------------------------------------------------------------------------

DRISCOLL = "Did you see the new Secretary of the Army, Dan Driscoll's AUSA talk yesterday?"
JRE = {"leader_slug": "ada-lovelace", "source_id": "hs-2394-ada", "url": "https://podcasts.happyscribe.example/jre/2394",
       "declared_title": "#2394 - Ada Lovelace", "declared_venue": "the-joe-rogan-experience",
       "fetched_at_utc": "2026-09-11T03:10:02Z",
       "text": ("[00:00:01] welcome " + WORDS + " [00:27:53] I do think we're turning a corner with some of this. "
                + DRISCOLL + " [00:28:14] No, I did not. " + WORDS + " [01:00:00] This episode is brought to you "
                "by BetterHelp. The big sale ends tomorrow, so visit betterhelp.com/jre today. " + WORDS)}
JRE_TID = "ada-lovelace/hs-2394-ada"
AUSA_URL = "https://www.ausa.example/news/driscoll-army-faces-inflection-point"
AUSA = ("<html><head><title>Driscoll: Army Faces Inflection Point</title></head><body><p>October 13, 2025. Secretary "
        "of the Army Dan Driscoll told the AUSA annual meeting that the Army faces an inflection point.</p></body></html>")
AUSA_SRC = src(AUSA_URL, "October 13, 2025. Secretary of the Army Dan Driscoll told the AUSA annual meeting")
APPLE_URL = "https://podcasts.apple.com/us/podcast/2394-ada-lovelace/id1"
APPLE = ("<html><head><title>#2394 - Ada Lovelace - The Joe Rogan Experience - Apple Podcasts</title></head><body>"
         "<p>Ada Lovelace is the founder of Analytical Engines. Show The Joe Rogan Experience Published October 16, "
         "2025 at 5:00 PM UTC</p></body></html>")
APPLE_SRC = src(APPLE_URL, "Show The Joe Rogan Experience Published October 16, 2025 at 5:00 PM UTC")
JRE_PAGES = {AUSA_URL: AUSA, APPLE_URL: APPLE}


def jre_prop(e="2025-10-14", l="2025-10-16", te=DRISCOLL, sources=(AUSA_SRC, APPLE_SRC)):
    o = prop(JRE_TID, e, l, list(sources), verdict="publication_only", te=te,
             event="The Joe Rogan Experience #2394 with Ada Lovelace", host="The Joe Rogan Experience",
             interviewer="Joe Rogan")
    o["reupload"] = "no"
    return o


class DayWord(unittest.TestCase):
    def test_yesterday_after_a_dated_event_pins_the_day(self):
        """palmer-luckey/hs-2394-palmer-luckey: 'AUSA talk yesterday', AUSA dates it 2025-10-13: spoken 10-14."""
        o = jre_prop()
        self.assertEqual(outcome(merge(JRE, {"astra": o}, JRE_PAGES, KP_COMPANY, V4)), ("override", "2025-10-16"))
        out = merge(JRE, {"astra": o}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-10-14"))
        e = out["entry"]
        self.assertNotIn("statement_date_earliest", e)                 # the range narrowed to one day
        self.assertEqual(e["confirmation"]["narrowed_from"], ["2025-10-14", "2025-10-16"])
        self.assertEqual(e["confirmation"]["verdict"], "dated")
        self.assertIn("the talk says 'yesterday' of an event a cited page dates 2025-10-13", e["basis"])
        pin = e["confirmation"]["source_checks"][0]
        self.assertEqual((pin["route"], pin["day"], pin["event_day"], pin["phrase"]),
                         ("relative_day", "2025-10-14", "2025-10-13", "army dan"))
        self.assertEqual(e["confirmation"]["source_checks"][1]["role"], "event")

    def test_the_sentence_that_carries_the_day_word_is_read_on_its_own(self):
        """FOUND in the merge-5 live run (JRE2394 r02, fable_web): the dater quoted the Driscoll sentence and then
        the next speaker's words, which the captions write differently, so the whole quote was not in the transcript
        and the day word was never read. The sentence that carries the day word is real transcript words."""
        te = DRISCOLL + " Oh, man. It might be worth pulling it up."
        out = merge(JRE, {"fable_web": jre_prop(te=te)}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-10-14"))
        self.assertEqual(out["entry"]["confirmation"]["source_checks"][0]["quote"], DRISCOLL)
        # Control: a day-word sentence that is not in the transcript pins nothing.
        made_up = "Did you see Dan Driscoll's AUSA talk yesterday? Oh, man. It might be worth pulling it up."
        out = merge(JRE, {"fable_web": jre_prop(te=made_up)}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-10-16"))       # the release page alone, unpinned
        self.assertNotIn("narrowed_from", out["entry"]["confirmation"])

    def test_the_pinned_day_outranks_another_daters_release_day(self):
        release = jre_prop(e="2025-10-16", l="2025-10-16", te=None, sources=[APPLE_SRC])
        out = merge(JRE, {"astra": jre_prop(), "fable_web": release}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-10-14"))
        self.assertEqual(out["entry"]["confirmation"]["refines"],
                         [{"dater": "fable_web", "range": ["2025-10-16", "2025-10-16"],
                           "why": "a publication day after the day the talk pins"}])

    def test_control_a_day_word_in_a_sponsor_read_pins_nothing(self):
        rec = {**JRE, "text": JRE["text"].replace("[00:28:14] No, I did not.",
                                                  "[00:28:14] This hour is brought to you by BetterHelp.")}
        out = merge(rec, {"astra": jre_prop()}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-10-16"))       # the release page still dates it
        out = merge(rec, {"astra": jre_prop(sources=[AUSA_SRC])}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")
        self.assertIn("stands in a sponsor read", out["detail"])

    def test_control_an_event_page_that_fails_the_check_pins_nothing(self):
        moved = src(AUSA_URL, "October 13, 2025. The Secretary of the Navy spoke")
        out = merge(JRE, {"astra": jre_prop(sources=[moved])}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")
        self.assertIn("the excerpt is not on the page", out["detail"])

    def test_control_an_event_without_a_confirmed_date_pins_nothing(self):
        out = merge(JRE, {"astra": jre_prop(sources=[APPLE_SRC])}, JRE_PAGES, KP_COMPANY, V5)
        self.assertEqual(outcome(out), ("override", "2025-10-16"))
        self.assertNotIn("narrowed_from", out["entry"]["confirmation"])

    def test_control_a_page_with_nothing_tying_it_to_the_words_pins_nothing(self):
        page = AUSA.replace("Secretary of the Army Dan Driscoll told the AUSA annual meeting",
                            "the harbour board approved a budget at its annual meeting")
        s = src(AUSA_URL, "October 13, 2025. the harbour board approved a budget")
        out = merge(JRE, {"astra": jre_prop(sources=[s])}, {AUSA_URL: page}, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")
        self.assertIn("shares no two-word phrase", out["detail"])


class SponsorReads(unittest.TestCase):
    def test_an_upcoming_day_inside_a_sponsor_read_is_no_ceiling(self):
        rec = {**KP, "text": KP["text"].replace("So towards the end of the year",
                                                "Use code KNOW for 20% off at engines.com/know. So towards the end")}
        out = merge(rec, {"astra": ceiling_prop()}, Ceiling.PAGES, KP_COMPANY, V5)
        self.assertEqual(out["outcome"], "queue")

    def test_the_cue_list(self):
        for text in ("brought to you by X", "use code JRE", "20% off", "visit example.com", "example.com/jre",
                     "this episode is sponsored"):
            self.assertTrue(DL._AD.search(text), text)
        for text in ("we announced the deal today", "a code red at OpenAI"):
            self.assertFalse(DL._AD.search(text), text)

    def test_the_prompt_says_ads_date_nothing_and_a_day_word_pins(self):
        task = " ".join(DL.DATING_TASK.split())
        self.assertIn("SPONSOR MESSAGES AND AD READS are recorded apart from the conversation", task)
        self.assertIn("A DAY WORD in the speaker's or the host's own words", task)
        self.assertIn("is a CEILING, never a floor", task)


class EvalForbiddenSource(unittest.TestCase):
    """A gold case may name pages the operator found to be about another occasion (forbid_sources): a confirmation
    from one is a wrong auto-confirmation even when its day falls inside the true range (OP7 r01's December 15)."""

    def test_a_confirmation_from_a_forbidden_page_is_a_hard_fail(self):
        import eval_prediction_cases as E  # noqa: PLC0415
        s = src(CASINO_URL, "Analytical Prediction Markets Entry Threatens Bookmakers, Says Analyst Posted on: "
                            "December 15, 2025")
        out = merge(KP, {"astra": kp_prop(sources=[s])}, {CASINO_URL: CASINO}, KP_COMPANY, V4)
        ex = {"negative": True, "pass_within": ["2025-12-02", "2025-12-15"]}
        self.assertEqual(E.judge_merge(ex, out)[0], "pass")
        status, detail = E.judge_merge({**ex, "forbid_sources": [CASINO_URL]}, out)
        self.assertEqual(status, "hard_fail")
        self.assertIn("a page about another occasion", detail)
        queued = merge(KP, {"astra": kp_prop(sources=[s])}, {CASINO_URL: CASINO}, KP_COMPANY, V5)
        self.assertEqual(E.judge_merge({**ex, "forbid_sources": [CASINO_URL]}, queued)[0], "pass")


if __name__ == "__main__":
    unittest.main()
