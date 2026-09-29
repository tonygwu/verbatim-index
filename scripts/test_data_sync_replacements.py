#!/usr/bin/env python3
"""`data_sync.py` reads a replacement manifest only from under predictions/.

`data_sync.py` regenerates scores.json in a scratch tree that holds only
predictions/ and roster/ from the commit. A scoring.json naming a replacement
manifest anywhere else, or one the commit does not hold, used to fail there
with a raw FileNotFoundError from `score_inputs_sha256` (review 0 item 4 and
review 1 item 7 of the round-4 funnel change). Both are now refused by name,
the way `override_transcripts` refuses a date-override file.

  OUTSIDE   a manifest outside predictions/ is refused by regenerate and by check
  MISSING   a manifest under predictions/ that the commit lacks is refused by both
  REGEN     a committed manifest under predictions/ regenerates, and is fresh

  .venv/bin/python scripts/test_data_sync_replacements.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def load(name: str, alias: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(alias, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = load("test_data_sync_push", "tdsp_for_replacements")   # its seed(): a real remote with records
S = T.S


def attempt(fn, *args):
    """(result, None) or (None, 'REFUSED ...' | 'CRASH ...')."""
    try:
        return fn(*args), None
    except S.Refusal as e:
        return None, f"REFUSED {e}"
    except SystemExit as e:
        return None, f"EXIT {e}"
    except Exception as e:  # noqa: BLE001 - a raw error is the defect under test
        return None, f"CRASH {type(e).__name__}: {e}"


def name_manifest(c: Path, rel: str, write: bool) -> None:
    cfg_path = c / "predictions" / "scoring.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["replacements"] = rel
    cfg_path.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")
    if write:
        (c / rel).parent.mkdir(parents=True, exist_ok=True)
        (c / rel).write_text(json.dumps({"schema_version": 1, "replacements": []}) + "\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote, _ = T.seed(td)

        print("OUTSIDE: a manifest outside predictions/ is refused by name")
        c = T.clone(td, remote, "outside")
        name_manifest(c, "manifests/replacements.json", write=True)
        T.commit(c, "name a manifest outside predictions/")
        _, err = attempt(S.regenerate, c, "HEAD")
        check("OUTSIDE: regenerate refuses, naming the path and the rule",
              bool(err) and err.startswith("REFUSED") and "manifests/replacements.json" in err
              and "under predictions/" in err, str(err))
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("OUTSIDE: check reports a named problem rather than raising",
              err is None and any("manifests/replacements.json" in p and "under predictions/" in p for p in got),
              str(err or got))

        print("MISSING: a manifest under predictions/ that the commit does not hold is refused by name")
        c = T.clone(td, remote, "missing")
        name_manifest(c, "predictions/replacements.json", write=False)
        T.commit(c, "name a manifest the commit lacks")
        _, err = attempt(S.regenerate, c, "HEAD")
        check("MISSING: regenerate refuses, naming the path and that the commit lacks it",
              bool(err) and err.startswith("REFUSED") and "predictions/replacements.json" in err
              and "not in the commit" in err, str(err))
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("MISSING: check reports a named problem rather than raising",
              err is None and any("predictions/replacements.json" in p and "not in the commit" in p for p in got),
              str(err or got))

        print("REGEN: a committed manifest under predictions/ regenerates and is fresh")
        c = T.clone(td, remote, "ok")
        name_manifest(c, "predictions/replacements.json", write=True)
        T.commit(c, "name a committed manifest")
        fresh, err = attempt(S.regenerate, c, "HEAD")
        doc = json.loads((fresh or {}).get("predictions/scores.json", b"{}"))
        check("REGEN: scores.json names the manifest it read",
              err is None and doc.get("settings", {}).get("replacements") == "predictions/replacements.json"
              and (doc.get("replacements") or {}).get("replaced_sidecars") == [], str(err or doc.get("settings")))
        for k, v in (fresh or {}).items():
            (c / k).write_bytes(v)
        if fresh:
            T.commit(c, "regenerate")
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("REGEN: derived_problems finds nothing stale", err is None and got == [], str(err or got))

    print("\n" + ("all passed" if not FAILED else f"{len(FAILED)} failed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
