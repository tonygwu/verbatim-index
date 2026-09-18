#!/usr/bin/env python3
"""A collapsed board does not publish over the board that did not collapse.

deploy.sh printed the leader count and applied no floor, so a membership file
with "leader" typed for "leaders" would have rendered zero leaders and published
them. The floor is the previous published count, decided by the operator on
2026-09-17 over two cheaper derivations that each refuse during normal operation.

THE ARMS THAT MATTER ARE THE ONES THAT MUST NOT FIRE. A guard that refuses a
healthy deploy is worse than no guard, because the operator learns to bypass it.
So P3 (seven predictions-only people added to the roster) and a leader dropping
under MIN_TRANSCRIPTS_TO_RANK are both asserted to PASS, and they are the two
cases that sank the derivation the plan originally proposed.

Nothing under data/ or site/ is read or written; every arm uses a temporary
directory. No network, no deploy, no quota.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PY = str(ROOT / ".venv" / "bin" / "python")

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


def main() -> int:
    import publication_floor as PF

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("[1] the first run bootstraps, loudly, and is not silently guarded")
        site = tmp / "site-a"
        site.mkdir()
        ok, line = PF.check(50, PF.read_previous(site))
        check("it publishes", ok)
        check("it says it is bootstrapping", "BOOTSTRAPS" in line, line)
        check("it names the count it is recording", "50" in line, line)
        check("it says the run is NOT guarded", "NOT guarded" in line, line)

        print("\n[2] the baseline is recorded only after a publication")
        rp = tmp / "results.json"
        rp.write_text(json.dumps({"leaders": [{"slug": "a"}]}))
        PF.record(site, 50, rp, "abc1234")
        prev = PF.read_previous(site)
        check("leaders_published is recorded", prev["leaders_published"] == 50, str(prev))
        check("the results digest is recorded", len(prev["results_sha256"]) == 64, str(prev))
        check("the data revision is recorded", prev["data_revision"] == "abc1234", str(prev))
        check("the stamp is UTC and fixed-width",
              prev["published_at_utc"].endswith("Z") and len(prev["published_at_utc"]) == 20,
              str(prev))

        print("\n[3] THE CASES THAT MUST NOT FIRE")
        # P3 adds seven predictions-only people to the roster. They are never
        # scored, so the published count does not move at all. This is the case
        # that would have refused for ever under the plan's roster-size floor.
        ok, line = PF.check(50, prev)
        check("P3: seven predictions-only people added, still 50 published", ok, line)
        # A leader falling under MIN_TRANSCRIPTS_TO_RANK. One withdrawal causes
        # it and it has already happened once, to C.C. Wei.
        ok, line = PF.check(49, prev)
        check("one leader drops under the rank floor: 49 of 50 publishes", ok, line)
        check("... and the line says DOWN 1 even though it passed", "DOWN 1" in line, line)
        ok, _ = PF.check(43, prev)
        check("a withdrawal sweep of 7 still publishes", ok)

        print("\n[4] THE CASES THAT MUST FIRE")
        ok, line = PF.check(0, prev)
        check("the empty board REFUSES", not ok, line)
        check("... and the refusal points at membership.json",
              "membership.json" in line, line)
        check("... and names both counts", "0 leaders against 50" in line, line)
        # The boundary, pinned exactly rather than approximately. floor_for(50)
        # is int(50 * 0.85) = 42, so 42 publishes and 41 is the first refusal.
        # My first draft asserted that 42 refuses; the code was right and the
        # assertion was wrong.
        check("the floor for 50 is 42", PF.floor_for(50) == 42, str(PF.floor_for(50)))
        ok42, _ = PF.check(42, prev)
        check("42 of 50 is exactly at the floor and publishes", ok42)
        ok41, _ = PF.check(41, prev)
        check("41 of 50 is the first refusal", not ok41)
        ok40, _ = PF.check(40, prev)
        check("the 50-to-40 erosion the operator named REFUSES", not ok40)
        ok, _ = PF.check(1, prev)
        check("a one-leader board REFUSES", not ok)

        print("\n[5] the threshold is visible on every run, not only when it fires")
        ok, line = PF.check(50, prev)
        check("a passing run still prints the floor", "floor 42" in line, line)
        check("... and the tolerance as a number", "15%" in line, line)

        print("\n[6] an unreadable baseline RAISES; it is not treated as absent")
        site_b = tmp / "site-b"
        site_b.mkdir()
        PF.state_path(site_b).write_text("{ not json")
        raised = False
        try:
            PF.read_previous(site_b)
        except RuntimeError:
            raised = True
        check("malformed state raises rather than bootstrapping", raised,
              "'cannot read the previous count' and 'there is no previous count' "
              "are different facts and only one is safe to continue from")
        site_c = tmp / "site-c"
        site_c.mkdir()
        PF.state_path(site_c).write_text(json.dumps({"leaders_published": "fifty"}))
        raised_c = False
        try:
            PF.read_previous(site_c)
        except RuntimeError:
            raised_c = True
        check("a non-integer count raises too", raised_c)

        print("\n[7] the CLI exits non-zero when it refuses, so a shell can gate on it")
        r = subprocess.run([PY, str(ROOT / "scripts" / "publication_floor.py"),
                            "check", "--site-dir", str(site), "--count", "0"],
                           capture_output=True, text=True)
        check("check --count 0 exits non-zero", r.returncode != 0, r.stdout + r.stderr)
        check("... and prints the refusal", "REFUSING" in r.stdout, r.stdout)
        r2 = subprocess.run([PY, str(ROOT / "scripts" / "publication_floor.py"),
                             "check", "--site-dir", str(site), "--count", "50"],
                            capture_output=True, text=True)
        check("check --count 50 exits zero", r2.returncode == 0, r2.stdout + r2.stderr)

        print("\n[8] deploy.sh actually calls it, in both places")
        # COMMENT LINES ARE STRIPPED FIRST. Commenting the call out leaves the
        # substring in the file, so a naive read passes against a deploy.sh that
        # no longer calls the floor at all. MEASURED: it did.
        src = "\n".join(ln for ln in (ROOT / "scripts" / "deploy.sh").read_text().splitlines()
                         if not ln.lstrip().startswith("#"))
        check("deploy.sh runs the floor check", "publication_floor.py check" in src,
              "a floor nothing calls is not a floor")
        check("deploy.sh records a new baseline", "publication_floor.py record" in src)
        chk = src.index("publication_floor.py check")
        rec = src.index("publication_floor.py record")
        wrangler = src.index("npx wrangler deploy")
        check("the check runs BEFORE the publish", chk < wrangler)
        check("the record runs AFTER the publish", rec > wrangler,
              "recording a baseline for a publication that failed would raise the "
              "floor to a board that never went live")
        dry = src.index("--dry-run: rendered")
        check("the check also runs on --dry-run", chk < dry,
              "a dry run is where an operator finds out, so it must see the floor too")
        check("the record does NOT run on --dry-run", rec > dry,
              "a dry run publishes nothing and must not move the baseline")

        print("\n[9] every script deploy.sh calls is carried by the clone fixtures")
        # test_data_clone_workflow.py builds a synthetic clone from a TYPED list
        # of filenames and runs deploy.sh inside it. Adding publication_floor.py
        # to deploy.sh broke it with "can't open file ... publication_floor.py",
        # which is the stale-literal defect this repo has paid for twice. The
        # list stays typed, because deriving it is worse, but it can no longer go
        # stale in silence.
        import re
        deploy_src = (ROOT / "scripts" / "deploy.sh").read_text()
        # The --refresh block is excluded: it calls aggregate.py, and the clone
        # fixture never passes --refresh because that path requires the daemon
        # clone. Only the scripts a plain deploy reaches are required.
        no_refresh = re.sub(r'if \[ "\$REFRESH" -eq 1 \]; then.*?\nfi\n', "",
                            deploy_src, flags=re.S)
        # On the INVOCATION, not the word: deploy.sh also mentions aggregate.py in
        # a comment outside the refresh block, which made a bare-substring version
        # of this check fail against a strip that had worked perfectly.
        check("the --refresh block was actually found and stripped",
              "scripts/aggregate.py" in deploy_src
              and "scripts/aggregate.py" not in no_refresh,
              "if this fails the exclusion silently stopped matching and the "
              "check below would demand a script the fixture never needs")
        called = sorted(set(re.findall(r"scripts/([A-Za-z0-9_]+\.(?:py|sh))", no_refresh)))
        check("deploy.sh's callees were found at all", len(called) >= 3, str(called))
        fixture = (ROOT / "scripts" / "test_data_clone_workflow.py").read_text()
        for name in called:
            if name == "deploy.sh":
                continue
            check(f"the clone fixture carries {name}", f"'{name}'" in fixture,
                  f"deploy.sh calls {name} but test_data_clone_workflow.py does not "
                  f"copy it into the synthetic clone, so that test dies on a missing file")


        print("\n[10] the three grade-file walks agree on what is not a score")
        # aggregate.py decides grade_files_read; deploy.sh refuses to publish
        # unless its own count matches. If the two disagree about a directory the
        # check refuses for ever, and --refresh cannot fix it because
        # re-aggregating excludes the same file again. deploy_pundits.sh is the
        # third walk over the same shelf. Derived from the sources, not typed.
        import re as _re
        agg = (ROOT / "scripts" / "aggregate.py").read_text()
        i = agg.index("def load_grades(")
        agg_skip = set(_re.findall(r'"(_[a-z]+)" in path\.parts', agg[i:i + 600]))
        dep_skip = set(_re.findall(r'"(_[a-z]+)"', 
                                   (ROOT / "scripts" / "deploy.sh").read_text()
                                   .split("on_disk = ")[0][-300:]))
        pun = (ROOT / "scripts" / "deploy_pundits.sh").read_text()
        pun_skip = set(_re.findall(r'"(_[a-z]+)"', pun[pun.index("skip = {"):pun.index("skip = {") + 120]))
        check("aggregate's exclusions were found", "_raw" in agg_skip and "_obsolete" in agg_skip,
              str(agg_skip))
        check("deploy.sh excludes everything aggregate does",
              agg_skip <= dep_skip,
              f"aggregate skips {sorted(agg_skip)}, deploy.sh skips {sorted(dep_skip)}; "
              f"a file counted by one and not the other makes the staleness check "
              f"refuse for ever")
        check("deploy_pundits.sh does too", agg_skip <= pun_skip,
              f"pundits skips {sorted(pun_skip)}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
