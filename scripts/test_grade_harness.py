#!/usr/bin/env python3
"""Guards for the four grading-harness bugs found on 2026-09-06.

Every test here was written failing first, against the behaviour actually
observed in the run, and each one names the evidence that motivated it.

The pure tests need no network and no quota. The live test costs real Fable
tokens, so it only runs with GRADE_LIVE=1.

  .venv/bin/python scripts/test_grade_harness.py
  GRADE_LIVE=1 .venv/bin/python scripts/test_grade_harness.py
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import pathlib
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_grade():
    spec = importlib.util.spec_from_file_location("grade_mod", REPO / "scripts" / "grade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


# ---------------------------------------------------------------------------
# 1. Failure classification.
#
# Observed: 262 failures all logged as bare `cli_nonzero_exit` with empty
# stderr, which said nothing about why. Two different causes were hiding
# behind that one code. The reason is in STDOUT, which the old code never
# read because it raised on the return code first.
# ---------------------------------------------------------------------------

QUOTA_STDOUT = json.dumps({
    "is_error": True,
    "stop_reason": "stop_sequence",
    "result": "You've reached your Fable limit. Switch to another model, or manage usage "
              "credits at claude.ai/settings/usage?from=cc_cli_limit_message, to keep going.",
    "num_turns": 1,
})

TOOL_STDOUT = json.dumps({
    "is_error": False,
    "stop_reason": "tool_use",
    "result": None,
    "num_turns": 2,
    "permission_denials": [],
})

CRASH_STDOUT = ""


def test_classification(g) -> None:
    print("\n[1] failure classification reads stdout, not just the return code")

    fn = getattr(g, "classify_cli_failure", None)
    if fn is None:
        check("classify_cli_failure() exists", False, "function not defined in grade.py")
        return
    check("classify_cli_failure() exists", True)

    et, detail = fn(1, QUOTA_STDOUT, "")
    check("quota refusal -> auth_or_quota (not cli_nonzero_exit)",
          et == g.E_AUTH, f"got {et!r}")
    check("quota detail keeps the CLI's own wording",
          "Fable limit" in detail, f"got {detail[:120]!r}")

    et, detail = fn(1, TOOL_STDOUT, "")
    check("tool attempt -> its own error class",
          et == g.E_TOOL_ATTEMPT, f"got {et!r}")

    et, detail = fn(1, CRASH_STDOUT, "some stderr text")
    check("unparseable stdout still falls back to cli_nonzero_exit",
          et == g.E_CLI, f"got {et!r}")
    check("fallback surfaces stderr so it is not silently empty",
          "some stderr text" in detail, f"got {detail[:120]!r}")


# ---------------------------------------------------------------------------
# 2. Account rotation.
#
# Observed: jobs are enumerated over product(paths, judges) with
# judges = [fable, astra], so Fable always lands on an even index. With
# cfg_dirs[i % 4] that reaches only accounts 0 and 2. On this machine those
# are the two with no Fable headroom, so ~half of all Fable calls failed
# while the two healthy accounts were never asked.
# ---------------------------------------------------------------------------

def test_rotation(g) -> None:
    print("\n[2] Fable jobs reach every account, not just the even-indexed ones")

    fn = getattr(g, "assign_accounts", None)
    if fn is None:
        check("assign_accounts() exists", False, "function not defined in grade.py")
        return
    check("assign_accounts() exists", True)

    accounts = ["acct0", "acct1", "acct2", "acct3"]
    judges = ["fable", "astra"]
    combos = list(itertools.product([f"t{n}" for n in range(12)], judges))
    got = {}
    for idx, (path, judge) in enumerate(combos):
        acct = fn(judge, idx, accounts, judges)
        if judge == "fable":
            got[acct] = got.get(acct, 0) + 1

    check("every account receives Fable work",
          set(got) == set(accounts), f"reached only {sorted(got)}")
    if got:
        spread = max(got.values()) - min(got.values())
        check("Fable work is spread evenly across accounts",
              spread <= 1, f"counts {got}")

    # And the old formula must be demonstrably worse, or this test proves nothing.
    old = {}
    for idx, (path, judge) in enumerate(combos):
        if judge == "fable":
            a = accounts[idx % len(accounts)]
            old[a] = old.get(a, 0) + 1
    check("the old i%%N formula really did collapse onto half the accounts",
          set(old) != set(accounts), f"old reached {sorted(old)}")


# ---------------------------------------------------------------------------
# 3. --limit-per-leader 0.
#
# Observed: the loop was started with OPEN_PER_LEADER=0 meaning "skip the
# unblinded pass". grade.py tested `if args.limit_per_leader:` so 0 was
# falsy and meant UNLIMITED. The control pass graded all 313 transcripts
# instead of ~2 per leader.
# ---------------------------------------------------------------------------

def test_limit(g) -> None:
    print("\n[3] --limit-per-leader 0 means none, not unlimited")

    fn = getattr(g, "apply_per_leader_limit", None)
    if fn is None:
        check("apply_per_leader_limit() exists", False, "function not defined in grade.py")
        return
    check("apply_per_leader_limit() exists", True)

    paths = [f"leader{n // 5}/tx{n}" for n in range(20)]
    slug = lambda p: p.split("/")[0]  # noqa: E731

    check("0 keeps nothing", fn(paths, 0, slug) == [], "0 must mean skip")
    check("None keeps everything", len(fn(paths, None, slug)) == 20)
    kept = fn(paths, 2, slug)
    check("2 keeps two per leader", len(kept) == 8, f"kept {len(kept)}")
    per = {}
    for p in kept:
        per[slug(p)] = per.get(slug(p), 0) + 1
    check("no leader exceeds the cap", all(v <= 2 for v in per.values()), f"{per}")


# ---------------------------------------------------------------------------
# 4. Tool access. The integrity test.
#
# Observed: with the production flags the judge tried to Read
# data/roster/final.json and permission_denials came back EMPTY, meaning
# nothing blocked it. Only --max-turns 1 stopped the run, by failing it.
# A judge that can read the roster can undo the blinding.
# ---------------------------------------------------------------------------

def test_tool_block_live(g) -> None:
    print("\n[4] LIVE: the judge cannot read the roster")
    if os.environ.get("GRADE_LIVE") != "1":
        print("  SKIP  set GRADE_LIVE=1 to run (costs Fable tokens)")
        return

    import subprocess
    jail = Path("/tmp/judge-jail")
    jail.mkdir(parents=True, exist_ok=True)
    roster = REPO / "data" / "roster" / "final.json"
    probe = (f"Read the file {roster} and tell me the first leader name. "
             f"If you cannot use tools, reply exactly NO_TOOLS.")

    cmd = g.fable_command(probe, "claude")
    env = dict(os.environ)
    # Which account pays for the live probe. Override with GRADE_LIVE_CONFIG_DIR;
    # the default is one that had Fable headroom when this was written.
    env["CLAUDE_CONFIG_DIR"] = os.environ.get(
        "GRADE_LIVE_CONFIG_DIR", str(Path.home() / ".claude-b"))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          env=env, cwd=str(jail))
    payload = {}
    if proc.stdout.strip().startswith("{"):
        payload = json.loads(proc.stdout)
    result = str(payload.get("result") or "")
    denials = payload.get("permission_denials") or []

    check("run completes instead of failing on the tool attempt",
          proc.returncode == 0, f"rc={proc.returncode}")
    check("the roster contents do not reach the judge",
          "Elon" not in result, f"result={result[:160]!r}")
    check("a tool attempt is recorded as DENIED, not silently allowed",
          len(denials) > 0 or "NO_TOOLS" in result,
          f"denials={denials} result={result[:160]!r}")


# ---------------------------------------------------------------------------
# 5. Queue ordering. The starvation bug.
#
# Observed 2026-09-06: Fable held blinded grades for exactly the alphabetically
# first 20 leaders and none of the last 20. grade.py built its queue with
# itertools.product over a SORTED path list, so every cycle walked the leaders
# in the same order. Fable ran out of session quota part-way down and stopped
# in the same place each time, so slugs 21-40 were attempted and rejected in
# seconds on every cycle. yann-lecun sorts 40th of 40 and never got one grade.
# Failure split from data/logs/grade_errors_blind.jsonl was prefix 57 /
# suffix 168: the live quota all went to the prefix.
# ---------------------------------------------------------------------------
def test_queue_ordering(g, tmp) -> None:
    print("\n[5] the queue is ordered breadth-first, so a quota stop truncates evenly")

    fn = getattr(g, "order_breadth_first", None)
    if fn is None:
        check("order_breadth_first() exists", False, "function not defined in grade.py")
        return
    check("order_breadth_first() exists", True)

    leaders = [f"leader-{n:02d}" for n in range(40)]

    def mkjobs(done_for=None):
        done_for = done_for or {}
        jobs = []
        for slug in leaders:                      # alphabetical, as product() emits
            for i in range(8):
                dest = tmp / "fable" / slug / f"tx{i}__fable__blinded__r0.json"
                if i < done_for.get(slug, 0):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text("{}")
                jobs.append({"judge": "fable", "mode": "blinded",
                             "rec": {"leader_slug": slug}, "dest": str(dest)})
        return jobs

    jobs = mkjobs()
    # The regression itself: alphabetical order gives the first 40 slots to 5 leaders.
    check("the old alphabetical order really did starve the tail",
          len({j["rec"]["leader_slug"] for j in jobs[:40]}) == 5,
          f"{len({j['rec']['leader_slug'] for j in jobs[:40]})} leaders in the first 40")

    out = fn(jobs)
    check("no job is lost or duplicated", len(out) == len(jobs) and
          {id(j) for j in out} == {id(j) for j in jobs}, f"{len(out)} vs {len(jobs)}")
    first = [j["rec"]["leader_slug"] for j in out[:40]]
    check("every leader gets its first grade before any gets a second",
          sorted(first) == leaders, f"{len(set(first))} distinct leaders in the first 40")
    check("yann-lecun's position no longer decides whether he is graded",
          out[39]["rec"]["leader_slug"] == leaders[-1], out[39]["rec"]["leader_slug"])

    # Depth must count grades already on disk, or a well-covered leader keeps
    # jumping the queue ahead of an uncovered one on the next cycle.
    deep = {leaders[0]: 7}
    out2 = fn(mkjobs(done_for=deep))
    pending = [j for j in out2 if not pathlib.Path(j["dest"]).exists()]
    check("cached jobs are not counted as pending", len(pending) == 40 * 8 - 7,
          f"{len(pending)} pending")
    check("a leader with 7 grades already on disk waits behind leaders with none",
          pending[0]["rec"]["leader_slug"] != leaders[0], pending[0]["rec"]["leader_slug"])
    check("free cached jobs are still queued first",
          all(pathlib.Path(j["dest"]).exists() for j in out2[:7]),
          "cached work should resolve before quota is spent")


def main() -> int:
    g = load_grade()
    print("grading-harness guards")
    test_classification(g)
    test_rotation(g)
    test_limit(g)
    test_tool_block_live(g)
    with tempfile.TemporaryDirectory() as td:
        test_queue_ordering(g, pathlib.Path(td))
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
