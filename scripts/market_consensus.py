#!/usr/bin/env python3
"""Stage 3: attach contemporaneous prediction-market evidence to ACCEPTED predictions.

Runs only on records that extraction and verification both accepted, after
those stages, from this script, and never re-runs them. For each record:

  1. cutoff    P_market(t^-): the latest valid market observation STRICTLY
               before the prediction became public. This corpus knows only a
               YouTube upload date, so the cutoff is 00:00:00 UTC at the start
               of that date (precision: date). Never a current price.
  2. retrieve  Polymarket (Gamma public-search) and Kalshi (series catalogue,
               events, markets) candidates by keyword, through their public
               APIs. A market that opened at or after the cutoff, or closed
               before it, is dropped with the reason recorded. No model here.
  3. match     ONE model call judges semantic match only: exact | proxy | none,
               with confidence, direction and a rationale. It never sees a price.
  4. observe   the price comes from the market's own history (Polymarket CLOB
               prices-history; Kalshi candlesticks, then trades), the last
               point strictly before the cutoff, with staleness recorded.
  5. status    matched (an exact match with an observation), no_match (nothing
               relevant), unavailable (matches but no ex-ante observation, or
               proxies only, or no date), failed (an API or model error).

Only an exact match may set market_probability. Proxies are context. The
speaker's confidence.probability is never touched. Every HTTP response is
cached under <predictions>/_markets so a rerun is free and reproducible;
--refresh-cache bypasses. no_match is the normal result.

  .venv/bin/python scripts/market_consensus.py
  .venv/bin/python scripts/market_consensus.py --leaders sam-altman --dry-run
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predictions_lib as L  # noqa: E402
from extract_predictions import Router, RouterUnavailable, call_harness, log  # noqa: E402
from grade import agy_profiles  # noqa: E402

POLY_GAMMA = "https://gamma-api.polymarket.com"
POLY_CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY_SEARCH_QUERIES = 3
MAX_CANDIDATES_PER_PLATFORM = 8
KALSHI_CATEGORIES = {"Science and Technology", "Companies", "Economics", "Financials", "Politics",
                     "World", "Crypto", "Climate and Weather", "Elections"}
KALSHI_MAX_SERIES = 5
E_MARKET_HTTP = "market_api_error"
E_MATCHER = "matcher_error"

STOP = set("""a an the and or of to in on at by for with from as is are was were be been being will would
could should may might can this that these those it its their his her our we you they i he she them
us not no yes if then than so very more most much many any some such over under about into out up
down there here when where which who whom what how all each every both few other own same do does
did done have has had having going get got make made say said think thinks thought believe expect
year years next this last within between around roughly about""".split())


def utc_epoch(s: str) -> int:
    return int(L.parse_utc(s).timestamp())


def epoch_utc(e: int | float) -> str:
    return datetime.fromtimestamp(int(e), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_to_utc(s: str | None) -> str | None:
    """Platform timestamps in several shapes -> YYYY-MM-DDTHH:MM:SSZ, or None."""
    if not s:
        return None
    s = s.strip().replace(" ", "T")
    s = re.sub(r"\.\d+", "", s)
    s = re.sub(r"\+00(:00)?$", "Z", s)
    if not s.endswith("Z"):
        s += "Z"
    try:
        L.parse_utc(s)
        return s
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%dZ").strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# HTTP with a durable cache. The fetcher is injectable so tests use no network.
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "verbatim-predictions/1 (+https://verbatim-index.tonygwu.com)",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


class Cache:
    """<root>/<platform>/<sha256(url)>.json holding url, fetched_at_utc, status, body."""

    def __init__(self, root: Path, fetcher=http_get, refresh: bool = False, write=None):
        self.root = root
        self.fetcher = fetcher
        self.refresh = refresh
        self.write = write or (lambda p, t: L.write_prediction_file(p, t))
        self.calls = 0
        self.hits = 0
        self._lock = threading.Lock()

    def get_json(self, platform: str, url: str):
        path = self.root / platform / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if path.exists() and not self.refresh:
            d = json.loads(path.read_text())
            with self._lock:
                self.hits += 1
            if d["status"] != 200:
                raise RuntimeError(f"{E_MARKET_HTTP}: cached {d['status']} for {url}")
            return json.loads(d["body"])
        with self._lock:
            self.calls += 1
        status, body = self.fetcher(url)
        self.write(path, json.dumps({"url": url, "fetched_at_utc": L.utc_now(), "status": status, "body": body}))
        if status != 200:
            raise RuntimeError(f"{E_MARKET_HTTP}: HTTP {status} for {url}: {body[:200]}")
        return json.loads(body)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def content_tokens(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-']+|\d{4}|\d+(?:\.\d+)?%?", text)
    out = []
    for t in toks:
        tl = t.lower().strip("'-")
        if tl in STOP or len(tl) < 2:
            continue
        if tl not in out:
            out.append(tl)
    return out


def search_queries(claim: str, quote: str, target_date: str | None) -> list[str]:
    """Up to POLY_SEARCH_QUERIES short keyword queries. Deterministic, no model."""
    toks = content_tokens(claim)
    words = [t for t in toks if not re.fullmatch(r"\d+(?:\.\d+)?%?", t)]
    caps = [t for t in re.findall(r"\b[A-Z][A-Za-z0-9\-]+\b", claim) if t.lower() not in STOP]
    nums = re.findall(r"\b\d{4}\b|\b\d+(?:\.\d+)?%?", claim)
    year = target_date[:4] if target_date else None
    rare = sorted(words, key=lambda w: (-len(w), words.index(w)))[:2]   # long words are rarer than short ones
    qs = []
    if words:
        qs.append(" ".join(words[:4]))
    if caps or nums:
        qs.append(" ".join(dict.fromkeys(caps[:3] + nums[:2])))
    if rare:
        qs.append(" ".join(rare + ([year] if year else [])))
    out = []
    for q in qs:
        q = q.strip()
        if q and q.lower() not in [o.lower() for o in out]:
            out.append(q)
    return out[:POLY_SEARCH_QUERIES]


def window_ok(open_utc: str | None, close_utc: str | None, cutoff_utc: str) -> str | None:
    """None when the market could carry an ex-ante price for this cutoff, else the drop reason."""
    cut = utc_epoch(cutoff_utc)
    if open_utc and utc_epoch(open_utc) >= cut:
        return "opened_after_cutoff"
    if close_utc and utc_epoch(close_utc) < cut:
        return "closed_before_cutoff"
    return None


def latest_before(points: list[tuple[int, dict]], cut_epoch: int) -> tuple[int, dict] | None:
    """The point with the greatest timestamp STRICTLY less than the cutoff, or None."""
    best = None
    for ts, payload in points:
        if ts < cut_epoch and (best is None or ts > best[0]):
            best = (ts, payload)
    return best


def observation(ts: int, cutoff_utc: str, p_yes: float, direction: str, price_kind: str, fidelity: int | None,
                bid: float | None, ask: float | None, volume, liquidity, source_url: str) -> dict:
    p_yes = round(float(p_yes), 6)
    p_claim = round(1 - p_yes, 6) if direction == "inverse" else p_yes
    mid = round((bid + ask) / 2, 6) if bid is not None and ask is not None else None
    return {"observed_at_utc": epoch_utc(ts), "probability_yes": p_yes, "probability_for_claim": p_claim,
            "bid": bid, "ask": ask, "midpoint": mid, "price_kind": price_kind, "fidelity_minutes": fidelity,
            "staleness_sec": utc_epoch(cutoff_utc) - ts, "volume": volume, "liquidity": liquidity,
            "source_url": source_url}


def pick_primary_exact(exacts: list[dict], target_date: str | None) -> dict | None:
    """Highest confidence, then Polymarket (deeper history), then closest close to the target date."""
    if not exacts:
        return None
    rank = {"high": 0, "medium": 1, "low": 2}
    tgt = None
    if target_date:
        full = target_date + {4: "-12-31", 7: "-28", 10: ""}[len(target_date)]
        tgt = utc_epoch(full + "T00:00:00Z")

    def key(m):
        close = utc_epoch(m["market_close_utc"]) if m.get("market_close_utc") else 0
        return (rank[m["match_confidence"]], 0 if m["platform"] == "polymarket" else 1,
                abs(close - tgt) if tgt else 0)
    return sorted(exacts, key=key)[0]


def compute_status(exact: dict | None, proxies: list[dict], had_candidates: bool, cutoff: dict) -> tuple[str, str | None]:
    if cutoff["requested_cutoff_utc"] is None:
        return "unavailable", "no_statement_date"
    if not had_candidates:
        return "no_match", "no_candidates"
    if exact is None and not proxies:
        return "no_match", "matcher_found_none"
    if exact is not None and exact.get("observation"):
        return "matched", None
    if exact is not None:
        return "unavailable", "no_observation_before_cutoff"
    return "unavailable", "proxy_only"


# ---------------------------------------------------------------------------
# Candidate retrieval
# ---------------------------------------------------------------------------

def polymarket_candidates(cache: Cache, queries: list[str], cutoff_utc: str) -> tuple[list[dict], list[dict]]:
    cands, dropped, seen = [], [], set()
    for q in queries:
        url = f"{POLY_GAMMA}/public-search?q={urllib.parse.quote(q)}&limit_per_type=5"
        d = cache.get_json("polymarket", url)
        for ev in d.get("events") or []:
            for m in ev.get("markets") or []:
                mid = str(m.get("id"))
                if mid in seen:
                    continue
                seen.add(mid)
                open_utc, close_utc = iso_to_utc(m.get("startDate")), iso_to_utc(m.get("endDate"))
                why = window_ok(open_utc, close_utc, cutoff_utc)
                if why:
                    dropped.append({"platform": "polymarket", "market_id": mid, "reason": why})
                    continue
                try:
                    tokens = json.loads(m.get("clobTokenIds") or "[]")
                except json.JSONDecodeError:
                    tokens = []
                if not tokens:
                    dropped.append({"platform": "polymarket", "market_id": mid, "reason": "no_clob_token"})
                    continue
                cands.append({"platform": "polymarket", "market_id": mid, "market_slug": m.get("slug"),
                              "market_url": f"https://polymarket.com/market/{m.get('slug')}",
                              "question": m.get("question") or ev.get("title") or "",
                              "resolution_text": (m.get("description") or None),
                              "market_open_utc": open_utc, "market_close_utc": close_utc,
                              "yes_token_id": str(tokens[0]),
                              "volume": _num(m.get("volumeNum") or m.get("volume")),
                              "liquidity": _num(m.get("liquidityNum") or m.get("liquidity"))})
    return cands[:MAX_CANDIDATES_PER_PLATFORM], dropped


def _num(v):
    try:
        return None if v in (None, "", "None") else float(v)
    except (TypeError, ValueError):
        return None


def kalshi_series(cache: Cache) -> list[dict]:
    out, cursor = [], None
    for _ in range(40):  # ~14k series at 1000 per page; a hard stop keeps a broken cursor finite
        url = f"{KALSHI}/series?limit=1000" + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else "")
        d = cache.get_json("kalshi", url)
        out.extend(d.get("series") or [])
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def kalshi_candidates(cache: Cache, claim_tokens: list[str], cutoff_utc: str,
                      series: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    series = kalshi_series(cache) if series is None else series
    scored = []
    ctoks = set(claim_tokens)
    for s in series:
        if s.get("category") not in KALSHI_CATEGORIES:
            continue
        toks = set(content_tokens(s.get("title") or ""))
        score = len(toks & ctoks)
        if score >= 1:
            scored.append((score, s.get("ticker"), s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    cands, dropped = [], []
    for _score, ticker, s in scored[:KALSHI_MAX_SERIES]:
        url = f"{KALSHI}/markets?series_ticker={urllib.parse.quote(ticker)}&limit=100"
        d = cache.get_json("kalshi", url)
        for m in d.get("markets") or []:
            open_utc, close_utc = iso_to_utc(m.get("open_time")), iso_to_utc(m.get("close_time"))
            why = window_ok(open_utc, close_utc, cutoff_utc)
            if why:
                dropped.append({"platform": "kalshi", "market_id": m.get("ticker"), "reason": why})
                continue
            rules = " ".join(x for x in (m.get("rules_primary"), m.get("rules_secondary")) if x) or None
            cands.append({"platform": "kalshi", "market_id": m.get("ticker"), "market_slug": m.get("event_ticker"),
                          "market_url": f"https://kalshi.com/markets/{str(ticker).lower()}",
                          "question": m.get("title") or s.get("title") or "",
                          "resolution_text": rules, "market_open_utc": open_utc, "market_close_utc": close_utc,
                          "series_ticker": ticker, "volume": _num(m.get("volume_fp")),
                          "liquidity": _num(m.get("liquidity_dollars"))})
            if len(cands) >= MAX_CANDIDATES_PER_PLATFORM:
                return cands, dropped
    return cands, dropped


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def observe_polymarket(cache: Cache, cand: dict, cutoff_utc: str, direction: str) -> dict | None:
    cut = utc_epoch(cutoff_utc)
    open_e = utc_epoch(cand["market_open_utc"]) if cand.get("market_open_utc") else cut - 400 * 86400
    ladder = [(1, cut - 2 * 86400), (60, cut - 30 * 86400), (1440, open_e)]
    for fidelity, start in ladder:
        start = max(start, open_e)
        if start >= cut:
            continue
        url = (f"{POLY_CLOB}/prices-history?market={cand['yes_token_id']}&startTs={start}&endTs={cut}&fidelity={fidelity}")
        d = cache.get_json("polymarket", url)
        pts = [(int(p["t"]), p) for p in d.get("history") or [] if "t" in p and "p" in p]
        best = latest_before(pts, cut)
        if best:
            ts, p = best
            return observation(ts, cutoff_utc, p["p"], direction, "polymarket_history_p", fidelity, None, None,
                               cand.get("volume"), cand.get("liquidity"), url)
    return None


def observe_kalshi(cache: Cache, cand: dict, cutoff_utc: str, direction: str) -> dict | None:
    cut = utc_epoch(cutoff_utc)
    open_e = utc_epoch(cand["market_open_utc"]) if cand.get("market_open_utc") else cut - 400 * 86400
    ladder = [(1, cut - 2 * 86400), (60, cut - 30 * 86400), (1440, open_e)]
    for period, start in ladder:
        start = max(start, open_e)
        if start >= cut:
            continue
        url = (f"{KALSHI}/series/{urllib.parse.quote(cand['series_ticker'])}/markets/{urllib.parse.quote(cand['market_id'])}"
               f"/candlesticks?start_ts={start}&end_ts={cut}&period_interval={period}")
        d = cache.get_json("kalshi", url)
        pts = []
        for c in d.get("candlesticks") or []:
            price = (c.get("price") or {}).get("close_dollars")
            if price is None or c.get("end_period_ts") is None:
                continue
            pts.append((int(c["end_period_ts"]), c))
        best = latest_before(pts, cut)
        if best:
            ts, c = best
            bid = _num((c.get("yes_bid") or {}).get("close_dollars"))
            ask = _num((c.get("yes_ask") or {}).get("close_dollars"))
            return observation(ts, cutoff_utc, float(c["price"]["close_dollars"]), direction, "kalshi_candle_close",
                               period, bid, ask, cand.get("volume"), cand.get("liquidity"), url)
    url = f"{KALSHI}/markets/trades?ticker={urllib.parse.quote(cand['market_id'])}&max_ts={cut - 1}&limit=1"
    d = cache.get_json("kalshi", url)
    pts = []
    for t in d.get("trades") or []:
        ts = iso_to_utc(t.get("created_time"))
        if ts and t.get("yes_price_dollars") is not None:
            pts.append((utc_epoch(ts), t))
    best = latest_before(pts, cut)
    if best:
        ts, t = best
        return observation(ts, cutoff_utc, float(t["yes_price_dollars"]), direction, "kalshi_trade", None, None, None,
                           cand.get("volume"), cand.get("liquidity"), url)
    return None


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def build_matching_prompt(rec: dict, candidates: list[dict], spec: str, schema: str) -> str:
    """No price, volume or liquidity field reaches the matcher."""
    p, s = rec["prediction"], rec["source"]
    blocks = []
    for c in candidates:
        blocks.append(f"--- CANDIDATE {c['platform']} {c['market_id']} ---\n"
                      f"QUESTION: {c['question']}\n"
                      f"RESOLUTION TEXT: {(c.get('resolution_text') or 'not available')[:700]}\n"
                      f"OPENS: {c.get('market_open_utc') or 'unknown'}   CLOSES: {c.get('market_close_utc') or 'unknown'}\n")
    ids = " ".join(f"{c['platform']}:{c['market_id']}" for c in candidates)
    return f"""You judge whether prediction-market contracts are about the same proposition as one public
