#!/usr/bin/env python3
"""Guards for status.sh when the study's data is missing, foreign, or holds non-grades.

FOUND 2026-09-17, by running `STUDY=pundits bash scripts/status.sh` in repo-4,
a clone with no data-pundits link. The script did not stop. FETCH died with a
FileNotFoundError traceback, GRADING printed "no grades yet", the Gemini line
printed "0/0 blinded transcripts", coverage_table.py refused, and NEXT told the
operator to start the pundits fetch loop in that clone. Three of those lines
read as a real, empty study, and the last one is advice to run production work
in a clone that does not own it.

The same day, in repo-3 where the pundits data does live, GRADING died with
KeyError: 'judge'. Contract v2 writes provenance records under
grades/_provenance/, and the section read every JSON file under grades/ as a
grade.

WHAT IS ASSERTED HERE.

  MISSING    no data link at all: exit 1, a REFUSING line, and none of the
             misleading lines above. Checked for pundits and for leaders.
  FOREIGN    a data-pundits whose .study names another study: exit 1, REFUSING.
  HINT       when a sibling clone holds the link, the refusal names that clone.
  NON-GRADE  a valid checkout holding _provenance and _obsolete records next to
             one real grade: exit 0, no traceback, and exactly one grade counted.

Each case runs the real status.sh from a fixture root whose scripts/, profiles/
and .venv are links into this repository. STATUS_SKIP_YT_PROBE=1 is set only on
the NON-GRADE case so that the test makes no network call; the refusal cases
stop before the probe and never need it.

Run: .venv/bin/python scripts/test_status_study_guard.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MISLEADING = ("no grades yet", "0/0 blinded", "fetch_loop.sh", "Traceback")

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        fails += 1
        if detail:
            print("        " + detail.replace("\n", "\n        ")[:3000])


def make_root(container: Path, name: str) -> Path:
    root = container / name
    root.mkdir(parents=True)
    for link in ("scripts", "profiles", ".venv"):
        (root / link).symlink_to(REPO / link)
    return root


def run(root: Path, study: str | None, extra_env: dict | None = None,
        args: tuple = ()) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("STUDY", "DATA", "RUN_MARKER_DIR", "STATUS_SKIP_YT_PROBE")}
    if study:
        env["STUDY"] = study
    env.update(extra_env or {})
    return subprocess.run(["bash", str(root / "scripts" / "status.sh"), *args],
                          cwd=root, env=env, capture_output=True, text=True, timeout=120)


def pundits_checkout(path: Path, marker: str = "pundits") -> None:
    path.mkdir(parents=True)
    (path / ".study").write_text(marker + "\n")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin",
                    "git@github.com:example/verbatim-pundits-data.git"], check=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # MISSING, pundits.
        root = make_root(tmp / "c1", "repo-x")
        p = run(root, "pundits")
        out = p.stdout + p.stderr
        check("MISSING pundits: exits nonzero", p.returncode != 0, out)
        check("MISSING pundits: says REFUSING", "REFUSING" in out, out)
        check("MISSING pundits: prints no misleading line",
              not any(m in out for m in MISLEADING), out)

        # MISSING, leaders.
        root = make_root(tmp / "c2", "repo-x")
        p = run(root, None)
        out = p.stdout + p.stderr
        check("MISSING leaders: exits nonzero", p.returncode != 0, out)
        check("MISSING leaders: says REFUSING", "REFUSING" in out, out)
        check("MISSING leaders: prints no misleading line",
              not any(m in out for m in MISLEADING), out)

        # HINT: a sibling clone holds the link.
        root = make_root(tmp / "c3", "repo-x")
        pundits_checkout(tmp / "c3" / "repo-owner" / "data-pundits")
        p = run(root, "pundits")
        out = p.stdout + p.stderr
        check("HINT: refusal names the sibling clone holding data-pundits",
              p.returncode != 0 and "repo-owner" in out, out)

        # FOREIGN: the link exists but its marker names another study.
        root = make_root(tmp / "c4", "repo-x")
        pundits_checkout(root / "data-pundits", marker="leaders")
        p = run(root, "pundits")
        out = p.stdout + p.stderr
        check("FOREIGN: exits nonzero with REFUSING",
              p.returncode != 0 and "REFUSING" in out, out)
        check("FOREIGN: prints no misleading line",
              not any(m in out for m in MISLEADING), out)

        # NON-GRADE: provenance and obsolete records beside one real grade.
        root = make_root(tmp / "c5", "repo-x")
        d = root / "data-pundits"
        pundits_checkout(d)
        (d / "roster").mkdir()
        (d / "roster/final.json").write_text(json.dumps({"roster": [{"slug": "a-pundit"}]}))
        (d / "transcripts/a-pundit").mkdir(parents=True)
        grade = {"judge": "gemini", "mode": "blinded", "leader_slug": "a-pundit",
                 "source_id": "s1"}
        (d / "grades/gemini/blinded/a-pundit").mkdir(parents=True)
        (d / "grades/gemini/blinded/a-pundit/s1.json").write_text(json.dumps(grade))
        (d / "grades/_provenance").mkdir(parents=True)
        (d / "grades/_provenance/ffb1fa8c3e4dca42.json").write_text(
            json.dumps({"argv": [], "code_commit": "x", "provenance_id": "ffb1fa8c3e4dca42"}))
        (d / "grades/_obsolete/gemini").mkdir(parents=True)
        (d / "grades/_obsolete/gemini/s0.json").write_text(json.dumps(grade))
        p = run(root, "pundits", {"STATUS_SKIP_YT_PROBE": "1"}, ("--brief",))
        out = p.stdout + p.stderr
        check("NON-GRADE: exits 0", p.returncode == 0, out)
        check("NON-GRADE: no traceback", "Traceback" not in out, out)
        check("NON-GRADE: counts exactly the one real grade",
              "grades on disk     1  " in out, out)

    print(f"\n{'OK' if not fails else 'FAILED'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
