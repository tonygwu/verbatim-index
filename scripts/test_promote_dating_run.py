#!/usr/bin/env python3
"""promote_dating_run.py: additive, refuses any conflict with production, writes nothing on a dry run.

Runs the real script against a temporary data root. The entries are operator-style
(confirmed_by "operator"), which the production loaders take without re-merging, so
no dating run's proposals are needed; the re-verification of agent entries is the
loaders' own and is tested with them. No network, no quota.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "promote_dating_run.py"

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def entry(date: str) -> dict:
    return {"statement_date": date, "basis": "event_date", "source_url": "https://example.org/event",
            "verbatim_evidence": f"held on {date}", "confirmed_by": "operator",
            "confirmed_at_utc": "2026-10-03T00:00:00Z"}


def setup(td: Path, run_over: dict, run_checks: dict, prod_over: dict | None, prod_checks: dict | None) -> tuple:
    data, run = td / "data", td / "data" / "predictions" / "_experiments" / "run1"
    run.mkdir(parents=True)
    for slug, sid, upload in (("a", "one", "20200105"), ("a", "two", "20210105"), ("b", "three", "20220105")):
        d = data / "transcripts_open" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.json").write_text(json.dumps({"leader_slug": slug, "source_id": sid, "yt_upload_date": upload}))
    (run / "overrides.json").write_text(json.dumps({"schema_version": 1, "overrides": run_over}))
    (run / "checks.json").write_text(json.dumps({"schema_version": 1, "checks": run_checks}))
    if prod_over is not None:
        (data / "predictions" / "statement_date_overrides.json").write_text(
            json.dumps({"schema_version": 1, "notes": "x", "overrides": prod_over}))
    if prod_checks is not None:
        (data / "predictions" / "statement_date_checks.json").write_text(
            json.dumps({"schema_version": 1, "notes": "x", "checks": prod_checks}))
    return data, run


def run(data: Path, run_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--data-root", str(data), *extra],
                          capture_output=True, text=True)


def files(data: Path) -> tuple:
    o, c = data / "predictions" / "statement_date_overrides.json", data / "predictions" / "statement_date_checks.json"
    return (json.loads(o.read_text()) if o.exists() else None, json.loads(c.read_text()) if c.exists() else None)


# 1. Additive: production's operator entry is kept, the run's entries are added, a checks file is created.
with tempfile.TemporaryDirectory() as td:
    data, rd = setup(Path(td), {"a/one": entry("2019-06-01")}, {"b/three": entry("2022-01-05")},
                     {"a/two": entry("2020-03-03")}, None)
    before = files(data)
    r = run(data, rd)
    check("a dry run exits 0 and says so", r.returncode == 0 and "dry run" in r.stdout, r.stdout + r.stderr)
    check("a dry run writes nothing", files(data) == before, str(files(data)))
    r = run(data, rd, "--apply")
    o, c = files(data)
    check("--apply exits 0", r.returncode == 0, r.stdout + r.stderr)
    check("production's own entry is kept and the run's override is added",
          o and set(o["overrides"]) == {"a/one", "a/two"} and o["overrides"]["a/two"] == entry("2020-03-03"), str(o))
    check("the checks file is created holding the run's check", c and set(c["checks"]) == {"b/three"}, str(c))
    check("the report counts what it added and kept",
          "added 1, unchanged 0, production-only kept 1 ['a/two']" in r.stdout, r.stdout)
    r2 = run(data, rd, "--apply")
    check("a second promotion of the same run changes nothing and reports it unchanged",
          r2.returncode == 0 and files(data) == (o, c) and "added 0, unchanged 1" in r2.stdout, r2.stdout + r2.stderr)

# 2. A different date for a transcript production already dates stops the run, naming it, and writes nothing.
with tempfile.TemporaryDirectory() as td:
    data, rd = setup(Path(td), {"a/one": entry("2019-06-01"), "a/two": entry("2020-04-04")}, {},
                     {"a/two": entry("2020-03-03")}, None)
    before = files(data)
    r = run(data, rd, "--apply")
    check("a conflicting date is refused", r.returncode != 0 and "a/two" in r.stderr and "differs" in r.stderr,
          r.stdout + r.stderr)
    check("a refusal writes neither file, not even the entries that did not conflict", files(data) == before,
          str(files(data)))

# 3. An override in the run for a transcript production CHECKS is refused: one date source per transcript.
with tempfile.TemporaryDirectory() as td:
    data, rd = setup(Path(td), {"b/three": entry("2021-12-01")}, {}, None, {"b/three": entry("2022-01-05")})
    r = run(data, rd, "--apply")
    check("an override over a production check is refused",
          r.returncode != 0 and "b/three" in r.stderr and "checks file already dates it" in r.stderr,
          r.stdout + r.stderr)

# 4. The run's own files go through the production loader: an override after the upload is refused.
with tempfile.TemporaryDirectory() as td:
    data, rd = setup(Path(td), {"a/one": entry("2020-02-01")}, {}, None, None)
    r = run(data, rd, "--apply")
    check("an entry the production loader refuses stops the promotion",
          r.returncode != 0 and "after the" in r.stderr and files(data) == (None, None), r.stdout + r.stderr)


def proposal(tid: str, e: str, lat: str, verdict: str = "dated", reupload: str = "no") -> dict:
    return {"harness": "gemini", "proposal": {
        "transcript_id": tid, "verdict": verdict, "event": "Some Summit", "event_kind": "keynote",
        "speech_date_earliest": e, "speech_date_latest": lat,
        "sources": [{"url": "https://example.org/x", "publisher": "x", "date_on_source": lat,
                     "verbatim_excerpt": "held on that day", "kind": "secondary"}],
        "transcript_evidence": None, "description_evidence": None, "reupload": reupload, "reasoning": "r"}}


def other_run(td: Path, props: dict) -> Path:
    o = td / "data" / "predictions" / "_experiments" / "dating-other"
    for (tid, h), doc in props.items():
        slug, sid = tid.split("/", 1)
        (o / "proposals" / slug).mkdir(parents=True, exist_ok=True)
        (o / "proposals" / slug / f"{sid}.{h}.json").write_text(json.dumps(doc))
    return o


# 5. Rule R1 across runs: another run's eligible proposal whose range misses the date holds the entry back.
with tempfile.TemporaryDirectory() as td:
    data, rd = setup(Path(td), {"a/one": entry("2019-06-01"), "a/two": entry("2020-03-03")},
                     {"b/three": entry("2022-01-05")}, None, None)
    o = other_run(Path(td), {("a/one", "gemini"): proposal("a/one", "2018-01-01", "2018-01-02"),
                             ("a/two", "fable"): proposal("a/two", "2020-03-01", "2020-03-05"),
                             # Not eligible: a re-upload's publication date says nothing about the speech.
                             ("b/three", "gemini"): proposal("b/three", "2021-01-01", "2021-01-01",
                                                             "publication_only", "yes")})
    r = run(data, rd, "--against", str(o), "--apply")
    ov, ck = files(data)
    check("--against exits 0 and names the held entry with the other run's range",
          r.returncode == 0 and "HELD a/one: override 2019-06-01: dating-other gemini named 2018-01-01..2018-01-02"
          in r.stdout, r.stdout + r.stderr)
    check("the held entry is not promoted, the one inside the other range is",
          ov and set(ov["overrides"]) == {"a/two"}, str(ov))
    check("an ineligible proposal (a re-upload's publication date) holds nothing back",
          ck and set(ck["checks"]) == {"b/three"}, str(ck))
    check("the report counts what was held", "held back by rule R1" in r.stdout and ": 1\n" in r.stdout, r.stdout)
    r = run(data, rd, "--against", str(Path(td) / "nope"))
    check("--against a directory that is not a dating run is refused",
          r.returncode != 0 and "not a dating run" in r.stderr, r.stdout + r.stderr)

# 6. --hold-file: entries a person holds for review are reported HELD and never promoted (2026-10-05:
# the operator asked that only script-confirmed dates be promoted, so two-dater agreements wait).
with tempfile.TemporaryDirectory() as td:
    data, rd = setup(Path(td), {"a/one": entry("2019-06-01"), "a/two": entry("2020-03-03")},
                     {"b/three": entry("2022-01-05")}, None, None)
    hold = Path(td) / "hold.json"
    hold.write_text(json.dumps({"a/one": "two-dater agreement, no source check", "b/three": "review"}))
    r = run(data, rd, "--hold-file", str(hold), "--apply")
    ov, ck = files(data)
    check("--hold-file exits 0 and names each held entry with its reason",
          r.returncode == 0 and "HELD a/one: override 2019-06-01: held for review: two-dater agreement, no source "
          "check" in r.stdout and "HELD b/three: check 2022-01-05: held for review: review" in r.stdout,
          r.stdout + r.stderr)
    check("a held entry is not promoted; the others are",
          ov and set(ov["overrides"]) == {"a/two"} and (ck is None or not ck["checks"]), f"{ov} {ck}")
    hold.write_text(json.dumps({"a/nine": "typo"}))
    r = run(data, rd, "--hold-file", str(hold))
    check("a hold naming a transcript the run does not date is refused",
          r.returncode != 0 and "a/nine" in r.stderr, r.stdout + r.stderr)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
