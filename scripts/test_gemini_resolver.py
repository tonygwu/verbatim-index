#!/usr/bin/env python3
"""The Gemini 4 Argon resolver harness: its jail, its tool audit, and the guards around it.

`gemini_resolver.py` runs the resolver prompt through `agy` in a jail of its own
(`/Users/Shared/verbatim-index-resolver/<run>-<id>`) that carries a custom agent
(search, page reads, and the reading of a fetched page's file) and a PreToolUse
hook (agy_resolver_gate.py) that refuses everything else. The live probes of
2026-10-20 measured each piece; these cases pin them without a model call:

1. call_gemini's new options change nothing when unused, and do what they say when used.
2. The jail holds exactly the three files, and a stale jail is refused.
3. The tool audit refuses an answer whose stream shows a tool step the gate did
   not allow, or a tool outside the resolver's set.
4. Only a profile that runs as another macOS user may resolve: that user cannot
   read this repository, which is what keeps the judge out of data/.
5. resolve_predictions refuses --resolver gemini outside a new experiment run.

No subprocess reaches agy; no network.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_resolver_gate as GATE  # noqa: E402
import gemini_resolver as GR  # noqa: E402
import grade as G  # noqa: E402
import resolve_predictions as RP  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def raises(fn) -> "str | None":
    try:
        fn()
    except (RuntimeError, SystemExit, ValueError) as exc:
        return str(exc)
    return None


CONV = "3496d0e8-7966-4aff-82a9-421b61cc1782"


def stream(*steps, model="gemini-4-argon-high", response='{"ok": 1}') -> str:
    ev = [{"event": "init", "conversation_id": CONV, "init": {"model": model}}]
    for idx, tool, state in steps:
        for st in ("ACTIVE", state):
            ev.append({"event": "step_update", "step_update": {
                "conversation_id": CONV, "step_index": idx, "state": st, "step_type": "tool", "tool_name": tool,
                "tool_info": {"name": tool, "parameters": {"query": f"q{idx}"} if tool == "search_web" else {}}}})
    ev.append({"event": "result", "result": {"status": "SUCCESS", "response": response,
                                             "usage": {"thinking_tokens": 7}}})
    return "\n".join(json.dumps(e) for e in ev) + "\n"


def fake_agy(stdout: str, seen: dict, email="gptwufamily@gmail.com"):
    """subprocess.run stand-in: records the argv and what the jail held, writes the --log-file, answers."""
    def run(argv, **kw):
        log_path = Path(argv[argv.index("--log-file") + 1])
        seen["argv"], seen["cwd"] = list(argv), kw.get("cwd")
        seen["jail_files"] = sorted(str(p.relative_to(log_path.parent)) for p in log_path.parent.rglob("*") if p.is_file())
        log_path.write_text("server.go:1663] Language server version: 1.3.5\n"
                            f"ChainedAuth: authenticated via keyring\nuser {email}\n")
        return NS(returncode=0, stdout=stdout, stderr="")
    return run


# ---- 1. call_gemini's options ---------------------------------------------
print("1. call_gemini: new options are inert by default")
real_run = G.subprocess.run
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    try:
        seen: dict = {}
        G.subprocess.run = fake_agy(stream(model="gemini-3.8-flash-high"), seen, email="a@gmail.com")
        G.call_gemini("PROMPT", str(td / "home"), 120, workdir=str(td / "w1"), model="gemini-3.8-flash-high",
                      binary="/usr/local/bin/agy", expected_identity="a@gmail.com")
        jail = td / "w1"
        want, _ = G.gemini_launch(str(td / "home"), G.gemini_command("PROMPT", "gemini-3.8-flash-high",
                                  "/usr/local/bin/agy", 60, jail / "agy-cli.log"), {})
        check("with no new option the argv is exactly gemini_command's, as before", seen["argv"] == want,
              f"{seen['argv']} != {want}")
        check("and no --dangerously-skip-permissions reaches the grader's call",
              "--dangerously-skip-permissions" not in seen["argv"], str(seen["argv"]))

        print("   the resolver's options")
        seen = {}
        G.subprocess.run = fake_agy(stream((2, "search_web", "DONE")), seen)
        calls: list = []
        raw = td / "raw" / "p.txt"
        text, tel = G.call_gemini("PROMPT", "user:someone", 120, workdir="run-p", model="gemini-4-argon-high",
                                  binary="/usr/local/bin/agy", expected_identity="gptwufamily@gmail.com",
                                  shared_root=td / "resolver-root", extra_args=["--agent", "x", "--flag"],
                                  prepare_jail=lambda j: (calls.append(j), (j / "marker").write_text("m")),
                                  raw_response_path=raw)
        check("extra_args go at the end of agy's argv", seen["argv"][-3:] == ["--agent", "x", "--flag"],
              str(seen["argv"][-6:]))
        check("a user profile still runs through the wrapper", seen["argv"][:4] == ["sudo", "-n",
              G.GEMINI_USER_WRAPPER, "someone"], str(seen["argv"][:4]))
        check("shared_root moves a user profile's jail", seen["cwd"] == str(td / "resolver-root" / "run-p"),
              str(seen["cwd"]))
        check("prepare_jail runs once, on the jail, before agy starts",
              calls == [td / "resolver-root" / "run-p"] and "marker" in seen["jail_files"], f"{calls} {seen}")
        saved = json.loads(raw.read_text()) if raw.exists() else {}
        check("raw_response_path keeps agy's whole answer", saved.get("stdout") == stream((2, "search_web", "DONE"))
              and saved.get("returncode") == 0, str(saved)[:200])
        check("the telemetry carries the search the stream shows", tel["web_search"]["queries"] == ["q2"],
              str(tel.get("web_search")))
    finally:
        G.subprocess.run = real_run

# ---- 2. the jail ------------------------------------------------------------
print("2. the jail")
with tempfile.TemporaryDirectory() as td:
    jail = Path(td) / "j"
    jail.mkdir()
    hashes = GR.write_jail(jail)
    agents = jail / ".agents"
    check("hooks.json is the gate's config", json.loads((agents / "hooks.json").read_text()) == GATE.hooks_config(), "")
    check("the gate script is the repo's, byte for byte",
          (agents / GATE.SCRIPT_NAME).read_bytes() == Path(GATE.__file__).read_bytes(), "")
    check("the agent is the gate's agent", (agents / "agents" / f"{GATE.AGENT_NAME}.md").read_text()
          == GATE.agent_markdown(), "")
    check("the jail's hashes are recorded", hashes == GR.jail_hashes() and len(hashes) == 3, str(hashes))
    check("nothing else is written", sorted(str(p.relative_to(jail)) for p in jail.rglob("*") if p.is_file())
          == sorted([".agents/hooks.json", f".agents/{GATE.SCRIPT_NAME}", f".agents/agents/{GATE.AGENT_NAME}.md"]),
          str(list(jail.rglob("*"))))
    msg = raises(lambda: GR.write_jail(jail))
    check("a jail that already holds .agents is refused, never reused", msg is not None and "already" in msg, str(msg))
check("the resolver runs agy as the jail's agent, with tools gated by the hook",
      list(GR.RESOLVER_ARGS) == ["--agent", GATE.AGENT_NAME, "--dangerously-skip-permissions"], str(GR.RESOLVER_ARGS))
check("the resolver's jail root is not the grader's", GR.RESOLVER_JAIL_ROOT != G.GEMINI_SHARED_JAIL
      and G.GEMINI_SHARED_JAIL not in GR.RESOLVER_JAIL_ROOT.parents, str(GR.RESOLVER_JAIL_ROOT))

# ---- 3. the tool audit ------------------------------------------------------
print("3. the tool audit")


def gate(idx, tool, decision="allow", conv=CONV):
    return {"conversation_id": conv, "step_idx": idx, "tool": tool, "decision": decision}


events, _ = G.parse_jsonl_events(stream((2, "search_web", "DONE"), (4, "read_url_content", "DONE"),
                                        (6, "read_file", "DONE"), (8, "read_url_content", "ERROR")))
entries = [gate(2, "search_web"), gate(4, "read_url_content"), gate(6, "read_file"),
           gate(8, "read_url_content", "deny")]
check("a stream whose every finished tool step the gate allowed passes", GR.tool_audit(events, entries) == [],
      str(GR.tool_audit(events, entries)))
probs = GR.tool_audit(events, entries[:2] + entries[3:])
check("a finished tool step with no allow in the gate log is refused (the hook did not run)",
      any("step 6" in p for p in probs), str(probs))
probs = GR.tool_audit(events, [gate(2, "search_web"), gate(4, "read_url_content"), gate(6, "read_file", "deny"),
                               gate(8, "read_url_content", "deny")])
check("a step the gate refused but the stream shows finished is refused", any("step 6" in p for p in probs), str(probs))
ev2, _ = G.parse_jsonl_events(stream((2, "run_command", "DONE")))
probs = GR.tool_audit(ev2, [gate(2, "run_command")])
check("a finished tool outside the resolver's set is refused even if logged as allowed",
      any("run_command" in p for p in probs), str(probs))
probs = GR.tool_audit(events, [dict(e, conversation_id="other") for e in entries])
check("gate entries from another conversation do not vouch for this one", len(probs) == 3, str(probs))
check("a stream with no init conversation id cannot be audited",
      GR.tool_audit([e for e in events if e.get("event") != "init"], entries) != [], "")

transcript = [{"type": "GENERIC", "status": "DONE", "content": "results ... https://verbatim-predictions.tonygwu.com/x"},
              {"type": "GENERIC", "status": "ERROR", "content": "denied: verbatim-predictions.tonygwu.com is ..."},
              {"type": "PLANNER_RESPONSE", "status": "DONE", "content": "the tonygwu.com page was refused"},
              {"type": "GENERIC", "status": "DONE", "content": "nothing here"}]
check("a tool output naming the project's site is counted; refusals and the model's own words are not",
      GR.own_site_mentions(transcript) == 1, str(GR.own_site_mentions(transcript)))

# ---- 4. profiles -----------------------------------------------------------
print("4. only another macOS user may resolve")
rot = G.GeminiRotation(profiles=["/Users/me", "user:agents"], identities={"/Users/me": "a@x", "user:agents": "b@x"},
                       benched=[], versions={}, accounts={"/Users/me": "antigravity_gemini",
                                                          "user:agents": "antigravity_gemini_b"})
check("the default HOME profile is left out of the resolver's rotation", GR.resolver_profiles(rot, None)
      == ["user:agents"], str(GR.resolver_profiles(rot, None)))
msg = raises(lambda: GR.resolver_profiles(rot, "antigravity_gemini"))
check("naming a HOME profile is refused, with the reason", msg is not None and "macOS user" in msg, str(msg))
only_home = rot._replace(profiles=["/Users/me"])
msg = raises(lambda: GR.resolver_profiles(only_home, None))
check("a rotation with no other-user profile is refused, never run on the operator's user",
      msg is not None, str(msg))
benched = rot._replace(benched=["user:agents"])
msg = raises(lambda: GR.resolver_profiles(benched, None))
check("a rotation whose only other-user profile is benched is refused", msg is not None, str(msg))

# ---- 5. resolve_predictions -------------------------------------------------
print("5. resolve_predictions --resolver gemini")
ap = RP.build_parser()
a = ap.parse_args(["--stage", "resolve", "--out", "x", "--as-of", "2026-10-20"])
check("Astra stays the default resolver", a.resolver == "astra", a.resolver)
check("the default Gemini model is Gemini 4 Argon at high effort", a.gemini_model == "gemini-4-argon-high",
      a.gemini_model)
exp = Path("/d/predictions/_experiments")
ok = ap.parse_args(["--stage", "resolve", "--resolver", "gemini", "--out", str(exp / "new"), "--as-of", "2026-10-20"])
check("a new experiment run is accepted", RP.gemini_resolver_refusal(ok, exp / "new", [exp / "scored"]) is None,
      str(RP.gemini_resolver_refusal(ok, exp / "new", [exp / "scored"])))
for argv, out, label in [
    (["--stage", "prior", "--resolver", "gemini"], exp / "new", "a stage other than resolve"),
    (["--stage", "resolve", "--resolver", "gemini"], exp / "scored", "a run scoring.json names"),
    (["--stage", "resolve", "--resolver", "gemini"], Path("/d/predictions/new"), "a run outside _experiments"),
    (["--stage", "resolve", "--resolver", "gemini", "--codex-homes", "/x"], exp / "new", "Codex homes"),
    (["--stage", "resolve", "--resolver", "gemini", "--fable-pool", "p"], exp / "new", "a credit pool"),
]:
    args = ap.parse_args([*argv, "--out", str(out), "--as-of", "2026-10-20"])
    why = RP.gemini_resolver_refusal(args, out, [exp / "scored"])
    check(f"--resolver gemini is refused for {label}", why is not None, str(why))
astra = ap.parse_args(["--stage", "resolve", "--out", str(exp / "scored"), "--as-of", "2026-10-20"])
check("an Astra run is never refused by the Gemini guard", RP.gemini_resolver_refusal(astra, exp / "scored",
      [exp / "scored"]) is None, "")
ap2 = ap.parse_args(["--stage", "resolve", "--gemini-profiles", "x", "--out", "x", "--as-of", "2026-10-20"])
check("Gemini options without --resolver gemini are refused, not ignored",
      RP.gemini_resolver_refusal(ap2, Path("x"), []) is not None, "")
for label in (G.E_EMPTY, G.E_TRANSIENT, GR.E_UNGATED):
    check(f"a Gemini failure labelled {label} is filed under its own label", RP.classify(f"{label}: x auth") == label,
          RP.classify(f"{label}: x auth"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
