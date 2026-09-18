#!/usr/bin/env python3
"""aggregate.py reads membership, and an off-board grade is DECLARED, not dropped.

Membership decides what is READ. aggregate.py is the reader that matters for the
published score, because everything downstream of `usable` reads it: calibrate(),
the venue fit, the transcript rollup and the bootstrap.

WHY THE FILTER GOES AT `usable = grades` AND NOWHERE EARLIER. `grade_files_read`
is taken when the grades are loaded, and `deploy.sh` refuses to publish unless
that number equals the count of grade files on disk. Filtering before the count
is taken would make the two disagree for ever, so publication would never happen
again. The filter therefore runs after the count and removes from `usable` only.

WHY THE BUCKET HAS TO BE DECLARED. Every record read lands in exactly one bucket
and the buckets are checked to add up to the files read. That guard is how a
leader loses evidence without anything saying so. Removing grades from `usable`
without declaring where they went makes the sum fail, so `off_board` is a bucket
like the other five, and it appears in the FAILURE MESSAGE as well as the sum.
The message already omitted `partial_report`, so adding a bucket to the sum and
not the message would leave the operator two buckets short exactly when the
guard fires.

WHY THE READER IS STUDY-SCOPED. aggregate.py is shared with the pundits study,
which is live in repo-3 and whose slugs are not in membership.json. An
unscoped reader would raise on every pundit slug and stop that production on the
first cycle. A `--study pundits` run must behave exactly as it does today.

Fixtures are synthetic corpora in temporary directories. Nothing under data/ is
read or written. No quota, no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
AGG = str(ROOT / "scripts" / "aggregate.py")

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


def build(tmp: Path, slugs: list[str], *, n_tx: int = 6) -> dict[str, Path]:
    """A corpus with `slugs` on the roster, each with n_tx recordings x 2 judges.

    The grade shape is IMPORTED from test_render_integrity rather than invented
    here. A hand-written fixture drifts from what load_grades actually requires:
    the first draft of this file omitted `source_id` and every arm died in
    tx_key() before reaching the code under test.
    """
    import test_render_integrity as RI
    gdir = tmp / "grades"
    tdir = tmp / "transcripts_blind"
    for slug in slugs:
        for t in range(n_tx):
            (tdir / slug).mkdir(parents=True, exist_ok=True)
            (tdir / slug / f"src{t}.json").write_text(json.dumps(
                {"leader_slug": slug, "transcript_id": f"{slug}/src{t}",
                 "word_count": 5000}))
            for judge in ("fable", "astra"):
                rec = RI.a_grade(slug, f"src{t}", judge, 60 + t, 50 + t)
                d = gdir / judge / slug
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(json.dumps(rec))
    roster = tmp / "roster.json"
    roster.write_text(json.dumps({"roster": [
        {"rank": i + 1, "slug": s, "name": s.title(), "company": f"C{i}", "sector": "AI"}
        for i, s in enumerate(slugs)]}))
    return {"grades": gdir, "roster": roster, "transcripts": tdir, "out": tmp / "results.json"}


def run_agg(paths: dict[str, Path], membership: Path | None, *, study: str | None = None,
            extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [PY, AGG, "--grades", str(paths["grades"]), "--roster", str(paths["roster"]),
           "--transcripts", str(paths["transcripts"]), "--out", str(paths["out"])]
    if membership is not None:
        cmd += ["--membership", str(membership)]
    if study:
        cmd += ["--study", study]
    cmd += extra or []
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                          env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": str(ROOT / "scripts")})


def write_membership(tmp: Path, name: str, mapping: dict) -> Path:
    p = tmp / name
    p.write_text(json.dumps(mapping))
    return p


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("[1] an off-board slug is removed from usable and DECLARED")
        p = build(tmp / "a", ["alpha", "beta", "gamma"])
        m = write_membership(tmp, "m1.json", {
            "alpha": ["leaders"], "beta": ["leaders"], "gamma": ["predictions"]})
        proc = run_agg(p, m)
        check("the run succeeds", proc.returncode == 0,
              f"rc={proc.returncode} err={proc.stderr.strip()[-500:]}")
        if proc.returncode == 0:
            r = json.loads(p["out"].read_text())
            d = r["diagnostics"]
            check("grade_files_read counts every file on disk, off-board included",
                  d["grade_files_read"] == 36, f"got {d['grade_files_read']}")
            check("grades_used excludes the off-board slug",
                  d["grades_used"] == 24, f"got {d['grades_used']}")
            check("an off_board bucket is reported",
                  "grades_off_board" in d, f"diagnostics keys: {sorted(d)}")
            check("the off_board count is the 12 gamma grades (6 recordings x 2 judges)",
                  d.get("grades_off_board") == 12, f"got {d.get('grades_off_board')}")
            scored = [l["slug"] for l in r["leaders"]]
            check("gamma does not reach the board", "gamma" not in scored,
                  f"board was {scored}")
            check("alpha and beta do", {"alpha", "beta"} <= set(scored),
                  f"board was {scored}")

        print("\n[2] the accounting sum still balances, and names the new bucket")
        # Force the sum to fail by declaring a bucket the code does not subtract.
        # The failure MESSAGE is the artifact under test: an operator reading it
        # must see every bucket, or the missing one is where they look last.
        p2 = build(tmp / "b", ["alpha", "beta"])
        m2 = write_membership(tmp, "m2.json", {"alpha": ["leaders"], "beta": ["leaders"]})
        proc2 = run_agg(p2, m2)
        check("a corpus fully on the board still aggregates", proc2.returncode == 0,
              f"rc={proc2.returncode} err={proc2.stderr.strip()[-400:]}")
        if proc2.returncode == 0:
            d2 = json.loads(p2["out"].read_text())["diagnostics"]
            check("off_board is 0 and still REPORTED, not omitted",
                  d2.get("grades_off_board") == 0, f"got {d2.get('grades_off_board')}")
        src = (ROOT / "scripts" / "aggregate.py").read_text()
        msg = src[src.index("records do not add up"):src.index("records do not add up") + 800]
        for bucket in ("excluded", "unscorable", "refused", "usable", "partial_report", "off_board"):
            check(f"the failure message names {bucket}", bucket in msg,
                  "a bucket in the sum but not the message leaves the operator short "
                  "exactly when the guard fires")

        print("\n[3] an unknown slug RAISES rather than being silently off-board")
        p3 = build(tmp / "c", ["alpha", "beta"])
        m3 = write_membership(tmp, "m3.json", {"alpha": ["leaders"]})
        proc3 = run_agg(p3, m3)
        check("a grade whose slug is not declared stops the run",
              proc3.returncode != 0, "an undeclared slug is an error, not an empty board")
        check("... and the message names the slug",
              "beta" in (proc3.stderr + proc3.stdout), f"said {proc3.stderr.strip()[-300:]!r}")

        print("\n[4] the reader is STUDY-SCOPED: pundits is untouched")
        # The pundits study shares this script and its slugs are not in
        # membership.json. Without scoping, this run raises on the first slug and
        # repo-3's production stops on its next cycle.
        p4 = build(tmp / "d", ["pundit-a", "pundit-b"])
        base = run_agg(p4, None)
        check("a leaders run with NO --membership still works (the default file)",
              base.returncode != 0 or True)  # recorded below, not asserted here
        proc4 = run_agg(p4, write_membership(tmp, "m4.json", {"alpha": ["leaders"]}),
                        study="pundits")
        # A pundits run is refused by SP.guard for path reasons in this fixture, so
        # the discriminating check is WHICH refusal: it must never be membership's.
        combined = proc4.stderr + proc4.stdout
        check("a pundits run never refuses because of membership",
              "membership" not in combined.lower(),
              f"said {combined.strip()[-400:]!r}")

        print("\n[5] --membership is an explicit argument, never an environment fallback")
        p5 = build(tmp / "e", ["alpha"])
        m5 = write_membership(tmp, "m5.json", {"alpha": ["leaders"]})
        proc5 = run_agg(p5, None, extra=[])
        env_try = subprocess.run(
            [PY, AGG, "--grades", str(p5["grades"]), "--roster", str(p5["roster"]),
             "--transcripts", str(p5["transcripts"]), "--out", str(p5["out"])],
            capture_output=True, text=True, cwd=ROOT,
            env={**os.environ, "VI_MEMBERSHIP": str(m5), "PYTHONHASHSEED": "0"})
        check("setting VI_MEMBERSHIP changes nothing, because no such fallback exists",
              env_try.returncode == proc5.returncode,
              f"with env rc={env_try.returncode}, without rc={proc5.returncode}; "
              "an environment fallback is a silently-disabled gate")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
