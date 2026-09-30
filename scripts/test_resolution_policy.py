#!/usr/bin/env python3
"""The resolver policy of 2026-09-29/30, and the release that pins it.

Operator decisions VD-5, VD-6 and the resolver rules of the rescue round-4
design (sections 3.3 and 3.4), with the critiques' fixes applied:
  - THE DEADLINE BOUNDS THE EVENT, NOT THE EVIDENCE: a report published after
    the deadline settles a period that ended before it (the Stripe case,
    a10417f2583c1cee);
  - one "HOW THIS RECORD IS JUDGED" block, generated from the record's own
    triggers (an implied window, approximate numbers, a stated pace, a period's
    figure, a company's fiscal year), sits BYTE-IDENTICAL in the resolver prompt
    and the prior prompt, so the two stages price and judge one question
    (critique 1 point 12). A record with no trigger gets no block, and its prior
    prompt is byte-identical to the one every existing prior was priced with;
  - a minimum research effort that applies to EVERY outcome, recorded in
    `searched` and checked against the harness's own search count, not only to
    refusals (critique 1 point 6, critique 3 C1); and no sentence telling the
    resolver what a refusal does to the speaker's score;
  - no `window_cannot_settle` reason: a resolver may not exclude a record after
    seeing what happened (critique 1 point 5);
  - "already public before the statement" (operator, 2026-09-29): the resolver
    records `already_public` {date, where, what_it_shows} with a source dated on
    or before the statement date; validation refuses a later date. Offline, on
    the recorded shape of the Buddy Media case (2203621a4e46691a);
  - every prompt of the resolve, prior, early and lead-test stages is pinned by a
    release id and a sha256 (critique 3 A2); editing a text without cutting a
    new release is refused before any call, and every sidecar records the release.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402

FAILED = []

PINNED_RELEASE = ("resolution-2026-09-30", "88a0ae81bfbc4e72cfaf8ecb6c3615acdd1dee36561a5ab37aa1dfdb9d4453de")


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid="abc123", *, basis="stated", quote="we will ship the engine next year", claim=None, crit=None,
        cat="technology_product", ctrl="own", said="2019-06-25", tdt="next year", target="2020", implied=None):
    r = {
        "prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/talk-1", "_basis": basis,
        "speaker": {"name": "Ada Lovelace", "role": "CEO", "company": "Analytical", "slug": "ada"},
        "source": {"statement_date": said, "venue": "keynote", "title": "A Talk", "quote": quote,
                   "context_before": "before " * 40, "context_after": "after " * 40},
        "prediction": {"normalized_claim": claim or "The engine ships by 2020-12-31.",
                       "resolution_criteria": crit or "By 2020-12-31, the engine will have shipped.",
                       "target_date": target, "target_date_text": tdt, "category": cat, "subject_control": ctrl},
        "resolution": {"status": "not_started"},
    }
    if implied is not None:
        r["_implied"] = implied
    return r


# The prompt every existing prior was priced with, rebuilt from a FROZEN copy of
# the pre-2026-09-29 block template, so a change to _block itself is caught.
def legacy_prior_prompt(r, deadline, task=None):
    f = R.prompt_facts(r, deadline)
    who = ", ".join(x for x in (f["role"], f["company"]) if x)
    block = f"""PREDICTION {f["prediction_id"]}

Speaker:         {f["speaker"]}{f" ({who})" if who else ""}
Said on:         {f["statement_date"]}
Where:           {f["title"]}{f" [{f['venue']}]" if f["venue"] else ""}
Deadline:        {f["deadline"]}   {f["deadline_note"]}
Category:        {f["category"]}

WHAT WAS SAID, verbatim:
  "{f["quote"]}"

Surrounding words, for context only:
  ...{f["context_before"]}  [[QUOTE]]  {f["context_after"]}...

The claim, as this pipeline recorded it:
  {f["claim"]}

The resolution criterion, as this pipeline recorded it:
  {f["criterion"]}