prediction. Apply the specification and return one JSON object. You never see or output a price.

=========================== MATCHING SPEC ===========================
{spec}
======================== END MATCHING SPEC ==========================

THE PREDICTION (id {rec['prediction_id']})
Speaker: {rec['speaker']['name']}
Statement date: {s['statement_date'] or 'unknown'}
Normalized claim: {p['normalized_claim']}
Verbatim quote: {s['quote_original']}
Target date: {p['target_date'] or 'none stated'} ({p['target_date_text'] or 'no words'})
Resolution criteria written at extraction: {p['resolution_criteria']}

=========================== CANDIDATE MARKETS ===========================
{chr(10).join(blocks)}
======================== END CANDIDATE MARKETS ==========================

Return ONE JSON object and nothing else. It must validate against this schema:

{schema}

Requirements that are checked automatically:
- prediction_id must be exactly: {rec['prediction_id']}
- verdicts must contain exactly one entry for each candidate, identified by platform and market_id: {ids}
- At most one exact match per platform."""


def apply_matcher(candidates: list[dict], obj: dict) -> tuple[list[dict], list[dict], list[str]]:
    """Pure: matcher verdicts -> (exacts, proxies, errors)."""
    by_key = {(c["platform"], str(c["market_id"])): c for c in candidates}
    seen, exacts, proxies, errors = set(), [], [], []
    for v in obj["verdicts"]:
        key = (v["platform"], str(v["market_id"]))
        if key not in by_key:
            errors.append(f"verdict for unknown candidate {key}")
            continue
        if key in seen:
            errors.append(f"duplicate verdict for {key}")
            continue
        seen.add(key)
        if v["match_type"] == "none":
            continue
        m = {k: by_key[key].get(k) for k in ("platform", "market_id", "market_slug", "market_url", "question",
                                                "resolution_text", "market_open_utc", "market_close_utc")}
        m.update({"match_type": v["match_type"], "match_confidence": v["match_confidence"],
                  "direction": v["direction"], "rationale": v["rationale"], "observation": None,
                  "_cand": by_key[key]})
        (exacts if v["match_type"] == "exact" else proxies).append(m)
    missing = set(by_key) - seen
    if missing:
        errors.append(f"no verdict for {sorted(missing)}")
    # At most one exact per platform: demote the rest to proxy.
    per = {}
    for m in exacts:
        per.setdefault(m["platform"], []).append(m)
    kept = []
    for plat, ms in per.items():
        ms.sort(key=lambda m: {"high": 0, "medium": 1, "low": 2}[m["match_confidence"]])
        kept.append(ms[0])
        for extra in ms[1:]:
            extra["match_type"] = "proxy"
            proxies.append(extra)
    return kept, proxies, errors


def strip_private(m: dict) -> dict:
    return {k: v for k, v in m.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# One record
# ---------------------------------------------------------------------------

def consensus_for_record(rec: dict, cache: Cache, matcher, contract: dict, run_id: str,
                         kalshi_catalogue: list[dict] | None = None) -> dict:
    """matcher(prompt) -> (text, telemetry, provenance) or None when there is nothing to judge."""
    cutoff = L.publication_cutoff(rec)
    base = {"status": "failed", "reason": None, "cutoff": cutoff, "market_probability": None, "exact_match": None,
            "proxy_matches": [], "candidates_considered": 0, "candidates_dropped": [], "matcher": None,
            "searched_at_utc": L.utc_now(), "error": None}
    if cutoff["requested_cutoff_utc"] is None:
        return {**base, "status": "unavailable", "reason": "no_statement_date"}
    cut = cutoff["requested_cutoff_utc"]
    p, s = rec["prediction"], rec["source"]
    try:
        queries = search_queries(p["normalized_claim"], s["quote_original"], p["target_date"])
        pc, pd = polymarket_candidates(cache, queries, cut)
        kc, kd = kalshi_candidates(cache, content_tokens(p["normalized_claim"]), cut, kalshi_catalogue)
    except RuntimeError as exc:
        return {**base, "error": str(exc)[:600]}
    candidates, dropped = pc + kc, pd + kd
    base.update({"candidates_considered": len(candidates), "candidates_dropped": dropped})
    if not candidates:
        return {**base, "status": "no_match", "reason": "no_candidates"}
    try:
        text, telemetry, prov = matcher(build_matching_prompt(rec, candidates, contract["spec"], contract["schema_text"]))
        obj = L.extract_json(text)
        errs = L.check_schema(obj, contract["schema"])
        if errs:
            raise RuntimeError(f"{L.E_SCHEMA}: {'; '.join(errs[:4])}")
        if obj.get("prediction_id") != rec["prediction_id"]:
            raise RuntimeError(f"{L.E_SCHEMA}: prediction_id {obj.get('prediction_id')!r} != {rec['prediction_id']}")
        exacts, proxies, merrs = apply_matcher(candidates, obj)
        if merrs:
            raise RuntimeError(f"{L.E_SCHEMA}: {'; '.join(merrs[:3])}")
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return {**base, "error": f"{E_MATCHER}: {exc}"[:600]}
    base["matcher"] = {**{k: prov.get(k) for k in ("harness", "requested_model", "served_model", "served_model_verified", "account")},
                       "contract_id": contract["contract_id"], "run_id": run_id, "matched_at_utc": L.utc_now()}
    try:
        for m in exacts + proxies:
            fn = observe_polymarket if m["platform"] == "polymarket" else observe_kalshi
            m["observation"] = fn(cache, m["_cand"], cut, m["direction"])
    except RuntimeError as exc:
        return {**base, "error": str(exc)[:600]}
    primary = pick_primary_exact([m for m in exacts if m["observation"]], p["target_date"]) \
        or pick_primary_exact(exacts, p["target_date"])
    for m in exacts:
        if m is not primary:
            m["match_type"] = "proxy"
            proxies.append(m)
    status, reason = compute_status(primary, proxies, True, cutoff)
    out = {**base, "status": status, "reason": reason,
           "exact_match": strip_private(primary) if primary else None,
           "proxy_matches": [strip_private(m) for m in proxies],
           "market_probability": primary["observation"]["probability_for_claim"] if status == "matched" else None}
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def make_matcher(router: Router, args, run_id: str, workroot: Path):
    counter = {"n": 0}
    lock = threading.Lock()

    def matcher(prompt: str):
        with lock:
            counter["n"] += 1
            n = counter["n"]
        route = router.pick(None if args.matcher == "auto" else args.matcher, None)
        wd = workroot / f"match__{run_id}__{n}"
        wd.mkdir(parents=True, exist_ok=True)
        text, telemetry, account = call_harness(route, prompt, args.timeout, wd, args)
        prov = L.normalise_provenance(route["harness"], telemetry, account, route["account_id"])
        return text, telemetry, prov
    return matcher


def process_file(job: dict) -> dict:
    args, path = job["args"], Path(job["path"])
    recs = L.parse_lines(path.read_text(), str(path))
    todo = [r for r in recs if r["accepted"] and (args.force or r["consensus"] == L.SENTINEL_CONSENSUS)]
    res = {"file": str(path), "records": len(recs), "todo": len(todo), "by_status": {}, "errors": []}
    if not todo:
        return {**res, "status": "nothing_to_do"}
    if args.dry_run:
        return {**res, "status": "dry_run"}
    changed = False
    for r in todo:
        try:
            c = consensus_for_record(r, job["cache"], job["matcher"], job["contract"], job["run_id"], job["kalshi"])
        except (RouterUnavailable, RuntimeError) as exc:
            c = {"status": "failed", "reason": None, "cutoff": L.publication_cutoff(r), "market_probability": None,
                 "exact_match": None, "proxy_matches": [], "candidates_considered": 0, "candidates_dropped": [],
                 "matcher": None, "searched_at_utc": L.utc_now(), "error": str(exc)[:600]}
        r["consensus"] = c
        changed = True
        res["by_status"][c["status"]] = res["by_status"].get(c["status"], 0) + 1
        if c.get("error"):
            res["errors"].append({"prediction_id": r["prediction_id"], "error_type": L.classify_exception_detail(c["error"]),
                                  "detail": c["error"]})
    if changed:
        L.write_prediction_file(path, L.serialise_lines(recs))
    return {**res, "status": "ok"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", default="data/predictions")
    ap.add_argument("--leaders", default="")
    ap.add_argument("--limit", type=int, default=None, help="at most N prediction files")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--matcher", choices=["auto", "fable", "astra", "gemini"], default="auto")
    ap.add_argument("--router-exclude", default="antigravity_claude")
    ap.add_argument("--allow-degraded", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fable-bin", default="claude")
    ap.add_argument("--agy-bin", default="agy")
    ap.add_argument("--astra-model", default="gpt-6-astra")
    ap.add_argument("--gemini-model", default="gemini-3.8-flash-high")
    ap.add_argument("--skill-dir", default=str(L.SKILL))
    return ap


def main(argv: list[str] | None = None) -> int:
    import os
    args = build_parser().parse_args(argv)
    if Path(args.fable_bin).name == "cl":
        raise SystemExit("refusing --fable-bin cl (see AGENTS.md)")
    root = L.guard_data_path(args.predictions)
    files = sorted(p for p in root.glob("*/*.jsonl") if not p.parent.name.startswith("_"))
    if args.leaders:
        want = set(args.leaders.split(","))
        files = [f for f in files if f.parent.name in want]
    if args.limit is not None:
        files = files[: args.limit]
    skill = Path(args.skill_dir)
    c = L.matching_contract(skill)
    contract = {**c, "spec": (skill / L.MATCHING_SPEC).read_text(),
                "schema": json.loads((skill / L.MATCHER_SCHEMA).read_text())}
    contract["schema_text"] = json.dumps(contract["schema"], indent=1)
    run_id = f"{L.utc_now().replace(':', '').replace('-', '')}-consensus-{secrets.token_hex(4)}"
    cache = Cache(root / "_markets", refresh=args.refresh_cache)
    log(f"[run {run_id}] {len(files)} prediction files, matcher contract {c['contract_id']}, cache {cache.root}")
    matcher = None
    kalshi = None
    if not args.dry_run:
        router = Router([x for x in args.router_exclude.split(",") if x], args.allow_degraded, agy_profiles())
        workroot = Path(os.environ.get("TMPDIR", "/tmp")) / "predict-work"
        matcher = make_matcher(router, args, run_id, workroot)
        kalshi = kalshi_series(cache)
        log(f"[run {run_id}] kalshi series catalogue: {len(kalshi)} entries")
    results = []
    jobs = [{"args": args, "path": str(f), "cache": cache, "matcher": matcher, "contract": contract, "run_id": run_id,
             "kalshi": kalshi} for f in files]
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in cf.as_completed([ex.submit(process_file, j) for j in jobs]):
            try:
                r = fut.result()
            except L.RefusedDataWrite:
                raise
            except Exception as exc:  # noqa: BLE001
                r = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:400]}
            results.append(r)
            log(json.dumps(r, ensure_ascii=False)[:300])
    by = {}
    for r in results:
        for k, v in (r.get("by_status") or {}).items():
            by[k] = by.get(k, 0) + v
    tax = {}
    for r in results:
        for e in r.get("errors") or []:
            tax[e["error_type"]] = tax.get(e["error_type"], 0) + 1
    summary = {"run_id": run_id, "files": len(files), "attempted_records": sum(r.get("todo", 0) for r in results),
               "by_status": by, "error_taxonomy": tax, "http_calls": cache.calls, "cache_hits": cache.hits,
               "file_failures": sum(1 for r in results if r["status"] == "failed")}
    if not args.dry_run:
        L.write_prediction_file(root / "_runs" / f"{run_id}.json",
                                json.dumps({"summary": summary, "matching_contract": c, "args": vars(args), "results": results,
                                            "finished_at_utc": L.utc_now()}, indent=1, sort_keys=True, ensure_ascii=False))
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["file_failures"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
