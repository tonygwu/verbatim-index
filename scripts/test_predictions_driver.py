#!/usr/bin/env python3
"""Guards on the extraction driver, without a single model call.

The driver's decisions are pure functions over data the model or the router
returned, so every one is exercised here from a dict. The only subprocess is
the driver itself in --dry-run, which builds prompts and must write nothing
under --out.

  ROUTE   a router decision maps to exactly one harness and account, or fails by name
  PROMPT  the prompts carry the speaker header, the warning, the constants, and no dates that leak
  GROUND  model candidates become records only when the quote grounds; drops are recorded
  VERIFY  verdicts write the verification block and the derived booleans
  SUMMARY attempted equals the sum of the outcome buckets, with a taxonomy
  DRYRUN  --dry-run writes the prompt to the workdir and nothing under --out; a bad --out is refused
  MISSING a transcript deleted mid-pass is excluded or labelled, never a CLI failure

  .venv/bin/python scripts/test_predictions_driver.py
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import types
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


ACCOUNTS = [("claude", "claude", "/Users/x/.claude", True), ("claude_b", "claude", "/Users/x/.claude-b", False),
            ("codex", "codex", None, False), ("antigravity_gemini", "antigravity", None, False),
            ("antigravity_claude", "antigravity", None, False)]


def sel(account, provider, degraded=()):
    return {"decision": {"account": account, "provider": provider, "reason": "r"}, "degraded": list(degraded), "warnings": []}


def test_route(D, L) -> None:
    r = D.route_from_selection(sel("claude", "claude"), ACCOUNTS, False)
    check("ROUTE: default Claude account -> fable with __DEFAULT__", r["harness"] == "fable" and r["config_dir"] == "__DEFAULT__")
    r = D.route_from_selection(sel("claude_b", "claude"), ACCOUNTS, False)
    check("ROUTE: named Claude account -> its config dir", r["config_dir"] == "/Users/x/.claude-b")
    r = D.route_from_selection(sel("codex", "codex"), ACCOUNTS, False)
    check("ROUTE: codex -> astra, no config dir", r["harness"] == "astra" and r["config_dir"] is None)
    r = D.route_from_selection(sel("antigravity_gemini", "antigravity"), ACCOUNTS, False)
    check("ROUTE: antigravity -> gemini", r["harness"] == "gemini")
    for name, s in (("no account", sel(None, None)), ("unknown provider", sel("cursor", "cursor")),
                    ("degraded pick without --allow-degraded", sel("codex", "codex", degraded=[{"account": "codex", "why": "stale"}]))):
        try:
            D.route_from_selection(s, ACCOUNTS, False)
            check(f"ROUTE: {name} raises RouterUnavailable", False, "no exception")
        except D.RouterUnavailable as exc:
            check(f"ROUTE: {name} raises RouterUnavailable", str(exc).startswith(L.E_ROUTER))
    r = D.route_from_selection(sel("codex", "codex", degraded=[{"account": "codex"}]), ACCOUNTS, True)
    check("ROUTE: degraded pick allowed with --allow-degraded, and marked", r["degraded"] is True)
    fits = sel("codex", "codex", degraded=[{"account": "codex", "reason": "usage reading is 18m old"}])
    fits["decision"]["fits"] = True
    r = D.route_from_selection(fits, ACCOUNTS, False)
    check("ROUTE: a degraded pick the router still calls a fit proceeds, with the reason recorded",
          r["degraded"] is True and "18m old" in r["degraded_reason"])
    check("ROUTE: a degraded entry about ANOTHER account does not block",
          D.route_from_selection(sel("codex", "codex", degraded=[{"account": "antigravity_gemini"}]), ACCOUNTS, False)["degraded"] is False)
    check("ROUTE: accounts_of_harness lists every account of the extractor's provider",
          D.accounts_of_harness(ACCOUNTS, "fable") == ["claude", "claude_b"]
          and D.accounts_of_harness(ACCOUNTS, "gemini") == ["antigravity_gemini", "antigravity_claude"])
    check("ROUTE: the taxonomy label router_no_account is classified, not filed as cli_nonzero_exit",
          L.classify_exception_detail(f"{L.E_ROUTER}: x") == L.E_ROUTER
          and L.classify_exception_detail(f"{L.E_VERIFIER_SAME}: x") == L.E_VERIFIER_SAME)
    src = inspect.getsource(D.Router.pick)
    check("ROUTE: the router pick books a reservation (record=True) and ignores stickiness",
          "record=True" in src and "no_sticky=True" in src)


REC = {"leader_slug": "ada", "source_id": "s1", "yt_upload_date": "20250301", "url": "u", "video_id": "v",
       "yt_title": "Ada on code", "declared_venue": "Pod", "declared_kind": "podcast", "declared_year": 2024,
       "word_count": 30, "duration_sec": 600,
       "text": "[00:00:01] welcome so tell me [00:01:00] I think by 2030 most code will be written by AI, that is my bet"}
ROSTER = {"name": "Ada L", "role": "CEO", "company": "Co", "sector": "AI"}


def test_prompt(D, L) -> None:
    spec = (L.SKILL / L.EXTRACTION_SPEC).read_text()
    schema = json.dumps(json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()))
    p = L.build_extraction_prompt(REC, ROSTER, spec, schema)
    for needle in ("Speaker: Ada L", "Role (current roster entry; may postdate this recording): CEO", "Company (current roster entry): Co", "Title: Ada on code", "Venue: Pod",
                   "Format: podcast", "Statement date: 2025-03-01", "no speaker labels", "transcript_id must be exactly: ada/s1",
                   REC["text"], f"{L.MIN_QUOTE_WORDS} to {L.MAX_QUOTE_WORDS} words", f"At most {L.MAX_CANDIDATES} candidates"):
        check(f"PROMPT: extraction prompt has {needle[:40]!r}", needle in p)
    check("PROMPT: no declared_year and no 2024 from it", "2024" not in p.replace("2024-12", "") or "declared" not in p)
    today = L.utc_now()[:10]
    check("PROMPT: today's date is not in the prompt", today not in p)
    p2 = L.build_extraction_prompt({**REC, "yt_upload_date": None}, None, spec, schema)
    check("PROMPT: unknown date says so and the name falls back to the slug",
          "Statement date: unknown" in p2 and "Speaker: Ada" in p2)
    with tempfile.TemporaryDirectory() as td:
        sk = Path(td)
        for f in (L.EXTRACTION_SPEC, L.EXTRACTOR_SCHEMA):
            (sk / f).write_bytes((L.SKILL / f).read_bytes())
        before = L.extraction_contract(sk)["contract_id"]
        (sk / L.EXTRACTION_SPEC).write_text((sk / L.EXTRACTION_SPEC).read_text() + "\nx")
        check("PROMPT: editing EXTRACTION.md changes the contract id", L.extraction_contract(sk)["contract_id"] != before)
        (sk / "SKILL.md").write_text("irrelevant")
        check("PROMPT: SKILL.md is not in the contract", L.extraction_contract(sk)["contract_id"] == L.extraction_contract(sk)["contract_id"]
              and "SKILL" not in inspect.getsource(L._contract))
    # The spec states the same numbers as the constants.
    check("PROMPT: EXTRACTION.md states the quote bounds and the cap that the code enforces",
          f"{L.MIN_QUOTE_WORDS} to {L.MAX_QUOTE_WORDS} words" in spec and f"at most\n{L.MAX_CANDIDATES} candidates" in spec.replace("at most 40", "at most\n40"))
    vspec = (L.SKILL / L.VERIFICATION_SPEC).read_text()
    check("PROMPT: VERIFICATION.md names the window size the code cuts", f"{L.CONTEXT_WORDS} words" in vspec)
    bundle = {"header": "H", "transcript_id": "ada/s1", "candidates": [
        {"prediction_id": "a" * 16, "quote_original": "Q", "normalized_claim": "C", "timestamp_mark": "[00:01:00]",
         "context_before": "B", "context_after": "A"}]}
    vp = L.build_verification_prompt(bundle, vspec, "{}")
    check("PROMPT: verification prompt shows window, quote and claim, and hides gates and reasoning",
          "CONTEXT BEFORE:\nB" in vp and "QUOTE:\nQ" in vp and "EXTRACTOR CLAIM:\nC" in vp
          and "gate_notes" not in vp and "resolution_criteria written at extraction" not in vp)
    for spec_text, name in ((spec, "EXTRACTION.md"), (vspec, "VERIFICATION.md")):
        check(f"PROMPT: {name} is ignorant of markets", not re.search(r"polymarket|kalshi|market_probability|consensus", spec_text, re.I))
    check("PROMPT: the prompt builders are ignorant of markets",
          not re.search(r"polymarket|kalshi|market_probability", inspect.getsource(L.build_extraction_prompt) + inspect.getsource(L.build_verification_prompt), re.I))


def cand(quote, hint="[00:01:00]", **over):
    c = {"quote": quote, "timestamp_hint": hint, "normalized_claim": "By 2030 most code is AI-written.",
         "gates": {g: True for g in ("forward_looking", "falsifiable", "committed", "own_voice", "stands_alone")},
         "gate_notes": "", "resolution_criteria": "By 2030-12-31, >50% of code is AI-written per survey",
         "category": "ai_capability", "prediction_type": "milestone", "target_date": "2030", "target_date_text": "by 2030",
         "horizon": "explicit", "horizon_years_inferred": None, "horizon_evidence": None, "specificity": "high",
         "subject_control": "external", "confidence": {"type": "none", "probability": None, "verbatim_confidence_language": None}}
    c.update(over)
    return c


def test_ground(D, L) -> None:
    prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}, "default", "claude")
    obj = {"candidates": [
        cand("I think by 2030 most code will be written by AI"),                  # grounds
        cand("I think by 2030 most code will be written by AI, that is"),         # near-identical -> folds into the longer
        cand("most code will be written by machines"),                             # paraphrase -> not_found
        cand("so tell me I think"),                                                # 5 words -> word_count
    ]}
    records, ungrounded, dropped = D.ground_candidates(REC, ROSTER, obj, prov, "c" * 12, "run", "2026-09-10T00:00:00Z", {})
    check("GROUND: only grounded, in-bounds, non-duplicate candidates become records",
          len(records) == 1 and records[0]["source"]["quote_original"].endswith("that is"), str([r["source"]["quote"] for r in records]))
    check("GROUND: ungrounded candidates are recorded with reasons",
          sorted(u["reason"] for u in ungrounded) == ["not_found", "word_count_5"], str(ungrounded))
    check("GROUND: the near-duplicate drop is recorded with kept_by", len(dropped) == 1 and dropped[0]["kept_by"] == records[0]["prediction_id"])
    check("GROUND: records validate against the record schema", L.check_schema(records[0], L.load_record_schema()) == [])
    bad = D.parse_model_output
    for text, label in (("no json at all", L.E_NOJSON), ('{"schema_version": "1"}', L.E_SCHEMA)):
        try:
            bad(text, json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()), "ada/s1")
            check(f"GROUND: {label} raised", False)
        except RuntimeError as exc:
            check(f"GROUND: {label} raised", str(exc).startswith(label), str(exc)[:120])
    good = {"schema_version": "1", "transcript_id": "ada/OTHER", "attribution_notes": "", "subject_speech_share_estimate_pct": 50,
            "candidates": [], "candidates_considered": 0, "cap_hit": False, "estimated_total_qualifying": 0}
    try:
        bad(json.dumps(good), json.loads((L.SKILL / L.EXTRACTOR_SCHEMA).read_text()), "ada/s1")
        check("GROUND: wrong transcript_id is schema_validation_failed", False)
    except RuntimeError as exc:
        check("GROUND: wrong transcript_id is schema_validation_failed", str(exc).startswith(L.E_SCHEMA))


def test_verify(D, L) -> None:
    prov = L.normalise_provenance("fable", {"requested_model": "m", "judge_model": "m"}, "default", "claude")
    obj = {"candidates": [cand("I think by 2030 most code will be written by AI")]}
    records, _, _ = D.ground_candidates(REC, ROSTER, obj, prov, "c" * 12, "run", "2026-09-10T00:00:00Z", {})
    pid = records[0]["prediction_id"]
    vprov = L.normalise_provenance("astra", {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}, None, "codex")
    verdict = {"prediction_id": pid, "attribution": "subject", "gates": {g: True for g in L.GATES}, "claim_faithful": True,
               "confidence_type_seen": "none", "qualifies": True, "resolution_criteria": "By end 2030 ...", "notes": None}
    D.apply_verdicts(records, [verdict], vprov, "d" * 12, "run-v", "2026-09-10T01:00:00Z", {})
    r = records[0]
    check("VERIFY: agreement -> accepted, with verifier provenance", r["accepted"] is True and r["verification"]["harness"] == "astra"
          and r["verification"]["agreement"] is True and r["verification"]["served_model_verified"] is False)
    check("VERIFY: the record still validates", L.check_schema(r, L.load_record_schema()) == [], str(L.check_schema(r, L.load_record_schema()))[:200])
    D.apply_verdicts(records, [{**verdict, "attribution": "interviewer", "qualifies": True}], vprov, "d" * 12, "run-v", "2026-09-10T01:00:00Z", {})
    check("VERIFY: qualifies is RECOMPUTED from attribution, not copied from the model",
          r["verification"]["qualifies_stated"] is True and r["verification"]["qualifies"] is False
          and r["accepted"] is False and r["verification"]["agreement"] is False)


def test_summary(D) -> None:
    rs = [{"stage": "extract", "status": "ok", "written": 3, "ungrounded": 1, "elapsed": 10},
          {"stage": "extract", "status": "cached"}, {"stage": "extract", "status": "excluded"},
          {"stage": "extract", "status": "failed", "error_type": "auth_or_quota"},
          {"stage": "extract", "status": "failed", "error_type": "router_no_account"},
          {"stage": "verify", "status": "ok", "verified": 2, "accepted": 1, "elapsed": 5}]
    s = D.summarise(rs, "extract")
    check("SUMMARY: attempted equals the sum of the buckets",
          s["attempted"] == 5 == s["ok"] + s["cached"] + s["excluded"] + s["failed"] + s["dry_run"] + s["skipped"] + s["nothing_to_verify"])
    check("SUMMARY: taxonomy is per label, never a bare count", s["error_taxonomy"] == {"auth_or_quota": 1, "router_no_account": 1})
    check("SUMMARY: stage counters", s["candidates_written"] == 3 and D.summarise(rs, "verify")["accepted"] == 1)


def test_dryrun(D, L) -> None:
    script = REPO / "scripts" / "extract_predictions.py"
    with tempfile.TemporaryDirectory() as td:
        tx = Path(td) / "tx" / "ada"
        tx.mkdir(parents=True)
        (tx / "s1.json").write_text(json.dumps(REC))
        roster = Path(td) / "roster.json"
        roster.write_text(json.dumps({"roster": [{"slug": "ada", **ROSTER}]}))
        out = Path(td) / "out"
        env = {**os.environ, "TMPDIR": td}
        p = subprocess.run([PY, str(script), "--single", str(tx / "s1.json"), "--roster", str(roster), "--out", str(out),
                            "--stage", "both", "--dry-run", "--no-exclude"], capture_output=True, text=True, cwd=REPO, env=env)
        prompts = list(Path(td).glob("predict-work/*/prompt.txt"))
        check("DRYRUN: exits 0, writes the prompt to the workdir", p.returncode == 0 and len(prompts) == 1, p.stderr[-400:])
        check("DRYRUN: nothing is written under --out", not out.exists(), str(list(out.rglob("*")) if out.exists() else ""))
        check("DRYRUN: the summary reports dry_run, not succeeded", '"dry_run": 1' in p.stdout and '"ok": 0' in p.stdout, p.stdout)
        p = subprocess.run([PY, str(script), "--single", str(tx / "s1.json"), "--roster", str(roster),
                            "--out", str(L.REPO / "data" / "grades"), "--dry-run", "--no-exclude"], capture_output=True, text=True, cwd=REPO, env=env)
        check("DRYRUN: --out data/grades is refused before anything runs",
              p.returncode != 0 and "refusing to write" in (p.stderr + p.stdout), p.stderr[-300:])
        p = subprocess.run([PY, str(script), "--single", str(tx / "s1.json"), "--roster", str(roster), "--out", str(out),
                            "--dry-run", "--no-exclude", "--fable-bin", "cl"], capture_output=True, text=True, cwd=REPO, env=env)
        check("DRYRUN: --fable-bin cl is refused", p.returncode != 0 and "dangerously" in p.stderr)
        # --list selects exactly the named files, and a missing one is refused.
        lst = Path(td) / "list.txt"
        lst.write_text(f"{tx / 's1.json'}\n")
        p = subprocess.run([PY, str(script), "--list", str(lst), "--roster", str(roster), "--out", str(out),
                            "--stage", "extract", "--dry-run", "--no-exclude"], capture_output=True, text=True, cwd=REPO, env=env)
        check("DRYRUN: --list selects the named transcript", p.returncode == 0 and '"dry_run": 1' in p.stdout, p.stdout + p.stderr[-200:])
        lst.write_text(f"{tx / 'nope.json'}\n")
        p = subprocess.run([PY, str(script), "--list", str(lst), "--roster", str(roster), "--out", str(out),
                            "--stage", "extract", "--dry-run", "--no-exclude"], capture_output=True, text=True, cwd=REPO, env=env)
        check("DRYRUN: --list with a missing file is refused", p.returncode != 0 and "missing file" in p.stderr, p.stderr[-200:])
        # An excluded transcript is marked and never prompted.
        excl = Path(td) / "ex.json"
        excl.write_text(json.dumps({"schema_version": 1, "exclusions": [{"transcript_id": "ada/s1", "reason": "wrong_person", "evidence": "e"}]}))
        for f in Path(td).glob("predict-work/*/prompt.txt"):
            f.unlink()
        p = subprocess.run([PY, str(script), "--single", str(tx / "s1.json"), "--roster", str(roster), "--out", str(out),
                            "--stage", "extract", "--dry-run", "--exclude", str(excl)], capture_output=True, text=True, cwd=REPO, env=env)
        check("DRYRUN: an excluded transcript is counted as excluded and gets no prompt",
              '"excluded": 1' in p.stdout and not list(Path(td).glob("predict-work/*/prompt.txt")), p.stdout + p.stderr[-200:])


def test_missing(D, L) -> None:
    """A transcript deleted under a running pass: repo-0 applies the withdrawal manifest
    while this pass holds a file list taken at launch, so the file can vanish mid-run."""
    with tempfile.TemporaryDirectory() as td:
        gone = Path(td) / "tx" / "ada" / "s1.json"
        gone.parent.mkdir(parents=True)
        out = Path(td) / "out"
        args = types.SimpleNamespace(dry_run=False, force=False, verifier="auto")
        job = {"args": args, "path": str(gone), "out": out, "roster": {"ada": ROSTER}, "run_id": "r1",
               "exclusions": {"ada/s1": {"reason": "wrong_person", "evidence": "e"}},
               "workroot": Path(td) / "work", "spec": "s", "schema": {}, "schema_text": "{}"}
        check("MISSING: the transcript id comes from the path, not from the file",
              L.transcript_id_from_path(gone) == "ada/s1", L.transcript_id_from_path(gone))
        r = D.extract_one(job)
        check("MISSING: an excluded transcript whose file is gone is excluded, not failed",
              r["status"] == "excluded" and r["id"] == "ada/s1", json.dumps(r))
        job["exclusions"] = {}
        try:
            r = D.extract_one(job)
            detail = json.dumps(r)
            etype = r.get("error_type", "")
        except Exception as exc:  # the pass classifies what the job raised
            detail = f"{type(exc).__name__}: {exc}"
            etype = L.classify_exception_detail(str(exc))
        check("MISSING: a transcript that is gone and not excluded is labelled transcript_missing",
              etype == L.E_TRANSCRIPT_MISSING, f"{etype}: {detail}")
        check("MISSING: transcript_missing is in the taxonomy", L.E_TRANSCRIPT_MISSING in L.ALL_ERROR_TYPES)
        check("MISSING: the failure names the transcript, never '?'", "ada/s1" in detail, detail)
        # verify_one meets the same file and must not crash on the read either.
        job["exclusions"] = {"ada/s1": {"reason": "wrong_person", "evidence": "e"}}
        r = D.verify_one(job)
        check("MISSING: verify skips a transcript whose file is gone, naming it",
              r["status"] in ("skipped", "excluded") and r["id"] == "ada/s1", json.dumps(r))


def main() -> int:
    L = load("predictions_lib")
    D = load("extract_predictions")
    test_route(D, L)
    test_prompt(D, L)
    test_ground(D, L)
    test_verify(D, L)
    test_summary(D)
    test_dryrun(D, L)
    test_missing(D, L)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
