#!/usr/bin/env python3
"""Coverage is counted against the BOARD, not the roster, or it reports a permanent gap.

WHAT BROKE. P3 appended seven investors to `data/roster/final.json` for the
PREDICTIONS board only. `coverage_table.py` and `status.sh` both take their
denominator straight from the roster length, so the moment those seven landed
both started reporting:

    leaders with any transcript : 50/57
    leaders at 5+      50/57
    leaders at zero    7

Those seven will never have a leaders transcript, because they are not on the
leaders board and `grade.py` drops them. So the shortfall is permanent, and it is
printed by `status.sh`, which the production loops run every cycle. This repo has
a name for that failure: a component reporting a false number every cycle teaches
the operator to stop reading it, and the next real shortfall arrives into an
output nobody trusts.

WHAT IS ASSERTED. The denominator is the leaders board, so a healthy corpus reads
n/n. The seven are not silently dropped either: they are reported on their own
line, because "these people are deliberately not here" and "these people are
missing" are different facts and this file exists because they got confused.

The real scripts are run against a temporary data checkout. No quota, no network,
nothing under data/ is read or written.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "bin" / "python")

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


ON_BOARD = [f"on-{i}" for i in range(4)]
OFF_BOARD = ["off-a", "off-b"]


def build(tmp: Path) -> tuple[Path, Path]:
    """A data checkout where every board member has transcripts and grades."""
    D = tmp / "data"
    (D / "roster").mkdir(parents=True)
    (D / "sources").mkdir(parents=True)
    (D / "logs").mkdir(parents=True)
    (D / "roster/final.json").write_text(json.dumps({"roster": [
        {"rank": i + 1, "slug": s, "name": s.title(), "company": "C", "sector": "AI"}
        for i, s in enumerate(ON_BOARD + OFF_BOARD)]}))
    for s in ON_BOARD:
        for shelf in ("transcripts", "transcripts_blind"):
            (D / shelf / s).mkdir(parents=True, exist_ok=True)
            for t in range(6):
                (D / shelf / s / f"src{t}.json").write_text(json.dumps(
                    {"leader_slug": s, "source_id": f"src{t}", "word_count": 900,
                     "text": "hello " * 200}))
    # The off-board people have NOTHING, exactly as in production.
    mem = tmp / "membership.json"
    mem.write_text(json.dumps(
        {**{s: ["leaders", "predictions"] for s in ON_BOARD},
         **{s: ["predictions"] for s in OFF_BOARD}}))
    return D, mem


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        D, mem = build(tmp)

        # coverage_table resolves its data through the study link, so the run
        # happens inside a throwaway clone whose `data` points at the fixture.
        clone = tmp / "repo-x"
        (clone / "scripts").mkdir(parents=True)
        for name in ("coverage_table.py", "study_profile.py", "membership.py",
                     "status.sh", "study_env.sh", "run_marker.sh", "daemon_guard.sh"):
            src = REPO / "scripts" / name
            if src.exists():
                shutil.copy2(src, clone / "scripts" / name)
        shutil.copytree(REPO / "profiles", clone / "profiles")
        shutil.copy2(mem, clone / "membership.json")
        (clone / "data").symlink_to(D, target_is_directory=True)
        (clone / ".venv" / "bin").mkdir(parents=True)
        (clone / ".venv/bin/python").symlink_to(sys.executable)

        # The clone carries the scripts UNDER TEST, and the real scripts/ is on
        # the path behind it so their transitive imports resolve. Order matters:
        # membership.py must come from the clone, because its default path is
        # anchored to its own __file__ and has to find the fixture's
        # membership.json rather than the repository's real one.
        env = {**os.environ,
               "PYTHONPATH": os.pathsep.join([str(clone / "scripts"),
                                              str(REPO / "scripts")])}
        r = subprocess.run([PY, str(clone / "scripts" / "coverage_table.py"),
                            "--membership", str(clone / "membership.json")],
                           capture_output=True, text=True, cwd=clone, env=env)
        out = r.stdout + r.stderr
        check("coverage_table runs", r.returncode == 0, out[-500:])

        print("\n[1] the denominator is the board, not the roster")
        check("'leaders with any transcript' reads 4/4, not 4/6",
              "leaders with any transcript : 4/4" in out,
              [l for l in out.splitlines() if "any transcript" in l])
        check("'leaders at target' reads n/4",
              any("leaders at target" in l and "/4" in l for l in out.splitlines()),
              [l for l in out.splitlines() if "leaders at target" in l])
        check("no line reports a /6 denominator", "/6" not in out,
              [l for l in out.splitlines() if "/6" in l])

        print("\n[2] the off-board people are REPORTED, not silently dropped")
        check("a line names them as off the leaders board",
              "off the leaders board" in out.lower() or "predictions only" in out.lower(),
              "'deliberately not here' and 'missing' are different facts")
        check("... and says how many", "2" in out)

        print("\n[3] status.sh counts the same way")
        rs = subprocess.run(["bash", str(clone / "scripts" / "status.sh")],
                            capture_output=True, text=True, cwd=clone, env=env)
        sout = rs.stdout + rs.stderr
        check("status.sh runs", rs.returncode == 0, sout[-400:])
        check("'leaders at 5+' reads n/4, not n/6",
              any("leaders at 5+" in l and "/4" in l for l in sout.splitlines()),
              [l for l in sout.splitlines() if "leaders at 5+" in l])
        check("'leaders at zero' is 0, not 2",
              any("leaders at zero" in l and l.strip().endswith("0")
                  for l in sout.splitlines()),
              [l for l in sout.splitlines() if "leaders at zero" in l])

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
