#!/usr/bin/env python3
"""merge-4: the dating rules the operator's audit of 2026-10-04 asked for, each against merge-3.

The operator audited seven recordings whose dates the dating stage failed to
confirm; every date was findable. Each class below pins one finding with a
synthetic recording shaped like the real one, and runs the SAME input under
merge-3 (what production did: the failure) and merge-4 (the fix), so every test
here fails on the code before the fix. No private data, no quota, no network.

  EMBED      (a) an organiser's page that embeds the video may confirm a day before
             the upload (bill-gates/khosla-ventures-8bosqk, michael-dell/citi-z30abb);
             control (i): an embed page that shows only the upload day is refused
  RELATIVE   (b) "last November" in the description, read against the upload date
             (bill-gates/village-global-w5g4sp); control (iii): "Originally released
             March 9, 2020" never becomes the day of speech
  DATEONLY   (c, e) "March 2, 2021" alone counts beside the speaker and the host
             (dara-khosrowshahi/greylock-fhxo7v); control (iv): a bare date on an
             unrelated page, or far from the names, never confirms
  REWORDED   (e) "February 12, 2020" cited, "12 February 2020" printed
             (tim-sweeney/academy-of-interactive-a-h7tgad)
  REFINE     (f) a day confirmed inside another dater's confirmed month refines it
             (tim-sweeney/bafta-guru-cjxc-u); R1 still queues an awards-night page
             against an unconfirmed keynote day
  BOUNDS     (d) a proposal's range must sit inside its own floors and ceilings
  VERSIONS   (g) merge-3 stays re-runnable; an entry re-merges under the version it names
  PROMPT     (c, d) the prompt asks for host, interviewer and guest together, and for bounds

  .venv/bin/python scripts/test_dating_operator_rules.py
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
from test_dating import D10, doc_for, proposal  # noqa: E402

V3, V4 = "merge-3", "merge-4"


def fetched(html: str, url: str) -> dict:
    return {"status": 200, "final_url": url, "body": html.encode(), "via": "direct", "error": None}


def src(url: str, excerpt: str) -> dict:
    return {"url": url, "publisher": "x", "date_on_source": None, "verbatim_excerpt": excerpt, "kind": "primary"}


def doc(obj: dict, rec: dict, harness: str = "gemini", daters=("gemini",)) -> dict:
    return {**doc_for(obj, rec), "harness": harness, "daters": list(daters), "leads": []}


def merged(rec: dict, objs: dict, pages: dict, version: str) -> dict:
    """objs {harness: proposal}; every cited page is checked from `pages` with today's check_source."""
    docs, checks = [], {}
    for h, o in objs.items():
        docs.append(doc(o, rec, h, list(objs)))
        checks[h] = [DL.check_source(s, rec, fetched(pages[s["url"]], s["url"]), o) for s in o["sources"]]
    return DL.merge(rec, docs, checks, version=version)


# ---------------------------------------------------------------------------
# (a) a page that embeds the recording
# ---------------------------------------------------------------------------

KHOSLA = {"leader_slug": "bill-gates", "source_id": "khosla-ventures-xyz", "video_id": "vidKHOSLA01",
          "url": "https://www.youtube.com/watch?v=vidKHOSLA01", "yt_upload_date": "20140517",
          "yt_title": "Fireside chat - Vinod Khosla and Bill Gates", "yt_channel": "Khosla Ventures",
          "yt_description": "", "text": "[00:00:01] welcome everyone " + " ".join(f"w{i}" for i in range(400))}
SUMMIT_URL = "https://www.organiser.example/ceo-summit"
SUMMIT = ('<html><head><title>CEO Summit</title></head><body><h1>CEO Summit archive</h1>'
          '<div class="session"><iframe src="https://www.youtube.com/embed/vidKHOSLA01"></iframe>'
          '<h3>Fireside Chat with Bill Gates</h3><p>Vinod Khosla, Bill Gates</p><p>May 21, 2012</p></div>'
          '</body></html>')


def khosla_prop(day="2012-05-21", excerpt="Fireside Chat with Bill Gates Vinod Khosla, Bill Gates May 21, 2012",
                verdict="dated"):
    return proposal(verdict=verdict, e=day, l=day, sources=[src(SUMMIT_URL, excerpt)], tid="bill-gates/khosla-ventures-xyz",
                    event="Khosla Ventures CEO Summit fireside chat", reupload="no")


