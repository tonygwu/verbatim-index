#!/usr/bin/env python3
"""PreToolUse hook for the Gemini resolver: web search and public page reads, nothing else.

The Gemini resolver (resolve_predictions.py --resolver gemini) runs `agy -p` in a
jail of its own whose `.agents/hooks.json` names this script. agy runs it before
every tool step, with the tool call as JSON on stdin, and obeys the decision it
prints on stdout. agy runs it as the macOS user the call runs as, from the
`.agents/` folder, under `/usr/bin/python3 -I`, so this file is copied into each
jail and imports nothing outside the standard library of Python 3.9.

WHY A HOOK. agy asks before it reads a URL, and a headless run cannot answer, so
the read is refused and the run ends with an empty answer (docs/agents/JUDGES.md).
The permission rules that would allow it live in agy's global and shared scopes,
which the leaders board's blinded Gemini grader also reads; a page-read grant
there would let the grader open pages that name the speaker. A hook in the
resolver's own jail reaches only sessions that start in that jail.

WHAT IT ALLOWS. `search_web` with a query, unless the query or its `domain`
argument names this project's own domain, and `read_url_content` on an http or
https URL with no credentials, whose host is not this project's own domain and
resolves only to public addresses. An allowed page read also returns
`permissionOverrides: ["read_url(<host>)"]`, a grant for that host and that call:
MEASURED 2026-10-20 in the third live probe, the hook's allow alone did not open a
page, because agy's own permission check still asked and a headless run cannot
answer. `read_file` (agy also calls it `view_file`) is allowed on one kind of
file only: a page this conversation
fetched. MEASURED 2026-10-20 in the seventh and eighth probes, read_url_content
returns no body text; it saves the page to
`<home>/.gemini/antigravity-cli/brain/<conversation>/.system_generated/steps/<n>/content.md`
and tells the model to open it. The path is resolved, symlinks included, and must
land on that file for the conversation the payload names. Everything else is
refused with a reason, including every other file, command and browser tool.

THE STOP HOOK. `--stop` copies this conversation's `transcript_full.jsonl` beside
this script. It is the one record of what the searches returned (the stream
carries only the queries), and it sits in the home of the user the call runs as,
which the repo's user cannot read. The project's sites are public and publish the resolver's
own verdicts, so a page there would hand Gemini Astra's answer. A host that does
not resolve is refused, never let through. Any error answers deny.

Every decision is appended to `gate_log.jsonl` beside this script, so the caller
can record what the judge asked for and what it got.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import sys
from urllib.parse import urlsplit

HOOK_NAME = "verbatim-resolver-gate"
SCRIPT_NAME = "agy_resolver_gate.py"
LOG_NAME = "gate_log.jsonl"
#: The custom agent the resolver runs as (`agy --agent`), kept in the jail's
#: `.agents/agents/`. Its tool list is what agy offers the model.
AGENT_NAME = "verbatim-resolver"

#: The tools the resolver may use. Tool names are agy's step types, lower-cased.
SEARCH_TOOLS = ("search_web",)
URL_TOOLS = ("read_url_content",)
PAGE_TOOLS = ("read_file", "view_file")
#: The argument keys a file tool has been seen to use for its path.
PATH_KEYS = ("AbsolutePath", "Path", "path")
#: A conversation id as agy writes it; anything else names no conversation.
CONVERSATION_ID = re.compile(r"[0-9a-f][0-9a-f-]{7,63}")
#: The argument keys agy has been seen to use for a URL. Others are refused.
URL_KEYS = ("Url", "url", "URL")
#: This project's own domain. Its sites are public and publish resolutions.
OWN_DOMAINS = ("tonygwu.com",)


def hooks_config() -> dict:
    """The `.agents/hooks.json` a resolver jail carries: this script gates every tool,
    and copies the transcript when the run stops."""
    return {HOOK_NAME: {
        "PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": f"/usr/bin/python3 -I ./{SCRIPT_NAME}", "timeout": 20}]}],
        "Stop": [{"type": "command", "command": f"/usr/bin/python3 -I ./{SCRIPT_NAME} --stop", "timeout": 30}]}}


def agent_markdown() -> str:
    """The `.agents/agents/<AGENT_NAME>.md` a resolver jail carries. MEASURED
    2026-10-20 in the second and third probes: agy's default agent did not offer
    read_url_content to the model, and an agent that lists its tools did."""
    return (f"---\nname: {AGENT_NAME}\n"
            f"description: Resolves one dated public prediction from web searches and public web pages only.\n"
            f"tools:\n  - search_web\n  - read_url_content\n  - read_file\n---\n"
            f"# Verbatim resolver\n\nFollow the user's instructions exactly.\n")


def _brain(home: str, conversation: str) -> str:
    return os.path.join(home, ".gemini", "antigravity-cli", "brain", conversation)


def _url_check(url, resolve) -> "tuple[str | None, str | None]":
    """(why this URL may not be read, or None; its host, lower case, no final dot)."""
    if not isinstance(url, str) or not url.strip():
        return "read_url_content needs one URL string", None
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError as exc:
        return f"unreadable URL: {exc}", None
    if parts.scheme.lower() not in ("http", "https"):
        return f"only http and https pages may be read, not {parts.scheme or 'no scheme'!r}", None
    if not host:
        return "the URL names no host", None
    if parts.username is not None or parts.password is not None:
        return "a URL carrying credentials is refused", None
    host = host.lower().rstrip(".")
    return _host_refusal(host, parts, resolve), host


def _host_refusal(host: str, parts, resolve) -> "str | None":
    """Why this host may not be read, or None. Every address it resolves to must be public."""
    for own in OWN_DOMAINS:
        if host == own or host.endswith("." + own):
            return f"{host} is this project's own site, which publishes resolutions; use other sources"
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return f"{host} is a local address"
    try:
        infos = resolve(host, parts.port or (443 if parts.scheme.lower() == "https" else 80))
    except (OSError, UnicodeError, ValueError) as exc:
        return f"{host} does not resolve ({exc}); refused rather than guessed"
    addrs = {info[4][0] for info in infos}
    if not addrs:
        return f"{host} resolved to no address"
    for a in sorted(addrs):
        try:
            ip = ipaddress.ip_address(a.split("%")[0])
        except ValueError:
            return f"{host} resolved to {a!r}, which is not an address"
        if not ip.is_global:
            return f"{host} resolves to {a}, which is not a public address"
    return None


def _search_refusal(args: dict) -> "str | None":
    """Why this search may not run, or None. MEASURED 2026-10-20 in the first live
    probe: asked to read the predictions site, Gemini 4 Argon searched with
    `domain` set to it. The stream carries no search results, so a search aimed at
    the project's own sites is refused here, where it can be seen."""
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return "search_web needs a query string"
    for key in ("query", "domain"):
        value = args.get(key)
        if isinstance(value, str) and any(own in value.lower() for own in OWN_DOMAINS):
            return (f"search_web {key} names this project's own site, which publishes resolutions; "
                    f"search other sources")
    return None


