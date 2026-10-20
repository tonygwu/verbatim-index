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
probs = GR.tool_audit(events, entries[:3])
check("a tool step that ended in an error with no gate entry at all is refused (the hook did not run)",
      any("step 8" in p for p in probs), str(probs))
ev2, _ = G.parse_jsonl_events(stream((2, "run_command", "DONE")))
probs = GR.tool_audit(ev2, [gate(2, "run_command")])
check("a finished tool outside the resolver's set is refused even if logged as allowed",
      any("run_command" in p for p in probs), str(probs))
probs = GR.tool_audit(events, [dict(e, conversation_id="other") for e in entries])
check("gate entries from another conversation do not vouch for this one (all four steps)", len(probs) == 4,
      str(probs))
check("a stream with no init conversation id cannot be audited",
      GR.tool_audit([e for e in events if e.get("event") != "init"], entries) != [], "")

transcript = [{"type": "GENERIC", "status": "DONE", "content": "results ... https://verbatim-predictions.tonygwu.com/x"},
              {"type": "GENERIC", "status": "ERROR", "content": "denied: verbatim-predictions.tonygwu.com is ..."},
              {"type": "PLANNER_RESPONSE", "status": "DONE", "content": "the tonygwu.com page was refused"},
              {"type": "GENERIC", "status": "DONE", "content": "nothing here"}]
check("a tool output naming the project's site is counted; refusals and the model's own words are not",
      GR.own_site_mentions(transcript) == 1, str(GR.own_site_mentions(transcript)))
proxied = [{"type": "GENERIC", "status": "DONE", "content": "https://verbatim--predictions-tonygwu-com.translate.goog/"}]
check("the dashed proxy form of the domain is counted too, as the gate matches it",
      GR.own_site_mentions(proxied) == 1, str(GR.own_site_mentions(proxied)))

# ---- 3b. GR.call: its refusals, and evidence kept either way ---------------
print("3b. gemini_resolver.call")


