#!/usr/bin/env python3
"""Check every invariant of the prediction corpus, and fail loud naming file:line.

A record that a model wrote is not trusted until every mechanical claim in it
has been recomputed from the transcript: the quote is there at those offsets,
the id is the hash it says it is, the date came from the upload date, the
probability is only there when the speaker said a number, the derived
booleans are what the rule gives, and the Phase 2 blocks are still at their
sentinels or hold a market block whose observation precedes the cutoff.

Every failure prints as
  <file>:<line>: <invariant>: <detail>
and the summary counts per invariant. Exit 1 on any failure. A JSON report
goes to --report (default data/predictions/_eval/validate_<utc>.json).

  .venv/bin/python scripts/validate_predictions.py
  .venv/bin/python scripts/validate_predictions.py --predictions <tree> --transcripts <tree>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402

INVARIANTS = [
    "schema", "transcript_exists", "not_excluded", "quote_grounds", "quote_length", "timestamp_mark",
    "context_windows", "prediction_id", "near_duplicate", "sorted", "statement_date", "target_date",
    "confidence", "gates_and_qualifies", "verification_status", "sentinels", "provenance",
    "meta_consistency", "speaker", "consensus", "file",
]


class Failure(dict):
    pass


def fail(out: list, file: Path, line: int | None, inv: str, detail: str) -> None:
    assert inv in INVARIANTS, inv
    out.append(Failure(file=str(file), line=line, invariant=inv, detail=detail))


def known_contract_ids(pred_root: Path, skill_dir: Path = L.SKILL) -> set[str]:
    """Current contracts if the skill files exist, plus every id a run manifest recorded."""
    ids: set[str] = set()
    for fn in (L.extraction_contract, L.verification_contract, L.matching_contract):
        try:
            ids.add(fn(skill_dir)["contract_id"])
        except FileNotFoundError:
            pass
    for m in sorted((pred_root / "_runs").glob("*.json")):
        try:
            d = json.loads(m.read_text())
        except json.JSONDecodeError:
            continue
        for k in ("extraction_contract", "verification_contract", "matching_contract"):
            c = d.get(k) or {}
            if c.get("contract_id"):
                ids.add(c["contract_id"])
    return ids


def check_record(rec: dict, text: str, file: Path, n: int, exclusions: dict, schema: dict,
                 known: set[str], out: list) -> None:
    for e in L.check_schema(rec, schema):
        fail(out, file, n, "schema", e)
    if out and out[-1]["invariant"] == "schema" and out[-1]["line"] == n:
        # A record that fails the schema is not read further: every rule below
        # indexes fields the schema guarantees.
        return
    slug, sid = file.parent.name, file.name[: -len(".jsonl")]
    tid = f"{slug}/{sid}"
    if rec["transcript_id"] != tid or rec["leader_slug"] != slug or rec["source_id"] != sid:
        fail(out, file, n, "transcript_exists", f"record says {rec['transcript_id']} but the file is {tid}")
    if tid in exclusions:
        fail(out, file, n, "not_excluded", f"{tid} is excluded: {exclusions[tid]['reason']}")

    src = rec["source"]
    s, e = src["quote_char_start"], src["quote_char_end"]
    if not (0 <= s < e <= len(text)):
        fail(out, file, n, "quote_grounds", f"offsets {s}:{e} outside text of length {len(text)}")
    else:
        span = text[s:e]
        if span != src["quote_original"]:
            fail(out, file, n, "quote_grounds", "quote_original is not text[start:end]")
        if L.normalise(span) != L.normalise(src["quote"]):
            fail(out, file, n, "quote_grounds", "normalised quote differs from the normalised span")
        wc = L.quote_word_count(span)
        if wc != src["quote_word_count"]:
            fail(out, file, n, "quote_length", f"quote_word_count {src['quote_word_count']} != recount {wc}")
        if not (L.MIN_QUOTE_WORDS <= wc <= L.MAX_QUOTE_WORDS):
            fail(out, file, n, "quote_length", f"{wc} words outside {L.MIN_QUOTE_WORDS}..{L.MAX_QUOTE_WORDS}")
        if src["timestamp_mark"] != L.nearest_mark(text, s):
            fail(out, file, n, "timestamp_mark", f"{src['timestamp_mark']} != {L.nearest_mark(text, s)}")
        before, after = L.context_window(text, s, e)
        if (before, after) != (src["context_before"], src["context_after"]):
            fail(out, file, n, "context_windows", "context differs from the mechanical cut")
    want_id = L.prediction_id(tid, src["quote"])
    if rec["prediction_id"] != want_id:
        fail(out, file, n, "prediction_id", f"{rec['prediction_id']} != recomputed {want_id}")

    # dates
    sd, basis = src["statement_date"], src["statement_date_basis"]
    if (sd is None) != (basis == "unknown"):
        fail(out, file, n, "statement_date", f"statement_date {sd!r} with basis {basis!r}")
    if sd is not None and not L.target_date_valid(sd) or (sd is not None and len(sd) != 10):
        fail(out, file, n, "statement_date", f"{sd!r} is not YYYY-MM-DD")
    p = rec["prediction"]
    if not L.target_date_valid(p["target_date"]):
        fail(out, file, n, "target_date", f"{p['target_date']!r} is not YYYY, YYYY-MM or YYYY-MM-DD")
    if p["horizon"] == "explicit" and not p["target_date_text"]:
        fail(out, file, n, "target_date", "explicit horizon without target_date_text")
    if p["horizon"] != "inferable" and p["horizon_years_inferred"] is not None:
        fail(out, file, n, "target_date", "horizon_years_inferred set on a non-inferable horizon")

    # confidence
    c = rec["confidence"]
    if (c["probability"] is not None) != (c["type"] == "explicit_probability"):
        fail(out, file, n, "confidence", f"probability {c['probability']!r} with type {c['type']}")
    if c["type"] == "explicit_probability" and not L.probability_language_ok(c["verbatim_confidence_language"]):
        fail(out, file, n, "confidence", "explicit_probability without a number in the language")
    if (c["verbatim_confidence_language"] is None) != (c["type"] == "none"):
        fail(out, file, n, "confidence", f"language {c['verbatim_confidence_language']!r} with type {c['type']}")
    if c["verbatim_confidence_language"] and L.normalise(c["verbatim_confidence_language"]) not in L.normalise(src["quote"]):
        fail(out, file, n, "confidence", "confidence language is not inside the quote")

    # derived booleans
    ex, v = rec["extraction"], rec["verification"]
    if ex["qualifies"] != L.extraction_qualifies(ex["gates"], p["resolution_criteria"]):
        fail(out, file, n, "gates_and_qualifies", "extraction.qualifies is not the rule's value")
    vq = L.verification_qualifies(v)
    if v["qualifies"] != vq:
        fail(out, file, n, "gates_and_qualifies", f"verification.qualifies {v['qualifies']!r} != recomputed {vq!r}")
    want_agree = (ex["qualifies"] == vq) if vq is not None else None
    if v["agreement"] != want_agree:
        fail(out, file, n, "gates_and_qualifies", f"agreement {v['agreement']!r} != {want_agree!r}")
    if rec["accepted"] != L.compute_accepted(rec):
        fail(out, file, n, "gates_and_qualifies", "accepted is not extraction.qualifies and verification.qualifies")
    nullable = [k for k in v if k != "status"]
    if v["status"] != "ok":
        wrong = [k for k in nullable if v[k] is not None]
        if wrong:
            fail(out, file, n, "verification_status", f"status {v['status']} but non-null {wrong}")
    else:
        wrong = [k for k in nullable if v[k] is None and k not in ("notes", "account", "router_account_id", "served_model")]
        if wrong:
            fail(out, file, n, "verification_status", f"status ok but null {wrong}")

    # sentinels and Phase 2 blocks
    if rec["status"] != "pending" or rec["resolution"] != L.SENTINEL_RESOLUTION:
        fail(out, file, n, "sentinels", "status or resolution left the V0 sentinel")
    cons = rec["consensus"]
    if cons != L.SENTINEL_CONSENSUS:
        check_consensus(cons, rec, file, n, out)

    # provenance
    if ex["harness"] not in L.HARNESSES:
        fail(out, file, n, "provenance", f"harness {ex['harness']!r}")
    if (ex["harness"] == "astra") != (ex["served_model_verified"] is False):
        fail(out, file, n, "provenance", "served_model_verified must be false exactly for astra")
    if ex["contract_id"] not in known:
        fail(out, file, n, "provenance", f"extraction contract {ex['contract_id']} is not a known contract")
    if v["status"] == "ok":
        if v["harness"] == ex["harness"]:
            fail(out, file, n, "provenance", f"verifier used the extractor's harness {v['harness']}")
        if (v["harness"] == "astra") != (v["served_model_verified"] is False):
            fail(out, file, n, "provenance", "verification served_model_verified must be false exactly for astra")
        if v["contract_id"] not in known:
            fail(out, file, n, "provenance", f"verification contract {v['contract_id']} is not a known contract")
    if rec["speaker"]["slug"] != rec["leader_slug"]:
        fail(out, file, n, "speaker", f"speaker.slug {rec['speaker']['slug']} != {rec['leader_slug']}")


def check_consensus(cons: dict, rec: dict, file: Path, n: int, out: list) -> None:
    st = cons["status"]
    cut = cons["cutoff"]
    want_cut = L.publication_cutoff(rec)
    if cut["basis"] != want_cut["basis"] or cut["requested_cutoff_utc"] != want_cut["requested_cutoff_utc"] \
            or cut["precision"] != want_cut["precision"]:
        fail(out, file, n, "consensus", f"cutoff {cut} != rule {want_cut}")
    if (cons["market_probability"] is not None) != (st == "matched"):
        fail(out, file, n, "consensus", f"market_probability {cons['market_probability']!r} with status {st}")
    if st == "matched":
        em = cons["exact_match"]
        if not em or not em.get("observation"):
            fail(out, file, n, "consensus", "matched without an exact match observation")
        elif cons["market_probability"] != em["observation"]["probability_for_claim"]:
            fail(out, file, n, "consensus", "market_probability differs from the exact match's probability_for_claim")
    if st == "no_match" and (cons["exact_match"] is not None or cons["proxy_matches"]):
        fail(out, file, n, "consensus", "no_match with matches present")
    if cons["exact_match"] is not None and cons["exact_match"]["match_type"] != "exact":
        fail(out, file, n, "consensus", "exact_match slot holds a non-exact match")
    for pm in cons["proxy_matches"]:
        if pm["match_type"] != "proxy":
            fail(out, file, n, "consensus", "proxy_matches holds a non-proxy match")
    matches = ([cons["exact_match"]] if cons["exact_match"] else []) + list(cons["proxy_matches"])
    for m in matches:
        ob = m.get("observation")
        if not ob:
            continue
        if cut["requested_cutoff_utc"] is None:
            fail(out, file, n, "consensus", "an observation exists without a cutoff")
            continue
        if not (L.parse_utc(ob["observed_at_utc"]) < L.parse_utc(cut["requested_cutoff_utc"])):
            fail(out, file, n, "consensus", f"observation {ob['observed_at_utc']} is not strictly before cutoff {cut['requested_cutoff_utc']}")
        want_stale = int((L.parse_utc(cut["requested_cutoff_utc"]) - L.parse_utc(ob["observed_at_utc"])).total_seconds())
        if ob["staleness_sec"] != want_stale:
            fail(out, file, n, "consensus", f"staleness_sec {ob['staleness_sec']} != {want_stale}")
        want_p = round(1 - ob["probability_yes"], 6) if m["direction"] == "inverse" else ob["probability_yes"]
        if abs(ob["probability_for_claim"] - want_p) > 1e-6:
            fail(out, file, n, "consensus", f"probability_for_claim {ob['probability_for_claim']} != {want_p} for direction {m['direction']}")


def validate_tree(pred_root: Path, transcripts_root: Path, exclusions: dict, schema: dict,
                  known: set[str]) -> tuple[list[Failure], dict]:
    out: list[Failure] = []
    seen_ids: dict[str, str] = {}
    files = sorted(p for p in pred_root.glob("*/*.jsonl") if not p.parent.name.startswith("_"))
    counts = {"files": len(files), "records": 0, "accepted": 0}
    for file in files:
        slug, sid = file.parent.name, file.name[: -len(".jsonl")]
        tpath = transcripts_root / slug / f"{sid}.json"
        if not tpath.exists():
            fail(out, file, None, "transcript_exists", f"no transcript at {tpath}")
            continue
        text = json.loads(tpath.read_text())["text"]
        raw = file.read_text()
        try:
            recs = L.parse_lines(raw, str(file))
        except L.PredictionError as exc:
            fail(out, file, None, "file", str(exc))
            continue
        counts["records"] += len(recs)
        if raw != L.serialise_lines(recs) and recs:
            fail(out, file, None, "sorted", "file is not the sorted, sort_keys serialisation of its records")
        spans = []
        for n, rec in enumerate(recs, 1):
            check_record(rec, text, file, n, exclusions, schema, known, out)
            pid = rec.get("prediction_id")
            if pid in seen_ids:
                fail(out, file, n, "prediction_id", f"duplicate id {pid}, first seen in {seen_ids[pid]}")
            elif isinstance(pid, str):
                seen_ids[pid] = f"{file}:{n}"
            if isinstance(rec.get("source"), dict) and isinstance(rec["source"].get("quote_char_start"), int):
                spans.append((rec["source"]["quote_char_start"], rec["source"]["quote_char_end"], n))
            if rec.get("accepted") is True:
                counts["accepted"] += 1
        spans.sort()
        for i, (s1, e1, n1) in enumerate(spans):
            for s2, e2, n2 in spans[i + 1:]:
                if s2 >= e1:
                    break
                share = L.span_overlap({"start": s1, "end": e1}, {"start": s2, "end": e2})
                if share >= L.DEDUPE_OVERLAP:
                    fail(out, file, n2, "near_duplicate", f"shares {share:.2f} of line {n1}'s span ({s1}:{e1} vs {s2}:{e2})")
        meta_path = file.with_name(f"{sid}.meta.json")
        if not meta_path.exists():
            fail(out, file, None, "meta_consistency", "no .meta.json beside the predictions file")
        else:
            meta = json.loads(meta_path.read_text())
            ext = meta.get("extract") or {}
            if ext.get("status") == "ok" and ext.get("candidates_written") != len(recs):
                fail(out, file, None, "meta_consistency", f"meta candidates_written {ext.get('candidates_written')} != {len(recs)} lines")
            ver = meta.get("verify") or {}
            if ver.get("status") == "ok":
                acc = sum(1 for r in recs if r.get("accepted") is True)
                if ver.get("accepted") != acc:
                    fail(out, file, None, "meta_consistency", f"meta verify.accepted {ver.get('accepted')} != {acc} accepted lines")
    return out, counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", default="data/predictions")
    ap.add_argument("--transcripts", default="data/transcripts_open")
    ap.add_argument("--exclude", default=str(L.REPO / "scripts" / "predictions_exclusions.json"))
    ap.add_argument("--skill-dir", default=str(L.SKILL))
    ap.add_argument("--report", default=None, help="JSON report path; default <predictions>/_eval/validate_<utc>.json")
    args = ap.parse_args()

    pred_root = Path(args.predictions)
    if not pred_root.exists():
        print(f"no predictions tree at {pred_root}", file=sys.stderr)
        return 2
    exclusions = L.load_exclusions(args.exclude) if args.exclude else {}
    schema = L.load_record_schema(Path(args.skill_dir))
    known = known_contract_ids(pred_root, Path(args.skill_dir))
    failures, counts = validate_tree(pred_root, Path(args.transcripts), exclusions, schema, known)

    for f in failures:
        where = f"{f['file']}:{f['line']}" if f["line"] is not None else f["file"]
        print(f"{where}: {f['invariant']}: {f['detail']}")
    by_inv = Counter(f["invariant"] for f in failures)
    print(f"\nfiles {counts['files']}  records {counts['records']}  accepted {counts['accepted']}  "
          f"known_contracts {len(known)}")
    for inv in INVARIANTS:
        print(f"  {inv:<20} {'FAIL ' + str(by_inv[inv]) if by_inv[inv] else 'ok'}")
    report = {"validated_at_utc": L.utc_now(), "predictions": str(pred_root), "counts": counts,
              "failures_by_invariant": dict(by_inv), "failures": failures[:500], "known_contracts": sorted(known)}
    rpath = Path(args.report) if args.report else pred_root / "_eval" / f"validate_{report['validated_at_utc'].replace(':', '')}.json"
    L.write_prediction_file(rpath, json.dumps(report, indent=1, sort_keys=True))
    print(f"report: {rpath}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
