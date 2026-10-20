#!/usr/bin/env python3
"""The Gemini 4 Argon resolver harness: `agy` in a jail of its own, allowed to search and read public pages.

    resolve_predictions.py --stage resolve --resolver gemini --out data/predictions/_experiments/<new run> ...

An option beside Astra, measured against it (BACKLOG.md VI-47, operator request of
2026-10-20). Astra stays the default and the production resolver, and
resolve_predictions refuses a Gemini run into any run scoring.json names.

WHY IT IS MORE THAN `agy -p`. A resolution must cite pages it opened, and agy asks
before it reads a URL; a headless run cannot answer, so the read is refused and
the run ends with an empty answer (docs/agents/JUDGES.md). The rules that would
allow it live in agy's global and shared permission scopes, which the leaders
board's blinded Gemini grader also reads. Granting page reads there would let the
grader open pages that name the speaker. So nothing here touches a profile's
configuration. Each call gets a jail under RESOLVER_JAIL_ROOT, which no grader
jail sits under, holding three files (`write_jail`):

  .agents/agents/verbatim-resolver.md  a custom agent whose tool list is search_web,
                                       read_url_content and read_file: the only
                                       tools agy offers the model;
  .agents/hooks.json                   a PreToolUse hook on every tool and a Stop hook;
  .agents/agy_resolver_gate.py         the hook: it allows a search, a read of a
                                       public http(s) page that is not this
                                       project's site, and the opening of a page
                                       this conversation fetched, and refuses all else.

agy runs with `--agent verbatim-resolver --dangerously-skip-permissions`. The flag
is what lets the allowed page read through: MEASURED 2026-10-20, a hook's allow,
even with `permissionOverrides: ["read_url(<host>)"]`, did not get past agy's own
ask in a headless run, and `--mode auto` "is not available for this account". The
grader's call never carries it (gemini_command). The flag approves only what the
agent offers and the hook allows; a hook refusal still blocks the step, and the
model sees the reason and goes on (measured in the same probes).

THREE LAYERS keep the judge out of data/, and each is checked:
  1. The OS. Only a profile that runs as ANOTHER macOS user may resolve
     (resolver_profiles). That user cannot enter the operator's home, which is
     mode 700, so no tool could read this repository even if both layers below
     failed. A HOME profile runs as the operator and is refused.
  2. The agent's tool list: file, command and browser tools are never offered.
  3. The hook: it refuses any other tool, path or URL.
And after every call, tool_audit compares the stream with the hook's log: a tool
step that finished without the hook's allow, or a tool outside the set, fails the
call as E_UNGATED. A hook that did not run cannot pass unnoticed.

EVIDENCE. Beside the raw answer (`<id>.txt`, as for Astra) each call keeps the
hook's log, agy's log and the conversation's full transcript, which the Stop hook
copies out of the other user's home. The transcript is the one record of what the
searches returned, so own_site_mentions can count tool output that names this
project's public site, whose pages carry the board's own verdicts. The jail is
then removed.
"""
from __future__ import annotations

import collections
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_resolver_gate as GATE  # noqa: E402
import grade as G  # noqa: E402

#: Where the resolver's jails live. Not under the grader's GEMINI_SHARED_JAIL:
#: agy loads `.agents/` from the working directory upward, so a grader jail must
#: never sit below a folder that holds one.
RESOLVER_JAIL_ROOT = Path("/Users/Shared/verbatim-index-resolver")
DEFAULT_MODEL = "gemini-4-argon-high"
RESOLVER_ARGS = ("--agent", GATE.AGENT_NAME, "--dangerously-skip-permissions")
#: The tools a resolver's stream may show finished. Anything else fails the call.
DONE_TOOLS = frozenset(GATE.SEARCH_TOOLS + GATE.URL_TOOLS + GATE.PAGE_TOOLS)
E_UNGATED = "ungated_tool_use"
ERROR_TYPES = (E_UNGATED,)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jail_files() -> dict[str, bytes]:
    """The three files every resolver jail holds, by path under the jail."""
    return {".agents/hooks.json": (json.dumps(GATE.hooks_config(), indent=1) + "\n").encode(),
            f".agents/{GATE.SCRIPT_NAME}": Path(GATE.__file__).read_bytes(),
            f".agents/agents/{GATE.AGENT_NAME}.md": GATE.agent_markdown().encode()}


def jail_hashes() -> dict[str, str]:
    return {name: _sha(data) for name, data in jail_files().items()}


def write_jail(jail: Path) -> dict[str, str]:
    """Write the jail's three files and return their hashes. A jail that already
    holds `.agents` is refused: a jail is made for one call and removed after it."""
    jail = Path(jail)
    if (jail / ".agents").exists():
        raise RuntimeError(f"{G.E_CLI}: resolver jail {jail} already holds .agents; a jail is never reused")
    for name, data in jail_files().items():
        dest = jail / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.chmod(0o644)
    for d in (jail / ".agents", jail / ".agents" / "agents"):
        # The hook and the Stop copy write here as the call's macOS user.
        G._share_with_group(d)
    return jail_hashes()


def resolver_profiles(rotation: "G.GeminiRotation", select: "str | None") -> list[str]:
    """The profiles the resolver may run on: the rotation's other-user profiles that are not benched.

    `select` (the --gemini-profiles value) has already narrowed `rotation`; a HOME
    profile in it is refused rather than dropped, since asking for one is asking
    for a judge that runs as the operator and could read this repository."""
    home = [p for p in rotation.profiles if not G.is_user_profile(p)]
    if select and home:
        raise SystemExit(f"--gemini-profiles names {[rotation.accounts.get(p, p) for p in home]}, which run as this "
                         f"macOS user: a resolver there could read this repository, including data/. The Gemini "
                         f"resolver runs only as another macOS user (a router account with macos_user).")
    users = [p for p in rotation.profiles if G.is_user_profile(p) and p not in rotation.benched]
    if not users:
        raise SystemExit("no Gemini profile that runs as another macOS user is available "
                         f"(rotation {rotation.profiles}, benched {rotation.benched}); the resolver never runs as "
                         f"this macOS user")
    return users


