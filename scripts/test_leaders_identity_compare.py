#!/usr/bin/env python3
"""The leaders identity comparison tolerates only the named field, and nothing that merely looks similar.

Pundits plan, P4.

  IDENTICAL   matching hashes count as identical
  ALLOWED     a JSON output differing only at normalization.normalized_at_utc is equal
  OTHER       the same key name at a different path is still a difference
  CONTENT     any other changed field is a difference
  NON-JSON    a changed text output is a difference
  MISSING     an output in only one run is a difference; so is a differing JSON
              output that cannot be found to re-read

No quota.

  .venv/bin/python scripts/test_leaders_identity_compare.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def run(root: Path, name: str, files: dict[str, object], manifest: dict[str, str]) -> Path:
    d = root / name
    for rel, content in files.items():
        p = d / "data-copy" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else json.dumps(content))
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


def main() -> int:
    print("leaders identity compare")
    import leaders_identity_compare as C

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = {"text": "t", "normalization": {"normalized_at_utc": "2026-09-13T00:00:00Z", "subs": 3}}

        def pair(b_doc, b_hash="h2", extra_a=None, extra_b=None, key="transcripts_blind/p/s.json"):
            a = run(root / "x", "a", {key: base, **(extra_a or {})}, {key: "h1"})
            b = run(root / "x", "b", {key: b_doc, **(extra_b or {})}, {key: b_hash})
            return C.compare(a, b)

        print("\n[IDENTICAL]")
        r = pair(base, b_hash="h1")
        check("matching hashes are identical", r["identical"] == 1 and not r["differences"], str(r))

        print("\n[ALLOWED]")
        r = pair({**base, "normalization": {"normalized_at_utc": "2026-09-14T09:00:00Z", "subs": 3}})
        check("only normalized_at_utc differing is equal after the allowed field", r["equal_after_allowed"] == 1 and not r["differences"], str(r))

        print("\n[OTHER]")
        r = pair({**base, "normalized_at_utc": "elsewhere"})
        check("the same key name at another path is a difference", len(r["differences"]) == 1, str(r))

        print("\n[CONTENT]")
        r = pair({**base, "normalization": {"normalized_at_utc": "2026-09-14T09:00:00Z", "subs": 4}})
        check("another changed field is a difference", len(r["differences"]) == 1, str(r))

        print("\n[NON-JSON]")
        a = run(root / "y", "a", {}, {"prompts": "h1"})
        b = run(root / "y", "b", {}, {"prompts": "h2"})
        check("a changed text output is a difference", len(C.compare(a, b)["differences"]) == 1)

        print("\n[MISSING]")
        a = run(root / "z", "a", {}, {"results.json": "h1", "extra": "h"})
        b = run(root / "z", "b", {}, {"results.json": "h2"})
        r = C.compare(a, b)
        why = sorted(d["why"] for d in r["differences"])
        check("an output in one run only, and an unlocatable differing JSON, are both differences",
              len(r["differences"]) == 2 and any("only one run" in w for w in why), str(why))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
