#!/usr/bin/env python3
"""A pundits run is not gated by membership, because membership is leaders-only.

THE HAZARD THIS GUARDS. `grade.py`, `aggregate.py` and `build_site.py` are shared
by both studies. `membership.json` describes the leaders study alone: it names the
50 on the roster, the seven investors and `cc-wei`, and no pundit. Every reader
raises on a slug it has not been told about, deliberately. So an UNSCOPED reader
would raise on the first pundit slug it met, and repo-3's pundits production —
which is live, and was grading while the membership work was being written —
would stop on its next cycle with an error naming a file that has nothing to do
with it.

The scoping rule is one line in each reader: apply membership only when
`args.study == SP.LEGACY_STUDY`. This file proves that rule BEHAVIOURALLY, by
running the real scripts against a real pundits checkout with a `.study` marker
and a pundits origin, rather than by grepping the source for the condition. A
grep cannot tell a working guard from one that never matches.

WHAT IS AND IS NOT ASSERTED. A pundits run may still fail for its own reasons in
a fixture this small. What it must never do is fail for a MEMBERSHIP reason, and
it must never drop a pundit's work because a leaders file did not list them. Both
are asserted on the run's own output.

Temporary git checkouts only. Nothing under data/ or data-pundits/ is read or
written, no judge is called, and the PATH is poisoned so none could be. No quota,
no network.
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
sys.path.insert(0, str(REPO / "scripts"))
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


def membership_words(text: str) -> list[str]:
    """Every line of `text` that is about membership. The evidence, not a boolean."""
    return [ln for ln in text.splitlines()
            if "membership" in ln.lower() or "membership.json" in ln]


def main() -> int:
    # The two-checkout fixture is IMPORTED, not re-written. test_study_isolation
    # already builds a committed data checkout with a .study marker, a pundits
    # origin and a .daemon-clone, and that shape is what SP.guard actually
    # inspects. A hand-rolled imitation drifts from it silently.
    import test_study_isolation as SI

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        leaders_co = tmp / "data-leaders"
        pundits_co = tmp / "data-pundits"
        SI.checkout(leaders_co, "verbatim-index-data", "alpha", "Alpha Person", None)
        SI.checkout(pundits_co, "verbatim-pundits-data", "pundit-a", "Pundit A", "pundits")

        # A PATH carrying git and NOTHING ELSE. git is needed because
        # guard_aggregate shells out to it, and without it a run refuses for a
        # git reason that looks exactly like a membership refusal from the
        # outside: arm [4] below passed for entirely the wrong reason until this
        # was fixed. No judge binary is reachable on this PATH, so a judge cannot
        # be called even if a run reached one.
        bin_dir = tmp / "tripwire-bin"
        bin_dir.mkdir()
        dud = bin_dir / "dud"
        dud.write_text("#!/bin/sh\necho 'TRIPWIRE: a judge binary was invoked' >&2\nexit 97\n")
        dud.chmod(0o755)
        git_bin = shutil.which("git")
        if not git_bin:
            print("  SKIP: no git on PATH, so the fixture cannot be built")
            return 1
        (bin_dir / "git").symlink_to(git_bin)
        env = {**os.environ, "PATH": str(bin_dir), "PYTHONPATH": str(REPO / "scripts"),
               "QUOTA_ROUTER_CODEX_BIN": str(dud), "PYTHONHASHSEED": "0"}

        print("[1] the premise: no pundit slug is in membership.json")
        import membership as MB
        board = MB.load()
        check("pundit-a is not declared, so an unscoped reader WOULD raise",
              "pundit-a" not in board,
              "if this fails the test proves nothing, because the guard would "
              "never be exercised")
        raised = False
        try:
            MB.on_board(board, "pundit-a", "leaders")
        except RuntimeError:
            raised = True
        check("... and it really does raise when asked directly", raised)

        missing = tmp / "does-not-exist" / "membership.json"

        print("\n[2] the scoping rule itself: for_study returns None off leaders")
        # WHY THIS IS A DIRECT TEST AND NOT AN END-TO-END RUN. The pundits half
        # cannot be exercised from repo-0 at all. MEASURED: a pundits grade.py
        # run refuses at "data-pundits is not a git checkout", and a pundits
        # aggregate.py run refuses at the v2 contract check, both long before any
        # reader is reached, because repo-3 owns pundits production and this
        # clone has no data-pundits link. An earlier version of this file
        # asserted on those runs and was VACUOUS: removing the scoping from both
        # readers left all 13 checks green. The scoping is therefore one function
        # with one test, and the readers are asserted to call it.
        def scoped_none(study: str) -> tuple[bool, str]:
            """Did for_study decline to load, or did it try and blow up?

            Reported rather than raised: if the rule is inverted, for_study
            raises on the missing file, and an uncaught exception here would end
            the file with a traceback instead of a named failure.
            """
            try:
                return MB.for_study(study, missing) is None, ""
            except Exception as exc:  # noqa: BLE001
                return False, f"raised instead of returning None: {exc}"

        ok, why = scoped_none("pundits")
        check("for_study('pundits') returns None even when the file is missing", ok, why)
        ok, why = scoped_none("some-future-study")
        check("... and for any other non-leaders study", ok, why)
        raised_leaders = False
        try:
            MB.for_study("leaders", missing)
        except RuntimeError:
            raised_leaders = True
        check("for_study('leaders') RAISES on the same missing file", raised_leaders,
              "if this does not raise the rule is inverted and every study is ungated")
        check("for_study('leaders') returns the real board by default",
              isinstance(MB.for_study("leaders"), dict))

        print("\n[3] every reader routes through for_study, none loads directly")
        for name in ("aggregate.py", "grade.py", "build_site.py"):
            src = (REPO / "scripts" / name).read_text()
            check(f"{name} calls MB.for_study", "for_study(args.study" in src,
                  "a reader that calls load() directly is unscoped and would stop "
                  "repo-3's pundits production on its next cycle")
            direct = [ln.strip() for ln in src.splitlines()
                      if ".load(args.membership)" in ln]
            check(f"{name} never calls load(args.membership) directly", not direct,
                  f"found {direct}")

        print("\n[3b] the missing file DOES stop a leaders run, end to end")
        # The leaders half IS reachable, so it is proved by running the real
        # script rather than by reading it.
        r2b = subprocess.run(
            [PY, str(REPO / "scripts" / "grade.py"),
             "--transcripts", str(leaders_co / "transcripts_blind"),
             "--roster", str(leaders_co / "roster/final.json"),
             "--out", str(tmp / "lg"), "--errors", str(tmp / "le.jsonl"),
             "--judges", "fable", "--modes", "blinded", "--repeats", "1",
             "--workers", "1", "--limit-per-leader", "0",
             "--membership", str(missing)],
            capture_output=True, text=True, cwd=REPO, env=env, timeout=240)
        c2b = r2b.stdout + r2b.stderr
        check("a leaders grade run refuses over the missing membership file",
              r2b.returncode != 0 and "does-not-exist" in c2b,
              f"rc={r2b.returncode} said {c2b.strip()[-400:]!r}")
        check("no judge binary was invoked", "TRIPWIRE" not in c2b)

        print("\n[4] the SAME corpus under --study leaders DOES hit membership")
        # The discriminating arm. Without it, arms [2] and [3] would pass against
        # a reader that had simply been deleted. The leaders checkout carries an
        # equally undeclared slug, so a leaders run must refuse where a pundits
        # run did not.
        # Real grades, not the isolation fixture's stub. That stub carries no
        # "grade" object, so aggregate exits at "no grades found" long before
        # membership is consulted, and this arm passed on THAT refusal instead.
        # Two wrong reasons for a green arm were found here: a missing git on the
        # tripwire PATH, and this.
        import test_render_integrity as RI
        lg = tmp / "leaders-corpus" / "grades"
        for t in range(6):
            for judge in ("fable", "astra"):
                d = lg / judge / "alpha"
                d.mkdir(parents=True, exist_ok=True)
                (d / f"src{t}__{judge}__blinded__r0.json").write_text(
                    json.dumps(RI.a_grade("alpha", f"src{t}", judge, 60 + t, 50 + t)))
        lroster = tmp / "leaders-corpus" / "roster.json"
        lroster.write_text(json.dumps({"roster": [
            {"rank": 1, "slug": "alpha", "name": "Alpha", "company": "C", "sector": "AI"}]}))
        r3 = subprocess.run(
            [PY, str(REPO / "scripts" / "aggregate.py"),
             "--grades", str(lg), "--roster", str(lroster),
             "--out", str(tmp / "leaders-results.json")],
            capture_output=True, text=True, cwd=REPO, env=env)
        c3 = r3.stdout + r3.stderr
        check("a leaders run over an undeclared slug DOES refuse",
              r3.returncode != 0, f"rc={r3.returncode}")
        check("... and says membership is why",
              "membership.json" in c3, f"said {c3.strip()[-400:]!r}")
        check("... naming the undeclared slug", "alpha" in c3)

        print("\n[5] build_site.py under another study returns before the import")
        # build_site dispatches to build_study_site for any study but leaders,
        # and membership is imported AFTER that dispatch. A module-level import
        # would fail in test_deploy_pundits' synthetic repo, which does not carry
        # membership.py. Assert the ordering in the source, since the dispatch
        # returns before anything observable happens.
        src = (REPO / "scripts" / "build_site.py").read_text()
        dispatch = src.index("return build_study_site.main_from_args(args)")
        imp = src.index("import membership as MB")
        check("membership is imported AFTER the study dispatch returns",
              imp > dispatch,
              "a module-level import fails in the synthetic pundits repo before "
              "the dispatch can no-op it")
        check("membership is not imported at module scope",
              not any(ln.strip().startswith(("import membership", "from membership"))
                      for ln in src.splitlines()[:60]),
              "the first 60 lines must not carry it")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
