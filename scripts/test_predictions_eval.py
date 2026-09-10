#!/usr/bin/env python3
"""The eval must credit only what matches gold, and must never spend quota by accident.

Builds a scored tree by hand from the fixtures (as if a driver had run), with
known hits, a miss, a false positive on an adversarial span, and a wrong
probability, and checks each metric lands where arithmetic says it should.

  MATCH     overlap of at least half the gold span counts; less does not
  METRICS   precision, recall, adversarial table, fidelity fields and probability exactness follow from the fixture
  GATES     the hard gates fail the run; the soft ones only report
  MODES     --scored needs no model; --out refuses without PREDICT_LIVE=1; both or neither is an error
  FIXTURES  every gold quote still grounds in its transcript (the builder's promise, re-checked)

  .venv/bin/python scripts/test_predictions_eval.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
FIX = REPO / "scripts" / "fixtures" / "predictions"
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


def record_from_gold(L, rec: dict, roster: dict, g: dict, verdict: bool | None, prob_override=None) -> dict:
    conf = {"type": g["confidence_type"], "probability": g["probability"] if g["confidence_type"] == "explicit_probability" else None,
            "verbatim_confidence_language": None}
    if g["confidence_type"] == "explicit_probability":
        conf["verbatim_confidence_language"] = "70% chance"
        if prob_override is not None:
            conf["probability"] = prob_override
    elif g["confidence_type"] == "qualitative":
        conf["verbatim_confidence_language"] = next(w for w in ("I'm almost certain", "I have no doubt", "I'm quite sure", "I'd bet", "my actual bet") if w.lower() in g["quote"].lower())
    cand = {"quote": g["quote"], "gates": {x: True for x in L.GATES}, "gate_notes": "", "resolution_criteria": "By X, Y will Z",
            "normalized_claim": f"{roster['name']}: " + " ".join(g["must_contain"]) + " " + g["quote"],
            "category": g["category"], "prediction_type": g["prediction_type"], "target_date": g["target_date"],
            "target_date_text": "by then" if g["horizon"] == "explicit" else None, "horizon": g["horizon"],
            "horizon_years_inferred": None, "horizon_evidence": None, "specificity": "high", "subject_control": g["subject_control"],
            "confidence": conf}
    loc = L.locate_quote(rec["text"], g["quote"])
    assert "start" in loc, (g["quote"], loc)
    prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}, "default", "claude")
    r = L.make_record(rec, roster, cand, loc, prov, "a" * 12, "run-x", "2026-09-10T00:00:00Z", {})
    if verdict is not None:
        v = r["verification"]
        v.update({"status": "ok", "harness": "astra", "requested_model": "gpt-6-astra", "served_model": "gpt-6-astra", "served_model_verified": False,
                  "account": "codex", "router_account_id": "codex", "contract_id": "b" * 12, "run_id": "run-v", "verified_at_utc": "2026-09-10T01:00:00Z",
                  "gates": {x: True for x in L.GATES}, "attribution": "subject" if verdict else "interviewer", "claim_faithful": True,
                  "qualifies_stated": verdict, "verifier_resolution_criteria": "x", "notes": None, "telemetry": {}})
        v["qualifies"] = L.verification_qualifies(v)
        v["agreement"] = r["extraction"]["qualifies"] == v["qualifies"]
        r["accepted"] = L.compute_accepted(r)
    return r


def build_scored(td: Path, L) -> Path:
    scored = td / "scored"
    roster = {r["slug"]: r for r in json.loads((FIX / "roster.json").read_text())["roster"]}
    for gf in sorted(FIX.glob("gold/*/*.json")):
        slug, sid = gf.parent.name, gf.stem
        gold = json.loads(gf.read_text())
        rec = json.loads((FIX / "transcripts" / slug / f"{sid}.json").read_text())
        recs = []
        for i, g in enumerate(gold["positives"]):
            if slug == "kenji-sato" and g["gold_id"] == "P14":
                continue                                            # one miss
            verdict = False if (slug == "nova-reyes" and g["gold_id"] == "P4") else True   # one verifier rejection
            prob = 0.9 if g["gold_id"] == "P2" else None            # one wrong probability
            recs.append(record_from_gold(L, rec, roster[slug], g, verdict, prob))
        if slug == "dev-okafor":                                    # one adversarial false positive: present-tense vision
            n = next(n for n in gold["negatives"] if n["reason"] == "present_tense_vision")
            fake = {"gold_id": "FP", "quote": n["quote"], "horizon": "none", "target_date": None, "confidence_type": "none", "probability": None,
                    "category": "technology_product", "prediction_type": "milestone", "subject_control": "own", "must_contain": []}
            recs.append(record_from_gold(L, rec, roster[slug], fake, True))
        (scored / slug).mkdir(parents=True, exist_ok=True)
        (scored / slug / f"{sid}.jsonl").write_text(L.serialise_lines(recs))
        (scored / slug / f"{sid}.meta.json").write_text(json.dumps({"schema_version": 1, "transcript_id": f"{slug}/{sid}",
            "extract": {"status": "ok", "candidates_written": len(recs), "ungrounded": [{"quote": "x", "reason": "not_found"}] if slug == "nova-reyes" else [],
                        "dedupe_dropped": [], "cap_hit": False},
            "verify": {"status": "ok", "accepted": sum(1 for r in recs if r["accepted"])}}))
    (scored / "_runs").mkdir()
    (scored / "_runs" / "r.json").write_text(json.dumps({"extraction_contract": {"contract_id": "a" * 12}, "verification_contract": {"contract_id": "b" * 12}}))
    return scored


def main() -> int:
    L = load("predictions_lib")
    E = load("eval_predictions")
    check("MATCH: half overlap counts, less does not",
          E.overlap_share((0, 50), (0, 100)) == 0.5 and E.overlap_share((60, 200), (0, 100)) == 0.4 and E.overlap_share((0, 100), (0, 100)) == 1.0)
    # FIXTURES: the builder's promise still holds on disk.
    bad = []
    for gf in sorted(FIX.glob("gold/*/*.json")):
        text = json.loads((FIX / "transcripts" / gf.parent.name / f"{gf.stem}.json").read_text())["text"]
        for e in json.loads(gf.read_text())["positives"] + json.loads(gf.read_text())["negatives"]:
            loc = L.locate_quote(text, e["quote"])
            if "error" in loc or (loc["start"], loc["end"]) != (e["char_start"], e["char_end"]):
                bad.append(e.get("gold_id") or e["reason"])
    check("FIXTURES: every gold quote grounds at its recorded offsets", not bad, str(bad))
    n_pos = sum(len(json.loads(g.read_text())["positives"]) for g in FIX.glob("gold/*/*.json"))
    n_neg = sum(len(json.loads(g.read_text())["negatives"]) for g in FIX.glob("gold/*/*.json"))
    reasons = {n["reason"] for g in FIX.glob("gold/*/*.json") for n in json.loads(g.read_text())["negatives"]}
    check("FIXTURES: 13 positives, 24 negatives, and every probe failure mode is represented",
          n_pos == 13 and n_neg == 24 and set(E.PROBE_FAILURE_MODES) <= reasons, f"{n_pos} {n_neg} {sorted(reasons)}")
    with tempfile.TemporaryDirectory() as td:
        scored = build_scored(Path(td), L)
        rep = E.score_tree(scored, FIX)
        m, t = rep["metrics"], rep["totals"]
        # 12 gold positives written (P14 missing); P4 rejected by the verifier -> 11 accepted matched; plus 1 false positive.
        check("METRICS: accepted 12, matched 11, precision 11/12, recall 11/13",
              t["accepted"] == 12 and t["matched"] == 11 and m["precision"] == round(11 / 12, 4) and m["recall"] == round(11 / 13, 4),
              json.dumps({k: t[k] for k in ("accepted", "matched", "gold", "false_positives")}) + json.dumps(m))
        check("METRICS: the adversarial table counts the vision false positive and nothing else",
              rep["adversarial"]["present_tense_vision"]["accepted"] == 1 and sum(v["accepted"] for v in rep["adversarial"].values()) == 1,
              json.dumps(rep["adversarial"]))
        check("METRICS: extractor-only precision counts the verifier-rejected P4 as an extractor hit",
              t["qualifying"] == 13 and t["extractor_matched"] == 12)
        check("METRICS: probability exactness catches the wrong 0.9 on P2", m["probability_exactness"] == 0.0 and m["confidence_type_correctness"] == 1.0)
        check("METRICS: claim and horizon fidelity are 1.0 on records built from gold", m["claim_fidelity"] == 1.0 and m["horizon_correctness"] == 1.0)
        check("METRICS: ungrounded rate reads the meta", m["ungrounded_rate"] == round(1 / 14, 4), str(m["ungrounded_rate"]))
        check("METRICS: schema and quote fidelity pass on a valid tree", m["schema_valid"] == 1.0 and m["quote_fidelity"] == 1.0, str(rep["validator_failures"][:3]))
        row = next(r for r in rep["per_transcript"] if r["transcript"] == "kenji-sato/fireside-01")
        check("METRICS: the missed gold is named per transcript", row["unmatched_gold"] == ["P14"])
        vs = dict((n, ok) for n, _t, ok in E.verdicts(rep))
        check("GATES: precision passes, probability exactness fails, the vision adversarial fails",
              vs["precision"] is True and vs["probability_exactness"] is False and vs["adversarial:present_tense_vision"] is False)
        p = subprocess.run([PY, str(REPO / "scripts" / "eval_predictions.py"), "--scored", str(scored)], capture_output=True, text=True, cwd=REPO)
        check("MODES: --scored runs offline and exits 1 because an adversarial gate failed",
              p.returncode == 1 and "[FAIL] adversarial:present_tense_vision" in p.stdout and (scored / "_eval_report.json").exists(), p.stdout[-500:] + p.stderr[-300:])
        env = {k: v for k, v in os.environ.items() if k != "PREDICT_LIVE"}
        p = subprocess.run([PY, str(REPO / "scripts" / "eval_predictions.py"), "--out", str(Path(td) / "live")], capture_output=True, text=True, cwd=REPO, env=env)
        check("MODES: --out without PREDICT_LIVE=1 refuses before any call", p.returncode != 0 and "PREDICT_LIVE" in p.stderr)
        p = subprocess.run([PY, str(REPO / "scripts" / "eval_predictions.py")], capture_output=True, text=True, cwd=REPO)
        check("MODES: neither --scored nor --out is an error", p.returncode != 0 and "exactly one" in p.stderr)
        p = subprocess.run([PY, str(REPO / "scripts" / "eval_predictions.py"), "--out", str(L.REPO / "data" / "grades" / "x")],
                           capture_output=True, text=True, cwd=REPO, env={**os.environ, "PREDICT_LIVE": "1"})
        check("MODES: --out under data/ but outside data/predictions/_eval is refused", p.returncode != 0 and "outside data/" in p.stderr, p.stderr[-300:])
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
