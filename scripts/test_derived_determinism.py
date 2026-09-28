#!/usr/bin/env python3
"""Derived predictions files are pure functions of their inputs.

WHY: several clones will push the private data repo's main themselves
(docs/plans in the operator's plan "every clone pushes private main"). A derived
file that changes on every rebuild conflicts on every concurrent push, and a
derived file whose freshness cannot be checked lets a stale copy land over newer
inputs. Both are clobbers. So:

  INDEX    predictions/index.json carries no wall-clock field and no absolute
           path, so two rebuilds of the same tree, in two different clones, are
           byte-identical.
  LISTING  the transcript roots the index counts are fingerprinted, because they
           are an input that inputs_sha256 and roster_sha256 cannot see.
  STALE    aggregate_predictions.staleness() names every input that moved.
  SCORES   predictions/scores.json can be built from a committed config
           (predictions/scoring.json), byte-identical to the flag form, carries no
           wall-clock field, and fingerprints every input it read.
  CONFIG   the config is strict: an unknown or missing key refuses.
  PAGE     the page's date comes from an explicit --data-date, never from a
           clock, so the index no longer needs a timestamp.

  .venv/bin/python scripts/test_derived_determinism.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_dd", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------- index ----

def index_checks(L, A, T) -> None:
    stale = getattr(A, "staleness", lambda *a: "MISSING aggregate_predictions.staleness()")
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        a, b = Path(t1), Path(t2)
        pr = T.build(a, L)
        roster_path = a / "roster.json"
        roster = {r["slug"]: r for r in json.loads(roster_path.read_text())["roster"]}
        roots = [a / "tx"]
        i1 = A.build_index(pr, roster, roots, roster_path)
        i2 = A.build_index(pr, roster, roots, roster_path)
        check("INDEX: two rebuilds of one tree are byte-identical, every key included", dumps(i1) == dumps(i2))
        check("INDEX: no wall-clock field", "generated_at_utc" not in i1, sorted(i1)[:12])
        check("INDEX: no absolute path", "predictions_root" not in i1 and str(a) not in dumps(i1),
              [k for k in i1 if str(a) in dumps(i1[k])])

        # A second clone holds the same tree at a different absolute path.
        shutil.copytree(a / "pred", b / "pred")
        shutil.copytree(a / "tx", b / "tx")
        shutil.copy(roster_path, b / "roster.json")
        i3 = A.build_index(b / "pred", roster, [b / "tx"], b / "roster.json")
        check("INDEX: the same tree in another clone gives the same bytes", dumps(i1) == dumps(i3))

        check("LISTING: the transcript listing is fingerprinted", bool(i1.get("transcripts_listing_sha256")))
        check("STALE: a fresh index has no staleness",
              stale(i1, pr, roster_path, roots) is None, str(stale(i1, pr, roster_path, roots)))

        (a / "tx" / "grace" / "t9.json").write_text("{}")
        moved = A.build_index(pr, roster, roots, roster_path)
        check("LISTING: a new transcript file changes the fingerprint",
              moved.get("transcripts_listing_sha256") != i1.get("transcripts_listing_sha256"))
        why = stale(i1, pr, roster_path, roots) or ""
        check("STALE: a new transcript is named as the stale input", "transcript" in why, why)
        (a / "tx" / "grace" / "t9.json").unlink()

        rec_file = sorted(pr.glob("ada/*.jsonl"))[0]
        original = rec_file.read_text()
        rec_file.write_text(original.replace("most code", "most CODE", 1))
        why = stale(i1, pr, roster_path, roots) or ""
        check("STALE: an in-place record rewrite is named", "record" in why, why)
        rec_file.write_text(original)

        roster_path.write_text(roster_path.read_text().replace("Admiral", "Rear Admiral"))
        why = stale(i1, pr, roster_path, roots) or ""
        check("STALE: a roster change is named", "roster" in why, why)


# --------------------------------------------------------------- scores ----

def pred(pid: str) -> dict:
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "prediction": {"target_date": "2020-12-31", "specificity": "high", "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": "c", "resolution_criteria": "crit"},
        "source": {"statement_date": "2019-01-01", "quote": "q"},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def pair(R, run: Path, pid: str, outcome: str, p: float) -> None:
    res = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "resolve",
           "outcome": outcome, "confidence": "high", "unresolvable_reason": None, "reasoning": "r",
           "sources": [{"where": "u", "what_it_shows": "w", "date": None}], "deadline": "2020-12-31"}
    pri = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "prior",
           "p": p, "p_raw": p, "clamped": False, "reference_class": "rc", "reasoning": "r"}
    for stage, obj in (("resolve", res), ("prior", pri)):
        fp = R.sidecar_path(run, stage, "ada", pid)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(obj))


CONFIG = {
    "as_of": "2026-09-16", "trend": True, "min_lead_days": 60,
    "predictions": ["predictions"],
    "runs": ["predictions/_experiments/run-a", "predictions/_experiments/run-b"],
    "index": "predictions/index.json",
    "out": "predictions/scores.json",
}


def score(root: Path, *argv: str):
    """Run from the public repo, as the pipeline does; every path is absolute."""
    return subprocess.run([PY, str(REPO / "scripts" / "score_predictions.py"), *argv],
                          capture_output=True, text=True, cwd=REPO)


def scores_checks(R, S) -> None:
    sst = getattr(S, "scores_staleness", lambda *a: "MISSING score_predictions.scores_staleness()")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "predictions" / "ada").mkdir(parents=True)
        (root / "predictions" / "ada" / "t1.jsonl").write_text(
            "".join(json.dumps(pred(p)) + "\n" for p in ("p1", "p2")))
        (root / "predictions" / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        pair(R, root / CONFIG["runs"][0], "p1", "occurred", 0.5)
        pair(R, root / CONFIG["runs"][1], "p2", "not_occurred", 0.4)
        cfg = root / "predictions" / "scoring.json"
        cfg.write_text(dumps(CONFIG) + "\n")

        flag = score(root, "--predictions", str(root / "predictions"), "--index", str(root / "predictions/index.json"),
                     "--run", str(root / CONFIG["runs"][0]), "--run", str(root / CONFIG["runs"][1]),
                     "--as-of", CONFIG["as_of"], "--min-lead-days", "60", "--trend",
                     "--out", str(root / "flag.json"))
        check("SCORES: the flag form exits 0", flag.returncode == 0, flag.stderr[-500:])
        conf = score(root, "--config", str(cfg))
        check("SCORES: the config form exits 0", conf.returncode == 0, conf.stderr[-500:])
        fb = (root / "flag.json").read_text() if (root / "flag.json").exists() else ""
        out = root / CONFIG["out"]
        cb = out.read_text() if out.exists() else ""
        check("SCORES: the config form writes the out path it names", bool(cb))
        check("SCORES: config and flag forms are byte-identical", fb == cb and bool(fb),
              f"flag {len(fb)} bytes, config {len(cb)} bytes")
        doc = json.loads(cb) if cb else {}
        check("SCORES: no wall-clock field", "generated_at_utc" not in doc, sorted(doc)[:12])
        check("SCORES: every input is fingerprinted", bool(doc.get("inputs_sha256")))

        again = score(root, "--config", str(cfg))
        check("SCORES: a rebuild with unchanged inputs is byte-identical",
              again.returncode == 0 and out.read_text() == cb)

        check("STALE: fresh scores have no staleness",
              sst(out, cfg) is None, str(sst(out, cfg)))
        pf = R.sidecar_path(root / CONFIG["runs"][1], "prior", "ada", "p2")
        orig = pf.read_text()
        pf.write_text(orig.replace("0.4", "0.45"))
        check("STALE: a changed prior makes scores stale", sst(out, cfg) is not None)
        pf.write_text(orig)
        idx = root / "predictions" / "index.json"
        orig_idx = idx.read_text()
        idx.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada Lovelace"}]}))
        check("STALE: a changed index makes scores stale", sst(out, cfg) is not None)
        idx.write_text(orig_idx)
        cfg.write_text(dumps({**CONFIG, "as_of": "2026-09-17"}) + "\n")
        check("STALE: a changed scoring config makes scores stale", sst(out, cfg) is not None)
        cfg.write_text(dumps(CONFIG) + "\n")
        check("STALE: restoring every input restores freshness", sst(out, cfg) is None,
              str(sst(out, cfg)))

        cfg.write_text(dumps({**CONFIG, "as_off": "2026-09-16"}) + "\n")
        bad = score(root, "--config", str(cfg))
        check("CONFIG: an unknown key refuses, naming it", bad.returncode != 0 and "as_off" in bad.stderr,
              bad.stderr[-300:])
        cfg.write_text(dumps({k: v for k, v in CONFIG.items() if k != "trend"}) + "\n")
        bad = score(root, "--config", str(cfg))
        check("CONFIG: a missing key refuses, naming it", bad.returncode != 0 and "trend" in bad.stderr,
              bad.stderr[-300:])
        cfg.write_text(dumps(CONFIG) + "\n")
        both = score(root, "--config", str(cfg), "--as-of", "2026-09-16")
        check("CONFIG: --config refuses to mix with the flags it replaces", both.returncode != 0, both.stderr[-300:])


# ----------------------------------------------------------------- page ----

def page_checks() -> None:
    p = subprocess.run([PY, str(REPO / "scripts" / "build_predictions_site.py"), "--index", "/nonexistent.json"],
                       capture_output=True, text=True, cwd=REPO)
    check("PAGE: rendering without --data-date refuses before reading anything",
          p.returncode != 0 and "--data-date" in p.stderr, p.stderr[-300:])


def main() -> int:
    L = load("predictions_lib")
    A = load("aggregate_predictions")
    T = load("test_predictions_aggregate")
    R = load("resolution_lib")
    S = load("score_predictions")
    index_checks(L, A, T)
    scores_checks(R, S)
    page_checks()
    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
