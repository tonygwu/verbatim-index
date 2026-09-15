#!/usr/bin/env python3
"""The two Phase 2 stages, and the wall between them.

What this pins, each of which would quietly change what a published score means:
  - the prior prompt cannot see an outcome, PROVEN by attaching one and asserting
    the prompt does not move;
  - a resolution that cites nothing is rejected, so no outcome enters on recall;
  - "unresolvable" is a real answer and must carry a reason from a fixed list;
  - both stages read the SAME deadline, and it is the funnel's expanded one;
  - a p outside [0.01, 0.99] is clamped and the record says it was.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import resolution_lib as R  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(**over):
    r = {
        "prediction_id": "abc123",
        "leader_slug": "ada",
        "transcript_id": "ada/talk-1",
        "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical", "slug": "ada"},
        "source": {"statement_date": "2019-06-25", "venue": "keynote", "title": "A Talk",
                   "quote": "we will ship the engine next year",
                   "context_before": "before " * 400, "context_after": "after " * 400},
        "prediction": {"normalized_claim": "The engine ships by 2020-12-31.",
                       "resolution_criteria": "By 2020-12-31, the engine will have shipped.",
                       "target_date": "2020", "target_date_text": "next year",
                       "category": "technology_product"},
        "resolution": {"status": "not_started"},
    }
    r.update(over)
    return r


def main() -> int:
    d = dt.date(2020, 12, 31)

    # ---- the wall -------------------------------------------------------
    clean = R.build_prior_prompt(rec(), d)
    loud = rec()
    loud["resolution"] = {"status": "resolved", "outcome": "not_occurred",
                          "reasoning": "the engine slipped to 2023 and was cancelled",
                          "sources": [{"where": "https://example.com", "what_it_shows": "cancelled"}]}
    loud["_resolution"] = loud["resolution"]
    loud["outcome"] = "not_occurred"
    check("WALL: attaching a resolution to the record does not change the prior prompt by one byte",
          R.build_prior_prompt(loud, d) == clean,
          "the prior stage can reach a field it must not see")
    check("WALL: the prior prompt carries no outcome vocabulary",
          R.prior_prompt_leaks(clean) == [], str(R.prior_prompt_leaks(clean)))
    check("WALL: the leak screen actually fires, so an empty list means something",
          R.prior_prompt_leaks("the claim turned out to be false") == ["turned out"],
          str(R.prior_prompt_leaks("the claim turned out to be false")))
    # The screen reads only what THIS repo authors. A speaker who says "the outcome"
    # in 2014 is not telling the assessor how their own prediction ended, and seven
    # real records in the corpus trip an unmasked screen exactly that way.
    noisy = rec()
    noisy["source"] = dict(noisy["source"],
                          quote="the outcome here actually happened faster than people expected",
                          context_before="in hindsight it turned out that way ")
    np_ = R.build_prior_prompt(noisy, d)
    check("WALL: outcome words inside the SPEAKER'S OWN WORDS do not trip the screen",
          R.prior_prompt_leaks(np_, R.prompt_facts(noisy, d)) == [],
          str(R.prior_prompt_leaks(np_, R.prompt_facts(noisy, d))))
    check("WALL: the same words trip it when they are UNMASKED, so the mask is doing the work",
          R.prior_prompt_leaks(np_) != [])
    check("WALL: an authored disclosure still trips the masked screen",
          R.prior_prompt_leaks(np_ + "\nWHAT ACTUALLY HAPPENED: it did not happen.\n",
                               R.prompt_facts(noisy, d)) != [],
          "a real leak must survive the mask")

    check("WALL: the prior prompt is not given today's date",
          "2026" not in clean, [l for l in clean.splitlines() if "2026" in l])
    check("WALL: prompt_facts reads no resolution field",
          "resolution" not in set(R.prompt_facts(loud, d)) and
          all("not_occurred" not in str(v) for v in R.prompt_facts(loud, d).values()))

    # ---- both stages read the same claim --------------------------------
    res = R.build_resolver_prompt(rec(), d, "2026-09-15")
    for needle in ("we will ship the engine next year", "By 2020-12-31, the engine will have shipped.",
                   "2020-12-31", "Ada Lovelace"):
        check(f"SHARED: both prompts carry {needle[:38]!r}", needle in res and needle in clean)
    check("DEADLINE: the prompt states the EXPANDED deadline, never the bare target_date",
          "Deadline:        2020-12-31" in res and "Deadline:        2020\n" not in res,
          [l for l in res.splitlines() if "Deadline" in l])
    check("RESOLVER: today is stated to the resolver, which needs it and the prior does not",
          "Today is 2026-09-15" in res)

    # ---- resolution validation ------------------------------------------
    ok = {"prediction_id": "abc123", "outcome": "occurred", "confidence": "high",
          "sources": [{"what_it_shows": "shipped", "where": "https://x/", "date": "2020-03-01"}],
          "unresolvable_reason": None, "reasoning": "It shipped in March 2020."}
    check("SCHEMA: a well-formed resolution passes both the schema and the extra rules",
          R.validate_resolution(ok, "abc123") == [] and
          __import__("predictions_lib").check_schema(ok, R.RESOLUTION_SCHEMA) == [],
          str(R.validate_resolution(ok, "abc123")))

    nosrc = dict(ok, sources=[])
    check("EVIDENCE: an outcome that cites nothing is REJECTED, so recall cannot enter as fact",
          any("cites no source" in e for e in R.validate_resolution(nosrc, "abc123")),
          str(R.validate_resolution(nosrc, "abc123")))
    unres = dict(ok, outcome="unresolvable", sources=[], unresolvable_reason="no_public_evidence")
    check("DECLINE: unresolvable with a reason and no source is ACCEPTED, because declining is an answer",
          R.validate_resolution(unres, "abc123") == [], str(R.validate_resolution(unres, "abc123")))
    check("DECLINE: unresolvable without a reason is rejected",
          any("no unresolvable_reason" in e for e in
              R.validate_resolution(dict(unres, unresolvable_reason=None), "abc123")))
    check("DECLINE: a decided outcome may not also carry an unresolvable reason",
          any("carries unresolvable_reason" in e for e in
              R.validate_resolution(dict(ok, unresolvable_reason="no_public_evidence"), "abc123")))
    check("SCHEMA: an invented reason is refused by the enum rather than stored",
          __import__("predictions_lib").check_schema(
              dict(unres, unresolvable_reason="i_did_not_look"), R.RESOLUTION_SCHEMA) != [])
    check("ID: a resolution answering about another prediction is refused",
          any("prediction_id" in e for e in R.validate_resolution(ok, "zzz")))

    # ---- prior validation and clamping ----------------------------------
    pok = {"prediction_id": "abc123", "p": 0.3, "reference_class": "roadmap items", "reasoning": "why"}
    check("PRIOR: a well-formed prior passes", R.validate_prior(pok, "abc123") == []
          and __import__("predictions_lib").check_schema(pok, R.PRIOR_SCHEMA) == [])
    check("PRIOR: p outside [0,1] is refused", R.validate_prior(dict(pok, p=1.4), "abc123") != [])
    check("PRIOR: a boolean is not a probability", R.validate_prior(dict(pok, p=True), "abc123") != [])

    mk = lambda p: R.prior_record(rec(), d, dict(pok, p=p), run_id="r", harness="fable", account="a",
                                  telemetry={}, assessed_at="2026-09-15T00:00:00Z",
                                  prompt_sha="deadbeef", leaks=[])
    check("CLAMP: a certainty is clamped to 0.99 and the record SAYS it was clamped",
          mk(1.0)["p"] == 0.99 and mk(1.0)["p_raw"] == 1.0 and mk(1.0)["clamped"] is True,
          str({k: mk(1.0)[k] for k in ("p", "p_raw", "clamped")}))
    check("CLAMP: an ordinary p is untouched and not marked clamped",
          mk(0.3)["p"] == 0.3 and mk(0.3)["clamped"] is False)
    check("PROOF: the prior record pins the prompt it was shown",
          mk(0.3)["prompt_sha256"] == "deadbeef" and mk(0.3)["prompt_leak_words"] == [])

    # ---- sidecars --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        p1 = R.sidecar_path(root, "resolve", "ada", "abc123")
        p2 = R.sidecar_path(root, "prior", "ada", "abc123")
        check("PATH: the two stages write to separate trees, so neither can read the other by glob",
              p1.parent != p2.parent and "resolutions" in str(p1) and "priors" in str(p2))
        p1.parent.mkdir(parents=True)
        p1.write_text(json.dumps(R.resolution_record(
            rec(), d, ok, run_id="r", harness="astra", account="codex_b", telemetry={},
            resolved_at="2026-09-15T00:00:00Z", as_of="2026-09-15")))
        loaded = R.load_sidecars(root, "resolve")
        check("LOAD: a written sidecar reads back under its prediction_id",
              list(loaded) == ["abc123"] and loaded["abc123"]["outcome"] == "occurred")
        check("LOAD: a missing tree is empty rather than an error",
              R.load_sidecars(root, "prior") == {})
        dup = R.sidecar_path(root, "resolve", "bob", "abc123")
        dup.parent.mkdir(parents=True)
        dup.write_text(p1.read_text())
        try:
            R.load_sidecars(root, "resolve")
            check("LOAD: two sidecars for one prediction fail LOUDLY rather than one silently winning", False)
        except ValueError as e:
            check("LOAD: two sidecars for one prediction fail LOUDLY rather than one silently winning",
                  "duplicate" in str(e))

    # ---- the repair stage --------------------------------------------------
    rok = {"prediction_id": "abc123", "verdict": "repaired",
           "criterion": "By 2020-12-31, the engine will have shipped.", "reasoning": "why"}
    check("REPAIR: a well-formed repair passes",
          R.validate_repair(rok, "abc123") == []
          and __import__("predictions_lib").check_schema(rok, R.REPAIR_SCHEMA) == [])
    und = "By 2020-12-31, the engine will / will not have shipped."
    check("REPAIR: a 'repaired' criterion that is STILL undirected is refused",
          any("undirected" in e for e in R.validate_repair(dict(rok, criterion=und), "abc123")),
          str(R.validate_repair(dict(rok, criterion=und), "abc123")))
    check("REPAIR: waving an undirected criterion through as 'already_correct' is ALSO refused",
          any("undirected" in e for e in
              R.validate_repair({"prediction_id": "abc123", "verdict": "already_correct",
                                 "criterion": und, "reasoning": "w"}, "abc123")),
          "a rubber stamp on the defect the stage exists to remove would pass silently")
    check("REPAIR: the undirected pattern uses \\s+, so it survives a line wrap",
          R.UNDIRECTED_RE.search("the engine will /\n  will not ship") is not None)
    check("REPAIR: cannot_repair must carry a null criterion",
          R.validate_repair({"prediction_id": "abc123", "verdict": "cannot_repair",
                             "criterion": None, "reasoning": "w"}, "abc123") == []
          and R.validate_repair({"prediction_id": "abc123", "verdict": "cannot_repair",
                                 "criterion": "x", "reasoning": "w"}, "abc123") != [])

    # ---- the overlay -------------------------------------------------------
    rows = [rec(), rec(prediction_id="other")]
    rows[1]["prediction"] = dict(rows[1]["prediction"])
    applied, unrep = R.apply_repairs(rows, {
        "abc123": {"prediction_id": "abc123", "verdict": "repaired", "criterion": "NEW TEXT"},
        "other": {"prediction_id": "other", "verdict": "cannot_repair", "criterion": None}})
    check("OVERLAY: a repaired criterion replaces the original and KEEPS it alongside",
          applied == 1 and rows[0]["prediction"]["resolution_criteria"] == "NEW TEXT"
          and rows[0]["prediction"]["resolution_criteria_original"].startswith("By 2020-12-31"),
          str(rows[0]["prediction"]))
    check("OVERLAY: an unrepairable record is MARKED, not silently left with broken text",
          unrep == 1 and rows[1].get("_unrepairable") is True)
    untouched = rec()
    R.apply_repairs([untouched], {})
    check("OVERLAY: a record with no repair is not touched at all",
          "resolution_criteria_original" not in untouched["prediction"])

    check("STAGE: an unknown stage name raises rather than writing somewhere unexpected",
          _raises(lambda: R.sidecar_path(pathlib.Path("/tmp"), "grade", "ada", "x")))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
