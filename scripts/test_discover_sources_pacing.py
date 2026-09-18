#!/usr/bin/env python3
"""Leaders discovery paces its requests too, not just pundits discovery.

WHAT WAS WRONG. Commit 9925c0e, "Discovery paces its own requests, because
nothing else paced them for it", changed `discover_pundits.py` and left
`discover_sources.py` alone. So the LEADERS path kept shelling out to yt-dlp with
no sleep flag, from EIGHT worker threads at once, while the pundits path ran
three workers at 1.5 seconds.

That is the configuration `BACKLOG.md` blames for the pundits P6 pilot producing
202 IP blocks in 218 first-pass errors, and the machine this was found on was
IP-blocked on YouTube at the time. The fix was written once and applied to one of
the two callers, which is the same shape as the judge list and the fetcher name
this repo has already paid for: one rule, several copies, one left behind.

MEASURED while checking whether P3 discovery could run at all: a single yt-dlp
`ytsearch` returned results normally while caption fetching was blocked. So the
block is per-endpoint, search still worked, and an unpaced 7-person run was
something this machine would have accepted right up until it did not.

`--sleep-requests` is the flag that covers data extraction, which is what a
`--flat-playlist` search is. `--sleep-interval` covers media downloads and does
not apply; `--limit-rate` caps bytes while a block counts requests.

  FLAG     the yt-dlp argv carries --sleep-requests
  VALUE    the interval is the one the caller asked for
  DEFAULT  the default is non-zero, so an unpaced run cannot happen by accident
  CONFIG   the CLI exposes both the interval and the workers
  MODEST   the shipped defaults are gentle rather than fast
  INTACT   the flags discovery already depended on are still passed

No network: the yt-dlp call is replaced by a recorder. No quota, no writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    return ok


class Recorder:
    """Stands in for subprocess.run and keeps every argv it was handed."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))

        class R:
            stdout = ""
            returncode = 0
        return R()


def main() -> int:
    import subprocess

    import discover_sources as D

    rec = Recorder()
    real = subprocess.run
    subprocess.run = rec
    try:
        D.search("cathie wood interview")
        D.search("tom lee outlook", sleep_requests=4.25)
    finally:
        subprocess.run = real

    check("both searches shelled out", len(rec.calls) == 2, str(len(rec.calls)))
    first, second = rec.calls

    print("[FLAG] the argv carries --sleep-requests")
    check("the default call passes it", "--sleep-requests" in first, " ".join(first))
    check("the explicit call passes it", "--sleep-requests" in second, " ".join(second))

    print("\n[VALUE] the interval is the one the caller asked for")
    check("the explicit 4.25 is passed through",
          second[second.index("--sleep-requests") + 1] == "4.25",
          " ".join(second))
    check("the default call passes the module default",
          first[first.index("--sleep-requests") + 1] == str(D.SLEEP_REQUESTS),
          " ".join(first))

    print("\n[DEFAULT] an unpaced run cannot happen by accident")
    check("SLEEP_REQUESTS is non-zero", D.SLEEP_REQUESTS > 0, str(D.SLEEP_REQUESTS))
    check("... and is at least a second", D.SLEEP_REQUESTS >= 1.0,
          f"{D.SLEEP_REQUESTS}; the yt-dlp wiki documents a guest session at "
          f"roughly 1000 requests an hour and a flat-playlist search paginates "
          f"internally")

    print("\n[CONFIG] the CLI exposes the interval and the workers")
    src = (REPO / "scripts" / "discover_sources.py").read_text()
    check("--sleep-requests is a flag", '"--sleep-requests"' in src)
    check("--workers is a flag", '"--workers"' in src)
    check("the worker default is the named constant, not a literal",
          "default=DEFAULT_WORKERS" in src,
          "a literal here is how the two discovery paths drifted apart")

    print("\n[MODEST] the shipped defaults are gentle rather than fast")
    check("workers default to 3 or fewer", D.DEFAULT_WORKERS <= 3,
          f"{D.DEFAULT_WORKERS}; it was 8, unpaced, which is the configuration "
          f"BACKLOG.md blames for 202 IP blocks")
    check("workers times the rate stays under one request a second",
          D.DEFAULT_WORKERS / D.SLEEP_REQUESTS <= 2.0,
          f"{D.DEFAULT_WORKERS} workers at {D.SLEEP_REQUESTS}s is "
          f"{D.DEFAULT_WORKERS / D.SLEEP_REQUESTS:.2f} requests a second")

    print("\n[INTACT] the flags discovery already depended on are still passed")
    for flag in ("--flat-playlist", "--no-warnings", "--print"):
        check(f"{flag} survives", flag in first, " ".join(first))
    check("the search target is still last",
          first[-1].startswith("ytsearch"), " ".join(first[-3:]))

    print("\n[PARITY] the two discovery paths agree on pacing")
    pund = (REPO / "scripts" / "discover_pundits.py").read_text()
    check("discover_pundits still paces", "--sleep-requests" in pund,
          "if pundits lost it, this file's premise is gone")
    check("neither path is unpaced",
          "--sleep-requests" in src and "--sleep-requests" in pund)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
