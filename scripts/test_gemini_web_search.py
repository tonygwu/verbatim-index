#!/usr/bin/env python3
"""The Gemini harness records every search it ran, in order, uncapped, for the resolver's effort floor.

`resolution_lib.validate_effort` refuses a resolution unless the harness's own
event log shows at least MIN_SEARCHES distinct queries, and unless every query
the judge lists in `searched` is one the harness ran. It reads
`telemetry["web_search"]["queries"]`. Astra fills that from codex events
(grade.web_search_actions); `grade.gemini_web_search_actions` fills it from agy's
stream-json events, and these cases pin how.

The event shapes are the ones the live probes of 2026-10-20 recorded (agy 1.3.5,
gemini-4-argon-high): each tool step emits an ACTIVE update and then a DONE or
ERROR update with the same step_index, the query sits in
tool_info.parameters.query, and a step the gate refused ends in ERROR. Built in
memory; no subprocess, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade as G  # noqa: E402
import resolution_lib as R  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def step(idx: int, state: str, tool: str, **params) -> dict:
    su = {"conversation_id": "c", "step_index": idx, "state": state, "step_type": "tool", "tool_name": tool,
          "tool_info": {"name": tool, "parameters": params}}
    if state == "ERROR":
        su["tool_info"]["error"] = {"type": "TOOL_ERROR", "message": "tool call denied by pre-tool hook: ..."}
    return {"event": "step_update", "step_update": su}


def search(idx: int, query: str, state: str = "DONE") -> list[dict]:
    return [step(idx, "ACTIVE", "search_web", query=query), step(idx, state, "search_web", query=query)]


events = [{"event": "init", "init": {"model": "gemini-4-argon-high"}},
          {"event": "step_update", "step_update": {"step_index": 0, "state": "DONE", "step_type": "user_input"}}]
events += search(2, "Acme Q3 2025 revenue")
events += [step(4, "ACTIVE", "read_url_content", Url="https://example.com/"),
           step(4, "DONE", "read_url_content", Url="https://example.com/")]
events += [step(6, "ACTIVE", "read_file", Path="/x/steps/4/content.md"),
           step(6, "DONE", "read_file", Path="/x/steps/4/content.md")]
events += search(8, "acme quarterly report 10-Q")
events += search(10, "site:tonygwu.com acme", state="ERROR")          # refused by the gate
events += search(12, "Acme Q3 2025 revenue")                           # a repeat is kept
events += [step(14, "DONE", "search_web", query="acme guidance 2025"),
           step(14, "DONE", "search_web", query="acme guidance 2025")]  # one step, reported twice
events += [step(16, "DONE", "search_web")]                             # a search with no query
events += [{"event": "step_update", "step_update": {"step_index": 17, "state": "DONE", "step_type": "agent_response"}},
           {"event": "result", "result": {"status": "SUCCESS", "response": "{}"}}]

ws = G.gemini_web_search_actions(events)
check("every finished search query is kept, in order, repeats included",
      ws["queries"] == ["Acme Q3 2025 revenue", "acme quarterly report 10-Q", "Acme Q3 2025 revenue",
                        "acme guidance 2025"], str(ws["queries"]))
check("a step reported DONE twice is one search", ws["search_actions"] == 5, str(ws))
check("a search the gate refused (ERROR) is not a search the judge ran",
      "site:tonygwu.com acme" not in ws["queries"] and ws["refused_actions"] == 1, str(ws))
check("a page read is counted apart, never as a search", ws["other_actions"] == 1, str(ws))
check("a page file opened after a read is counted apart too", ws["page_file_reads"] == 1, str(ws))
check("a finished search with no query is counted, never guessed at",
      ws["search_actions_without_queries"] == 1, str(ws))
check("the block has the keys the codex block has, so one validator reads both",
      set(G.web_search_actions([])) <= set(ws), f"{sorted(G.web_search_actions([]))} vs {sorted(ws)}")

many = [e for i in range(15) for e in search(100 + 2 * i, f"query {i}")]
check("the record is uncapped (the older web_search_queries keeps 10)",
      G.gemini_web_search_actions(many)["queries"] == [f"query {i}" for i in range(15)],
      str(G.gemini_web_search_actions(many)["queries"]))
check("an event stream with no tool steps records no search", G.gemini_web_search_actions([])["queries"] == [], "")

# ---- it feeds resolution_lib.validate_effort unchanged ---------------------
tel = {"web_search": ws}
ok = {"searched": ["Acme Q3 2025 revenue", "acme quarterly report 10-Q", "acme guidance 2025"]}
check("three distinct queries the harness ran pass the effort floor", R.validate_effort(ok, tel) == [],
      str(R.validate_effort(ok, tel)))
claims_refused = {"searched": ["Acme Q3 2025 revenue", "site:tonygwu.com acme", "acme guidance 2025"]}
errs = R.validate_effort(claims_refused, tel)
check("listing a search the gate refused is refused as never run",
      any("never ran" in e and "site:tonygwu.com acme" in e for e in errs), str(errs))
two = {"web_search": G.gemini_web_search_actions(search(2, "a") + search(4, "b") + search(6, "A"))}
errs = R.validate_effort({"searched": ["a", "b"]}, two)
check("two distinct queries (a repeat in other case does not count) fail the floor",
      any(f"needs at least {R.MIN_SEARCHES}" in e for e in errs), str(errs))
errs = R.validate_effort({"searched": ["a", "b", "c"]}, {"web_search_queries": ["a", "b", "c"]})
check("the judge's own list is never trusted without the harness's record",
      any("no web_search block" in e for e in errs), str(errs))

# ---- call_gemini puts the block on its telemetry ---------------------------
src = Path(G.__file__).read_text()
body = src[src.index("def call_gemini("):src.index("def _v2_prompt_and_identity(")]
check("call_gemini records the uncapped web_search block from its own events",
      '"web_search": gemini_web_search_actions(events)' in body, "not found in call_gemini")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
