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

# The CLI's wording when the PAID usage credits run out, which is a different
# refusal from the subscription-window one above: it says "spend limit", never
# "usage limit", and never "reached your". Observed 2026-09-07 after account A
# passed its $175.32 monthly cap. It was landing in cli_nonzero_exit, which
# hides a quota stop inside the bucket meant for genuine crashes.
SPEND_LIMIT_STDOUT = json.dumps({
    "is_error": True,
    "stop_reason": "stop_sequence",
    "result": "You've hit your monthly spend limit \u00b7 raise it at "
              "claude.ai/settings/usage?from=cc_cli_limit_message \u00b7 your weekly "
              "limit resets 4pm",
    "num_turns": 1,
})

QUOTA_STDOUT = json.dumps({
    "is_error": True,
    "stop_reason": "stop_sequence",
    "result": "You've reached your Fable limit. Switch to another model, or manage usage "
              "credits at claude.ai/settings/usage?from=cc_cli_limit_message, to keep going.",
    "num_turns": 1,
})

# The 5-hour window refusal, which is a THIRD wording. Captured verbatim from
# claude-e on 2026-09-07 while the account was refusing, by running the judge's
# own flags and keeping the raw stdout. It shares no phrase with the two above:
# not "reached your", not "usage limit", not "spend limit", and it carries no
# cc_cli_limit_message marker. It was landing in cli_nonzero_exit, so 75 quota
# stops in one pass read as crashes.
#
# The family is "You've <verb> your <scope> limit". Each new <scope> the CLI
# introduces needs adding here, because the matcher tests for whole phrases.
SESSION_LIMIT_STDOUT = json.dumps({
    "is_error": True,
    "stop_reason": "stop_sequence",
    "terminal_reason": "api_error",
    "subtype": "success",
    "result": "You've hit your session limit · resets 2:40pm (America/Los_Angeles)",
    "modelUsage": {},
    "num_turns": 0,
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

    et, detail = fn(1, SPEND_LIMIT_STDOUT, "")
    check("spent-out usage credits -> auth_or_quota, not cli_nonzero_exit",
          et == g.E_AUTH, f"got {et!r}")
    check("spend-limit detail keeps the CLI's own wording",
          "spend limit" in detail, f"got {detail[:120]!r}")

    et, detail = fn(1, SESSION_LIMIT_STDOUT, "")
    check("5-hour session limit -> auth_or_quota, not cli_nonzero_exit",
          et == g.E_AUTH, f"got {et!r}")
    check("session-limit detail keeps the reset time the operator needs",
          "2:40pm" in detail, f"got {detail[:120]!r}")

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


def test_blind_judges_is_configurable(g) -> None:
    """The daemon grades with every published judge, and the set is overridable.

    Two guarantees. The judge list must be changeable without editing a file the
    operator then has to remember to revert. And the default must name every
    PUBLISHED judge: a new transcript graded by a subset reintroduces the uneven
    judge mix that the backfill existed to remove, and widens it every cycle.
    """
    loop = (REPO / "scripts" / "grade_loop.sh").read_text()
    check("grade_loop: blinded judges come from BLIND_JUDGES",
          '--judges "$BLIND_JUDGES"' in loop, "the pass still hardcodes its judges")
    check("grade_loop: the default grades with every published judge",
          'BLIND_JUDGES="${BLIND_JUDGES:-fable,astra,gemini}"' in loop,
          "a new transcript graded by fewer judges than the corpus reintroduces "
          "the uneven mix the backfill removed")
    check("grade_loop: the judges in use are logged, not left to be inferred",
          "blinded judges ${BLIND_JUDGES}" in loop)


def test_failure_taxonomy_names_the_real_cause(g) -> None:
    """A failure is filed under the label it raised, not swept into cli_nonzero_exit.

    FOUND 2026-09-07 in the first Gemini pass: 10 failures, of which 9 were
    reported as `cli_nonzero_exit` while their own detail said
    `transient_retryable` or `empty_response`. The inline classifier enumerated
    five of the eleven labels and everything else fell through to the default.

    That is not cosmetic. The three causes need three different responses: a
    transient should be retried, an empty answer means a denied tool ended the
    turn, and a genuine non-zero exit is a crash. Collapsed into one count, the
    pass reads as broken when it is shedding load, which is exactly the
    "a fully-broken component reads as slow" failure the taxonomy exists to stop.
    """
    check("every taxonomy label is listed in ALL_ERROR_TYPES",
          set(g.ALL_ERROR_TYPES) == {v for k, v in vars(g).items()
                                     if k.startswith("E_") and isinstance(v, str)},
          f"listed={sorted(g.ALL_ERROR_TYPES)}")
    # The exact strings observed in that pass.
    observed = [
        ("transient_retryable: rate-limit/transport error with no quota wording; "
         "safe to retry. matched=transient:timeout", g.E_TRANSIENT),
        ('empty_response: status SUCCESS with an empty response. denied_actions=[]', g.E_EMPTY),
        ("auth_or_quota: exhausted_with_deadline resets in 1554s", g.E_AUTH),
        ("model_identity_mismatch: requested x, telemetry names y", g.E_MODEL_MISMATCH),
        ("cli_nonzero_exit: rc=1 panic", g.E_CLI),
        ("something nobody labelled", g.E_CLI),
    ]
    for detail, want in observed:
        got = g.classify_exception_detail(detail)
        check(f"taxonomy: {detail[:38]!r} -> {want}", got == want, f"got {got}")


def test_a_transient_is_retried_not_discarded(g) -> None:
    """The verdict "safe to retry" must actually cause a retry.

    The load-shedding wave that motivated this raised `transient_retryable`
    correctly and then threw the grade away, because nothing acted on the
    verdict. 8 of 24 calls were lost that way, all of them the last repeat of
    their transcript, which is where order_breadth_first puts the tail of a pass.
    """
    import inspect
    src = inspect.getsource(g.call_gemini)
    check("call_gemini retries rather than failing on the first transient",
          "E_TRANSIENT" in src and "for delay in" in src,
          "no retry loop found in call_gemini")
    # An empty answer is retried too, and for a reason the raw rate understates:
    # the loss lands on transcripts whose content prompts a lookup, so leaving it
    # is a content-correlated hole rather than a uniform 6%.
    check("an empty answer under a SUCCESS status is retried, not accepted",
          '"response":""' in src and "empty_retries" in src,
          "call_gemini treats an empty SUCCESS as a result")
    check("the empty-answer retry is bounded",
          "empty_retries > 2" in src, "an empty answer could retry forever")
    check("attempts and empty retries are recorded on the grade",
          '"attempts": attempts' in src and '"empty_retries": empty_retries' in src,
          "the exposure would only be visible in logs, not in the record")
    check("the retry backs off instead of hammering a source turning us away",
          "time.sleep(delay)" in src)
    check("a non-transient failure breaks out instead of burning the budget",
          "if kind != E_TRANSIENT:" in src and "break" in src)
    # The exact wording the CLI produced under load must reach that branch.
    observed = ('{"conversation_id": "", "status": "ERROR", "response": "", '
                '"error": "authentication failed or timed out", "duration_seconds": 0}')
    got, _d = g.classify_agy_failure(1, observed, now_s=1_800_000_000.0)
    check("the observed load-shedding text classifies as transient, not exhaustion",
          got == g.E_TRANSIENT, f"got {got}")


def test_dead_scaffold_is_not_a_profile(g) -> None:
    """A directory agy scaffolded but nobody logged into is not a profile.

    FOUND 2026-09-07: `agy` creates $HOME/.gemini/... on startup, so a stray
    `HOME=... agy` invocation leaves a directory shaped exactly like a profile
    with no credential in it. One entered a 501-job rotation and would have
    failed every third call.

    SUPERSEDED IN PART, 2026-09-10. This used to also assert that a non-default
    HOME carrying a token stays in the rotation, on the belief that such a home
    could not reach the Keychain and therefore held its own account. It can
    reach it: both HOMEs logged "authenticated via keyring", and all 567 Gemini
    grades in the corpus came from ONE account while two HOMEs alternated. The
    credential is one Keychain item per macOS USER, so every HOME under this
    user serves the same account. An extra HOME is now skipped, loudly, and a
    second account is a `user:` profile. See scripts/test_gemini_user_profile.py.
    """
    with tempfile.TemporaryDirectory() as td:
        root, home = Path(td) / ".agy-homes", Path(td) / "home"
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True)   # no token: the DEFAULT
        live = root / "live" / ".gemini" / "antigravity-cli"
        live.mkdir(parents=True)
        (live / "antigravity-oauth-token").write_text("{}")
        (root / "scaffold" / ".gemini" / "antigravity-cli").mkdir(parents=True)  # no token
        got = g.agy_profiles(root=root, default_home=str(home))
        os.environ["GEMINI_EXTRA_HOMES"] = "1"
        try:
            forced = g.agy_profiles(root=root, default_home=str(home))
        finally:
            del os.environ["GEMINI_EXTRA_HOMES"]

    check("agy_profiles: the default home is kept even with no token (Keychain auth)",
          str(home) in got, f"got {got}")
    check("agy_profiles: an extra HOME is skipped; it shares one Keychain item "
          "and so cannot be a second account",
          str(root / "live") not in got, f"got {got}")
    check("agy_profiles: GEMINI_EXTRA_HOMES=1 puts it back for a future agy",
          str(root / "live") in forced, f"got {forced}")
    check("agy_profiles: a scaffold with no token is not a profile",
          str(root / "scaffold") not in got and str(root / "scaffold") not in forced,
          f"got {got} / {forced}")


def test_a_spent_profile_is_stepped_around(g) -> None:
    """The only quota signal Antigravity gives is a pool saying it is spent.

    There is no usage endpoint, so the rotation cannot be ranked by headroom.
    What it can do is stop routing to a pool inside the dead window that pool
    itself named. A deadline that cannot be parsed benches nothing: guessing a
    duration would remove half the rotation on a guess.
    """
    A, B = "/home/a", "/home/b"
    now = 1_800_000_000.0
    g._GEMINI_BENCH.clear()
    check("picker: with nothing benched, the round-robin assignment stands",
          g.pick_gemini_profile(A, [A, B], now) == A)

    g.bench_gemini_profile(A, now + 600)
    check("picker: a benched profile is stepped around",
          g.pick_gemini_profile(A, [A, B], now) == B)
    check("picker: the other profile is untouched",
          g.pick_gemini_profile(B, [A, B], now) == B)
    check("picker: the bench expires on its own",
          g.pick_gemini_profile(A, [A, B], now + 601) == A)

    g.bench_gemini_profile(B, now + 600)
    check("picker: with every profile spent the call is still made, so it fails "
          "into the taxonomy instead of vanishing",
          g.pick_gemini_profile(A, [A, B], now) == A)

    g._GEMINI_BENCH.clear()
    g.bench_gemini_profile(A, None)
    check("picker: an unparseable deadline benches nothing",
          g.pick_gemini_profile(A, [A, B], now) == A)

    # The deadline must come from agy's own wording, via the router.
    until = g.agy_exhausted_until("Individual quota reached. Resets in 25m54s", now)
    check("picker: agy's relative reset wording yields a real deadline",
          until is not None and 1500 < until - now < 1600, f"got {until}")
    check("picker: a message with no reset time yields None, never 'now'",
          g.agy_exhausted_until("something went wrong", now) is None)


def test_gemini_profiles(g) -> None:
    """The Antigravity rotation is a glob, and it must not gate on a token file.

    The account list is a glob, never hardcoded letters: this machine has
    already made that mistake twice with the Claude accounts, once for D and
    once for E, so assume a third Antigravity account will appear.

    Token rules live in test_dead_scaffold_is_not_a_profile. In short, the
    default home is exempt because it authenticates from the Keychain, and a
    non-default one is not because it cannot reach a Keychain at all.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / ".agy-homes"
        home = Path(td) / "home"
        (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
        for name in ("zeta", "alpha"):          # created out of sorted order
            d = root / name / ".gemini" / "antigravity-cli"
            d.mkdir(parents=True)
            (d / "antigravity-oauth-token").write_text("{}")
        # A directory that is not a profile at all must not join the rotation.
        (root / "not-a-profile").mkdir(parents=True)
        got = g.agy_profiles(root=root, default_home=str(home))
        os.environ["GEMINI_EXTRA_HOMES"] = "1"
        try:
            forced = g.agy_profiles(root=root, default_home=str(home))
        finally:
            del os.environ["GEMINI_EXTRA_HOMES"]

    check("agy_profiles: default HOME leads the rotation",
          got and got[0] == str(home), f"got {got}")
    check("agy_profiles: extra HOMEs are skipped, so the rotation is the default alone",
          got == [str(home)], f"got {got}")
    check("agy_profiles: under GEMINI_EXTRA_HOMES they return, still sorted",
          [Path(p).name for p in forced[1:]] == ["alpha", "zeta"], f"got {forced}")
    check("agy_profiles: a directory without antigravity-cli is not a profile",
          str(root / "not-a-profile") not in got and str(root / "not-a-profile") not in forced,
          f"got {got} / {forced}")


def test_gemini_identity_is_not_read_by_mtime(g) -> None:
    """Identity comes from the log a call wrote, never from the newest by mtime.

    FOUND 2026-09-07: the first version sorted a profile's log directory by
    st_mtime and named the WRONG account. A renamed or reused profile keeps its
    old logs, and mtime records when a file was touched rather than what is in
    it. This test reproduces exactly that: a stale log carrying the other
    account is given the newest mtime, and the reader must be unaffected because
    it is handed one explicit path.
    """
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        stale = d / "cli-20260101_000000.log"
        stale.write_text("signed in as olduser@example.com\n")
        mine = d / "cli-20260907_204743.log"
        mine.write_text("[AuthProvider] account=realuser@example.com\nauth ok\n")
        # Make the STALE file the newest by mtime, the trap that caught this.
        os.utime(stale, (2 ** 31 - 1, 2 ** 31 - 1))

        got = g.agy_identity_from_log(mine)
        check("agy_identity_from_log: reads the log it was given, not the newest mtime",
              got == "realuser@example.com", f"got {got!r}")
        check("agy_identity_from_log: a missing log is None, not a crash",
              g.agy_identity_from_log(d / "nope.log") is None)
        empty = d / "empty.log"; empty.write_text("no addresses here\n")
        check("agy_identity_from_log: a log with no address is None",
              g.agy_identity_from_log(empty) is None)


def test_gemini_command(g) -> None:
    """The flags that make this arm auditable and safe are actually passed.

    stream-json is the ONLY output mode that names the model that answered, so
    dropping it would silently remove the arm's one identity assertion and
    leave it in the same unverifiable position as the Astra arm.
    """
    cmd = g.gemini_command("PROMPT", "gemini-3.8-flash-high", "agy", 540, Path("/tmp/x.log"))
    check("gemini_command: stream-json, the only mode that names the served model",
          "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "stream-json",
          f"got {cmd}")
    check("gemini_command: pins this call's log path, so identity needs no guessing",
          "--log-file" in cmd and cmd[cmd.index("--log-file") + 1] == "/tmp/x.log")
    check("gemini_command: slash-command expansion off, so a '/' transcript line is data",
          "--disable-slash-commands" in cmd)
    check("gemini_command: never auto-approves tools; the judge is blinded against this repo",
          "--dangerously-skip-permissions" not in cmd)
    check("gemini_command: requests the model it was told to",
          cmd[cmd.index("--model") + 1] == "gemini-3.8-flash-high")


def test_gemini_failure_classification(g) -> None:
    """A quota stop is a quota stop, not a crash.

    Same reason classify_cli_failure exists for the Claude CLI: both exit
    non-zero, and a bare cli_nonzero_exit count cannot tell them apart after
    the fact. The Antigravity wording is the one llm-quota-router already
    parses a reset deadline out of.
    """
    cases = [
        ("Individual quota reached. Please try later. Resets in 25m54s", g.E_AUTH),
        ("RESOURCE_EXHAUSTED: please try again later", g.E_AUTH),
        ('model gemini-9 is not recognized as a known model', g.E_MODEL_MISMATCH),
        ("panic: runtime error: index out of range", g.E_CLI),
        # The two that a first version got WRONG, in the direction that benches a
        # healthy account. An OAuth refresh race between concurrent headless
        # spawns arrives carrying a 429 and means retry, not exhaustion.
        ("Not logged in \u00b7 Please run /login", g.E_TRANSIENT),
        ("rate_limit exceeded (429)", g.E_TRANSIENT),
        # MEASURED in the backfill: this arrived while both profiles were signed
        # in, and the next two jobs succeeded on those same profiles seconds
        # later. A real logout does not repair itself between calls.
        ("error getting token source: You are not logged into Antigravity.", g.E_TRANSIENT),
        # A real exhaustion must still win, or the retry loop hammers a spent pool.
        ("Individual quota reached. Resets in 25m54s", g.E_AUTH),
    ]
    for blob, want in cases:
        got, _detail = g.classify_agy_failure(1, blob, now_s=1_800_000_000.0)
        check(f"classify_agy_failure: {blob[:34]!r} -> {want}", got == want, f"got {got}")

    # A quota stop must carry its reset time, or a scheduler has nothing to wait on.
    _k, detail = g.classify_agy_failure(1, "Individual quota reached. Resets in 25m54s",
                                        now_s=1_800_000_000.0)
    check("classify_agy_failure: an exhaustion deadline reaches the log line",
          "resets in" in detail and "155" in detail, f"got {detail!r}")
    check("classify_agy_failure: empty text is not silently a quota stop",
          g.classify_agy_failure(1, "", now_s=1_800_000_000.0)[0] == g.E_CLI)


def test_gemini_tool_accounting(g) -> None:
    """Only tools that COMPLETED count, and what was looked up is captured.

    This judge has live web search that cannot be disabled: its permission
    system knows three grant actions plus mcp, and rejects any rule naming a
    builtin tool. The exposure is accepted, so it has to be visible. A step that
    ended in ERROR returned nothing to the judge and must not be counted, or the
    record overstates what the judge actually saw.
    """
    events = [
        {"event": "init", "init": {"model": "gemini-3.8-flash-high"}},
        {"event": "step_update", "step_update": {
            "step_type": "tool", "state": "ACTIVE", "tool_name": "search_web",
            "tool_info": {"parameters": {"query": "who is the speaker"}}}},
        {"event": "step_update", "step_update": {
            "step_type": "tool", "state": "DONE", "tool_name": "search_web",
            "tool_info": {"parameters": {"query": "who is the speaker"}}}},
        {"event": "step_update", "step_update": {
            "step_type": "tool", "state": "ERROR", "tool_name": "view_file",
            "tool_info": {"parameters": {"AbsolutePath": "/roster.json"}}}},
        {"event": "step_update", "step_update": {
            "step_type": "agent_response", "state": "DONE"}},
    ]
    counts, queries = g.count_gemini_tool_events(events)
    check("count_gemini_tool_events: a completed search counts exactly once",
          counts.get("search_web") == 1, f"got {counts}")
    check("count_gemini_tool_events: an ACTIVE step is not double-counted",
          sum(counts.values()) == 1, f"got {counts}")
    check("count_gemini_tool_events: an ERRORed tool returned nothing, so it is not counted",
          "view_file" not in counts, f"got {counts}")
    check("count_gemini_tool_events: the search terms are recorded, not just a tally",
          any("who is the speaker" in q for q in queries), f"got {queries}")

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
    test_blind_judges_is_configurable(g)
    test_failure_taxonomy_names_the_real_cause(g)
    test_a_transient_is_retried_not_discarded(g)
    test_dead_scaffold_is_not_a_profile(g)
    test_a_spent_profile_is_stepped_around(g)
    test_gemini_profiles(g)
    test_gemini_identity_is_not_read_by_mtime(g)
    test_gemini_command(g)
    test_gemini_failure_classification(g)
    test_gemini_tool_accounting(g)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
