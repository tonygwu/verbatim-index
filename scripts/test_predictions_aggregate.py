#!/usr/bin/env python3
"""The index must be descriptive, deterministic, and honest about coverage.

  COUNTS   per-person and corpus counts follow from a small fixture tree
  NEUTRAL  no key anywhere in the index reads like an evaluation of foresight
  STABLE   two runs over the same tree are byte-identical apart from generated_at_utc
  COVERAGE extraction and verification statuses are counted from meta, excluded and failed included
  CLI      the script writes index.json under the predictions root and refuses an evaluative key

  .venv/bin/python scripts/test_predictions_aggregate.py
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


def record(L, slug, sid, quote_text, accepted, horizon="explicit", ctype="none", date="20250301", cons_status=None):
    text = f"[00:00:01] intro words here [00:01:00] {quote_text} and more words follow after that"
    rec = {"leader_slug": slug, "source_id": sid, "text": text, "yt_upload_date": date, "url": "u", "video_id": "v",
           "yt_title": "T", "declared_venue": "V", "declared_kind": "podcast", "word_count": 30, "duration_sec": 60}
    conf = {"explicit_probability": {"type": "explicit_probability", "probability": 0.7, "verbatim_confidence_language": "70% chance"},
            "qualitative": {"type": "qualitative", "probability": None, "verbatim_confidence_language": "I'd bet"},
            "none": {"type": "none", "probability": None, "verbatim_confidence_language": None}}[ctype]
    cand = {"quote": quote_text, "gates": {g: True for g in L.GATES}, "gate_notes": "", "resolution_criteria": "By X, Y",
            "normalized_claim": "c", "category": "ai_capability", "prediction_type": "milestone",
            "target_date": "2030" if horizon == "explicit" else None, "target_date_text": "by 2030" if horizon == "explicit" else None,
            "horizon": horizon, "horizon_years_inferred": 2.0 if horizon == "inferable" else None, "horizon_evidence": None,
            "specificity": "high", "subject_control": "external", "confidence": conf}
    loc = L.locate_quote(text, quote_text)
    prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1[1m]"}, "default", "claude")
    r = L.make_record(rec, {"name": slug.title(), "role": "CEO", "company": "Co"}, cand, loc, prov, "a" * 12, "run-x", "2026-09-10T00:00:00Z", {})
    if accepted is not None:
        v = r["verification"]
        v.update({"status": "ok", "harness": "astra", "requested_model": "gpt-6-astra", "served_model": "gpt-6-astra",
                  "served_model_verified": False, "account": "codex", "router_account_id": "codex", "contract_id": "b" * 12,
                  "run_id": "run-v", "verified_at_utc": "2026-09-10T01:00:00Z", "gates": {g: True for g in L.GATES},
                  "attribution": "subject" if accepted else "interviewer", "claim_faithful": True, "qualifies_stated": accepted,
                  "verifier_resolution_criteria": "x", "notes": None, "telemetry": {}})
        v["qualifies"] = L.verification_qualifies(v)
        v["agreement"] = r["extraction"]["qualifies"] == v["qualifies"]
        r["accepted"] = L.compute_accepted(r)
    if cons_status:
        r["consensus"] = {"status": cons_status, "reason": None, "cutoff": L.publication_cutoff(r), "market_probability": None,
                          "exact_match": None, "proxy_matches": [], "candidates_considered": 0, "candidates_dropped": [],
                          "matcher": None, "searched_at_utc": "2026-09-10T02:00:00Z", "error": None}
    return r


def build(td: Path, L) -> Path:
    pr = td / "pred"
    for slug, sid, recs, meta in (
        ("ada", "s1", [record(L, "ada", "s1", "by 2030 most code will be written by AI I would say", True, cons_status="no_match"),
                       record(L, "ada", "s1", "open models will catch up to closed ones within two years", True, "inferable", "qualitative"),
                       record(L, "ada", "s1", "there is a 70% chance we ship the new chip this year", False, ctype="explicit_probability")],
         {"extract": {"status": "ok", "harness": "fable", "candidates_written": 3, "cap_hit": False, "ungrounded": [{"quote": "q", "reason": "not_found"}], "dedupe_dropped": []},
          "verify": {"status": "ok", "harness": "astra", "accepted": 2}}),
        ("ada", "s2", [], {"extract": {"status": "ok", "harness": "gemini", "candidates_written": 0, "cap_hit": True, "ungrounded": [], "dedupe_dropped": []},
                          "verify": {"status": "nothing_to_verify"}}),
        ("alan", "s3", [record(L, "alan", "s3", "rates will be substantially lower by the end of next year", None, date=None)],
         {"extract": {"status": "ok", "harness": "astra", "candidates_written": 1, "cap_hit": False, "ungrounded": [], "dedupe_dropped": []},
          "verify": {"status": "not_run"}}),
        ("alan", "s4", None, {"extract": {"status": "excluded", "reason": "wrong_person"}, "verify": {"status": "not_run"}}),
        ("alan", "s5", None, {"extract": {"status": "failed", "error_type": "auth_or_quota"}, "verify": {"status": "not_run"}}),
    ):
        (pr / slug).mkdir(parents=True, exist_ok=True)
        if recs is not None:
            (pr / slug / f"{sid}.jsonl").write_text(L.serialise_lines(recs))
        (pr / slug / f"{sid}.meta.json").write_text(json.dumps({"schema_version": 1, "transcript_id": f"{slug}/{sid}", **meta}, sort_keys=True))
    (td / "roster.json").write_text(json.dumps({"roster": [{"slug": "ada", "name": "Ada L", "company": "Co", "role": "CEO", "sector": "AI"},
                                                            {"slug": "alan", "name": "Alan T", "company": "Lab", "role": "Founder", "sector": "AI"},
                                                            {"slug": "grace", "name": "Grace H", "company": "Navy", "role": "Admiral", "sector": "Gov"}]}))
    tx = td / "tx"
    for slug, n in (("ada", 3), ("alan", 4), ("grace", 2)):
        (tx / slug).mkdir(parents=True)
        for i in range(n):
            (tx / slug / f"t{i}.json").write_text("{}")
    return pr


def main() -> int:
    L = load("predictions_lib")
    A = load("aggregate_predictions")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pr = build(td, L)
        roster = {r["slug"]: r for r in json.loads((td / "roster.json").read_text())["roster"]}
        idx = A.build_index(pr, roster, td / "tx")
        by = {l["slug"]: l for l in idx["leaders"]}
        check("COUNTS: files and records counted before any filter", idx["files_read"] == 3 and idx["records_read"] == 4)
        ada = by["ada"]
        check("COUNTS: ada accepted 2, rejected_by_verifier 1, horizons and confidence types",
              ada["accepted"] == 2 and ada["rejected_by_verifier"] == 1 and ada["by_horizon"] == {"explicit": 1, "inferable": 1}
              and ada["by_confidence_type"] == {"none": 1, "qualitative": 1} and ada["explicit_probability"] == 0,
              json.dumps({k: ada[k] for k in ("accepted", "rejected_by_verifier", "by_horizon", "by_confidence_type")}))
        check("COUNTS: ada dates, transcripts with accepted, consensus status",
              ada["earliest_statement_date"] == "2025-03-01" and ada["transcripts_with_accepted"] == 1
              and ada["consensus_by_status"] == {"no_match": 1, "not_searched": 1} and ada["market_matched"] == 0)
        alan = by["alan"]
        check("COUNTS: alan has one pending verification, no accepted, unknown date, excluded and failed transcripts",
              alan["accepted"] == 0 and alan["verification_pending"] == 1 and alan["transcripts_excluded"] == 1
              and alan["transcripts_extract_failed"] == 1 and alan["transcripts_on_disk"] == 4 and alan["earliest_statement_date"] is None)
        check("COUNTS: a roster leader with no files still appears with zeros", by["grace"]["accepted"] == 0 and by["grace"]["transcripts_on_disk"] == 2)
        check("COUNTS: leaders sorted by slug", [l["slug"] for l in idx["leaders"]] == ["ada", "alan", "grace"])
        c = idx["corpus"]
        check("COUNTS: corpus totals and models", c["accepted"] == 2 and c["candidates"] == 4 and c["transcripts_on_disk"] == 9
              and c["extractor_models"] == ["claude-fable-5-1[1m]"] and c["verifier_models"] == ["gpt-6-astra"]
              and c["agreement_rate"] == round(2 / 3, 4), json.dumps({k: c[k] for k in ("accepted", "candidates", "agreement_rate", "extractor_models")}))
        cov = idx["coverage"]
        check("COVERAGE: statuses from meta, excluded and failed included",
              cov["extract"] == {"excluded": 1, "failed": 1, "ok": 3} and cov["verify"] == {"not_run": 3, "nothing_to_verify": 1, "ok": 1}
              and cov["by_harness"]["extract"] == {"astra": 1, "fable": 1, "gemini": 1} and cov["cap_hit_transcripts"] == 1
              and cov["ungrounded_candidates_total"] == 1, json.dumps(cov))
        check("NEUTRAL: no evaluative key anywhere", A.forbidden_keys(idx) == [], str(A.forbidden_keys(idx)))
        check("NEUTRAL: an injected evaluative key is refused", A.forbidden_keys({"leaders": [{"accuracy_pct": 1}]}) == ["$.leaders[0].accuracy_pct"])
        idx2 = A.build_index(pr, roster, td / "tx")
        strip = lambda d: {k: v for k, v in d.items() if k != "generated_at_utc"}  # noqa: E731
        check("STABLE: two runs are byte-identical apart from the timestamp",
              json.dumps(strip(idx), sort_keys=True) == json.dumps(strip(idx2), sort_keys=True))
        check("STABLE: contracts and run ids are recorded", idx["contracts_seen"] == {"extraction": ["a" * 12], "verification": ["b" * 12], "matching": []}
              and idx["run_ids_seen"] == ["run-v", "run-x"])
        p = subprocess.run([PY, str(REPO / "scripts" / "aggregate_predictions.py"), "--predictions", str(pr), "--roster", str(td / "roster.json"),
                            "--transcripts", str(td / "tx")], capture_output=True, text=True, cwd=REPO)
        check("CLI: writes index.json under the predictions root and prints the counts",
              p.returncode == 0 and (pr / "index.json").exists() and "accepted 2" in p.stdout, p.stdout + p.stderr[-300:])
        check("CLI: the written file is sort_keys JSON that parses", json.loads((pr / "index.json").read_text())["files_read"] == 3)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
