#!/usr/bin/env python3
"""The predictions page must show what was said, never a verdict, and must deploy from the right config.

  FIXTURE    renders from a synthetic index.json plus jsonl; DATA, SRC and PRED parse
  NEUTRAL    no evaluative vocabulary outside the fenced disclaimer and the data constants
  SORT       alphabetical by default, static aria-sort, exact column keys, DATA alphabetical
  TIMESTAMP  [01:02:03] gives t 3723 and a YouTube link at that second; a null mark gives no link
  REJECTED   a rejected candidate's quote never reaches the page; its count does
  TRIM       telemetry, gates, offsets and harness internals are not embedded
  PROVENANCE run ids, contract ids and both model names are on the page
  ESCAPE     a quote containing </script> cannot end the script block
  STALE      an index count that disagrees with the files fails the render, naming the person
  MARKET     a matched market renders its number, platform, match type and staleness; a proxy renders no number
  ATOMIC     the builder writes through write_atomic
  XLINK      each page links to the other
  THEME      both pages carry the shared tokens through site_theme
  WRANGLER   the predictions Worker config names its own Worker, directory, 404 mode and hostname
  GITIGNORE  site-predictions/index.html is ignored
  DEPLOY     deploy_predictions.sh renders before it deploys, passes -c, guards --refresh, refuses unknown flags
  GUARD-LIVE from a non-daemon clone, --refresh --dry-run is refused (SKIP in the daemon clone)

  .venv/bin/python scripts/test_predictions_site.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import tomllib
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


TEXT = ("[00:00:01] welcome everyone [01:02:03] by 2030 most code will be written by AI I would say that is my bet "
        "and REJECTED-MARKER-QUOTE should never be shown to anyone here and later "
        "[01:05:00] we will see 30 gigawatts of new capacity in 2026 </script><b>bold</b> and that is that "
        "and finally rates will be lower next year for sure")


def rec(L, slug, sid, quote, accepted, upload="20250301", video="vid123", mark_expected=None, consensus=None, ctype="none"):
    r0 = {"leader_slug": slug, "source_id": sid, "text": TEXT, "yt_upload_date": upload, "url": f"https://www.youtube.com/watch?v={video}" if video else "https://pod/x",
          "video_id": video, "yt_title": f"{slug} talk", "declared_venue": "Pod", "declared_kind": "podcast", "word_count": 60, "duration_sec": 4000}
    conf = {"none": {"type": "none", "probability": None, "verbatim_confidence_language": None},
            "qualitative": {"type": "qualitative", "probability": None, "verbatim_confidence_language": "for sure"}}[ctype]
    cand = {"quote": quote, "gates": {g: True for g in L.GATES}, "gate_notes": "", "resolution_criteria": "By 2030-12-31, X",
            "normalized_claim": f"Claim about {quote[:20]}", "category": "ai_capability", "prediction_type": "milestone",
            "target_date": "2030", "target_date_text": "by 2030", "horizon": "explicit", "horizon_years_inferred": None,
            "horizon_evidence": None, "specificity": "high", "subject_control": "external", "confidence": conf}
    loc = L.locate_quote(TEXT, quote)
    assert "start" in loc, (quote, loc)
    prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}, "default", "claude")
    r = L.make_record(r0, {"name": slug.title(), "role": "CEO", "company": "Co"}, cand, loc, prov, "a" * 12, "run-x", "2026-09-10T00:00:00Z", {"secret_telemetry": 1})
    v = r["verification"]
    v.update({"status": "ok", "harness": "astra", "requested_model": "gpt-6-astra", "served_model": "gpt-6-astra", "served_model_verified": False,
              "account": "codex", "router_account_id": "codex", "contract_id": "b" * 12, "run_id": "run-v", "verified_at_utc": "2026-09-10T01:00:00Z",
              "gates": {g: True for g in L.GATES}, "attribution": "subject" if accepted else "interviewer", "claim_faithful": True,
              "qualifies_stated": accepted, "verifier_resolution_criteria": "verifier says by 2030", "notes": None, "telemetry": {"secret_telemetry": 2}})
    v["qualifies"] = L.verification_qualifies(v)
    v["agreement"] = r["extraction"]["qualifies"] == v["qualifies"]
    r["accepted"] = L.compute_accepted(r)
    if consensus:
        r["consensus"] = consensus
    return r


def matched_consensus(L, r, direction="same"):
    return {"status": "matched", "reason": None, "cutoff": L.publication_cutoff(r), "market_probability": 0.27,
            "exact_match": {"platform": "polymarket", "market_id": "1", "market_slug": "s", "market_url": "https://polymarket.com/market/s",
                            "question": "Will most code be AI-written by 2030?", "resolution_text": "r", "market_open_utc": "2024-01-01T00:00:00Z",
                            "market_close_utc": "2030-12-31T00:00:00Z", "match_type": "exact", "match_confidence": "high", "direction": direction,
                            "rationale": "same proposition", "observation": {"observed_at_utc": "2025-02-28T23:46:00Z", "probability_yes": 0.27,
                            "probability_for_claim": 0.27, "bid": None, "ask": None, "midpoint": None, "price_kind": "polymarket_history_p",
                            "fidelity_minutes": 1, "staleness_sec": 840, "volume": 1.0, "liquidity": None, "source_url": "https://clob/x"}},
            "proxy_matches": [{"platform": "kalshi", "market_id": "K", "market_slug": "k", "market_url": "https://kalshi.com/markets/k",
                               "question": "PROXY-QUESTION about AI code", "resolution_text": None, "market_open_utc": None, "market_close_utc": None,
                               "match_type": "proxy", "match_confidence": "medium", "direction": "same", "rationale": "broader", "observation": None}],
            "candidates_considered": 2, "candidates_dropped": [], "matcher": {"harness": "gemini", "requested_model": "g", "served_model": "g",
            "served_model_verified": True, "account": "a", "contract_id": "c" * 12, "run_id": "run-m", "matched_at_utc": "2026-09-10T02:00:00Z"},
            "searched_at_utc": "2026-09-10T02:00:00Z", "error": None}


def build(td: Path, L, A) -> tuple[Path, Path, Path]:
    pr = td / "pred"
    (pr / "ada").mkdir(parents=True); (pr / "alan").mkdir()
    ada = [rec(L, "ada", "s1", "by 2030 most code will be written by AI I would say that is my bet", True),
           rec(L, "ada", "s1", "REJECTED-MARKER-QUOTE should never be shown to anyone here", False),
           rec(L, "ada", "s1", "we will see 30 gigawatts of new capacity in 2026 </script><b>bold</b> and that is that", True)]
    ada[0]["consensus"] = matched_consensus(L, ada[0])
    (pr / "ada" / "s1.jsonl").write_text(L.serialise_lines(ada))
    (pr / "ada" / "s1.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 3, "harness": "fable"}, "verify": {"status": "ok", "accepted": 2}}))
    alan = [rec(L, "alan", "s2", "rates will be lower next year for sure", True, upload=None, video=None, ctype="qualitative")]
    (pr / "alan" / "s2.jsonl").write_text(L.serialise_lines(alan))
    (pr / "alan" / "s2.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 1, "harness": "astra"}, "verify": {"status": "ok", "accepted": 1}}))
    roster = td / "roster.json"
    roster.write_text(json.dumps({"roster": [{"slug": "ada", "name": "Ada L", "role": "CEO", "company": "Co", "sector": "AI"},
                                             {"slug": "alan", "name": "Alan T", "role": "Founder", "company": "Lab", "sector": "AI"}]}))
    index = A.build_index(pr, {"ada": {"name": "Ada L", "company": "Co", "role": "CEO", "sector": "AI"},
                               "alan": {"name": "Alan T", "company": "Lab", "role": "Founder", "sector": "AI"}}, None)
    (pr / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True))
    return pr, roster, pr / "index.json"


def embedded(html: str, name: str):
    m = re.search(rf"const {name} = (.*?);\n", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def main() -> int:
    L = load("predictions_lib")
    A = load("aggregate_predictions")
    B = load("build_predictions_site")
    script = REPO / "scripts" / "build_predictions_site.py"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pr, roster, index = build(td, L, A)
        out = td / "site" / "index.html"
        p = subprocess.run([PY, str(script), "--index", str(index), "--predictions", str(pr), "--roster", str(roster), "--out", str(out)],
                           capture_output=True, text=True, cwd=REPO)
        check("FIXTURE: builder exits 0 and writes the page", p.returncode == 0 and out.exists(), p.stdout + p.stderr[-500:])
        html = out.read_text()
        data, src, pred = embedded(html, "DATA"), embedded(html, "SRC"), embedded(html, "PRED")
        check("FIXTURE: DATA, SRC and PRED parse", isinstance(data, list) and isinstance(src, dict) and isinstance(pred, dict))

        body = re.sub(r"<!-- disclaimer:start -->.*?<!-- disclaimer:end -->", "", html, flags=re.S)
        body = re.sub(r"const (DATA|SRC|PRED) = .*?;\n", "", body, flags=re.S)
        # The prediction_type enum value "ranking" (X will be first/largest) is a label key, not prose.
        body = re.sub(r"const TYPE = \{.*?\};\n", "", body, flags=re.S)
        hits = sorted(set(m.group(0).lower() for m in re.finditer(
            r"\b(accuracy|accurate|brier|correct|incorrect|resolved|leaderboard|best forecaster|best predictor|score|skill|edge|rank|ranking|outperform)\b", body, re.I)))
        check("NEUTRAL: no evaluative vocabulary outside the disclaimer and the data", not hits, str(hits))
        check("NEUTRAL: the disclaimer block exists and is non-empty", "<!-- disclaimer:start -->" in html and "no Brier score" in html)

        check("SORT: default sort is name ascending and the Person header announces it in static HTML",
              'let sortKey = "name", sortDir = 1;' in html and '<th data-k="name" aria-sort="ascending">' in html)
        keys = re.findall(r'data-k="([a-z_]+)"', html)
        check("SORT: the column keys are exactly the allowed set",
              keys == ["name", "company", "accepted", "h_explicit", "h_inferable", "h_none", "p_explicit", "p_qual", "transcripts", "earliest", "latest"], str(keys))
        check("SORT: DATA is emitted alphabetically by name", [d["name"] for d in data] == ["Ada L", "Alan T"])

        ada = pred["ada"]
        first = next(r for r in ada if r["quote"].startswith("by 2030"))
        check("TIMESTAMP: [01:02:03] gives t 3723 and the card links to the video at that second",
              first["timestamp_mark"] == "[01:02:03]" and first["t"] == 3723 and "youtube.com/watch?v=" in html and "&t=${" in html and "}s`" in html)
        check("TIMESTAMP: a record with no video id keeps a plain mark (ytLink returns null)", src["alan/s2"]["video_id"] is None and "ytLink = (vid, t) => vid && t != null" in html)
        # The marker may legitimately appear inside an accepted record's context window (it is
        # transcript text); it must never appear as a quote or a claim under the person's name.
        embedded_claims = json.dumps([[r["quote"], r["claim"]] for rs in pred.values() for r in rs])
        check("REJECTED: the rejected quote is never a quote or claim on the page, and its count is embedded",
              "REJECTED-MARKER-QUOTE" not in embedded_claims and len(ada) == 2
              and next(d for d in data if d["slug"] == "ada")["rejected"] == 1)
        check("TRIM: no telemetry, gates, offsets, harness or accepted flag in PRED",
              not re.search(r"secret_telemetry|\"gates\"|quote_char_start|\"harness\"|\"accepted\"", json.dumps(pred)) and "prediction_id" in first)
        check("PROVENANCE: run ids, contract ids and both model names are on the page",
              "run-x" in html and "aaaaaaaaaaaa" in html and "bbbbbbbbbbbb" in html and "Claude Fable 5.1" in html and "OpenAI GPT-6 Astra" in html)
        check("ESCAPE: '</script>' occurs exactly once in the page although a quote contains it", html.count("</script>") == 1)
        m = first["market"]
        check("MARKET: the matched market is embedded with number, platform, staleness and precision; proxies carry no number",
              m and m["status"] == "matched" and m["probability"] == 0.27 and m["exact"]["platform"] == "Polymarket"
              and m["exact"]["staleness_sec"] == 840 and m["precision"] == "date" and m["proxies"][0]["question"].startswith("PROXY-QUESTION")
              and "probability" not in m["proxies"][0], json.dumps(m)[:300])
        check("MARKET: the card template renders the number with platform, match type and staleness, and a proxy without a number",
              "contemporaneous market" in html and "exact match" in html and "before publication" in html and "proxy, no probability shown" in html)
        check("ATOMIC: the builder writes through write_atomic and never args.out.write_text",
              "write_atomic(args.out" in script.read_text() and "args.out).write_text" not in script.read_text())

        bad = json.loads(index.read_text())
        bad["leaders"][0]["accepted"] = 9
        (td / "bad.json").write_text(json.dumps(bad))
        p = subprocess.run([PY, str(script), "--index", str(td / "bad.json"), "--predictions", str(pr), "--roster", str(roster), "--out", str(td / "x.html")],
                           capture_output=True, text=True, cwd=REPO)
        check("STALE: an index count that disagrees with the files fails, naming the person", p.returncode != 0 and "ada" in p.stderr, p.stderr[-300:])

    bs = (REPO / "scripts" / "build_site.py").read_text()
    mast = bs[bs.index('<header class="mast">'):bs.index("</header>")]
    check("XLINK: the index page links to the predictions page in its masthead", 'href="https://verbatim-predictions.tonygwu.com"' in mast)
    check("XLINK: the predictions page links back to the index", 'href="https://verbatim-index.tonygwu.com"' in html)
    check("THEME: both templates substitute __THEME__ and __FONTS__ from site_theme",
          "__THEME__" in bs and "__THEME__" in B.TEMPLATE and "from site_theme import FONT_LINKS, THEME_CSS" in bs
          and "--d1:#2E6FC9" in html and ':root[data-theme="dark"]' in html)

    w = tomllib.loads((REPO / "wrangler.predictions.toml").read_text())
    w0 = tomllib.loads((REPO / "wrangler.toml").read_text())
    check("WRANGLER: name, directory, 404 mode and hostname are right, and differ from the index Worker",
          w["name"] == "verbatim-predictions" and w["assets"]["directory"] == "./site-predictions" and w["assets"]["not_found_handling"] == "none"
          and w["routes"][0]["pattern"] == "verbatim-predictions.tonygwu.com" and w["routes"][0]["custom_domain"] is True
          and w["name"] != w0["name"] and w["assets"]["directory"] != w0["assets"]["directory"], str(w))
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "init", "-q", td], check=True)
        (Path(td) / ".gitignore").write_text((REPO / ".gitignore").read_text())
        (Path(td) / "site-predictions").mkdir()
        (Path(td) / "site-predictions" / "index.html").write_text("x")
        p = subprocess.run(["git", "-C", td, "check-ignore", "-q", "site-predictions/index.html"])
        check("GITIGNORE: site-predictions/index.html is ignored", p.returncode == 0)

    dep = REPO / "scripts" / "deploy_predictions.sh"
    src_sh = dep.read_text()
    check("DEPLOY: bash -n passes", subprocess.run(["bash", "-n", str(dep)]).returncode == 0)
    check("DEPLOY: renders before deploying, with -c and never a bare wrangler deploy",
          src_sh.index("build_predictions_site.py") < src_sh.index("npx wrangler deploy") and "-c wrangler.predictions.toml" in src_sh
          and not re.search(r"wrangler deploy\s*$", src_sh, re.M))
    check("DEPLOY: --refresh is daemon-guarded before aggregation, and aggregation precedes the build",
          src_sh.index('if [ "$REFRESH" -eq 1 ]') < src_sh.index("require_daemon_clone") < src_sh.index("aggregate_predictions.py") < src_sh.index("build_predictions_site.py"))
    check("DEPLOY: staleness line and unknown-argument handling are present", "STALE" in src_sh and "cannot be checked" in src_sh and "unknown argument" in src_sh)
    p = subprocess.run(["bash", str(dep), "--nonsense"], capture_output=True, text=True, cwd=REPO)
    check("DEPLOY: an unknown flag exits 2 before anything runs", p.returncode == 2 and "unknown argument" in p.stderr)
    marker = REPO / "data" / ".daemon-clone"
    if marker.exists() and marker.read_text().strip() != REPO.name:
        p = subprocess.run(["bash", str(dep), "--refresh", "--dry-run"], capture_output=True, text=True, cwd=REPO)
        check("GUARD-LIVE: --refresh from a non-daemon clone is refused", p.returncode != 0 and "REFUSING" in (p.stdout + p.stderr), (p.stdout + p.stderr)[-300:])
    else:
        print("  SKIP  GUARD-LIVE: this is the daemon clone (or no marker); not exercising --refresh here")
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
