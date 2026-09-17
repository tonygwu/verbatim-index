#!/usr/bin/env python3
"""The documented pacing constant is the one the fetcher actually uses.

FOUND 2026-09-17, while sizing the fetch for the 29 roster people who have no
transcripts. `fetch_transcripts.py` carries this, with its reasoning:

    # Pacing follows the yt-dlp wiki, which is the only primary source with
    # numbers: a guest session gets roughly 1000 requests an hour, and 5 to 10
    # seconds between requests is the stated remedy for HTTP 429. The first
    # version of this file used 1.5 seconds, which is about four times too fast,
    # and the IP was blocked within the hour.
    DEFAULT_INTERVAL = 6.0

`DEFAULT_INTERVAL` appeared exactly once in the file: its own definition. The CLI
default was 2.0, on an argument whose help text says "5 to 10 seconds". At the
default 6 workers that is one request every 0.33 seconds, against a documented
guest ceiling of one every 3.6 seconds.

WHAT IT COST, measured from the P6 pilot's own error logs:

    fetch_errors.jsonl          218 errors, 202 of them IP blocks
    retry1  218 / 202     retry2  202 / 186     retry3  182 / 166
    retry4    3 /   3     retry5    3 /   3     retry6    0 /   0

Six retry passes to clear a block on 248 candidates. The Pacer and the Breaker
both worked and reported honestly; they were handed a rate that could not work.

This is the third time in this repo that a constant and the value in force
disagreed, after the hand-typed judge list and the TARGET default that read 5
while every real run passed 14. The lesson each time is the same: a number
written in one place and consumed in another goes stale silently, so the test
asserts they are the SAME object rather than that they happen to match today.

  WIRED      the CLI default IS DEFAULT_INTERVAL, not a copy of its value
  DOCUMENTED the constant sits in the band its own comment cites
  EFFECTIVE  the run reports interval / workers, which is the real rate
  LOUD       a configuration over the documented ceiling warns, naming numbers
  QUIET      a configuration inside the ceiling does not cry wolf

  .venv/bin/python scripts/test_fetch_pacing_default.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []

# yt-dlp wiki: a guest session gets roughly 1000 webpage or player requests an
# hour, which is one request every 3.6 seconds.
DOCUMENTED_GUEST_SECONDS_PER_REQUEST = 3.6


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("fetch pacing default")
    import fetch_transcripts as F

    print("\n[WIRED]")
    src = (REPO / "scripts" / "fetch_transcripts.py").read_text()
    check("the CLI default for --min-interval is the DEFAULT_INTERVAL constant",
          'default=DEFAULT_INTERVAL' in src,
          "a literal here drifts from the constant; that is the whole defect")
    check("DEFAULT_INTERVAL is referenced somewhere other than its own definition",
          src.count("DEFAULT_INTERVAL") >= 2, f"appears {src.count('DEFAULT_INTERVAL')} time(s)")

    print("\n[DOCUMENTED]")
    check("DEFAULT_INTERVAL sits in the 5-to-10 second band its comment cites",
          5.0 <= F.DEFAULT_INTERVAL <= 10.0, f"DEFAULT_INTERVAL={F.DEFAULT_INTERVAL}")
    check("and it is not faster than the documented guest ceiling",
          F.DEFAULT_INTERVAL >= DOCUMENTED_GUEST_SECONDS_PER_REQUEST,
          f"{F.DEFAULT_INTERVAL} < {DOCUMENTED_GUEST_SECONDS_PER_REQUEST}")

    print("\n[EFFECTIVE]")
    check("the module exposes effective_rate", hasattr(F, "effective_rate"))
    if hasattr(F, "effective_rate"):
        r = F.effective_rate(interval=6.0, workers=6)
        check("N workers divide the interval, because each one sleeps on its own",
              abs(r["seconds_per_request"] - 1.0) < 1e-6, str(r))
        check("it reports the requests per hour that implies",
              abs(r["requests_per_hour"] - 3600.0) < 1.0, str(r))
        check("and whether that is over the documented ceiling",
              r["over_documented_ceiling"] is True, str(r))
        ok = F.effective_rate(interval=6.0, workers=1)
        check("one worker at the default is inside the ceiling",
              ok["over_documented_ceiling"] is False, str(ok))

    print("\n[LOUD]")
    if hasattr(F, "pacing_warning"):
        w = F.pacing_warning(interval=2.0, workers=6)
        check("the pilot's own settings produce a warning", bool(w), repr(w))
        check("and it names the effective rate rather than saying 'too fast'",
              w and "0.33" in w, repr(w))
        check("and it names the documented figure it is compared against",
              w and "3.6" in w, repr(w))
    else:
        check("the module exposes pacing_warning", False)

    print("\n[QUIET]")
    if hasattr(F, "pacing_warning"):
        check("a safe configuration produces no warning",
              F.pacing_warning(interval=6.0, workers=1) is None,
              repr(F.pacing_warning(interval=6.0, workers=1)))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
