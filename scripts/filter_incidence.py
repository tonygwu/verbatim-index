#!/usr/bin/env python3
"""Who does a validation filter actually bite? Report it, never assume it is even.

The working agreement: "Any cap, truncation, or sampling is reported with what it
cut and for which group; a limit that bites one group 10x more than another is a
bias, not a detail."

FOUND by adversarial audit 2026-09-16. The pundits rubric caps every evidence
quote at 25 words, and a grade that overruns it fails validation entirely. Across
the P8a2 corpus it rejected 12 grades and nothing reported the shape of that
loss. It was not even: Gemini took 10 of 12, Gemini blinded took 8 against Gemini
open 2, and one person carried 5. Reported as "about 8% of calls" it reads as a
uniform tax on the corpus, which it is not.

This measures. It does not change the cap. The cap is hashed into contract_id
through RUBRIC.md and judge_output.schema.json, so moving it makes every grade
already collected incompatible; that decision is recorded in BACKLOG.md.

  .venv/bin/python scripts/filter_incidence.py --study pundits \
      --logs data-pundits/logs/p8a2 data-pundits/logs/p8a \
      --obsolete data-pundits/grades/_obsolete
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# A group taking this many times another group's RATE is called skewed. Not a
# round number by accident: the working agreement names 10x as obviously a bias,
# and a factor of 3 is where a difference stops being explainable by chance at
# the counts these corpora carry.
SKEW_RATIO = 3.0


def read_rejections(paths: list[Path], match: str) -> list[dict]:
    """Pull matching failures out of grade.py error logs (JSONL).

    `match` is tested against the failure's detail text, so the caller names the
    filter it is measuring rather than this file hard-coding one.
    """
    out: list[dict] = []
    for p in paths:
        if not Path(p).exists():
            continue
        for line in Path(p).read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue  # a half-written line from a live run
            if match not in (r.get("detail") or ""):
                continue
            tid = r.get("id") or "/"
            out.append({"judge": r.get("judge"), "mode": r.get("mode"),
                        "slug": tid.split("/", 1)[0], "source_id": tid.split("/", 1)[-1],
                        "error": r.get("detail", "")[:200]})
    return out


def read_obsolete(root: Path, match: str) -> list[dict]:
    """Rejected grade records that `grade.py --force` or the cache repair set aside."""
    out: list[dict] = []
    if not Path(root).exists():
        return out
    for p in sorted(Path(root).rglob("*.json")):
        d = json.loads(p.read_text())
        errs = " ".join(d.get("validation_errors") or [])
        if match not in errs:
            continue
        out.append({"judge": d.get("judge"), "mode": d.get("mode"),
                    "slug": d.get("leader_slug"), "source_id": d.get("source_id"),
                    "error": errs[:200]})
    return out


def incidence(rejections: list[dict], attempted: dict[tuple[str, str], int]) -> dict:
    """Break the loss down by judge, mode and person, as counts AND as rates.

    A bare count cannot show bias: a judge with twice the calls should take twice
    the rejections. The rate is against that group's own attempted calls, which
    is the only form in which two groups are comparable.
    """
    by_judge = Counter(r["judge"] for r in rejections)
    by_mode = Counter(r["mode"] for r in rejections)
    by_person = Counter(r["slug"] for r in rejections)
    by_cell = Counter((r["judge"], r["mode"]) for r in rejections)

    att_judge: Counter = Counter()
    att_mode: Counter = Counter()
    for (j, m), n in attempted.items():
        att_judge[j] += n
        att_mode[m] += n
    rate_by_judge = {j: round(by_judge.get(j, 0) / n, 4) for j, n in att_judge.items() if n}
    rate_by_mode = {m: round(by_mode.get(m, 0) / n, 4) for m, n in att_mode.items() if n}

    skewed, note = False, ""
    rates = {j: r for j, r in rate_by_judge.items() if r > 0}
    if len(rate_by_judge) >= 2 and rates:
        hi = max(rate_by_judge, key=lambda j: rate_by_judge[j])
        lo = min(rate_by_judge, key=lambda j: rate_by_judge[j])
        if rate_by_judge[lo] == 0 and rate_by_judge[hi] > 0:
            skewed = True
            note = (f"{hi} is rejected at {rate_by_judge[hi]:.1%} and {lo} never; the filter is "
                    f"not measuring the same thing in both arms")
        elif rate_by_judge[lo] > 0 and rate_by_judge[hi] / rate_by_judge[lo] >= SKEW_RATIO:
            skewed = True
            note = (f"{hi} is rejected at {rate_by_judge[hi]:.1%} against {lo} at "
                    f"{rate_by_judge[lo]:.1%}, a ratio of "
                    f"{rate_by_judge[hi] / rate_by_judge[lo]:.1f}x")
    return {"total": len(rejections),
            "by_judge": dict(by_judge), "by_mode": dict(by_mode),
            "by_person": dict(by_person), "by_judge_mode": {f"{j}/{m}": n for (j, m), n in by_cell.items()},
            "rate_by_judge": rate_by_judge, "rate_by_mode": rate_by_mode,
            "skewed": skewed, "skew_note": note}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--logs", nargs="*", default=[], help="directories or files of grade error JSONL")
    ap.add_argument("--obsolete", default=None, help="a grades _obsolete/ tree")
    ap.add_argument("--match", default="cap is 25", help="text identifying the filter in a failure detail")
    ap.add_argument("--attempted", type=int, default=None,
                    help="calls attempted per (judge, mode) cell; the rate denominator")
    ap.add_argument("--judges", default="fable,gemini")
    args = ap.parse_args()

    files: list[Path] = []
    for p in args.logs:
        p = Path(p)
        files.extend(sorted(p.glob("*.jsonl")) if p.is_dir() else [p])
    rej = read_rejections(files, args.match)
    seen = {(r["judge"], r["mode"], r["slug"], r["source_id"]) for r in rej}
    if args.obsolete:
        for r in read_obsolete(Path(args.obsolete), args.match):
            if (r["judge"], r["mode"], r["slug"], r["source_id"]) not in seen:
                rej.append(r)
                seen.add((r["judge"], r["mode"], r["slug"], r["source_id"]))

    judges = [j.strip() for j in args.judges.split(",") if j.strip()]
    n = args.attempted or 0
    attempted = {(j, m): n for j in judges for m in ("blinded", "open")}
    rep = incidence(rej, attempted)
    rep["match"] = args.match
    rep["sources"] = [str(f) for f in files] + ([args.obsolete] if args.obsolete else [])
    print(json.dumps(rep, indent=2, sort_keys=True))
    if rep["skewed"]:
        print(f"\nSKEWED: {rep['skew_note']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
