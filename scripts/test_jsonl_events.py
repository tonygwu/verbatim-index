#!/usr/bin/env python3
"""The harnesses' JSONL event streams are split on newlines only, and a bad line is counted.

FOUND 2026-10-03 in the rebuild run: an Astra early-call answer was refused three
times as `rule_violation: searched lists queries the harness never ran`. The query
had run. Codex printed an event whose web text held U+2028 (LINE SEPARATOR), and
call_astra split stdout with str.splitlines(), which also splits on U+2028. The
event came apart into two unparseable halves, the bare `except: pass` dropped both,
and the search inside it vanished from telemetry.web_search, which the resolver's
effort floor reads. JSON escapes "\n" inside strings, so a real newline only ever
ends an event. call_gemini parsed its stream the same way.

Builds a stream like the real one; no subprocess, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade as G  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


search = {"type": "item.completed", "item": {"type": "web_search", "id": "ws1", "query": "2026 AI agents deployed",
                                              "action": {"type": "search", "query": "2026 AI agents deployed"}}}
page = {"type": "item.completed", "item": {"type": "agent_message", "text": "a page said: one two"}}
# json.dumps with ensure_ascii=False writes U+2028 raw, as codex does.
stdout = "\n".join([json.dumps({"type": "thread.started"}),
                    json.dumps(page, ensure_ascii=False),
                    json.dumps(search, ensure_ascii=False) + " ",  # a separator after an event too
                    "not json at all {",
                    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1}})]) + "\n"

events, unparsed = G.parse_jsonl_events(stdout)
check("an event holding U+2028 inside a string parses whole",
      any((e.get("item") or {}).get("text") == "a page said: one two" for e in events), str(events)[:300])
check("the search after it is kept, so the effort floor sees it",
      G.web_search_actions(events)["queries"] == ["2026 AI agents deployed"], str(G.web_search_actions(events)))
check("a line that is not JSON is counted, not silently dropped", unparsed == 1, str(unparsed))
check("every real event is kept", len(events) == 4, str(len(events)))
# The same stream through str.splitlines(), the old way, for the record: it breaks the U+2028 event.
old = []
for line in stdout.splitlines():
    try:
        old.append(json.loads(line.strip()))
    except json.JSONDecodeError:
        pass
check("str.splitlines() on the same stream loses the event (demonstrates the defect)", len(old) < len(events),
      f"old {len(old)} new {len(events)}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
