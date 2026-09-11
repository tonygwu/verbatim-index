#!/usr/bin/env python3
"""A withdrawn Happy Scribe recording must stay withdrawn.

withdraw_sources.py retires a recording by renaming it to <id>.json.superseded,
and fetch_one honours that name so YouTube never re-downloads it. The Happy
Scribe path did not look at the marker at all, so dedupe_transcripts.py --merge
re-created the live copy on the next cycle.

OBSERVED 2026-09-11: four sources sat as both <id>.json and <id>.json.superseded
at the same time, and the withdrawal manifest reported them actionable again
within the hour. Retiring them a second time would have restarted the same loop.

These checks run --merge against a temporary corpus, so nothing under data/ is
read or written. No quota, no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEDUPE = ROOT / "scripts" / "dedupe_transcripts.py"

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def rec(slug: str, sid: str, text: str) -> dict:
    return {"leader_slug": slug, "source_id": sid, "text": text,
            "word_count": len(text.split()), "duration_sec": 600,
            "n_timestamp_marks": 10, "caption_track": "auto"}


def build(tmp: Path, *, withdrawn: bool) -> tuple[Path, Path, Path]:
    """A corpus with one Happy Scribe recording, optionally already retired."""
    yt, hs = tmp / "transcripts", tmp / "transcripts_hs"
    (yt / "leader-a").mkdir(parents=True)
    (hs / "leader-a").mkdir(parents=True)
    body = " ".join(f"word{i}" for i in range(400))
    (hs / "leader-a" / "hs-talk.json").write_text(json.dumps(rec("leader-a", "hs-talk", body)))
    if withdrawn:
        # Exactly what withdraw_sources.py leaves behind: the marker, no live file.
        (yt / "leader-a" / "hs-talk.json.superseded").write_text(
            json.dumps(rec("leader-a", "hs-talk", body)))
    out = tmp / "dedupe.json"
    return yt, hs, out


def run_merge(yt: Path, hs: Path, out: Path) -> dict:
    r = subprocess.run(
        [sys.executable, str(DEDUPE), "--merge", "--youtube", str(yt),
         "--happyscribe", str(hs), "--out", str(out), "--grades", str(yt.parent / "grades")],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"dedupe_transcripts.py failed: {r.stderr[-2000:]}")
    return json.loads(out.read_text())


def main() -> int:
    print("happy scribe withdrawal guards\n")

    print("[1] with no marker, the recording merges normally")
    with tempfile.TemporaryDirectory() as d:
        yt, hs, out = build(Path(d), withdrawn=False)
        res = run_merge(yt, hs, out)
        live = yt / "leader-a" / "hs-talk.json"
        check("the live copy is written", live.exists())
        check("merged_into_corpus counts it",
              res["summary"].get("merged_into_corpus") == 1,
              f"got {res['summary'].get('merged_into_corpus')}")

    print("\n[2] with a .superseded marker, it must NOT come back")
    with tempfile.TemporaryDirectory() as d:
        yt, hs, out = build(Path(d), withdrawn=True)
        res = run_merge(yt, hs, out)
        live = yt / "leader-a" / "hs-talk.json"
        check("no live copy is re-created", not live.exists(),
              "the withdrawal was undone, which is the 2026-09-11 bug")
        check("the marker is left alone",
              (yt / "leader-a" / "hs-talk.json.superseded").exists())
        check("nothing is counted as merged",
              res["summary"].get("merged_into_corpus", 0) == 0,
              f"got {res['summary'].get('merged_into_corpus')}")

        print("\n[3] the hold is reported, never silent")
        check("summary carries withheld_already_withdrawn",
              "withheld_already_withdrawn" in res["summary"],
              "a silent skip is how the original bug hid")
        verdicts = [x.get("verdict") for x in res["decisions"]]
        check("the decision says 'withdrawn'", "withdrawn" in verdicts,
              f"verdicts were {verdicts}")
        d0 = next((x for x in res["decisions"] if x.get("verdict") == "withdrawn"), {})
        check("its action is 'none'", d0.get("action") == "none")
        check("it explains itself", "withdrawal" in (d0.get("why") or ""))

    print(f"\n{passed}/{passed + failed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