class Embed(unittest.TestCase):
    def test_an_organiser_page_that_embeds_the_video_and_dates_the_session_confirms(self):
        """Finding a: merge-3 refused the organiser's archive because it embeds the 2014 upload."""
        c = DL.check_source(khosla_prop()["sources"][0], KHOSLA, fetched(SUMMIT, SUMMIT_URL), khosla_prop())
        self.assertTrue(c["page_names_video_id"])
        ok3, why3 = DL.confirms(c, khosla_prop(), KHOSLA, V3)
        self.assertFalse(ok3)
        self.assertIn("embeds the recording's own video", why3)
        self.assertEqual(DL.confirms(c, khosla_prop(), KHOSLA, V4), (True, "confirms"))
        out = merged(KHOSLA, {"gemini": khosla_prop()}, {SUMMIT_URL: SUMMIT}, V4)
        self.assertEqual((out["outcome"], out["entry"]["statement_date"]), ("override", "2012-05-21"), out)

    def test_control_i_an_embed_page_showing_only_the_upload_day_is_refused(self):
        page = SUMMIT.replace("May 21, 2012", "May 17, 2014")
        obj = khosla_prop(day="2014-05-17", verdict="publication_only",
                          excerpt="Fireside Chat with Bill Gates Vinod Khosla, Bill Gates May 17, 2014")
        c = DL.check_source(obj["sources"][0], KHOSLA, fetched(page, SUMMIT_URL), obj)
        self.assertTrue(c["excerpt_found"])
        for v in (V3, V4):
            ok, why = DL.confirms(c, obj, KHOSLA, v)
            self.assertFalse(ok, v)
            self.assertIn("embeds the recording's own video", why)
        self.assertIn("not before the recording's own date 2014-05-17", DL.confirms(c, obj, KHOSLA, V4)[1])

    def test_an_upload_date_the_window_names_is_never_the_event_day(self):
        """A VideoObject beside the excerpt names uploadDate 2012-05-21: that day is an upload, of some copy.

        The window is what a later load can see, so only an uploadDate inside it is read; on a
        page that embeds THIS recording, its own upload day is refused wherever it stands.
        """
        page = SUMMIT.replace("<p>May 21, 2012</p>", '<script type="application/ld+json">{"@type":"VideoObject",'
                                                     '"name":"Fireside Chat with Bill Gates",'
                                                     '"uploadDate":"2012-05-21T10:00:00-07:00"}</script>')
        obj = khosla_prop(excerpt='"name":"Fireside Chat with Bill Gates","uploadDate":"2012-05-21T10:00:00-07:00"')
        c = DL.check_source(obj["sources"][0], KHOSLA, fetched(page, SUMMIT_URL), obj)
        self.assertEqual(c["found_in"], "markup")
        ok, why = DL.confirms(c, obj, KHOSLA, V4)
        self.assertFalse(ok)
        self.assertIn("uploadDate", why)

    def test_an_embed_page_on_a_recording_with_no_upload_date_is_refused(self):
        rec = {k: v for k, v in KHOSLA.items() if k != "yt_upload_date"}
        rec["fetched_at_utc"] = "2026-09-07T21:33:30Z"
        c = DL.check_source(khosla_prop()["sources"][0], rec, fetched(SUMMIT, SUMMIT_URL), khosla_prop())
        ok, why = DL.confirms(c, khosla_prop(), rec, V4)
        self.assertFalse(ok)
        self.assertIn("no upload date", why)

    def test_the_recordings_own_youtube_page_is_still_refused(self):
        s = src("https://www.youtube.com/watch?v=vidKHOSLA01", "Fireside Chat with Bill Gates May 21, 2012")
        self.assertIsNotNone(DL.own_page_reason(s["url"], KHOSLA))
        c = DL.refused_check(s, DL.own_page_reason(s["url"], KHOSLA))
        self.assertFalse(DL.confirms(c, khosla_prop(), KHOSLA, V4)[0])


# ---------------------------------------------------------------------------
# (b) a relative date in the description; control (iii)
# ---------------------------------------------------------------------------

VILLAGE = {"leader_slug": "bill-gates", "source_id": "village-xyz", "video_id": "vidVILLAGE1",
           "url": "https://www.youtube.com/watch?v=vidVILLAGE1", "yt_upload_date": "20190621",
           "yt_title": "Bill Gates on Startups", "yt_channel": "Village Global",
           "yt_description": ("We are honored to have Bill Gates among our LPs.\n—\nWe asked Bill to join us in San "
                              "Francisco for a fireside chat on the future of technology and the nature of innovation "
                              "and impact last November. Bill's passion inspires our founders."),
           "text": "[00:00:01] lessons from luminaries brought to you by village global " + " ".join(
               f"w{i}" for i in range(400))}
CITED = ("We asked Bill to join us in San Francisco for a fireside chat on the future of technology and the nature of "
         "innovation and impact last November")


def village_prop(e="2018-11-01", l="2018-11-30", ev=CITED):
    return proposal(e=e, l=l, sources=[], tid="bill-gates/village-xyz", description_evidence=ev, reupload="no",
                    event="Village Global Lessons from Luminaries: Bill Gates with Julia Hartz")


