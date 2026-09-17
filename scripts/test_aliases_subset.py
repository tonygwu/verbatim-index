#!/usr/bin/env python3
"""Re-deriving aliases.json must never drop a term that is already on disk.

sources_to_manifest.py wrote aliases.json wholesale from the discovery payload:

    Path(args.aliases).write_text(json.dumps(aliases, indent=1))

The file on disk is not purely derived. Terms have been added by hand since the
last discovery run, and re-derivation is a STRICT SUBSET of what is there.
MEASURED 2026-09-16 by regenerating from the live data/sources/discovered.json
into a temp directory and diffing: terms only on disk 14, terms only derived 0,
across 7 slugs -- `Alphabet`, `Sun Microsystems`, `Novell` (eric-schmidt),
`OpenAI`, `Safe Superintelligence` (ilya-sutskever), `comma.ai`, `geohot`,
`tinycorp`, `the tiny corp` (george-hotz), `Scale AI`,
`Meta Superintelligence Labs` (alexandr-wang), `gdb` (greg-brockman),
`Strategy Inc` (michael-saylor), `Tobias` (tobi-lutke).

Losing them is not cosmetic. aliases.json is ALSO the QA glossary:
grade_loop.sh:150 passes it as --glossaries, qa_transcripts.py:142 computes
`known = dictionary | glossary`, and that drives oov_rate, which drives the
reject verdict, which orphans a leader's grades.

So the assertion is SUBSET CONTAINMENT, never byte equality. Byte equality is
the wrong direction: it would make the 14 hand-curated terms a failure to be
removed rather than state to be kept. For the 50 the containment assertion is a
tautology, and that is the point -- it holds whatever discovery returns next.

repairs.json is written by the same path and was checked at the same time: 0
repairs only on disk and 0 only derived, so it carries no equivalent exposure.

These checks run against temporary files. Nothing under data/ is written.
No quota, no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S2M = ROOT / "scripts" / "sources_to_manifest.py"

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def build(tmp: Path, *, existing: dict | None) -> dict:
    """Discovery returns FEWER alias terms than the file already holds."""
    src = {"leaders": [
        {"leader_slug": "leader-a",
         "aliases": ["Leader A", "Acme"],
         "repairs": [],
         "sources": [{"source_id": "talk-one", "video_id": "abcdefghijk",
                      "title": "A talk", "venue": "podcast", "kind": "interview",
                      "year": 2024, "rank": 1}]},
        {"leader_slug": "leader-b",
         "aliases": ["Leader B"],
         "repairs": [],
         "sources": [{"source_id": "talk-two", "video_id": "bcdefghijkl",
                      "title": "B talk", "venue": "podcast", "kind": "interview",
                      "year": 2024, "rank": 1}]},
    ]}
    (tmp / "discovered.json").write_text(json.dumps(src))
    paths = {k: tmp / f"{k}.json" for k in ("aliases", "repairs", "report")}
    paths["manifest"] = tmp / "all.jsonl"
    if existing is not None:
        paths["aliases"].write_text(json.dumps(existing, indent=1))
    return paths


def run(tmp: Path, paths: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(S2M),
         "--sources", str(tmp / "discovered.json"),
         "--manifest", str(paths["manifest"]),
         "--aliases", str(paths["aliases"]),
         "--repairs", str(paths["repairs"]),
         "--report", str(paths["report"]), *extra],
        capture_output=True, text=True)


# The hand-curated state: leader-a carries two terms discovery does not return.
# Deliberately NOT in sorted order: a sorted fixture would make the
# order-preservation check below pass against a sorting implementation.
EXISTING = {"leader-a": ["Acme Corporation", "Acme", "a-hacker-handle", "Leader A"],
            "leader-b": ["Leader B"]}


def main() -> int:
    print("re-deriving aliases must not drop hand-curated terms\n")

    print("[1] with no file on disk, the derived set is written as-is")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        paths = build(tmp, existing=None)
        r = run(tmp, paths)
        check("exits 0", r.returncode == 0, r.stderr[-800:])
        got = json.loads(paths["aliases"].read_text())
        check("leader-a gets exactly the derived terms",
              got.get("leader-a") == ["Acme", "Leader A"], f"got {got.get('leader-a')}")

    print("\n[2] THE BUG: a re-run must not drop terms only the file holds")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        paths = build(tmp, existing=EXISTING)
        r = run(tmp, paths)
        check("exits 0", r.returncode == 0, r.stderr[-800:])
        got = json.loads(paths["aliases"].read_text())
        a = set(got.get("leader-a", []))
        for term in ("Acme Corporation", "a-hacker-handle"):
            check(f"{term!r} survives the re-run", term in a,
                  f"leader-a is now {sorted(a)}; a hand-curated glossary term was "
                  "destroyed, which changes oov_rate and can orphan grades")
        check("the derived terms are still present",
              {"Acme", "Leader A"} <= a, f"got {sorted(a)}")
        check("containment holds for every slug",
              all(set(EXISTING[s]) <= set(got.get(s, [])) for s in EXISTING),
              f"got {got}")
        check("terms stay unique",
              all(len(v) == len(set(v)) for v in got.values()), f"got {got}")
        # ORDER IS LOAD-BEARING. The live blinder is the `wordlist is None`
        # branch of normalize_transcripts.blind(), which applies
        # `name_forms + aliases` in list order with no length sort, so
        # re-ordering "Aaron Levie" behind "Aaron" changes blinded text under
        # every grade already collected. The existing order must survive and
        # new terms may only be appended.
        check("the existing order is preserved, new terms appended",
              got.get("leader-a", [])[:len(EXISTING["leader-a"])] == EXISTING["leader-a"],
              f"got {got.get('leader-a')}; expected it to start with "
              f"{EXISTING['leader-a']}")

    print("\n[3] the merge is reported, never silent")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        paths = build(tmp, existing=EXISTING)
        run(tmp, paths)
        rep = json.loads(paths["report"].read_text())
        check("the report says how many terms the merge preserved",
              rep.get("alias_terms_preserved_by_merge") == 2,
              f"got {rep.get('alias_terms_preserved_by_merge')!r}; a merge that "
              "keeps state silently cannot be audited")

    print("\n[4] replacing is possible, but explicit and it names what it drops")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        paths = build(tmp, existing=EXISTING)
        r = run(tmp, paths, "--replace-aliases")
        check("exits 0", r.returncode == 0, r.stderr[-800:])
        got = json.loads(paths["aliases"].read_text())
        check("leader-a is now exactly the derived set",
              got.get("leader-a") == ["Acme", "Leader A"], f"got {got.get('leader-a')}")
        rep = json.loads(paths["report"].read_text())
        dropped = rep.get("alias_terms_dropped_by_replace") or {}
        check("the dropped terms are named, not counted",
              sorted(dropped.get("leader-a", [])) == ["Acme Corporation", "a-hacker-handle"],
              f"got {dropped!r}")

    print("\n[5] a merge that adds nothing rewrites the file byte-identically")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        paths = build(tmp, existing=None)
        # Seed with a superset of the derived terms, carrying non-ASCII, in
        # non-sorted order. Nothing new can be added, so the merge must be a
        # no-op down to the bytes. The pre-push audit requires this file
        # unchanged, and \u00fc-escaping alone would show as a diff.
        seeded = {"leader-a": ["Leader A", "Acme", "Tobi L\u00fctke"],
                  "leader-b": ["Leader B"]}
        paths["aliases"].write_text(json.dumps(seeded, indent=1, ensure_ascii=False))
        before = paths["aliases"].read_bytes()
        r = run(tmp, paths)
        check("exits 0", r.returncode == 0, r.stderr[-800:])
        check("the file is byte-identical after a no-op merge",
              paths["aliases"].read_bytes() == before,
              "a no-op merge rewrote the file; the pre-push audit requires "
              "aliases.json unchanged for the existing leaders")
        check("the non-ASCII term is not escaped",
              "L\u00fctke" in paths["aliases"].read_text(encoding="utf-8"))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
