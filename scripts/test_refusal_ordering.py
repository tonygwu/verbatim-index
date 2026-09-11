#!/usr/bin/env python3
"""A refusal is split out BEFORE the scorable filter, not after.

WHY THIS EXISTS. aggregate.py split records in this order:

    excluded = [g for g in grades if g.get("_excluded")]      # split out
    grades, unscorable = filter_unscorable(grades, ...)       # refusals still here
    for g in unscorable: if "subject_speech_share_pct" not in ...: raise
    refusals = [g for g in grades if g.get("refused")]        # too late

A refusal carries no subject_speech_share_pct, because the judge declined to
read the recording that way. It therefore fell into `unscorable` and tripped the
NOT A GRADE guard, which is working exactly as designed: it refuses to publish
rather than smooth a missing share into a default.

On 2026-09-11 astra refused mark-zuckerberg/hs-sacha-baron-cohen-has-a-message-
for-mark-zuc, correctly, since the recording is Kara Swisher interviewing Sacha
Baron Cohen ABOUT Zuckerberg, who never speaks. grade.py did its job and wrote
`refused: true` with the reason. aggregate.py then died on every cycle for three
cycles running, and data/results.json plus site/index.html silently kept serving
the last build that succeeded.

This is the SAME reorder aggregate.py already applied to `_excluded`, and the
same reasoning: a record that failed validation should not get a vote on whether
a recording is scorable, and neither should a judge who declined to score it.

What is asserted here:

  SURVIVES  a corpus containing an unshared refusal aggregates successfully
            instead of dying on the guard.
  COUNTED   the refusal appears in judge_refusals and in the per-leader
            breakdown, so it is reported rather than silently dropped.
  EXCLUDED  the refusal contributes no score to its leader.
  STILL_LOUD a record that is NOT a refusal and NOT marked invalid, yet carries
            no share, must still stop the run. The fix must not become a
            blanket tolerance for missing shares.

Pure checks: no network, no quota, no data/.

  .venv/bin/python scripts/test_refusal_ordering.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if not cond and detail else ""))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ri = load("test_render_integrity")
LEADERS = ["alpha", "beta", "gamma"]
N = 6


def a_refusal(leader: str, src: str) -> dict:
    """The shape grade.py writes when a judge declines: refused=true, no share."""
    return {
        "transcript_id": f"{leader}/{src}", "leader_slug": leader, "source_id": src,
        "judge": "astra", "mode": "blinded", "run": 0,
        "graded_at_utc": "2026-09-11T06:15:29Z", "grading_contract": ri.CONTRACT,
        "elapsed_sec": 1.0, "telemetry": {}, "validation_errors": [],
        "refused": True,
        "refusal_reason": "I cannot assign numerical scores to this political material.",
        "grade": {"transcript_id": f"{leader}/{src}", "status": "unscored",
                  "reason": "declined", "attribution_notes": "subject does not speak"},
    }


def build(root: Path, poison) -> tuple[Path, Path]:
    grades = root / "grades"
    roster = {"roster": [{"rank": i + 1, "slug": s, "name": s.title(),
                          "company": f"C{i}", "sector": "AI"}
                         for i, s in enumerate(LEADERS)]}
    (root / "roster.json").write_text(json.dumps(roster))
    for li, leader in enumerate(LEADERS):
        for t in range(N):
            for judge in ("fable", "astra", "gemini"):
                rec = ri.a_grade(leader, f"src{t}", judge, 60, 55 + li * 6 + t)
                d = grades / judge / leader
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(json.dumps(rec))
    if poison is not None:
        # The poisoned record must sit on a transcript the share filter DROPS,
        # because that is how production reached the guard. filter_unscorable
        # works per TRANSCRIPT: the other judges put the subject at 0, which
        # drops every grade sharing that key, and the refusal rides along with
        # no share of its own. A refusal on a transcript nobody else graded is
        # simply kept and never reaches the guard.
        src = poison["source_id"]
        for judge in ("fable", "gemini"):
            rec = ri.a_grade(LEADERS[0], src, judge, 0, 1)   # share 0 = subject absent
            d = grades / judge / LEADERS[0]
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{src}__{judge}__blinded__r0.json").write_text(json.dumps(rec))
        d = grades / "astra" / LEADERS[0]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{src}__astra__blinded__r0.json").write_text(json.dumps(poison))
    return grades, root / "roster.json"


def run(poison):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        g, r = build(tmp, poison)
        out = tmp / "results.json"
        proc = ri.run_aggregate(REPO / "scripts" / "aggregate.py", g, r, out)
        data = json.loads(out.read_text()) if out.exists() else None
        return proc, data


def main() -> int:
    print("refusal ordering")

    print("\nSURVIVES / COUNTED / EXCLUDED: an unshared refusal")
    proc, data = run(a_refusal(LEADERS[0], "poison"))
    check("aggregate publishes instead of dying on the guard",
          proc.returncode == 0, (proc.stderr or proc.stdout)[-500:])
    if data:
        dg = data["diagnostics"]
        check("the refusal is counted in judge_refusals",
              dg.get("judge_refusals", 0) >= 1, str(dg.get("judge_refusals")))
        check("the per-leader breakdown names the leader and the judge",
              LEADERS[0] in (dg.get("judge_refusals_by_leader") or {}),
              str(list((dg.get("judge_refusals_by_leader") or {}))))
        by = {l["slug"]: l for l in data["leaders"]}
        check("the refusal contributes no transcript to its leader",
              by.get(LEADERS[0], {}).get("n_transcripts") == N,
              f"n_transcripts={by.get(LEADERS[0], {}).get('n_transcripts')}, expected {N}")
        check("no record without a share reached the unscorable report",
              all(u.get("subject_share_pct") is not None
                  for u in dg.get("unscorable_detail", [])))

    print("\nSTILL_LOUD: a non-refusal with no share must still stop the run")
    bad = a_refusal(LEADERS[0], "poison2")
    bad.pop("refused")                 # not a refusal, not marked invalid
    bad.pop("refusal_reason", None)
    proc2, _ = run(bad)
    check("aggregate still refuses to publish a bare non-grade",
          proc2.returncode != 0,
          "the reorder became a blanket tolerance for missing shares")
    check("and it still names the offending record",
          "NOT A GRADE" in (proc2.stderr or "") + (proc2.stdout or ""),
          (proc2.stderr or proc2.stdout)[-300:])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
