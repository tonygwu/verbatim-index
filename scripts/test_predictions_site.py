#!/usr/bin/env python3
"""The predictions page must show what was said, never a verdict, and must deploy from the right config.

  FIXTURE    renders from a synthetic index.json plus jsonl; DATA and SRC parse
  PAYLOAD    the records are files beside the page, versioned, and the page stays under the budget
  NEUTRAL    no evaluative vocabulary outside the fenced disclaimer and the data constants
  SORT       Score descending by default with scores (unscored last, name order), name order without;
             static aria-sort, exact column keys
  FLOOR      a person under MIN_PREDICTIONS_TO_LIST has no row and is named; score prose counts listed people
  ORG        the Organisation column is at most 150px
  POPOVER    year squares carry data for the popover, which is held to WCAG AA (behaviour: check_predictions_site_ui.py)
  INTRO      the scored intro is derived from the listed people and links the repo; the social text matches
  PRIOR      the prior explanation names the model from its sidecars and prints prediction_score's numbers
  BUCKETS    the Predictions cell's lines are derived per person, add up to the total, and refuse unknown reasons
  STATE      one state per record, computed once; the column counts the cards' states, under the scorer's
             old strings and its new not_eligible:<reason> strings alike (behaviour: check_predictions_site_ui.py)
  ORDER      a record failing two clauses is named by phase2_resolvability's one order, as the scorer names it
  CARD       each state's Outcome line; never "Not yet resolved" for a record no stage will resolve; a record
             with no scores row takes its eligibility from phase2_resolvability.funnel_flags (SHARED); a
             directional claim the scorer's trend rule judges later gives the date, never "Never checked"
  PRICED     a card with no price says why; a price is dated "as of" the statement date, and its reason
             follows the state
  SAID       the statement date is labelled by its basis (stated, sourced, upload, publication, unknown);
             a sourced date with no override block refuses
  TARGET     the extractor's horizon words show before "none stated", only when they are the recording's words
  SCORE INFO the resolver's "cannot be resolved" count is the Predictions panel's Couldn't check, and the
             answers on records not testable anyway are named apart
  REPLACED   sidecars a replacement manifest replaced are left out, as the scorer left them out
  ENTITY     Happy Scribe text is decoded; any entity left in a page-visible field refuses the build
  COPY       the lead-floor rule is not called an announcement in every case
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

import collections
import copy
import importlib.util
import json
import os
import re
import shutil
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
    # LIST FLOOR. Since 2026-09-27 a person needs B.MIN_PREDICTIONS_TO_LIST (4)
    # accepted predictions for a row. ada and alan are brought to exactly 4 by a
    # second recording each, so they sit ON the floor and stay; cleo has 1 and
    # sits under it, so she must leave the table and be NAMED in the note.
    ada2 = [rec(L, "ada", "s3", "by 2030 most code will be written by AI I would say that is my bet", True),
            rec(L, "ada", "s3", "we will see 30 gigawatts of new capacity in 2026 </script><b>bold</b> and that is that", True)]
    (pr / "ada" / "s3.jsonl").write_text(L.serialise_lines(ada2))
    (pr / "ada" / "s3.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 2, "harness": "fable"}, "verify": {"status": "ok", "accepted": 2}}))
    alan2 = [rec(L, "alan", "s4", q, True, upload=None, video=None) for q in (
        "by 2030 most code will be written by AI I would say that is my bet",
        "we will see 30 gigawatts of new capacity in 2026 </script><b>bold</b> and that is that",
        "and finally rates will be lower next year for sure")]
    # BUCKETS: one prediction with no deadline at all, which is neither due nor
    # past due and must land in its own bucket.
    alan2[2]["prediction"].update(target_date=None, target_date_text=None, horizon="none")
    (pr / "alan" / "s4.jsonl").write_text(L.serialise_lines(alan2))
    (pr / "alan" / "s4.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 3, "harness": "astra"}, "verify": {"status": "ok", "accepted": 3}}))
    (pr / "cleo").mkdir()
    cleo = [rec(L, "cleo", "s5", "by 2030 most code will be written by AI I would say that is my bet", True)]
    (pr / "cleo" / "s5.jsonl").write_text(L.serialise_lines(cleo))
    (pr / "cleo" / "s5.meta.json").write_text(json.dumps({"extract": {"status": "ok", "candidates_written": 1, "harness": "fable"}, "verify": {"status": "ok", "accepted": 1}}))
    roster = td / "roster.json"
    roster.write_text(json.dumps({"roster": [{"slug": "ada", "name": "Ada L", "role": "CEO", "company": "Co", "sector": "AI"},
                                             {"slug": "alan", "name": "Alan T", "role": "Founder", "company": "Lab", "sector": "AI"},
                                             {"slug": "cleo", "name": "Cleo F", "role": "CTO", "company": "Few", "sector": "AI"}]}))
    index = A.build_index(pr, {"ada": {"name": "Ada L", "company": "Co", "role": "CEO", "sector": "AI"},
                               "alan": {"name": "Alan T", "company": "Lab", "role": "Founder", "sector": "AI"},
                               "cleo": {"name": "Cleo F", "company": "Few", "role": "CTO", "sector": "AI"}}, None)
    (pr / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True))
    write_year_summaries(pr)
    return pr, roster, pr / "index.json"


def mem(roster: Path, off: tuple = (), drop: tuple = ()) -> Path:
    """A membership.json beside the fixture roster: everyone on both boards, except
    `off` (leaders only) and `drop` (absent, which the page must refuse)."""
    slugs = [r["slug"] for r in json.loads(roster.read_text())["roster"]]
    doc = {s: (["leaders"] if s in off else ["leaders", "predictions"]) for s in slugs if s not in drop}
    path = roster.parent / "membership.json"
    path.write_text(json.dumps(doc))
    return path


def write_year_summaries(pr: Path) -> dict:
    """A current summary for every dated cell, as `year_summaries.py --write` leaves it."""
    B, YS = load("build_predictions_site"), load("year_summaries")
    by_slug: dict = {}
    for r in B.load_records(pr)["accepted"]:
        by_slug.setdefault(r["leader_slug"], []).append(r)
    entries = {YS.key(s, y): {"summary": f"{s} predicted things in {y}", "inputs_sha256": YS.cell_digest(recs), "n": len(recs)}
               for s, ys in YS.cells(by_slug).items() for y, recs in ys.items()}
    doc = {"schema_version": 1, "entries": entries}
    (pr / "year_summaries.json").write_text(json.dumps(doc))
    return doc


def fl(eligible: bool, lead_days, *, dbs: bool = False, spec_ok: bool = True, trend: bool = False,
       basis: str = "stated", min_lead: int = 60) -> dict:
    """The funnel flags score_predictions.join copies onto every row, as resolve_predictions.select writes them."""
    return {"basis": basis, "deadline_before_statement": dbs, "eligible": eligible, "lead_days": lead_days,
            "lead_ok": lead_days is not None and lead_days >= min_lead, "specificity_high": spec_ok,
            "specificity_ok": spec_ok, "trend": trend}


def embedded(html: str, name: str):
    m = re.search(rf"const {name} = (.*?);\n", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def records(out: Path) -> dict[str, list]:
    """The prediction records, read from the files the page fetches them from.

    They were inlined as `const PRED` until 2026-09-17. Everything this test
    asserted about what may and may not reach a reader still holds; it holds
    about these files now, because they are what the drawer renders.
    """
    d = out.parent / "predictions"
    return {f.stem: json.loads(f.read_text()) for f in sorted(d.glob("*.json"))} if d.is_dir() else {}


# ---------------------------------------------------------------------------
# CARD STATE (rescue round 4, root-cause design section 4). One person, dora, with
# one record in every state the page can show. Her scores.json is written twice:
# once with the scorer's OLD strings, where an unresolved ineligible row reads
# `no_resolution` and a resolved one `not_eligible`, and once with the NEW
# strings, `not_eligible:<reason>`, which the parallel funnel task introduces.
# The page must say the same thing about every record under both.
# ---------------------------------------------------------------------------

STATE_AS_OF = "2026-09-14"
HS_TEXT = ("[00:00:05] so here is the thing it&#39;s going to be the year of the robot in 2030 "
           "I&#39;m sure of it and that&#39;s what we&#39;ll see")
OVERRIDE = {"statement_date": "1996-10-16", "basis": "Opening keynote, Example Developer Conference",
            "source_url": "https://example.org/press", "verbatim_evidence": "held October 16",
            "confirmed_by": "operator", "confirmed_at_utc": "2026-09-28T05:19:02Z"}


def srec(L, sid: str, quote: str, *, target=None, target_text=None, horizon="explicit", yrs=None,
         evidence=None, specificity="high", upload="20250301", declared=None, override=None,
         claim=None, criteria=None, conf=None, text=None) -> dict:
    """One accepted record for dora, built by the pipeline's own make_record."""
    text = text or f"[00:00:05] so here is the thing {quote} and that is what I think will happen"
    r0 = {"leader_slug": "dora", "source_id": sid, "text": text, "yt_upload_date": upload,
          "url": f"https://www.youtube.com/watch?v=v{sid}" if upload else f"https://example.org/{sid}",
          "video_id": f"v{sid}" if upload else None, "yt_title": f"{sid} talk", "declared_venue": "Pod",
          "declared_kind": "podcast", "word_count": 40, "duration_sec": 600}
    if declared:
        r0.update(statement_date=declared[0], statement_date_basis=declared[1])
    if override:
        r0["statement_date_override"] = override
    cand = {"quote": quote, "gates": {g: True for g in L.GATES}, "gate_notes": "",
            "resolution_criteria": criteria or f"By the deadline: {quote}", "normalized_claim": claim or f"Dora says {sid}",
            "category": "technology_product", "prediction_type": "milestone", "target_date": target,
            "target_date_text": target_text, "horizon": horizon, "horizon_years_inferred": yrs,
            "horizon_evidence": evidence, "specificity": specificity, "subject_control": "external",
            "confidence": conf or {"type": "none", "probability": None, "verbatim_confidence_language": None}}
    loc = L.locate_quote(text, quote)
    assert "start" in loc, (quote, loc)
    prov = L.normalise_provenance("fable", {"requested_model": "claude-fable-5-1", "judge_model": "claude-fable-5-1"}, "default", "claude")
    r = L.make_record(r0, {"name": "Dora M", "role": "CEO", "company": "Co"}, cand, loc, prov, "a" * 12, "run-x",
                      "2026-09-10T00:00:00Z", {})
    v = r["verification"]
    v.update({"status": "ok", "harness": "astra", "requested_model": "gpt-6-astra", "served_model": "gpt-6-astra",
              "served_model_verified": False, "account": "codex", "router_account_id": "codex", "contract_id": "b" * 12,
              "run_id": "run-v", "verified_at_utc": "2026-09-10T01:00:00Z", "gates": {g: True for g in L.GATES},
              "attribution": "subject", "claim_faithful": True, "qualifies_stated": True,
              "verifier_resolution_criteria": "verifier says so", "notes": None, "telemetry": {}})
    v["qualifies"] = L.verification_qualifies(v)
    v["agreement"] = r["extraction"]["qualifies"] == v["qualifies"]
    r["accepted"] = L.compute_accepted(r)
    assert r["accepted"], sid
    return r


def dora_records(L) -> dict[str, dict]:
    """sid -> record. Statement date 2025-03-01 (an upload) unless the record says otherwise."""
    q = lambda sid: f"we will ship the {sid.replace('-', ' ')} widget"  # noqa: E731
    qual = lambda s: {"type": "qualitative", "probability": None, "verbatim_confidence_language": s}  # noqa: E731
    return {r["source_id"]: r for r in [
        srec(L, "scored", q("scored"), target="2025-12", target_text="by the end of 2025"),
        srec(L, "trend", "revenue will keep growing every quarter", horizon="none", upload="20200101",
             claim="Revenue will keep growing"),
        srec(L, "lead-resolved", q("lead-resolved"), target="2025-03-20"),
        srec(L, "lead-unresolved", q("lead-unresolved"), target="2025-04-01"),
        srec(L, "lead-unresolvable", q("lead-unresolvable"), target="2025-04-15"),
        srec(L, "dbs", q("dbs"), target="2024-06"),
        srec(L, "vague", q("vague"), target="2025-12", specificity="low"),
        srec(L, "undated-past", q("undated-past"), target="2025-06", upload=None),
        srec(L, "awaiting", q("awaiting"), target="2025-11"),
        srec(L, "unresolvable", q("unresolvable"), target="2025-10"),
        srec(L, "no-prior", q("no-prior"), target="2025-09"),
        srec(L, "late", q("late"), target="2026-06"),
        srec(L, "not-due", q("not-due"), target="2030"),
        srec(L, "pub", q("pub"), target="2030", upload=None, declared=("2025-09-17", "publication_date")),
        srec(L, "stated", q("stated"), target="2030", upload=None, declared=("2012-05-30", "stated_in_page")),
        srec(L, "override", q("override"), target="2030", upload="20130705", override=OVERRIDE),
        srec(L, "hs-dora-talk", "it&#39;s going to be the year of the robot in 2030", target="2030",
             upload=None, declared=("2025-09-17", "publication_date"), text=HS_TEXT, conf=qual("I&#39;m sure"),
             criteria="By 2030-12-31, robots are on sale"),
        srec(L, "inferable", q("inferable"), horizon="inferable", yrs=20,
             evidence="now that's out a couple of decades from now",
             text=f"[00:00:05] so here is the thing {q('inferable')} and now that's out a couple of decades "
                  "from now I would say"),
        srec(L, "nodl-undated", q("nodl-undated"), target_text="in two years", upload=None),
        srec(L, "nodl-window", q("nodl-window"), target_text="soon", horizon="none"),
        # Round-4 review fixes (2026-09-29). Each record below reached a false card.
        # Fails specificity AND the lead floor: the one order names specificity.
        srec(L, "vague-lead", q("vague-lead"), target="2025-04-10", specificity="low"),
        # Not yet due and ineligible for good: no scores row, so eligibility comes
        # from the funnel's own flags, never "It is checked after that date."
        srec(L, "undated-due", q("undated-due"), target="2030", upload=None),
        srec(L, "vague-due", q("vague-due"), target="2030", specificity="low"),
        # Past due at the as-of, missing from scores.json, and under the lead floor:
        # Not testable with its reason, never "Awaiting check".
        srec(L, "late-lead", q("late-lead"), target="2025-04-20"),
        # A directional claim the trend rule judges once three years have passed.
        srec(L, "trend-later", "costs will keep falling every year", horizon="none", claim="Costs will keep falling"),
        # A trend row not checked yet, one priced but not checked, one not testable
        # and priced, and one that could not be settled and carries no price.
        srec(L, "trend-open", "margins will keep rising every year", horizon="none", upload="20200101",
             claim="Margins will keep rising"),
        srec(L, "awaiting-priced", q("awaiting-priced"), target="2025-08"),
        srec(L, "lead-priced", q("lead-priced"), target="2025-04-05"),
        srec(L, "unresolvable-nop", q("unresolvable-nop"), target="2025-07"),
        # The extractor's horizon_evidence is its own note here, not words anyone said.
        srec(L, "inferable-notes", q("inferable-notes"), horizon="inferable", yrs=3,
             evidence="The interviewer asks about the next few years. Three years is an approximate interpretation."),
        # The same prediction said again later: shown under not-due, with an Also said line.
        srec(L, "restated-b", q("restated b"), target="2030", upload="20250601"),
    ]}


