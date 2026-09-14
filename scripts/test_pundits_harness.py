#!/usr/bin/env python3
"""The pundits judge harness: sandboxed judges, Fable without tools, leaders unchanged.

Pundits plan, P3, as decided on 2026-09-14. All three judges run under a
`sandbox-exec` profile that denies reads and writes under the verbatim-index
container, so no judge can read the repository, the roster or the private lean
labels. Fable also runs with `--tools ""` and must show zero tool calls in its
own session transcript. Provider-side web search by Astra and Gemini is accepted
and measured, not blocked.

No quota: every judge CLI is replaced by a stub that captures its argv. The one
real process is `sandbox-exec` running /bin/cat, to prove the profile denies.

  SANDBOX        the profile denies a read inside the root and allows one outside it
  FABLE          a pundits call is wrapped and ends with --tools ""; a leaders call
                 builds exactly fable_command's argv; zero transcript tool calls
                 pass; any tool call, or no transcript at all, fails loudly
  ASTRA/GEMINI   a pundits call is wrapped; a leaders call is not; a Gemini user
                 profile is refused under the sandbox rather than guessed at
  PROFILE        v2_harness reads the profile: Fable gets its extra args and the
                 no-tools audit, an unknown sandbox or extra args on another
                 judge are refused
  GRADE_ONE      a contract v2 job hands the harness to the judge call; a leaders
                 job hands it nothing

  .venv/bin/python scripts/test_pundits_harness.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load_grade():
    spec = importlib.util.spec_from_file_location("grade_p3h", REPO / "scripts" / "grade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Captured:
    """Replaces subprocess.run for one call and returns canned output."""

    def __init__(self, stdout: str, rc: int = 0):
        self.stdout, self.rc, self.argv = stdout, rc, None

    def __call__(self, argv, **kw):
        self.argv = list(argv)
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, "")


def with_run(fake, fn):
    real = subprocess.run
    subprocess.run = fake
    try:
        return fn()
    finally:
        subprocess.run = real


def raises(fn, needle: str) -> bool:
    try:
        fn()
    except (RuntimeError, SystemExit) as exc:
        return needle in str(exc)
    return False


def transcript(config: Path, sid: str, tool_calls: int) -> None:
    d = config / "projects" / "jail-x"
    d.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "grade"}]}}]
    for i in range(tool_calls):
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "whoami"}}]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "is_error": False, "content": "someone"}]}})
    (d / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def fable_stdout(sid: str) -> str:
    return json.dumps({"result": '{"transcript_id": "x/y"}', "session_id": sid,
                       "modelUsage": {"claude-fable-5-1": {"inputTokens": 10, "outputTokens": 5}},
                       "usage": {"output_tokens_details": {"thinking_tokens": 3}}})


def main() -> int:
    print("pundits judge harness")
    try:
        G = load_grade()
    except Exception as exc:
        check("grade.py loads", False, repr(exc))
        return 1
    needed = ("sandbox_profile", "sandbox_wrapper", "v2_harness", "fable_transcript_tool_calls")
    missing = [n for n in needed if not hasattr(G, n)]
    check("grade.py exposes the harness functions", not missing, f"missing {missing}")
    if missing:
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    with tempfile.TemporaryDirectory(prefix="p3-harness-") as td:
        tmp = Path(td).resolve()
        root, outside = tmp / "container", tmp / "outside"
        (root / "repo").mkdir(parents=True)
        outside.mkdir()
        (root / "repo" / "roster.json").write_text("SECRET-ROSTER")
        (outside / "ok.txt").write_text("fine")
        wrapper = G.sandbox_wrapper(root)

        print("\n[SANDBOX]")
        inside = subprocess.run([*wrapper, "/bin/cat", str(root / "repo" / "roster.json")],
                                capture_output=True, text=True)
        check("a read inside the root is denied",
              inside.returncode != 0 and "SECRET-ROSTER" not in inside.stdout, inside.stderr[-120:])
        free = subprocess.run([*wrapper, "/bin/cat", str(outside / "ok.txt")], capture_output=True, text=True)
        check("a read outside the root is allowed", free.returncode == 0 and free.stdout == "fine", free.stderr)
        check("no wrapper at all when no root is given", G.sandbox_wrapper(None) == [])

        print("\n[FABLE]")
        cfg = tmp / "claude-config"
        transcript(cfg, "sid-clean", 0)
        fake = Captured(fable_stdout("sid-clean"))
        text, tel = with_run(fake, lambda: G.call_fable("PROMPT", str(cfg), 30, "claude", str(tmp / "wj"),
                                                        wrapper=wrapper, extra_args=["--tools", ""],
                                                        require_no_tools=True))
        base = G.fable_command("PROMPT", "claude")
        check("a pundits call starts with the sandbox wrapper", fake.argv[:len(wrapper)] == wrapper, str(fake.argv[:3]))
        check("then runs fable_command's argv unchanged", fake.argv[len(wrapper):len(wrapper) + len(base)] == base)
        check('and ends with --tools ""', fake.argv[-2:] == ["--tools", ""], str(fake.argv[-3:]))
        check("zero transcript tool calls pass and are recorded", tel.get("transcript_tool_calls") == 0, str(tel))
        fake = Captured(fable_stdout("sid-clean"))
        with_run(fake, lambda: G.call_fable("PROMPT", str(cfg), 30, "claude", str(tmp / "wj")))
        check("a leaders call builds exactly fable_command's argv", fake.argv == base, str(fake.argv[:4]))
        transcript(cfg, "sid-tools", 1)
        check("a tool call with tools removed fails loudly as a tool attempt",
              with_run(Captured(fable_stdout("sid-tools")),
                       lambda: raises(lambda: G.call_fable("PROMPT", str(cfg), 30, "claude", str(tmp / "wj"),
                                                           wrapper=wrapper, extra_args=["--tools", ""],
                                                           require_no_tools=True), G.E_TOOL_ATTEMPT)))
        check("a missing transcript fails loudly rather than passing",
              with_run(Captured(fable_stdout("sid-nowhere")),
                       lambda: raises(lambda: G.call_fable("PROMPT", str(cfg), 30, "claude", str(tmp / "wj"),
                                                           wrapper=wrapper, extra_args=["--tools", ""],
                                                           require_no_tools=True), G.E_NO_TRANSCRIPT)))

        print("\n[ASTRA/GEMINI]")
        astra_out = "\n".join(json.dumps(e) for e in (
            {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
            {"type": "turn.completed", "usage": {"reasoning_output_tokens": 4, "input_tokens": 1, "output_tokens": 1}}))
        wd = tmp / "astra-wd"
        wd.mkdir()
        fake = Captured(astra_out)
        with_run(fake, lambda: G.call_astra("PROMPT", 30, wd, "gpt-6-astra", wrapper=wrapper))
        check("a pundits Astra call starts with the sandbox wrapper",
              fake.argv[:len(wrapper)] == wrapper and fake.argv[len(wrapper)] == "codex", str(fake.argv[:4]))
        fake = Captured(astra_out)
        with_run(fake, lambda: G.call_astra("PROMPT", 30, wd, "gpt-6-astra"))
        check("a leaders Astra call builds exactly astra_command's argv",
              fake.argv == G.astra_command("PROMPT", "gpt-6-astra", wd / "astra_last_message.txt"), str(fake.argv[:3]))
        gem_out = "\n".join(json.dumps(e) for e in (
            {"event": "init", "init": {"model": G.GEMINI_MODEL}},
            {"event": "result", "result": {"status": "SUCCESS", "response": "{}", "usage": {"thinking_tokens": 2}}}))
        fake = Captured(gem_out)
        with_run(fake, lambda: G.call_gemini("PROMPT", str(tmp / "home"), 120, str(tmp / "gem-wd"), wrapper=wrapper))
        check("a pundits Gemini call starts with the sandbox wrapper", fake.argv[:len(wrapper)] == wrapper,
              str(fake.argv[:3]))
        check("a Gemini user profile is refused under the sandbox",
              raises(lambda: G.call_gemini("PROMPT", "user:someone", 120, str(tmp / "gem-wd2"), wrapper=wrapper),
                     "user profile"))

        print("\n[PROFILE]")
        prof = json.loads((REPO / "profiles" / "pundits.json").read_text())
        h = G.v2_harness(prof, "fable", root)
        check('Fable gets the wrapper, --tools "" and the no-tools audit',
              h["wrapper"] == wrapper and h["extra_args"] == ["--tools", ""] and h["require_no_tools"] is True, str(h))
        h = G.v2_harness(prof, "astra", root)
        check("Astra gets the wrapper, no extra args and no tool audit",
              h["wrapper"] == wrapper and h["extra_args"] == [] and h["require_no_tools"] is False, str(h))
        bad = json.loads(json.dumps(prof))
        bad["judge_requests"]["gemini"]["sandbox"] = "something_else"
        check("an unknown sandbox is refused", raises(lambda: G.v2_harness(bad, "gemini", root), "sandbox"))
        bad = json.loads(json.dumps(prof))
        bad["judge_requests"]["astra"]["extra_args"] = ["--x"]
        check("extra args on a judge other than Fable are refused",
              raises(lambda: G.v2_harness(bad, "astra", root), "extra_args"))

        print("\n[GRADE_ONE]")
        seen = {}

        def stub(prompt, *a, **kw):
            seen.clear()
            seen.update(kw)
            raise RuntimeError(f"{G.E_CLI}: stub stops here")

        G.call_fable = stub
        v2_job = {"rec": {"leader_slug": "p", "source_id": "s", "text": "t"}, "judge": "fable", "mode": "blinded",
                  "run": 0, "force": False, "dest": str(tmp / "g" / "d.json"), "raw_dest": str(tmp / "g" / "r.txt"),
                  "config_dir": "__DEFAULT__", "timeout": 5, "fable_bin": "claude", "workdir": str(tmp / "w"),
                  "contract_version": 2, "harness": G.v2_harness(prof, "fable", root)}
        G._v2_prompt_and_identity = lambda job: ("PROMPT", {})
        G.grade_one(v2_job)
        check("a contract v2 job hands the harness to the judge call",
              seen.get("wrapper") == wrapper and seen.get("extra_args") == ["--tools", ""]
              and seen.get("require_no_tools") is True, str(seen))
        leaders_job = dict(v2_job)
        for k in ("contract_version", "harness"):
            leaders_job.pop(k)
        leaders_job.update(rubric="r", schema="s", dest=str(tmp / "g2" / "d.json"))
        G.grade_one(leaders_job)
        check("a leaders job hands the judge call no harness arguments", seen == {}, str(seen))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