def _page_file_refusal(args: dict, conversation, home: str) -> "str | None":
    """Why view_file may not open this path, or None when it is a page this
    conversation fetched: <brain>/<conversation>/.system_generated/steps/<n>/content.md."""
    if not isinstance(conversation, str) or not CONVERSATION_ID.fullmatch(conversation):
        return "the hook payload names no conversation, so no fetched page can be matched"
    keys = [k for k in PATH_KEYS if k in args]
    if len(keys) != 1 or not isinstance(args[keys[0]], str):
        return f"view_file needs exactly one path in {list(PATH_KEYS)}; got keys {sorted(args)}"
    path = args[keys[0]]
    if not os.path.isabs(path):
        return "view_file needs an absolute path"
    steps = os.path.realpath(os.path.join(_brain(home, conversation), ".system_generated", "steps"))
    real = os.path.realpath(path)
    parts = os.path.relpath(real, steps).split(os.sep)
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] != "content.md" or not os.path.isfile(real):
        return ("this tool may only open a page this conversation fetched with read_url_content "
                "(the content.md file that tool named); no other file is available to the resolver")
    return None


def decide(payload, resolve=socket.getaddrinfo, home: "str | None" = None) -> "tuple[str, str, list[str]]":
    """(decision, reason, permission grants) for one PreToolUse payload. Only "allow"
    lets the step run, and only an allowed page read carries a grant. `home` is the
    home of the user the call runs as, whose agy brain holds the fetched pages."""
    if not isinstance(payload, dict) or not isinstance(payload.get("toolCall"), dict):
        return "deny", "the hook payload carries no tool call", []
    call = payload["toolCall"]
    name = call.get("name")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    if not isinstance(name, str) or not name:
        return "deny", "the tool call names no tool", []
    if name in SEARCH_TOOLS:
        why = _search_refusal(args)
        return ("deny", why, []) if why else ("allow", "web search", [])
    if name in URL_TOOLS:
        keys = [k for k in URL_KEYS if k in args]
        if len(keys) != 1:
            return "deny", f"read_url_content needs exactly one of {list(URL_KEYS)}; got keys {sorted(args)}", []
        why, host = _url_check(args[keys[0]], resolve)
        return ("deny", why, []) if why else ("allow", "public page", [f"read_url({host})"])
    if name in PAGE_TOOLS:
        why = _page_file_refusal(args, payload.get("conversationId"), str(home or os.path.expanduser("~")))
        return ("deny", why, []) if why else ("allow", "a page this conversation fetched", [])
    return "deny", (f"tool {name} is not available to the resolver: it may only search the web and read "
                    f"public web pages, never files or commands"), []


