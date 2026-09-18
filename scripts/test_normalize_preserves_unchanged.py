#!/usr/bin/env python3
"""Normalize leaves a derived file alone when its content has not changed.

FOUND 2026-09-17, before starting `STUDY=pundits fetch_loop.sh`. The loop runs QA
and normalize over EVERY transcript after each productive pass. Normalize wrote
every output file unconditionally and stamped it with the current time in
`normalization.normalized_at_utc`. A controlled run of the loop's exact commands
into a scratch directory, compared with the live pundits corpus:

    blinded: 114 existing files -> identical 0, DIFFERENT 114
    fields that differ: normalization.normalized_at_utc (114 of 114), nothing else

The blinded TEXT was identical in every file. But the pundits grade cache keys on
`input_sha256 = sha256(path.read_bytes())`, the whole file, so the timestamp alone
would have moved the input hash of all 114 pilot recordings and made all 308
grades `stale_cache`: refused on reuse, and only recoverable with `--force`, which
buys the same grades again with hundreds of judge calls.

It also broke the stamp's one reader. `withdraw_sources.regrade()` reads
`normalized_at_utc` as WHEN THIS TEXT WAS WRITTEN and skips a re-grade when every
grade post-dates it. Restamping unchanged text every cycle made every grade look
older than its text, which is the 27-wasted-calls case that function exists to
prevent.

So an existing file whose content equals the new record, the stamp aside, is
KEPT, bytes and stamp both. Anything else is written with a fresh stamp.

  KEEP       a second identical normalize leaves the file byte-identical
  STAMP      and keeps the original timestamp, which is what the stamp means
  CHANGED    a change to the text is written, with a new stamp
  META       a change to any other normalization field is written too
  FRESH      a file that does not exist yet is written
  DAMAGED    an unreadable existing file is replaced, never trusted
  COUNTED    main() reports how many files it kept, so the run is auditable

  .venv/bin/python scripts/test_normalize_preserves_unchanged.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def rec(text="the speaker said a thing", stamp="2026-09-15T00:00:00Z", blind_total=3):
    return {"leader_slug": "p", "source_id": "s", "text": text, "word_count": len(text.split()),
            "normalization": {"mode": "blinded", "normalized_at_utc": stamp,
                              "blind_substitutions": {"name": blind_total}, "blind_total": blind_total}}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    print("normalize preserves unchanged derived files")
    import normalize_transcripts as N

    if not hasattr(N, "write_if_changed"):
        check("normalize_transcripts exposes write_if_changed", False,
              "every output is rewritten and restamped unconditionally")
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "p" / "s.json"

        print("\n[FRESH]")
        st = N.write_if_changed(dest, rec(stamp="2026-09-15T00:00:00Z"))
        check("a file that does not exist is written", dest.exists() and st == "written", st)
        before = sha(dest)

        print("\n[KEEP]")
        st = N.write_if_changed(dest, rec(stamp="2026-09-17T09:09:09Z"))
        check("an identical record, stamp aside, is reported unchanged", st == "unchanged", st)
        check("and the file is byte-identical, so input_sha256 does not move", sha(dest) == before)

        print("\n[STAMP]")
        kept = json.loads(dest.read_text())["normalization"]["normalized_at_utc"]
        check("the original timestamp survives, because the text was not rewritten",
              kept == "2026-09-15T00:00:00Z", kept)

        print("\n[CHANGED]")
        st = N.write_if_changed(dest, rec(text="the speaker said another thing", stamp="2026-09-18T00:00:00Z"))
        got = json.loads(dest.read_text())
        check("a change to the text is written", st == "written" and got["text"].endswith("another thing"), st)
        check("with the new timestamp", got["normalization"]["normalized_at_utc"] == "2026-09-18T00:00:00Z")

        print("\n[META]")
        st = N.write_if_changed(dest, rec(text="the speaker said another thing",
                                          stamp="2026-09-19T00:00:00Z", blind_total=4))
        check("a change to another normalization field is written", st == "written", st)

        print("\n[DAMAGED]")
        dest.write_text("{not json")
        st = N.write_if_changed(dest, rec())
        check("an unreadable existing file is replaced rather than trusted",
              st == "written" and json.loads(dest.read_text())["text"] == rec()["text"], st)

    print("\n[COUNTED]")
    src = (REPO / "scripts" / "normalize_transcripts.py").read_text()
    main_src = src[src.index("def main("):]
    check("main() writes through write_if_changed", "write_if_changed(" in main_src)
    check("and its summary reports how many files it kept", '"kept_unchanged"' in main_src)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
