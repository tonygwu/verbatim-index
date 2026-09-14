#!/usr/bin/env python3
"""A recording is eligible or not ONCE, for both modes, so blinded and open grades stay paired.

Pundits plan, P5. filter_unscorable decides subject-share eligibility per
(person, recording, mode). For leaders that is the published behaviour and it
stays. For a contract v2 study it would break the pairing the halo needs: a
recording whose blinded judges estimate the share at 8% and whose open judges
estimate 30% would be dropped in one mode and kept in the other. With
pool_modes=True every judge's estimate across BOTH modes decides once.

  POOLED     the mean over both modes decides, and the decision covers both modes
  ANY-ZERO   a zero from any judge in either mode drops the recording in both
  NEVER-SPLIT a randomised corpus never leaves a recording in exactly one mode
  LEADERS    pool_modes defaults to off, so the leaders behaviour is unchanged

  .venv/bin/python scripts/test_eligibility_pairing.py
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load():
    spec = importlib.util.spec_from_file_location("agg_pair", REPO / "scripts" / "aggregate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def g(slug: str, sid: str, mode: str, judge: str, share: int) -> dict:
    return {"leader_slug": slug, "source_id": sid, "mode": mode, "judge": judge,
            "grade": {"subject_speech_share_pct": share}}


def modes_kept(kept: list[dict], slug: str, sid: str) -> set[str]:
    return {x["mode"] for x in kept if x["leader_slug"] == slug and x["source_id"] == sid}


def main() -> int:
    print("eligibility pairing")
    A = load()
    corpus = [g("p", "split", "blinded", "fable", 8), g("p", "split", "blinded", "astra", 9),
              g("p", "split", "open", "fable", 30), g("p", "split", "open", "astra", 31),
              g("p", "zero", "blinded", "fable", 60), g("p", "zero", "open", "astra", 0),
              g("p", "fine", "blinded", "fable", 70), g("p", "fine", "open", "fable", 72)]

    print("\n[LEADERS]")
    kept, _ = A.filter_unscorable(corpus, 10)
    check("without pool_modes a split recording is kept in one mode only (leaders behaviour)",
          modes_kept(kept, "p", "split") == {"open"}, str(modes_kept(kept, "p", "split")))

    print("\n[POOLED]")
    try:
        kept, dropped = A.filter_unscorable(corpus, 10, pool_modes=True)
    except TypeError as exc:
        check("filter_unscorable accepts pool_modes", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1
    check("a recording whose pooled mean clears the cutoff is kept in both modes",
          modes_kept(kept, "p", "split") == {"blinded", "open"}, str(modes_kept(kept, "p", "split")))

    print("\n[ANY-ZERO]")
    check("a zero in one mode drops the recording in both",
          modes_kept(kept, "p", "zero") == set() and len([x for x in dropped if x["source_id"] == "zero"]) == 2)
    check("an ordinary recording is kept in both", modes_kept(kept, "p", "fine") == {"blinded", "open"})
    check("every grade is in exactly one bucket", len(kept) + len(dropped) == len(corpus))

    print("\n[NEVER-SPLIT]")
    rng = random.Random(20260914)
    big = [g(f"p{p}", f"s{s}", mode, judge, rng.choice([0, 3, 7, 9, 11, 14, 40, 80]))
           for p in range(6) for s in range(8) for mode in ("blinded", "open") for judge in ("fable", "astra", "gemini")]
    kept, _ = A.filter_unscorable(big, 10, pool_modes=True)
    splits = [(p, s) for p in range(6) for s in range(8)
              if len(modes_kept(kept, f"p{p}", f"s{s}")) == 1]
    check("no recording in a randomised corpus is kept in exactly one mode", splits == [], str(splits[:5]))
    kept_off, _ = A.filter_unscorable(big, 10)
    splits_off = [(p, s) for p in range(6) for s in range(8) if len(modes_kept(kept_off, f"p{p}", f"s{s}")) == 1]
    check("while the per-mode rule does split some, so the test can see a split", len(splits_off) > 0)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
