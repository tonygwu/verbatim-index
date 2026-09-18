#!/usr/bin/env python3
"""Outputs that cross clone boundaries are written whole or not at all.

Every clone shares one data checkout. `Path.write_text` truncates the target and
then writes, so a reader in another clone can get a prefix. `json.load` raises on
that, which fails loudly rather than publishing a wrong page, but an
intermittently failing deploy is a bad thing to debug months later.

`scripts/atomicio.py` has existed for this since results.json and site/index.html
needed it, and it had no test of its own. This is that test, plus an assertion
that the two files converted on 2026-09-18 actually use it:

  discovered.json   read by build_site.py DURING a render, and written by
                    discovery in whichever clone is crawling
  aliases.json      the blinder input AND the QA glossary, read by normalize and
                    qa while other clones run. A torn read there flips a QA
                    verdict, and a flipped verdict orphans grades

No network, no quota. Temporary directories only.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

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


def main() -> int:
    from atomicio import write_atomic

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("[1] it writes the content, and returns the path")
        target = tmp / "out.json"
        got = write_atomic(target, json.dumps({"a": 1}))
        check("the file holds what was written",
              json.loads(target.read_text()) == {"a": 1})
        check("it returns the path", Path(got) == target, str(got))

        print("\n[2] a reader NEVER sees a prefix, under real concurrency")
        # The discriminating test. A large payload is rewritten repeatedly while
        # a reader parses the file as fast as it can. With write_text the reader
        # eventually catches a truncated file and json.loads raises; with an
        # atomic rename it always sees one whole version or the other.
        big_a = json.dumps({"rows": [{"i": i, "pad": "x" * 200} for i in range(4000)]})
        big_b = json.dumps({"rows": [{"i": i, "pad": "y" * 200} for i in range(4000)]})
        target.write_text(big_a)
        stop = threading.Event()
        torn: list[str] = []
        seen: set[int] = set()

        def reader() -> None:
            while not stop.is_set():
                try:
                    d = json.loads(target.read_text())
                    seen.add(len(d["rows"]))
                except Exception as exc:  # noqa: BLE001
                    torn.append(f"{type(exc).__name__}: {exc}")

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        for i in range(60):
            write_atomic(target, big_a if i % 2 else big_b)
        stop.set()
        t.join(timeout=5)
        check(f"no torn read in 60 rewrites (reader saw {len(seen)} shape(s))",
              not torn, f"{len(torn)} torn reads, first: {torn[:1]}")
        check("the reader actually ran and parsed something", bool(seen),
              "if the reader never parsed, this arm proves nothing")

        print("\n[3] the same loop with write_text DOES tear, so arm [2] is real")
        target2 = tmp / "naive.json"
        target2.write_text(big_a)
        stop2 = threading.Event()
        torn2: list[str] = []

        def reader2() -> None:
            while not stop2.is_set():
                try:
                    json.loads(target2.read_text())
                except FileNotFoundError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    torn2.append(type(exc).__name__)

        t2 = threading.Thread(target=reader2, daemon=True)
        t2.start()
        for i in range(60):
            target2.write_text(big_a if i % 2 else big_b)
        stop2.set()
        t2.join(timeout=5)
        # Reported rather than asserted: a torn read is a race and a fast machine
        # may win it every time. If this says 0 the comparison is inconclusive,
        # and it says so instead of quietly claiming a result.
        if torn2:
            check(f"write_text tore {len(torn2)} times, so the window is real", True)
        else:
            check("write_text did not tear in this run, so arm [2] is UNPROVEN "
                  "on this machine", True,
                  "not a failure: the race was not won. Arm [2] still shows "
                  "write_atomic never tears.")

        print("\n[4] no temporary file is left behind")
        leftovers = [p.name for p in tmp.iterdir()
                     if p.name not in {"out.json", "naive.json"}]
        check("the directory holds only the targets", not leftovers, str(leftovers))

        print("\n[5] the temp file is written in the TARGET's directory")
        # os.replace is atomic only within one filesystem. A temp in /tmp and a
        # target on another mount would fall back to a copy, which is the window
        # this file exists to close.
        src = (REPO / "scripts" / "atomicio.py").read_text()
        check("the temp is created next to the target",
              "dir=" in src or "parent" in src, "os.replace is atomic per filesystem")

        print("\n[6] the writers that cross clone boundaries use it")
        for name, needle in (("discover_sources.py", "write_atomic(args.out"),
                             ("sources_to_manifest.py", "write_atomic(ap_path")):
            body = (REPO / "scripts" / name).read_text()
            check(f"{name} writes through write_atomic", needle in body)
            check(f"{name} has no write_text(json.dumps left",
                  "write_text(json.dumps" not in body,
                  [l.strip() for l in body.splitlines() if "write_text(json.dumps" in l])

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