def _summary(payload) -> dict:
    """What the log keeps of a call: the tool and its URL or query, cut to 300 characters."""
    call = payload.get("toolCall") if isinstance(payload, dict) else None
    if not isinstance(call, dict):
        return {"tool": None}
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    return {"tool": call.get("name"), "args": {k: str(v)[:300] for k, v in args.items()},
            "conversation_id": payload.get("conversationId")}


def stop(raw: str, home: "str | None" = None, cwd: "str | None" = None) -> dict:
    """The Stop hook: copy this conversation's full transcript into `cwd`, and let the run stop.
    The source is derived from the conversation id, never taken from the payload's path."""
    home, cwd = str(home or os.path.expanduser("~")), str(cwd or os.getcwd())
    entry = {"event": "Stop"}
    try:
        payload = json.loads(raw)
        conversation = payload.get("conversationId") if isinstance(payload, dict) else None
        entry["conversation_id"] = conversation
        if isinstance(conversation, str) and CONVERSATION_ID.fullmatch(conversation):
            src = os.path.join(_brain(home, conversation), ".system_generated", "logs", "transcript_full.jsonl")
            dest = os.path.join(cwd, f"transcript_full.{conversation}.jsonl")
            shutil.copyfile(src, dest)
            os.chmod(dest, 0o644)
            entry["copied"] = os.path.basename(dest)
        else:
            entry["copied"] = None
    except Exception as exc:  # noqa: BLE001 - a failed copy is logged; the run still stops
        entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        with open(os.path.join(cwd, LOG_NAME), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass
    return {"decision": "stop"}


def main() -> int:
    if sys.argv[1:] == ["--stop"]:
        print(json.dumps(stop(sys.stdin.read())))
        return 0
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        decision, reason, grants = decide(payload)
    except Exception as exc:  # noqa: BLE001 - any error refuses the step
        payload, decision, reason, grants = None, "deny", f"the gate could not read the tool call: {type(exc).__name__}", []
    entry = {**_summary(payload), "decision": decision, "reason": reason, "grants": grants,
             "step_idx": payload.get("stepIdx") if isinstance(payload, dict) else None}
    try:
        with open(LOG_NAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        # The decision still stands; a missing log is reported by the caller,
        # which compares it with the steps the judge ran.
        print(f"gate log not written: {exc}", file=sys.stderr)
    out = {"decision": decision}
    if decision != "allow":
        out["reason"] = reason
    elif grants:
        out["permissionOverrides"] = grants
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
