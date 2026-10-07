#!/usr/bin/env python3
"""AGENTS.md stays small enough to load whole, and the shards it points at exist.

WHY THIS EXISTS. On 2026-10-06 AGENTS.md was 133,085 bytes. Claude Code warned
that the instruction files together passed its 150k-character limit. Codex was
worse off, silently: it reads at most `project_doc_max_bytes` of the file,
32,768 bytes by default, so every Codex agent in the fleet got the first quarter
and nothing after it. MEASURED by asking Codex for the last words it received,
with no tool calls: "not because it was wr", cut mid-word at byte 32,768,
inside "Rules that exist because something broke". It never saw the measurement
decisions, the known limits or the map of where things are.

The agreement was split. AGENTS.md keeps what every agent needs on every task
and an index; everything else moved unchanged to docs/agents/<TOPIC>.md, which
an agent opens when its task touches that topic.

WHAT IS CHECKED.

  1. AGENTS.md is at most 32,768 bytes, Codex's default limit. Past it the
     text is lost to Codex without any message, which is why this is a refusal
     and not a warning.
  2. Every relative link in AGENTS.md and in each shard resolves.
  3. The index table in AGENTS.md names every file in docs/agents/, gives each
     one a trigger, and names no file that does not exist. A shard the index
     does not name is a shard nobody opens.
  4. AGENTS.md carries no `@`-import. Claude Code expands `@path` into every
     session, so one import of a shard would load it on every task again.

No network, no quota, no writes.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = REPO / "AGENTS.md"
SHARD_DIR = REPO / "docs" / "agents"

#: Codex's default `project_doc_max_bytes`. Read out of the installed binary
#: (codex-cli 0.157.1, the string `project_doc_max_bytes = 32768`) and confirmed
#: by the truncation measured above.
CODEX_PROJECT_DOC_MAX_BYTES = 32768

LINK = re.compile(r"\]\(([^)\s]+)\)")
INDEX_ROW = re.compile(r"^\| \[docs/agents/([^\]]+\.md)\]\(docs/agents/\1\) \| (.*?) \|$", re.M)
#: An `@path` at the start of a line or after whitespace, outside code. An email
#: such as `x@users.noreply.github.com` has a word character before the `@`.
IMPORT = re.compile(r"(?:^|(?<=\s))@[~\w./-]+", re.M)

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    return ok


def outside_code(text: str) -> str:
    text = re.sub(r"^\s*```.*?^\s*```", "", text, flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def main() -> int:
    shards = sorted(SHARD_DIR.glob("*.md"))
    text = AGENTS.read_text()

    print("[1] AGENTS.md fits inside what Codex reads")
    size = len(AGENTS.read_bytes())
    check(f"AGENTS.md is {size:,} bytes, at most {CODEX_PROJECT_DOC_MAX_BYTES:,}",
          size <= CODEX_PROJECT_DOC_MAX_BYTES,
          f"Codex drops everything after byte {CODEX_PROJECT_DOC_MAX_BYTES:,}. Move "
          f"material that not every task needs into the docs/agents/ file of its topic")

    print("\n[2] every relative link resolves")
    check("the shard directory holds shards at all", len(shards) > 0,
          f"{SHARD_DIR} is empty or missing, so the index points at nothing")
    for f in [AGENTS] + shards:
        targets = [t for t in LINK.findall(outside_code(f.read_text()))
                   if not re.match(r"[a-z]+:", t) and not t.startswith("#")]
        dangling = [t for t in targets if not (f.parent / t.split("#")[0]).exists()]
        check(f"{f.relative_to(REPO)}: {len(targets)} relative links resolve",
              not dangling, f"dangling: {dangling}")

    print("\n[3] the index in AGENTS.md and docs/agents/ name the same files")
    rows = dict(INDEX_ROW.findall(text))
    check("the index table has rows at all", bool(rows),
          "no row matched; if its format changed, this check stops testing")
    on_disk = {p.name for p in shards}
    check("every shard on disk is in the index", on_disk <= set(rows),
          f"not in the index: {sorted(on_disk - set(rows))}")
    check("every shard in the index is on disk", set(rows) <= on_disk,
          f"in the index but missing: {sorted(set(rows) - on_disk)}")
    empty = [n for n, trigger in rows.items() if len(trigger.strip()) < 20]
    check("every index row says when to read the shard", not empty,
          f"no trigger for: {empty}")

    print("\n[4] AGENTS.md imports nothing into every session")
    imports = IMPORT.findall(outside_code(text))
    check("no @-import outside code", not imports, f"found {imports}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
