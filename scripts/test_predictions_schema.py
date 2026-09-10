#!/usr/bin/env python3
"""The validator must name every defect it exists to catch, by file and line.

Builds a valid fixture tree (one transcript, two records, a meta file and a
run manifest), confirms the validator passes it, then breaks exactly one thing
at a time and asserts the validator reports THAT invariant on THAT line. A
validator that passes a poisoned record is the failure this file exists to
prevent, so every mutation is also checked to be visible: a mutation the
validator misses fails the test by name.

  CLEAN     a valid tree validates with exit 0
  MUTATE    one defect per invariant is named with file:line
  CONSENSUS the sentinel and a full market block both validate; three market defects are caught
  CLI       the script exits 1 on a defect, 0 on a clean tree, 2 on a missing tree, and writes a report

  .venv/bin/python scripts/test_predictions_schema.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEXT = ("[00:00:01] thanks for having me so where is this all going [00:01:00] I think by 2030 most code "
        "will be written by AI, honestly, and I would put a 70% chance on that. [Music] people don't get it. "
        "[00:02:00] and separately we will have a hundred billion in revenue this year, that is just the math.")

CONTRACT_X = "aaaaaaaaaaaa"
CONTRACT_V = "bbbbbbbbbbbb"


def build_tree(td: Path, L) -> tuple[Path, Path, list[dict]]:
    tx = td / "transcripts"
    pr = td / "predictions"
    rec = {"leader_slug": "ada", "source_id": "s1", "text": TEXT, "yt_upload_date": "20250301", "url": "https://youtu.be/v",
           "video_id": "v", "yt_title": "Ada on code", "declared_venue": "Pod", "declared_kind": "podcast",
           "word_count": 60, "duration_sec": 180}
    (tx / "ada").mkdir(parents=True)
    (tx / "ada" / "s1.json").write_text(json.dumps(rec))
    roster = {"name": "Ada L", "role": "CEO", "company": "Co"}
    gates = {g: True for g in L.GATES}
    prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}, "default", "claude")
    c1 = {"quote": "by 2030 most code will be written by AI, honestly, and I would put a 70% chance on that",
          "gates": gates, "gate_notes": "", "resolution_criteria": "By 2030-12-31, more than half of new code is AI-written per a major survey",
          "normalized_claim": "By 2030 most code will be written by AI.", "category": "ai_capability",
          "prediction_type": "milestone", "target_date": "2030", "target_date_text": "by 2030", "horizon": "explicit",
          "horizon_years_inferred": None, "horizon_evidence": None, "specificity": "high", "subject_control": "external",
          "confidence": {"type": "explicit_probability", "probability": 0.7, "verbatim_confidence_language": "70% chance"}}
    c2 = {"quote": "we will have a hundred billion in revenue this year, that is just the math",
          "gates": gates, "gate_notes": "", "resolution_criteria": "By fiscal year end 2025, reported revenue >= 100 billion",
          "normalized_claim": "Co will report 100 billion revenue in 2025.", "category": "company_business",
          "prediction_type": "numeric", "target_date": "2025", "target_date_text": "this year", "horizon": "inferable",
          "horizon_years_inferred": 0.8, "horizon_evidence": "this year", "specificity": "high", "subject_control": "own",
          "confidence": {"type": "none", "probability": None, "verbatim_confidence_language": None}}
    recs = []
    for c in (c1, c2):
        loc = L.locate_quote(TEXT, c["quote"])
        assert "start" in loc, loc
        r = L.make_record(rec, roster, c, loc, prov, CONTRACT_X, "run-x", "2026-09-10T00:00:00Z", {})
        recs.append(r)
    # Verify the first, leave the second not_run.
    v = recs[0]["verification"]
    v.update({"status": "ok", "harness": "astra", "requested_model": "gpt-6-astra", "served_model": "gpt-6-astra",
              "served_model_verified": False, "account": "codex", "router_account_id": "codex", "contract_id": CONTRACT_V,
              "run_id": "run-v", "verified_at_utc": "2026-09-10T01:00:00Z", "gates": dict(gates), "attribution": "subject",
              "claim_faithful": True, "qualifies_stated": True, "verifier_resolution_criteria": "By end of 2030 ...",
              "notes": None, "telemetry": {}})
    v["qualifies"] = L.verification_qualifies(v)
    v["agreement"] = recs[0]["extraction"]["qualifies"] == v["qualifies"]
    recs[0]["accepted"] = L.compute_accepted(recs[0])
    write_tree(pr, recs, L)
    return pr, tx, recs


def write_tree(pr: Path, recs: list[dict], L, meta: dict | None = None) -> None:
    (pr / "ada").mkdir(parents=True, exist_ok=True)
    (pr / "ada" / "s1.jsonl").write_text(L.serialise_lines(recs))
    acc = sum(1 for r in recs if r["accepted"])
    meta = meta or {"schema_version": 1, "transcript_id": "ada/s1",
                    "extract": {"status": "ok", "candidates_written": len(recs)},
                    "verify": {"status": "ok", "accepted": acc}}
    (pr / "ada" / "s1.meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    (pr / "_runs").mkdir(exist_ok=True)
    (pr / "_runs" / "run-x.json").write_text(json.dumps({"extraction_contract": {"contract_id": CONTRACT_X},
                                                          "verification_contract": {"contract_id": CONTRACT_V}}))


def run_validator(V, L, pr: Path, tx: Path):
    schema = L.load_record_schema()
    known = V.known_contract_ids(pr)
    return V.validate_tree(pr, tx, {}, schema, known)


def test_clean_and_mutations(V, L) -> None:
    with tempfile.TemporaryDirectory() as td:
        pr, tx, recs = build_tree(Path(td), L)
        failures, counts = run_validator(V, L, pr, tx)
        check("CLEAN: a valid tree has no failures", not failures, "; ".join(f"{f['invariant']}: {f['detail']}" for f in failures[:5]))
        check("CLEAN: counts are files 1, records 2, accepted 1",
              (counts["files"], counts["records"], counts["accepted"]) == (1, 2, 1), str(counts))

        def mut(name: str, inv: str, line: int | None, fn) -> None:
            rs = copy.deepcopy(recs)
            fn(rs)
            write_tree(pr, rs, L)
            fails, _ = run_validator(V, L, pr, tx)
            hit = [f for f in fails if f["invariant"] == inv and f["line"] == line]
            check(f"MUTATE: {name} -> {inv} at line {line}", bool(hit),
                  "got: " + "; ".join(f"{f['invariant']}@{f['line']}: {f['detail']}" for f in fails[:4]) or "no failures")

        def set_src(k, val):
            return lambda rs: rs[0]["source"].__setitem__(k, val)

        mut("extra property", "schema", 1, lambda rs: rs[0].__setitem__("bogus", 1))
        mut("bad enum", "schema", 1, lambda rs: rs[0]["prediction"].__setitem__("category", "sports"))
        mut("wrong transcript_id", "transcript_exists", 2, lambda rs: rs[1].__setitem__("transcript_id", "ada/other"))
        mut("quote_original edited", "quote_grounds", 1, set_src("quote_original", "by 2030 most code will be written by AI honestly and I would put a 70% chance on that"))
        mut("quote paraphrased", "quote_grounds", 1, set_src("quote", "by 2030 most code will be written by machines"))
        mut("offsets shifted", "quote_grounds", 2, lambda rs: (rs[1]["source"].__setitem__("quote_char_start", rs[1]["source"]["quote_char_start"] + 1)))
        mut("word count wrong", "quote_length", 1, set_src("quote_word_count", 3))
        mut("timestamp mark wrong", "timestamp_mark", 2, set_src("timestamp_mark", "[00:00:01]") if False else (lambda rs: rs[1]["source"].__setitem__("timestamp_mark", "[00:00:01]")))
        mut("context edited", "context_windows", 1, set_src("context_before", "nothing"))
        mut("id tampered", "prediction_id", 1, lambda rs: rs[0].__setitem__("prediction_id", "0000000000000000"))
        mut("duplicate id", "prediction_id", 2, lambda rs: rs[1].__setitem__("prediction_id", rs[0]["prediction_id"]))
        mut("near-duplicate spans", "near_duplicate", 2, lambda rs: (rs[1]["source"].__setitem__("quote_char_start", rs[0]["source"]["quote_char_start"] + 2),
                                                                     rs[1]["source"].__setitem__("quote_char_end", rs[0]["source"]["quote_char_end"] + 2)))
        mut("statement_date without basis", "statement_date", 1, set_src("statement_date_basis", "unknown"))
        mut("target_date malformed", "target_date", 1, lambda rs: rs[0]["prediction"].__setitem__("target_date", "2030-13"))
        mut("explicit horizon without text", "target_date", 1, lambda rs: rs[0]["prediction"].__setitem__("target_date_text", None))
        mut("probability without number", "confidence", 1, lambda rs: rs[0]["confidence"].__setitem__("verbatim_confidence_language", "very likely"))
        mut("probability on qualitative", "confidence", 1, lambda rs: rs[0]["confidence"].__setitem__("type", "qualitative"))
        mut("language outside the quote", "confidence", 1, lambda rs: rs[0]["confidence"].__setitem__("verbatim_confidence_language", "90% chance"))
        mut("qualifies flipped", "gates_and_qualifies", 2, lambda rs: rs[1]["extraction"].__setitem__("qualifies", False))
        mut("accepted flipped", "gates_and_qualifies", 2, lambda rs: rs[1].__setitem__("accepted", True))
        mut("verification qualifies flipped", "gates_and_qualifies", 1, lambda rs: rs[0]["verification"].__setitem__("qualifies", False))
        mut("not_run with a model set", "verification_status", 2, lambda rs: rs[1]["verification"].__setitem__("requested_model", "x"))
        mut("astra marked verified", "provenance", 1, lambda rs: rs[0]["verification"].__setitem__("served_model_verified", True))
        mut("unknown contract", "provenance", 1, lambda rs: rs[0]["extraction"].__setitem__("contract_id", "cccccccccccc"))
        mut("verifier on the extractor's harness", "provenance", 1, lambda rs: rs[0]["verification"].update({"harness": "fable", "served_model_verified": True}))
        mut("speaker slug", "speaker", 1, lambda rs: rs[0]["speaker"].__setitem__("slug", "someone-else"))

        # The sentinels are consts in the schema, so a change is caught by the walker:
        rs = copy.deepcopy(recs); rs[0]["status"] = "resolved"; write_tree(pr, rs, L)
        fails, _ = run_validator(V, L, pr, tx)
        check("MUTATE: status resolved -> schema at line 1", any(f["invariant"] == "schema" and f["line"] == 1 for f in fails))

        # File-level defects.
        write_tree(pr, recs, L)
        (pr / "ada" / "s1.jsonl").write_text("".join(L.serialise_line(r) + "\n" for r in reversed(recs)))
        fails, _ = run_validator(V, L, pr, tx)
        check("MUTATE: unsorted file -> sorted", any(f["invariant"] == "sorted" for f in fails))
        write_tree(pr, recs, L)
        (pr / "ada" / "s1.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 5}, "verify": {"status": "ok", "accepted": 1}}))
        fails, _ = run_validator(V, L, pr, tx)
        check("MUTATE: meta count wrong -> meta_consistency", any(f["invariant"] == "meta_consistency" for f in fails))
        write_tree(pr, recs, L)
        excl = {"ada/s1": {"transcript_id": "ada/s1", "reason": "wrong_person", "evidence": "x"}}
        fails, _ = V.validate_tree(pr, tx, excl, L.load_record_schema(), V.known_contract_ids(pr))
        check("MUTATE: excluded transcript -> not_excluded", any(f["invariant"] == "not_excluded" for f in fails))
        (tx / "ada" / "s1.json").unlink()
        fails, _ = run_validator(V, L, pr, tx)
        check("MUTATE: missing transcript -> transcript_exists", any(f["invariant"] == "transcript_exists" for f in fails))


def full_consensus(rec: dict, observed: str, direction: str = "same", p_yes: float = 0.27, status: str = "matched") -> dict:
    p_claim = round(1 - p_yes, 6) if direction == "inverse" else p_yes
    cutoff = "2025-03-01T00:00:00Z"
    from datetime import datetime, timezone
    stale = int((datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(observed, "%Y-%m-%dT%H:%M:%SZ")).total_seconds())
    match = {"platform": "polymarket", "market_id": "514502", "market_slug": "will-gpt-5-be-released-by-march-31",
             "market_url": "https://polymarket.com/market/will-gpt-5-be-released-by-march-31", "question": "Will GPT-5 be released by March 31?",
             "resolution_text": "Resolves Yes if ...", "market_open_utc": "2024-12-23T17:26:41Z", "market_close_utc": "2025-03-31T12:00:00Z",
             "match_type": "exact", "match_confidence": "high", "direction": direction, "rationale": "same proposition and date",
             "observation": {"observed_at_utc": observed, "probability_yes": p_yes, "probability_for_claim": p_claim,
                             "bid": None, "ask": None, "midpoint": None, "price_kind": "polymarket_history_p", "fidelity_minutes": 60,
                             "staleness_sec": stale, "volume": 87684.2, "liquidity": None,
                             "source_url": "https://clob.polymarket.com/prices-history?market=5262"}}
    return {"status": status, "reason": None,
            "cutoff": {"basis": "publication_date_only", "requested_cutoff_utc": cutoff, "precision": "date", "rule": "r"},
            "market_probability": p_claim if status == "matched" else None,
            "exact_match": match if status == "matched" else None, "proxy_matches": [],
            "candidates_considered": 3, "candidates_dropped": [{"platform": "kalshi", "market_id": "K1", "reason": "opened_after_cutoff"}],
            "matcher": {"harness": "gemini", "requested_model": "gemini-3.8-flash-high", "served_model": "gemini-3.8-flash-high",
                        "served_model_verified": True, "account": "a@b", "contract_id": "dddddddddddd", "run_id": "run-m",
                        "matched_at_utc": "2026-09-10T02:00:00Z"},
            "searched_at_utc": "2026-09-10T02:00:00Z", "error": None}


def test_consensus(V, L) -> None:
    with tempfile.TemporaryDirectory() as td:
        pr, tx, recs = build_tree(Path(td), L)
        rs = copy.deepcopy(recs)
        rs[0]["consensus"] = full_consensus(rs[0], "2025-02-28T23:00:03Z")
        write_tree(pr, rs, L)
        fails, _ = run_validator(V, L, pr, tx)
        check("CONSENSUS: a full matched block with an ex-ante observation validates", not fails,
              "; ".join(f"{f['invariant']}: {f['detail']}" for f in fails[:4]))
        rs[0]["consensus"] = full_consensus(rs[0], "2025-02-28T23:00:03Z", direction="inverse", p_yes=0.27)
        write_tree(pr, rs, L)
        fails, _ = run_validator(V, L, pr, tx)
        check("CONSENSUS: inverse direction with probability_for_claim = 1 - p validates", not fails,
              "; ".join(f"{f['invariant']}: {f['detail']}" for f in fails[:4]))
        for name, obs, direction, extra in (
            ("observation AT the cutoff", "2025-03-01T00:00:00Z", "same", None),
            ("observation after the cutoff", "2025-03-01T09:00:00Z", "same", None),
            ("inverse without the flip", "2025-02-28T23:00:03Z", "inverse", "noflip"),
            ("probability on no_match", "2025-02-28T23:00:03Z", "same", "nomatch_prob"),
        ):
            c = full_consensus(rs[0], obs, direction)
            if extra == "noflip":
                c["exact_match"]["observation"]["probability_for_claim"] = c["exact_match"]["observation"]["probability_yes"]
                c["market_probability"] = c["exact_match"]["observation"]["probability_yes"]
            if name == "observation after the cutoff":
                # A negative staleness fails the schema first; zero it so the timestamp rule itself is tested.
                c["exact_match"]["observation"]["staleness_sec"] = 0
            if extra == "nomatch_prob":
                c["status"] = "no_match"; c["exact_match"] = None
            rs[0]["consensus"] = c
            write_tree(pr, rs, L)
            fails, _ = run_validator(V, L, pr, tx)
            check(f"CONSENSUS: {name} is caught", any(f["invariant"] == "consensus" and f["line"] == 1 for f in fails),
                  "; ".join(f"{f['invariant']}: {f['detail']}" for f in fails[:3]) or "no failures")


def test_cli(V, L) -> None:
    script = REPO / "scripts" / "validate_predictions.py"
    with tempfile.TemporaryDirectory() as td:
        pr, tx, recs = build_tree(Path(td), L)
        rep = Path(td) / "report.json"
        p = subprocess.run([PY, str(script), "--predictions", str(pr), "--transcripts", str(tx), "--exclude", "", "--report", str(rep)],
                           capture_output=True, text=True, cwd=REPO)
        check("CLI: clean tree exits 0 and writes the report", p.returncode == 0 and rep.exists() and "records 2" in p.stdout, p.stdout[-300:] + p.stderr[-300:])
        rs = copy.deepcopy(recs); rs[0]["prediction_id"] = "0000000000000000"; write_tree(pr, rs, L)
        p = subprocess.run([PY, str(script), "--predictions", str(pr), "--transcripts", str(tx), "--exclude", "", "--report", str(rep)],
                           capture_output=True, text=True, cwd=REPO)
        check("CLI: a defect exits 1 and names file:line: invariant",
              p.returncode == 1 and "s1.jsonl:1: prediction_id:" in p.stdout, p.stdout[-300:])
        p = subprocess.run([PY, str(script), "--predictions", str(Path(td) / "nowhere"), "--transcripts", str(tx)],
                           capture_output=True, text=True, cwd=REPO)
        check("CLI: a missing tree exits 2", p.returncode == 2, p.stderr[-200:])


def main() -> int:
    L = load("predictions_lib")
    V = load("validate_predictions")
    test_clean_and_mutations(V, L)
    test_consensus(V, L)
    test_cli(V, L)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
