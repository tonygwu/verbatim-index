#!/usr/bin/env python3
"""The social card's "Words graded" is the page's number, computed by the same code.

WHY THIS EXISTS. build_og_card.py said its word total was "summed the same way
build_site.py sums it", and it was not. Since the membership work the page
counts only transcripts of people on the leaders board, refuses a record with no
`leader_slug`, and skips only unreadable files. The card summed every file under
the directory and swallowed any error. On 2026-10-11 both printed 9,020,532,
because no off-board transcript sat in data/transcripts_blind that day, so the
drift was latent: the first off-board transcript would have put a number on the
card that the page beside it does not show, and check_og_card() does not compare
words. Both now call build_site.words_graded().

  SAME      the card's total equals the page's total on a corpus holding an
            off-board transcript.
  OFF       neither counts the off-board transcript.
  ONE       there is one counting function, and the card calls it.

  .venv/bin/python scripts/test_og_card_words.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_words", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("social card words = page words")
    site, card = load("build_site"), load("build_og_card")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "transcripts_blind"
        for slug, words in (("on-board", 1000), ("off-board", 500)):
            (tdir / slug).mkdir(parents=True)
            (tdir / slug / "s1.json").write_text(json.dumps({"leader_slug": slug, "word_count": words}))
        membership = root / "membership.json"
        membership.write_text(json.dumps({"on-board": ["leaders", "predictions"], "off-board": ["predictions"]}))
        results = root / "results.json"
        results.write_text(json.dumps({"leaders": [], "diagnostics": {"judge_models": {"fable": ["m"]}}}))

        fn = getattr(site, "words_graded", None)
        check("build_site exposes words_graded()", callable(fn))
        page = None
        if callable(fn):
            import membership as MB
            board = MB.for_study("leaders", membership)
            page, off = fn(tdir, lambda s: MB.on_board(board, s, "leaders"))
            check("the page counts the on-board transcript and sets the off-board one aside",
                  page == 1000 and off == 500, f"page={page} off={off}")
        try:
            counts, _ = card.leaderboard_counts(SimpleNamespace(results=str(results), transcripts=str(tdir),
                                                                membership=str(membership)))
            drawn = counts.get("words_graded")
        except (SystemExit, Exception) as exc:  # noqa: BLE001
            drawn = f"{type(exc).__name__}: {exc}"
        check("the card's words graded equals the page's", drawn == page == 1000, f"card={drawn} page={page}")
    src = (REPO / "scripts" / "build_og_card.py").read_text()
    check("the card calls the page's function rather than summing on its own", "words_graded(" in src)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
