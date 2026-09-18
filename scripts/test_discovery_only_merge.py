#!/usr/bin/env python3
"""Discovery without --only REPLACES discovered.json. This is the guard for that.

THE HAZARD, verbatim from the plan: appending the seven and then running
discovery without `--only` is destructive. `discover_sources.py` populates its
`existing` map only when `--only` was passed; without it, `existing` stays empty
and the file is rewritten from the current run alone. So a run scoped to seven
people, launched without the flag, silently deletes the other 50 leaders' source
lists, and `build_site.py` renders `discovered.json` per row.

Nothing guarded that. The flag is one word on a command line and the damage is
2,000 sources.

WHY THIS TEST MAKES NO NETWORK REQUEST. Real discovery searches YouTube, and at
the time this was written repo-3's pundits fetcher was IP-blocked on this machine
and waiting for a VPN rotation. `discover()` is therefore replaced by a stub and
only the MERGE is exercised, which is the part with the defect in it. The search
itself is not what this file is about.

Temporary files only. No network, no quota.
"""
from __future__ import annotations

import json
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


#: A stub that answers instantly and makes no request. It replaces
#: discover_sources.discover, whose signature is (person, target, candidates).
STUB = '''
import json, sys, types
sys.path.insert(0, {scripts!r})
import discover_sources as D

def fake_discover(person, target, candidates_per_leader):
    return {{"leader_slug": person["slug"],
             "aliases": [person["name"]],
             "repairs": [],
             "sources": [{{"source_id": person["slug"] + "-new", "title": "T",
                          "kind": "interview", "url": "u", "duration_min": 40}}],
             "rejected": [],
             "shortfall_reason": None}}

D.discover = fake_discover
sys.argv = ["discover_sources.py"] + {argv!r}
raise SystemExit(D.main())
'''


def run_discovery(tmp: Path, roster: Path, out: Path, only: str | None) -> subprocess.CompletedProcess:
    argv = ["--roster", str(roster), "--out", str(out), "--workers", "1"]
    if only:
        argv += ["--only", only]
    runner = tmp / f"run_{'only' if only else 'all'}.py"
    runner.write_text(STUB.format(scripts=str(REPO / "scripts"), argv=argv))
    return subprocess.run([PY, str(runner)], capture_output=True, text=True, cwd=REPO)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # An existing file standing in for the 50 already on the board.
        existing = {"leaders": [
            {"leader_slug": f"old-{i}", "aliases": [], "repairs": [],
             "sources": [{"source_id": f"old-{i}-a", "title": "kept",
                         "kind": "interview", "url": "u", "duration_min": 40}],
             "rejected": [], "shortfall_reason": None} for i in range(50)],
            "total_sources": 50, "target_per_leader": 12}
        out = tmp / "discovered.json"
        out.write_text(json.dumps(existing))

        roster = tmp / "roster.json"
        roster.write_text(json.dumps({"roster":
            [{"slug": f"old-{i}", "name": f"Old {i}", "company": "C"} for i in range(50)] +
            [{"slug": "new-one", "name": "New One", "company": "C"}]}))

        print("[1] WITH --only, the other 50 survive")
        r = run_discovery(tmp, roster, out, "new-one")
        check("the run succeeds", r.returncode == 0, r.stderr[-400:])
        got = json.loads(out.read_text())
        slugs = [x["leader_slug"] for x in got["leaders"]]
        check("all 50 existing leaders are still there",
              sum(1 for s in slugs if s.startswith("old-")) == 50,
              f"only {sum(1 for s in slugs if s.startswith('old-'))} survived")
        check("the new slug was added", "new-one" in slugs, str(slugs[-3:]))
        kept = [x for x in got["leaders"] if x["leader_slug"] == "old-7"][0]
        check("an untouched leader's sources are unchanged",
              kept["sources"][0]["source_id"] == "old-7-a"
              and kept["sources"][0]["title"] == "kept", str(kept["sources"]))

        print("\n[2] WITHOUT --only, the file is REPLACED and the 50 are gone")
        # This is the documented behaviour, asserted so it cannot change by
        # accident and so the danger is written down in a runnable form.
        out.write_text(json.dumps(existing))
        r2 = run_discovery(tmp, roster, out, None)
        check("the run succeeds", r2.returncode == 0, r2.stderr[-400:])
        got2 = json.loads(out.read_text())
        slugs2 = [x["leader_slug"] for x in got2["leaders"]]
        check("every roster slug is rewritten from this run", len(slugs2) == 51, str(len(slugs2)))
        check("... and that is only safe because the roster held them ALL",
              sum(1 for s in slugs2 if s.startswith("old-")) == 50)

        print("\n[3] the destructive case: --only omitted AND the roster scoped")
        # The real shape of the accident. A roster trimmed to the seven, or a
        # --roster pointing at a partial file, with --only forgotten.
        out.write_text(json.dumps(existing))
        small = tmp / "seven.json"
        small.write_text(json.dumps({"roster": [
            {"slug": "new-one", "name": "New One", "company": "C"}]}))
        r3 = run_discovery(tmp, small, out, None)
        check("the run succeeds, which is what makes this dangerous", r3.returncode == 0,
              r3.stderr[-300:])
        got3 = json.loads(out.read_text())
        slugs3 = [x["leader_slug"] for x in got3["leaders"]]
        check("ALL 50 EXISTING LEADERS WERE DELETED", slugs3 == ["new-one"],
              f"got {slugs3[:5]}")
        check("and the file says total_sources 1", got3["total_sources"] == 1,
              str(got3["total_sources"]))

        print("\n[4] the same run WITH --only is harmless")
        out.write_text(json.dumps(existing))
        r4 = run_discovery(tmp, small, out, "new-one")
        got4 = json.loads(out.read_text())
        check("50 survive and 1 is added",
              len(got4["leaders"]) == 51
              and sum(1 for x in got4["leaders"] if x["leader_slug"].startswith("old-")) == 50,
              str(len(got4["leaders"])))

    print(f"\n{passed} passed, {failed} failed")
    print("\nTHE RULE: any discovery run that does not cover the WHOLE roster must "
          "pass --only. There is no guard inside discover_sources.py; the flag is "
          "the guard.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
