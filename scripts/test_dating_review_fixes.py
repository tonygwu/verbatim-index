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


if __name__ == "__main__":
    unittest.main()
