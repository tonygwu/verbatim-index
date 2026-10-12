#!/usr/bin/env python3
"""The era covariate plan P5 asks the board to report, measured with the speaker held fixed.

docs/PUNDITS-PLAN.md, P5 "Sampling rules": "The board reports era as a covariate."
Until 2026-10-12 nothing fitted it. aggregate.era_covariate() reads each board
recording's upload date (yt_upload_date, a UTC calendar date in the blinded
transcript record) and fits the pooled within-person slope of the recording's
blinded score on that date, in points per year. It is reported, never applied.

Within-person matters for the same reason it does for venue: people are not
spread evenly over time, so a raw slope across the board mixes "later
recordings score higher" with "the people recorded later score higher".

  TREND      every person gains exactly 2 points a year: the slope is 2.0 and
             every resample agrees
  CONFOUND   the high scorer's recordings are old and the low scorer's are new,
             and nobody changes over time: the slope is 0.0, though a raw slope
             across the board is strongly negative
  UNDATED    a board recording with no date, or a date not in YYYYMMDD, is left
             out of the fit and listed by name, never guessed
  SCOPE      open rows and unranked people never enter; a person with one date
             cannot carry a within-person slope and is counted as such
  TOO FEW    under two people with a within-person spread, computed=false with why
  END TO END aggregate.py reads the dates from --transcripts; without the flag it
             says so; the key is written only for a contract-v2 study

No quota, no data.

  .venv/bin/python scripts/test_era_covariate.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PY = sys.executable
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def enclosing_line(src: str, needle: str) -> str:
    """The statement that opens the block holding the first line with `needle`."""
    lines = src.splitlines()
    i = next((k for k, ln in enumerate(lines) if needle in ln), None)
    if i is None:
        return ""
    depth = len(lines[i]) - len(lines[i].lstrip())
    for ln in reversed(lines[:i]):
        if ln.strip() and len(ln) - len(ln.lstrip()) < depth:
            return ln.strip()
    return ""


def board(spec: dict[str, list[tuple[str, float]]]) -> tuple[list[dict], list[dict], dict]:
    """Blinded and open rows, the ranked list and the date map for {slug: [(yyyymmdd, score)]}."""
    rows, dates = [], {}
    for slug, recs in spec.items():
        for i, (day, score) in enumerate(recs):
            sid = f"{slug}-{i}"
            dates[(slug, sid)] = day
            for mode in ("blinded", "open"):
                # Open rows carry a wildly different value, so counting them would show.
                rows.append({"leader_slug": slug, "source_id": sid, "mode": mode,
                             "cal_overall": score if mode == "blinded" else 99.0})
    ranked = [{"slug": s, "rank": k + 1} for k, s in enumerate(spec)]
    return rows, ranked, dates


def naive_slope(rows: list[dict], dates: dict, years) -> float:
    pts = [(years(dates[(r["leader_slug"], r["source_id"])]), r["cal_overall"]) for r in rows
           if r["mode"] == "blinded"]
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    return sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)


def main() -> int:
    print("era covariate")
    try:
        import aggregate as A
        fn = A.era_covariate
    except Exception as exc:  # noqa: BLE001 - the missing function is the failure under test
        check("aggregate.era_covariate exists", False, repr(exc))
        print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
        return 1

    print("\n[TREND]")
    # Dates a calendar year apart. At 365.25 days a year a 365- or 366-day step is
    # within 0.1% of a year, so each person's slope rounds to 2.0 at two decimals.
    spec = {"a": [("20220601", 50.0), ("20230601", 52.0), ("20240601", 54.0)],
            "b": [("20230101", 30.0), ("20250101", 34.0)],
            "c": [("20211001", 70.0), ("20221001", 72.0), ("20231001", 74.0), ("20241001", 76.0)]}
    rows, ranked, dates = board(spec)
    out = fn(rows, ranked, dates, n=400)
    check("computed", out.get("computed") is True, json.dumps(out)[:300])
    check("the slope is 2.0 points a year", out.get("slope_per_year") == 2.0, str(out.get("slope_per_year")))
    check("every resample agrees, so the interval is [2.0, 2.0]", out.get("ci95") == [2.0, 2.0], str(out.get("ci95")))
    check("9 recordings from 3 people", out.get("recordings_used") == 9 and out.get("people_used") == 3, str(out))
    check("recordings are counted by upload year",
          out.get("recordings_by_year") == {"2021": 1, "2022": 2, "2023": 3, "2024": 2, "2025": 1},
          str(out.get("recordings_by_year")))
    check("the first and last upload dates", out.get("first_upload") == "2021-10-01"
          and out.get("last_upload") == "2025-01-01", f"{out.get('first_upload')} {out.get('last_upload')}")
    check("it says it is reported, not applied", out.get("applied") is False, str(out.get("applied")))

    print("\n[CONFOUND]")
    spec = {"old-high": [("20220101", 80.0), ("20220601", 80.0), ("20221101", 80.0)],
            "new-low": [("20250101", 40.0), ("20250601", 40.0), ("20251101", 40.0)]}
    rows, ranked, dates = board(spec)
    out = fn(rows, ranked, dates, n=400)
    raw = naive_slope(rows, dates, A.upload_years)
    check("the fixture really confounds: a raw slope across the board is below -10", raw < -10, str(raw))
    check("the within-person slope is 0.0", out.get("slope_per_year") == 0.0, str(out.get("slope_per_year")))

    print("\n[UNDATED]")
    spec = {"a": [("20220601", 50.0), ("20230601", 52.0), ("", 90.0)],
            "b": [("20230101", 30.0), ("20250101", 34.0), ("2024-01-01", 10.0)]}
    rows, ranked, dates = board(spec)
    dates[("a", "a-9")] = None  # no transcript record at all
    rows.append({"leader_slug": "a", "source_id": "a-9", "mode": "blinded", "cal_overall": 0.0})
    out = fn(rows, ranked, dates, n=400)
    check("the three undated recordings are listed by name",
          out.get("recordings_without_date") == ["a/a-2", "a/a-9", "b/b-2"], str(out.get("recordings_without_date")))
    check("and left out of the fit, which stays at 2.0", out.get("slope_per_year") == 2.0
          and out.get("recordings_used") == 4, str(out))

    print("\n[SCOPE]")
    spec = {"a": [("20220601", 50.0), ("20230601", 52.0)],
            "b": [("20230101", 30.0), ("20250101", 34.0)],
            "one-day": [("20240101", 10.0), ("20240101", 90.0)],
            "unranked": [("20220101", 0.0), ("20260101", 100.0)]}
    rows, ranked, dates = board(spec)
    ranked = [p for p in ranked if p["slug"] != "unranked"]
    out = fn(rows, ranked, dates, n=400)
    check("an unranked person and open rows never enter: the slope stays 2.0",
          out.get("slope_per_year") == 2.0, str(out.get("slope_per_year")))
    check("a person whose recordings share one date is counted, not fitted",
          out.get("people_used") == 2 and out.get("people_without_spread") == ["one-day"], str(out))
    # FOUND 2026-10-12 by the second review: the span and the year counts included
    # the unfitted person, though the page states them beside recordings_used.
    check("the date span and year counts describe the fitted recordings only",
          out.get("recordings_by_year") == {"2022": 1, "2023": 2, "2025": 1} and out.get("recordings_used") == 4
          and out.get("first_upload") == "2022-06-01" and out.get("last_upload") == "2025-01-01", str(out))

    print("\n[TWO STAGE]")
    # FOUND 2026-10-12 by the second review: plan P5's bootstrap "resamples people,
    # then transcripts within each person", and this one resampled people only, so
    # people with the same noisy pattern gave a zero-width interval.
    spec = {p: [("20220601", 50.0), ("20230601", 54.0), ("20240601", 50.0)] for p in ("a", "b", "c")}
    rows, ranked, dates = board(spec)
    out = fn(rows, ranked, dates, n=2000)
    lo, hi = out.get("ci95") or [0, 0]
    check("identical noisy people: slope 0.0 with an interval that has width", out.get("slope_per_year") == 0.0
          and lo < 0 < hi, str(out.get("ci95")))
    check("it says which draws it could not use, if any",
          isinstance(out.get("degenerate_resamples"), int), str(out.get("degenerate_resamples")))

    print("\n[TOO FEW]")
    spec = {"a": [("20220601", 50.0), ("20230601", 52.0)], "b": [("20230101", 30.0)]}
    rows, ranked, dates = board(spec)
    out = fn(rows, ranked, dates, n=400)
    check("one person with a spread: computed=false, saying why",
          out.get("computed") is False and "two people" in out.get("why", ""), str(out))

    print("\n[END TO END]")
    tps = load("tps_era", REPO / "scripts" / "test_profile_scoring.py")
    with tempfile.TemporaryDirectory(prefix="era-") as td:
        root, profiles = tps.fixture_corpus(Path(td).resolve())
        tb = root / "transcripts_blind"
        for f in (root / "grades").rglob("*.json"):
            rec = json.loads(f.read_text())
            year = 2021 + int(rec["source_id"][1:])
            out_f = tb / rec["leader_slug"] / f"{rec['source_id']}.json"
            out_f.parent.mkdir(parents=True, exist_ok=True)
            out_f.write_text(json.dumps({"source_id": rec["source_id"], "leader_slug": rec["leader_slug"],
                                         "yt_upload_date": f"{year}0301", "text": "x"}))
        env = {k: v for k, v in os.environ.items() if k != "STUDY"}
        env["VI_PROFILES_DIR"] = str(profiles)
        base = [PY, REPO / "scripts" / "aggregate.py", "--study", "pundits", "--grades", root / "grades",
                "--roster", root / "roster" / "final.json"]
        r = subprocess.run(base + ["--transcripts", tb, "--out", root / "with.json"],
                           env=env, capture_output=True, text=True)
        check("the fixture corpus aggregates with --transcripts", r.returncode == 0, r.stderr[-400:])
        res = json.loads((root / "with.json").read_text()) if (root / "with.json").exists() else {}
        era = (res.get("diagnostics") or {}).get("era_covariate") or {}
        n_board = sum(1 for t in res.get("transcripts", []) if t["mode"] == "blinded"
                      and t["leader_slug"] in {p["slug"] for p in res.get("leaders", [])})
        check("it fitted every board recording, with none undated",
              era.get("computed") is True and era.get("recordings_used") == n_board > 0
              and era.get("recordings_without_date") == [], json.dumps(era)[:400])
        r2 = subprocess.run(base + ["--out", root / "without.json"], env=env, capture_output=True, text=True)
        res2 = json.loads((root / "without.json").read_text()) if (root / "without.json").exists() else {}
        era2 = (res2.get("diagnostics") or {}).get("era_covariate") or {}
        check("without --transcripts: computed=false, naming the flag",
              r2.returncode == 0 and era2.get("computed") is False and "--transcripts" in era2.get("why", ""),
              str(era2))

    opener = enclosing_line((REPO / "scripts" / "aggregate.py").read_text(), 'diagnostics["era_covariate"]')
    check("the key is written only under is_v2", opener == "if is_v2:", opener)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
