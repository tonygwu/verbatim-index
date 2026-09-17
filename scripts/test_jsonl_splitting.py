#!/usr/bin/env python3
"""A JSONL record is one NEWLINE-delimited line, not one str.splitlines() line.

`str.splitlines()` also breaks on NEL, U+2028, U+2029, VT, FF and the four
information separators. `json.loads` accepts every one of those RAW inside a
string, so a record carrying one is cut in half and BOTH halves then fail to
parse: the record is not merely dropped, it takes the whole file down.

FOUND by repo-1 on 2026-09-14, in a Stripe PDF caption carrying U+2028. It is
invisible on the YouTube corpus, which contains none of these characters, and it
fires the moment a web-sourced record lands. VERIFIED against repo-1's
supplemental run: exactly one of its 72 record files splits into two pieces under
splitlines(), and both pieces fail to parse.

This test is written against the real character rather than a synthetic one, so
it keeps failing if someone reintroduces splitlines() anywhere in the read path.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import criteria_agreement as C  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import predictions_lib as L  # noqa: E402

FAILED = []

# Every character str.splitlines() treats as a break. Only three of them can
# actually reach a file through this repo's writer: json.dumps escapes the C0
# controls (VT, FF, and the information separators) even with ensure_ascii=False,
# because JSON requires it, while NEL, U+2028 and U+2029 are written raw. VERIFIED
# by running this test against the pre-fix code: 6 checks fail, and the C0 cases
# pass. The C0 characters stay in the list anyway, because a file written by
# anything other than serialise_line could still carry them.
SPLITLINES_ONLY = ["", " ", " ", "\v", "\f", "", "", ""]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def attempt(label, fn, want):
    """Run fn and compare, treating a RAISE as a failure rather than a crash.

    Against the pre-fix code every one of these raises, because splitlines cuts a
    record in half and both halves fail to parse. An uncaught exception ends the
    run at the first case and reports nothing, which is how a test can look like
    it passes against the defect it exists to catch. This repo has paid for that
    twice already."""
    try:
        got = fn()
    except Exception as exc:  # noqa: BLE001
        check(label, False, f"raised {type(exc).__name__}: {str(exc)[:160]}")
        return
    check(label, got == want, f"got {got!r}, want {want!r}")


def record(slug: str, quote: str) -> dict:
    return {
        "accepted": True, "leader_slug": slug,
        "prediction_id": f"{abs(hash(quote)) % 10**16:016x}",
        "transcript_id": f"{slug}/web-1", "schema_version": 1, "status": "pending",
        # quote_char_start is what serialise_lines sorts on, so the fixture has to
        # carry it: the test writes through the REAL writer, not a stand-in.
        "source": {"quote": quote, "statement_date": "2019-01-01",
                   "quote_char_start": 0, "quote_char_end": len(quote)},
        "prediction": {"target_date": "2020", "specificity": "high",
                       "resolution_criteria": "By 2020-12-31, it will have happened.",
                       "subject_control": "own", "category": "company_business",
                       "horizon": "explicit", "target_date_text": "in 2020",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": "It happens."},
        "verification": {"verifier_resolution_criteria": "By 2020-12-31, it will have happened."},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def main() -> int:
    # Serialise through the repo's OWN writer. It uses ensure_ascii=False, which is
    # why a raw U+2028 reaches the file at all; a plain json.dumps escapes it to
    # \\u2028 and the bug cannot reproduce. The first version of this test made
    # exactly that mistake and PASSED against the defect it was written to catch.
    check("FIXTURE: the repo's serialiser writes these characters RAW, which is the premise",
          "\u2028" in L.serialise_line(record("ada", "a\u2028b")),
          "if the writer escaped them there would be no bug to fix")
    for ch in SPLITLINES_ONLY:
        line = L.serialise_line(record("ada", f"we will ship it{ch}next year"))
        attempt(f"PARSE: a record carrying U+{ord(ch):04X} inside a string is ONE record",
                lambda ln=line: len(L.parse_lines(ln + "\n", "t")), 1)

    # And the loaders that read the corpus off disk.
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "ada").mkdir()
        recs = [record("ada", "plain quote one"),
                record("ada", "a quote with a line separator in it"),
                record("ada", "plain quote three")]
        (d / "ada" / "web.jsonl").write_text(L.serialise_lines(recs))

        attempt("FUNNEL: the funnel loader reads all 3 records, not 4 pieces",
                lambda: len(P2.load(d)), 3)
        attempt("FUNNEL: the separator survives INSIDE the quote it belongs to",
                lambda: any(" " in (r["source"]["quote"] or "") for r in P2.load(d)), True)
        attempt("CRITERIA: the criteria screen reads all 3 records",
                lambda: len(C.load(d)), 3)

    # The corpus as it stands, so this test says something about the live data too.
    #
    # RE-SCOPED 2026-09-16. This used to assert that NO file in the corpus splits
    # differently under the two readings. That assertion was wrong in kind, and it
    # went red the moment the supplemental web records were placed in production:
    # patrick-collison/web-assets-ctfassets-net-cbb20aaa.jsonl carries one U+2028
    # inside a quoted string, from a Stripe letter that really contains it.
    #
    # JSON permits that character raw inside a string, so such a record is VALID
    # and the corpus is entitled to hold it. Asserting its absence asserts that
    # legitimate data must not exist, and it fails precisely when the codebase
    # meets the data this whole test was written to survive. The two ways to make
    # that green were to sanitise the record, which destroys real source text and
    # re-stales the production index for no correctness gain, or to delete the
    # check. Neither is right.
    #
    # What matters is not whether such a file EXISTS but whether the production
    # loaders READ it. So the check now finds every differing file and proves the
    # real readers handle each one. That is strictly stronger than the old
    # assertion: it still goes red if anybody reintroduces splitlines() in the
    # read path, and it turns this record from a liability into a real-world
    # fixture that a synthetic one cannot replace.
    live = ROOT / "data" / "predictions"
    if live.exists():
        affected = []
        for f in sorted(live.glob("*/*.jsonl")):
            t = f.read_text()
            if len([l for l in t.splitlines() if l.strip()]) != len([l for l in t.split("\n") if l.strip()]):
                affected.append(f)

        bad_count, bad_parse = [], []
        for f in affected:
            t = f.read_text()
            want = len([l for l in t.split("\n") if l.strip()])
            got = L.parse_lines(t, str(f))
            if len(got) != want:
                bad_count.append(f"{f.name}: reader returned {len(got)}, byte-split has {want}")
            for line in L.jsonl_lines(t):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except Exception as exc:  # noqa: BLE001
                    bad_parse.append(f"{f.name}: {type(exc).__name__} {str(exc)[:60]}")
                    break

        check("LIVE: every corpus file carrying a splitlines-only separator is read "
              "correctly by the production loader",
              not bad_count and not bad_parse,
              f"count mismatches {bad_count}; parse failures {bad_parse}")
        # Reported, not asserted. An experiment clone legitimately has 0 affected
        # files while production has 1, so a non-vacuity assertion would be red in
        # one clone and green in the other for no defect. The count is printed so a
        # reader can see whether the check had anything to bite on.
        print(f"       ({len(affected)} of {len(list(live.glob('*/*.jsonl')))} corpus files carry "
              f"such a separator: {', '.join(f.name for f in affected) if affected else 'none'})")

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
