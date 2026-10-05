#!/usr/bin/env python3
"""Fable with web search, as a DATER only (coordinator, 2026-10-04). No quota, no network.

The Fable dater ran through the judge harness (grade.call_fable), where every tool
is denied, so it answered from memory. date_recordings.call_fable_web is a separate,
dating-only harness. These tests pin what it may and may not do:

  ARGV      raw claude -p, never cl and never --dangerously-skip-permissions;
            exactly WebSearch and WebFetch in --tools and --allowedTools;
            --permission-prompts none; the judge harness is unchanged
  SANDBOX   sandbox-exec denies reads and writes under the verbatim-index
            container, the data checkout and this checkout; the call runs in a
            working directory outside them, or not at all
  AUDIT     the session transcript is the evidence: web searches and fetches are
            counted with their queries and URLs; any other tool fails the call as
            judge_attempted_tool_use; no transcript fails it as tool_audit_unavailable;
            a response with no Fable model fails it as model_identity_mismatch
  ROUTING   --harness fable_web is a dater; its calls rotate over --fable-config-dir;
            Astra rotates over --codex-home

  .venv/bin/python scripts/test_dating_fable_web.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import date_recordings as DR  # noqa: E402
import grade as G  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"


def payload(models=("claude-fable-5-1",), result='{"verdict": "cannot_date"}', is_error=False):
    return json.dumps({"is_error": is_error, "result": result, "session_id": SESSION, "num_turns": 7,
                       "total_cost_usd": 1.5, "duration_ms": 1000,
                       "usage": {"server_tool_use": {"web_search_requests": 2}},
                       "modelUsage": {m: {"inputTokens": 10, "outputTokens": 5, "canonicalModel": m} for m in models}})


def transcript(config: Path, tools: list[tuple[str, dict]]) -> None:
    d = config / "projects" / "-tmp-dating"
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (name, inp) in enumerate(tools):
        lines.append({"message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}})
        lines.append({"message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
    (d / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


class Runner:
    def __init__(self, stdout, rc=0):
        self.stdout, self.rc, self.calls = stdout, rc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=self.rc, stdout=self.stdout, stderr="")


class Argv(unittest.TestCase):
    def test_exactly_two_web_tools_and_never_the_skip_permissions_flag(self):
        cmd = DR.fable_web_command("PROMPT", "claude")
        self.assertEqual(cmd[:3], ["claude", "-p", "PROMPT"])
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-fable-5-1")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "WebSearch,WebFetch")
        self.assertEqual(cmd[cmd.index("--permission-prompts") + 1], "none")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertNotIn("--dangerously-skip-permissions", " ".join(cmd))
        with self.assertRaisesRegex(RuntimeError, "cl launcher"):
            DR.fable_web_command("PROMPT", "/usr/local/bin/cl")

    def test_the_judge_harness_still_denies_every_tool(self):
        judge = G.fable_command("PROMPT", "claude")
        self.assertEqual(judge[judge.index("--allowedTools") + 1], "")
        self.assertNotIn("--tools", judge)


class Sandbox(unittest.TestCase):
    def test_the_container_is_found_from_a_clone_a_worktree_and_a_data_clone(self):
        c = Path("/x/Code/misc/verbatim-index")
        self.assertEqual(DR.sandbox_roots(c / "repo-0/.claude/worktrees/agent-a", c / "data"), [c])
        self.assertEqual(DR.sandbox_roots(c / "repo-2", c / "repo-2/.data-clones/main"), [c])
        self.assertEqual(DR.sandbox_roots(Path("/y/checkout"), Path("/z/data")), [Path("/y/checkout"), Path("/z/data")])

    def test_the_profile_denies_reads_and_writes_under_every_root(self):
        prof = DR.sandbox_profile([Path("/a"), Path("/b")])
        for r in ("/a", "/b"):
            self.assertIn(f'(deny file-read* (subpath "{r}"))', prof)
            self.assertIn(f'(deny file-write* (subpath "{r}"))', prof)


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "claude-x"
        self.work = self.root / "work"

    def call(self, runner):
        return DR.call_fable_web("PROMPT", str(self.config), 60, workdir=str(self.work), runner=runner)

    def test_searches_and_fetches_are_counted_from_the_session_transcript(self):
        transcript(self.config, [("WebSearch", {"query": "Greylock Reid Hoffman Dara Khosrowshahi"}),
                                 ("WebFetch", {"url": "https://greylock.com/greymatter/uber/", "prompt": "date?"}),
                                 ("WebSearch", {"query": "Iconversations February 2021"})])
        r = Runner(payload(models=("claude-fable-5-1", "claude-haiku-4-5")))
        text, tel = self.call(r)
        self.assertEqual(text, '{"verdict": "cannot_date"}')
        self.assertEqual((tel["web_searches"], tel["web_fetches"]), (2, 1))
        self.assertEqual(tel["web_search_queries"], ["Greylock Reid Hoffman Dara Khosrowshahi",
                                                     "Iconversations February 2021"])
        self.assertEqual(tel["fetched_urls"], ["https://greylock.com/greymatter/uber/"])
        self.assertEqual(tel["judge_model"], "claude-fable-5-1")
        self.assertEqual(tel["telemetry_models"], ["claude-fable-5-1", "claude-haiku-4-5"])
        self.assertEqual(tel["server_web_search_requests"], 2)
        cmd, kw = r.calls[0]
        self.assertEqual(cmd[:2], ["sandbox-exec", "-p"])
        for root in DR.sandbox_roots():
            self.assertIn(f'(deny file-read* (subpath "{root}"))', cmd[2])
        self.assertEqual(kw["cwd"], str(self.work))
        self.assertEqual(kw["env"]["CLAUDE_CONFIG_DIR"], str(self.config))

    def test_a_call_to_any_other_tool_fails_the_answer(self):
        transcript(self.config, [("WebSearch", {"query": "x"}), ("Bash", {"command": "cat data/roster/final.json"})])
        with self.assertRaisesRegex(RuntimeError, G.E_TOOL_ATTEMPT):
            self.call(Runner(payload()))

    def test_no_transcript_means_no_audit_and_no_answer(self):
        with self.assertRaisesRegex(RuntimeError, G.E_NO_TRANSCRIPT):
            self.call(Runner(payload()))

    def test_a_run_the_turn_budget_ended_is_labelled_so_not_as_a_tool_violation(self):
        """FOUND in the pilot (2026-10-04): 53 searches and 55 fetches, then the turn budget; grade called it
        judge_attempted_tool_use, which here would read as a breach of the tool list."""
        stop = json.dumps({"is_error": True, "result": "", "stop_reason": "tool_use", "num_turns": 81,
                           "permission_denials": []})
        with self.assertRaisesRegex(RuntimeError, f"^{DR.E_TURN_BUDGET}: .*turns=81 denials=0"):
            self.call(Runner(stop, rc=1))

    def test_the_prompt_gives_the_research_budget(self):
        prompt, _ = DR.DL.build_dating_prompt({"leader_slug": "ada", "source_id": "x", "text": "w"}, [],
                                              harness="fable_web")
        self.assertIn("at most 20 searches and 20 page opens", prompt)
        self.assertGreater(DR.FABLE_WEB_MAX_TURNS, 40)

    def test_a_response_with_no_fable_model_is_refused(self):
        transcript(self.config, [])
        with self.assertRaisesRegex(RuntimeError, G.E_MODEL_MISMATCH):
            self.call(Runner(payload(models=("claude-sonnet-5",))))

    def test_a_working_directory_inside_a_denied_root_is_refused_before_any_call(self):
        r = Runner(payload())
        inside = DR.sandbox_roots()[0] / "tmp-dating-work-never-made"
        with self.assertRaisesRegex(RuntimeError, "inside a denied root"):
            DR.call_fable_web("PROMPT", str(self.config), 60, workdir=str(inside), runner=r)
        self.assertEqual(r.calls, [])
        self.assertFalse(inside.exists(), "a refused working directory must never be created")


class Routing(unittest.TestCase):
    def args(self, **kw):
        base = {"harness": "gemini,fable_web", "fable_config_dir": "/c1,/c2", "codex_home": "/h1,/h2",
                "fable_bin": "claude", "astra_model": "gpt-6-astra", "gemini_model": "gemini-3.8-flash-high",
                "agy_bin": "agy"}
        return types.SimpleNamespace(**{**base, **kw})

    def test_fable_web_is_a_dater_and_rotates_over_the_config_dirs(self):
        self.assertIn("fable_web", DR.HARNESSES)
        self.assertEqual(DR.daters(self.args()), ["gemini", "fable_web"])
        self.assertEqual(DR.requested_model(self.args(), "fable_web"), "claude-fable-5-1")
        seen = []

        def fake(prompt, cfg, timeout, binary="claude", workdir=None):
            seen.append(cfg)
            return "{}", {"judge_model": "claude-fable-5-1"}
        orig = DR.call_fable_web
        DR.call_fable_web = fake
        try:
            for i in range(3):
                _, tel, who = DR.call_agent("fable_web", "P", 5, Path(tempfile.gettempdir()) / "fw", self.args(), i)
                self.assertEqual(tel["served_model"], "claude-fable-5-1")
        finally:
            DR.call_fable_web = orig
        self.assertEqual(seen, ["/c1", "/c2", "/c1"])

    def test_astra_rotates_over_the_codex_homes(self):
        self.assertEqual(DR.codex_homes(self.args()), ["/h1", "/h2"])
        self.assertEqual(DR.codex_homes(self.args(codex_home=None)), ["__DEFAULT__"])
        with self.assertRaises(SystemExit):
            DR.codex_homes(self.args(codex_home="/h1,"))


if __name__ == "__main__":
    unittest.main()
