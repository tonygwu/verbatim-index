#!/usr/bin/env python3
"""The fetch target defaults to what the corpus can actually supply.

WHY THIS EXISTS. Two separate problems shared one cause: the default was 5.

FIRST, 5 is not the number anyone runs. Every real invocation passed
TARGET=14 in the environment, so the default existed only to be overridden.
On 2026-09-11 fetch_loop.sh was restarted without it, read the default, found
every leader already above 5, and printed "COMPLETE: all 50 leaders have 5
transcripts" in under a second. A default nobody uses is a trap, not a default.

SECOND, 14 was never reachable. MEASURED on 2026-09-11: the YouTube manifest
was built with a median of exactly 14 candidates per leader for a target of
14, so it assumed every candidate would work. Across the corpus, fetch keeps
93% of candidates and QA keeps 92% of those, about 85% combined. 14 candidates
therefore yield about 12, and ten of the twelve leaders short of target were
sitting on exactly 12. Both fetch sources are now exhausted, so 12 is not a
compromise; it is what the sources hold.

What is asserted here:

  DEFAULT   both loops default to the same number, and it is 12.
  REASON    the default carries the measurement that produced it, so the next
            person changing it has to face the arithmetic.
  SEPARATE  TARGET reaches NO published number. It is a fetching goal. The
            board is gated by MIN_TRANSCRIPTS_TO_RANK, and conflating the two
            is how "at target" gets mistaken for "on the board".

Pure checks: reads the scripts. No network, no quota, no data/.

  .venv/bin/python scripts/test_target_default.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


FETCH = (REPO / "scripts" / "fetch_loop.sh").read_text()
HS = (REPO / "scripts" / "happyscribe_loop.sh").read_text()
EXPECTED = 12


def default_of(src: str) -> float | None:
    m = re.search(r'^TARGET="\$\{TARGET:-([0-9]+)\}"', src, re.M)
    return int(m.group(1)) if m else None


def main() -> int:
    print("fetch target default")

    f, h = default_of(FETCH), default_of(HS)
    check("fetch_loop.sh declares a TARGET default", f is not None)
    check("happyscribe_loop.sh declares a TARGET default", h is not None)
    check(f"fetch_loop.sh defaults to {EXPECTED}", f == EXPECTED,
          f"default is {f}; 5 is the value that made the loop exit COMPLETE in "
          f"under a second, and 14 is unreachable from the manifest")
    check(f"happyscribe_loop.sh defaults to {EXPECTED}", h == EXPECTED, f"default is {h}")
    check("both loops agree on the target", f == h,
          f"fetch_loop={f}, happyscribe_loop={h}; two targets means two "
          f"definitions of 'at target' in the same corpus")

    # A bare number is how the reasoning gets lost and 14 comes back.
    for name, src in (("fetch_loop.sh", FETCH), ("happyscribe_loop.sh", HS)):
        idx = src.find('TARGET="${TARGET:-')
        preceding = src[max(0, idx - 900):idx]
        check(f"{name} explains the target with its measurement",
              any(w in preceding for w in ("85%", "candidates", "manifest", "exhaust")),
              "no comment records why this number and not another")

    # The distinction that this session got loose about. TARGET is a fetching
    # goal; it must not leak into anything that publishes a score.
    for mod in ("aggregate.py", "build_site.py"):
        src = (REPO / "scripts" / mod).read_text()
        check(f"{mod} does not read a fetch TARGET",
              "TARGET" not in src,
              f"{mod} references TARGET; a fetching goal must not gate a published number")

    agg = (REPO / "scripts" / "aggregate.py").read_text()
    check("the board is gated by MIN_TRANSCRIPTS_TO_RANK instead",
          "MIN_TRANSCRIPTS_TO_RANK" in agg)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