class Relative(unittest.TestCase):
    def test_last_november_in_the_description_is_read_against_the_upload(self):
        """Finding b: merge-3 said 'no date with a year'; merge-4 reads November 2018."""
        d3 = DL.check_description(VILLAGE, village_prop(), V3)
        self.assertFalse(d3["ok"])
        self.assertIn("no date with a year", d3["why"])
        d4 = DL.check_description(VILLAGE, village_prop(), V4)
        self.assertTrue(d4["ok"], d4)
        self.assertEqual(d4["spans"], [["2018-11-01", "2018-11-30"]])
        self.assertEqual(d4["read_as"], [{"text": "last November", "range": ["2018-11-01", "2018-11-30"],
                                          "against": "2019-06-21"}])
        out3 = DL.merge_one(VILLAGE, doc(village_prop(), VILLAGE), [], version=V3)
        self.assertEqual(out3["outcome"], "queue")
        out4 = DL.merge_one(VILLAGE, doc(village_prop(), VILLAGE), [], version=V4)
        self.assertEqual(out4["outcome"], "override", out4)
        e = out4["entry"]
        self.assertEqual((e["statement_date_earliest"], e["statement_date"], e["precision"]),
                         ("2018-11-01", "2018-11-30", "days"))
        self.assertEqual(e["source_url"], VILLAGE["url"])

    def test_a_relative_range_must_still_lie_inside_the_proposal(self):
        """The description says November; it cannot source a last day of November 2."""
        out = DL.merge_one(VILLAGE, doc(village_prop(l="2018-11-02"), VILLAGE), [], version=V4)
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "no_confirming_source"))

    def test_the_readings(self):
        def r(phrase, ref):
            m = DL._REL.search(phrase)
            got = DL.relative_range(m, date.fromisoformat(ref))
            return got and (got[0].isoformat(), got[1].isoformat())
        self.assertEqual(r("last November", "2019-06-21"), ("2018-11-01", "2018-11-30"))
        self.assertEqual(r("last November", "2019-11-20"), ("2018-11-01", "2018-11-30"))
        # Said in December, "last November" may be the one just ended or the year before: both.
        self.assertEqual(r("last November", "2019-12-10"), ("2018-11-01", "2019-11-30"))
        self.assertEqual(r("this past March", "2019-06-21"), ("2019-03-01", "2019-03-31"))
        self.assertEqual(r("earlier this year", "2019-06-21"), ("2019-01-01", "2019-06-20"))
        self.assertEqual(r("last year", "2019-06-21"), ("2018-01-01", "2018-12-31"))
        self.assertEqual(r("last month", "2019-06-21"), ("2019-05-01", "2019-05-31"))
        self.assertEqual(r("last summer", "2019-06-21"), ("2018-06-01", "2018-08-31"))
        self.assertEqual(r("last winter", "2019-06-21"), ("2018-12-01", "2019-02-28"))
        self.assertIsNone(DL._REL.search("in November we spoke"))     # a bare month is never read

    def test_a_relative_date_needs_an_upload_or_publication_date(self):
        rec = {k: v for k, v in VILLAGE.items() if k != "yt_upload_date"}
        rec["fetched_at_utc"] = "2026-09-07T22:38:26Z"
        d = DL.check_description(rec, village_prop(), V4)
        self.assertFalse(d["ok"])
        self.assertIn("no upload or publication date", d["why"])

    def test_control_iii_a_release_date_in_the_description_is_never_the_speech(self):
        """tim-sweeney/academy-of-interactive-a-h7tgad: the podcast's release date is a ceiling, not the keynote."""
        rec = {**VILLAGE, "leader_slug": "tim-sweeney", "source_id": "aias-xyz", "yt_upload_date": "20200819",
               "yt_description": "(Originally released March 9, 2020 on podcast services)\n\nFresh off his #DICE2020 "
                                 "keynote, Tim Sweeney joins Ted on the show."}
        obj = proposal(e="2020-03-09", l="2020-03-09", sources=[], tid="tim-sweeney/aias-xyz", reupload="no",
                       description_evidence="Originally released March 9, 2020 on podcast services")
        for v in (V3, V4):
            d = DL.check_description(rec, obj, v)
            self.assertFalse(d["ok"], v)
            self.assertIn("originally", d["why"].lower())
            out = DL.merge_one(rec, doc(obj, rec), [], version=v)
            self.assertEqual((out["outcome"], out["reason"]), ("queue", "no_confirming_source"), v)
        self.assertIsNone(DL.tier0_day(rec, "dated")[0])
        cued = {**rec, "yt_description": "We sat down with Tim, originally released last November."}
        obj2 = proposal(e="2019-11-01", l="2019-11-30", sources=[], tid="tim-sweeney/aias-xyz", reupload="no",
                        description_evidence="We sat down with Tim, originally released last November")
        self.assertFalse(DL.check_description(cued, obj2, V4)["ok"])


# ---------------------------------------------------------------------------
# (c, e) a date-only excerpt beside the speaker and the host; control (iv)
# ---------------------------------------------------------------------------

GREYLOCK = {"leader_slug": "dara-khosrowshahi", "source_id": "greylock-xyz", "video_id": "vidGREYLOCK",
            "url": "https://www.youtube.com/watch?v=vidGREYLOCK", "yt_upload_date": "20211201",
            "yt_title": "Uber CEO Dara Khosrowshahi on the Go Anywhere platform", "yt_channel": "Greylock",
            "yt_description": "", "text": "[00:00:01] welcome to our very first greylock iconversations " + " ".join(
                f"w{i}" for i in range(400))}