def tool_audit(events: list[dict], gate_entries: list[dict]) -> list[str]:
    """Problems with the tools this call ran, or [] when every one was the gate's to allow and was allowed.

    The conversation is the init event's; gate entries for other conversations
    (an earlier attempt of the same call) vouch for nothing here."""
    conv = next((e.get("conversation_id") for e in events if e.get("event") == "init"), None)
    if not conv:
        return ["the stream names no conversation, so its tool steps cannot be matched to the gate's log"]
    allowed = {(g.get("step_idx"), g.get("tool")) for g in gate_entries
               if g.get("conversation_id") == conv and g.get("decision") == "allow"}
    problems, seen = [], set()
    for e in events:
        su = e.get("step_update") if e.get("event") == "step_update" else None
        if not isinstance(su, dict) or su.get("step_type") != "tool" or su.get("state") != "DONE":
            continue
        idx, tool = su.get("step_index"), su.get("tool_name")
        if (idx, tool) in seen:
            continue
        seen.add((idx, tool))
        if tool not in DONE_TOOLS:
            problems.append(f"step {idx} ran {tool}, which the resolver may never run")
        elif (idx, tool) not in allowed:
            problems.append(f"step {idx} ran {tool} with no allow from the gate in its log")
    return problems


def own_site_mentions(transcript: list[dict]) -> int:
    """Tool outputs (finished GENERIC steps) that name this project's own domain.
    A refusal message and the model's own words are not counted."""
    return sum(1 for row in transcript if row.get("type") == "GENERIC" and row.get("status") == "DONE"
               and any(d in str(row.get("content") or "").lower() for d in GATE.OWN_DOMAINS))


def collect(jail: Path, raw_dir: Path, stem: str) -> dict:
    """Move the call's evidence from the jail into the run's raw folder, then remove the jail."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    out: dict = {"files": {}}
    sources = [(jail / "agy-cli.log", "agy-cli.log"), (jail / ".agents" / GATE.LOG_NAME, "gate_log.jsonl")]
    sources += [(t, t.name) for t in sorted((jail / ".agents").glob("transcript_full.*.jsonl"))]
    for src, name in sources:
        if src.is_file():
            dest = raw_dir / f"{stem}.{name}"
            shutil.copyfile(src, dest)
            out["files"][dest.name] = _sha(dest.read_bytes())
    try:
        shutil.rmtree(jail)
        out["jail_removed"] = True
    except OSError as exc:
        out["jail_removed"] = False
        out["jail_remove_error"] = f"{type(exc).__name__}: {exc}"[:300]
        G.log(f"    WARNING: resolver jail {jail} not removed: {exc}")
    return out


def call(prompt: str, profile: str, timeout: int, *, jail_name: str, model: str, expected_identity: str,
         raw_dir: Path, stem: str) -> tuple[str, dict]:
    """One resolution on Gemini. Returns (text, telemetry) like call_astra, or raises with a taxonomy label."""
    if not G.is_user_profile(profile):
        raise SystemExit(f"the Gemini resolver runs only as another macOS user, not on {profile!r}")
    jail = G.gemini_jail(profile, jail_name, shared_root=RESOLVER_JAIL_ROOT)
    hashes: dict = {}
    raw_path = raw_dir / f"{stem}.txt"
    try:
        text, tel = G.call_gemini(prompt, profile, timeout, workdir=jail_name, model=model, binary=G.AGY_JUDGE_BIN,
                                  expected_identity=expected_identity, shared_root=RESOLVER_JAIL_ROOT,
                                  extra_args=list(RESOLVER_ARGS), prepare_jail=lambda j: hashes.update(write_jail(j)),
                                  raw_response_path=raw_path)
    finally:
        evidence = collect(jail, raw_dir, stem)
    events, _ = G.parse_jsonl_events(json.loads(raw_path.read_text())["stdout"])
    gate_file = raw_dir / f"{stem}.gate_log.jsonl"
    gate = [json.loads(x) for x in gate_file.read_text().splitlines() if x.strip()] if gate_file.exists() else []
    problems = tool_audit(events, gate)
    if problems:
        raise RuntimeError(f"{E_UNGATED}: {'; '.join(problems[:4])}")
    conv = next((e.get("conversation_id") for e in events if e.get("event") == "init"), None)
    transcript_file = raw_dir / f"{stem}.transcript_full.{conv}.jsonl"
    if not transcript_file.exists():
        # The Stop hook's copy is the one record of what the searches returned;
        # without it the own-site screen cannot run, so the answer is refused.
        raise RuntimeError(f"{G.E_CLI}: no transcript was copied for conversation {conv}; the Stop hook did not run")
    transcript = [json.loads(x) for x in transcript_file.read_text().splitlines() if x.strip()]
    mine = [g for g in gate if g.get("conversation_id") == conv and "decision" in g]
    tel["resolver_jail"] = {"root": str(RESOLVER_JAIL_ROOT), "args": list(RESOLVER_ARGS), "files_sha256": hashes}
    tel["gate"] = {"allowed": sum(g["decision"] == "allow" for g in mine),
                   "refused": dict(collections.Counter(g.get("tool") for g in mine if g["decision"] != "allow"))}
    tel["own_site_mentions"] = own_site_mentions(transcript)
    tel["evidence"] = evidence
    return text, tel
