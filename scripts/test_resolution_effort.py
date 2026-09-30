#!/usr/bin/env python3
"""The research-effort floor counts what the harness actually searched (review of 2026-09-30, item 1).

The first version counted codex `web_search` ITEMS. MEASURED on the 129 raw
resolver responses in the data repository: 691 completed web_search items, 405
of them carrying MORE than one query in `action.queries`, and 224 of 681 in one
tally are page opens (`action.type == "other"`, no query at all). So an item
count both undercounts searching and counts reading as searching, and it
refused 28 of 129 calls, 24 of them hits. `web_search_queries` also kept only
the first 10 item display strings.

What this pins, through the real `grade.call_astra` with its spawn stubbed to
return a codex event stream of the real shape (item.started and item.completed
pairs; `action` of type `search` with a `queries` list, or `other`):
  - the harness records every DISTINCT query of every completed search action,
    uncapped, and counts page opens apart;
  - the floor is three distinct queries, whatever the outcome; page opens do not
    count, one action with three queries does;
  - the model's `searched` list must be queries the harness ran, compared after
    normalising case, quotes and spaces; one it never ran is refused by name;
  - telemetry without the search record is refused, never assumed.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import grade  # noqa: E402
import resolution_lib as R  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def stream(actions: list[dict], answer: dict) -> str:
    """A codex --json stdout in the shape the raw resolver responses on disk carry."""
    ev = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
          {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "Skill descriptions were shortened"}}]
    for i, a in enumerate(actions):
        shown = (a.get("queries") or [""])[0] + (" ..." if len(a.get("queries") or []) > 1 else "")
        item = {"id": f"ws_{i}", "type": "web_search", "query": shown if a["type"] == "search" else "", "action": a}
        ev.append({"type": "item.started", "item": {**item, "action": {"type": "other"}, "query": ""}})
        if not a.get("_never_completed"):
            ev.append({"type": "item.completed", "item": item})
    ev.append({"type": "item.completed", "item": {"id": "msg", "type": "agent_message", "text": json.dumps(answer)}})
    ev.append({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5,
                                                   "reasoning_output_tokens": 3}})
    return "\n".join(json.dumps(e) for e in ev) + "\n"


def run_astra(stdout: str) -> dict:
    """The real call_astra, with its one subprocess call answered by `stdout`."""
    real = subprocess.run
    subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout, "")
    try:
        with tempfile.TemporaryDirectory() as td:
            _, tel = grade.call_astra("prompt", 60, pathlib.Path(td) / "jail")
    finally:
        subprocess.run = real
    return tel


def main() -> int:
    answer = {"prediction_id": "p", "outcome": "occurred"}
    actions = [
        {"type": "search", "queries": ["Stripe 2025 profitability", "Stripe annual letter 2025"]},
        {"type": "other"},                                                          # a page open
        {"type": "search", "queries": ["stripe  2025 PROFITABILITY", "Stripe net income 2025"]},  # one repeat
        {"type": "search", "queries": ["never finished"], "_never_completed": True},
    ]
    tel = run_astra(stream(actions, answer))
    ws = tel.get("web_search") or {}
    print("the harness's record of what it searched")
    check("TELEMETRY: completed search actions and page opens are counted apart",
          ws.get("search_actions") == 2 and ws.get("other_actions") == 1, json.dumps(ws))
    check("TELEMETRY: every query of every completed search action is kept, the unfinished one is not",
          ws.get("queries") == ["Stripe 2025 profitability", "Stripe annual letter 2025", "stripe  2025 PROFITABILITY",
                                "Stripe net income 2025"], json.dumps(ws.get("queries")))
    # The other real search shape: 59 of the 691 items carry ONE query as `action.query`. And the
    # other real `other` shapes: 141 open a URL and 42 look for a snippet in a page; neither is a search.
    single = run_astra(stream([{"type": "search", "query": '"Netscape ONE"'},
                               {"type": "other", "query_": "https://example.com/filing"},
                               {"type": "search", "queries": ["Netscape 1996 network", "Netscape marketplaces"]}],
                              answer))["web_search"]
    check("TELEMETRY: a search action carrying one `query` is one search; page opens are not searches",
          single["queries"] == ['"Netscape ONE"', "Netscape 1996 network", "Netscape marketplaces"]
          and single["search_actions"] == 2 and single["other_actions"] == 1
          and single["search_actions_without_queries"] == 0, json.dumps(single))
    many = run_astra(stream([{"type": "search", "queries": [f"query {i}" for i in range(12)]}], answer))["web_search"]
    check("TELEMETRY: nothing is capped at ten", len(many["queries"]) == 12, str(len(many["queries"])))
    check("COUNT: three distinct queries after normalising case and spaces, from four listed",
          R.distinct_queries(ws["queries"]) == 3, str(R.distinct_queries(ws["queries"])))

    print("the floor, whatever the outcome")
    obj = {"searched": ["Stripe 2025 profitability", "stripe annual letter 2025", "Stripe net income 2025"]}
    check("FLOOR: three distinct queries run and listed pass", R.validate_effort(obj, tel) == [],
          str(R.validate_effort(obj, tel)))
    two = run_astra(stream([{"type": "search", "queries": ["a one"]}, {"type": "other"}, {"type": "other"},
                            {"type": "search", "queries": ["b two"]}], answer))
    errs = R.validate_effort({"searched": ["a one", "b two"]}, two)
    check("FLOOR: four items, but two queries and two page opens, are two searches: refused",
          any("2 distinct" in e for e in errs), str(errs))
    one = run_astra(stream([{"type": "search", "queries": ["x", "y", "z"]}], answer))
    check("FLOOR: one action carrying three queries is three searches: passes",
          R.validate_effort({"searched": ["x", "y", "z"]}, one) == [], str(R.validate_effort({"searched": ["x", "y", "z"]}, one)))
    errs = R.validate_effort(dict(obj, searched=obj["searched"] + ["Stripe IPO date"]), tel)
    check("COMPARE: a listed query the harness never ran is refused by name",
          any("Stripe IPO date" in e for e in errs), str(errs))
    check("COMPARE: curly quotes and extra spaces are not a different query",
          R.validate_effort({"searched": ["“Stripe 2025 profitability”", "Stripe  annual letter 2025",
                                          "Stripe net income 2025"]},
                            run_astra(stream([{"type": "search", "queries": ['"Stripe 2025 profitability"',
                                                                             "Stripe annual letter 2025",
                                                                             "Stripe net income 2025"]}], answer))) == [])
    check("TELEMETRY: a record with no web_search block is refused, never assumed",
          R.validate_effort(obj, {"tool_use_counts": {"web_search": 9}}) != [] and R.validate_effort(obj, {}) != [])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
