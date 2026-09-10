#!/usr/bin/env python3
"""The market-consensus stage must never look forward, never invent a price, and never leak into extraction.

Every check runs with an injected fetcher (canned Polymarket and Kalshi
responses shaped like the real ones probed on 2026-09-10) and an injected
matcher, so nothing here touches the network or a model.

  CUTOFF     date-only publication gives 00:00 UTC at date precision; unknown gives no cutoff
  OBSERVE    the latest point strictly before the cutoff is chosen; at/after never; inverse flips
  CANDIDATES a market opened after the cutoff or closed before it is dropped with the reason; caps hold
  MATCH      the matcher prompt carries no price; a proxy never sets market_probability; one exact per platform
  STATUS     matched / no_match / unavailable / failed are each reachable and exclusive; failed keeps accepted
  CACHE      a second run makes zero HTTP calls
  ISOLATION  extraction and verification specs and prompt builders contain no market vocabulary
  SCHEMA     the block the stage writes validates and passes the validator's consensus rules

  .venv/bin/python scripts/test_predictions_markets.py
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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


CUT = "2025-03-01T00:00:00Z"          # statement date 2025-03-01, date-only
CUT_E = 1740787200                    # epoch of CUT

POLY_SEARCH = {"events": [{"id": "15042", "title": "GPT-5 released by...?", "markets": [
    {"id": "514502", "question": "Will GPT-5 be released by March 31?", "slug": "will-gpt-5-be-released-by-march-31",
     "description": "Resolves Yes if OpenAI's GPT-5 is made available to the general public by March 31, 2025.",
     "startDate": "2024-12-23T17:26:41.750649Z", "endDate": "2025-03-31T12:00:00Z", "volumeNum": "87684.22",
     "clobTokenIds": "[\"526277\", \"889729\"]"},
    {"id": "514503", "question": "Will GPT-5 be released by June 30?", "slug": "will-gpt-5-be-released-by-june-30",
     "description": "Resolves Yes if ... by June 30, 2025.", "startDate": "2024-12-23T17:27:01Z", "endDate": "2025-06-30T12:00:00Z",
     "volumeNum": "50000", "clobTokenIds": "[\"103389\", \"2\"]"},
    {"id": "600000", "question": "Will GPT-6 be released in 2026?", "slug": "gpt-6-2026", "description": "...",
     "startDate": "2025-06-01T00:00:00Z", "endDate": "2026-12-31T12:00:00Z", "volumeNum": "1", "clobTokenIds": "[\"9\", \"8\"]"},
    {"id": "600001", "question": "Will GPT-4.5 ship by Feb 2025?", "slug": "gpt45", "description": "...",
     "startDate": "2024-11-01T00:00:00Z", "endDate": "2025-02-15T12:00:00Z", "volumeNum": "1", "clobTokenIds": "[\"7\", \"6\"]"},
]}], "pagination": {}}

# Hourly points: one before the cutoff, one exactly at it, one after.
POLY_HIST_60 = {"history": [{"t": CUT_E - 3600, "p": 0.235}, {"t": CUT_E - 7200, "p": 0.24}, {"t": CUT_E, "p": 0.5}, {"t": CUT_E + 3600, "p": 0.9}]}
POLY_HIST_1 = {"history": []}

KALSHI_SERIES = {"series": [{"ticker": "KXGPT5", "title": "GPT-5 release", "category": "Science and Technology"},
                            {"ticker": "KXNBA", "title": "NBA champion", "category": "Sports"}], "cursor": ""}
KALSHI_MARKETS = {"markets": [
    {"ticker": "KXGPT5-25JUN30", "event_ticker": "KXGPT5-25", "title": "GPT-5 released before July 2025?",
     "rules_primary": "Yes if OpenAI releases GPT-5 before Jul 1 2025.", "open_time": "2025-01-10T15:00:00Z",
     "close_time": "2025-06-30T23:59:00Z", "volume_fp": "1200.5", "liquidity_dollars": "300.0"},
    {"ticker": "KXGPT5-24DEC31", "event_ticker": "KXGPT5-24", "title": "GPT-5 released in 2024?", "rules_primary": "...",
     "open_time": "2024-06-01T00:00:00Z", "close_time": "2024-12-31T23:59:00Z", "volume_fp": "1", "liquidity_dollars": "0"},
], "cursor": ""}
KALSHI_CANDLES_1 = {"candlesticks": []}
KALSHI_CANDLES_60 = {"candlesticks": [
    {"end_period_ts": CUT_E - 5400, "price": {"close_dollars": "0.3100"}, "yes_bid": {"close_dollars": "0.3000"},
     "yes_ask": {"close_dollars": "0.3200"}, "volume_fp": "3"},
    {"end_period_ts": CUT_E + 1800, "price": {"close_dollars": "0.9000"}, "yes_bid": {"close_dollars": "0.89"}, "yes_ask": {"close_dollars": "0.91"}},
]}


def fake_fetcher(calls: list):
    def fetch(url: str):
        calls.append(url)
        if "public-search" in url:
            return 200, json.dumps(POLY_SEARCH)
        if "prices-history" in url:
            return 200, json.dumps(POLY_HIST_1 if "fidelity=1&" in url or url.endswith("fidelity=1") else POLY_HIST_60)
        if "/series?" in url:
            return 200, json.dumps(KALSHI_SERIES)
        if "/markets?series_ticker=" in url:
            return 200, json.dumps(KALSHI_MARKETS)
        if "/candlesticks?" in url:
            return 200, json.dumps(KALSHI_CANDLES_1 if "period_interval=1" in url and "period_interval=1440" not in url else KALSHI_CANDLES_60)
        if "/markets/trades" in url:
            return 200, json.dumps({"trades": []})
        return 404, "not found"
    return fetch


def make_record(L) -> dict:
    """An accepted record shaped by the real builder, statement date 2025-03-01."""
    text = "[00:00:01] hello [00:01:00] I think OpenAI will release GPT-5 before July this year, I'd bet on it"
    rec = {"leader_slug": "ada", "source_id": "s1", "text": text, "yt_upload_date": "20250301", "url": "u", "video_id": "v",
           "yt_title": "T", "declared_venue": "V", "declared_kind": "podcast", "word_count": 20, "duration_sec": 60}
    cand = {"quote": "OpenAI will release GPT-5 before July this year, I'd bet on it", "gates": {g: True for g in L.GATES},
            "gate_notes": "", "resolution_criteria": "By 2025-06-30, OpenAI will have released GPT-5 to the public.",
            "normalized_claim": "OpenAI will release GPT-5 before July 2025.", "category": "technology_product",
            "prediction_type": "binary_event", "target_date": "2025-06-30", "target_date_text": "before July this year",
            "horizon": "explicit", "horizon_years_inferred": None, "horizon_evidence": None, "specificity": "high",
            "subject_control": "external", "confidence": {"type": "qualitative", "probability": None, "verbatim_confidence_language": "I'd bet on it"}}
    loc = L.locate_quote(text, cand["quote"])
    prov = L.normalise_provenance("fable", {"requested_model": "m", "judge_model": "m"}, "default", "claude")
    r = L.make_record(rec, {"name": "Ada", "role": "CEO", "company": "Co"}, cand, loc, prov, "a" * 12, "run", "2026-09-10T00:00:00Z", {})
    v = r["verification"]
    v.update({"status": "ok", "harness": "astra", "requested_model": "g", "served_model": "g", "served_model_verified": False,
              "account": "codex", "router_account_id": "codex", "contract_id": "b" * 12, "run_id": "rv", "verified_at_utc": "2026-09-10T01:00:00Z",
              "gates": {g: True for g in L.GATES}, "attribution": "subject", "claim_faithful": True, "qualifies_stated": True,
              "verifier_resolution_criteria": "x", "notes": None, "telemetry": {}})
    v["qualifies"] = L.verification_qualifies(v)
    v["agreement"] = True
    r["accepted"] = L.compute_accepted(r)
    assert r["accepted"]
    return r


def matcher_returning(verdicts):
    prompts = []

    def matcher(prompt: str):
        prompts.append(prompt)
        pid = re.search(r"\(id ([0-9a-f]{16})\)", prompt).group(1)
        text = json.dumps({"schema_version": "1", "prediction_id": pid, "verdicts": verdicts})
        return text, {}, {"harness": "gemini", "requested_model": "g", "served_model": "g", "served_model_verified": True, "account": "a@b"}
    matcher.prompts = prompts
    return matcher


def contract_for(M, L):
    skill = L.SKILL
    c = L.matching_contract(skill)
    schema = json.loads((skill / L.MATCHER_SCHEMA).read_text())
    return {**c, "spec": (skill / L.MATCHING_SPEC).read_text(), "schema": schema, "schema_text": json.dumps(schema)}


def test_cutoff(M, L) -> None:
    c = L.publication_cutoff({"yt_upload_date": "20250301"})
    check("CUTOFF: date-only -> 00:00:00Z, precision date", c["requested_cutoff_utc"] == CUT and c["precision"] == "date")
    check("CUTOFF: unknown -> unavailable/no_statement_date without any HTTP",
          M.consensus_for_record({"source": {"statement_date": None, "statement_date_basis": "unknown"}, "prediction": {}, "prediction_id": "x" * 16},
                                 M.Cache(Path("/nonexistent"), fetcher=lambda u: (_ for _ in ()).throw(AssertionError("no http")), write=lambda p, t: None),
                                 None, {}, "r")["status"] == "unavailable")
    check("CUTOFF: iso shapes from both platforms normalise",
          M.iso_to_utc("2024-12-23T17:26:41.750649Z") == "2024-12-23T17:26:41Z" and M.iso_to_utc("2024-11-06 15:17:41+00") == "2024-11-06T15:17:41Z"
          and M.iso_to_utc("2024-11-05") == "2024-11-05T00:00:00Z" and M.iso_to_utc(None) is None)


def test_observe(M) -> None:
    pts = [(CUT_E - 3600, {"p": 0.235}), (CUT_E, {"p": 0.5}), (CUT_E + 10, {"p": 0.9}), (CUT_E - 7200, {"p": 0.24})]
    best = M.latest_before(pts, CUT_E)
    check("OBSERVE: latest point STRICTLY before the cutoff wins; a point AT the cutoff never does", best[0] == CUT_E - 3600 and best[1]["p"] == 0.235)
    check("OBSERVE: nothing before the cutoff -> None", M.latest_before([(CUT_E, {}), (CUT_E + 1, {})], CUT_E) is None)
    ob = M.observation(CUT_E - 3600, CUT, 0.235, "same", "polymarket_history_p", 60, None, None, 1.0, None, "u")
    check("OBSERVE: staleness is cutoff minus observation, positive", ob["staleness_sec"] == 3600 and ob["probability_for_claim"] == 0.235)
    ob = M.observation(CUT_E - 3600, CUT, 0.235, "inverse", "polymarket_history_p", 60, 0.2, 0.3, None, None, "u")
    check("OBSERVE: inverse direction flips the price and records bid/ask/midpoint",
          ob["probability_for_claim"] == 0.765 and ob["probability_yes"] == 0.235 and ob["midpoint"] == 0.25)
    calls = []
    cache = M.Cache(Path(tempfile.mkdtemp()), fetcher=fake_fetcher(calls), write=lambda p, t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t)))
    cand = {"platform": "polymarket", "market_id": "514502", "yes_token_id": "526277", "market_open_utc": "2024-12-23T17:26:41Z", "volume": 1.0, "liquidity": None}
    ob = M.observe_polymarket(cache, cand, CUT, "same")
    check("OBSERVE: polymarket walks the fidelity ladder and picks the hourly point before the cutoff",
          ob and ob["observed_at_utc"] == "2025-02-28T23:00:00Z" and ob["probability_yes"] == 0.235 and ob["fidelity_minutes"] == 60, str(ob))
    check("OBSERVE: every prices-history request ends at the cutoff, never later",
          all(f"endTs={CUT_E}" in u for u in calls if "prices-history" in u))
    kc = {"platform": "kalshi", "market_id": "KXGPT5-25JUN30", "series_ticker": "KXGPT5", "market_open_utc": "2025-01-10T15:00:00Z", "volume": 3.0, "liquidity": None}
    ob = M.observe_kalshi(cache, kc, CUT, "same")
    check("OBSERVE: kalshi picks the candle that ENDS before the cutoff with bid and ask",
          ob and ob["probability_yes"] == 0.31 and ob["bid"] == 0.3 and ob["ask"] == 0.32 and ob["price_kind"] == "kalshi_candle_close", str(ob))


def test_candidates(M) -> None:
    calls = []
    cache = M.Cache(Path(tempfile.mkdtemp()), fetcher=fake_fetcher(calls), write=lambda p, t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t)))
    cands, dropped = M.polymarket_candidates(cache, ["GPT-5"], CUT)
    ids = sorted(c["market_id"] for c in cands)
    check("CANDIDATES: polymarket keeps markets live across the cutoff", ids == ["514502", "514503"], str(ids))
    reasons = {d["market_id"]: d["reason"] for d in dropped}
    check("CANDIDATES: opened-after and closed-before are dropped with reasons",
          reasons == {"600000": "opened_after_cutoff", "600001": "closed_before_cutoff"}, str(reasons))
    kc, kd = M.kalshi_candidates(cache, ["openai", "gpt-5", "release"], CUT)
    check("CANDIDATES: kalshi finds the series by title overlap, skips Sports, drops the closed market",
          [c["market_id"] for c in kc] == ["KXGPT5-25JUN30"] and kd[0]["reason"] == "closed_before_cutoff", f"{kc} {kd}")
    check("CANDIDATES: window_ok", M.window_ok("2025-03-01T00:00:00Z", None, CUT) == "opened_after_cutoff"
          and M.window_ok("2024-01-01T00:00:00Z", "2025-02-28T23:59:59Z", CUT) == "closed_before_cutoff"
          and M.window_ok("2024-01-01T00:00:00Z", "2025-03-01T00:00:00Z", CUT) is None)
    check("CANDIDATES: caps hold", M.MAX_CANDIDATES_PER_PLATFORM == 8 and M.POLY_SEARCH_QUERIES == 3)
    qs = M.search_queries("OpenAI will release GPT-5 before July 2025.", "q", "2025-06-30")
    check("CANDIDATES: queries are deterministic, short and carry the rare tokens", len(qs) <= 3 and any("gpt-5" in q.lower() for q in qs), str(qs))


def test_match_and_status(M, L) -> None:
    rec = make_record(L)
    contract = contract_for(M, L)
    calls = []
    tmp = Path(tempfile.mkdtemp())
    wr = lambda p, t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t))  # noqa: E731
    cache = M.Cache(tmp, fetcher=fake_fetcher(calls), write=wr)
    exact_v = [{"platform": "polymarket", "market_id": "514503", "match_type": "exact", "match_confidence": "high", "direction": "same", "rationale": "same proposition, same date"},
               {"platform": "polymarket", "market_id": "514502", "match_type": "proxy", "match_confidence": "medium", "direction": "same", "rationale": "earlier date"},
               {"platform": "kalshi", "market_id": "KXGPT5-25JUN30", "match_type": "exact", "match_confidence": "medium", "direction": "same", "rationale": "same"}]
    m = matcher_returning(exact_v)
    c = M.consensus_for_record(copy.deepcopy(rec), cache, m, contract, "run-m")
    check("MATCH: matcher prompt carries the claim and candidates but no price, volume or liquidity",
          m.prompts and "Normalized claim: OpenAI will release GPT-5" in m.prompts[0]
          and not re.search(r"price|volume|liquidity|probab", m.prompts[0].split("CANDIDATE MARKETS")[1].split("END CANDIDATE")[0], re.I), m.prompts[0][-800:] if m.prompts else "no prompt")
    check("STATUS: matched, with market_probability from the primary exact match's observation",
          c["status"] == "matched" and c["market_probability"] == 0.235 and c["exact_match"]["market_id"] == "514503"
          and c["exact_match"]["observation"]["observed_at_utc"] < CUT, json.dumps(c)[:600])
    check("MATCH: the second exact (other platform) is demoted to proxy; proxies carry no market_probability field",
          sorted(p["market_id"] for p in c["proxy_matches"]) == ["514502", "KXGPT5-25JUN30"]
          and all("market_probability" not in p for p in c["proxy_matches"]) and all(p["match_type"] == "proxy" for p in c["proxy_matches"]))
    check("MATCH: matcher provenance is recorded and the block validates",
          c["matcher"]["harness"] == "gemini" and c["matcher"]["contract_id"] == contract["contract_id"]
          and L.check_schema({**rec, "consensus": c}, L.load_record_schema()) == [], str(L.check_schema({**rec, "consensus": c}, L.load_record_schema()))[:300])
    # Proxy only -> unavailable/proxy_only, no probability.
    c2 = M.consensus_for_record(copy.deepcopy(rec), cache, matcher_returning([{**exact_v[1]}] + [
        {"platform": "polymarket", "market_id": "514503", "match_type": "none", "match_confidence": "low", "direction": "same", "rationale": "n"},
        {"platform": "kalshi", "market_id": "KXGPT5-25JUN30", "match_type": "none", "match_confidence": "low", "direction": "same", "rationale": "n"}]), contract, "r")
    check("STATUS: proxies only -> unavailable/proxy_only with no market_probability",
          c2["status"] == "unavailable" and c2["reason"] == "proxy_only" and c2["market_probability"] is None and len(c2["proxy_matches"]) == 1, json.dumps(c2)[:300])
    # All none -> no_match.
    c3 = M.consensus_for_record(copy.deepcopy(rec), cache, matcher_returning([
        {"platform": p, "market_id": i, "match_type": "none", "match_confidence": "low", "direction": "same", "rationale": "n"}
        for p, i in (("polymarket", "514502"), ("polymarket", "514503"), ("kalshi", "KXGPT5-25JUN30"))]), contract, "r")
    check("STATUS: every verdict none -> no_match with candidates_considered recorded",
          c3["status"] == "no_match" and c3["reason"] == "matcher_found_none" and c3["candidates_considered"] == 3 and c3["exact_match"] is None)
    # Missing verdict -> failed, record stays accepted.
    r4 = copy.deepcopy(rec)
    c4 = M.consensus_for_record(r4, cache, matcher_returning(exact_v[:1]), contract, "r")
    check("STATUS: an incomplete matcher answer -> failed with the error, and the record is still accepted",
          c4["status"] == "failed" and "no verdict" in c4["error"] and r4["accepted"] is True, json.dumps(c4)[:300])
    # HTTP failure -> failed.
    bad = M.Cache(Path(tempfile.mkdtemp()), fetcher=lambda u: (500, "boom"), write=wr)
    c5 = M.consensus_for_record(copy.deepcopy(rec), bad, m, contract, "r")
    check("STATUS: an API failure -> failed with market_api_error", c5["status"] == "failed" and c5["error"].startswith(M.E_MARKET_HTTP))
    # Inverse direction.
    c6 = M.consensus_for_record(copy.deepcopy(rec), cache, matcher_returning([{**exact_v[0], "direction": "inverse"}] + [
        {"platform": "polymarket", "market_id": "514502", "match_type": "none", "match_confidence": "low", "direction": "same", "rationale": "n"},
        {"platform": "kalshi", "market_id": "KXGPT5-25JUN30", "match_type": "none", "match_confidence": "low", "direction": "same", "rationale": "n"}]), contract, "r")
    check("STATUS: inverse exact -> market_probability = 1 - p", c6["status"] == "matched" and c6["market_probability"] == 0.765)
    # The validator accepts the matched block.
    V = load("validate_predictions")
    with tempfile.TemporaryDirectory() as td:
        tx = Path(td) / "tx" / "ada"; tx.mkdir(parents=True)
        (tx / "s1.json").write_text(json.dumps({"text": "[00:00:01] hello [00:01:00] I think OpenAI will release GPT-5 before July this year, I'd bet on it"}))
        pr = Path(td) / "pred"; (pr / "ada").mkdir(parents=True); (pr / "_runs").mkdir()
        full = copy.deepcopy(rec); full["consensus"] = c
        (pr / "ada" / "s1.jsonl").write_text(L.serialise_lines([full]))
        (pr / "ada" / "s1.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 1}, "verify": {"status": "ok", "accepted": 1}}))
        (pr / "_runs" / "r.json").write_text(json.dumps({"extraction_contract": {"contract_id": "a" * 12}, "verification_contract": {"contract_id": "b" * 12}}))
        fails, _ = V.validate_tree(pr, Path(td) / "tx", {}, L.load_record_schema(), V.known_contract_ids(pr))
        check("SCHEMA: the validator passes the block the stage wrote", not fails, "; ".join(f"{f['invariant']}: {f['detail']}" for f in fails[:4]))


def test_cache(M, L) -> None:
    rec = make_record(L)
    contract = contract_for(M, L)
    calls = []
    tmp = Path(tempfile.mkdtemp())
    wr = lambda p, t: (p.parent.mkdir(parents=True, exist_ok=True), p.write_text(t))  # noqa: E731
    cache = M.Cache(tmp, fetcher=fake_fetcher(calls), write=wr)
    v = [{"platform": p, "market_id": i, "match_type": "none", "match_confidence": "low", "direction": "same", "rationale": "n"}
         for p, i in (("polymarket", "514502"), ("polymarket", "514503"), ("kalshi", "KXGPT5-25JUN30"))]
    M.consensus_for_record(copy.deepcopy(rec), cache, matcher_returning(v), contract, "r")
    n1 = len(calls)
    cache2 = M.Cache(tmp, fetcher=fake_fetcher(calls), write=wr)
    M.consensus_for_record(copy.deepcopy(rec), cache2, matcher_returning(v), contract, "r")
    check("CACHE: the second run makes zero HTTP calls and reads from the cache", n1 > 0 and len(calls) == n1 and cache2.calls == 0 and cache2.hits == n1,
          f"first {n1}, second calls {cache2.calls} hits {cache2.hits}")
    check("CACHE: entries carry url, fetched_at_utc, status and body",
          all({"url", "fetched_at_utc", "status", "body"} <= set(json.loads(p.read_text())) for p in tmp.rglob("*.json")))


def test_isolation(M, L) -> None:
    pat = re.compile(r"polymarket|kalshi|market_probability|consensus", re.I)
    for f in ("EXTRACTION.md", "VERIFICATION.md", "extractor_output.schema.json", "verifier_output.schema.json"):
        check(f"ISOLATION: {f} has no market vocabulary", not pat.search((L.SKILL / f).read_text()))
    src = inspect.getsource(L.build_extraction_prompt) + inspect.getsource(L.build_verification_prompt) + inspect.getsource(L.speaker_header)
    check("ISOLATION: the extraction and verification prompt builders have no market vocabulary", not pat.search(src))
    D = load("extract_predictions")
    check("ISOLATION: the extraction driver never imports the market stage", "market_consensus" not in inspect.getsource(D))
    check("ISOLATION: the market stage never writes confidence.probability",
          "confidence" not in inspect.getsource(M.consensus_for_record) and "confidence" not in inspect.getsource(M.process_file))


def main() -> int:
    L = load("predictions_lib")
    M = load("market_consensus")
    test_cutoff(M, L)
    test_observe(M)
    test_candidates(M)
    test_match_and_status(M, L)
    test_cache(M, L)
    test_isolation(M, L)
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
