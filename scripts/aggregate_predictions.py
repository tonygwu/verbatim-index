#!/usr/bin/env python3
"""Descriptive statistics over the prediction corpus -> data/predictions/index.json.

Counts of what was said, per person and for the corpus: accepted predictions,
horizons, confidence types, categories, types, control, statement-date span,
verifier agreement, extraction coverage, and market-consensus status. No field
here measures whether anyone was right, and the test walks every key to make
sure none is named like it does. Someone with more transcripts has more
predictions; that is a fact about the corpus, not about foresight.

Counters are sorted dicts and the leader list is sorted by slug, so two runs
over the same tree are byte-identical. `files_read` and `records_read` are
counted before any filter so a deploy can check staleness against disk.

  .venv/bin/python scripts/aggregate_predictions.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402

FORBIDDEN_KEY_WORDS = ("accuracy", "accurate", "score", "rank", "resolved", "correct", "brier", "edge", "skill")


def _counter(items) -> dict:
    return dict(sorted(Counter(items).items()))


def summarise_records(recs: list[dict]) -> dict:
    acc = [r for r in recs if r["accepted"]]
    dates = sorted(r["source"]["statement_date"] for r in acc if r["source"]["statement_date"])
    cons = [r["consensus"].get("status", "not_searched") for r in acc]
    return {
        "candidates": len(recs),
        "accepted": len(acc),
        "rejected_by_verifier": sum(1 for r in recs if r["extraction"]["qualifies"] and r["verification"]["status"] == "ok" and not r["accepted"]),
        "verification_pending": sum(1 for r in recs if r["extraction"]["qualifies"] and r["verification"]["status"] == "not_run"),
        "extractor_disqualified": sum(1 for r in recs if not r["extraction"]["qualifies"]),
        "agreement_rate": _rate([r for r in recs if r["verification"]["agreement"] is not None], lambda r: r["verification"]["agreement"]),
        "by_horizon": _counter(r["prediction"]["horizon"] for r in acc),
        "by_confidence_type": _counter(r["confidence"]["type"] for r in acc),
        "by_category": _counter(r["prediction"]["category"] for r in acc),
        "by_prediction_type": _counter(r["prediction"]["prediction_type"] for r in acc),
        "by_subject_control": _counter(r["prediction"]["subject_control"] for r in acc),
        "by_specificity": _counter(r["prediction"]["specificity"] for r in acc),
        "with_target_date": sum(1 for r in acc if r["prediction"]["target_date"]),
        "explicit_probability": sum(1 for r in acc if r["confidence"]["type"] == "explicit_probability"),
        "qualitative_confidence": sum(1 for r in acc if r["confidence"]["type"] == "qualitative"),
        "earliest_statement_date": dates[0] if dates else None,
        "latest_statement_date": dates[-1] if dates else None,
        "statement_date_unknown": sum(1 for r in acc if not r["source"]["statement_date"]),
        "consensus_by_status": _counter(cons),
        "market_matched": sum(1 for c in cons if c == "matched"),
        "transcripts_with_accepted": len({r["transcript_id"] for r in acc}),
    }


def _rate(rows, fn) -> float | None:
    return round(sum(1 for r in rows if fn(r)) / len(rows), 4) if rows else None


def summarise_meta(metas: list[dict]) -> dict:
    ext = Counter((m.get("extract") or {}).get("status", "not_run") for m in metas)
    ver = Counter((m.get("verify") or {}).get("status", "not_run") for m in metas)
    by_h_ext = Counter((m.get("extract") or {}).get("harness") for m in metas if (m.get("extract") or {}).get("status") == "ok")
    by_h_ver = Counter((m.get("verify") or {}).get("harness") for m in metas if (m.get("verify") or {}).get("status") == "ok")
    return {
        "extract": dict(sorted(ext.items())),
        "verify": dict(sorted(ver.items())),
        "by_harness": {"extract": dict(sorted((k or "unknown", v) for k, v in by_h_ext.items())),
                       "verify": dict(sorted((k or "unknown", v) for k, v in by_h_ver.items()))},
        "cap_hit_transcripts": sum(1 for m in metas if (m.get("extract") or {}).get("cap_hit")),
        "ungrounded_candidates_total": sum(len((m.get("extract") or {}).get("ungrounded") or []) for m in metas),
        "dedupe_dropped_total": sum(len((m.get("extract") or {}).get("dedupe_dropped") or []) for m in metas),
    }


def build_index(pred_root: Path, roster: dict, transcripts_root: Path | None) -> dict:
    files = sorted(p for p in pred_root.glob("*/*.jsonl") if not p.parent.name.startswith("_"))
    all_recs: list[dict] = []
    per_slug: dict[str, list[dict]] = {}
    metas_per_slug: dict[str, list[dict]] = {}
    run_ids, contracts_x, contracts_v, contracts_m = set(), set(), set(), set()
    ext_models, ver_models = set(), set()
    records_read = 0
    for f in files:
        recs = L.parse_lines(f.read_text(), str(f))
        records_read += len(recs)
        slug = f.parent.name
        per_slug.setdefault(slug, []).extend(recs)
        all_recs.extend(recs)
        for r in recs:
            run_ids.add(r["extraction"]["run_id"])
            contracts_x.add(r["extraction"]["contract_id"])
            ext_models.add(r["extraction"]["served_model"] or r["extraction"]["requested_model"])
            if r["verification"]["status"] == "ok":
                run_ids.add(r["verification"]["run_id"])
                contracts_v.add(r["verification"]["contract_id"])
                ver_models.add(r["verification"]["served_model"] or r["verification"]["requested_model"])
            if r["consensus"].get("matcher"):
                contracts_m.add(r["consensus"]["matcher"]["contract_id"])
    metas = []
    for mp in sorted(p for p in pred_root.glob("*/*.meta.json") if not p.parent.name.startswith("_")):
        m = json.loads(mp.read_text())
        metas.append(m)
        metas_per_slug.setdefault(mp.parent.name, []).append(m)

    on_disk: dict[str, int] = {}
    if transcripts_root and transcripts_root.exists():
        for p in transcripts_root.glob("*/*.json"):
            on_disk[p.parent.name] = on_disk.get(p.parent.name, 0) + 1

    leaders = []
    for slug in sorted(set(roster) | set(per_slug) | set(metas_per_slug)):
        recs = per_slug.get(slug, [])
        ms = metas_per_slug.get(slug, [])
        entry = roster.get(slug, {})
        leaders.append({
            "slug": slug, "name": entry.get("name", slug), "company": entry.get("company"), "role": entry.get("role"),
            "sector": entry.get("sector"), "on_roster": slug in roster,
            "transcripts_on_disk": on_disk.get(slug, 0),
            "transcripts_extracted": sum(1 for m in ms if (m.get("extract") or {}).get("status") == "ok"),
            "transcripts_excluded": sum(1 for m in ms if (m.get("extract") or {}).get("status") == "excluded"),
            "transcripts_extract_failed": sum(1 for m in ms if (m.get("extract") or {}).get("status") == "failed"),
            "transcripts_verified": sum(1 for m in ms if (m.get("verify") or {}).get("status") in ("ok", "nothing_to_verify")),
            **summarise_records(recs),
            "cap_hit_transcripts": sum(1 for m in ms if (m.get("extract") or {}).get("cap_hit")),
        })

    corpus = {
        "transcripts_on_disk": sum(on_disk.values()),
        "transcripts_with_meta": len(metas),
        **summarise_records(all_recs),
        "extractor_models": sorted(m for m in ext_models if m),
        "verifier_models": sorted(m for m in ver_models if m),
    }
    return {
        "schema_version": L.SCHEMA_VERSION,
        "generated_at_utc": L.utc_now(),
        "predictions_root": str(pred_root),
        "files_read": len(files),
        "records_read": records_read,
        "run_ids_seen": sorted(run_ids),
        "contracts_seen": {"extraction": sorted(contracts_x), "verification": sorted(contracts_v), "matching": sorted(contracts_m)},
        "corpus": corpus,
        "coverage": summarise_meta(metas),
        "leaders": leaders,
    }


def walk_keys(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


def forbidden_keys(index: dict) -> list[str]:
    """Any key that reads like an evaluation of foresight. The test and main() both refuse it."""
    bad = []
    for path, k in walk_keys(index):
        kl = k.lower()
        if any(w in kl for w in FORBIDDEN_KEY_WORDS):
            bad.append(path)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", default="data/predictions")
    ap.add_argument("--roster", default="data/roster/final.json")
    ap.add_argument("--transcripts", default="data/transcripts_open")
    ap.add_argument("--out", default=None, help="default <predictions>/index.json")
    args = ap.parse_args(argv)
    pred_root = Path(args.predictions)
    if not pred_root.exists():
        print(f"no predictions tree at {pred_root}", file=sys.stderr)
        return 2
    roster = {r["slug"]: r for r in json.loads(Path(args.roster).read_text())["roster"]}
    index = build_index(pred_root, roster, Path(args.transcripts))
    bad = forbidden_keys(index)
    if bad:
        raise SystemExit(f"index carries evaluative keys, refusing to write: {bad[:5]}")
    out = Path(args.out) if args.out else pred_root / "index.json"
    L.write_prediction_file(out, json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    c = index["corpus"]
    print(f"files {index['files_read']}  records {index['records_read']}  accepted {c['accepted']}  "
          f"rejected_by_verifier {c['rejected_by_verifier']}  pending {c['verification_pending']}  "
          f"leaders {len(index['leaders'])}  consensus {c['consensus_by_status']}")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
