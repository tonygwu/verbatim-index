"""A non-YouTube source must not have its date labelled `youtube_upload_date`.

Supplemental sources (earnings calls, testimony, printed interviews) carry a
publication date or a date the page states outright. Before this, the only path
into `statement_date` was `yt_upload_date`, and its basis string was hardcoded.
Writing a web source's date into that field would have produced a record saying
a Palantir earnings call was dated from a YouTube upload.

That is the same defect class as the `or 2024` default this repo already paid
for: a field whose NAME disagrees with its CONTENT, reaching every downstream
reader silently.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import predictions_lib as L  # noqa: E402

CHECKS = 0
FAILED: list[str] = []


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILED.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


def check_raises(label: str, rec: dict, needle: str = "") -> None:
    global CHECKS
    CHECKS += 1
    try:
        L.derive_statement_date(rec)
    except L.PredictionError as exc:
        if needle and needle not in str(exc):
            FAILED.append(f"{label}\n     message {str(exc)!r} lacks {needle!r}")
        return
    FAILED.append(f"{label}\n     did not raise")


# --- the existing YouTube path is untouched ---------------------------------

check("youtube path still works",
      L.derive_statement_date({"yt_upload_date": "20250918", "source_id": "x"}),
      ("2025-09-18", "youtube_upload_date"))
check("absent date is unknown",
      L.derive_statement_date({"source_id": "x"}), (None, "unknown"))
check("empty date is unknown",
      L.derive_statement_date({"yt_upload_date": "", "source_id": "x"}), (None, "unknown"))
check_raises("malformed upload date raises",
             {"yt_upload_date": "2025-09-18", "source_id": "x"}, "not YYYYMMDD")
check_raises("impossible upload date raises",
             {"yt_upload_date": "20250231", "source_id": "x"}, "not a real date")
check_raises("zero upload date raises",
             {"yt_upload_date": "00000000", "source_id": "x"}, "not a real date")

# --- the declared path, for a web source ------------------------------------

check("stated_in_page is honoured",
      L.derive_statement_date({"statement_date": "2026-08-04",
                               "statement_date_basis": "stated_in_page",
                               "source_id": "pltr-q2"}),
      ("2026-08-04", "stated_in_page"))
check("publication_date is honoured",
      L.derive_statement_date({"statement_date": "2026-08-11",
                               "statement_date_basis": "publication_date",
                               "source_id": "pltr-q2"}),
      ("2026-08-11", "publication_date"))

# --- the declared path fails loud -------------------------------------------

check_raises("a basis outside the vocabulary raises",
             {"statement_date": "2026-08-04", "statement_date_basis": "guessed",
              "source_id": "x"}, "must be one of")
check_raises("a missing basis raises, never defaults",
             {"statement_date": "2026-08-04", "source_id": "x"}, "must be one of")
check_raises("youtube_upload_date may not be DECLARED",
             {"statement_date": "2026-08-04",
              "statement_date_basis": "youtube_upload_date", "source_id": "x"},
             "must be one of")
check_raises("YYYYMMDD in the declared field raises",
             {"statement_date": "20260804", "statement_date_basis": "stated_in_page",
              "source_id": "x"}, "not YYYY-MM-DD")
check_raises("a year alone raises",
             {"statement_date": "2026", "statement_date_basis": "stated_in_page",
              "source_id": "x"}, "not YYYY-MM-DD")
check_raises("an impossible declared date raises",
             {"statement_date": "2026-02-31", "statement_date_basis": "stated_in_page",
              "source_id": "x"}, "not a real date")
check_raises("two dates at once raises rather than picking one",
             {"statement_date": "2026-08-04", "statement_date_basis": "stated_in_page",
              "yt_upload_date": "20260811", "source_id": "x"}, "BOTH")

# --- the cutoff reads the declared basis ------------------------------------

cut = L.publication_cutoff({"statement_date": "2026-08-04",
                            "statement_date_basis": "stated_in_page",
                            "source_id": "x"})
check("cutoff uses the declared date", cut["requested_cutoff_utc"], "2026-08-04T00:00:00Z")
check("cutoff precision stays date-level", cut["precision"], "date")

cut_none = L.publication_cutoff({"source_id": "x"})
check("no date means no ex-ante claim", cut_none["basis"], "unknown")
check("no date means no cutoff", cut_none["requested_cutoff_utc"], None)

print(f"test_statement_date_basis: {CHECKS} checks, {len(FAILED)} failed")
for f in FAILED:
    print("  FAIL " + f)
sys.exit(1 if FAILED else 0)
