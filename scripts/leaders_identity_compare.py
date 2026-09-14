#!/usr/bin/env python3
"""Compare two leaders baseline runs, allowing only the named differences.

Pundits plan, P4. `scripts/leaders_baseline.py` writes each run's
`manifest.json`, a flat or nested map of output name to sha256. Hashes alone
overstate change, because some outputs legitimately carry a run time. Those
fields are named in ALLOWED, as dotted JSON paths, and nothing else is
tolerated:

  - an output whose hash matches is identical;
  - a JSON output whose hash differs is re-read from both runs' `data-copy`
    with every ALLOWED path removed, and still counts as different if anything
    else differs;
  - a non-JSON output whose hash differs, an output missing from one run, or a
    differing JSON output that cannot be found in `data-copy`, is a difference.

The first raw comparison of run12 against run1 reported 1,328 differences, all
of them this allowed field; that misreading is why the rule is committed here.

  .venv/bin/python scripts/leaders_identity_compare.py --a RUN1_DIR --b RUNN_DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ALLOWED = ("normalization.normalized_at_utc",)


def flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}/"))
        else:
            out[f"{prefix}{k}"] = v
    return out


def drop_path(obj, path: list[str]) -> None:
    if not isinstance(obj, dict) or not path:
        return
    if len(path) == 1:
        obj.pop(path[0], None)
    else:
        drop_path(obj.get(path[0]), path[1:])


def masked(path: Path) -> object:
    data = json.loads(path.read_text())
    for p in ALLOWED:
        drop_path(data, p.split("."))
    return data


def locate(run: Path, key: str) -> Path | None:
    for cand in (run / "data-copy" / key, run / "data-copy" / key.partition("/")[2]):
        if cand.is_file():
            return cand
    return None


def compare(a: Path, b: Path) -> dict:
    fa = flatten(json.loads((a / "manifest.json").read_text()))
    fb = flatten(json.loads((b / "manifest.json").read_text()))
    report = {"outputs": len(set(fa) | set(fb)), "identical": 0, "equal_after_allowed": 0, "differences": []}
    for key in sorted(set(fa) | set(fb)):
        if fa.get(key) == fb.get(key):
            report["identical"] += 1
            continue
        if key not in fa or key not in fb:
            report["differences"].append({"output": key, "why": "present in only one run"})
            continue
        pa, pb = locate(a, key), locate(b, key)
        if not key.endswith(".json") or pa is None or pb is None:
            report["differences"].append({"output": key, "why": "hash differs and it cannot be compared with allowed fields removed"})
            continue
        if masked(pa) == masked(pb):
            report["equal_after_allowed"] += 1
        else:
            report["differences"].append({"output": key, "why": f"differs outside the allowed fields {list(ALLOWED)}"})
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()
    report = compare(Path(args.a), Path(args.b))
    print(json.dumps({**report, "differences": report["differences"][:25],
                      "difference_count": len(report["differences"]), "allowed": list(ALLOWED)}, indent=1))
    return 1 if report["differences"] else 0


if __name__ == "__main__":
    sys.exit(main())
