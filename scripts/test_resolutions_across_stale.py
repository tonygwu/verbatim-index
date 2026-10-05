#!/usr/bin/env python3
"""The resolver freezes trend windows only from resolutions the scorer still reads.

FOUND 2026-10-05: three records were scored on the live board as trend records, their
windows frozen at their first resolutions (2026-09-14 and 2026-09-16). Their transcripts
were then re-dated (an override moved the statement date) and re-extracted with the same
ids. The scorer drops a sidecar made under a date an override replaced
(score_predictions.drop_stale_sidecars), so it saw them unresolved, gave them implied
windows, and listed them as needing a lead test. The resolver's resolutions_across read the
same stale sidecars, froze the old trend windows, and the lead-test stage refused the ids as
"no accepted record past due". The two halves of the pipeline disagreed about one record.

resolutions_across now takes the override file and skips a stale sidecar the same way.
Pure: sidecars on disk in a temporary directory, no quota.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R  # noqa: E402
import resolve_predictions as RP  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


def put(run: Path, pid: str, tid: str, date: str, deadline: str) -> None:
    p = R.sidecar_path(run, "resolve", tid.split("/")[0], pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"prediction_id": pid, "transcript_id": tid, "statement_date": date,
                             "deadline": deadline, "outcome": "occurred"}))


with tempfile.TemporaryDirectory() as td:
    old, new = Path(td) / "old-run", Path(td) / "new-run"
    put(old, "stale1", "ada/talk", "2022-10-20", "2026-09-14")   # made before ada/talk was re-dated
    put(old, "fresh1", "ada/other", "2021-01-01", "2021-12-31")  # its transcript has no override
    put(new, "redone", "ada/talk", "2022-09-06", "2023-09-06")   # made under the override's date
    put(old, "redone", "ada/talk", "2022-10-20", "2026-09-14")   # the same prediction, before the re-date
    overrides = {"ada/talk": {"statement_date": "2022-09-06"}}

    got, clash = RP.resolutions_across([old, new], overrides)
    check("a sidecar made under a date an override replaced is not read", "stale1" not in got, str(sorted(got)))
    check("a sidecar of a transcript with no override is read", "fresh1" in got, str(sorted(got)))
    check("the sidecar made under the override's date is the one read",
          got.get("redone", {}).get("deadline") == "2023-09-06", str(got.get("redone")))
    check("a stale sidecar is not a window conflict", "redone" not in clash, str(clash))

    got0, clash0 = RP.resolutions_across([old, new], {})
    check("without overrides every sidecar is read, as before", "stale1" in got0 and "redone" in clash0,
          f"{sorted(got0)} {clash0}")

# The lead-test labels the stages read obey the same rule (score_predictions loads lead tests
# through drop_stale_sidecars too). A label made under the replaced date would make the
# resolver treat a record as labelled that the scorer reports unlabelled, and the lead-test
# stage would then refuse to label it again.
with tempfile.TemporaryDirectory() as td:
    old, new = Path(td) / "old-run", Path(td) / "new-run"

    def lead(run, pid, tid, date, label):
        p = R.sidecar_path(run, "lead_test", tid.split("/")[0], pid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"prediction_id": pid, "transcript_id": tid, "statement_date": date, "label": label}))
    lead(old, "stale1", "ada/talk", "2022-10-20", "world_forecast")
    lead(old, "fresh1", "ada/other", "2021-01-01", "own_plan_announcement")
    lead(old, "relabel", "ada/talk", "2022-10-20", "world_forecast")
    lead(new, "relabel", "ada/talk", "2022-09-06", "own_results_forecast")
    overrides = {"ada/talk": {"statement_date": "2022-09-06"}}
    try:
        got = RP.lead_labels_across([old, new], overrides)
        check("a lead-test label made under a replaced date is not read", "stale1" not in got, str(got))
        check("a label of a transcript with no override is read", got.get("fresh1") == "own_plan_announcement", str(got))
        check("the label made under the override's date wins, with no conflict refusal",
              got.get("relabel") == "own_results_forecast", str(got))
    except (TypeError, SystemExit) as exc:
        check("lead_labels_across reads labels under the override's date", False, f"{type(exc).__name__}: {exc}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
