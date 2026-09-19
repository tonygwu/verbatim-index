#!/usr/bin/env python3
"""A transcript QA rejected does not count toward a leader's fetch target.

FOUND 2026-09-18 on the pundits fetch loop at TARGET=7. Three people stalled:

    jon-favreau   blinded 6  raw 7  manifest 24
    jon-stewart   blinded 6  raw 7  manifest 24
    matt-taibbi   blinded 6  raw 7  manifest 24

The loop measures its target in GRADEABLE transcripts (`--have-dir
transcripts_blind`), so it saw each at 6 of 7 and asked for more. `fetch_leader`
counted every file already on disk, `cached`, toward the target, including the one
QA had rejected, so it saw 7 of 7 and fetched nothing. The two counts never agree:
every pass came back empty, and the loop gives up after three with all three short.

This is the Michael Dell trap recorded in the working agreement (16 raw, 9
gradeable, reported "at target"). That fix reached the fewest-first ORDERING in
main(), which reads `--have-dir`, and never reached the count inside
`fetch_leader`, which decides when to stop.

With a have-dir, a cached file counts only if it is gradeable. A NEW fetch still
counts at once, because QA runs after the pass; a new file that QA later rejects is
caught the same way on the next pass. Without a have-dir the old raw count stands,
so a one-shot run is unchanged.

  REJECTED   a cached file absent from have_dir does not count, so the walk goes on
  GRADEABLE  a cached file present in have_dir counts
  NEW        a fresh fetch counts toward the target immediately
  STOPS      the walk still stops at the target, spending no extra request
  LEGACY     with no have_dir, every cached file counts, as before
  WIRED      main() passes --have-dir through to fetch_leader

  .venv/bin/python scripts/test_fetch_leader_gradeable.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("fetch_leader counts gradeable transcripts")
    import inspect
    import fetch_transcripts as F

    if "have_dir" not in inspect.signature(F.fetch_leader).parameters:
        check("fetch_leader takes have_dir", False,
              "it can only count raw files, including ones QA rejected")
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    def run(statuses, target, gradeable, use_have_dir=True):
        """statuses: per-candidate result; gradeable: source_ids present in have_dir."""
        calls = []

        def fake_fetch(c, *a, **k):
            calls.append(c["source_id"])
            return {"status": statuses[c["source_id"]], "source_id": c["source_id"]}

        real = F.fetch_with_retry
        F.fetch_with_retry = fake_fetch
        try:
            with tempfile.TemporaryDirectory() as td:
                have = Path(td) / "blind" / "p"
                have.mkdir(parents=True)
                for sid in gradeable:
                    (have / f"{sid}.json").write_text("{}")
                cands = [{"leader_slug": "p", "source_id": sid} for sid in statuses]
                F.fetch_leader("p", cands, target, Path(td) / "raw", 700, False,
                               F.Pacer(0.0), F.Breaker(),
                               have_dir=(Path(td) / "blind") if use_have_dir else None)
        finally:
            F.fetch_with_retry = real
        return calls

    # Seven cached, one of them rejected by QA, then fresh candidates.
    st = {f"c{i}": "cached" for i in range(7)} | {"n1": "ok", "n2": "ok"}
    good = {f"c{i}" for i in range(7)} - {"c3"}

    print("\n[REJECTED]")
    calls = run(st, 7, good)
    check("with one of seven cached files rejected, the walk reaches a new candidate",
          "n1" in calls, str(calls))

    print("\n[STOPS]")
    check("and stops as soon as the target is met, spending one request, not two",
          "n2" not in calls, str(calls))

    print("\n[GRADEABLE]")
    calls = run(st, 7, {f"c{i}" for i in range(7)})
    check("seven gradeable cached files meet the target with no new request",
          "n1" not in calls, str(calls))

    print("\n[NEW]")
    st2 = {"c0": "cached", "n1": "ok", "n2": "ok", "n3": "ok"}
    calls = run(st2, 3, {"c0"})
    check("a fresh fetch counts at once, so 1 gradeable + 2 new meets a target of 3",
          calls == ["c0", "n1", "n2"], str(calls))

    print("\n[LEGACY]")
    calls = run(st, 7, good, use_have_dir=False)
    check("with no have_dir every cached file counts, as before",
          "n1" not in calls, str(calls))

    print("\n[WIRED]")
    src = (REPO / "scripts" / "fetch_transcripts.py").read_text()
    main_src = src[src.index("def main("):]
    check("main() passes --have-dir through to fetch_leader",
          "have_dir=" in main_src[main_src.index("ex.submit(fetch_leader"):main_src.index("ex.submit(fetch_leader") + 400],
          "the flag would order by gradeable counts but still stop on raw ones")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
