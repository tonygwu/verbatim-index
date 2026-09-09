#!/usr/bin/env python3
"""Guards for the render path: a record that is not a grade, and a silent failure.

Both defects are from 2026-09-09, and together they cost 13 hours of leaderboard.

WHAT HAPPENED. Astra refused tim-cook/the-bulwark-and-the-prof-zi07-f at
02:00:00Z and wrote a record whose "grade" object held one key, "error". Fable
had scored the same recording with a subject share of 0. filter_unscorable
decides in or out once per RECORDING, so the whole recording fell under the
cutoff and every grade for it went to the unscorable list, the refusal record
among them. The report built from that list read subject_speech_share_pct off
the refusal record, which has no dimensions, no overall and no share, and
aggregate.py died with KeyError.

The record already carried validation_errors and load_grades had already marked
it _excluded. The split that acts on that mark simply ran too late, AFTER the
share filter. That is defect one.

Defect two is why nobody noticed. grade_loop.sh chained aggregate and build_site
with &&, so a failure only skipped the "re-rendered" line. The loop graded 96
more transcripts across 58 cycles, never rebuilt the board, and then exited 0
saying "COMPLETE: nothing left to grade. leaderboard at site/index.html".

WHAT IS ASSERTED HERE.

  ORDER     an invalid record leaves before filter_unscorable, so nothing reads
            a field off a record that is not a grade. The fixture below
            reproduces the exact production KeyError against the pre-fix
            ordering, so this is a real regression test and not a restatement.
  NEUTRAL   the reorder moves no published number. MEASURED on the corpus of
            2026-09-09: of 1906 records, 14 are invalid, 6 of those carry a
            subject share, all 6 sit far above the cutoff, and 0 transcripts
            change their in-or-out verdict.
  TALLY     every record read lands in exactly one bucket and the buckets add
            up to the files read.
  LOUD-1    a record that is not a grade and was NOT marked invalid stops the
            run with a message naming it, rather than a bare KeyError that does
            not say which file to look at.
  LOUD-2    grade_loop.sh names a render failure, counts consecutive failures,
            and refuses to report COMPLETE over a board it could not rebuild.

Run: .venv/bin/python scripts/test_render_integrity.py
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(Path(sys.executable))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


# ---------------------------------------------------------------------------
# Fixture. Four leaders, six recordings each, two judges, all valid but one
# recording where the subject never speaks. That recording is the trap: it falls
# under MIN_SUBJECT_SHARE, so every grade attached to it reaches the unscorable
# report, including one that is not a grade at all.
# ---------------------------------------------------------------------------
LEADERS = [f"leader-{i}" for i in range(4)]
CONTRACT = {"contract_id": "test0001", "rubric_sha256": "a" * 64,
            "schema_sha256": "b" * 64, "rubric_bytes": 1, "schema_bytes": 1}


def a_grade(leader: str, src: str, judge: str, share: int, score: int) -> dict:
    return {
        "transcript_id": f"{leader}/{src}", "leader_slug": leader, "source_id": src,
        "judge": judge, "mode": "blinded", "run": 0,
        "graded_at_utc": "2026-09-09T00:00:00Z", "grading_contract": CONTRACT,
        "elapsed_sec": 1.0, "telemetry": {}, "validation_errors": [],
        "grade": {
            "schema_version": "1.0", "transcript_id": f"{leader}/{src}",
            "venue_type": "long_form_podcast", "venue_challenge": 3,
            "subject_speech_share_pct": share, "attribution_confidence": "high",
            "identity_guess": leader, "identity_confident": True, "identity_basis": "x",
            "asr_quality": "clean", "coverage": 1.0, "confidence": "high",
            "dimensions": {d: {"score": score + off, "reasoning": "r",
                               "counterevidence": "none",
                               "evidence": [{"quote": "q", "why": "w"}]}
                           for d, off in (("d1_clarity", 0), ("d2_insight", -2),
                                          ("d3_technical_depth", 1))},
            "subcriteria": [], "red_flags": [], "salient_claims": [],
            "overall": float(score),
        },
    }


def not_a_grade(leader: str, src: str, marked_invalid: bool) -> dict:
    """The shape Astra actually wrote when it refused: a "grade" holding an error.

    marked_invalid says whether validation caught it, which is the difference
    between the record being dropped quietly and the run stopping loudly.
    """
    return {
        "transcript_id": f"{leader}/{src}", "leader_slug": leader, "source_id": src,
        "judge": "astra", "mode": "blinded", "run": 0,
        "graded_at_utc": "2026-09-09T02:00:00Z", "grading_contract": CONTRACT,
        "elapsed_sec": 1.0, "telemetry": {},
        "validation_errors": ["dimension d1_clarity missing"] if marked_invalid else [],
        "grade": {"error": "I can't score reasoning about political campaigns."},
    }


def build_corpus(root: Path, poison: str | None) -> tuple[Path, Path]:
    """poison: None, "invalid" (validation caught it), or "unmarked" (it did not)."""
    root.mkdir(parents=True, exist_ok=True)
    grades = root / "grades"
    roster = {"roster": [{"rank": i + 1, "slug": s, "name": s.title(),
                          "company": f"C{i}", "sector": "AI"}
                         for i, s in enumerate(LEADERS)]}
    roster_path = root / "roster.json"
    roster_path.write_text(json.dumps(roster))

    def write(rec: dict) -> None:
        d = grades / rec["judge"] / rec["leader_slug"]
        d.mkdir(parents=True, exist_ok=True)
        name = f"{rec['source_id']}__{rec['judge']}__{rec['mode']}__r{rec['run']}.json"
        (d / name).write_text(json.dumps(rec))

    rnd = random.Random(7)
    for li, leader in enumerate(LEADERS):
        for t in range(6):
            # One recording where the subject never speaks. Everything else is
            # comfortably above the cutoff.
            share = 0 if (leader == LEADERS[0] and t == 0) else 60 + t
            for judge in ("fable", "astra"):
                write(a_grade(leader, f"src{t}", judge, share,
                              50 + li * 5 + t + rnd.randint(0, 3)))
    if poison:
        # Overwrites that recording's astra grade, exactly as the refusal did.
        write(not_a_grade(LEADERS[0], "src0", poison == "invalid"))
    return grades, roster_path


def run_aggregate(script: Path, grades: Path, roster: Path, out: Path,
                  cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(script), "--grades", str(grades), "--roster", str(roster),
         "--out", str(out)],
        capture_output=True, text=True, cwd=cwd,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO / "scripts")})


# ---------------------------------------------------------------------------
# 1. The fixture must reproduce the production crash against the OLD ordering.
#    Without this the rest of the file proves only that today's code runs.
# ---------------------------------------------------------------------------
def build_prefix_copy(tmp: Path) -> Path | None:
    """Rebuild the pre-fix ordering from today's source, or return None."""
    src = (REPO / "scripts" / "aggregate.py").read_text()
    split = '''    excluded = [g for g in grades if g.get("_excluded")]
    grades = [g for g in grades if not g.get("_excluded")]

    grades, unscorable = filter_unscorable'''
    if split not in src:
        return None
    src = src.replace(split, "    grades, unscorable = filter_unscorable", 1)
    guard_start = src.find('    for g in unscorable:\n        if "subject_speech_share_pct" not in')
    report_start = src.find("    unscorable_report = [{")
    if -1 in (guard_start, report_start) or guard_start > report_start:
        return None
    src = src[:guard_start] + src[report_start:]
    src = src.replace("    usable = grades\n",
                      '    excluded = [g for g in grades if g.get("_excluded")]\n'
                      '    usable = [g for g in grades if not g.get("_excluded")]\n', 1)
    # The tally check postdates the fix, so it does not belong in the old copy.
    tally = src.find("    accounted = len(excluded)")
    tally_end = src.find("dropped or double-counted between load_grades and here.\")", tally)
    if -1 in (tally, tally_end):
        return None
    src = src[:tally] + src[tally_end + len("dropped or double-counted between load_grades and here.\")"):]
    p = tmp / "aggregate_prefix.py"
    p.write_text(src)
    return p