GREY_URL = "https://greylock.example/greymatter/uber-go-anywhere/"
GREY_PAGE = ('<html><head><title>Go Anywhere, Get Anything | Greylock</title>'
             '<meta property="article:published_time" content="2021-03-02T18:02:42+00:00" />'
             '<meta name="description" content="Uber CEO Dara Khosrowshahi sat down with Greylock general partner '
             'Reid Hoffman" /></head><body><p>Published: 03.02.21</p><p>In February, Greylock kicked off '
             'Iconversations.</p></body></html>')


def grey_prop(excerpt="March 2, 2021"):
    return proposal(verdict="publication_only", e="2021-02-02", l="2021-03-02", tid="dara-khosrowshahi/greylock-xyz",
                    sources=[src(GREY_URL, excerpt)], reupload="no", event="Greylock Iconversations interview",
                    host_organization="Greylock", interviewer="Reid Hoffman")


class DateOnly(unittest.TestCase):
    def test_a_date_alone_beside_the_speaker_and_the_host_confirms(self):
        """Findings c and e: merge-3 refused 'March 2, 2021' for having fewer than four words."""
        c = DL.check_source(grey_prop()["sources"][0], GREYLOCK, fetched(GREY_PAGE, GREY_URL), grey_prop())
        self.assertTrue(c["excerpt_found"], c)
        self.assertEqual(c["found_in"], "markup")
        ok3, why3 = DL.confirms(c, grey_prop(), GREYLOCK, V3)
        self.assertFalse(ok3)
        self.assertIn("fewer than 4 words", why3)
        self.assertEqual(DL.confirms(c, grey_prop(), GREYLOCK, V4), (True, "confirms"))
        out = merged(GREYLOCK, {"gemini": grey_prop()}, {GREY_URL: GREY_PAGE}, V4)
        e = out["entry"]
        self.assertEqual((out["outcome"], e["statement_date_earliest"], e["statement_date"], e["precision"]),
                         ("override", "2021-02-02", "2021-03-02", "days"), out)

    def test_control_iv_a_bare_date_on_an_unrelated_page_never_confirms(self):
        page = ('<html><body><p>March 2, 2021</p><p>Weather for Boston: rain, then sun.</p>'
                '<p>Dara Khosrowshahi</p></body></html>')     # the speaker alone, with no host or event
        c = DL.check_source(grey_prop()["sources"][0], GREYLOCK, fetched(page, GREY_URL), grey_prop())
        self.assertTrue(c["excerpt_found"])
        ok, why = DL.confirms(c, grey_prop(), GREYLOCK, V4)
        self.assertFalse(ok)
        self.assertIn("does not name the speaker together with", why)

    def test_names_far_from_the_date_do_not_count(self):
        page = ("<html><body><p>Dara Khosrowshahi talks to Greylock</p>" + "<p>filler words here</p>" * 60
                + "<p>March 2, 2021</p></body></html>")
        c = DL.check_source(grey_prop()["sources"][0], GREYLOCK, fetched(page, GREY_URL), grey_prop())
        self.assertFalse(DL.confirms(c, grey_prop(), GREYLOCK, V4)[0])

    def test_a_short_excerpt_that_is_not_a_date_alone_is_still_refused(self):
        obj = grey_prop(excerpt="Greylock March 2021")
        c = DL.check_source(obj["sources"][0], GREYLOCK, fetched(GREY_PAGE.replace("03.02.21", "Greylock March 2021"),
                                                                 GREY_URL), obj)
        ok, why = DL.confirms(c, obj, GREYLOCK, V4)
        self.assertFalse(ok)
        self.assertIn("not a date alone", why)

    def test_what_is_a_date_alone(self):
        self.assertTrue(DL.excerpt_is_date_only("March 2, 2021"))
        self.assertTrue(DL.excerpt_is_date_only("PST · February 2, 2021"))
        self.assertTrue(DL.excerpt_is_date_only("Published: 12:32 PM PDT · November 2, 2018"))
        self.assertFalse(DL.excerpt_is_date_only("Benj Edwards – Dec 2, 2025"))
        self.assertFalse(DL.excerpt_is_date_only("published in March"))


# ---------------------------------------------------------------------------
# (e) a date the page writes another way
# ---------------------------------------------------------------------------

AIAS = {"leader_slug": "tim-sweeney", "source_id": "aias-xyz", "video_id": "vidAIAS0001",
        "url": "https://www.youtube.com/watch?v=vidAIAS0001", "yt_upload_date": "20200819",
        "yt_title": "Epic Games Founder Tim Sweeney | The AIAS Game Maker's Notebook",
        "yt_channel": "Academy of Interactive Arts & Sciences", "yt_description": "",
        "text": "[00:00:01] i had the good fortune to grab tim sweeney just after his dice 2020 keynote " + " ".join(
            f"w{i}" for i in range(400))}
