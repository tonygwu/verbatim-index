#!/usr/bin/env python3
"""Eval for the wrong-person detector in identity_audit.py.

The fixture is not invented. It is the twelve transcripts that were filed under
C.C. Wei on 2026-09-10, with the judges' verbatim `identity_guess` text frozen
as it was written. Ten are ten different people whose names contain "Wei". Two
are really him. The detector has to separate them with no false positive on
either real appearance, because a false positive here withdraws a leader's
genuine evidence.

Pure checks. No quota, no network, no data directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identity_audit import audit, judge_verdict, norm  # noqa: E402

WEI = {"slug": "cc-wei", "name": "C.C. Wei", "company": "TSMC"}

# source_id -> (is_really_the_leader, {judge: identity_guess})
FIXTURE: dict[str, tuple[bool, dict[str, str]]] = {
    "adobe-creative-cloud-1l--yn": (False, {
        "gemini": "Jean Wei",
        "fable": "Jing Wei, Brooklyn-based illustrator and in-house illustrator at Etsy, circa 2017",
        "astra": "Possibly Jing Wei"}),
    "bankless-tik8am": (False, {
        "gemini": "Eugene Wei",
        "fable": "Eugene Wei, former product leader (Amazon, Hulu, Flipboard, Oculus) and author "
                 "of the essay 'Status as a Service'.",
        "astra": "Eugene Wei"}),
    "danny-haiphong-k-c3ae": (False, {
        "gemini": "Zhang Weiwei (Professor of International Relations at Fudan University)",
        "fable": "Zhang Weiwei, professor of international relations and director of the China "
                 "Institute at Fudan University; the host addressed as 'Danny' is presumably "
                 "Danny Haiphong.",
        "astra": "Zhang Weiwei"}),
    # The hard one. Two judges name the leader ONLY to rule them out.
    "george-daniel-swpx7b": (False, {
        "gemini": "Wei (DJ wavy / Wei-Shawn), a San Francisco Bay Area electronic music DJ, event "
                  "organizer (Way Creative), and tech industry project manager; distinctly "
                  "unrelated to C.C. Wei of TSMC despite the transcript ID label.",
        "fable": "A San Francisco Bay Area DJ and small-event promoter performing as 'Wavy' (Wei "
                 "Shawn), a US Air Force veteran with a project-management day job, co-founding "
                 "Immersive Rhythm Records with Sandra Maine and Vic. This is not a technology "
                 "business leader.",
        "astra": "Weivy Wei, the DJ guest who introduces himself as Wei Sean; identification as "
                 "C.C. Wei is unsupported."}),
    "han-wei-shen-ughuv0": (False, {
        "gemini": "Han-Wei Shen",
        "fable": "Han-Wei Shen, a scientific-visualization professor (Ohio State University); in "
                 "any case an academic lecturer in scientific visualization rather than a "
                 "business executive.",
        "astra": "unknown"}),
    "mit-civil-and-environmen-rwmwc3": (False, {
        "gemini": "Dr. Wei Chen (Wilson-Cook Professor in Engineering Design and Chair of "
                  "Mechanical Engineering at Northwestern University)",
        "fable": "Wei Chen, Wilson Cook Professor of Engineering Design and Chair of Mechanical "
                 "Engineering at Northwestern University.",
        "astra": "Wei Chen"}),
    # The other hard one: one judge negates the name, the others abstain.
    "newton-free-library-9aab7z": (False, {
        "gemini": "William Wu (or William Wei), an academic administrator and former MIT postdoc "
                  "and Harvard social science data center manager living in Newton, "
                  "Massachusetts. This is not C.C. Wei of TSMC despite the transcript ID prefix.",
        "fable": "Not a technology business leader. A Chinese-born (Fujian) retired academic "
                 "administrator who came to the US in 1987 at 30, took a PhD in Delaware, did an "
                 "MIT postdoc, and became director of a social-science data center at Harvard. I "
                 "cannot identify the specific individual.",
        "astra": "unknown"}),
    "six-five-media-rmprp4": (False, {
        "gemini": "Wei Li (VP and GM of AI Software / Machine Learning Performance at Intel)",
        "fable": "Wei Li, Vice President of Machine Learning Performance (AI software) at Intel.",
        "astra": "Wei Li of Intel"}),
    "ted-hahs-iyee3v": (False, {
        "gemini": "Lord Nat Wei (Nathaniel Wei, Baron Wei)",
        "fable": "Nat Wei, Lord Wei of Shoreditch: UK life peer, former McKinsey consultant, "
                 "co-founder of Teach First, founder of the Shaftesbury Partnership.",
        "astra": "Lord Nat Wei"}),
    "usacm-juvcrj": (False, {
        "gemini": "Professor Wei Chen (Wilson-Cook Professor in Engineering Design and Chair of "
                  "Mechanical Engineering at Northwestern University)",
        "fable": "Wei Chen, Wilson Cook Professor and chair of mechanical engineering at "
                 "Northwestern University",
        "astra": "Wei Chen, the Northwestern University engineering-design professor identified "
                 "in the introduction"}),
    # The two that really are him.
    "the-wellth-channel-opxr-s": (True, {
        "gemini": "C.C. Wei (Wei Zhejia), CEO of TSMC",
        "fable": "C.C. Wei, CEO of TSMC",
        "astra": "C.C. Wei"}),
    "yale-university-q1b-fn": (True, {
        "gemini": "C.C. Wei (CEO / Chairman of TSMC)",
        "fable": "C.C. Wei, CEO of TSMC (Taiwan Semiconductor Manufacturing Company)",
        "astra": "C. C. Wei"}),
}

passed = failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def as_grades() -> list[dict]:
    out = []
    for sid, (_, guesses) in FIXTURE.items():
        for judge, g in guesses.items():
            out.append({"leader_slug": "cc-wei", "source_id": sid, "judge": judge,
                        "mode": "blinded", "grade": {"identity_guess": g}})
    return out


def naive_verdict(guess: str, full: str) -> str:
    """The detector as it would be WITHOUT negation handling. Kept so the eval
    shows what the negation rule actually buys, rather than asserting it."""
    g = norm(guess)
    if not g or "unknown" in g:
        return "abstain"
    return "match" if full in g else "mismatch"


def main() -> int:
    print("wrong-person detector eval (fixture: the C.C. Wei corpus of 2026-09-10)\n")
    report = audit(as_grades(), {"cc-wei": WEI})
    flagged = {r["source_id"] for r in report["confirmed"]} | {r["source_id"] for r in report["suspect"]}
    truly_wrong = {s for s, (ok, _) in FIXTURE.items() if not ok}
    truly_right = {s for s, (ok, _) in FIXTURE.items() if ok}

    print("[1] every wrong-person transcript is flagged")
    missed = sorted(truly_wrong - flagged)
    check(f"all {len(truly_wrong)} wrong-person transcripts flagged", not missed,
          f"missed: {missed}")

    print("\n[2] neither real appearance is flagged")
    wrongly = sorted(truly_right & flagged)
    check("no false positive on a genuine transcript", not wrongly, f"flagged: {wrongly}")
    check("both real appearances counted as consistent with the roster",
          report["verdicts"]["consistent_with_roster"] == len(truly_right),
          f"consistent_with_roster={report['verdicts']['consistent_with_roster']}")

    print("\n[3] a judge that names the leader only to DENY it is a mismatch")
    full = norm(WEI["name"])
    denials = [
        "distinctly unrelated to C.C. Wei of TSMC despite the transcript ID label.",
        "identification as C.C. Wei is unsupported.",
        "This is not C.C. Wei of TSMC despite the transcript ID prefix.",
    ]
    for d in denials:
        check(f"mismatch: {d[:52]}...",
              judge_verdict(d, full, norm(WEI["company"])) == "mismatch",
              f"got {judge_verdict(d, full, norm(WEI['company']))}")

    print("\n[4] a plain affirmative identification still matches")
    for g in ("C.C. Wei, CEO of TSMC", "C. C. Wei", "C.C. Wei (Wei Zhejia), CEO of TSMC"):
        check(f"match: {g}", judge_verdict(g, full, norm(WEI["company"])) == "match")

    print("\n[5] 'unknown' abstains rather than voting either way")
    for g in ("unknown", "Unknown", "unknown."):
        check(f"abstain: {g!r}", judge_verdict(g, full, norm(WEI["company"])) == "abstain")

    print("\n[6] the negation rule is load-bearing, not decoration")
    naive_flagged = set()
    for sid, (_, guesses) in FIXTURE.items():
        vs = [naive_verdict(g, full) for g in guesses.values()]
        op = [v for v in vs if v != "abstain"]
        if op and all(v == "mismatch" for v in op):
            naive_flagged.add(sid)
    naive_missed = truly_wrong - naive_flagged
    check("substring matching alone MISSES wrong-person transcripts",
          len(naive_missed) > 0,
          "the naive matcher caught everything, so this eval no longer discriminates")
    print(f"        negation-aware: {len(truly_wrong & flagged)}/{len(truly_wrong)} caught."
          f"  substring-only: {len(truly_wrong & naive_flagged)}/{len(truly_wrong)}"
          f"  (misses {sorted(naive_missed)})")

    print("\n[7] the report states its own thresholds")
    m = report["method"]
    check("negation cues are reported", bool(m.get("negation_cues")))
    check("both window sizes are reported",
          isinstance(m.get("window_before_chars"), int) and isinstance(m.get("window_after_chars"), int))
    check("the confirmed threshold is reported", m.get("confirmed_requires_n_judges") == 2)

    print("\n[8] counts add up, so nothing is dropped silently")
    v = report["verdicts"]
    total = (v["confirmed_wrong_person"] + v["suspect_single_judge"]
             + v["consistent_with_roster"] + v["no_judge_expressed_an_opinion"])
    check("every transcript lands in exactly one bucket",
          total == report["transcripts_examined"],
          f"{total} != {report['transcripts_examined']}")

    print(f"\n{passed}/{passed + failed} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