# What each record's state must be, and its reason where the state has one.
DORA_STATES = {
    "scored": ("scored", None), "trend": ("scored", None),
    "lead-resolved": ("not_testable", "lead_under_floor"), "lead-unresolved": ("not_testable", "lead_under_floor"),
    "lead-unresolvable": ("not_testable", "lead_under_floor"),
    "dbs": ("not_testable", "deadline_before_statement"), "vague": ("not_testable", "specificity"),
    "undated-past": ("not_testable", "undated"),
    "awaiting": ("awaiting", "not_checked"), "no-prior": ("awaiting", "not_priced"), "late": ("awaiting", "after_scoring"),
    "unresolvable": ("unresolvable", "criterion_ambiguous"),
    "not-due": ("not_due", None), "pub": ("not_due", None), "stated": ("not_due", None), "override": ("not_due", None),
    "hs-dora-talk": ("not_due", None), "inferable": ("not_due", None),
    "nodl-undated": ("no_deadline", "undated"), "nodl-window": ("no_deadline", "no_window"),
    "vague-lead": ("not_testable", "specificity"),
    "undated-due": ("not_due", "undated"), "vague-due": ("not_due", "specificity"),
    "late-lead": ("not_testable", "lead_under_floor"),
    "trend-later": ("no_deadline", "trend_later"),
    "trend-open": ("awaiting", "not_checked"), "awaiting-priced": ("awaiting", "not_checked"),
    "lead-priced": ("not_testable", "lead_under_floor"),
    "unresolvable-nop": ("unresolvable", "no_public_evidence"),
    "inferable-notes": ("not_due", None),
    # A restated record's reason is its specific member, named here by sid.
    "restated-b": ("restated", "not-due"),
}


def dora_scores(recs: dict[str, dict], run: Path, new_strings: bool) -> dict:
    """scores.json over dora's past-due rows, in the scorer's old or new strings."""
    PS = load("prediction_score")
    def row(sid, deadline, flags, why_old, why_new=None, outcome=None, p=None, scored=False, unres=None):
        pts = round(PS.score(outcome == "occurred", p)["points"], 4) if scored else None
        return {"prediction_id": recs[sid]["prediction_id"], "leader_slug": "dora",
                "transcript_id": recs[sid]["transcript_id"], "statement_date": recs[sid]["source"]["statement_date"],
                "deadline": deadline, "flags": flags, "outcome": outcome, "scored": scored, "points": pts,
                "unresolvable_reason": unres, "resolution_reasoning": f"reasoning for {sid}" if outcome else None,
                "sources": [{"where": "https://example.com/e", "what_it_shows": "it", "date": "2025-12-01"}] if outcome else [],
                "p": p, "reference_class": "things like this" if p is not None else None,
                "not_scored_because": (why_new if new_strings and why_new else why_old)}
    rows = [
        row("scored", "2025-12-31", fl(True, 305), None, outcome="occurred", p=0.7, scored=True),
        row("trend", STATE_AS_OF, fl(True, 2448, trend=True, basis="trend: trend over 6.7y since the statement"),
            None, outcome="not_occurred", p=0.6, scored=True),
        row("lead-resolved", "2025-03-20", fl(False, 19), "not_eligible", "not_eligible:lead_under_floor",
            outcome="occurred", p=0.85),
        row("lead-unresolved", "2025-04-01", fl(False, 31), "no_resolution", "not_eligible:lead_under_floor"),
        row("lead-unresolvable", "2025-04-15", fl(False, 45), "unresolvable:no_public_evidence",
            "not_eligible:lead_under_floor", outcome="unresolvable", unres="no_public_evidence"),
        row("dbs", "2024-06-30", fl(False, -244, dbs=True), "no_resolution", "not_eligible:deadline_before_statement"),
        row("vague", "2025-12-31", fl(False, 305, spec_ok=False), "no_resolution", "not_eligible:specificity"),
        row("undated-past", "2025-06-30", fl(False, None), "no_resolution", "not_eligible:undated"),
        row("awaiting", "2025-11-30", fl(True, 274), "no_resolution"),
        row("unresolvable", "2025-10-31", fl(True, 244), "unresolvable:criterion_ambiguous",
            outcome="unresolvable", p=0.4, unres="criterion_ambiguous"),
        row("no-prior", "2025-09-30", fl(True, 213), "no_prior", outcome="occurred"),
        # Appended, so the refusal checks below keep their row indices.
        row("vague-lead", "2025-04-10", fl(False, 40, spec_ok=False), "no_resolution", "not_eligible:specificity"),
        row("trend-open", STATE_AS_OF, fl(True, 2448, trend=True, basis="trend: trend over 6.7y since the statement"),
            "no_resolution"),
        row("awaiting-priced", "2025-08-31", fl(True, 183), "no_resolution", p=0.55),
        row("lead-priced", "2025-04-05", fl(False, 35), "no_resolution", "not_eligible:lead_under_floor", p=0.3),
        row("unresolvable-nop", "2025-07-31", fl(True, 152), "unresolvable:no_public_evidence",
            outcome="unresolvable", unres="no_public_evidence"),
    ]
    scored = [r for r in rows if r["scored"]]
    unres = collections.Counter(r["unresolvable_reason"] for r in rows if r["outcome"] == "unresolvable")
    outcomes = collections.Counter(r["outcome"] for r in rows if r["outcome"])
    lead = {"slug": "dora", "name": "Dora M", "past_due": len(rows), "eligible": sum(r["flags"]["eligible"] for r in rows),
            "unresolvable": outcomes["unresolvable"], "n_scored": len(scored),
            "scored_occurred": sum(r["outcome"] == "occurred" for r in scored),
            "mean_points": round(sum(r["points"] for r in scored) / len(scored), 4), "ranked": False,
            "hit_rate": round(sum(r["outcome"] == "occurred" for r in scored) / len(scored), 4)}
    doc = {"as_of": STATE_AS_OF, "run_dirs": [str(run)],
           # Every scorer writes the trend setting it ran with; the new one also
           # states the rule, with its minimum years, under `rule`.
           "settings": {"as_of": STATE_AS_OF, "trend": True, "min_lead_days": 60},
           "rule": {"clamp": 0.01, "min_scored_to_rank": 3, "min_lead_days": 60,
                    "baseline_only": "points = -log2(p) if it happened, else (p/(1-p))*log2(p)"},
           "corpus": {"past_due": len(rows), "eligible": lead["eligible"], "scored": len(scored), "leaders_ranked": 0,
                      "by_outcome": dict(outcomes), "unresolvable_reasons": dict(unres)},
           "restatements": {"clusters": [{"cluster_id": "dora-c1", "specific_member": recs["not-due"]["prediction_id"],
                                          "members": [recs["not-due"]["prediction_id"],
                                                      recs["restated-b"]["prediction_id"]]}]},
           "leaders": [lead], "predictions": rows}
    if new_strings:
        doc["rule"]["trend"] = {"enabled": True, "min_years": 3.0}
        split = {k: [r for r in rows if r["outcome"] == "unresolvable" and r["flags"]["eligible"] is want]
                 for k, want in (("eligible", True), ("not_eligible", False))}
        doc["corpus"]["unresolvable_by_eligibility"] = {
            k: {"n": len(v), "reasons": dict(collections.Counter(r["unresolvable_reason"] for r in v))}
            for k, v in split.items()}
    return doc


