#!/usr/bin/env python3
"""`data_sync.py` regenerates the derived files with the withdrawal manifest the scoring config names.

The manifest (predictions/withdrawn_predictions.json, ledger VD-9) is read by
aggregate_predictions and the scorer only when scoring.json names it under the
optional key `withdrawn`. data_sync.py regenerates both derived files in a
scratch tree holding predictions/ and roster/ from the commit, so it must pass
the manifest to aggregate_predictions and refuse, by name, a path outside
predictions/ or one the commit lacks.

  OUTSIDE   a manifest outside predictions/ is refused by regenerate and by check
  MISSING   a manifest the commit lacks is refused by both
  REGEN     a committed manifest regenerates: the index fingerprints it and counts
            the withdrawn prediction, scores.json names it, and both are fresh

  .venv/bin/python scripts/test_data_sync_withdrawn.py
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


T = load("test_data_sync_push", "tdsp_for_withdrawn")   # its seed(): a real remote with records
S = T.S


def attempt(fn, *args):
    try:
        return fn(*args), None
    except S.Refusal as e:
        return None, f"REFUSED {e}"
    except SystemExit as e:
        return None, f"EXIT {e}"
    except Exception as e:  # noqa: BLE001 - a raw error is the defect under test
        return None, f"CRASH {type(e).__name__}: {e}"


def name_manifest(c: Path, rel: str, pid: "str | None") -> None:
    cfg_path = c / "predictions" / "scoring.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["withdrawn"] = rel
    cfg_path.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")
    if pid:
        (c / rel).parent.mkdir(parents=True, exist_ok=True)
        (c / rel).write_text(json.dumps({"schema_version": 1, "note": "n", "withdrawn": {pid: {
            "reason": "not_a_forecast", "detail": "d", "evidence": ["https://example.com/x"],
            "transcript_id": "ada/s1", "decided_by": "operator", "decided_at_utc": "2026-09-30T07:10:44Z"}}}) + "\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        remote, ids = T.seed(td)
        pid = ids["s1"][0]

        print("OUTSIDE: a manifest outside predictions/ is refused by name")
        c = T.clone(td, remote, "outside")
        name_manifest(c, "manifests/withdrawn.json", pid)
        T.commit(c, "name a manifest outside predictions/")
        _, err = attempt(S.regenerate, c, "HEAD")
        check("OUTSIDE: regenerate refuses, naming the path and the rule",
              bool(err) and err.startswith("REFUSED") and "manifests/withdrawn.json" in err and "under predictions/" in err,
              str(err))
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("OUTSIDE: check reports a named problem rather than raising",
              err is None and any("manifests/withdrawn.json" in p for p in got), str(err or got))

        print("MISSING: a manifest the commit does not hold is refused by name")
        c = T.clone(td, remote, "missing")
        name_manifest(c, "predictions/withdrawn_predictions.json", None)
        T.commit(c, "name a manifest the commit lacks")
        _, err = attempt(S.regenerate, c, "HEAD")
        check("MISSING: regenerate refuses, naming the path and that the commit lacks it",
              bool(err) and err.startswith("REFUSED") and "predictions/withdrawn_predictions.json" in err
              and "not in the commit" in err, str(err))

        print("BUILT WITHOUT: a config naming the manifest over an index built without it")
        c = T.clone(td, remote, "without")
        name_manifest(c, "predictions/withdrawn_predictions.json", pid)
        T.commit(c, "name the manifest, keep the index built without it")
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("BUILT WITHOUT: check reports that the index ignores the withdrawals, naming the manifest",
              err is None and any("built without it" in p and "predictions/withdrawn_predictions.json" in p for p in got),
              str(err or got))

        print("REGEN: a committed manifest regenerates, fingerprinted in both derived files")
        c = T.clone(td, remote, "ok")
        name_manifest(c, "predictions/withdrawn_predictions.json", pid)
        T.commit(c, "withdraw one prediction")
        fresh, err = attempt(S.regenerate, c, "HEAD")
        idx = json.loads((fresh or {}).get("predictions/index.json", b"{}"))
        doc = json.loads((fresh or {}).get("predictions/scores.json", b"{}"))
        check("REGEN: the index fingerprints the manifest and counts the withdrawn prediction",
              err is None and idx.get("withdrawn_file") == "withdrawn_predictions.json"
              and len(idx.get("withdrawn_sha256") or "") == 64 and idx.get("corpus", {}).get("withdrawn") == 1,
              str(err or {k: idx.get(k) for k in ("withdrawn_file", "withdrawn_sha256")}))
        check("REGEN: scores.json names the manifest and carries the entry",
              doc.get("settings", {}).get("withdrawn") == "predictions/withdrawn_predictions.json"
              and pid in (doc.get("withdrawn") or {}).get("entries", {}), str(doc.get("settings")))
        for k, v in (fresh or {}).items():
            (c / k).write_bytes(v)
        if fresh:
            T.commit(c, "regenerate")
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("REGEN: derived_problems finds nothing stale", err is None and got == [], str(err or got))
        wf = c / "predictions" / "withdrawn_predictions.json"
        wf.write_text(wf.read_text().replace('"d"', '"edited"'))
        T.commit(c, "edit the manifest without regenerating")
        got, err = attempt(S.derived_problems, c, "HEAD")
        check("STALE: editing the manifest makes both derived files stale in the commit",
              err is None and any("index.json" in p for p in got) and any("scores.json" in p for p in got),
              str(err or got))

    print("\n" + ("all passed" if not FAILED else f"{len(FAILED)} failed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
