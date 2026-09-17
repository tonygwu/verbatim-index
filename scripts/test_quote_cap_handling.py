#!/usr/bin/env python3
"""An over-long evidence quote is RECORDED, not a reason to destroy the grade.

DECIDED by the operator 2026-09-16, during the P9 top-up run, after the pattern
below turned up live.

The rubric asks every evidence quote to be 25 words or fewer. That is a cap on
CITATION LENGTH: the judge reads the whole transcript, and the cap only limits
how much of it may be pasted back as evidence. Until now a single over-long
quote appended a validation error, which made the whole record invalid, which
threw away the score, the reasoning and both other dimensions, and spent another
judge call to get the same answer one word shorter.

MEASURED across eight P8a2 rounds and the first 69 calls of the P9 top-up:

    P8a2   24 rejections   gemini 19 (19.0%)  fable 5 (5.0%)   ratio 3.8x
    P9     4 rejections    ALL FOUR on d3_good_faith, both judges, two people

The dimension concentration is the part that matters. D3 asks whether a person
applies one standard, answers the question asked, and concedes when warranted.
None of that can be shown in one sentence, because it takes a back-and-forth to
demonstrate that somebody shifted position. D1 and D2 are showable in a single
claim. So the penalty lands on one dimension, and that dimension carries 0.30 of
the overall score. Re-rolling until the judge writes a short D3 quote selects
D3 grades for quote brevity. The audit put that selection at +1.07 points
(se 0.77, n=24), too small to call at that size and pointing the wrong way to
ignore.

The cap NUMBER stays 25 and stays in the contract. Only the CONSEQUENCE moves,
and the consequence lives in code that no hash covers, so `contract_id` does not
change and the 267 grades already collected stay poolable.

  KEEP       an over-long quote no longer appends a validation error
  RECORD     it comes back from quote_overruns naming dimension, words and cap
  CLEAN      a grade inside the cap reports no overruns
  MULTI      several overruns are each reported, across dimensions
  STRICT     every other validation rule still rejects
  FROZEN     contract_id is unchanged, so no re-grade is triggered
  REPORT     aggregate counts overruns by judge and by dimension

  .venv/bin/python scripts/test_quote_cap_handling.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []

# The contract in force for every pundits grade collected so far. If relaxing
# the PENALTY moved this, the change would have silently invalidated the corpus.
CONTRACT_BEFORE = "3844dd2693acd471"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load_aggregate():
    spec = importlib.util.spec_from_file_location("agg_qc", REPO / "scripts" / "aggregate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def canned(prof: dict, tid: str) -> dict:
    """A well-formed v2 grade. Same shape as test_pundit_skill.canned."""
    dims, subs = {}, []
    for d in prof["scoring"]["dimensions"]:
        dims[d["key"]] = {
            "dimension_status": "supported", "score": 62,
            "reasoning": "The subject restated the opposing case in its own terms before answering it, "
                         "and conceded one factual point when pressed by the host.",
            "evidence": [{"quote": "the strongest version of their argument is this", "timestamp": "[00:12:04]",
                          "speaker": "subject", "why_it_matters": "states the other side first"},
                         {"quote": "fair point, I had that wrong", "timestamp": "[00:31:40]",
                          "speaker": "subject", "why_it_matters": "concedes when warranted"}],
            "counterevidence": "Later the subject called a critic's motives cynical without citing anything."}
        subs += [{"code": c, "score": 3, "justification": "observed once"} for c in d["subcriteria"]]
    weights = {d["key"]: d["weight"] for d in prof["scoring"]["dimensions"]}
    return {"schema_version": "pundits-1.0", "transcript_id": tid, "venue_type": "conversation",
            "venue_challenge": 3, "venue_challenge_reason": "The host pressed twice on specifics.",
            "subject_speech_share_pct": 55, "attribution_confidence": "medium",
            "attribution_notes": "Turns separated by question marks and names.",
            "identity_guess": "unknown", "identity_confident": False, "identity_basis": "No names survive.",
            "asr_quality": "minor_corruption", "asr_notes": "none",
            "subcriteria": subs, "dimensions": dims,
            "overall": round(sum(weights[k] * 62 for k in weights), 2), "coverage": 1.0,
            "confidence": "medium", "confidence_reason": "One long recording.",
            "salient_claims": ["The subject argued a policy's costs outweigh its benefits."], "red_flags": []}


def long_quote(n: int) -> str:
    """A quote of exactly n words, so the word count in a message is checkable."""
    return " ".join(f"w{i}" for i in range(n))


def main() -> int:
    print("quote cap handling")
    import grading_contract as GC
    prof = json.loads((REPO / "profiles" / "pundits.json").read_text())
    scoring = prof["scoring"]
    cap = scoring["max_quote_words"]
    d3 = scoring["dimensions"][-1]["key"]
    d1 = scoring["dimensions"][0]["key"]
    tid = "pundit-p/s1"

    if not hasattr(GC, "quote_overruns"):
        check("grading_contract exposes quote_overruns", False,
              "the recording channel does not exist, so an overrun can only be an error")
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    print("\n[KEEP]")
    g = canned(prof, tid)
    g["dimensions"][d3]["evidence"][0]["quote"] = long_quote(cap + 5)
    errs = GC.validate_v2(g, tid, scoring)
    check("an over-long quote appends no validation error", errs == [], str(errs))
    check("so the grade is still usable", not errs)

    print("\n[RECORD]")
    over = GC.quote_overruns(g, scoring)
    check("the overrun is reported, exactly once", len(over) == 1, str(over))
    if over:
        o = over[0]
        check("it names the dimension", o.get("dimension") == d3, str(o))
        check("it names the word count", o.get("words") == cap + 5, str(o))
        check("it names the cap it passed", o.get("cap") == cap, str(o))
        check("it names the speaker, so a cut can be attributed", o.get("speaker") == "subject", str(o))

    print("\n[CLEAN]")
    clean = canned(prof, tid)
    check("a grade inside the cap reports no overruns", GC.quote_overruns(clean, scoring) == [],
          str(GC.quote_overruns(clean, scoring)))
    check("and still validates", GC.validate_v2(clean, tid, scoring) == [])

    print("\n[MULTI]")
    m = canned(prof, tid)
    m["dimensions"][d1]["evidence"][0]["quote"] = long_quote(cap + 1)
    m["dimensions"][d3]["evidence"][0]["quote"] = long_quote(cap + 40)
    m["dimensions"][d3]["evidence"][1]["quote"] = long_quote(cap + 2)
    over = GC.quote_overruns(m, scoring)
    check("every overrun is reported, not just the first", len(over) == 3, str(over))
    check("and they carry their own dimensions",
          sorted(o["dimension"] for o in over) == sorted([d1, d3, d3]), str(over))
    check("a quote one word over the cap counts", any(o["words"] == cap + 1 for o in over), str(over))
    check("the relaxed penalty still does not reject", GC.validate_v2(m, tid, scoring) == [])

    print("\n[STRICT]")
    bad_speaker = canned(prof, tid)
    bad_speaker["dimensions"][d1]["evidence"][0]["speaker"] = "narrator"
    check("an evidence speaker outside the enum is still a validation error",
          bool(GC.validate_v2(bad_speaker, tid, scoring)))
    bad_tid = canned(prof, tid)
    check("a wrong transcript_id is still a validation error",
          bool(GC.validate_v2(bad_tid, "pundit-p/other", scoring)))
    bad_score = canned(prof, tid)
    bad_score["dimensions"][d1]["score"] = 250
    check("an out-of-range dimension score is still a validation error",
          bool(GC.validate_v2(bad_score, tid, scoring)))
    thin = canned(prof, tid)
    thin["dimensions"][d1]["evidence"] = [thin["dimensions"][d1]["evidence"][0]]
    check("too few subject quotes is still a validation error",
          bool(GC.validate_v2(thin, tid, scoring)))

    print("\n[FROZEN]")
    contract = GC.contract_v2(prof)
    check(f"contract_id is still {CONTRACT_BEFORE}, so no grade already collected is invalidated",
          contract["contract_id"] == CONTRACT_BEFORE, contract["contract_id"])
    check("and the cap number itself is untouched at 25", cap == 25, str(cap))

    print("\n[REPORT]")
    A = load_aggregate()
    if not hasattr(A, "quote_cap_report"):
        check("aggregate.py exposes quote_cap_report", False,
              "a cap that cuts must report what it cut and for which group")
    else:
        rows = [
            {"judge": "gemini", "mode": "blinded", "leader_slug": "p0",
             "quote_cap_overruns": [{"dimension": d3, "words": 28, "cap": 25, "speaker": "subject"}]},
            {"judge": "gemini", "mode": "open", "leader_slug": "p1",
             "quote_cap_overruns": [{"dimension": d3, "words": 26, "cap": 25, "speaker": "subject"},
                                    {"dimension": d1, "words": 30, "cap": 25, "speaker": "subject"}]},
            {"judge": "fable", "mode": "blinded", "leader_slug": "p0", "quote_cap_overruns": []},
            {"judge": "fable", "mode": "blinded", "leader_slug": "p2"},
        ]
        rep = A.quote_cap_report(rows)
        check("overruns are counted by judge", rep["by_judge"] == {"gemini": 3}, str(rep))
        check("and by dimension, which is where the skew was found",
              rep["by_dimension"] == {d3: 2, d1: 1}, str(rep))
        check("grades carrying at least one overrun are counted",
              rep["grades_with_overrun"] == 2, str(rep))
        check("the share is reported against the grades read, not guessed",
              rep["grades_read"] == 4, str(rep))
        check("a corpus with no overrun reports zero rather than nothing",
              A.quote_cap_report([{"judge": "fable"}])["by_judge"] == {}, str(A.quote_cap_report([{"judge": "fable"}])))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
