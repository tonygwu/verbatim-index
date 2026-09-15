#!/usr/bin/env python3
"""Do the extractor and the verifier agree on what would settle each prediction?

Read-only over data/predictions. Spends no model calls and writes nothing.

Every accepted record carries TWO resolution criteria, written independently:
`prediction.resolution_criteria` by the extractor, and
`verification.verifier_resolution_criteria` by the verifier, which never saw the
extractor's reasoning. docs/PREDICTIONS-PHASE2-SCOPE.md says a record whose two
criteria disagree needs a human rather than a tiebreak model, and that the rate
should be measured before a resolution pass is designed. This measures it.

WHAT THIS IS NOT. It is a MECHANICAL screen, not a semantic judgement. It compares
the parts of a criterion a machine can read exactly: the deadline, the numeric
thresholds and the polarity. It cannot tell whether two differently worded
observations mean the same thing. So the flagged count is a LOWER bound on the
records needing a human, and it carries false positives that a reader must
discard. Both directions are reported, never one.

  .venv/bin/python scripts/criteria_agreement.py
  .venv/bin/python scripts/criteria_agreement.py --flag deadline_year --sample 5
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys
import textwrap

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
MON = "|".join(MONTHS)
ISO = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
NAMED = re.compile(rf"\b({MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
MONTH_YEAR = re.compile(rf"\b({MON})\s+(\d{{4}})\b", re.I)
YEAR = re.compile(r"(?<![\d-])(19\d{2}|20\d{2})(?![\d-])")
# "By <date>" is the deadline; any other date in the sentence is a comparison point.
BY = re.compile(r"\bby\s+(?:the\s+end\s+of\s+)?", re.I)

# Magnitudes, so "2 billion" and "2,000,000,000" are the same threshold.
SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12,
         "k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9}
NUM = re.compile(r"(\d[\d,]*\.?\d*)\s*(%|percent|thousand|million|billion|trillion|k|m|b|bn)?\b", re.I)
# "X will / will not happen" states no direction, so it cannot be resolved either way.
# The verifier writes this, and it is a defect in the criterion rather than a disagreement
# about the claim. Mechanically exact, so this flag carries no false positives.
UNDIRECTED = re.compile(r"\bwill\s*/\s*will not\b|\bwill not\s*/\s*will\b|\bwill\s+or\s+will not\b", re.I)
NEGATION = re.compile(r"\b(will not|won't|not exceed|no more than|fewer than|less than|below|"
                      r"fail(?:s|ed)? to|never|shall not|does not|do not)\b", re.I)


def dates_in(text: str):
    """Every date the text names, coarsest grain preserved: (start, end, year, month, day)."""
    out = []
    for m in ISO.finditer(text):
        out.append((m.start(), m.end(), int(m.group(1)), int(m.group(2)),
                    int(m.group(3)) if m.group(3) else None))
    for m in NAMED.finditer(text):
        out.append((m.start(), m.end(), int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))))
    for m in MONTH_YEAR.finditer(text):
        if not any(d[0] <= m.start() < d[1] for d in out):        # already caught with a day
            out.append((m.start(), m.end(), int(m.group(2)), MONTHS[m.group(1).lower()], None))
    for m in YEAR.finditer(text):
        if not any(d[0] <= m.start() < d[1] for d in out):        # already inside a fuller date
            out.append((m.start(), m.end(), int(m.group(1)), None, None))
    return sorted(out)


def mask_dates(text: str) -> str:
    """Blank every date span. A date's month and day are NOT thresholds, and leaving them
    in was this screen's largest false positive: "2013-12-31" against "December 31, 2013"
    read as the extractor testing a threshold of 12 that the verifier dropped."""
    out = list(text)
    for a, b, *_ in dates_in(text):
        out[a:b] = " " * (b - a)
    return "".join(out)


def main_clause(text: str) -> str:
    """The criterion's own test, without the verifier's falsification rider.

    The verifier habitually appends "; a figure short of that would falsify", which
    negates by design. Comparing polarity across that rider made 41 records look like
    disagreements when both were saying the same thing in two house styles.
    """
    cut = len(text)
    for m in re.finditer(r";|\bif\b|\bwould (?:falsify|be falsified)\b|\bwould falsif", text, re.I):
        cut = min(cut, m.start())
    return text[:cut]


def deadline(text: str):
    """(year, month, day) the criterion closes on, or None.

    A criterion is written "By <date>, <observable>", so the date introduced by "by"
    is the deadline and any later date is a comparison point. When no "by" is present
    the LATEST date is taken, because a deadline is the far end of what is mentioned.
    """
    found = dates_in(text)
    if not found:
        return None
    for m in BY.finditer(text):
        after = [d for d in found if 0 <= d[0] - m.end() <= 3]
        if after:
            return after[0][2:]
    return max(found, key=lambda d: (d[2], d[3] or 0, d[4] or 0))[2:]


def thresholds(text: str):
    """The scaled numbers a criterion tests against. Dates are masked out first."""
    out = set()
    for m in NUM.finditer(mask_dates(text)):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        if unit in ("%", "percent"):
            out.add(("pct", round(v, 3)))
            continue
        if unit in SCALE:
            out.add(("n", round(v * SCALE[unit], 3)))
            continue
        if 1900 <= v <= 2100 and v == int(v) and "-" not in raw:
            continue                                   # a bare year is a date, not a threshold
        out.add(("n", round(v, 3)))
    return out


def compare(e: str, v: str):
    """Every mechanical disagreement between two criteria, as a list of flag names."""
    flags = []
    de, dv = deadline(e), deadline(v)
    if de is None and dv is None:
        pass          # neither names a date: open-ended, and they AGREE about that. Not a flag,
                      # but the criteria are still checked below: an undirected or inverted
                      # criterion is a defect whether or not the prediction carries a deadline.
                      # Returning early here hid 4 of the 18 undirected criteria.
    elif de is None or dv is None:
        flags.append("deadline_missing_in_one")
    elif de is not None and dv is not None and de[0] != dv[0]:
        flags.append("deadline_year")
    elif de[1] is not None and dv[1] is not None and de[1] != dv[1]:
        flags.append("deadline_month")
    elif (de[1] is not None and dv[1] is not None and de[2] is not None
          and dv[2] is not None and de[2] != dv[2]):
        flags.append("deadline_day")
    te, tv = thresholds(e), thresholds(v)
    if te - tv:
        flags.append("threshold_dropped")          # the extractor tests a number the verifier does not
    if UNDIRECTED.search(e) or UNDIRECTED.search(v):
        flags.append("undirected_criterion")       # not resolvable either way; must be rewritten
    elif bool(NEGATION.search(main_clause(e))) != bool(NEGATION.search(main_clause(v))):
        flags.append("polarity")
    return flags


def load(pred_dir: pathlib.Path):
    rows = []
    for f in sorted(pred_dir.glob("*/*.jsonl")):
        # split on the newline byte only; see predictions_lib.parse_lines
        for line in f.read_text().split("\n"):
            if line.strip():
                r = json.loads(line)
                if r.get("accepted"):
                    rows.append(r)
    if not rows:
        raise SystemExit(f"no accepted predictions under {pred_dir}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", type=pathlib.Path, default=ROOT / "data" / "predictions")
    ap.add_argument("--flag", help="print the records carrying this flag")
    ap.add_argument("--sample", type=int, default=0, help="how many flagged pairs to print in full")
    args = ap.parse_args()

    rows = load(args.predictions)
    counts = collections.Counter()
    flagged = []
    for r in rows:
        e = (r["prediction"].get("resolution_criteria") or "").strip()
        v = (r["verification"].get("verifier_resolution_criteria") or "").strip()
        if not e or not v:
            counts["criterion_absent"] += 1
            flagged.append((r, ["criterion_absent"]))
            continue
        if deadline(e) is None and deadline(v) is None:
            counts["both call it open-ended (not a disagreement)"] += 1
        f = compare(e, v)
        for name in f:
            counts[name] += 1
        if f:
            flagged.append((r, f))

    print(f"corpus: {len(rows)} accepted predictions, each with two independently written criteria\n")
    print("MECHANICAL DISAGREEMENT SCREEN (no model calls, no semantic judgement)")
    agreed_open = counts.pop("both call it open-ended (not a disagreement)", 0)
    for k, n in counts.most_common():
        print(f"  {n:5d}  {k}")
    if agreed_open:
        print(f"  {agreed_open:5d}  (both call it open-ended: agreement, not a flag)")
    if not counts:
        print("      0  no mechanical disagreement found")
    print(f"\n  {len(flagged):5d}  records carry at least one flag  "
          f"({100 * len(flagged) / len(rows):.1f}% of {len(rows)})")
    print(f"  {len(rows) - len(flagged):5d}  records agree on every part a machine can read")

    print("\nWHAT THIS BOUNDS")
    print("  A LOWER bound on the records needing a human: two criteria can use identical dates")
    print("  and numbers and still test different observables, and this screen cannot see that.")
    print("  It also carries false positives, because the verifier writes a longer criterion and")
    print("  its extra numbers are often context rather than a changed threshold.")
    print("  Read a sample before costing the human review:  --flag <name> --sample 5")

    if args.flag:
        pick = [(r, f) for r, f in flagged if args.flag in f]
        print(f"\n{len(pick)} records carry {args.flag!r}")
        for r, f in pick[:args.sample or 3]:
            p = r["prediction"]
            print(f"\n  [{r['leader_slug']} · said {r['source']['statement_date']} · "
                  f"target_date {p['target_date']}] flags={f}")
            print(textwrap.fill("E: " + (p.get("resolution_criteria") or ""), 108,
                                initial_indent="    ", subsequent_indent="       "))
            print(textwrap.fill("V: " + (r["verification"].get("verifier_resolution_criteria") or ""), 108,
                                initial_indent="    ", subsequent_indent="       "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