PCG_URL = "https://www.pcgamer.example/epic-ceo-tim-sweeney-condemns-loot-boxes/"
PCG = ("<html><head><title>Epic CEO Tim Sweeney condemns loot boxes | PC Gamer</title></head><body>"
       "<p>News By Andy Chalk Published 12 February 2020 In a wide-ranging keynote at DICE, Sweeney said that it's "
       "time for the game industry to move away from both.</p></body></html>")
WIKI_URL = "https://en.wikipedia.example/wiki/23rd_Annual_DICE_Awards"
WIKI = ("<html><head><title>23rd Annual D.I.C.E. Awards</title></head><body><p>The 23rd Annual D.I.C.E. Awards "
        "were held on February 13, 2020 at the DICE Summit in Las Vegas.</p></body></html>")


def keynote(excerpt="By Andy Chalk published February 12, 2020", url=PCG_URL):
    return proposal(e="2020-02-12", l="2020-02-12", sources=[src(url, excerpt)], tid="tim-sweeney/aias-xyz",
                    reupload="no", event="DICE Summit 2020 keynote interview")


def awards():
    return proposal(e="2020-02-11", l="2020-02-13", sources=[src(WIKI_URL, "were held on February 13, 2020")],
                    tid="tim-sweeney/aias-xyz", reupload="no", event="DICE Summit 2020 interview")


class Reworded(unittest.TestCase):
    def test_a_date_written_another_way_matches_and_confirms(self):
        c = DL.check_source(keynote()["sources"][0], AIAS, fetched(PCG, PCG_URL), keynote())
        self.assertTrue(c["excerpt_found"], c)
        self.assertEqual(c["page_span"], "By Andy Chalk Published 12 February 2020")
        self.assertEqual(DL.confirms(c, keynote(), AIAS, V3), (False, "the excerpt is not on the page"))
        self.assertEqual(DL.confirms(c, keynote(), AIAS, V4), (True, "confirms"))

    def test_a_different_day_written_another_way_never_matches(self):
        obj = keynote(excerpt="By Andy Chalk published February 13, 2020")
        c = DL.check_source(obj["sources"][0], AIAS, fetched(PCG, PCG_URL), obj)
        self.assertFalse(c["excerpt_found"])
        self.assertFalse(DL.confirms(c, obj, AIAS, V4)[0])

    def test_an_exact_match_keeps_the_window_merge3_kept(self):
        """check_source tries the exact match first, so a check merge-3 could read is the same check today."""
        obj = keynote(excerpt="By Andy Chalk Published 12 February 2020")
        c = DL.check_source(obj["sources"][0], AIAS, fetched(PCG, PCG_URL), obj)
        self.assertEqual(c["page_span"], "By Andy Chalk Published 12 February 2020")
        self.assertTrue(DL.confirms(c, obj, AIAS, V3)[0])


# ---------------------------------------------------------------------------
# (f) refinement inside a wider confirmed range; R1 decided
# ---------------------------------------------------------------------------

BAFTA = {"leader_slug": "tim-sweeney", "source_id": "bafta-xyz", "video_id": "vidBAFTA001",
         "url": "https://www.youtube.com/watch?v=vidBAFTA001", "yt_upload_date": "20190902",
         "yt_title": "BAFTA Celebrates: Epic Games | Interview with Tim Sweeney", "yt_channel": "BAFTA Guru",
         "yt_description": "", "text": "[00:00:01] present Epic Games with this very special BAFTA award " + " ".join(
             f"w{i}" for i in range(400))}
GETTY_URL = "https://photos.example/detail/news-photo/sweeney-bafta"
GETTY = ("<html><head><title>Tim Sweeney at BAFTA Presents Special Award to Epic Games</title></head><body><p>Tim "
         "Sweeney speaks onstage at the BAFTA Presents Special Award to Epic Games at The London on June 12, 2019 in "
         "West Hollywood, California</p></body></html>")
EPIC_URL = "https://en.wikipedia.example/wiki/Epic_Games"
EPIC = ("<html><head><title>Epic Games</title></head><body><p>Epic Games received the BAFTA Special Award in June "
        "2019 for its impact on the games industry; Tim Sweeney accepted it.</p></body></html>")


def bafta_day():
    return proposal(e="2019-06-12", l="2019-06-12", tid="tim-sweeney/bafta-xyz", reupload="no",
                    event="BAFTA Special Award to Epic Games", sources=[src(
                        GETTY_URL, "Tim Sweeney speaks onstage at the BAFTA Presents Special Award to Epic Games at The "
                                   "London on June 12, 2019")])


def bafta_month(e="2019-06-01", l="2019-06-30"):
    return proposal(e=e, l=l, tid="tim-sweeney/bafta-xyz", reupload="no", event="BAFTA Special Award to Epic Games",
                    sources=[src(EPIC_URL, "the BAFTA Special Award in June 2019")])


