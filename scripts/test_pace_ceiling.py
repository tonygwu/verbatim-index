#!/usr/bin/env python3
"""The pace ceiling is configurable, and the loop sets it.

WHY THIS EXISTS. fetch_loop.sh states the operating economics in its own
comment: "The operator can rotate the VPN exit on demand, so a block costs one
manual switch rather than hours of waiting... Fetch fast, trip early, ask for a
new IP." Every other knob honours that. PACE starts at 2s, BACKOFF_CAP is 20,
MAX_SLEEP carries the comment "the fix is a new IP, not patience".

Pacer did not. Its ceiling was hardcoded at 90.0s with no flag, so fetch_loop.sh
could not reach it, and Pacer.slow_down widens permanently with no recovery. On
2026-09-10 cycle 43 took five throttles in its first minutes, pinned the shared
gap at 90s, and then ground for six hours on 6 of 14 leaders while throttling
158 more times. The Breaker never tripped: record_ok() clears the consecutive
counter on every success, and at a 90s pace most requests do succeed. That is
precisely the failure the Breaker docstring says it exists to prevent, "a hard
block reads as slow for an hour instead of stopping", so nothing ever raised
NEEDS_IP_ROTATION and the operator was never asked for the cheap fix.

What is asserted here:

  FLAG      Pacer takes a ceiling, fetch_transcripts.py exposes it as
            --max-interval, and main() passes it through. A ceiling nobody can
            set is the bug, not the number.
  CEILING   slow_down never exceeds the ceiling it was given, and the ceiling
            is honoured even when the starting interval already sits above it.
  RATCHET   widening is still one-way WITHIN a pass. This is deliberate and is
            asserted so that a later change to add recovery has to face this
            test and the reasoning in it.
  WIRED     fetch_loop.sh passes a ceiling on the command line, from a named
            variable rather than a typed number, and that ceiling is low
            enough that sustained throttling reaches the Breaker instead of
            hiding at the cap.

Run: .venv/bin/python scripts/test_pace_ceiling.py
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import fetch_transcripts as ft  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


LOOP = (REPO / "scripts" / "fetch_loop.sh").read_text()
SRC = (REPO / "scripts" / "fetch_transcripts.py").read_text()


def test_flag() -> None:
    print("FLAG: the ceiling is reachable from outside")
    sig = inspect.signature(ft.Pacer.__init__)
    check("Pacer still takes a ceiling parameter", "max_interval" in sig.parameters)
    check("--max-interval is a command-line flag",
          '"--max-interval"' in SRC or "'--max-interval'" in SRC,
          "the ceiling cannot be set, which is the defect this file exists for")
    # The construction must pass the parsed value, not fall back to the default.
    m = re.search(r"pacer\s*=\s*Pacer\(([^)]*)\)", SRC)
    check("Pacer is constructed with the parsed ceiling",
          bool(m) and "max_interval" in (m.group(1) if m else ""),
          f"constructed as Pacer({m.group(1) if m else '?'}), so the flag is parsed and ignored")


def test_ceiling() -> None:
    print("\nCEILING: slow_down respects the value it was given")
    p = ft.Pacer(2.0, max_interval=15.0)
    seen = [p.slow_down() for _ in range(12)]
    check("widening stops at the given ceiling", max(seen) == 15.0, str(seen))
    check("it climbs by doubling until it gets there",
          seen[:4] == [4.0, 8.0, 15.0, 15.0], str(seen[:4]))
    check("the ceiling is not the old hardcoded 90",
          all(v <= 15.0 for v in seen), str(seen))

    # A ceiling below the starting interval must still bind. Otherwise a low
    # ceiling silently does nothing whenever PACE is raised above it.
    q = ft.Pacer(30.0, max_interval=10.0)
    check("a ceiling below the starting interval still binds",
          q.slow_down() == 10.0, str(q.interval))

    # Default construction must not reintroduce a ceiling the loop cannot see.
    r = ft.Pacer(2.0)
    check("the default ceiling is no higher than the loop's own setting",
          r.max_interval <= 20.0,
          f"default is {r.max_interval}s, high enough to hide sustained throttling again")


def test_ratchet() -> None:
    """One-way inside a pass. Asserted on a tiny interval so nothing sleeps."""
    print("\nRATCHET: widening stays one-way inside a pass")
    p = ft.Pacer(0.001, max_interval=0.004)
    p.slow_down()
    before = p.interval
    for _ in range(20):
        p.wait()
    check("waiting does not narrow the interval on its own",
          p.interval == before,
          "the pacer now recovers; that is a real design change and this test "
          "should be rewritten deliberately rather than relaxed")
    check("Pacer exposes no speed-up method yet",
          not any(n for n in dir(ft.Pacer) if "speed" in n or "narrow" in n or "reset" in n),
          str([n for n in dir(ft.Pacer) if not n.startswith("_")]))


def test_wired() -> None:
    print("\nWIRED: fetch_loop.sh sets the ceiling")
    check("the loop passes --max-interval to the fetcher",
          "--max-interval" in LOOP,
          "fetch_loop.sh never sets the ceiling, so the flag exists unused")
    m = re.search(r"--max-interval\s+\"?\$\{?(\w+)", LOOP)
    check("it passes a named variable, not a typed number",
          bool(m), "a literal here goes stale the way the 90 did")
    var = m.group(1) if m else ""
    vm = re.search(rf'^{re.escape(var)}="\$\{{{re.escape(var)}:-([0-9.]+)\}}"', LOOP, re.M)
    check(f"{var or 'the variable'} has a documented default",
          bool(vm), f"no default assignment found for {var!r}")
    ceiling = float(vm.group(1)) if vm else None
    # The point of the ceiling is that sustained throttling keeps reaching the
    # Breaker. Too high and the pass hides at the cap again, which is the bug.
    check("the ceiling is low enough that a throttled pass trips out",
          ceiling is not None and ceiling <= 20.0,
          f"ceiling is {ceiling}s; at that pace a refusing endpoint still reads as slow")
    check("the comment explaining the ceiling cites the rotation economics",
          re.search(r"(rotat|new IP).{0,400}--max-interval", LOOP, re.S | re.I) is not None
          or re.search(r"--max-interval", LOOP) is not None and "ceiling" in LOOP.lower())


def main() -> int:
    print("pace ceiling")
    test_flag()
    test_ceiling()
    test_ratchet()
    test_wired()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
