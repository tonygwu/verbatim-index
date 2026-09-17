#!/usr/bin/env python3
"""Normalize must tell a QA RACE from a STALE QA REPORT, and refuse only the latter.

normalize_transcripts.py excludes transcripts QA rejected. It read the report
with `if args.qa and Path(args.qa).exists()`, so a report that was missing, or
older than the shelf it describes, silently excluded nothing and every
unexamined transcript went through as if QA had passed it.

A naive "refuse if QA does not cover every transcript" fires in normal
operation. Three daemons write the shelf and the QA report with no lock, and one
blinding pass takes about 50 seconds over 720 transcripts, so a transcript that
lands mid-pass is legitimately uncovered. That is a RACE, and refusing it would
skip a healthy cycle.

The distinction is arrival time. If an uncovered transcript reached the shelf
BEFORE the report was generated, the report is stale and normalize refuses. If
it arrived after, the report simply predates it and the next cycle covers it.

Every way this rule can be wrong is a FALSE REFUSE, never a false skip:
  - equal-second arrivals count as "after", the safe direction
  - a report with no stamp refuses outright rather than assuming it is fresh
  - a named-but-absent --qa file refuses rather than excluding nothing

The stamp is taken BEFORE the first directory listing, not when the summary is
built. The scan takes about 6 seconds on the live corpus, so a transcript
landing during it would otherwise be both uncovered and pre-stamp, which is the
exact false refusal this repairs.

Arrival is read out of the record -- shelf_arrived_at_utc, falling back to
fetched_at_utc -- never off the filesystem. All 720 live shelf records carry
fetched_at_utc; mtime records when a file was touched and three loops touch
these constantly.

These checks run against temporary corpora. Nothing under data/ is read or
written. No quota, no network.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "scripts" / "qa_transcripts.py"
NORM = ROOT / "scripts" / "normalize_transcripts.py"
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(slug: str, sid: str, *, arrived: str | None, fetched: str, words: int = 400) -> dict:
    body = " ".join(f"word{i % 97}" for i in range(words))
    r = {"leader_slug": slug, "source_id": sid, "video_id": sid[:11].ljust(11, "x"),
         "text": f"Leader A of Acme here. {body}", "word_count": words + 5,
         "duration_sec": 600, "n_timestamp_marks": 10, "caption_track": "auto",
         "fetched_at_utc": fetched}
    if arrived is not None:
        r["shelf_arrived_at_utc"] = arrived
    return r


def roster_file(tmp: Path) -> Path:
    p = tmp / "roster.json"
    p.write_text(json.dumps({"roster": [
        {"slug": "leader-a", "name": "Leader A", "company": "Acme"},
        {"slug": "leader-b", "name": "Leader B", "company": "Beta"},
    ]}))
    return p


def write_qa(path: Path, covered: list[tuple[str, str]], *, generated: str | None) -> None:
    summary: dict = {"transcripts_examined": len(covered), "verdicts": {"pass": len(covered)}}
    if generated is not None:
        summary["generated_at_utc"] = generated
    path.write_text(json.dumps({"summary": summary, "reports": [
        {"leader_slug": s, "source_id": i, "verdict": "pass", "reasons": []}
        for s, i in covered]}, indent=1))


def run_norm(tmp: Path, shelf: Path, qa: Path | None, *extra: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(NORM), "--mode", "blinded",
           "--transcripts", str(shelf), "--out", str(tmp / "out"),
           "--roster", str(roster_file(tmp)), "--log", str(tmp / "norm.json"),
           "--no-prune"]
    if qa is not None:
        cmd += ["--qa", str(qa)]
    return subprocess.run(cmd + list(extra), capture_output=True, text=True)


def main() -> int:
    print("normalize must distinguish a QA race from a stale QA report\n")

    print("[1] qa_transcripts stamps the report, and stamps it BEFORE the scan")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        # Enough work that the scan is measurably long, so "before the scan" and
        # "when the summary is built" are distinguishable outcomes.
        # MEASURED on this machine: 120x3000 words scans in 0.56s, 300x4000 in
        # 1.39s, 600x4000 in 2.79s. 600 is chosen so the scan is long enough
        # that a pre-scan stamp and a summary-time stamp land in different
        # halves of the window. A smaller fixture cannot tell them apart, and
        # the check below says so out loud rather than passing.
        for i in range(600):
            (shelf / "leader-a" / f"t{i:03d}.json").write_text(json.dumps(
                rec("leader-a", f"t{i:03d}", arrived=None,
                    fetched="2026-09-01T00:00:00Z", words=4000)))
        out = tmp / "qa.json"
        t0 = time.time()
        r = subprocess.run(
            [sys.executable, str(QA), "--transcripts", str(shelf),
             "--roster", str(roster_file(tmp)), "--out", str(out)],
            capture_output=True, text=True)
        t1 = time.time()
        check("qa_transcripts exits 0", r.returncode == 0, r.stderr[-1500:])
        if r.returncode != 0:
            print(f"\n{passed} passed, {failed} failed")
            return 1
        summ = json.loads(out.read_text())["summary"]
        check("summary.generated_at_utc exists", "generated_at_utc" in summ,
              f"summary keys: {sorted(summ)}")
        g = summ.get("generated_at_utc")
        check("it is a UTC instant", bool(g and UTC_RE.match(g)), f"got {g!r}")
        elapsed = t1 - t0
        if g and UTC_RE.match(g):
            got = datetime.strptime(g, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            if elapsed < 1.0:
                # Say so rather than pass vacuously: with a fast scan this check
                # cannot tell the two implementations apart.
                check("the scan was long enough to discriminate", False,
                      f"scan took {elapsed:.2f}s; raise the fixture size, this "
                      "check cannot distinguish pre-scan from post-scan stamping")
            else:
                check(f"the stamp lands in the first half of a {elapsed:.1f}s scan",
                      got <= t0 + elapsed / 2,
                      f"stamp is {got - t0:.1f}s into a {elapsed:.1f}s scan; it "
                      "looks like it was taken when the summary was built")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    gen = stamp(now)

    print("\n[2] THE RACE: a transcript that arrived AFTER the report is fine")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        (shelf / "leader-a" / "covered.json").write_text(json.dumps(
            rec("leader-a", "covered", arrived=stamp(now - timedelta(minutes=5)),
                fetched="2026-09-01T00:00:00Z")))
        (shelf / "leader-a" / "late.json").write_text(json.dumps(
            rec("leader-a", "late", arrived=stamp(now + timedelta(seconds=30)),
                fetched="2026-09-01T00:00:00Z")))
        qa = tmp / "qa.json"
        write_qa(qa, [("leader-a", "covered")], generated=gen)
        r = run_norm(tmp, shelf, qa)
        check("normalize proceeds", r.returncode == 0,
              f"exit {r.returncode}; refusing a benign race skips a healthy "
              f"cycle\n{r.stderr[-1200:]}")

    print("\n[3] THE STALE CASE: a transcript that arrived BEFORE the report refuses")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        (shelf / "leader-a" / "covered.json").write_text(json.dumps(
            rec("leader-a", "covered", arrived=stamp(now - timedelta(minutes=5)),
                fetched="2026-09-01T00:00:00Z")))
        (shelf / "leader-a" / "early.json").write_text(json.dumps(
            rec("leader-a", "early", arrived=stamp(now - timedelta(minutes=1)),
                fetched="2026-09-01T00:00:00Z")))
        qa = tmp / "qa.json"
        write_qa(qa, [("leader-a", "covered")], generated=gen)
        r = run_norm(tmp, shelf, qa)
        check("normalize refuses", r.returncode != 0,
              "an uncovered transcript that predates the report means the "
              "report is stale, and every unexamined transcript would pass")
        check("it names the transcript", "early" in (r.stderr + r.stdout),
              f"stderr: {r.stderr[-800:]}")
        check("it names the QA command to run",
              "qa_transcripts" in (r.stderr + r.stdout), f"stderr: {r.stderr[-800:]}")

    print("\n[4] equal-second arrivals are NOT 'predates', which is the safe direction")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        (shelf / "leader-a" / "tie.json").write_text(json.dumps(
            rec("leader-a", "tie", arrived=gen, fetched="2026-09-01T00:00:00Z")))
        qa = tmp / "qa.json"
        write_qa(qa, [], generated=gen)
        r = run_norm(tmp, shelf, qa)
        check("normalize proceeds on an exact tie", r.returncode == 0,
              f"exit {r.returncode}\n{r.stderr[-800:]}")

    print("\n[5] shelf_arrived_at_utc wins over fetched_at_utc")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        # Fetched ten days ago, merged onto the shelf 30s from now: a legitimate
        # merge of an old fetch. Reading fetched_at_utc would refuse this.
        (shelf / "leader-a" / "merged.json").write_text(json.dumps(
            rec("leader-a", "merged", arrived=stamp(now + timedelta(seconds=30)),
                fetched="2026-09-06T07:23:04Z")))
        qa = tmp / "qa.json"
        write_qa(qa, [], generated=gen)
        r = run_norm(tmp, shelf, qa)
        check("a late merge of an old fetch proceeds", r.returncode == 0,
              f"exit {r.returncode}; it read fetched_at_utc instead of "
              f"shelf_arrived_at_utc\n{r.stderr[-1000:]}")

    print("\n[6] a report with NO stamp refuses, naming the command")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        (shelf / "leader-a" / "t.json").write_text(json.dumps(
            rec("leader-a", "t", arrived=stamp(now), fetched="2026-09-01T00:00:00Z")))
        qa = tmp / "qa.json"
        write_qa(qa, [("leader-a", "t")], generated=None)
        r = run_norm(tmp, shelf, qa)
        check("normalize refuses an unstamped report", r.returncode != 0,
              "skipping the check on a missing stamp is the silent fallback "
              "this repo forbids")
        check("it names the QA command", "qa_transcripts" in (r.stderr + r.stdout),
              f"stderr: {r.stderr[-800:]}")

    print("\n[7] a named-but-absent file refuses instead of quietly doing nothing")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        (shelf / "leader-a" / "t.json").write_text(json.dumps(
            rec("leader-a", "t", arrived=stamp(now), fetched="2026-09-01T00:00:00Z")))
        r = run_norm(tmp, shelf, tmp / "does-not-exist.json")
        check("an absent --qa refuses", r.returncode != 0,
              "it excluded nothing and every transcript passed as if QA had run")
        check("the message names the path", "does-not-exist.json" in (r.stderr + r.stdout),
              f"stderr: {r.stderr[-600:]}")

        qa = tmp / "qa.json"
        write_qa(qa, [("leader-a", "t")], generated=gen)
        r = run_norm(tmp, shelf, qa, "--repairs", str(tmp / "no-repairs.json"))
        check("an absent --repairs refuses", r.returncode != 0, r.stdout[-400:])
        r = run_norm(tmp, shelf, qa, "--aliases", str(tmp / "no-aliases.json"))
        check("an absent --aliases refuses", r.returncode != 0, r.stdout[-400:])

    print("\n[8] no --qa at all is still allowed, since it names nothing")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shelf = tmp / "transcripts"
        (shelf / "leader-a").mkdir(parents=True)
        (shelf / "leader-a" / "t.json").write_text(json.dumps(
            rec("leader-a", "t", arrived=stamp(now), fetched="2026-09-01T00:00:00Z")))
        r = run_norm(tmp, shelf, None)
        check("normalize proceeds with no --qa", r.returncode == 0,
              f"exit {r.returncode}\n{r.stderr[-800:]}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