class Refine(unittest.TestCase):
    PAGES = {GETTY_URL: GETTY, EPIC_URL: EPIC, PCG_URL: PCG, WIKI_URL: WIKI,
             "https://gone.example/x": "<html><body>moved</body></html>"}

    def test_a_day_inside_another_daters_confirmed_month_refines_it(self):
        objs = {"gemini": bafta_day(), "fable": bafta_month()}
        out3 = merged(BAFTA, objs, self.PAGES, V3)
        self.assertEqual((out3["outcome"], out3["reason"]), ("queue", "dater_disagreement"))
        out4 = merged(BAFTA, objs, self.PAGES, V4)
        self.assertEqual((out4["outcome"], out4["entry"]["statement_date"]), ("override", "2019-06-12"), out4)
        c = out4["entry"]["confirmation"]
        self.assertEqual(c["lead"], "gemini")
        self.assertEqual(c["refines"], [{"dater": "fable", "range": ["2019-06-01", "2019-06-30"]}])
        self.assertEqual({x["proposal"] for x in c["source_checks"]}, {"gemini", "fable"})

    def test_the_narrow_day_leads_whichever_dater_gives_it(self):
        out = merged(BAFTA, {"gemini": bafta_month(), "fable": bafta_day()}, self.PAGES, V4)
        self.assertEqual((out["entry"]["statement_date"], out["entry"]["confirmation"]["lead"]), ("2019-06-12", "fable"))

    def test_a_day_outside_the_other_confirmed_range_still_disagrees(self):
        late = bafta_month(e="2019-06-13", l="2019-06-30")
        out = merged(BAFTA, {"gemini": bafta_day(), "fable": late}, self.PAGES, V4)
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "dater_disagreement"))

    def test_overlapping_ranges_that_both_allow_the_earlier_last_day_refine(self):
        """FOUND in the live run (village-global): Oct 22..Nov 2 from a page and Nov 1..30 from the
        description overlap without nesting; both allow November 2, the latest day all evidence allows."""
        early = bafta_day()
        early.update(speech_date_earliest="2019-05-20")              # 2019-05-20..2019-06-12
        objs = {"gemini": early, "fable": bafta_month()}              # 2019-06-01..2019-06-30
        self.assertEqual(merged(BAFTA, objs, self.PAGES, V3)["reason"], "dater_disagreement")
        out = merged(BAFTA, objs, self.PAGES, V4)
        self.assertEqual((out["outcome"], out["entry"]["statement_date"]), ("override", "2019-06-12"), out)
        self.assertEqual(out["entry"]["confirmation"]["refines"], [{"dater": "fable",
                                                                     "range": ["2019-06-01", "2019-06-30"]}])

    def test_r1_still_queues_an_awards_night_page_against_an_unconfirmed_keynote_day(self):
        """Decided: R1 is unchanged. Fable's page dates the awards night; Gemini named the keynote day."""
        gone = keynote(url="https://gone.example/x")
        out = merged(AIAS, {"gemini": gone, "fable": awards()}, self.PAGES, V4)
        self.assertEqual((out["outcome"], out["reason"]), ("queue", "dater_disagreement"), out)
        self.assertIn("rule R1", out["detail"])

    def test_the_keynote_page_found_in_another_wording_refines_the_awards_range(self):
        objs = {"gemini": keynote(), "fable": awards()}
        self.assertEqual(merged(AIAS, objs, self.PAGES, V3)["reason"], "dater_disagreement")
        out = merged(AIAS, objs, self.PAGES, V4)
        self.assertEqual((out["outcome"], out["entry"]["statement_date"]), ("override", "2020-02-12"), out)


# ---------------------------------------------------------------------------
# From the live run of 2026-10-04: transcript words, and a UTC ceiling
# ---------------------------------------------------------------------------

