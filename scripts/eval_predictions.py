#!/usr/bin/env python3
"""Golden eval of prediction extraction against the synthetic fixtures.

Scores an extraction tree produced from scripts/fixtures/predictions against
the gold labels there. Every metric prints its value, its threshold and a
verdict, in the style of validate_grader.py, and a JSON report is written.

Two modes:
  --scored DIR          score a tree already on disk (no model call, no quota)
  --out DIR             run the real driver on the fixtures first (both stages),
                        then score. Costs about eight model calls. Refused
                        unless PREDICT_LIVE=1, so a test run cannot spend quota
                        by accident. --out must be OUTSIDE data/ (the fixtures
                        are not corpus records) or under data/predictions/_eval.

A written candidate matches a gold positive when the character ranges overlap
by at least half of the gold span. Precision is the hard gate; recall is
reported and gated loosely because V0 is precision-first.

  PREDICT_LIVE=1 .venv/bin/python scripts/eval_predictions.py --out /tmp/pred-eval
  .venv/bin/python scripts/eval_predictions.py --scored /tmp/pred-eval
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402

FIXTURES = L.REPO / "scripts" / "fixtures" / "predictions"
PROBE_FAILURE_MODES = ("confident_grammar_no_test", "present_tense_vision", "hedged", "dangling_quote")
THRESHOLDS = {
    "precision": 0.85, "recall": 0.60, "attribution_correctness": 1.0, "quote_fidelity": 1.0,
    "claim_fidelity": 0.90, "horizon_correctness": 0.90, "confidence_type_correctness": 0.90,
    "probability_exactness": 1.0, "schema_valid": 1.0,
}
OVERLAP_MIN = 0.5


def overlap_share(a: tuple[int, int], gold: tuple[int, int]) -> float:
    lo, hi = max(a[0], gold[0]), min(a[1], gold[1])
    return max(0, hi - lo) / max(1, gold[1] - gold[0])


def score_tree(scored: Path, fixtures: Path = FIXTURES) -> dict:
    gold_files = sorted(fixtures.glob("gold/*/*.json"))
    per_transcript = []
    tot = Counter()
    adversarial: Counter = Counter()
    adversarial_seen: Counter = Counter()
    matched_pairs: list[tuple[dict, dict]] = []
    all_records: list[dict] = []
    for gf in gold_files:
        slug, sid = gf.parent.name, gf.stem
        gold = json.loads(gf.read_text())
        jl = scored / slug / f"{sid}.jsonl"
        meta_path = scored / slug / f"{sid}.meta.json"
        recs = L.parse_lines(jl.read_text(), str(jl)) if jl.exists() else []
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        all_records.extend(recs)
        accepted = [r for r in recs if r["accepted"]]
        qualifying = [r for r in recs if r["extraction"]["qualifies"]]
        spans = {id(r): (r["source"]["quote_char_start"], r["source"]["quote_char_end"]) for r in recs}
        row = {"transcript": f"{slug}/{sid}", "extract_status": (meta.get("extract") or {}).get("status"),
               "verify_status": (meta.get("verify") or {}).get("status"), "candidates": len(recs),
               "qualifying": len(qualifying), "accepted": len(accepted), "gold_positives": len(gold["positives"]),
               "matched": [], "unmatched_gold": [], "false_positives": [], "adversarial_hits": []}
        gold_hit = set()
        for r in accepted:
            best, best_share = None, 0.0
            for g in gold["positives"]:
                sh = overlap_share(spans[id(r)], (g["char_start"], g["char_end"]))
                if sh >= OVERLAP_MIN and sh > best_share:
                    best, best_share = g, sh
            if best is None:
                row["false_positives"].append({"quote": r["source"]["quote_original"], "prediction_id": r["prediction_id"]})
                for n in gold["negatives"]:
                    if overlap_share(spans[id(r)], (n["char_start"], n["char_end"])) >= OVERLAP_MIN:
                        adversarial[n["reason"]] += 1
                        row["adversarial_hits"].append({"reason": n["reason"], "quote": r["source"]["quote_original"]})
            else:
                gold_hit.add(best["gold_id"])
                matched_pairs.append((r, best))
                row["matched"].append(best["gold_id"])
        for n in gold["negatives"]:
            adversarial_seen[n["reason"]] += 1
        row["unmatched_gold"] = [g["gold_id"] for g in gold["positives"] if g["gold_id"] not in gold_hit]
        # Extractor-only view, so a verifier that rejects everything is visible as such.
        row["extractor_matched"] = sum(1 for r in qualifying if any(
            overlap_share(spans[id(r)], (g["char_start"], g["char_end"])) >= OVERLAP_MIN for g in gold["positives"]))
        row["dedupe_dropped"] = len((meta.get("extract") or {}).get("dedupe_dropped") or [])
        row["ungrounded"] = len((meta.get("extract") or {}).get("ungrounded") or [])
        per_transcript.append(row)
        tot["accepted"] += len(accepted)
        tot["qualifying"] += len(qualifying)
        tot["gold"] += len(gold["positives"])
        tot["matched"] += len(row["matched"])
        tot["extractor_matched"] += row["extractor_matched"]
        tot["false_positives"] += len(row["false_positives"])
        tot["dedupe_dropped"] += row["dedupe_dropped"]
        tot["ungrounded"] += row["ungrounded"]
        tot["candidates"] += len(recs)

    def rate(num, den):
        return round(num / den, 4) if den else None

    # Field-level fidelity on matched accepted records.
    fid = Counter()
    for r, g in matched_pairs:
        claim = r["prediction"]["normalized_claim"].lower()
        fid["claim_ok"] += all(tok.lower() in claim for tok in g["must_contain"])
        fid["horizon_ok"] += r["prediction"]["horizon"] == g["horizon"]
        fid["ctype_ok"] += r["confidence"]["type"] == g["confidence_type"]
        if g["confidence_type"] == "explicit_probability":
            fid["prob_n"] += 1
            fid["prob_ok"] += r["confidence"]["probability"] == g["probability"]
        fid["attr_ok"] += r["verification"]["attribution"] == "subject"
    n_m = len(matched_pairs)

    # Schema and grounding validity through the validator itself.
    from validate_predictions import known_contract_ids, validate_tree  # noqa: E402
    failures, _ = validate_tree(scored, fixtures / "transcripts", {}, L.load_record_schema(), known_contract_ids(scored))
    quote_failures = [f for f in failures if f["invariant"] in ("quote_grounds", "quote_length", "timestamp_mark", "context_windows")]

    agreement = [r["verification"]["agreement"] for r in all_records if r["verification"]["agreement"] is not None]
    gate_disagree = Counter()
    for r in all_records:
        v = r["verification"]
        if v["status"] == "ok" and v["gates"]:
            for gname in L.GATES:
                if r["extraction"]["gates"][gname] != v["gates"][gname]:
                    gate_disagree[gname] += 1

    metrics = {
        "precision": rate(tot["matched"], tot["accepted"]),
        "recall": rate(tot["matched"], tot["gold"]),
        "extractor_precision": rate(tot["extractor_matched"], tot["qualifying"]),
        "extractor_recall": rate(tot["extractor_matched"], tot["gold"]),
        "attribution_correctness": rate(fid["attr_ok"], n_m),
        "quote_fidelity": 1.0 if not quote_failures and tot["candidates"] else (0.0 if tot["candidates"] else None),
        "claim_fidelity": rate(fid["claim_ok"], n_m),
        "horizon_correctness": rate(fid["horizon_ok"], n_m),
        "confidence_type_correctness": rate(fid["ctype_ok"], n_m),
        "probability_exactness": rate(fid["prob_ok"], fid["prob_n"]),
        "duplicate_rate": rate(tot["dedupe_dropped"], tot["candidates"] + tot["dedupe_dropped"]),
        "ungrounded_rate": rate(tot["ungrounded"], tot["candidates"] + tot["ungrounded"]),
        "schema_valid": 1.0 if not failures else 0.0,
        "verifier_agreement_rate": rate(sum(1 for a in agreement if a), len(agreement)),
    }
    return {"metrics": metrics, "totals": dict(tot), "adversarial": {k: {"seen": adversarial_seen[k], "accepted": adversarial[k]} for k in sorted(adversarial_seen)},
            "gate_disagreements": dict(sorted(gate_disagree.items())), "validator_failures": [dict(f) for f in failures[:50]],
            "per_transcript": per_transcript, "matched_pairs": n_m}


def verdicts(report: dict) -> list[tuple[str, str, bool | None]]:
    out = []
    m = report["metrics"]
    for name, thr in THRESHOLDS.items():
        v = m.get(name)
        if v is None:
            out.append((name, f"n/a (no data)  threshold {thr}", None))
        else:
            out.append((name, f"{v:.3f}  threshold {thr}", v >= thr))
    adv = report["adversarial"]
    for mode in PROBE_FAILURE_MODES:
        a = adv.get(mode, {"seen": 0, "accepted": 0})
        out.append((f"adversarial:{mode}", f"accepted {a['accepted']} of {a['seen']} seen  threshold 0", a["accepted"] == 0 if a["seen"] else None))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", default=str(FIXTURES))
    ap.add_argument("--scored", default=None, help="score this tree; no model call")
    ap.add_argument("--out", default=None, help="run the driver on the fixtures into this tree, then score (PREDICT_LIVE=1)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--report", default=None)
    ap.add_argument("--extractor", default="auto")
    ap.add_argument("--verifier", default="auto")
    args = ap.parse_args(argv)
    fixtures = Path(args.fixtures)
    if bool(args.scored) == bool(args.out):
        raise SystemExit("give exactly one of --scored DIR or --out DIR")
    if args.out:
        if os.environ.get("PREDICT_LIVE") != "1":
            raise SystemExit("refusing to call a model: set PREDICT_LIVE=1 to run the driver on the fixtures (costs quota)")
        out = Path(args.out).resolve()
        root = L.data_root()
        if (out == root or root in out.parents) and not (root / "predictions" / "_eval") in (out, *out.parents):
            raise SystemExit(f"--out must be outside data/ or under {root / 'predictions' / '_eval'}: fixtures are not corpus records")
        from extract_predictions import main as drive
        rc = drive(["--transcripts", str(fixtures / "transcripts"), "--roster", str(fixtures / "roster.json"),
                    "--out", str(out), "--stage", "both", "--no-exclude", "--workers", str(args.workers),
                    "--extractor", args.extractor, "--verifier", args.verifier])
        print(f"driver exit {rc}")
        scored = out
    else:
        scored = Path(args.scored)
    report = score_tree(scored, fixtures)
    report["scored"] = str(scored)
    report["evaluated_at_utc"] = L.utc_now()
    lines = verdicts(report)
    hard_fail = False
    for name, text, ok in lines:
        tag = "PASS" if ok else ("n/a " if ok is None else "FAIL")
        print(f"  [{tag}] {name:<36} {text}")
        if ok is False and (name in ("precision", "quote_fidelity", "schema_valid", "attribution_correctness") or name.startswith("adversarial:")):
            hard_fail = True
    t = report["totals"]
    print(f"\ncandidates {t['candidates']}  qualifying {t['qualifying']}  accepted {t['accepted']}  matched {t['matched']}  "
          f"gold {t['gold']}  false_positives {t['false_positives']}  ungrounded {t['ungrounded']}")
    for row in report["per_transcript"]:
        print(f"  {row['transcript']:<32} extract {row['extract_status']!s:<8} verify {row['verify_status']!s:<18} "
              f"accepted {row['accepted']}/{row['gold_positives']}  missed {row['unmatched_gold']}  fp {len(row['false_positives'])}")
    if report["adversarial"]:
        print("adversarial (accepted/seen): " + ", ".join(f"{k} {v['accepted']}/{v['seen']}" for k, v in report["adversarial"].items()))
    rpath = Path(args.report) if args.report else scored / "_eval_report.json"
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False))
    print(f"report: {rpath}")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
