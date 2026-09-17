#!/usr/bin/env python3
"""Discovery paces its own requests, because nothing else does it for discovery.

`fetch_transcripts.py` already carries the Pacer and Breaker from the
`polite-bulk-fetching` skill. `discover_pundits.py` carried neither: it shelled
out to yt-dlp with no sleep flag, from 4 worker threads at once.

SIZED 2026-09-17 for the 29 roster people who have no transcripts yet:

    64 channel-tabs at --playlist-end 600, each of which paginates internally
    152 searches
    216 yt-dlp invocations, roughly 816 underlying requests

The yt-dlp wiki documents a guest session at roughly 1000 webpage or player
requests per hour, so an unpaced run of this size sits at about 80% of the
hourly ceiling and delivers it in a burst. A YouTube IP block already made the
P6 pilot INCONCLUSIVE once.

`--sleep-requests` is the flag that covers data extraction, which is what a
flat-playlist listing and a search both are. `--sleep-interval` does not cover
them, and `--limit-rate` caps bytes while a block counts requests.

  FLAG       the yt-dlp argv carries --sleep-requests
  VALUE      the interval is what the caller asked for
  DEFAULT    the default is non-zero, so an unpaced run cannot happen by accident
  CONFIG     the CLI exposes it, and exposes workers
  MODEST     the shipped defaults are gentle rather than fast
  INTACT     the flags discovery already depended on are still passed

  .venv/bin/python scripts/test_discover_pundits_pacing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("discover_pundits pacing")
    import discover_pundits as D

    captured = {}

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return FakeProc()

    import subprocess
    real = subprocess.run
    subprocess.run = fake_run
    try:
        D._yt_dlp("https://example.invalid/@x/videos", 10, sleep_requests=2.5)
        argv = captured.get("argv") or []
    finally:
        subprocess.run = real

    print("\n[FLAG]")
    check("the yt-dlp argv carries --sleep-requests", "--sleep-requests" in argv, " ".join(map(str, argv)))

    print("\n[VALUE]")
    if "--sleep-requests" in argv:
        got = argv[argv.index("--sleep-requests") + 1]
        check("the interval is the one the caller asked for", str(got) == "2.5", f"got {got!r}")
    else:
        check("the interval is the one the caller asked for", False, "no flag to read")

    print("\n[DEFAULT]")
    import inspect
    sig = inspect.signature(D._yt_dlp)
    default = sig.parameters.get("sleep_requests")
    check("_yt_dlp takes a sleep_requests parameter", default is not None, str(sig))
    check("and its default is non-zero",
          default is not None and isinstance(default.default, (int, float)) and default.default > 0,
          str(default.default if default else None))

    print("\n[CONFIG]")
    src = (REPO / "scripts" / "discover_pundits.py").read_text()
    check("the CLI exposes --sleep-requests", '"--sleep-requests"' in src)
    check("the CLI still exposes --workers", '"--workers"' in src)

    print("\n[MODEST]")
    check("the shipped default pace is at least 1 second",
          getattr(D, "SLEEP_REQUESTS", 0) >= 1.0, f"SLEEP_REQUESTS={getattr(D, 'SLEEP_REQUESTS', None)}")
    check("the shipped default worker count is at most 3, because workers multiply the real rate",
          D.DEFAULT_WORKERS <= 3, f"DEFAULT_WORKERS={getattr(D, 'DEFAULT_WORKERS', None)}")

    print("\n[THREADED]")
    seen = {}

    def spy_lister(ch, depth, sleep_requests=None):
        seen["lister"] = sleep_requests
        return []

    def spy_searcher(q, sleep_requests=None):
        seen["searcher"] = sleep_requests
        return []

    D.discover({"slug": "x", "name": "X", "show": "S", "own_channels": [{"channel_id": "c"}], "handles": []},
               depth=5, lister=spy_lister, searcher=spy_searcher, sleep_requests=9.25)
    check("discover passes the interval down to the channel lister", seen.get("lister") == 9.25, str(seen))
    check("and down to the search path", seen.get("searcher") == 9.25, str(seen))
    src_main = src[src.index("def main("):]
    check("and main() hands the CLI value to discover, so the flag is not a no-op",
          "args.sleep_requests" in src_main and "ex.submit(discover" in src_main
          and "args.sleep_requests" in src_main[src_main.index("ex.submit(discover"):
                                                src_main.index("ex.submit(discover") + 120],
          "the CLI flag never reaches the request")

    print("\n[INTACT]")
    for flag in ("--flat-playlist", "--no-warnings", "--socket-timeout", "--playlist-end", "--print"):
        check(f"{flag} is still passed", flag in argv)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