def fake_call_gemini(stdout: str, gate_entries: list, transcript: "list | None", raise_with: "str | None" = None):
    def run(prompt, profile, timeout, *, workdir, shared_root, prepare_jail, raw_response_path, **kw):
        jail = G.gemini_jail(profile, workdir, shared_root=shared_root)
        prepare_jail(jail)
        (jail / "agy-cli.log").write_text("log")
        (jail / ".agents" / GATE.LOG_NAME).write_text("".join(json.dumps(e) + "\n" for e in gate_entries))
        if transcript is not None:
            (jail / ".agents" / f"transcript_full.{CONV}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in transcript))
        raw_response_path.parent.mkdir(parents=True, exist_ok=True)
        raw_response_path.write_text(json.dumps({"returncode": 0, "stdout": stdout, "stderr": ""}))
        if raise_with:
            raise RuntimeError(raise_with)
        return '{"ok": 1}', {"served_model": "gemini-4-argon-high", "web_search": {"queries": ["q2"]}}
    return run


good_stream = stream((2, "search_web", "DONE"), (4, "read_url_content", "DONE"))
good_gate = [gate(2, "search_web"), gate(4, "read_url_content"), {"event": "Stop", "conversation_id": CONV}]
own = [{"type": "GENERIC", "status": "DONE", "content": "[1] [verbatim-predictions.tonygwu.com](https://x)"}]
real_cg, real_root = G.call_gemini, GR.RESOLVER_JAIL_ROOT
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    GR.RESOLVER_JAIL_ROOT = td / "jails"
    try:
        def go(stem, **kw):
            G.call_gemini = fake_call_gemini(**kw)
            return lambda: GR.call("P", "user:someone", 60, jail_name=f"run-{stem}", model="gemini-4-argon-high",
                                   expected_identity="b@x", raw_dir=td / "raw", stem=stem)
        text, tel = go("ok", stdout=good_stream, gate_entries=good_gate, transcript=own)()
        check("a gated call returns its text and the gate's count", text == '{"ok": 1}'
              and tel["gate"] == {"allowed": 2, "refused": {}}, str(tel.get("gate")))
        check("tool output naming the project's site is counted on the telemetry", tel["own_site_mentions"] == 1,
              str(tel.get("own_site_mentions")))
        check("the jail's file hashes are recorded", tel["resolver_jail"]["files_sha256"] == GR.jail_hashes(), "")
        check("the evidence is kept beside the raw answer", sorted(tel["evidence"]["files"]) == sorted(
              ["ok.agy-cli.log", "ok.gate_log.jsonl", f"ok.transcript_full.{CONV}.jsonl"]), str(tel["evidence"]))
        check("and the jail is removed", tel["evidence"]["jail_removed"] and not (td / "jails" / "run-ok").exists(), "")
        msg = raises(go("ungated", stdout=good_stream, gate_entries=good_gate[:1], transcript=own))
        check("a finished step the gate did not allow fails the call as ungated_tool_use",
              msg is not None and msg.startswith(GR.E_UNGATED), str(msg))
        check("and its evidence is still kept", (td / "raw" / "ungated.gate_log.jsonl").exists()
              and not (td / "jails" / "run-ungated").exists(), "")
        msg = raises(go("nott", stdout=good_stream, gate_entries=good_gate, transcript=None))
        check("a call with no copied transcript fails, labelled so", msg is not None
              and msg.startswith(G.E_NO_TRANSCRIPT) and G.E_NO_TRANSCRIPT in GR.ERROR_TYPES, str(msg))
        msg = raises(go("empty", stdout=good_stream, gate_entries=good_gate, transcript=own,
                        raise_with=f"{G.E_EMPTY}: no answer"))
        check("a failed agy call still leaves its evidence and removes its jail", msg is not None
              and msg.startswith(G.E_EMPTY) and (td / "raw" / "empty.agy-cli.log").exists()
              and not (td / "jails" / "run-empty").exists(), str(msg))
    finally:
        G.call_gemini, GR.RESOLVER_JAIL_ROOT = real_cg, real_root

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

# ---- 6. the gemini branch of run_one, through main --------------------------
print("6. resolve_predictions main with --resolver gemini (GR.call stubbed)")
import contextlib  # noqa: E402
import io  # noqa: E402
from unittest.mock import patch  # noqa: E402

import resolution_lib as R  # noqa: E402

THREE = ["engine ship date", "Analytical engine release", "Analytical annual report"]
REC = {"accepted": True, "leader_slug": "ada", "prediction_id": "g1", "transcript_id": "ada/t1",
       "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical"},
       "prediction": {"target_date": "2021-12-31", "target_date_text": "by 2021-12-31", "horizon_years_inferred": None,
                      "specificity": "high", "subject_control": "external", "category": "technology_product",
                      "prediction_type": "milestone", "horizon": "explicit", "normalized_claim": "claim g1",
                      "resolution_criteria": "By 2021-12-31, g1 will have happened."},
       "source": {"statement_date": "2020-01-01", "statement_date_basis": "stated_in_page", "quote": "quote g1",
                  "venue": "", "title": "t", "context_before": "", "context_after": ""},
       "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None}}
ANSWER = {"prediction_id": "g1", "outcome": "occurred", "confidence": "high", "unresolvable_reason": None,
          "sources": [{"what_it_shows": "shipped", "where": "https://x.example.com/", "date": "2021-03-01"}],
          "searched": THREE, "already_public": None, "reasoning": "It shipped in March 2021."}
ROT = G.GeminiRotation(profiles=["user:agents"], identities={"user:agents": "b@x"}, benched=[], versions={},
                       accounts={"user:agents": "antigravity_gemini_b"})


def run_main(tel, raise_with=None, extra=()):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        corpus = td / "predictions"
        (corpus / "ada").mkdir(parents=True)
        (corpus / "ada" / "t1.jsonl").write_text(json.dumps(REC) + "\n")
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        out, errs = corpus / "_experiments" / "g", td / "errors.jsonl"
        seen = []

        def fake_call(prompt, profile, timeout, **kw):
            seen.append((profile, kw))
            if raise_with:
                raise RuntimeError(raise_with)
            return json.dumps(ANSWER), tel
        with patch.object(GR, "call", fake_call), patch.object(G, "gemini_rotation_preflight", lambda *a, **k: ROT), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = RP.main(["--stage", "resolve", "--resolver", "gemini", "--predictions", str(corpus), "--out", str(out),
                          "--as-of", "2026-09-28", "--errors", str(errs), "--workers", "1", *extra])
        side = R.sidecar_path(out, "resolve", "ada", "g1")
        obj = json.loads(side.read_text()) if side.exists() else None
        summary = json.loads(next((out / "_runs").glob("*.json")).read_text())
        lines = [json.loads(x) for x in errs.read_text().splitlines()] if errs.exists() else []
        return rc, obj, summary, lines, seen


rc, obj, summary, lines, seen = run_main({"served_model": "gemini-4-argon-high", "web_search": {"queries": THREE}})
check("a Gemini resolution that meets every rule is written", rc == 0 and obj is not None, f"{rc} {lines}")
check("its sidecar names the harness and the router account", obj and (obj["harness"], obj["account"])
      == ("gemini", "antigravity_gemini_b"), str(obj and (obj["harness"], obj["account"])))
check("the call ran on the other user's profile with its expected identity and a per-run jail",
      seen and seen[0][0] == "user:agents" and seen[0][1]["expected_identity"] == "b@x"
      and seen[0][1]["jail_name"].endswith("-g1") and seen[0][1]["model"] == "gemini-4-argon-high", str(seen))
check("the run summary names the resolver", summary.get("resolver") == {"harness": "gemini", "model":
      "gemini-4-argon-high", "accounts": ["antigravity_gemini_b"]}, str(summary.get("resolver")))
rc, obj, summary, lines, _ = run_main({"served_model": "gemini-4-argon-high", "web_search": {"queries": THREE[:2]}})
check("a Gemini answer whose own stream shows two searches is refused by the effort floor",
      rc == 1 and obj is None and summary["error_taxonomy"] == {RP.E_RULES: 1}, f"{summary} {lines}")
rc, obj, summary, lines, _ = run_main({}, raise_with=f"{GR.E_UNGATED}: step 6 ran read_file with no allow")
check("an ungated call is filed as ungated_tool_use and writes nothing",
      rc == 1 and obj is None and summary["error_taxonomy"] == {GR.E_UNGATED: 1}, f"{summary} {lines}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