def test_fixture_reproduces_the_crash(tmp: Path) -> None:
    print("\n[1] the fixture reproduces the production KeyError against the pre-fix ordering")
    old = build_prefix_copy(tmp)
    if old is None:
        check("the pre-fix ordering could be reconstructed from source", False,
              "aggregate.py no longer has the shape this test knows how to invert; "
              "update build_prefix_copy or this file proves nothing")
        return
    grades, roster = build_corpus(tmp / "witness", "invalid")
    r = run_aggregate(old, grades, roster, tmp / "witness" / "results.json")
    check("the OLD ordering dies on the refusal record",
          r.returncode != 0 and "KeyError: 'subject_speech_share_pct'" in r.stderr,
          f"rc={r.returncode} stderr tail={r.stderr[-300:]}")


# ---------------------------------------------------------------------------
# 2. Today's ordering survives the same corpus, and accounts for the record.
# ---------------------------------------------------------------------------
def test_invalid_record_is_split_out_first(tmp: Path) -> None:
    print("\n[2] an invalid record leaves before the share filter can read a field off it")
    agg = REPO / "scripts" / "aggregate.py"
    grades, roster = build_corpus(tmp / "fixed", "invalid")
    out = tmp / "fixed" / "results.json"
    r = run_aggregate(agg, grades, roster, out)
    check("aggregate.py completes with a refusal record on an unscorable recording",
          r.returncode == 0, f"rc={r.returncode} stderr tail={r.stderr[-400:]}")
    if r.returncode != 0:
        return
    d = json.loads(out.read_text())
    diag = d["diagnostics"]
    check("the record is counted as excluded rather than lost",
          diag["grades_excluded_validation"] == 1, json.dumps(diag)[:200])
    check("and it never appears in the unscorable report",
          all(row["judge"] != "astra" for row in diag["unscorable_detail"]),
          json.dumps(diag["unscorable_detail"]))
    check("the recording it belongs to is still filtered out on its own merits",
          diag["unscorable_subject_absent"] >= 1)
    check("every record read lands in exactly one bucket",
          diag["grades_excluded_validation"] + diag["unscorable_subject_absent"]
          + diag["grades_used"] == diag["grade_files_read"],
          f"{diag['grades_excluded_validation']} + {diag['unscorable_subject_absent']}"
          f" + {diag['grades_used']} != {diag['grade_files_read']}")


