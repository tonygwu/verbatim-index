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


# ---------------------------------------------------------------------------
# 6. Fable routing comes from the llm-quota-router library, not a parsed CLI.
#
# Observed: fable_headroom() shelled out to `quotapick status` and regex-parsed
# its human-readable table, so any change to that table silently turned every
# measurement into "unknown". The library call returns typed rows. The mapping
# from router rows to this script's config-dir sentinels is pure, so it is
# tested here without the library installed.
# ---------------------------------------------------------------------------

def test_quota_routing(g) -> None:
    print("\n[6] Fable routing uses the router library, and maps its rows faithfully")

    fn = getattr(g, "fable_accounts_from_router", None)
    if fn is None:
        check("fable_accounts_from_router() exists", False, "function not defined in grade.py")
        return
    check("fable_accounts_from_router() exists", True)

    accounts = [
        ("claude",   "claude", "/h/.claude",   True),
        ("claude_b", "claude", "/h/.claude-b", False),
        ("claude_c", "claude", "/h/.claude-c", False),
        ("codex",    "codex",  "/h/.codex",    False),
    ]
    rows = [
        {"account": "claude",   "remaining": 0.0,  "eligible": False},
        {"account": "claude_b", "remaining": 0.41, "eligible": True},
        {"account": "codex",    "remaining": 0.9,  "eligible": True},
    ]
    dirs, headroom = fn(accounts, rows)
    check("the default account is addressed by the __DEFAULT__ sentinel, never its path",
          dirs[0] == "__DEFAULT__", f"dirs={dirs}")
    check("non-Claude providers are not Claude Code accounts",
          "/h/.codex" not in dirs and "/h/.codex" not in headroom, f"dirs={dirs}")
    check("configuration order is preserved",
          dirs == ["__DEFAULT__", "/h/.claude-b", "/h/.claude-c"], f"dirs={dirs}")
    check("remaining fractions are carried through unchanged",
          headroom.get("__DEFAULT__") == 0.0 and headroom.get("/h/.claude-b") == 0.41,
          f"headroom={headroom}")
    check("an account the router did not measure is unknown, not zero and not full",
          "/h/.claude-c" not in headroom, f"headroom={headroom}")

    ordered = g.order_accounts_by_fable(dirs, headroom)
    check("the exhausted account is dropped and the unmeasured one is kept",
          set(ordered) == {"/h/.claude-b", "/h/.claude-c"}, f"ordered={ordered}")
    ordered = g.order_accounts_by_fable(
        dirs, {"__DEFAULT__": 0.0, "/h/.claude-b": 0.41, "/h/.claude-c": 0.7})
    check("among measured accounts the richest Fable window goes first",
          ordered == ["/h/.claude-c", "/h/.claude-b"], f"ordered={ordered}")

    src = (REPO / "scripts" / "grade.py").read_text()
    check("grade.py no longer shells out to quotapick",
          '"quotapick"' not in src, "found a quotapick subprocess call")
    check("the judge binary defaults to the plain claude CLI, not the cl wrapper",
          'default="cl"' not in src, "found --fable-bin default of cl")

# ---------------------------------------------------------------------------
# [7] Pinning the Fable rotation to named accounts.
#
# Measured headroom cannot see paid usage credits. An account whose weekly
# Fable window is 100% used reports 0.00 remaining whether or not credits let
# it keep serving, so the operator has to name the accounts that work. A name
# that matches nothing must raise: silently narrowing the rotation would send
# every grade to the wrong account, or to none.
# ---------------------------------------------------------------------------

def test_account_pinning(g) -> None:
    print("\n[7] --fable-accounts pins the rotation to accounts that can actually serve")

    fn = getattr(g, "select_named_accounts", None)
    if fn is None:
        check("select_named_accounts() exists", False, "function not defined in grade.py")
        return
    check("select_named_accounts() exists", True)

    dirs = ["__DEFAULT__", "/h/.claude-b", "/h/.claude-c", "/h/.claude-d"]

    check("'default' names account A, which is addressed by unsetting the variable",
          fn(dirs, "default") == ["__DEFAULT__"], f"got {fn(dirs, 'default')}")
    check("the config-dir basename names an account",
          fn(dirs, ".claude-b") == ["/h/.claude-b"], f"got {fn(dirs, '.claude-b')}")
    check("the basename without its dot names the same account",
          fn(dirs, "claude-b") == ["/h/.claude-b"], f"got {fn(dirs, 'claude-b')}")
    check("a full path names the same account",
          fn(dirs, "/h/.claude-b") == ["/h/.claude-b"], f"got {fn(dirs, '/h/.claude-b')}")
    check("several accounts keep the order they were named in",
          fn(dirs, "claude-c,default") == ["/h/.claude-c", "__DEFAULT__"],
          f"got {fn(dirs, 'claude-c,default')}")
    check("a repeated name is not rotated over twice",
          fn(dirs, "default,default") == ["__DEFAULT__"],
          f"got {fn(dirs, 'default,default')}")
    check("whitespace around a name is not part of the name",
          fn(dirs, " default , claude-b ") == ["__DEFAULT__", "/h/.claude-b"],
          f"got {fn(dirs, ' default , claude-b ')}")

    for bad, why in [("claude-z", "an account that does not exist"),
                     ("__DEFAULT_", "a near-miss on the sentinel"),
                     (",", "a list that names nothing")]:
        try:
            got = fn(dirs, bad)
            check(f"{why} is refused, not guessed", False, f"returned {got}")
        except SystemExit:
            check(f"{why} is refused, not guessed", True)

    # The pin must beat measured headroom. Every account here reads as spent,
    # which is exactly the state credits are bought for.
    spent = {"__DEFAULT__": 0.0, "/h/.claude-b": 0.0, "/h/.claude-c": 0.0, "/h/.claude-d": 0.0}
    check("headroom alone would rotate over all four exhausted accounts",
          g.order_accounts_by_fable(dirs, spent) == dirs,
          f"got {g.order_accounts_by_fable(dirs, spent)}")
    check("the pin narrows that to the one account with credits",
          fn(dirs, "default") == ["__DEFAULT__"], f"got {fn(dirs, 'default')}")

    src = (REPO / "scripts" / "grade.py").read_text()
    check("--fable-accounts is a real flag, not just a function",
          '"--fable-accounts"' in src, "flag not registered with argparse")
    check("the flag can be set from the environment, so the daemon can pass it",
          'os.environ.get("FABLE_ACCOUNTS"' in src, "no FABLE_ACCOUNTS env default")
    loop = (REPO / "scripts" / "grade_loop.sh").read_text()
    check("grade_loop.sh forwards FABLE_ACCOUNTS to both grading passes",
          loop.count("--fable-accounts") == 2, f"found {loop.count('--fable-accounts')}")


def main() -> int:
    g = load_grade()
    print("grading-harness guards")
    test_classification(g)
    test_rotation(g)
    test_limit(g)
    test_tool_block_live(g)
    with tempfile.TemporaryDirectory() as td:
        test_queue_ordering(g, pathlib.Path(td))
    test_quota_routing(g)
    test_account_pinning(g)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