class TranscriptWords(unittest.TestCase):
    """Gemini dated michael-dell/citi-z30abb to Citi's own page and misspelled a name in its transcript
    quote; Fable with web tools joined three exact passages of bill-gates/khosla-ventures-8bosqk with '...'.
    merge-3 discarded both right dates."""

    def test_a_misquoted_transcript_line_no_longer_discards_a_page_confirmed_date(self):
        obj = khosla_prop()
        obj["transcript_evidence"] = "when I first heard about this from Brad Gersonner"
        page = SUMMIT.replace('<iframe src="https://www.youtube.com/embed/vidKHOSLA01"></iframe>', "")
        out3 = merged(KHOSLA, {"gemini": obj}, {SUMMIT_URL: page}, V3)
        self.assertEqual((out3["outcome"], out3["reason"]), ("queue", "transcript_evidence_not_found"))
        out4 = merged(KHOSLA, {"gemini": obj}, {SUMMIT_URL: page}, V4)
        self.assertEqual((out4["outcome"], out4["entry"]["statement_date"]), ("override", "2012-05-21"), out4)
        self.assertNotIn("internal_evidence", out4["entry"])          # the misquote is never cited

    def test_a_misquoted_proposal_takes_no_part_in_an_agreement_or_in_r1(self):
        bad = proposal(sources=[src("https://gone.example/x", "Ada at DX on May 30, 2012 in full")],
                       transcript_evidence="words that are nowhere in it at all")
        good = proposal(sources=[src("https://gone.example/x", "Ada at DX on May 30, 2012 in full")])
        out = merged(D10, {"gemini": good, "fable": bad}, {"https://gone.example/x": "<html>moved</html>"}, V4)
        self.assertEqual(out["outcome"], "queue", out)
        self.assertEqual(out["by_dater"], {"gemini": "no_confirming_source", "fable": "transcript_evidence_not_found"})
        a = DL.assess(D10, doc(bad, D10), [], V4)
        self.assertFalse(a["eligible"])

    def test_words_joined_with_an_ellipsis_are_found_fragment_by_fragment(self):
        rec = {**D10, "text": "[00:00:01] when that changed in 2008 basically four years ago I got some extra time "
                              "and one of our speakers tomorrow is Dan Gardner who wrote a book"}
        te = "when that changed in 2008, basically four years ago ... one of our speakers tomorrow is Dan Gardner"
        self.assertFalse(DL.transcript_evidence_found(rec, te, V3))
        self.assertTrue(DL.transcript_evidence_found(rec, te, V4))
        self.assertFalse(DL.transcript_evidence_found(rec, te.replace("Dan Gardner", "Ann Gardner"), V4))
        self.assertFalse(DL.transcript_evidence_found(rec, "nowhere ... at all", V4))


class UtcCeiling(unittest.TestCase):
    """A publication timestamp may ceil a 'dated' range of days; it still never dates a speech day."""

    def grey_dated(self, e="2021-02-02"):
        obj = grey_prop()
        obj.update(verdict="dated", speech_date_earliest=e)
        return obj

    def test_a_utc_publication_stamp_shows_the_last_day_of_a_dated_range(self):
        obj = self.grey_dated()
        c = DL.check_source(obj["sources"][0], GREYLOCK, fetched(GREY_PAGE, GREY_URL), obj)
        ok3, why3 = DL.confirms(c, obj, GREYLOCK, V3)
        self.assertFalse(ok3)
        ok4, why4 = DL.confirms(c, obj, GREYLOCK, V4)
        self.assertTrue(ok4, why4)
        out = merged(GREYLOCK, {"gemini": obj}, {GREY_URL: GREY_PAGE}, V4)
        self.assertEqual((out["outcome"], out["entry"]["statement_date_earliest"], out["entry"]["statement_date"]),
                         ("override", "2021-02-02", "2021-03-02"), out)

    def test_it_never_dates_a_single_day_of_speech(self):
        obj = self.grey_dated(e="2021-03-02")
        c = DL.check_source(obj["sources"][0], GREYLOCK, fetched(GREY_PAGE, GREY_URL), obj)
        ok, why = DL.confirms(c, obj, GREYLOCK, V4)
        self.assertFalse(ok)
        self.assertIn("UTC timestamps", why)


# ---------------------------------------------------------------------------
# (d) bounds
# ---------------------------------------------------------------------------

class Bounds(unittest.TestCase):
    TID = "ada/re-upload-abc123"

    def test_a_range_past_its_own_ceiling_is_invalid(self):
        obj = proposal(e="2025-12-01", l="2025-12-16", bounds=[
            {"kind": "floor", "date": "2025-12-02", "evidence": "OpenAI code red reported", "source_url": None},
            {"kind": "ceiling", "date": "2025-12-15", "evidence": "event on December 16th is upcoming",
             "source_url": None}])
        self.assertEqual(DL.validate_proposal(obj, self.TID, V3), [])
        errs = DL.validate_proposal(obj, self.TID, V4)
        self.assertTrue(any("after its own ceiling 2025-12-15" in e for e in errs), errs)
        self.assertTrue(any("before its own floor 2025-12-02" in e for e in errs), errs)

    def test_a_range_inside_its_bounds_and_a_proposal_with_none_validate(self):
        good = proposal(e="2025-12-02", l="2025-12-15", host_organization="The Knowledge Project",
                        interviewer="Shane Parrish", bounds=[
                            {"kind": "floor", "date": "2025-12-02", "evidence": "code red", "source_url": None},
                            {"kind": "ceiling", "date": "2025-12-15", "evidence": "Dec 16 upcoming", "source_url": None}])
        self.assertEqual(DL.validate_proposal(good, self.TID, V4), [])
        self.assertEqual(DL.validate_proposal(proposal(), self.TID, V4), [])

    def test_a_bad_bound_date_and_an_unknown_kind_are_refused(self):
        obj = proposal(bounds=[{"kind": "floor", "date": "2025-13-01", "evidence": "x", "source_url": None}])
        self.assertTrue(any("not a real" in e for e in DL.validate_proposal(obj, self.TID, V4)))
        obj = proposal(bounds=[{"kind": "around", "date": "2025-12-01", "evidence": "x", "source_url": None}])
        self.assertTrue(DL.validate_proposal(obj, self.TID, V4))


