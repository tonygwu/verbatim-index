#!/usr/bin/env python3
"""A record merged onto the shelf records WHEN IT ARRIVED THERE, not when it was fetched.

dedupe_transcripts.py --merge copies a Happy Scribe record from transcripts_hs
onto the shelf, carrying its original fetched_at_utc across unchanged. Fetch and
merge are different events on different cycles, so that timestamp says nothing
about when the shelf gained the file.

This matters for the QA race rule that follows it. That rule refuses normalize
when a transcript the QA report does not cover ARRIVED BEFORE the report was
generated, since that means the report is stale rather than merely racing. With
only fetched_at_utc to read, a legitimate merge of an old fetch looks exactly
like the stale case and normalize refuses for no reason.

MEASURED 2026-09-16: 5 Happy Scribe records are pending merge, the oldest
fetched 2026-09-06, ten days ago. All 720 shelf records carry fetched_at_utc and
0 carry shelf_arrived_at_utc. So the stamp has to land BEFORE the refusal rule,
or the first merge after the rule ships would refuse a healthy cycle.

The stamp is read out of the record, never off the filesystem: mtime records
when a file was touched, and three loops touch these constantly.

These checks run --merge against a temporary corpus. Nothing under data/ is
read or written. No quota, no network.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEDUPE = ROOT / "scripts" / "dedupe_transcripts.py"
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


OLD_FETCH = "2026-09-06T07:23:04Z"


def build(tmp: Path) -> tuple[Path, Path, Path]:
    yt, hs = tmp / "transcripts", tmp / "transcripts_hs"
    (yt / "leader-a").mkdir(parents=True)
    (hs / "leader-a").mkdir(parents=True)
    body = " ".join(f"word{i}" for i in range(400))
    (hs / "leader-a" / "hs-talk.json").write_text(json.dumps({
        "leader_slug": "leader-a", "source_id": "hs-talk", "text": body,
        "word_count": 400, "duration_sec": 600, "n_timestamp_marks": 10,
        "caption_track": "auto",
        # Fetched ten days ago; it reaches the shelf only now.
        "fetched_at_utc": OLD_FETCH,
    }))
    return yt, hs, tmp / "dedupe.json"


def main() -> int:
    print("a merged record stamps its shelf arrival\n")

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        yt, hs, out = build(tmp)
        before = datetime.now(timezone.utc).replace(microsecond=0)
        r = subprocess.run(
            [sys.executable, str(DEDUPE), "--merge", "--youtube", str(yt),
             "--happyscribe", str(hs), "--out", str(out),
             "--grades", str(tmp / "grades")],
            capture_output=True, text=True)
        after = datetime.now(timezone.utc)
        check("exits 0", r.returncode == 0, r.stderr[-1500:])

        live = yt / "leader-a" / "hs-talk.json"
        check("the record reached the shelf", live.exists())
        if not live.exists():
            print(f"\n{passed} passed, {failed} failed")
            return 1
        rec = json.loads(live.read_text())

        print("\n[1] THE FIX: the shelf arrival is recorded")
        check("shelf_arrived_at_utc is present", "shelf_arrived_at_utc" in rec,
              f"keys: {sorted(rec)}")
        stamp = rec.get("shelf_arrived_at_utc")

        print("\n[2] it is a UTC instant, not a local one")
        check("it matches ...Z", bool(stamp and UTC_RE.match(stamp)), f"got {stamp!r}")
        if stamp and UTC_RE.match(stamp):
            got = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            check("it falls inside this run's own window",
                  before <= got <= after,
                  f"{stamp} is outside [{before.isoformat()}, {after.isoformat()}]; "
                  "a local-time stamp lands hours away on a non-UTC machine")

        print("\n[3] the fetch time is preserved, not overwritten")
        check("fetched_at_utc is unchanged", rec.get("fetched_at_utc") == OLD_FETCH,
              f"got {rec.get('fetched_at_utc')!r}, expected {OLD_FETCH!r}")
        check("the two differ, so arrival is not just a copy of fetch",
              rec.get("shelf_arrived_at_utc") != rec.get("fetched_at_utc"))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