def card_states(L, A, B) -> None:
    script = REPO / "scripts" / "build_predictions_site.py"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pr = td / "pred"
        (pr / "dora").mkdir(parents=True)
        recs = dora_records(L)
        for sid, r in recs.items():
            (pr / "dora" / f"{sid}.jsonl").write_text(L.serialise_lines([r]))
            (pr / "dora" / f"{sid}.meta.json").write_text(json.dumps(
                {"extract": {"status": "ok", "candidates_written": 1, "harness": "fable"}, "verify": {"status": "ok", "accepted": 1}}))
        people = {"dora": {"name": "Dora M", "company": "Co", "role": "CEO", "sector": "AI"}}
        (pr / "index.json").write_text(json.dumps(A.build_index(pr, people, None), indent=1, sort_keys=True))
        write_year_summaries(pr)
        roster = td / "roster.json"
        roster.write_text(json.dumps({"roster": [{"slug": "dora", "name": "Dora M", "role": "CEO", "company": "Co", "sector": "AI"}]}))
        run = td / "run"
        by_sid = {sid: r["prediction_id"] for sid, r in recs.items()}
        for sid, p, outcome in (("scored", 0.7, "occurred"), ("trend", 0.6, "not_occurred")):
            pid = by_sid[sid]
            for sub, doc in (("priors", {"prediction_id": pid, "leader_slug": "dora", "stage": "prior", "p": p, "p_raw": p,
                                         "clamped": False, "reference_class": "r", "reasoning": "r", "harness": "fable",
                                         "telemetry": {"canonical_model": "claude-fable-5-1", "requested_model": "claude-fable-5-1",
                                                       "telemetry_models": ["claude-fable-5-1"]}}),
                             ("resolutions", {"prediction_id": pid, "leader_slug": "dora", "stage": "resolve", "outcome": outcome,
                                              "harness": "astra", "telemetry": {"requested_model": "gpt-6-astra",
                                                                                "served_model": "gpt-6-astra"}})):
                (run / sub / "dora").mkdir(parents=True, exist_ok=True)
                (run / sub / "dora" / f"{pid}.json").write_text(json.dumps(doc))

        def render(doc: "dict | None", name: str, preds: Path = pr):
            args = [PY, str(script), "--data-date", "2026-09-10", "--index", str(preds / "index.json"),
                    "--predictions", str(preds), "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / name / "index.html")]
            if doc is not None:
                (td / f"{name}.json").write_text(json.dumps(doc))
                args += ["--scores", str(td / f"{name}.json")]
            return subprocess.run(args, capture_output=True, text=True, cwd=REPO)

        built = {}
        for tag, new in (("old", False), ("new", True)):
            p = render(dora_scores(recs, run, new), tag)
            check(f"STATE: the page builds from the scorer's {tag} strings", p.returncode == 0,
                  (p.stdout + p.stderr)[-600:])
            if p.returncode == 0:
                built[tag] = ({r["transcript_id"].split("/")[1]: r for r in records(td / tag / "index.html")["dora"]},
                              embedded((td / tag / "index.html").read_text(), "DATA")[0],
                              (td / tag / "index.html").read_text())
        if not built:
            return
        if os.environ.get("VI_KEEP_STATE_SITE") and "new" in built:
            shutil.copytree(td / "new", Path(os.environ["VI_KEEP_STATE_SITE"]), dirs_exist_ok=True)
        # Every check below reads the new-strings build, or the old one if only that built.
        pub, row, page = built.get("new") or built["old"]
        st = {sid: r.get("state") or {} for sid, r in pub.items()}
        sid_of = {pid: sid for sid, pid in by_sid.items()}
        got = {sid: (s.get("state"), sid_of.get(s.get("reason"), s.get("reason"))) for sid, s in st.items()}
        check("STATE: every record carries the state its scores row and its deadline give",
              got == DORA_STATES, json.dumps({k: (got.get(k), v) for k, v in DORA_STATES.items() if got.get(k) != v})[:900])
        # FOUND in review 2026-09-29: a record with a verdict and a price kept the
        # "Not priced..." words of its state in the published record file. The card
        # showed the right price, from outcome.p, so only the data contradicted itself.
        priced = [sid for sid, r in pub.items() if (r.get("outcome") or {}).get("p") is not None]
        stale = {sid: st[sid].get("price") for sid in priced if st[sid].get("price") is not None}
        check("STATE: a record whose verdict carries a price has no price words of its own in the record file",
              bool(priced) and not stale, json.dumps({"priced": priced, "stale": stale})[:600])
        both = len(built) == 2
        check("STATE: under the old and the new scorer strings every record has the same state and card text",
              both and all(built["old"][0][sid].get("state") == pub[sid].get("state") for sid in pub),
              "only one build" if not both else
              str([sid for sid in pub if built["old"][0][sid].get("state") != pub[sid].get("state")]))
        check("STATE: the page and its record files are byte-identical under the old and the new scorer strings",
              both and built["old"][2] == page
              and (td / "old" / "predictions" / "dora.json").read_bytes() == (td / "new" / "predictions" / "dora.json").read_bytes(),
              "only one build" if not both else "the pages or the record files differ")
        want = collections.Counter(s for s, _ in DORA_STATES.values())
        check("STATE: the Predictions column counts exactly the states the cards carry, under both strings",
              both and row.get("buckets") == dict(want) and built["old"][1].get("buckets") == dict(want),
              f"new {row.get('buckets')} old {built['old'][1].get('buckets')} want {dict(want)}")
        check("STATE: a record checked but not testable counts as Not testable, not Couldn't check",
              row.get("unres") == {"criterion_ambiguous": 1, "no_public_evidence": 1}, str(row.get("unres")))
        # ORDER (review items 1 and 4). The page names the clause the scorer names,
        # from phase2_resolvability's one order, when a record fails two clauses.
        P2 = load("phase2_resolvability")
        check("ORDER: a record failing specificity AND the lead floor is named specificity under both string sets",
              both and st["vague-lead"].get("reason") == "specificity"
              and (built["old"][0]["vague-lead"].get("state") or {}).get("reason") == "specificity"
              and P2.INELIGIBLE_REASONS.index("specificity") < P2.INELIGIBLE_REASONS.index("lead_under_floor"),
              str((st["vague-lead"].get("reason"), both and (built["old"][0]["vague-lead"].get("state") or {}).get("reason"))))
        check("ORDER: the page keeps no order of its own",
              not hasattr(B, "NOT_ELIGIBLE_REASONS") and "failing_clauses" in (REPO / "scripts" / "build_predictions_site.py").read_text(),
              "build_predictions_site still defines NOT_ELIGIBLE_REASONS")

        line = {sid: s.get("line") or "" for sid, s in st.items()}
        check("CARD: no card, and no line of the page, reads 'Not yet resolved'",
              "Not yet resolved" not in page and all("Not yet resolved" not in v for v in line.values()),
              str([sid for sid, v in line.items() if "Not yet resolved" in v]))
        check("CARD: not yet due says it is open until its deadline",
              line["not-due"] == "Open until 2030-12-31. It is checked after that date.", line["not-due"])
        check("CARD: no deadline because the recording is undated quotes the speaker's time words",
              line["nodl-undated"] == ("Never checked: the recording has no known date, so no deadline can be "
                                       "computed from “in two years”."), line["nodl-undated"])
        check("CARD: no deadline because it names no readable date says so",
              line["nodl-window"] == "Never checked: it names no date this pipeline can read.", line["nodl-window"])
        check("CARD: past due and not checked says so, from the scores file and after it",
              line["awaiting"] == "Past its 2025-11-30 deadline; not checked yet."
              and line["late"] == "Past its 2026-06-30 deadline; not checked yet.", f"{line['awaiting']} | {line['late']}")
        check("CARD: under the lead floor it says how many days ahead it was said, and names the floor",
              line["lead-resolved"] == "Not scored: said 19 days before its own deadline, 2025-03-20, under the 60-day floor."
              and line["lead-unresolved"].startswith("Not scored: said 31 days before"), line["lead-resolved"])
        check("CARD: a lead-floor record that was checked anyway says what happened and that it does not count",
              (pub["lead-resolved"].get("outcome") or {}).get("verdict") == "occurred"
              and "does not count" in (st["lead-resolved"].get("verdict_note") or "")
              and (pub["lead-unresolvable"].get("outcome") or {}).get("verdict") == "unresolvable"
              and "does not count" in (st["lead-unresolvable"].get("verdict_note") or ""),
              str((st["lead-resolved"].get("verdict_note"), st["lead-unresolvable"].get("verdict_note"))))
        check("CARD: a deadline before the statement date names both dates",
              line["dbs"] == "Not scored: its deadline, 2024-06-30, is earlier than the date it is recorded as said, 2025-03-01.",
              line["dbs"])
        check("CARD: a past-due record from an undated recording says the date is unknown",
              line["undated-past"].startswith("Not scored: the recording has no known date") and "60 days" in line["undated-past"],
              line["undated-past"])
        check("CARD: a too-vague record says so, with the rule it failed",
              line["vague"] == "Not scored: rated too vague to test (specificity low); a scored prediction must be high or medium.",
              line["vague"])
        check("CARD: a trend record says it was judged as a trend, over what window",
              line["trend"] == f"Judged as a trend over the 6.7 years from its statement date to {STATE_AS_OF}; "
                               "checked and scored.", line["trend"])
        # Review 0 items 1 and 2: a record with no scores row takes its eligibility
        # from the funnel's flags, so a card never promises a check that no stage makes.
        check("CARD: not yet due and undated says it will not be scored, and why",
              line["undated-due"] == ("Open until 2030-12-31, but it will not be scored: the recording has no known "
                                      "date, so it cannot be shown to have been said at least 60 days before its "
                                      "2030-12-31 deadline."), line["undated-due"])
        check("CARD: not yet due and too vague says it will not be scored, and why",
              line["vague-due"] == ("Open until 2030-12-31, but it will not be scored: rated too vague to test "
                                    "(specificity low); a scored prediction must be high or medium."), line["vague-due"])
        check("CARD: past due, missing from scores.json and under the lead floor is Not testable, never awaiting",
              line["late-lead"] == "Not scored: said 50 days before its own deadline, 2025-04-20, under the 60-day floor.",
              line["late-lead"])
        # Review 0 item 3: scores.json says the scorer judges a directional claim as
        # a trend, so its card may not say "Never".
        check("CARD: a directional claim the trend rule judges later says when, never 'Never'",
              line["trend-later"] == "Not checked yet: as a directional claim it is judged as a trend from 2028-03-01.",
              line["trend-later"])
        # Review 0 item 6: a trend row that is not scored.
        check("CARD: a trend record not checked yet does not say it was judged",
              line["trend-open"] == (f"Past its trend window, the 6.7 years from its statement date to {STATE_AS_OF}; "
                                     "not checked yet."), line["trend-open"])
        check("CARD: the card lays out the state's line and marks a verdict that does not count",
              "st.line" in page and "st.verdict_note" in page and 'data-state="${esc(r.state.state)}"' in page,
              "outcomeRows does not read r.state")

        price = {sid: s.get("price") for sid, s in st.items()}
        # A restated record has no card of its own, only an Also said line under the card it repeats.
        unpriced = [sid for sid, r in pub.items() if (r.get("outcome") or {}).get("p") is None and not r.get("restated_by")]
        check("PRICED: every card with no price says why in one line",
              all(price[sid] for sid in unpriced), str([sid for sid in unpriced if not price[sid]]))
        check("PRICED: the reason follows the state",
              price["not-due"] == "Not priced yet: a price is set when it is checked."
              and price["awaiting"] == "Not priced yet: a price is set when it is checked."
              and price["lead-unresolved"] == "Not priced: it is under the lead floor, so it is never scored."
              and price["nodl-window"] == "Not priced: it never entered the scoring funnel, because it has no deadline."
              and price["nodl-undated"] == ("Not priced: it never entered the scoring funnel, because the recording "
                                            "has no known date."),
              json.dumps(price)[:700])
        check("PRICED: a record that will not be scored is not promised a price",
              price["undated-due"] == ("Not priced: the recording has no known date, so it cannot be shown to have "
                                       "been said at least 60 days before its 2030-12-31 deadline.")
              and price["vague-due"] == ("Not priced: rated too vague to test (specificity low); a scored prediction "
                                         "must be high or medium.")
              and price["late-lead"] == "Not priced: it is under the lead floor, so it is never scored.",
              json.dumps({k: price[k] for k in ("undated-due", "vague-due", "late-lead")}))
        check("PRICED: a directional claim judged later is priced when it is judged",
              price["trend-later"] == "Not priced yet: it is priced when it is judged as a trend, from 2028-03-01.",
              str(price["trend-later"]))
        # Review 0 item 6: the reason beside a price follows the state, and "could not
        # be settled" is never given as the reason for no price.
        check("PRICED: a price on a record not checked yet says it is not checked yet",
              price["awaiting-priced"] == "Priced at 55% as of 2025-03-01, but not checked yet, so it is not scored yet.",
              str(price["awaiting-priced"]))
        check("PRICED: a price on a Not testable record names the clause, not 'not checked'",
              price["lead-priced"] == ("Priced at 30% as of 2025-03-01, but not scored: said 35 days before its own "
                                       "deadline, 2025-04-05, under the 60-day floor."), str(price["lead-priced"]))
        check("PRICED: a record nothing public settles is not said to be unpriced because of that",
              price["unresolvable-nop"] == "Not priced, and a price would not score it: nothing public settles it."
              and "could not be settled" not in json.dumps(price), str(price["unresolvable-nop"]))
        check("PRICED: a price is dated as of the statement date, never 'likely on the day it was said'",
              "likely on the day it was said" not in page and "as of ${esc(r.statement_date)}" in page)

        said = {sid: (r.get("said") or {}).get("card") for sid, r in pub.items()}
        check("SAID: an upload date is an upper bound, not checked against the event",
              said["scored"] == "on or before 2025-03-01 (YouTube upload; not checked against the event)", str(said["scored"]))
        check("SAID: a publication date is an upper bound", said["pub"] == "on or before 2025-09-17 (publication date)",
              str(said["pub"]))
        check("SAID: a date the source states is a plain date", said["stated"] == "2012-05-30", str(said["stated"]))
        check("SAID: a sourced date is a plain date and names the upload it replaced",
              said["override"] == "1996-10-16 (sourced; the YouTube upload is 2013-07-05)", str(said["override"]))
        check("SAID: no date reads 'date unknown'", said["undated-past"] == "date unknown", str(said["undated-past"]))
        check("SAID: the 'also said' line uses the same basis",
              (pub["stated"].get("said") or {}).get("also") == "on 2012-05-30"
              and (pub["scored"].get("said") or {}).get("also") == "on or before 2025-03-01"
              and (pub["undated-past"].get("said") or {}).get("also") is None)
        # Review 1 item 6: a sourced date with no override block is refused, never a
        # bare "(sourced)"; one whose source had no date of its own says so.
        src = recs["override"]["source"]
        bare = {k: v for k, v in src.items() if k != "statement_date_override"}
        try:
            B.said_label(bare, "dora's prediction X")
            refused = "no refusal"
        except SystemExit as exc:
            refused = str(exc)
        check("SAID: a sourced date with no override block refuses, naming the record",
              refused.startswith("REFUSING") and "dora's prediction X" in refused and "statement_date_override" in refused,
              refused)
        nodate = dict(src, statement_date_override=dict(src["statement_date_override"], replaced_date=None,
                                                        replaced_basis="unknown"))
        check("SAID: a sourced date whose source carried no date of its own says so, never a bare '(sourced)'",
              B.said_label(nodate, "x")["card"] == "1996-10-16 (sourced; the source carries no date of its own)",
              B.said_label(nodate, "x")["card"])

        tgt = {sid: r.get("target") for sid, r in pub.items()}
        # Review 0 item 6: horizon_evidence is shown only when it is words from the
        # recording; the extractor's own notes are never shown as what was said.
        check("TARGET: an inferred horizon shows the recording's words instead of 'none stated'",
              tgt["inferable"] == "about 20 years, inferred from: “now that's out a couple of decades from now”",
              str(tgt["inferable"]))
        check("TARGET: an inferred horizon whose evidence is the extractor's note shows no note",
              tgt["inferable-notes"] == "about 3 years, inferred", str(tgt["inferable-notes"]))
        check("TARGET: time words with no date are shown as said",
              tgt["nodl-window"] == "“soon”" and tgt["nodl-undated"] == "“in two years”",
              f"{tgt['nodl-window']} | {tgt['nodl-undated']}")
        check("TARGET: a date keeps its words, and nothing at all is 'none stated'",
              tgt["scored"] == "2025-12 — “by the end of 2025”" and tgt["trend"] == "none stated",
              f"{tgt['scored']} | {tgt['trend']}")

        hs = pub["hs-dora-talk"]
        check("ENTITY: a Happy Scribe record's quote, context and confidence words are decoded",
              hs["quote"] == "it's going to be the year of the robot in 2030" and hs["confidence_language"] == "I'm sure"
              and "&#39;" not in hs["context_after"] + hs["context_before"], json.dumps(
                  {k: hs[k] for k in ("quote", "confidence_language", "context_after")}))
        other = dict(recs["not-due"])
        other["source"] = dict(other["source"], quote_original="it&#39;s a widget")
        check("ENTITY: trim leaves every other source's text byte for byte",
              B.trim(other)["quote"] == "it&#39;s a widget", B.trim(other)["quote"])

        # A page-visible field that still holds an entity refuses the build, like
        # MAX_PAGE_BYTES: once from a source trim does not decode, once from a field
        # of a Happy Scribe record that trim does not decode either.
        for tag, sid, mutate, field in (
                ("yt", "not-due", lambda r: r["source"].update(quote_original="it&#39;s a widget"), "quote"),
                ("hs", "hs-dora-talk", lambda r: r["prediction"].update(normalized_claim="Dora&#39;s robot"), "claim")):
            pr2 = td / f"pred-ent-{tag}"
            shutil.copytree(pr, pr2)
            bad = copy.deepcopy(recs[sid])
            mutate(bad)
            (pr2 / "dora" / f"{sid}.jsonl").write_text(L.serialise_lines([bad]))
            (pr2 / "index.json").write_text(json.dumps(A.build_index(pr2, people, None), indent=1, sort_keys=True))
            write_year_summaries(pr2)
            p = render(None, f"ent-{tag}", preds=pr2)
            out = p.stdout + p.stderr
            check(f"ENTITY: an entity left in a {tag} record's {field} refuses the build, naming the record and field",
                  p.returncode != 0 and "entity" in out and bad["prediction_id"] in out and f".{field}" in out, out[-500:])

        # SCORE INFO (review 1 item 3). The resolver's "cannot be resolved" count is
        # split by eligibility, and the testable half is the Predictions panel's
        # Couldn't check: here 2, while 1 more was answered on a Not testable record.
        info_new = re.search(r"score: `(.*?)`,", page, re.S)
        info_old = re.search(r"score: `(.*?)`,", built["old"][2], re.S) if both else None
        check("SCORE INFO: the resolver's count is the Predictions panel's Couldn't check, and the rest are named",
              bool(info_new) and "did so 2 times on predictions that could be tested" in info_new.group(1)
              and "1 more time on a prediction that was not testable anyway" in info_new.group(1)
              and "(for the people listed: 1 ambiguous criterion, 1 no public evidence)" in page,
              info_new.group(1)[:900] if info_new else "no score info")
        check("SCORE INFO: the split is the same from the rows (old file) and from the corpus block (new file)",
              bool(info_old) and bool(info_new) and info_old.group(1) == info_new.group(1))

        # The strings must still agree with the flags; a disagreement is refused, never guessed.
        base = dora_scores(recs, run, True)
        for n, (label, mutate, needle) in enumerate((
                ("a not_eligible reason whose flag is not failing",
                 lambda d: d["predictions"][3].update(not_scored_because="not_eligible:specificity"), "specificity"),
                ("an unknown not_eligible reason",
                 lambda d: d["predictions"][3].update(not_scored_because="not_eligible:mystery"), "mystery"),
                # The needle is the new message's own words (review 1 item 4): the
                # prediction id alone was in main's generic refusal too.
                ("not_eligible on a row flagged eligible",
                 lambda d: d["predictions"][8].update(not_scored_because="not_eligible:lead_under_floor"),
                 "flags say it is eligible"),
                ("an ineligible row whose flags lack the lead time",
                 lambda d: d["predictions"][3]["flags"].pop("lead_days"), "lead_days"),
                # Review 1 item 6: a scored row with no flags is refused, never read as {}.
                ("a scored row with no funnel flags",
                 lambda d: d["predictions"][0].pop("flags"), "carries no funnel flags"),
                # Review 0 item 3: the trend rule is read, never assumed.
                ("a scores file that states no trend rule",
                 lambda d: (d["rule"].pop("trend"), d["settings"].pop("trend")), "trend rule"),
                ("a trend rule that disagrees with the trend setting",
                 lambda d: d["settings"].update(trend=False), "rule.trend"),
                # Final review item 2: two refusals had no test.
                ("a failing clause named that the shared order does not name first",
                 lambda d: [r.update(not_scored_because="not_eligible:lead_under_floor") for r in d["predictions"]
                            if r.get("not_scored_because") == "not_eligible:specificity"],
                 "order names"),
                ("a scored row whose flags say it is not eligible",
                 lambda d: d["predictions"][0]["flags"].update(eligible=False), "flags say it is not eligible"),
                ("a corpus split of unresolvable outcomes that disagrees with the rows",
                 lambda d: d["corpus"]["unresolvable_by_eligibility"]["eligible"].update(n=5),
                 "unresolvable_by_eligibility"))):
            doc = copy.deepcopy(base)
            mutate(doc)
            p = render(doc, f"bad-{n}")
            check(f"STATE: {label} refuses the render, naming it", p.returncode != 0 and needle in (p.stdout + p.stderr),
                  (p.stdout + p.stderr)[-400:])

        # TREND OFF: with the trend rule disabled, "Never checked" is true again.
        off = copy.deepcopy(base)
        off["rule"]["trend"]["enabled"] = False
        off["settings"]["trend"] = False
        s_off, _ = B.record_states({"dora": [recs["trend-later"]]}, {**off, "predictions": [], "restatements": {}})
        check("CARD: with the trend rule off, a directional claim with no date is never checked",
              s_off[by_sid["trend-later"]]["state"] == "no_deadline"
              and s_off[by_sid["trend-later"]]["line"] == "Never checked: it names no date this pipeline can read.",
              str(s_off[by_sid["trend-later"]]))
        # SHARED: the page asks phase2_resolvability for a record's flags and its
        # reason, so a record with no scores row follows the funnel's own rule.
        P2B = B.P2
        keep = getattr(P2B, "funnel_flags", None)
        s_sen = {by_sid["not-due"]: "phase2_resolvability has no funnel_flags"}
        if keep is not None:
            try:
                P2B.funnel_flags = lambda r, m: {**keep(r, m), "specificity_ok": False, "eligible": False}
                s_sen, _ = B.record_states({"dora": [recs["not-due"]]}, {**base, "predictions": [], "restatements": {}})
            finally:
                P2B.funnel_flags = keep
        check("SHARED: a record with no scores row takes its flags from phase2_resolvability.funnel_flags",
              (s_sen[by_sid["not-due"]] or {}).get("reason") == "specificity" if keep else False,
              str(s_sen[by_sid["not-due"]]))

        # REPLACEMENTS (funnel review 1 item 6). A replacement manifest leaves two
        # sidecars for one prediction; the page must read the replacement, as the
        # scorer did, and never refuse with "has sidecars in two runs".
        run2 = td / "run2"
        pid = by_sid["scored"]
        for sub, doc in (("priors", {"prediction_id": pid, "leader_slug": "dora", "stage": "prior", "p": 0.7, "p_raw": 0.7,
                                     "clamped": False, "reference_class": "r", "reasoning": "r", "harness": "fable",
                                     "telemetry": {"canonical_model": "claude-quill-1", "requested_model": "claude-quill-1",
                                                   "telemetry_models": ["claude-quill-1"]}}),
                         ("resolutions", {"prediction_id": pid, "leader_slug": "dora", "stage": "resolve",
                                          "outcome": "occurred", "harness": "astra",
                                          "telemetry": {"requested_model": "gpt-7-nova", "served_model": "gpt-7-nova"}})):
            (run2 / sub / "dora").mkdir(parents=True, exist_ok=True)
            (run2 / sub / "dora" / f"{pid}.json").write_text(json.dumps(doc))
        # The original prior priced it at 0.5, so a page that read the replaced
        # sidecar would refuse on the p check; the row carries the replacement's 0.7.
        orig = json.loads((run / "priors" / "dora" / f"{pid}.json").read_text())
        (run / "priors" / "dora" / f"{pid}.json").write_text(json.dumps(dict(orig, p=0.5, p_raw=0.5)))
        rep = copy.deepcopy(base)
        rep["run_dirs"] = [str(run), str(run2)]
        rep["replacements"] = {"manifest": "predictions/replacements.json", "manifest_sha256": "0" * 64,
                               "replaced_sidecars": [
                                   {"stage": st_, "prediction_id": pid, "run": str(run), "replacement": str(run2),
                                    "reason": "re-run", "was": None, "now": None,
                                    "deadline_was": "2025-12-31", "deadline_now": "2025-12-31"}
                                   for st_ in ("prior", "resolve")]}
        p = render(rep, "replaced")
        out_rep = p.stdout + p.stderr
        check("REPLACED: the page builds over a scores file that names replaced sidecars",
              p.returncode == 0, next((x for x in out_rep.splitlines() if "REFUSING" in x or "two runs" in x),
                                      out_rep[-500:]))
        check("REPLACED: the page names the replacement's models and not the replaced sidecars'",
              "'claude-quill-1': 1" in out_rep and "'gpt-7-nova': 1" in out_rep, out_rep[-500:])
        (run / "priors" / "dora" / f"{pid}.json").write_text(json.dumps(orig))

    # COPY: the lead floor is not "an announcement rather than a forecast" in every case.
    info = B.score_info({"scored": 7, "past_due": 20, "leaders_ranked": 4, "unresolvable_reasons": {},
                         "by_outcome": {"unresolvable": 3},
                         "unresolvable_split": {"eligible": {"n": 3, "reasons": {}}, "not_eligible": {"n": 0, "reasons": {}}}},
                        {"min_lead_days": 60, "baseline_only": "x", "clamp": 0.01})
    check("COPY: the lead-floor rule is not called an announcement in every case",
          "announcement rather than a forecast" not in info and "treats as an announcement" in info
          and "a few are real forecasts" in info, info[-500:])


def main() -> int:
    L = load("predictions_lib")
    A = load("aggregate_predictions")
    B = load("build_predictions_site")
    script = REPO / "scripts" / "build_predictions_site.py"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pr, roster, index = build(td, L, A)
        out = td / "site" / "index.html"
        p = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr), "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(out)],
                           capture_output=True, text=True, cwd=REPO)
        check("FIXTURE: builder exits 0 and writes the page", p.returncode == 0 and out.exists(), p.stdout + p.stderr[-500:])
        html = out.read_text()
        data, src, pred = embedded(html, "DATA"), embedded(html, "SRC"), records(out)
        check("FIXTURE: DATA and SRC parse, and the records are files beside the page",
              isinstance(data, list) and isinstance(src, dict) and sorted(pred) == ["ada", "alan", "cleo"],
              f"{sorted(pred)}")
        # Without a scores file there is no as-of date: a card may say a record has
        # no deadline, which needs no date, but never that a check is pending or done.
        nostate = [(r["prediction_id"], r.get("state")) for rs in pred.values() for r in rs
                   if (r.get("state") or {}).get("state") not in ("unchecked", "no_deadline") or (r.get("state") or {}).get("price")]
        check("STATE: without a scores file every card is unchecked or has no deadline, and none carries a price line",
              not nostate and any(r["state"]["state"] == "no_deadline" for rs in pred.values() for r in rs), str(nostate[:3]))

        # OFF BOARD. Operator request 2026-09-29: a person whose predictions cannot
        # yet be scored fairly is taken off the predictions board in membership.json.
        # The page must leave them out AND name them, never drop them silently.
        outm = td / "offboard" / "index.html"
        po = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster, off=("alan",))), "--out", str(outm)],
                            capture_output=True, text=True, cwd=REPO)
        htm = outm.read_text() if outm.exists() else ""
        rows_m = [r["slug"] for r in embedded(htm, "DATA")] if htm else []
        note_m = re.search(r'<p class="omitted" id="omitted">(.*?)</p>', htm, re.S)
        check("OFF BOARD: a person off the predictions board has no row and is named in the note",
              po.returncode == 0 and "alan" not in rows_m and "ada" in rows_m
              and bool(note_m) and "Alan T" in note_m.group(1) and "checked" in note_m.group(1),
              (po.stderr[-300:] + " rows " + str(rows_m) + " note " + (note_m.group(1) if note_m else "none"))[:700])
        pd = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster, drop=("cleo",))),
                             "--out", str(td / "dropm" / "index.html")], capture_output=True, text=True, cwd=REPO)
        check("OFF BOARD: a person missing from membership.json refuses the build, naming them",
              pd.returncode != 0 and "cleo" in pd.stderr + pd.stdout and "membership.json" in pd.stderr + pd.stdout,
              (pd.stderr + pd.stdout)[-300:])
        mem(roster)

        # YEAR SUMMARIES. The popover over a year square named the colour band
        # ("lightest blue: 1"). Operator request 2026-09-29: say what the person
        # predicted that year instead, in a few words a model wrote.
        YS = load("year_summaries")
        cells_ok = all(r.get("ysum") == {y: f"{r['slug']} predicted things in {y}" for y in r["years"]} for r in data)
        check("YEARS: every row carries the summary of each year it shows", cells_ok and any(r["years"] for r in data),
              json.dumps([(r["slug"], r["years"], r.get("ysum")) for r in data])[:400])
        check("YEARS: the popover shows the summary, never the colour band's name",
              "lightest blue" not in html and "BAND_WORDS" not in html and "ysum" in html)
        ydoc = json.loads((pr / "year_summaries.json").read_text())
        k0 = sorted(ydoc["entries"])[0]
        ydoc["entries"][k0]["inputs_sha256"] = "0" * 64
        (pr / "year_summaries.json").write_text(json.dumps(ydoc))
        py = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "ystale" / "index.html")], capture_output=True, text=True, cwd=REPO)
        check("YEARS: a summary written for different predictions refuses the build and names the fix",
              py.returncode != 0 and "year_summaries.py --write" in py.stderr + py.stdout and k0.split("/")[0] in py.stderr + py.stdout,
              py.stderr[-300:])
        (pr / "year_summaries.json").unlink()
        py = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "ystale" / "index.html")], capture_output=True, text=True, cwd=REPO)
        check("YEARS: a missing summaries file refuses the build", py.returncode != 0 and "missing" in py.stderr + py.stdout, py.stderr[-300:])
        write_year_summaries(pr)
        check("YEARS: a label that grades the outcome, or runs long, is refused",
              YS.check_answer({"2020": "Tesla robots on sale, which came true"}, ["2020"])
              and YS.check_answer({"2020": " ".join(["word"] * 11)}, ["2020"])
              and YS.check_answer({"2020": "fine"}, ["2020", "2021"])
              and not YS.check_answer({"2020": "Humanoid robots on sale at Tesla"}, ["2020"]))
        # FOUND 2026-09-29: the first live run failed 32 of 53 people, every one on
        # length, because the prompt stated the word cap and not the character cap.
        pr_txt = YS.build_prompt("Ada L", {"2020": [{"prediction": {"normalized_claim": "x"}}]})
        check("YEARS: the prompt states every limit the checker enforces",
              f"{YS.PROMPT_WORDS} words" in pr_txt and f"{YS.PROMPT_CHARS} characters" in pr_txt
              and YS.PROMPT_WORDS <= YS.MAX_WORDS and YS.PROMPT_CHARS <= YS.MAX_CHARS, pr_txt[:300])
        r0 = {"prediction_id": "a", "prediction": {"normalized_claim": "x"}}
        check("YEARS: the cell digest moves when a claim is re-extracted",
              YS.cell_digest([r0]) != YS.cell_digest([{**r0, "prediction": {"normalized_claim": "y"}}]))

        # COVERAGE. The drawer says "extraction ran on X of Y of their
        # transcripts". X counted every meta, withdrawn transcripts included,
        # while Y counted one transcript root, so the live page printed 22 of 15.
        idx = json.loads(index.read_text())
        lead = next(l for l in idx["leaders"] if l["slug"] == "ada")
        lead.update(transcripts_on_disk=15, transcripts_extracted=22, transcripts_extracted_in_corpus=15)
        row = next(r for r in B.person_rows(idx, {}, {}, {}) if r["slug"] == "ada")
        check("COVERAGE: the drawer's numerator counts only extracted transcripts still in the corpus",
              (row["tx_succeeded"], row["tx_attempted"]) == (15, 15), f"{row['tx_succeeded']} of {row['tx_attempted']}")

        # ------------------------------------------------------------------
        # PAYLOAD. The records were inline until 2026-09-17, which made this
        # page 4.7 MB. The board at verbatim-index carried its evidence the
        # same way at 16 MB, and Twitter's card validator refused it:
        # "Fetching the page failed because the response is too large", so the
        # link posted with no card although every og: tag was correct.
        # ------------------------------------------------------------------
        check("PAYLOAD: no prediction record is serialised into the page",
              '"prediction_id"' not in html and "by 2030 most code" not in html,
              f"page is {len(html.encode())} bytes")
        m = re.search(r'const PRED_VERSION = "([0-9a-f]+)"', html)
        check("PAYLOAD: the page carries a version for the record files", bool(m))
        check("PAYLOAD: the fetch url is per person and carries that version",
              "predictions/${encodeURIComponent(slug)}.json?v=${PRED_VERSION}" in html)
        sl = re.search(r"const PRED_SLUGS = (\[[^\]]*\])", html)
        check("PAYLOAD: the page names who has records",
              bool(sl) and json.loads(sl.group(1).replace("<\\/", "</")) == ["ada", "alan", "cleo"],
              sl.group(1) if sl else "none")
        stale_file = out.parent / "predictions" / "gone.json"
        stale_file.write_text("[]")
        p2 = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(out)],
                            capture_output=True, text=True, cwd=REPO)
        check("PAYLOAD: a file from an earlier render is deleted and named",
              p2.returncode == 0 and not stale_file.exists() and "gone.json" in p2.stdout,
              p2.stdout[-300:] + p2.stderr[-200:])
        p3 = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(out)],
                            capture_output=True, text=True, cwd=REPO,
                            env={**__import__("os").environ, "VI_MAX_PAGE_BYTES": "1000"})
        check("PAYLOAD: a page over the crawler budget is refused",
              p3.returncode != 0 and "1,000" in (p3.stderr + p3.stdout), p3.stderr[-300:])

        # ------------------------------------------------------------------
        # The page is a real HTML document and unfurls as a link.
        #
        # Until 2026-09-17 this page, like the leaderboard before it, had no
        # DOCTYPE, no <html>, no <head> and no <meta> tags at all: it began
        # with <title>. Browsers therefore rendered it in quirks mode, a phone
        # fell back to a ~980px layout viewport because no viewport meta said
        # otherwise, and Twitter and LinkedIn unfurled the link as a bare URL
        # with no title, description or image. Measured on the live site:
        # 0 meta tags.
        # ------------------------------------------------------------------
        check("SOCIAL: starts with a DOCTYPE, so browsers use standards mode",
              html.lstrip().lower().startswith("<!doctype html>"), repr(html[:60]))
        for frag, why in [('<html lang="en">', "declares its language"),
                          ('<meta charset="utf-8">', "declares its encoding"),
                          ('name="viewport"', "tells a phone to use device width"),
                          ("</head>", "closes the head"),
                          ("<body>", "opens a body"),
                          ("</html>", "closes the document")]:
            check(f"SOCIAL: page {why}", frag in html, f"missing {frag!r}")
        for prop in ("og:type", "og:url", "og:title", "og:description",
                     "og:image", "og:image:width", "og:image:height"):
            check(f"SOCIAL: has {prop}", f'property="{prop}"' in html)
        check("SOCIAL: twitter card is the large-image kind",
              'name="twitter:card" content="summary_large_image"' in html)
        for nm in ("twitter:title", "twitter:description", "twitter:image"):
            check(f"SOCIAL: has {nm}", f'name="{nm}"' in html)
        check("SOCIAL: has a canonical url", 'rel="canonical"' in html)
        check("SOCIAL: has a meta description", 'name="description"' in html)

        # A crawler has no page context, so every card URL must be absolute,
        # and must point at THIS site rather than the leaderboard beside it.
        card_urls = re.findall(
            r'(?:property|name)="(?:og:image|twitter:image|og:url)" content="([^"]+)"', html)
        check("SOCIAL: card urls are absolute",
              bool(card_urls) and all(u.startswith("https://") for u in card_urls), f"{card_urls}")
        check("SOCIAL: card urls name the predictions host, not the leaderboard",
              all("verbatim-predictions.tonygwu.com" in u for u in card_urls), f"{card_urls}")
        check("SOCIAL: card image carries a cache-busting version",
              any("og.png?v=" in u for u in card_urls), f"{card_urls}")

        # Social text must be rendered from the corpus, never left as a placeholder.
        headpart = html[:html.find("</head>")]
        check("SOCIAL: no unrendered placeholder survives in the head",
              not re.search(r"__[A-Z_]+__", headpart),
              str(re.findall(r"__[A-Z_]+__", headpart)[:5]))
        check("SOCIAL: the description carries the corpus counts",
              str(len(data)) in headpart, f"expected {len(data)} people named in the head")

        # Two fenced regions may name a verdict: the disclaimer, and the Score column, which now
        # holds a real number and whose copy has to be able to say so. Both fences are stripped
        # before the scan rather than the pattern being weakened, so an evaluative word ANYWHERE
        # else still fails. That matters more since the page began scoring, not less: the counts
        # and the drawer still measure nothing, and must not borrow the scoring column's language.
        # The score fence is written twice because it spans HTML and JS, where <!-- --> is not a comment.
        body = re.sub(r"<!-- disclaimer:start -->.*?<!-- disclaimer:end -->", "", html, flags=re.S)
        body = re.sub(r"<!-- score:start -->.*?<!-- score:end -->", "", body, flags=re.S)
        body = re.sub(r"/\* score:start \*/.*?/\* score:end \*/", "", body, flags=re.S)
        body = re.sub(r"const (DATA|SRC|PRED) = .*?;\n", "", body, flags=re.S)
        hits = sorted(set(m.group(0).lower() for m in re.finditer(
            r"\b(accuracy|accurate|brier|correct|incorrect|resolved|leaderboard|best forecaster|best predictor|score|skill|edge|rank|ranking|outperform)\b", body, re.I)))
        check("NEUTRAL: no evaluative vocabulary outside the disclaimer and the data", not hits, str(hits))
        check("NEUTRAL: the disclaimer block exists and is non-empty", "<!-- disclaimer:start -->" in html and "no Brier score" in html)

        check("SORT: with no scores file the default sort is name ascending, announced in static HTML",
              'let sortKey = "name", sortDir = 1;' in html and '<th data-k="name" aria-sort="ascending">' in html)
        keys = re.findall(r'data-k="([a-z_]+)"', html)
        # FIVE columns. The five horizon and confidence breakdown columns moved into the
        # drawer on 2026-09-13: they are three ways of splitting one count and read as a
        # scoreboard in a table that scores nothing. Earliest and Latest became one
        # sparkline on 2026-09-14. Score arrived empty and now carries a number.
        # Transcripts was removed on 2026-09-16: it counts recordings, which is a
        # property of what was COLLECTED rather than of the person, and it was actively
        # misleading beside a Score column, because a high transcript count says nothing
        # about whether anything of theirs has come due.
        check("SORT: the column keys are exactly the allowed set",
              # No scores file in this build, so Score is the nosort variant and
              # carries no data-k. The live-scores build below asserts it gains one.
              keys == ["name", "company", "accepted", "earliest"], str(keys))
        # With a scores file the two judgement columns gain sort keys; without one
        # they are inert, because an empty column that looks sortable implies data.

        check("SORT: the dropped breakdown keys are still embedded in DATA and shown in the drawer",
              all(k in data[0] for k in ("h_explicit", "h_inferable", "h_none", "p_explicit", "p_qual"))
              and "${person.h_explicit} named in the quote" in html
              and "${person.p_qual} where the speaker used words of likelihood" in html, str(sorted(data[0])))
        ncols = len(re.findall(r"<col(?:>| style)", html))
        # ---- the year axis ---------------------------------------------------
        # The axis is its own row under the header, so every header label shares one
        # baseline. Three things about it are load-bearing and none is visible in a
        # diff of the JS alone.
        axisrow = re.search(r'<tr class="axisrow">(.*?)</tr>', html, re.S)
        check("AXIS: the gutter row carries one cell per column, or it shears the table",
              bool(axisrow) and len(re.findall(r"<td", axisrow.group(1))) == ncols,
              f"{len(re.findall(r'<td', axisrow.group(1))) if axisrow else None} cells vs {ncols} columns")
        # EVERY square names its own year. Three labels floating over fifteen squares
        # made a reader count columns to place a shaded one, and a later edit that
        # puts the label back behind the five-year test would undo that silently.
        check("AXIS: every year is labelled, not only the five-year marks",
              ">&rsquo;${y.slice(2)}</i>" in html,
              [l for l in html.splitlines() if "y.slice(2)" in l])
        check("AXIS: the five-year marks stay emphasised, so the run of years has anchors",
              ".sq-ax i.tick{color:var(--ink-2); font-weight:600}" in html)
        # The axis HUGS the strip. A rule under it turns it back into a band of its
        # own, which is what it looked like before and what the operator rejected.
        gutter = re.search(r"tr\.axisrow td\{(.*?)\}", html, re.S)
        check("AXIS: the gutter has no rule under it, so it reads as the top of the timeline",
              bool(gutter) and "border-bottom" not in gutter.group(1),
              gutter.group(1) if gutter else "no tr.axisrow td rule")
        # The Score column has two modes and BOTH are load-bearing. Without a scores file it must
        # stay inert, because an empty column that looks sortable implies data that is not there.
        # With one it must carry the number, the count it was averaged over, and a sort key.
        check("SCORE: with no scores file the column is inert and carries no key or data field",
              'class="nosort">Score' in html and not re.search(r'data-k="score"', html)
              and all(d.get("score") is None for d in data)
              and "Score is empty on every row" in html, str(sorted(data[0])))
        check("SCORE: an unscored row renders an em dash and says WHY on hover, never a zero",
              'if (r.score == null) return `<td class="sc none"' in html
              and all(d["score_why"] for d in data), str([d.get("score_why") for d in data]))

        # ---- the same page, built WITH a scores file -------------------------
        # The empty column above is the safe default. This is the mode that actually
        # publishes a judgement, so every claim it makes has to hold: the number, the
        # count it averages, the rank floor, and the refusal to show a number for
        # somebody the aggregation does not cover.
        scores = td / "scores.json"
        scored_pid = pred[sorted(pred)[0]][0]["prediction_id"]
        # The prior and resolution sidecars the scorer joined. The page names the
        # model that set each p, and it reads that name out of these records, the
        # same run directories scores.json says it was computed from.
        run1 = td / "run1"
        prior_doc = {"prediction_id": scored_pid, "leader_slug": "ada", "stage": "prior", "p": 0.25,
                     "p_raw": 0.25, "clamped": False, "reference_class": "things like this",
                     "reasoning": "r", "harness": "fable",
                     "telemetry": {"canonical_model": "claude-fable-5-1", "requested_model": "claude-fable-5-1",
                                   "telemetry_models": ["claude-fable-5-1"]}}
        (run1 / "priors" / "ada").mkdir(parents=True)
        (run1 / "priors" / "ada" / f"{scored_pid}.json").write_text(json.dumps(prior_doc))
        (run1 / "resolutions" / "ada").mkdir(parents=True)
        (run1 / "resolutions" / "ada" / f"{scored_pid}.json").write_text(json.dumps(
            {"prediction_id": scored_pid, "leader_slug": "ada", "stage": "resolve", "outcome": "occurred",
             "harness": "astra", "telemetry": {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}}))
        # The corpus block counts cleo, who is under the list floor: 1 past due, 1
        # unresolvable. The page must describe the LISTED people, so every figure
        # it prints is the corpus figure minus cleo's: 8 of 9, not 8 of 10.
        scores.write_text(json.dumps({
            "as_of": "2026-09-14",
            "run_dirs": [str(run1)],
            "settings": {"as_of": "2026-09-14", "trend": True, "min_lead_days": 60},
            "rule": {"clamp": 0.01, "min_scored_to_rank": 5, "min_lead_days": 60,
                     "baseline_only": "points = -log2(p) if it happened, else (p/(1-p))*log2(p)"},
            "corpus": {"past_due": 10, "eligible": 10, "scored": 8, "leaders_ranked": 1,
                       "by_outcome": {"occurred": 5, "not_occurred": 3, "unresolvable": 2},
                       "unresolvable_reasons": {"no_public_evidence": 1, "criterion_ambiguous": 1}},
            "leaders": [
                {"slug": "ada", "name": "Ada L", "n_scored": 6, "mean_points": 1.2345,
                 "ranked": True, "past_due": 7, "eligible": 7, "unresolvable": 1,
                 "scored_occurred": 4, "hit_rate": 0.6667},
                {"slug": "alan", "name": "Alan T", "n_scored": 2, "mean_points": -0.5,
                 "ranked": False, "past_due": 2, "eligible": 2, "unresolvable": 0,
                 "scored_occurred": 1, "hit_rate": 0.5},
                {"slug": "cleo", "name": "Cleo F", "n_scored": 0, "mean_points": None,
                 "ranked": False, "past_due": 1, "eligible": 1, "unresolvable": 1,
                 "scored_occurred": 0, "hit_rate": None}],
            "predictions": [
                {"prediction_id": scored_pid, "leader_slug": "ada", "outcome": "occurred", "scored": True,
                 "unresolvable_reason": None, "resolution_reasoning": "it shipped",
                 "sources": [{"where": "https://example.com/a", "what_it_shows": "shipped",
                              "date": "2026-01-02"}],
                 "p": 0.25, "reference_class": "things like this", "points": 2.0, "deadline": "2026-06-30",
                 "flags": fl(True, 486), "not_scored_because": None},
                # Every unscored row carries the funnel flags, as score_predictions.join
                # writes them; the page reads eligibility off them for every such row.
                {"prediction_id": pred["ada"][1]["prediction_id"], "leader_slug": "ada", "outcome": "unresolvable", "scored": False,
                 "unresolvable_reason": "criterion_ambiguous", "resolution_reasoning": "x", "sources": [],
                 "p": None, "reference_class": None, "points": None, "deadline": "2026-06-30",
                 "flags": fl(True, 486), "not_scored_because": "unresolvable:criterion_ambiguous"},
                {"prediction_id": pred["cleo"][0]["prediction_id"], "leader_slug": "cleo", "outcome": "unresolvable", "scored": False,
                 "unresolvable_reason": "no_public_evidence", "resolution_reasoning": "x", "sources": [],
                 "p": None, "reference_class": None, "points": None, "deadline": "2026-06-30",
                 "flags": fl(True, 486), "not_scored_because": "unresolvable:no_public_evidence"}],
        }))
        out2 = td / "site" / "scored.html"
        p2 = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(out2), "--scores", str(scores)],
                            capture_output=True, text=True, cwd=REPO)
        check("SCORE: the builder accepts a scores file and exits 0",
              p2.returncode == 0 and out2.exists(), p2.stdout + p2.stderr[-600:])
        h2 = out2.read_text()
        d2 = {r["slug"]: r for r in embedded(h2, "DATA")}
        check("SCORE: a ranked person carries the mean and the count it was averaged over",
              d2["ada"]["score"] == 1.2345 and d2["ada"]["n_scored"] == 6, str(d2["ada"].get("score")))
        check("SCORE: a person BELOW the floor carries no number but keeps the count, never a zero",
              d2["alan"]["score"] is None and d2["alan"]["n_scored"] == 2
              and "floor" in d2["alan"]["score_why"], str(d2["alan"]))
        check("HITS: a ranked person shows the count that came true over the count scored",
              d2["ada"]["score_hits"] == 4 and d2["ada"]["n_scored"] == 6,
              str((d2["ada"].get("score_hits"), d2["ada"].get("n_scored"))))
        # The fraction is a plain count and needs no floor to be honest; only the
        # mean is the noisy statistic the floor protects. Before 2026-09-27 both
        # cells were blank below the floor, and a reader who opened Bill Gurley's
        # drawer saw two resolved misses under a row that said nothing.
        check("HITS: a person BELOW the floor still shows the fraction, and is marked unranked",
              d2["alan"]["score_hits"] == 1 and d2["alan"]["n_scored"] == 2
              and d2["alan"]["ranked"] is False and d2["alan"]["hit_rate"] == 0.5,
              str({k: d2["alan"].get(k) for k in ("score_hits", "n_scored", "ranked", "hit_rate")}))
        check("HITS: a ranked person is marked ranked, so the cell can tell the two apart",
              d2["ada"]["ranked"] is True, str(d2["ada"].get("ranked")))
        check("HITS: the cell says on hover that an unranked fraction sits below the floor",
              "hitCell" in h2 and "r.ranked" in h2 and "below the floor" in h2
              and '"hit unranked"' in h2)
        none_scored = B.person_rows(idx, {}, {}, {"alan": {
            "n_scored": 0, "mean_points": None, "ranked": False, "past_due": 2,
            "eligible": 0, "unresolvable": 2, "scored_occurred": 0, "hit_rate": None}}, 60)
        alan0 = next(r for r in none_scored if r["slug"] == "alan")
        check("HITS: a person with NOTHING scored carries no fraction, never 0/0",
              alan0["score_hits"] is None and alan0["hit_rate"] is None and alan0["n_scored"] == 0,
              str({k: alan0[k] for k in ("score_hits", "hit_rate", "n_scored")}))
        check("HITS: the ? panel says the fraction has no floor and Score does",
              "no floor" in B.came_true_info({"scored": 6, "past_due": 9}), B.came_true_info({}) [:200])
        check("HITS: the numerator is STORED, never recovered from hit_rate times n",
              "scored_occurred" in json.loads(scores.read_text())["leaders"][0])

        check("SCORE: the column becomes sortable only once there is something to sort",
              'data-k="score"' in h2 and 'class="nosort">Score' not in h2)
        # The masthead must not contradict the table. A page carrying numbers while its
        # own first sentence says nothing has been checked is worse than either alone.
        # A row for somebody with nothing that has come due says nothing on a board
        # that reports resolved foresight. alan has past_due 2 in the fixture and
        # stays; a person absent from the scores file has nothing due and goes.
        names2 = {r["name"] for r in embedded(h2, "DATA")}
        check("LIST: a person with no past-due prediction is not listed at all",
              "Ada L" in names2 and "Alan T" in names2 and len(names2) == 2, str(names2))
        thin = td / "thin.json"
        tdoc = json.loads(scores.read_text())
        tdoc["leaders"] = [dict(l, past_due=0, eligible=0, n_scored=0, ranked=False) if l["slug"] == "alan" else l
                           for l in tdoc["leaders"]]
        tdoc["corpus"].update(past_due=8, eligible=8, scored=6)
        thin.write_text(json.dumps(tdoc))
        p5 = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "site" / "t.html"),
                             "--scores", str(thin)], capture_output=True, text=True, cwd=REPO)
        n5 = {r["name"] for r in embedded((td / "site" / "t.html").read_text(), "DATA")}
        check("LIST: dropping a person's past-due count to 0 removes their row",
              p5.returncode == 0 and n5 == {"Ada L"}, f"{p5.returncode} {n5}")
        check("LIST: with NO scores file the past-due rule hides nobody; only the count floor applies",
              {r["name"] for r in data} == {"Ada L", "Alan T"}, str({r["name"] for r in data}))

        check("SCORE: the masthead stops claiming everything is pending once anything is scored",
              "Every item pending" not in h2 and "every item\n    is pending" not in h2
              and "8 of 9 due predictions resolved" in h2, 
              [l for l in h2.splitlines() if "pending" in l.lower()][:3])
        # The intro replaced the disclaimer sentence on 2026-09-27 and still has
        # to say what the score leaves out, in its own figures.
        check("SCORE: the intro says the score covers only the past-due predictions it could check",
              "So far 8 of 9 past-due predictions could be checked and scored" in h2,
              [l for l in h2.splitlines() if "could not be resolved" in l][:2])
        check("SCORE: with no scores file the page still says everything is pending",
              "Every item pending" in html and "every item is" in html)

        check("SCORE: the page reports the corpus figures from the file, not typed numbers",
              "8 of 9 past-due predictions" in h2 and "did so 1 time" in h2,
              [l for l in h2.splitlines() if "past-due predictions" in l][:2])
        check("SCORE: the rank floor named on the page is the aggregation constant",
              # Pinned to the constant, not to a literal: the operator moved it
              # from 5 to 3 on 2026-09-16 and the page must follow automatically.
              f"below {B.MIN_SCORED} resolved predictions" in h2 and B.MIN_SCORED == 3)
        check("SCORE: the evaluative vocabulary is still fenced with a live column",
              not sorted(set(m.group(0).lower() for m in re.finditer(
                  r"\b(accuracy|brier|leaderboard|outperform|score|rank)\b",
                  re.sub(r"/\* score:start \*/.*?/\* score:end \*/", "",
                         re.sub(r"<!-- score:start -->.*?<!-- score:end -->", "",
                                re.sub(r"<!-- disclaimer:start -->.*?<!-- disclaimer:end -->", "", h2, flags=re.S),
                                flags=re.S), flags=re.S).split("const DATA")[0], re.I))))

        # A scores file may cover MORE predictions than the page embeds, which is what
        # happens when several corpora are scored together and only one is rendered.
        # Then a person's number is averaged over predictions their own drawer cannot
        # show, and nothing on the page says so.
        wide = td / "wide.json"
        wdoc = json.loads(scores.read_text())
        wdoc["predictions"] = wdoc["predictions"] + [
            {"prediction_id": "not-on-this-page", "leader_slug": "ada", "outcome": "occurred",
             "scored": True, "unresolvable_reason": None, "resolution_reasoning": "x",
             "sources": [], "p": 0.5, "reference_class": "c", "points": 1.0,
             "not_scored_because": None}]
        wide.write_text(json.dumps(wdoc))
        p4 = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "site" / "w.html"),
                             "--scores", str(wide)], capture_output=True, text=True, cwd=REPO)
        check("SCORE: a scored prediction the page cannot show fails the render, naming the person",
              p4.returncode != 0 and "ada" in (p4.stdout + p4.stderr)
              and "drawer cannot show" in (p4.stdout + p4.stderr),
              (p4.stdout + p4.stderr)[-300:])

        # A scores file describing somebody the page does not carry means the two inputs
        # were built from different corpora, which would show up as a missing row.
        stray = td / "stray.json"
        doc = json.loads(scores.read_text())
        doc["leaders"].append({"slug": "ghost", "name": "G", "n_scored": 9, "mean_points": 9.0,
                               "ranked": True, "past_due": 9, "eligible": 9, "unresolvable": 0})
        stray.write_text(json.dumps(doc))
        p3 = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
                             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "site" / "x.html"),
                             "--scores", str(stray)], capture_output=True, text=True, cwd=REPO)
        # The drawer is what makes a published number auditable. A reader who doubts a
        # score has to be able to see the outcome, the sources it rests on and the p it
        # was priced at, without leaving the page.
        pr2 = records(out2)
        # Three rows of the scores file name records on the page since task 7:
        # one scored, two that could not be resolved.
        outs = [r for rs in pr2.values() for r in rs if r.get("outcome") and r["outcome"]["verdict"] == "occurred"]
        check("DRAWER: a resolved prediction carries its outcome, evidence, p and points",
              len(outs) == 1 and outs[0]["outcome"]["verdict"] == "occurred"
              and outs[0]["outcome"]["sources"][0]["where"].startswith("http")
              and outs[0]["outcome"]["p"] == 0.25 and outs[0]["outcome"]["points"] == 2.0,
              str(outs[0]["outcome"] if outs else "no outcome attached"))
        check("DRAWER: an unresolved prediction carries no outcome key at all, not a null one",
              sum(1 for rs in pr2.values() for r in rs if "outcome" in r) == 3,
              "an empty outcome object would render as a verdict")
        check("DRAWER: the telemetry of the resolving call never reaches the page",
              not any(k in outs[0]["outcome"] for k in ("telemetry", "run_id", "account", "harness")),
              str(sorted(outs[0]["outcome"])))
        check("DRAWER: a markdown source link renders its label, not its brackets",
              r'.replace(/^\[|\]$/g, "")' in h2)

        check("SCORE: a score for somebody not on the page fails the render, naming them",
              p3.returncode != 0 and "ghost" in (p3.stdout + p3.stderr),
              (p3.stdout + p3.stderr)[-300:])

        # ---- 2026-09-27 operator changes: list floor, sort, column, popover, intro, prior ----
        run = lambda *extra, out_name, env=None: subprocess.run(  # noqa: E731
            [PY, str(script), "--data-date", "2026-09-10", "--index", str(index), "--predictions", str(pr),
             "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "site" / out_name), *extra],
            capture_output=True, text=True, cwd=REPO, env=env)

        # LIST FLOOR. One named constant, not a list of names, so a person who
        # later gains predictions comes back without an edit.
        check("FLOOR: the list floor is one named constant, 4 accepted predictions",
              getattr(B, "MIN_PREDICTIONS_TO_LIST", None) == 4, str(getattr(B, "MIN_PREDICTIONS_TO_LIST", None)))
        names_h2 = [r["name"] for r in embedded(h2, "DATA")]
        check("FLOOR: a person under the floor has no row, with or without scores",
              "Cleo F" not in names_h2 and "Cleo F" not in [r["name"] for r in data], f"{names_h2}")
        check("FLOOR: a person exactly ON the floor keeps their row",
              "Ada L" in names_h2 and "Alan T" in names_h2, f"{names_h2}")
        om = re.search(r'<p class="omitted" id="omitted">(.*?)</p>', h2, re.S)
        check("FLOOR: the page NAMES the omitted person with their count and the reason, on its own line",
              bool(om) and "Cleo F (1)" in om.group(1) and "fewer than 4" in om.group(1),
              om.group(1) if om else "no omitted note")
        check("FLOOR: the note says the omitted predictions still count in the totals above",
              bool(om) and "1 prediction still counts in the totals" in om.group(1),
              om.group(1) if om else "no omitted note")
        om0 = re.search(r'<p class="omitted" id="omitted">(.*?)</p>', html, re.S)
        check("FLOOR: with no scores file the note still names who is under the floor",
              bool(om0) and "Cleo F (1)" in om0.group(1), om0.group(1) if om0 else "no omitted note")
        idx4 = json.loads(index.read_text())
        next(l for l in idx4["leaders"] if l["slug"] == "cleo")["accepted"] = 4
        check("FLOOR: a person who reaches the floor reappears automatically",
              "cleo" in [r["slug"] for r in B.person_rows(idx4, {}, {}, {})],
              str([r["slug"] for r in B.person_rows(idx4, {}, {}, {})]))
        bad_sum = td / "badsum.json"
        bdoc = json.loads(scores.read_text())
        bdoc["corpus"]["past_due"] = 11
        bad_sum.write_text(json.dumps(bdoc))
        pb = run("--scores", str(bad_sum), out_name="bs.html")
        check("FLOOR: per-person score counts that do not add up to the corpus block refuse the render",
              pb.returncode != 0 and "do not add up" in (pb.stdout + pb.stderr), (pb.stdout + pb.stderr)[-300:])

        # SORT. Score, highest first, once there is a Score; unscored rows after
        # every scored one, alphabetical among themselves, in both directions.
        check("SORT: with scores the default sort is Score descending, announced in static HTML",
              'let sortKey = "score", sortDir = -1;' in h2
              and '<th data-k="score" aria-sort="descending">' in h2
              and '<th data-k="name" aria-sort' not in h2,
              [l for l in h2.splitlines() if "let sortKey" in l])
        sample = [{"name": "Zed", "score": None}, {"name": "Amy", "score": None},
                  {"name": "Bo", "score": 0.5}, {"name": "Cy", "score": 1.0}, {"name": "Al", "score": 0.5}]
        order = [r["name"] for r in B.default_order(sample, scored=True)] if hasattr(B, "default_order") else None
        check("SORT: default order is score descending, ties and unscored rows alphabetical, unscored last",
              order == ["Cy", "Al", "Bo", "Amy", "Zed"], str(order))
        check("SORT: no sentence on the scored page says the default is alphabetical",
              not re.search(r"default is alphabetical|alphabetical by default|the table is alphabetical", h2),
              str(re.findall(r"[^.]*alphabetical[^.]*", h2)[:3]))

        # ORGANISATION column. It was 205px and mostly white space.
        cols = re.findall(r'<col style="width:(\d+)px">', h2)
        check("ORG: the Organisation column is at most 150px", len(cols) == 6 and int(cols[1]) <= 150, str(cols))

        # POPOVER on the year squares. Behaviour is proven in a browser by
        # scripts/check_predictions_site_ui.py; these pin the parts a refactor
        # would silently drop.
        check("POPOVER: a popover element exists for the year squares",
              'id="sqtip"' in h2 and 'role="tooltip"' in h2)
        check("POPOVER: squares carry their year and count as data, not a native title",
              'data-y="${yr}" data-n="${n}"' in h2 and 'title="${yr}: ${n}' not in h2)
        check("POPOVER: text colour is held to WCAG AA 4.5:1 against the popover",
              "const AA = 4.5;" in h2 and "function readable(" in h2)
        check("POPOVER: it opens on hover, on keyboard focus and on tap",
              "sqShow(" in h2 and "pointerover" in h2 and "focusin" in h2 and 'pointerType === "touch"' in h2)
        check("POPOVER: the timeline help no longer types a people count",
              "shared by all 50 people" not in h2)

        # INTRO. Written for a general reader, every number derived.
        thesis = re.search(r'<p class="thesis">(.*?)</p>', h2, re.S)
        th = thesis.group(1) if thesis else ""
        check("INTRO: the scored page opens with the question, a derived people count and the repo link",
              "Who in tech or finance is best at predicting the future?" in th
              and f"{len(names_h2)} tech leaders" in th
              and 'href="https://github.com/tonygwu/verbatim-index"' in th, th[:400])
        check("INTRO: the intro states what the score covers, from the listed people's figures",
              "8 of 9 past-due predictions could be checked" in th and "1 person has enough" in th, th[:600])
        head2 = h2[:h2.find("</head>")]
        check("INTRO: the social description matches the intro once there is a score",
              'name="description" content="Who in tech or finance is best at predicting the future?' in head2
              and 'property="og:description" content="Who in tech' in head2, head2[-900:])
        th0 = re.search(r'<p class="thesis">(.*?)</p>', html, re.S)
        check("INTRO: with no scores file the intro stays an index and claims no score",
              bool(th0) and "Who in tech" not in th0.group(1) and "Forward-looking claims" in th0.group(1))

        # PRIOR. The explanation names the model from the prior records and
        # prints numbers computed by prediction_score, never typed ones.
        PS = load("prediction_score")
        f2 = lambda x: ("+" if x >= 0 else "−") + f"{abs(x):.2f}"  # noqa: E731
        hs = re.search(r'<div class="howscore" id="howscore">(.*?)</div>\s*<!-- score:end -->', h2, re.S)
        hb = hs.group(1) if hs else ""
        check("PRIOR: the index section explains p, and names the prior model read from its records",
              "Claude Fable 5.1" in hb and "does not see what happened" in hb and "OpenAI GPT-6 Astra" in hb,
              hb[:500])
        want = [f2(PS.score(True, pp)["points"]) for pp in (0.9, 0.1)] + [f2(PS.score(False, pp)["points"]) for pp in (0.9, 0.1)]
        check("PRIOR: the worked example prints the scoring function's own numbers",
              bool(hb) and all(w in hb for w in want), f"{want} in {hb[-700:]}")
        nodir = td / "nodir.json"
        ndoc = json.loads(scores.read_text())
        ndoc["run_dirs"] = [str(td / "no-such-run")]
        nodir.write_text(json.dumps(ndoc))
        pn = run("--scores", str(nodir), out_name="nd.html")
        check("PRIOR: a scores file whose run directory is missing refuses the render, naming it",
              pn.returncode != 0 and "no-such-run" in (pn.stdout + pn.stderr), (pn.stdout + pn.stderr)[-300:])
        # run_dirs are written two ways: from a clone root as data/predictions/...
        # (until data a5525e31) and from the data checkout root as predictions/...
        # (since). Both resolve inside the checkout that holds scores.json.
        droot = td / "droot"
        (droot / "predictions" / "_experiments" / "r1").mkdir(parents=True)
        spath = droot / "predictions" / "scores.json"
        try:
            got = B.run_dirs({"run_dirs": ["data/predictions/_experiments/r1", "predictions/_experiments/r1"]}, str(spath))
        except SystemExit as err:
            got = str(err)
        check("PRIOR: run_dirs resolve in both the data/-prefixed and the checkout-relative form",
              got == [droot.resolve() / "predictions" / "_experiments" / "r1"] * 2, str(got))
        mism = td / "mism.json"
        mdoc = json.loads(scores.read_text())
        mdoc["predictions"][0]["p"] = 0.5
        mism.write_text(json.dumps(mdoc))
        pm = run("--scores", str(mism), out_name="mm.html")
        check("PRIOR: a scored p that differs from its prior record refuses the render",
              pm.returncode != 0 and scored_pid in (pm.stdout + pm.stderr), (pm.stdout + pm.stderr)[-300:])

        # ---- task 7: the Predictions column says where each prediction stands ----
        # Withdrawn joined as the eighth on 2026-09-30 (ledger VD-9): a prediction the
        # operator withdrew still counts toward the total, so the lines still add up.
        want_labels = ["Scored", "Not yet due", "No deadline", "Awaiting check", "Not testable", "Couldn't check",
                       "Restated", "Withdrawn"]
        check("BUCKETS: eight buckets in a fixed order with short plain labels",
              [lab for _, lab in getattr(B, "BUCKETS", ())] == want_labels, str(getattr(B, "BUCKETS", None)))
        dd = {r["slug"]: r for r in embedded(h2, "DATA")}
        check("BUCKETS: derived per person from the records and scores.json",
              dd["ada"].get("buckets") == {"scored": 1, "unresolvable": 1, "not_due": 2}
              and dd["alan"].get("buckets") == {"not_due": 3, "no_deadline": 1},
              f"{dd['ada'].get('buckets')} {dd['alan'].get('buckets')}")
        check("BUCKETS: the unresolvable line carries its split by reason",
              dd["ada"].get("unres") == {"criterion_ambiguous": 1}, str(dd["ada"].get("unres")))
        check("BUCKETS: every row's buckets add up to its total",
              all(sum((r.get("buckets") or {"x": -1}).values()) == r["accepted"] for r in dd.values()),
              str({s: (r.get("buckets"), r["accepted"]) for s, r in dd.items()}))
        check("BUCKETS: with no scores file there is no as-of date, so no breakdown",
              all(r.get("buckets") is None for r in data), str([r.get("buckets") for r in data]))
        try:
            getattr(B, "check_buckets_sum", lambda rows: None)([{"name": "Xavier Q", "accepted": 3, "buckets": {"scored": 1}}])
            refused = ""
        except SystemExit as err:
            refused = str(err)
        check("BUCKETS: a row whose buckets do not add up refuses the render, naming the person",
              "Xavier Q" in refused, refused or "no refusal")
        odd = td / "odd.json"
        odoc = json.loads(scores.read_text())
        odoc["predictions"][1]["not_scored_because"] = "mystery_reason"
        odd.write_text(json.dumps(odoc))
        po = run("--scores", str(odd), out_name="odd.html")
        check("BUCKETS: a not-scored reason the page does not know refuses the render, naming it",
              po.returncode != 0 and "mystery_reason" in (po.stdout + po.stderr), (po.stdout + po.stderr)[-300:])
        # The scorer names `no_resolution` before it checks eligibility, so an unresolved
        # row can be one that will NEVER be resolved (lead under the floor). Found
        # 2026-09-28: 33 such rows read "Awaiting check" on the integrated board.
        for elig, want, tag in ((False, "not_testable", "inel"), (True, "awaiting", "elig")):
            ndoc = json.loads(scores.read_text())
            ndoc["predictions"][1].update(not_scored_because="no_resolution", outcome=None,
                                          flags=fl(elig, 486 if elig else 20))
            ndoc["corpus"]["unresolvable_reasons"].pop("criterion_ambiguous", None)
            (td / f"nores-{tag}.json").write_text(json.dumps(ndoc))
            pn = run("--scores", str(td / f"nores-{tag}.json"), out_name=f"nores-{tag}.html")
            got = ({r["slug"]: r for r in embedded((td / "site" / f"nores-{tag}.html").read_text(), "DATA")}
                   .get("ada", {}).get("buckets") if pn.returncode == 0 else (pn.stdout + pn.stderr)[-200:])
            check(f"BUCKETS: an unresolved row with eligible={elig} counts as {want}",
                  isinstance(got, dict) and got.get(want) == 1 and "awaiting" not in got if not elig
                  else isinstance(got, dict) and got.get(want) == 1, str(got))
        ndoc = json.loads(scores.read_text())
        ndoc["predictions"][1].update(not_scored_because="no_resolution", outcome=None)
        ndoc["predictions"][1].pop("flags", None)
        ndoc["corpus"]["unresolvable_reasons"].pop("criterion_ambiguous", None)
        (td / "nores-noflags.json").write_text(json.dumps(ndoc))
        pn = run("--scores", str(td / "nores-noflags.json"), out_name="nores-noflags.html")
        check("BUCKETS: an unresolved row with no eligibility flag refuses the render, never guesses",
              pn.returncode != 0 and "eligib" in (pn.stdout + pn.stderr), (pn.stdout + pn.stderr)[-300:])
        stray_row = td / "strayrow.json"
        sdoc = json.loads(scores.read_text())
        sdoc["predictions"].append(dict(sdoc["predictions"][1], prediction_id="not-a-page-record"))
        stray_row.write_text(json.dumps(sdoc))
        pr_ = run("--scores", str(stray_row), out_name="sr.html")
        check("BUCKETS: a scored-file row that is no record on the page refuses the render",
              pr_.returncode != 0 and "not-a-page-record" in (pr_.stdout + pr_.stderr), (pr_.stdout + pr_.stderr)[-300:])
        check("BUCKETS: the column is left-aligned, header and cells, and still sorts by the total",
              '<th class="pc" data-k="accepted">' in h2 and "td.pc{" in h2 and "th.pc{text-align:left" in h2)
        check("BUCKETS: the (?) help names every bucket and the scoring as-of date",
              all(lab.replace("'", "&#39;") in h2 or lab in h2 for lab in want_labels)
              and "as of 2026-09-14" in h2)

        # ---- 2026-09-28: a restated prediction is shown ONCE ----
        # scores.json carries the scorer's `restatements` block. Ada said the "by
        # 2030" claim in two recordings (s1 and s3). The cluster's specific member
        # is the scored record; the other is restated, and the scorer listed it
        # with `restated:<specific>`.
        spec_pid = scored_pid
        spec_quote = pred["ada"][0]["quote"]
        twin = next(r for r in pred["ada"][1:] if r["quote"] == spec_quote and r["prediction_id"] != spec_pid)
        rdoc = json.loads(scores.read_text())
        rdoc["restatements"] = {"manifest": "predictions/restatements.json", "manifest_sha256": "0" * 64,
                                "clusters": [{"cluster_id": "ada/code-by-2030", "leader_slug": "ada",
                                              "specific_member": spec_pid,
                                              "members": [spec_pid, twin["prediction_id"]]}],
                                "superseded_resolutions": [], "restated_rows": 1}
        rdoc["predictions"].append({"prediction_id": twin["prediction_id"], "leader_slug": "ada", "outcome": None,
                                    "scored": False, "unresolvable_reason": None, "resolution_reasoning": None,
                                    "sources": [], "p": None, "reference_class": None, "points": None,
                                    "not_scored_because": f"restated:{spec_pid}", "restated_by": spec_pid})
        rdoc["corpus"]["restated"] = 1
        for l in rdoc["leaders"]:
            l["restated"] = 1 if l["slug"] == "ada" else 0
        rsc = td / "restated.json"
        rsc.write_text(json.dumps(rdoc))
        prs = run("--scores", str(rsc), out_name="rs.html")
        check("RESTATED: the builder accepts a scores file with restatements", prs.returncode == 0,
              (prs.stdout + prs.stderr)[-600:])
        hr = (td / "site" / "rs.html").read_text() if prs.returncode == 0 else ""
        if os.environ.get("VI_KEEP_RESTATED_SITE") and prs.returncode == 0:
            keep = Path(os.environ["VI_KEEP_RESTATED_SITE"])
            shutil.copytree(td / "site", keep, dirs_exist_ok=True)
        precs = records(td / "site" / "rs.html") if prs.returncode == 0 else {}
        dr = {r["slug"]: r for r in embedded(hr, "DATA")} if hr else {}
        check("RESTATED: a seventh bucket, Restated, before Withdrawn",
              [lab for _, lab in getattr(B, "BUCKETS", ())][-2:] == ["Restated", "Withdrawn"]
              and len(getattr(B, "BUCKETS", ())) == 8,
              str(getattr(B, "BUCKETS", None)))
        check("RESTATED: the restated member is counted as Restated, and the lines still add up to the total",
              dr.get("ada", {}).get("buckets") == {"scored": 1, "unresolvable": 1, "not_due": 1, "restated": 1}
              and sum(dr["ada"]["buckets"].values()) == dr["ada"]["accepted"], str(dr.get("ada", {}).get("buckets")))
        ada_recs = {r["prediction_id"]: r for r in precs.get("ada", [])}
        check("RESTATED: every record still reaches the drawer; the restated one names its specific member",
              len(ada_recs) == 4 and ada_recs.get(twin["prediction_id"], {}).get("restated_by") == spec_pid
              and "restated_by" not in ada_recs.get(spec_pid, {"restated_by": 1}), str({k: v.get("restated_by") for k, v in ada_recs.items()}))
        # "Also said" carries the date's basis, like the card's Said line: an upload
        # date reads "on or before", never "on".
        check("RESTATED: the drawer lists a restated record once, under its specific member, as 'Also said on or before'",
              "Also said ${esc(x.said.also)}" in hr and "!r.restated_by" in hr and "x.restated_by === r.prediction_id" in hr
              and ada_recs.get(twin["prediction_id"], {}).get("said", {}).get("also") == "on or before 2025-03-01",
              str(ada_recs.get(twin["prediction_id"], {}).get("said")))
        check("RESTATED: the drawer header says how many statements fold under another",
              "restates another prediction and is shown under the prediction it repeats." in hr
              and "restate another prediction and are shown under the prediction they repeat." in hr, "")
        check("RESTATED: the Predictions help explains the Restated line",
              "<b>Restated</b>" in hr and "scored once" in hr, "")
        th_r = re.search(r'<p class="thesis">(.*?)</p>', hr, re.S)
        check("RESTATED: the intro counts a past-due event once, not once per statement",
              bool(th_r) and "8 of 8 past-due predictions" in th_r.group(1), th_r.group(1)[:500] if th_r else "")

        def refuses(label, mutate, needle):
            doc = json.loads(rsc.read_text())
            mutate(doc)
            f = td / f"rs-bad-{abs(hash(label))}.json"
            f.write_text(json.dumps(doc))
            p = run("--scores", str(f), out_name=f"rsb-{abs(hash(label))}.html")
            check(label, p.returncode != 0 and needle in (p.stdout + p.stderr), (p.stdout + p.stderr)[-400:])

        # A cluster's fresh resolution supersedes an older sidecar in another run. The
        # page reads the sidecars to name the models, so it must apply the same
        # supersession the scorer applied, or it refuses one prediction in two runs.
        run2 = td / "run-fresh"
        (run2 / "resolutions" / "ada").mkdir(parents=True)
        (run2 / "resolutions" / "ada" / f"{spec_pid}.json").write_text(json.dumps(
            {"prediction_id": spec_pid, "leader_slug": "ada", "stage": "resolve", "outcome": "occurred",
             "harness": "astra", "telemetry": {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}}))
        sdoc2 = json.loads(rsc.read_text())
        sdoc2["run_dirs"] = [str(run1), str(run2)]
        sdoc2["restatements"]["superseded_resolutions"] = [
            {"cluster_id": "ada/code-by-2030", "run": str(run1), "prediction_id": spec_pid, "outcome": "occurred"}]
        sup_f = td / "rs-sup.json"
        sup_f.write_text(json.dumps(sdoc2))
        psu = run("--scores", str(sup_f), out_name="rs-sup.html")
        check("RESTATED: a superseded resolution in another run is left out, as the scorer left it out",
              psu.returncode == 0, (psu.stdout + psu.stderr)[:600])
        sdoc2["restatements"]["superseded_resolutions"][0]["run"] = str(td / "run-nowhere")
        sup_f.write_text(json.dumps(sdoc2))
        psn = run("--scores", str(sup_f), out_name="rs-sup2.html")
        check("RESTATED: a superseded sidecar the page cannot find refuses the render",
              psn.returncode != 0 and "run-nowhere" in (psn.stdout + psn.stderr), (psn.stdout + psn.stderr)[-400:])

        # ---- 2026-09-28: a statement-date override drops old-date sidecars ----
        # The scorer drops, and names in date_overrides.stale_sidecars_dropped, the
        # prior and resolution a run made under the old statement date. The page
        # reads the sidecars to name the models, so it drops the same ones, or it
        # refuses one prediction with sidecars in two runs.
        run3 = td / "run-redated"
        for sub, stage_doc in (("priors", prior_doc), ("resolutions", {
                "prediction_id": spec_pid, "leader_slug": "ada", "stage": "resolve", "outcome": "occurred",
                "harness": "astra", "telemetry": {"requested_model": "gpt-6-astra", "served_model": "gpt-6-astra"}})):
            (run3 / sub / "ada").mkdir(parents=True)
            (run3 / sub / "ada" / f"{spec_pid}.json").write_text(json.dumps(stage_doc))
        odoc3 = json.loads(rsc.read_text())
        odoc3["run_dirs"] = [str(run1), str(run3)]
        odoc3["date_overrides"] = {"file": "predictions/statement_date_overrides.json", "entries": ["ada/s1"],
                                   "superseded_records": [], "entries_without_records": [],
                                   "stale_sidecars_dropped": [
                                       {"prediction_id": spec_pid, "stage": st, "run": str(run1),
                                        "transcript_id": "ada/s1", "sidecar_statement_date": None}
                                       for st in ("prior", "resolve")]}
        ov_f = td / "ov.json"
        ov_f.write_text(json.dumps(odoc3))
        pov = run("--scores", str(ov_f), out_name="ov.html")
        check("OVERRIDE: old-date sidecars the scorer dropped are left out, so the page renders",
              pov.returncode == 0, (pov.stdout + pov.stderr)[-600:])
        odoc3["date_overrides"]["stale_sidecars_dropped"][0]["run"] = str(td / "run-nowhere")
        ov_f.write_text(json.dumps(odoc3))
        pon = run("--scores", str(ov_f), out_name="ov2.html")
        check("OVERRIDE: a dropped sidecar the page cannot find refuses the render",
              pon.returncode != 0 and "run-nowhere" in (pon.stdout + pon.stderr), (pon.stdout + pon.stderr)[-400:])

        refuses("RESTATED: a cluster only partly on the page refuses the render, naming it",
                lambda d: d["restatements"]["clusters"][0]["members"].append("not-on-this-page"), "ada/code-by-2030")
        refuses("RESTATED: a row restated to a different member than the manifest says refuses the render",
                lambda d: d["predictions"][-1].update(not_scored_because="restated:someone-else"), "someone-else")
        refuses("RESTATED: a restated row with no restatements block refuses the render",
                lambda d: d.pop("restatements"), twin["prediction_id"])

        # The sparkline axis is derived from the records. A hardcoded span silently drops a
        # recording older than the span, which is the whole failure mode here.
        m_years = re.search(r"const YEARS = (\[.*?\]);", html)
        check("SPARK: the page embeds a YEARS axis for the sparkline", m_years is not None)
        years = json.loads(m_years.group(1)) if m_years else []
        ada_row = next(d for d in data if d["slug"] == "ada")
        alan_row = next(d for d in data if d["slug"] == "alan")
        check("SPARK: the year span comes from the records, and dated and undated records are split",
              years == ["2025"] and ada_row["years"] == {"2025": 4} and ada_row["undated"] == 0
              and alan_row["years"] == {} and alan_row["undated"] == 4,
              f"{years} {ada_row['years']}/{ada_row['undated']} {alan_row['years']}/{alan_row['undated']}")
        check("SPARK: every leader's squares sum to their dated accepted predictions",
              all(sum(d["years"].values()) + d["undated"] == d["accepted"] for d in data),
              str([(d["slug"], d["years"], d["undated"], d["accepted"]) for d in data]))

        # Unit check on a wider corpus than the fixture: a gap year is still a square, the span is
        # contiguous from the earliest record to the latest, and an undated record enters no year.
        span_in = {"x": [{"source": {"statement_date": "2011-03-04"}}, {"source": {"statement_date": "2014-07-01"}},
                         {"source": {"statement_date": "2014-12-31"}}, {"source": {"statement_date": None}}],
                   "y": [{"source": {"statement_date": "2012-01-01"}}]}
        per, span = B.statement_years(span_in)
        check("SPARK: the span is contiguous across a gap year and undated records sit outside it",
              span == ["2011", "2012", "2013", "2014"] and per["x"]["years"] == {"2011": 1, "2014": 2}
              and per["x"]["undated"] == 1 and per["y"]["years"] == {"2012": 1}, f"{span} {per}")
        try:
            B.statement_years({"z": [{"source": {"statement_date": "not-a-date"}}]})
            bad = False
        except ValueError:
            bad = True
        check("SPARK: a malformed statement date raises rather than being sliced into a year", bad)

        check("SORT: the drawer cell spans every column",
              # Six columns since Came true arrived on 2026-09-16.
              '<td colspan="6">' in html and ncols == 6, str(ncols))
        check("SORT: with no scores file DATA is emitted alphabetically by name",
              [d["name"] for d in data] == ["Ada L", "Alan T"], str([d["name"] for d in data]))

        ada = pred["ada"]
        first = next(r for r in ada if r["quote"].startswith("by 2030"))
        check("TIMESTAMP: [01:02:03] gives t 3723 and the card links to the video at that second",
              first["timestamp_mark"] == "[01:02:03]" and first["t"] == 3723 and "youtube.com/watch?v=" in html and "&t=${" in html and "}s`" in html)
        check("TIMESTAMP: a record with no video id keeps a plain mark (ytLink returns null)", src["alan/s2"]["video_id"] is None and "ytLink = (vid, t) => vid && t != null" in html)
        # The marker may legitimately appear inside an accepted record's context window (it is
        # transcript text); it must never appear as a quote or a claim under the person's name.
        embedded_claims = json.dumps([[r["quote"], r["claim"]] for rs in pred.values() for r in rs])
        check("REJECTED: the rejected quote is never a quote or claim on the page, and its count is embedded",
              "REJECTED-MARKER-QUOTE" not in embedded_claims and len(ada) == 4
              and next(d for d in data if d["slug"] == "ada")["rejected"] == 1)
        check("TRIM: no telemetry, gates, offsets, harness or accepted flag in the records",
              not re.search(r"secret_telemetry|\"gates\"|quote_char_start|\"harness\"|\"accepted\"", json.dumps(pred)) and "prediction_id" in first)
        check("PROVENANCE: run ids, contract ids and both model names are on the page",
              "run-x" in html and "aaaaaaaaaaaa" in html and "bbbbbbbbbbbb" in html and "Claude Fable 5.1" in html and "OpenAI GPT-6 Astra" in html)
        check("ESCAPE: '</script>' occurs exactly once in the page, and the quote holding it is in its own file",
              html.count("</script>") == 1
              and any("</script>" in r["quote"] for r in pred["ada"]),
              f"{html.count('</script>')} in the page")
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
        p = subprocess.run([PY, str(script), "--data-date", "2026-09-10", "--index", str(td / "bad.json"), "--predictions", str(pr), "--roster", str(roster), "--membership", str(mem(roster)), "--out", str(td / "x.html")],
                           capture_output=True, text=True, cwd=REPO)
        check("STALE: an index count that disagrees with the files fails, naming the person", p.returncode != 0 and "ada" in p.stderr, p.stderr[-300:])

    card_states(L, A, B)

    bs = (REPO / "scripts" / "build_site.py").read_text()
    mast = bs[bs.index('<header class="mast">'):bs.index("</header>")]
    # The link OUT of the index page is off, by one named switch, so that the
    # finished board can be posted publicly without sending a reader to a board
    # whose Score column is still empty for most of the roster. Both halves are
    # pinned: the anchor must not be hard-coded into the masthead any more, and
    # the text that comes back when the switch is flipped must still be a real
    # link, or "turn it back on" would restore an empty string.
    import build_site as BS
    check("XLINK: the masthead carries no hard-coded predictions anchor, only the token",
          "__XLINK__" in mast and "verbatim-predictions.tonygwu.com" not in mast, mast[-200:])
    check("XLINK: the switch is OFF, so a rendered masthead carries no link out",
          BS.SHOW_PREDICTIONS_LINK is False
          and "verbatim-predictions.tonygwu.com" not in mast.replace(
              "__XLINK__", BS.PREDICTIONS_LINK if BS.SHOW_PREDICTIONS_LINK else ""),
          f"SHOW_PREDICTIONS_LINK={BS.SHOW_PREDICTIONS_LINK}")
    check("XLINK: flipping the switch back restores a real anchor, not an empty string",
          'href="https://verbatim-predictions.tonygwu.com"' in BS.PREDICTIONS_LINK,
          BS.PREDICTIONS_LINK)
    # The link back the OTHER way stays. It sends a reader from the unfinished
    # board to the finished one, which is the direction that helps.
    check("XLINK: the predictions page still links back to the index", 'href="https://verbatim-index.tonygwu.com"' in html)
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
    # Origin mode since plan phase P5 (docs/plans/shared-data-push-2026-09-27.md):
    # any push-role clone deploys exactly origin/main, and a deploy never
    # regenerates data (data_sync.py push does). Behaviour is tested end to end
    # in test_deploy_predictions_origin.py; this pins the order in the script.
    check("DEPLOY: origin mode is declared before deploy_source.sh, the origin checks precede npx, "
          "and a deploy regenerates nothing",
          src_sh.index("PUBLICATION_MODE=origin") < src_sh.index(". scripts/deploy_source.sh")
          and src_sh.index("check_origin_before_publish") < src_sh.index("npx wrangler deploy")
          and "$PY scripts/aggregate_predictions.py" not in src_sh and "require_daemon_clone" not in src_sh)
    check("DEPLOY: staleness line and unknown-argument handling are present", "STALE" in src_sh and "cannot be checked" in src_sh and ". scripts/deploy_source.sh" in src_sh and "unknown argument" in (REPO / "scripts/deploy_source.sh").read_text())
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
