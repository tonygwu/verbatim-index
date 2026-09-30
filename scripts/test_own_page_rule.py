#!/usr/bin/env python3
"""The recording's own page never counts, whatever host serves it.

Final review of the combined branch, 2026-09-30, item 8. dating_lib.own_page_reason
refuses YouTube pages by host. Three shapes got through:
  - a fully qualified host with its trailing dot, www.youtube.com./watch?v=x, which
    the host comparison did not match;
  - YouTube's own page shapes served by a mirror whose name the lists do not carry:
    /watch?v=, /channel/UC... and /@handle on inv.nadeko.net or hooktube.com;
  - ghostarchive.org, a web archive like archive.today, whose copy of an unknown
    page may be a copy of the recording's own.
A watch page dates an upload and a channel page lists them; neither dates the event.

Controls pin what must still pass: an ordinary dated page, a Medium post under an
@author path and a Mastodon post under an @user path (a post can date an event),
and a watch page's WORDS inside an ordinary article's path.

  .venv/bin/python scripts/test_own_page_rule.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dating_lib as DL  # noqa: E402
from test_dating import D10  # noqa: E402


class Refused(unittest.TestCase):
    def assert_refused(self, url):
        self.assertIsNotNone(DL.own_page_reason(url, D10), url)

    def test_a_trailing_dot_on_the_host(self):
        for url in ("https://www.youtube.com./watch?v=someOtherVid", "https://youtu.be./someOtherVid",
                    "https://m.youtube.com./@ReUploads", "https://liveblog.example.com./2012/05/30/ada-live"):
            if "liveblog" in url:
                self.assertIsNone(DL.own_page_reason(url, D10), url)
            else:
                self.assert_refused(url)

    def test_youtube_page_shapes_on_any_host(self):
        for url in ("https://inv.nadeko.net/watch?v=someOtherVid", "https://hooktube.com/watch?v=someOtherVid",
                    "https://inv.nadeko.net/watch?list=PL1&v=someOtherVid",
                    "https://inv.nadeko.net/channel/UCabcdefghijklmnop", "https://hooktube.com/channel/UCxyz/videos",
                    "https://inv.nadeko.net/@ReUploads", "https://hooktube.com/@ReUploads/videos",
                    "https://inv.nadeko.net/@ReUploads/streams"):
            self.assert_refused(url)

    def test_ghostarchive_is_an_archive_copy(self):
        for url in ("https://ghostarchive.org/varchive/youtube/20190227/someOtherVid",
                    "https://ghostarchive.org/archive/AbCdE"):
            self.assert_refused(url)

    def test_a_wayback_copy_of_a_mirror(self):
        self.assert_refused("http://web.archive.org/web/2019/https://hooktube.com/watch?v=someOtherVid")


class StillAllowed(unittest.TestCase):
    def test_controls(self):
        for url in ("https://liveblog.example.com/2012/05/30/ada-live",
                    "https://medium.com/@reporter/ada-at-dx-2012-a1b2c3",
                    "https://mastodon.social/@reporter/109876543210",
                    "https://news.example.com/2012/05/30/watch-ada-live-at-dx",
                    "https://news.example.com/channel/tech/2012/ada",
                    "https://news.example.com/watch?id=5"):
            self.assertIsNone(DL.own_page_reason(url, D10), url)


if __name__ == "__main__":
    unittest.main()
