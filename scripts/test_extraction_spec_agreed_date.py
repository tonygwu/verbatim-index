#!/usr/bin/env python3
"""EXTRACTION.md tells the extractor how to read every kind of statement-date line the header can print.

FOUND 2026-10-01 at the merge of the two-dater dating stage: the header gained lines
saying "two dating agents named this day; no source confirms it", and section 1a of
the extraction spec, which tells the extractor how to read each kind of date line,
had no bullet for them. An extractor reading an agreed date like a sourced one is
mostly right (the pilot's agreements were 4 of 4 right), but it must also know the
date is an estimate it may contradict.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import predictions_lib as L  # noqa: E402

failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"))
    failed += 0 if ok else 1


spec = L.read_spec(L.SKILL / L.EXTRACTION_SPEC)
sec = spec[spec.index("## 1a."):]
sec = sec[:sec.index("\n## ", 5)] if "\n## " in sec[5:] else sec
header = json.loads((L.SKILL / L.HEADER_TEMPLATE_FILE).read_text())
agreed = [v for v in header["date_lines"].values() if isinstance(v, str) and "two dating agents named this day" in v]
check("the header template has agreed-date lines", len(agreed) >= 2, str(list(header)))
check("section 1a names the agreed-date line in the header's own words",
      "two dating agents named this day" in sec, sec[:300])
check("section 1a says an agreed date is an estimate the transcript may contradict",
      bool(re.search(r"two dating agents named this day.{0,600}statement_date_doubt", sec, re.S)), sec[:300])
L.load_policy_release()  # raises if the spec changed without a new pin
print("all passed" if not failed else f"{failed} failed")
sys.exit(1 if failed else 0)
