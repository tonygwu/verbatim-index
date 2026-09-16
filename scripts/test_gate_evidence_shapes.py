#!/usr/bin/env python3
"""Two defects in fetch_web_sources that round 2 of the supplemental sweep hit.

Both are provenance or integrity defects, not cosmetics, and both were found by
running the round-1 fetcher against a round-2 findings file.

1. `gate_evidence` was only ever a list of STRINGS. Round 2 asks each discovery
   agent for the DEADLINE and the RESOLUTION ROUTE beside every quote, because a
   quote that passes the five gates is still worthless to the board if its
   deadline has not passed. That makes each entry an object. The old
   `ground_evidence` passed the object straight to `locate_quote`, which raised
   `TypeError: expected string or bytes-like object, got 'dict'`.

   The fix accepts both shapes and REFUSES anything else by name. It does not
   skip an entry it cannot read. A silently skipped quote lowers the grounding
   rate, and the grounding rate is the integrity check on the discovery pass, so
   a silent skip would read as "the agent paraphrased" when the truth is "the
   fetcher could not parse it". That is the accept-and-guess this repo forbids.

2. `record_for` hardcoded `discovery.run` to the literal string
   "supplemental-sources-2026-09-14". Every record fetched by any later run
   would claim to have come from the September 14 sweep. The run directory is
   already on the command line; the record now reads it from there.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_web_sources as F  # noqa: E402

TEXT = ("Speaking in May 2016, he said: we expect Azure revenue to exceed twenty "
        "billion dollars by the end of fiscal 2018, and we will ship the new "
        "runtime in the first half of next year.")

QUOTE_A = "we expect Azure revenue to exceed twenty billion dollars"
QUOTE_B = "we will ship the new runtime in the first half of next year"
ABSENT = "we will land a person on Mars before the end of the decade"

checks = 0
failures: list[str] = []


def check(label: str, got, want) -> None:
    global checks
    checks += 1
    if got != want:
        failures.append(f"{label}\n     got  {got!r}\n     want {want!r}")


def raises(label: str, fn, exc_type, needle: str) -> None:
    global checks
    checks += 1
    try:
        fn()
    except exc_type as exc:
        if needle not in str(exc):
            failures.append(f"{label}: message {str(exc)!r} does not mention {needle!r}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{label}: raised {type(exc).__name__}, wanted {exc_type.__name__}")
    else:
        failures.append(f"{label}: did not raise {exc_type.__name__}")


# --- 1. the string shape still works, unchanged --------------------------------
check("strings: both grounded",
      F.ground_evidence(TEXT, [QUOTE_A, QUOTE_B]),
      {"claimed": 2, "grounded": 2, "missing": []})

check("strings: one missing is reported",
      F.ground_evidence(TEXT, [QUOTE_A, ABSENT]),
      {"claimed": 2, "grounded": 1, "missing": [ABSENT[:90]]})

check("strings: empty list", F.ground_evidence(TEXT, []),
      {"claimed": 0, "grounded": 0, "missing": []})

check("strings: None", F.ground_evidence(TEXT, None),
      {"claimed": 0, "grounded": 0, "missing": []})

# --- 2. the round-2 object shape grounds on its `quote` field -------------------
OBJ_A = {"quote": QUOTE_A, "deadline": "2018-06-30", "lead_days": 780,
         "past_due": True, "resolvable_how": "Microsoft FY2018 Q4 earnings release"}
OBJ_B = {"quote": QUOTE_B, "deadline": "2017-06-30", "past_due": True}
OBJ_ABSENT = {"quote": ABSENT, "deadline": "2029-12-31", "past_due": False}

check("objects: both grounded",
      F.ground_evidence(TEXT, [OBJ_A, OBJ_B]),
      {"claimed": 2, "grounded": 2, "missing": []})

check("objects: one missing is reported by its quote text",
      F.ground_evidence(TEXT, [OBJ_A, OBJ_ABSENT]),
      {"claimed": 2, "grounded": 1, "missing": [ABSENT[:90]]})

check("mixed shapes in one list",
      F.ground_evidence(TEXT, [QUOTE_A, OBJ_B]),
      {"claimed": 2, "grounded": 2, "missing": []})

# --- 3. anything else is REFUSED by name, never skipped ------------------------
raises("object with no quote key refuses",
       lambda: F.ground_evidence(TEXT, [{"deadline": "2018-06-30"}]),
       F.EvidenceShapeError, "quote")

raises("object with an empty quote refuses",
       lambda: F.ground_evidence(TEXT, [{"quote": "   "}]),
       F.EvidenceShapeError, "quote")

raises("a number refuses",
       lambda: F.ground_evidence(TEXT, [42]),
       F.EvidenceShapeError, "int")

raises("a nested list refuses",
       lambda: F.ground_evidence(TEXT, [[QUOTE_A]]),
       F.EvidenceShapeError, "list")

# the refusal names the offending entry, so the operator can find it in the file
raises("the refusal names the offending entry",
       lambda: F.ground_evidence(TEXT, [QUOTE_A, {"deadline": "2018-06-30"}]),
       F.EvidenceShapeError, "deadline")


# --- 4. discovery.run comes from the run directory, never a literal -------------
class FakeResponse:
    status_code = 200
    headers = {"content-type": "text/html"}
    content = b"<html>body</html>"


def record(run_name: str, evidence) -> dict:
    src = {"url": "https://example.com/a", "title": "T", "publisher": "P",
           "kind": "letter", "speech_date": "2016-05-01",
           "speech_date_basis": "stated_in_page", "density": "high",
           "identity_note": "byline", "gate_evidence": evidence, "notes": ""}
    return F.record_for(src, "satya-nadella", TEXT, "requests", FakeResponse(),
                        run=run_name)


check("discovery.run is the run passed in",
      record("supplemental-round2-2026-09-16", [OBJ_A])["discovery"]["run"],
      "supplemental-round2-2026-09-16")

check("a different run name is carried through",
      record("some-later-run-2027-01-01", [QUOTE_A])["discovery"]["run"],
      "some-later-run-2027-01-01")

check("the round-1 literal is no longer hardcoded",
      record("supplemental-round2-2026-09-16", [])["discovery"]["run"]
      != "supplemental-sources-2026-09-14", True)

check("grounding still rides along in the record",
      record("r", [OBJ_A, OBJ_ABSENT])["discovery"]["evidence_grounding"],
      {"claimed": 2, "grounded": 1, "missing": [ABSENT[:90]]})

check("the object evidence is stored verbatim for a later reader",
      record("r", [OBJ_A])["discovery"]["gate_evidence"], [OBJ_A])

# --- 5. the helper is usable on its own, because the summariser needs it --------
check("evidence_quotes on strings", F.evidence_quotes([QUOTE_A]), [QUOTE_A])
check("evidence_quotes on objects", F.evidence_quotes([OBJ_A]), [QUOTE_A])
check("evidence_quotes on None", F.evidence_quotes(None), [])

print(f"{checks - len(failures)}/{checks} checks passed")
for f in failures:
    print(f"  FAIL {f}")
sys.exit(1 if failures else 0)
