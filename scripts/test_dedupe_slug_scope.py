#!/usr/bin/env python3
"""A duplicate sweep must orphan grades for the slug it retired, and no other.

dedupe_transcripts.py --sweep retires a re-uploaded appearance and then orphans
that appearance's grades, so a leader stops scoring on a recording that has left
the corpus. It found those grades by globbing the WHOLE grades tree for the
source id alone:

    for gp in Path(args.grades).rglob(f"{r['retired']}__*.json")

A source id is unique within a leader and NOT across leaders. MEASURED against
the live corpus on 2026-09-16: 720 shelf transcripts carry one colliding id,
`crowdstrike-tatbja`, filed under both `greg-brockman` and `lip-bu-tan`, and it
has 7 live grade files, 3 under one leader and 4 under the other. Retiring it
for either leader orphaned all 7, destroying four grades that no retirement
decision stood behind.

--sweep runs on every grade_loop cycle with no dry run, so this ran unattended.

These checks build a temporary corpus, so nothing under data/ is read or
written. No quota, no network.
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


def rec(slug: str, sid: str, text: str, *, marks: int) -> dict:
    return {"leader_slug": slug, "source_id": sid, "text": text,
            "word_count": len(text.split()), "duration_sec": 600,
            "n_timestamp_marks": marks, "caption_track": "auto"}


def build(tmp: Path) -> tuple[Path, Path, Path, Path]:
    """Two leaders sharing one source id, only one of which is a duplicate.

    leader-a holds `shared` and `keeper`, whose texts are near-identical, so the
    sweep retires the weaker of the two. leader-b holds `shared` ALONE, with
    unrelated text, so nothing about leader-b is a duplicate of anything. Its
    grades must survive untouched.
    """
    yt, hs = tmp / "transcripts", tmp / "transcripts_hs"
    grades = tmp / "grades"
    (yt / "leader-a").mkdir(parents=True)
    (yt / "leader-b").mkdir(parents=True)
    hs.mkdir(parents=True)

    body = " ".join(f"word{i}" for i in range(400))
    # The keeper is a strict superset, so containment of the weaker is 1.0, and
    # it wins quality() on timestamp marks, so the sweep retires `shared`.
    (yt / "leader-a" / "shared.json").write_text(
        json.dumps(rec("leader-a", "shared", body, marks=1)))
    (yt / "leader-a" / "keeper.json").write_text(
        json.dumps(rec("leader-a", "keeper", body + " and one more thing entirely", marks=99)))
    # Same id, different leader, unrelated words: not a duplicate of anything.
    other = " ".join(f"other{i}" for i in range(400))
    (yt / "leader-b" / "shared.json").write_text(
        json.dumps(rec("leader-b", "shared", other, marks=50)))

    for slug in ("leader-a", "leader-b"):
        d = grades / "fable" / slug
        d.mkdir(parents=True)
        (d / "shared__fable__blinded__r0.json").write_text(json.dumps({"leader_slug": slug}))
    return yt, hs, grades, tmp / "dedupe.json"


def run_sweep(yt: Path, hs: Path, grades: Path, out: Path) -> dict:
    r = subprocess.run(
        [sys.executable, str(DEDUPE), "--sweep", "--youtube", str(yt),
         "--happyscribe", str(hs), "--grades", str(grades), "--out", str(out)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"dedupe_transcripts.py failed: {r.stderr[-2000:]}")
    return json.loads(r.stdout)


def main() -> int:
    print("duplicate sweep must scope orphaned grades to the retired slug\n")

    with tempfile.TemporaryDirectory() as d:
        yt, hs, grades, out = build(Path(d))
        res = run_sweep(yt, hs, grades, out)

        print("[1] the sweep retires the duplicate it was built to find")
        check("exactly one transcript retired", res["sweep_retired"] == 1,
              f"got {res['sweep_retired']}: {res['detail']}")
        check("it is leader-a's `shared`",
              res["detail"] and res["detail"][0]["leader_slug"] == "leader-a"
              and res["detail"][0]["retired"] == "shared",
              f"got {res['detail']}")
        check("leader-a's shelf copy is renamed .superseded",
              (yt / "leader-a" / "shared.json.superseded").exists()
              and not (yt / "leader-a" / "shared.json").exists())

        print("\n[2] the retired leader's grades are orphaned")
        a = grades / "fable" / "leader-a" / "shared__fable__blinded__r0.json"
        check("leader-a's grade is orphaned",
              not a.exists() and a.with_name(a.name + ".orphaned").exists())

        print("\n[3] THE BUG: another leader's grades for the same id must survive")
        b = grades / "fable" / "leader-b" / "shared__fable__blinded__r0.json"
        check("leader-b's grade is untouched", b.exists(),
              "a grade was destroyed for a leader whose transcript was never retired")
        check("leader-b's grade was not renamed .orphaned",
              not b.with_name(b.name + ".orphaned").exists())
        check("leader-b's shelf copy is untouched",
              (yt / "leader-b" / "shared.json").exists())

        print("\n[4] the count reported is the count acted on")
        check("orphaned_grades_removed is 1, not 2",
              res["orphaned_grades_removed"] == 1,
              f"got {res['orphaned_grades_removed']}")
        check("a grade skipped for belonging to another slug is reported, never silent",
              res.get("orphans_skipped_other_slug") == 1,
              f"got {res.get('orphans_skipped_other_slug')!r}; a collision must be "
              "visible in the sweep's own output")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