# ---------------------------------------------------------------------------
# (g) versions
# ---------------------------------------------------------------------------

class Versions(unittest.TestCase):
    def test_the_versions(self):
        """merge-6 (2026-10-09) is today's; merge-3 to merge-5 stay runnable (test_dating_merge6 pins merge-6).
        merge-6 changed only the agreement, so its source rule is merge-5's."""
        self.assertEqual(DL.MERGE_VERSION, "merge-6")
        self.assertEqual(DL.MERGE_VERSIONS, ("merge-3", "merge-4", "merge-5", "merge-6"))
        self.assertEqual(DL.RULE, DL.RULES["merge-5"])
        with self.assertRaises(ValueError):
            DL.merge_rank("merge-7")

    def write(self, root: Path, version: str) -> tuple[Path, dict]:
        rec = KHOSLA
        obj = khosla_prop(excerpt="Fireside Chat with Bill Gates Vinod Khosla, Bill Gates May 21, 2012")
        (root / "transcripts_open" / "bill-gates").mkdir(parents=True)
        (root / "transcripts_open" / "bill-gates" / "khosla-ventures-xyz.json").write_text(json.dumps(rec))
        run = root / "predictions" / "_experiments" / "dating-v"
        pp = run / "proposals" / "bill-gates" / "khosla-ventures-xyz.gemini.json"
        pp.parent.mkdir(parents=True)
        pp.write_text(json.dumps(doc(obj, rec)))
        ref = {"gemini": {"path": str(pp.relative_to(run)), "sha256": hashlib.sha256(pp.read_bytes()).hexdigest()}}
        page = SUMMIT.replace('<iframe src="https://www.youtube.com/embed/vidKHOSLA01"></iframe>', "")
        checks = {"gemini": [DL.check_source(obj["sources"][0], rec, fetched(page, SUMMIT_URL), obj)]}
        out = DL.merge(rec, [json.loads(pp.read_text())], checks, ref, run_rel="predictions/_experiments/dating-v",
                       version=version)
        self.assertEqual(out["outcome"], "override", out)
        entry = {**out["entry"], "confirmed_at_utc": "2026-10-04T00:00:00Z"}
        path = run / "overrides.json"
        path.write_text(json.dumps({"schema_version": 1, "overrides": {"bill-gates/khosla-ventures-xyz": entry}}))
        return path, entry

    def test_a_merge3_entry_re_merges_as_merge3_and_a_merge4_entry_as_merge4(self):
        for v in (V3, V4):
            with tempfile.TemporaryDirectory() as td:
                path, entry = self.write(Path(td), v)
                self.assertEqual(entry["confirmation"]["merge_version"], v)
                self.assertEqual(entry["confirmation"]["rule"], DL.RULES[v])
                got = L.load_statement_date_overrides(path, [Path(td) / "transcripts_open"])
                self.assertEqual(got["bill-gates/khosla-ventures-xyz"]["statement_date"], "2012-05-21")

    def test_relabelling_a_merge3_entry_as_merge4_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path, entry = self.write(Path(td), V3)
            e = copy.deepcopy(entry)
            e["confirmation"]["merge_version"] = V4
            path.write_text(json.dumps({"schema_version": 1, "overrides": {"bill-gates/khosla-ventures-xyz": e}}))
            with self.assertRaisesRegex(L.PredictionError, "differs from its re-merge"):
                L.load_statement_date_overrides(path, [Path(td) / "transcripts_open"])


# ---------------------------------------------------------------------------
# (c, d) the prompt
# ---------------------------------------------------------------------------

class Prompt(unittest.TestCase):
    def test_the_prompt_asks_for_the_combination_the_bounds_and_the_relative_description(self):
        prompt, _ = DL.build_dating_prompt(D10, [], harness="gemini")
        for words in ("host organization, the interviewer and the guest TOGETHER", "FLOOR", "CEILING",
                      '"bounds"', 'place the date "around" it', "the day before it",
                      "last November", "RELEASE date", "ceiling, never the day the words were spoken",
                      '"host_organization"', '"interviewer"', "EMBEDS the video"):
            self.assertIn(words, prompt)
        self.assertNotIn("Open the page", prompt)

    def test_the_schema_keeps_the_new_fields_optional_so_stored_proposals_still_validate(self):
        for k in ("host_organization", "interviewer", "bounds"):
            self.assertIn(k, DL.DATING_SCHEMA["properties"])
            self.assertNotIn(k, DL.DATING_SCHEMA["required"])

    def test_fable_with_web_is_told_it_may_search_and_open_pages(self):
        prompt, _ = DL.build_dating_prompt(D10, [], harness="fable_web")
        self.assertIn("WebSearch", prompt)
        self.assertIn("WebFetch", prompt)
        self.assertNotIn("You have no working tools", prompt)
        self.assertIn("You have no working tools", DL.build_dating_prompt(D10, [], harness="fable")[0])


if __name__ == "__main__":
    unittest.main()
