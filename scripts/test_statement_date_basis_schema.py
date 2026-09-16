#!/usr/bin/env python3
"""The record schema must admit every basis `derive_statement_date` accepts.

Round 1 taught `derive_statement_date` two date bases for sources that are not
YouTube recordings, `stated_in_page` and `publication_date`, and did NOT teach
them to `prediction_record.schema.json`. The code and the contract disagreed
from that moment, and nothing caught it, because the supplemental records lived
in an experiment directory that `validate_predictions.py` never walked.

It surfaced the moment repo-0 placed those records in the production corpus:

    $.source.statement_date_basis: 'stated_in_page'
        not in enum ['youtube_upload_date', 'unknown']

206 schema failures, one per accepted web record, blocking the integration of
every supplemental prediction.

This test pins the two together so they cannot drift again. It asserts the
relationship, not a list: a third basis added to `DECLARED_DATE_BASES` fails
here until the schema learns it too.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import predictions_lib as L  # noqa: E402

SCHEMA = ROOT / ".claude/skills/prediction-extractor/prediction_record.schema.json"

checks = 0
failures: list[str] = []


def check(label: str, got, want) -> None:
    global checks
    checks += 1
    if got != want:
        failures.append(f"{label}\n     got  {got!r}\n     want {want!r}")


schema = json.loads(SCHEMA.read_text())
enum = schema["properties"]["source"]["properties"]["statement_date_basis"]["enum"]

# --- 1. the relationship, asserted rather than a typed list ---------------------
missing = sorted(b for b in L.DECLARED_DATE_BASES if b not in enum)
check("every DECLARED_DATE_BASES value is in the schema enum", missing, [])

# The two bases that predate the web sources must survive. `youtube_upload_date`
# is what the whole existing corpus carries and `unknown` is what a dateless
# source gets, so dropping either silently invalidates records already on disk.
check("youtube_upload_date still permitted", "youtube_upload_date" in enum, True)
check("unknown still permitted", "unknown" in enum, True)

check("stated_in_page permitted", "stated_in_page" in enum, True)
check("publication_date permitted", "publication_date" in enum, True)
check("no duplicate entries", len(enum), len(set(enum)))

# --- 2. the enum admits nothing the code would refuse --------------------------
# The schema must not be LOOSER than the code either. A basis the schema allows
# but derive_statement_date rejects would pass validation and then raise at read
# time, which is worse than failing at the gate.
allowed_by_code = set(L.DECLARED_DATE_BASES) | {"youtube_upload_date", "unknown"}
extra = sorted(b for b in enum if b not in allowed_by_code)
check("schema admits nothing the code refuses", extra, [])

# --- 3. the accepting path still works, end to end -----------------------------
for basis in sorted(L.DECLARED_DATE_BASES):
    rec = {"source_id": "web-x", "statement_date": "2016-05-01",
           "statement_date_basis": basis}
    check(f"derive_statement_date accepts {basis}",
          L.derive_statement_date(rec), ("2016-05-01", basis))

# a YouTube record is untouched
check("yt_upload_date path unchanged",
      L.derive_statement_date({"source_id": "yt-x", "yt_upload_date": "20190718"}),
      ("2019-07-18", "youtube_upload_date"))

# a dateless record is unknown, not an error
check("dateless record is unknown",
      L.derive_statement_date({"source_id": "web-y"}), (None, "unknown"))

# --- 4. an unknown basis is still REFUSED, loudly ------------------------------
checks += 1
try:
    L.derive_statement_date({"source_id": "web-z", "statement_date": "2016-05-01",
                             "statement_date_basis": "vibes"})
except L.PredictionError as exc:
    if "vibes" not in str(exc):
        failures.append(f"refusal does not name the offending basis: {exc}")
else:
    failures.append("a bogus statement_date_basis was accepted")

print(f"{checks - len(failures)}/{checks} checks passed")
for f in failures:
    print(f"  FAIL {f}")
sys.exit(1 if failures else 0)