"""
    return (f"{task or R.PRIOR_TASK}\n{'=' * 70}\n{block}{'=' * 70}\n\n"
            f"Stand on {f['statement_date']}. Answer with the JSON object now.\n")


def judged_section(prompt: str) -> str:
    """The HOW THIS RECORD IS JUDGED section of a prompt, or '' when it has none."""
    head = "HOW THIS RECORD IS JUDGED\n"
    if head not in prompt:
        return ""
    return prompt[prompt.index(head):].split("=" * 70)[0]


def resolution(**over):
    obj = {"prediction_id": "abc123", "outcome": "occurred", "confidence": "high",
           "sources": [{"what_it_shows": "shipped", "where": "https://x/", "date": "2020-03-01"}],
           "searched": ["engine ship date", "Analytical engine release 2020", "Analytical annual report 2020"],
           "already_public": None, "unresolvable_reason": None, "reasoning": "It shipped in March 2020."}
    obj.update(over)
    return obj


def main() -> int:
    d = dt.date(2020, 12, 31)

    print("the resolver's rules")
    t = R.RESOLVER_TASK
    flat = " ".join(t.split())   # phrases wrap across lines in the prompt
    check("RULE 1: the deadline bounds the event, not the evidence",
          "THE DEADLINE BOUNDS THE EVENT, NOT THE EVIDENCE" in t and "published after the deadline settles the claim"
          in flat, t[:900])
    check("RULE 4: no sentence telling the resolver what a refusal costs or saves",
          "costs nothing" not in t and "far" not in t.split("4.")[1].split("5.")[0] and "score" not in t.lower(),
          t)
    check("EFFORT: every outcome needs searches, listed in 'searched'",
          "SEARCH BEFORE YOU ANSWER, WHATEVER THE ANSWER" in t and '"searched"' in t)
    check("ALREADY PUBLIC: the resolver is told to check what was public before the statement",
          "ALREADY PUBLIC BEFORE IT WAS SAID" in t and '"already_public"' in t)
    check("JUDGED: the resolver is told to apply the HOW THIS RECORD IS JUDGED section",
          "HOW THIS RECORD IS JUDGED" in t)
    check("TREND: the trend rule is still rule 7, which the shared deadline note names",
          "\n7. SOME CLAIMS ARE A DIRECTION OVER A WINDOW" in t)
    check("NO EXCLUSION AFTER THE FACT: window_cannot_settle is not a reason, in the list or the prompt",
          "window_cannot_settle" not in R.UNRESOLVABLE_REASONS and "window_cannot_settle" not in t)

    print("one judged block, byte-identical in both prompts")
    info = {"row": "words: soon", "window_words": "1 year", "scale": 1.0, "matched": "soon",
            "matched_in": "quote", "shortest_reading_days": None, "window": [1, "year"]}
    imp = rec(basis="implied: words: soon (quote), 1 year", tdt=None, target=None, quote="it will come soon",
              claim="The engine will ship.", crit="The engine will have shipped.", implied=info)
    rp, pp = R.build_resolver_prompt(imp, d, "2026-09-30"), R.build_prior_prompt(imp, d)
    js = judged_section(rp)
    check("IMPLIED: the block names the implied window in both prompts", "AN IMPLIED WINDOW" in js and "1 year" in js, js)
    check("IMPLIED: the block is byte-identical in the resolver and the prior prompt", js and js == judged_section(pp),
          f"{js!r}\n---\n{judged_section(pp)!r}")
    dl = [l for l in rp.splitlines() if l.startswith("Deadline:")]
    check("IMPLIED: both prompts carry one deadline line, naming the implied window",
          dl and dl == [l for l in pp.splitlines() if l.startswith("Deadline:")] and "implied window" in dl[0], str(dl))
    check("IMPLIED: the deadline note points at the block, never at a rule number the prior does not have",
          "See rule" not in dl[0], dl[0])
    cases = {
        "APPROXIMATE NUMBERS": rec(claim="Revenue will reach about $5 billion by 2020.",
                                   crit="By 2020-12-31, revenue will be about $5 billion."),
        "A STATED PACE OR SCHEDULE": rec(claim="We will publish another ten games each day until all 50 are out.",
                                         crit="By 2017-05-31, all 50 games will be published, ten each day."),
        "A FIGURE FOR A PERIOD": rec(claim="Stripe will be profitable in 2025.", ctrl="own", cat="company_business",
                                    crit="By 2025-12-31, Stripe will report that it was profitable for 2025.",
                                    target="2025", tdt="in 2025"),
        "A COMPANY'S FISCAL YEAR": rec(claim="Revenue will grow 20% this year.", cat="company_business", ctrl="own",
                                       crit="By 2020-12-31, revenue will have grown 20% year over year.",
                                       tdt="this year", target="2020"),
    }
    for head, r in cases.items():
        a, b = judged_section(R.build_resolver_prompt(r, d, "2026-09-30")), judged_section(R.build_prior_prompt(r, d))
        check(f"TRIGGER: {head} reaches both prompts, byte-identical", head in a and a == b, f"{a!r}")
        check(f"TRIGGER: {head} leaks no outcome vocabulary into the prior",
              R.prior_prompt_leaks(R.build_prior_prompt(r, d), R.prompt_facts(r, d)) == [],
              str(R.prior_prompt_leaks(R.build_prior_prompt(r, d), R.prompt_facts(r, d))))
    tol = judged_section(R.build_prior_prompt(cases["APPROXIMATE NUMBERS"], d))
    check("TOLERANCE: 'about' within 10%, 'nearly' 90% to 100%, 'a couple' is two",
          "within 10%" in tol and "90%" in tol and "two" in tol, tol)
    check("TRIGGER: the imp prompt leaks nothing", R.prior_prompt_leaks(pp, R.prompt_facts(imp, d)) == [],
          str(R.prior_prompt_leaks(pp, R.prompt_facts(imp, d))))
    plain = rec(quote="we will ship the engine", claim="The engine ships.", crit="The engine will have shipped by then.")
    check("NO TRIGGER: no block at all", judged_section(R.build_prior_prompt(plain, d)) == "")
    check("NO TRIGGER: the prior prompt is byte-identical to the one existing priors were priced with",
          R.build_prior_prompt(plain, d) == legacy_prior_prompt(plain, d))
    tr = rec(basis="trend: trend over 5.6y since the statement", quote="margins will go up",
             claim="Margins will go up.", crit="Margins will be higher.")
    check("TREND: a trend prior prompt is byte-identical to the legacy one too",
          R.build_prior_prompt(tr, d) == legacy_prior_prompt(tr, d, R.PRIOR_TASK + R.PRIOR_TREND_RULE))

    print("what a resolution must carry")
    ok = resolution()
    check("SCHEMA: a well-formed resolution passes", L.check_schema(ok, R.RESOLUTION_SCHEMA) == []
          and R.validate_resolution(ok, "abc123", "2019-06-25") == [],
          str(L.check_schema(ok, R.RESOLUTION_SCHEMA)) + str(R.validate_resolution(ok, "abc123", "2019-06-25")))
    for outcome, extra in (("occurred", {}), ("not_occurred", {}),
                           ("unresolvable", {"unresolvable_reason": "no_public_evidence", "sources": []})):
        thin = resolution(outcome=outcome, searched=["one query", "one query ", "two"], **extra)
        errs = R.validate_resolution(thin, "abc123", "2019-06-25")
        check(f"EFFORT: {outcome} with two distinct searches is refused, whatever the outcome",
              any("searched" in e for e in errs), str(errs))
    check("SCHEMA: searched and already_public are required keys",
          {"searched", "already_public"} <= set(R.RESOLUTION_SCHEMA["required"]))
    tel_ok = {"tool_use_counts": {"web_search": 3}}
    check("EFFORT: the harness's own count of three searches passes", R.validate_effort(ok, tel_ok) == [])
    check("EFFORT: fewer than three searches in the telemetry is refused, for an 'occurred' too",
          R.validate_effort(ok, {"tool_use_counts": {"web_search": 2}}) != [])
    check("EFFORT: telemetry with no search count is refused, never assumed",
          R.validate_effort(ok, {"tool_use_counts": {}}) != [] and R.validate_effort(ok, {}) != [])
    check("EFFORT: listing more searches than the harness ran is refused",
          R.validate_effort(resolution(searched=["a", "b", "c", "d", "e"]), tel_ok) != [])

    print("already public before the statement (Buddy Media, 2203621a4e46691a)")
    buddy = resolution(prediction_id="2203621a4e46691a", outcome="occurred",
                       sources=[{"what_it_shows": "Salesforce signs a definitive agreement to acquire Buddy Media",
                                 "where": "https://www.salesforce.com/news/press-releases/2012/06/04/salesforce-com-signs-definitive-agreement-to-acquire-buddy-media/",
                                 "date": "2012-06-04"}],
                       searched=["Salesforce Buddy Media acquisition", "Buddy Media deal May 2012",
                                 "AllThingsD Salesforce Buddy Media"],
                       already_public={"date": "2012-05-29",
                                       "where": "https://allthingsd.com/20120529/salesforce-set-to-snap-up-facebook-friend-buddy-media-for-more-than-800-million/",
                                       "what_it_shows": "Salesforce is close to a deal to acquire Buddy Media; the two "
                                                        "companies have agreed to terms"})
    check("ALREADY PUBLIC: the recorded Buddy Media answer passes the schema and validation (said 2012-05-30)",
          L.check_schema(buddy, R.RESOLUTION_SCHEMA) == [] and R.validate_resolution(buddy, "2203621a4e46691a", "2012-05-30") == [],
          str(L.check_schema(buddy, R.RESOLUTION_SCHEMA)) + str(R.validate_resolution(buddy, "2203621a4e46691a", "2012-05-30")))
    late = R.validate_resolution(buddy, "2203621a4e46691a", "2012-05-28")
    check("ALREADY PUBLIC: a date after the statement date is refused", any("already_public" in e for e in late), str(late))
    check("ALREADY PUBLIC: an undated record cannot carry it",
          any("already_public" in e for e in R.validate_resolution(buddy, "2203621a4e46691a", None)))
    bad = dict(buddy, already_public=dict(buddy["already_public"], date="May 29, 2012"))
    check("ALREADY PUBLIC: a date that is not YYYY-MM-DD is refused",
          any("already_public" in e for e in R.validate_resolution(bad, "2203621a4e46691a", "2012-05-30")))
    check("ALREADY PUBLIC: the schema pins exactly date, where and what_it_shows",
          L.check_schema(dict(buddy, already_public=dict(buddy["already_public"], note="x")), R.RESOLUTION_SCHEMA) != [])

    print("the Stripe case: a report after the deadline settles a period that ended before it")
    stripe = resolution(prediction_id="a10417f2583c1cee",
                        sources=[{"what_it_shows": "Stripe's 2025 annual letter: profitable in 2025",
                                  "where": "https://stripe.com/annual-updates/2025", "date": "2026-02-24"}])
    check("DEADLINE: an 'occurred' whose only source postdates the 2025-12-31 deadline is not refused",
          R.validate_resolution(stripe, "a10417f2583c1cee", "2025-04-01") == [])

    print("the release")
    rid, sha = R.policy_release()
    check("RELEASE: the resolution policy is pinned by id and sha256", (rid, sha) == PINNED_RELEASE, f"{rid} {sha}")
    check("RELEASE: the pinned release matches the texts in this checkout", R.check_policy_release() == rid)
    saved = R.RESOLVER_TASK
    try:
        R.RESOLVER_TASK = saved.replace("at least three", "at least two")
        try:
            R.check_policy_release()
            check("RELEASE: editing a prompt without cutting a release is refused before any call", False)
        except ValueError as e:
            check("RELEASE: editing a prompt without cutting a release is refused before any call",
                  "resolution_release_mismatch" in str(e), str(e))
    finally:
        R.RESOLVER_TASK = saved
    out = R.resolution_record(rec(), d, ok, run_id="r", harness="astra", account="a", telemetry=tel_ok,
                              resolved_at="2026-09-30T00:00:00Z", as_of="2026-09-30", prompt_sha="beef",
                              release=rid, code_revision="c0ffee")
    check("RECORD: a resolution sidecar records its release, prompt hash, code revision, searches and "
          "already_public", out.get("policy_release") == rid and out.get("prompt_sha256") == "beef"
          and out.get("code_revision") == "c0ffee" and out.get("searched") == ok["searched"]
          and "already_public" in out, json.dumps({k: out.get(k) for k in ("policy_release", "prompt_sha256")}))
    pri = R.prior_record(rec(), d, {"prediction_id": "abc123", "p": 0.3, "reference_class": "rc", "reasoning": "r"},
                         run_id="r", harness="fable", account="a", telemetry={}, assessed_at="2026-09-30T00:00:00Z",
                         prompt_sha="beef", leaks=[], release=rid, code_revision="c0ffee")
    check("RECORD: a prior sidecar records its release", pri.get("policy_release") == rid)

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
