#!/usr/bin/env python3
"""grade.py will not spend a judge call on somebody who is not on the board.

Membership decides what is READ. For grade.py that means: drop the off-board
transcripts from the work list BEFORE any judge is chosen, so a person who is on
the predictions board and not the leaders board never costs a Fable, Astra or
Gemini call.

WHY THE GATE SITS WHERE IT DOES. `quota_router` reads the macOS Keychain and
spawns `codex app-server` inside `fable_accounts()`. Everything above that line
is free; everything below it has already touched a credential. The transcript
list is complete one line earlier, so the gate goes between the two and the test
below proves the ordering by running the gate with a POISONED PATH: if the
router ran first, the run would die naming the tripwire instead of exiting
cleanly on an empty work list.

WHY THE NON-EMPTY CHECK IS RE-ASSERTED AFTER THE GATE. `if not paths` already
runs, but it runs BEFORE the gate. A membership file that excludes everything
would therefore sail past it and the run would exit 0 having graded nothing,
which reads as a healthy pass. The gate re-asserts, and the re-assertion is what
one arm below removes to prove it is load-bearing.

WHY STUDY-SCOPED. grade.py is shared with the pundits study, which is live and
whose slugs are not in membership.json. A `--study pundits` run must never
refuse for a membership reason.

Nothing under data/ is read or written. NO JUDGE IS EVER CALLED: every arm is
constructed so the run ends before the router, and the PATH is poisoned so that
a judge binary cannot be found even if one were reached. No quota, no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
GRADE = str(ROOT / "scripts" / "grade.py")

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


def corpus(tmp: Path, slugs: list[str], n: int = 2) -> dict[str, Path]:
    tdir = tmp / "transcripts_blind"
    for slug in slugs:
        (tdir / slug).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (tdir / slug / f"src{i}.json").write_text(json.dumps({
                "leader_slug": slug, "transcript_id": f"{slug}/src{i}",
                "source_id": f"src{i}", "word_count": 500,
                "text": "hello world " * 50,
                "fetched_at_utc": "2026-09-01T00:00:00Z"}))
    roster = tmp / "roster.json"
    roster.write_text(json.dumps({"roster": [
        {"rank": i + 1, "slug": s, "name": s.title(), "company": "C"}
        for i, s in enumerate(slugs)]}))
    return {"transcripts": tdir, "roster": roster, "out": tmp / "grades",
            "errors": tmp / "errors.jsonl"}


def tripwire_env(tmp: Path) -> dict:
    """A PATH with no judge binary on it, plus the router's hardcoded codex path.

    From test_study_isolation.py: the router does not search PATH for codex, it
    uses a hardcoded /opt/homebrew/bin/codex, so QUOTA_ROUTER_CODEX_BIN has to
    be poisoned separately or the tripwire has a hole in it.
    """
    bin_dir = tmp / "tripwire-bin"
    bin_dir.mkdir(exist_ok=True)
    dud = bin_dir / "dud"
    dud.write_text("#!/bin/sh\necho 'TRIPWIRE: a judge binary was invoked' >&2\nexit 97\n")
    dud.chmod(0o755)
    return {**os.environ,
            "PATH": str(bin_dir),
            "PYTHONPATH": str(ROOT / "scripts"),
            "QUOTA_ROUTER_CODEX_BIN": str(dud),
            "PYTHONHASHSEED": "0"}


def run(paths: dict[str, Path], membership: Path | None, env: dict,
        *, study: str | None = None, extra: list[str] | None = None):
    cmd = [PY, GRADE, "--transcripts", str(paths["transcripts"]),
           "--roster", str(paths["roster"]), "--out", str(paths["out"]),
           "--errors", str(paths["errors"]), "--judges", "fable",
           "--modes", "blinded", "--repeats", "1", "--workers", "1"]
    if membership is not None:
        cmd += ["--membership", str(membership)]
    if study:
        cmd += ["--study", study]
    cmd += extra or []
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env,
                          timeout=180)
    # argparse refusing an unknown --membership produces a non-zero exit whose
    # text contains the word "membership", which would satisfy several checks
    # below for entirely the wrong reason. Fail loudly instead.
    if "unrecognized arguments" in (proc.stdout + proc.stderr):
        raise SystemExit("REFUSING: grade.py does not accept --membership, so every arm "
                         "in this file would pass on argparse's own error text")
    return proc


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = tripwire_env(tmp)

        print("[1] an off-board leader's transcripts never reach the work list")
        p = corpus(tmp / "a", ["alpha", "beta"])
        m = tmp / "m1.json"
        m.write_text(json.dumps({"alpha": ["leaders"], "beta": ["predictions"]}))
        r = run(p, m, env)
        out = r.stdout + r.stderr
        check("the run does not invoke a judge binary", "TRIPWIRE" not in out,
              f"said {out[-400:]!r}")
        check("it says how many transcripts membership dropped",
              "membership: dropping 2 transcript" in out,
              f"said {out[-600:]!r}")
        check("beta is named as the dropped slug", "beta" in out,
              "the operator must be able to see WHO was dropped, not just how many")
        check("alpha is not reported as dropped",
              "dropping" not in out.lower() or "alpha" not in
              out[out.lower().find("membership"):out.lower().find("membership") + 300],
              f"said {out[-400:]!r}")

        print("\n[2] a membership file that excludes EVERYTHING stops the run")
        # This is the arm that matters. `if not paths` runs BEFORE the gate, so
        # without a re-assertion the run exits 0 having graded nobody, which is
        # indistinguishable from a healthy pass with nothing to do.
        p2 = corpus(tmp / "b", ["alpha", "beta"])
        m2 = tmp / "m2.json"
        m2.write_text(json.dumps({"alpha": ["predictions"], "beta": ["predictions"]}))
        r2 = run(p2, m2, env)
        out2 = r2.stdout + r2.stderr
        check("it exits NON-ZERO rather than reporting a clean empty pass",
              r2.returncode != 0,
              f"rc={r2.returncode}; exiting 0 here reads as 'nothing to grade'")
        check("... and says membership is why",
              "membership excludes every transcript" in out2,
              f"said {out2[-500:]!r}")
        check("... and no judge was invoked", "TRIPWIRE" not in out2)

        print("\n[3] the gate runs BEFORE the account router touches a credential")
        # If the router ran first, the poisoned QUOTA_ROUTER_CODEX_BIN would
        # surface before membership could empty the list, and arm [2] would fail
        # naming the tripwire instead of membership. Assert the ordering directly.
        check("the empty-membership run never reached fable_accounts()",
              "TRIPWIRE" not in out2 and "codex" not in out2.lower(),
              f"said {out2[-500:]!r}; the gate must sit above the router")

        print("\n[4] an unknown slug RAISES")
        p4 = corpus(tmp / "d", ["alpha", "beta"])
        m4 = tmp / "m4.json"
        m4.write_text(json.dumps({"alpha": ["leaders"]}))
        r4 = run(p4, m4, env)
        out4 = r4.stdout + r4.stderr
        check("a transcript whose slug is not declared stops the run",
              r4.returncode != 0)
        check("... and the message names the slug", "beta" in out4,
              f"said {out4[-400:]!r}")

        print("\n[5] the slug comes from the RECORD, never the path component")
        # A record filed under one directory but carrying another slug must be
        # judged by what it SAYS. Path components are renameable; the record is
        # the fact.
        p5 = corpus(tmp / "e", ["alpha"])
        rogue = p5["transcripts"] / "alpha" / "rogue.json"
        rogue.write_text(json.dumps({
            "leader_slug": "beta", "transcript_id": "beta/rogue", "source_id": "rogue",
            "word_count": 500, "text": "x " * 50, "fetched_at_utc": "2026-09-01T00:00:00Z"}))
        m5 = tmp / "m5.json"
        m5.write_text(json.dumps({"alpha": ["leaders"], "beta": ["predictions"]}))
        r5 = run(p5, m5, env)
        out5 = r5.stdout + r5.stderr
        # NOT a bare `"beta" in out5`: the record's own transcript_id is
        # "beta/rogue", so that substring appears in the queued-job listing
        # whether or not the gate read the record. MEASURED: with the slug taken
        # from p.parent.name instead, a bare substring check passed all 13 arms.
        # Assert the DROP itself, which only the record-reading version produces.
        check("the record under alpha/ carrying leader_slug beta is dropped as beta",
              "membership: dropping 1 transcript" in out5 and "beta (1)" in out5,
              f"said {out5[-600:]!r}")
        check("... and no judge was invoked", "TRIPWIRE" not in out5)

        print("\n[6] STUDY-SCOPED: a pundits run never refuses for a membership reason")
        p6 = corpus(tmp / "f", ["pundit-a", "pundit-b"])
        r6 = run(p6, tmp / "m1.json", env, study="pundits")
        out6 = (r6.stdout + r6.stderr).lower()
        check("a pundits run's refusal, if any, is not membership's",
              "membership: dropping" not in out6 and "membership excludes" not in out6,
              f"said {out6[-400:]!r}; repo-3's production shares this script")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
