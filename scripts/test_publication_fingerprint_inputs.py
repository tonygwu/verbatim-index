#!/usr/bin/env python3
"""The publication fingerprint must cover membership.json, which now gates the render.

WHAT THE FINGERPRINT IS FOR. `deploy.sh` takes a fingerprint of the production
inputs before rendering and checks it again afterwards, and refuses if anything
moved. That binds one published page to the exact bytes it was built from, and it
is what catches a concurrent write by another clone mid-render.

THE GAP. `fingerprint()` hashes only paths under the production DATA source, via
`SITE_SHELVES`. `membership.json` sits at the root of the PUBLIC repository. Until
P2 that did not matter, because nothing read it. P2 made it a render input: it
decides which grades reach `usable`, how many people the page claims are on the
roster, and which transcripts count toward the words-graded total. So an edit
between `PUBLICATION_BEFORE` and `check_publication_unchanged` changes the
published page and the guard still passes.

MEASURED before the fix: changing every board name in membership.json left the
fingerprint byte-identical.

WHAT THIS DOES NOT CLAIM TO FIX. The same hole exists for `scripts/` itself, and
that is deliberate rather than overlooked: code is tracked, reviewed and pinned by
the commit being deployed, while `membership.json` is a config file an operator
edits by hand and which now moves the board. One file, named explicitly, is the
whole change.

Temporary directories only. No network, no deploy, no quota.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

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


def fake_source(root: Path) -> Path:
    """A minimal production data source carrying every leaderboard shelf."""
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "roster").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "grades" / "fable" / "alpha").mkdir(parents=True, exist_ok=True)
    (root / "results.json").write_text('{"leaders": []}')
    (root / "results_audit.json").write_text("{}")
    (root / "roster" / "final.json").write_text('{"roster": []}')
    (root / "logs" / "calibration.json").write_text("{}")
    (root / "sources" / "discovered.json").write_text('{"leaders": []}')
    (root / "grades" / "fable" / "alpha" / "a.json").write_text("{}")
    return root


def main() -> int:
    import data_clone_workflow as D

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = fake_source(tmp / "data")
        repo = tmp / "repo"
        (repo / "scripts").mkdir(parents=True)
        mem = repo / "membership.json"
        mem.write_text(json.dumps({"alpha": ["leaders"], "beta": ["predictions"]}))

        print("[1] the fingerprint covers the data shelves, as it always did")
        a = D.fingerprint(src, "leaderboard", repo=repo)
        (src / "results.json").write_text('{"leaders": [1]}')
        b = D.fingerprint(src, "leaderboard", repo=repo)
        check("a changed results.json changes the fingerprint", a != b)
        (src / "results.json").write_text('{"leaders": []}')
        check("and restoring it restores the fingerprint",
              D.fingerprint(src, "leaderboard", repo=repo) == a)

        print("\n[2] it now also covers membership.json, which gates the render")
        before = D.fingerprint(src, "leaderboard", repo=repo)
        # The exact edit that empties the board: "leader" for "leaders".
        mem.write_text(json.dumps({"alpha": ["leader"], "beta": ["predictions"]}))
        after = D.fingerprint(src, "leaderboard", repo=repo)
        check("the 'leader'-for-'leaders' typo changes the fingerprint", before != after,
              "this edit renders zero leaders; the guard must not let it through "
              "between the before and after checks")
        mem.write_text(json.dumps({"alpha": ["leaders"], "beta": ["predictions"]}))
        check("restoring it restores the fingerprint",
              D.fingerprint(src, "leaderboard", repo=repo) == before)
        mem.write_text(json.dumps({"alpha": ["leaders", "predictions"],
                                   "beta": ["predictions"]}))
        check("moving one person onto a second board changes it too",
              D.fingerprint(src, "leaderboard", repo=repo) != before)

        print("\n[3] a MISSING membership.json is refused, not hashed as absent")
        mem.write_text(json.dumps({"alpha": ["leaders"]}))
        mem.unlink()
        raised = False
        try:
            D.fingerprint(src, "leaderboard", repo=repo)
        except RuntimeError as exc:
            raised = "membership.json" in str(exc)
        check("it raises, naming the file", raised,
              "hashing nothing would make a deleted gate look like an unchanged one")
        mem.write_text(json.dumps({"alpha": ["leaders"], "beta": ["predictions"]}))

        print("\n[4] the predictions site is NOT fingerprinted on membership.json")
        # build_predictions_site.py does not read membership, so binding the
        # predictions render to it would refuse deploys for an input it never
        # consulted. If that changes, this check is the reminder to add it.
        (src / "predictions").mkdir(exist_ok=True)
        (src / "predictions" / "index.json").write_text("{}")
        p_before = D.fingerprint(src, "predictions", repo=repo)
        mem.write_text(json.dumps({"alpha": ["leader"]}))
        check("editing membership does not move the predictions fingerprint",
              D.fingerprint(src, "predictions", repo=repo) == p_before,
              "build_predictions_site.py does not read membership today")
        mem.write_text(json.dumps({"alpha": ["leaders"], "beta": ["predictions"]}))

        print("\n[5] the repo inputs are declared per site, never guessed")
        check("leaderboard declares membership.json",
              "membership.json" in D.SITE_REPO_INPUTS["leaderboard"],
              str(D.SITE_REPO_INPUTS))
        check("every site in SITE_SHELVES has an entry",
              set(D.SITE_REPO_INPUTS) == set(D.SITE_SHELVES),
              f"{sorted(D.SITE_REPO_INPUTS)} vs {sorted(D.SITE_SHELVES)}")
        raised2 = False
        try:
            D.fingerprint(src, "not-a-site", repo=repo)
        except RuntimeError:
            raised2 = True
        check("an unknown site is still refused", raised2)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