def test_the_reorder_moves_no_published_number(tmp: Path) -> None:
    print("\n[3] dropping the invalid record earlier changes no published score")
    agg = REPO / "scripts" / "aggregate.py"
    a_g, a_r = build_corpus(tmp / "with", "invalid")
    b_g, b_r = build_corpus(tmp / "without", None)
    a_out, b_out = tmp / "with" / "results.json", tmp / "without" / "results.json"
    ra = run_aggregate(agg, a_g, a_r, a_out)
    rb = run_aggregate(agg, b_g, b_r, b_out)
    if ra.returncode != 0 or rb.returncode != 0:
        check("both corpora aggregate", False, f"{ra.returncode} {rb.returncode}")
        return
    a, b = json.loads(a_out.read_text()), json.loads(b_out.read_text())
    check("the published leader block is identical with and without the record",
          a["leaders"] == b["leaders"],
          "an invalid record is moving a published score, which it must never do")


# ---------------------------------------------------------------------------
# 3. A record that is not a grade and slipped past validation stops the run,
#    and says which file it was.
# ---------------------------------------------------------------------------
def test_an_unmarked_non_grade_is_loud(tmp: Path) -> None:
    print("\n[4] a non-grade that validation did NOT catch stops the run by name")
    agg = REPO / "scripts" / "aggregate.py"
    grades, roster = build_corpus(tmp / "unmarked", "unmarked")
    r = run_aggregate(agg, grades, roster, tmp / "unmarked" / "results.json")
    check("it refuses to publish", r.returncode != 0, f"rc={r.returncode}")
    check("the message names the record rather than raising a bare KeyError",
          "NOT A GRADE" in r.stderr and "astra/leader-0/src0" in r.stderr,
          r.stderr[-300:])
    check("and it does not fall back to a default share",
          "KeyError" not in r.stderr, r.stderr[-300:])


# ---------------------------------------------------------------------------
# 4. grade_loop.sh must say when it could not rebuild the board.
# ---------------------------------------------------------------------------
def test_render_failure_is_loud() -> None:
    print("\n[5] grade_loop.sh reports a failed render and will not call it COMPLETE")
    sh = REPO / "scripts" / "grade_loop.sh"
    src = sh.read_text()

    r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
    check("grade_loop.sh is valid bash", r.returncode == 0, r.stderr[-300:])

    check("the silent && chain is gone",
          "&& $PY scripts/build_site.py" not in src,
          "a failed aggregate would again only skip the re-rendered line")
    check("aggregate failure is named in the loop's own log",
          "AGGREGATE FAILED" in src)
    check("build_site failure is named separately from aggregate failure",
          "BUILD_SITE FAILED" in src,
          "results.json current and the page stale is a different state")
    check("the failing stage prints the last line of the error log",
          "tail -n 1 data/logs/grade_loop.err" in src,
          "the traceback stays in a file nobody reads until something looks wrong")
    check("consecutive render failures are counted",
          "render_fail=0" in src and "render_fail=$((render_fail + 1))" in src)
    check("a recovered render says so",
          "render RECOVERED" in src)

    stale, done = src.find("STOPPING ON A STALE LEADERBOARD"), src.find("COMPLETE: nothing left to grade")
    check("the stale-board exit is checked BEFORE the COMPLETE line",
          -1 not in (stale, done) and stale < done,
          "COMPLETE would print over a board that was never rebuilt")
    check("and stopping on a stale board exits non-zero",
          "exit 1" in src[stale:done],
          "a silent exit 0 is what let this run for 13 hours")


def main() -> int:
    print("render-integrity guards")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_fixture_reproduces_the_crash(tmp)
        test_invalid_record_is_split_out_first(tmp)
        test_the_reorder_moves_no_published_number(tmp)
        test_an_unmarked_non_grade_is_loud(tmp)
    test_render_failure_is_loud()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
