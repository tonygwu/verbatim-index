#!/usr/bin/env python3
"""pundits_sample_size.py on synthetic grades: it recovers a known sd and ICC, and its formula is the stated one.

No pundits data, no quota.
  .venv/bin/python scripts/test_pundits_sample_size.py
"""
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pundits_sample_size as S  # noqa: E402

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  -- {detail}")


# The formula, by hand: sd 5, ICC 0.3, 12 per person, 20/20 -> v = 25*(0.3+0.7/12) = 8.9583; *(1/20+1/20) = 0.8958;
# sqrt = 0.9465; *1.6449 = 1.5569.
check("half_width matches the hand computation", abs(S.half_width(5, 0.3, 20, 20, 12) - 1.5569) < 1e-3,
      str(S.half_width(5, 0.3, 20, 20, 12)))
check("fewer people per side widen it", S.half_width(5, 0.3, 13, 13, 12) > S.half_width(5, 0.3, 20, 20, 12))
check("ICC 0 and 1 bound it", S.half_width(5, 0.0, 20, 20, 12) < S.half_width(5, 1.0, 20, 20, 12))

# Synthetic grades with a known person effect: d = person_effect (sd 3) + noise (sd 4), so sd ~ 5 and ICC ~ 0.36.
rng = random.Random(7)
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "data-pundits"
    for j in ("fable", "gemini"):
        (root / "grades" / j).mkdir(parents=True)
    for p in range(60):
        eff = rng.gauss(0, 3)
        for t in range(12):
            tid = f"p{p}/t{t}"
            base = rng.gauss(60, 8)
            d = eff + rng.gauss(0, 4)
            for j, val in (("fable", base + d), ("gemini", base)):
                f = root / "grades" / j / f"p{p}" / f"t{t}__{j}__blinded__r0.json"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps({"transcript_id": tid, "leader_slug": f"p{p}", "judge": j, "mode": "blinded",
                                         "validation_errors": [], "grade": {"overall": val}}))
    # an open-mode grade and an invalid grade are ignored, and a transcript one judge lacks is skipped
    (root / "grades" / "fable" / "p0" / "x__fable__open__r0.json").write_text(json.dumps(
        {"transcript_id": "p0/x", "leader_slug": "p0", "mode": "open", "validation_errors": [], "grade": {"overall": 1}}))
    (root / "grades" / "fable" / "p0" / "y__fable__blinded__r0.json").write_text(json.dumps(
        {"transcript_id": "p0/y", "leader_slug": "p0", "mode": "blinded", "validation_errors": [], "grade": {"overall": 1}}))
    groups = S.load_d(root / "grades")
    check("only transcripts every judge graded in blinded mode enter", sum(len(g) for g in groups.values()) == 720,
          str(sum(len(g) for g in groups.values())))
    sd, icc = S.sd_icc(groups)
    check("sd is recovered (true 5.0)", abs(sd - 5.0) < 0.5, str(sd))
    check("ICC is recovered (true 0.36)", abs(icc - 0.36) < 0.12, str(icc))
    out = Path(td) / "rep.json"
    S.main(["--data", str(root), "--boot", "200", "--json", str(out)])
    rep = json.loads(out.read_text())
    check("the report carries every split with a bootstrap interval",
          set(rep["projections"]) == {"20/20", "16/16", "13/13"}
          and all(v["boot_p5"] <= v["half_width"] <= v["boot_p95"] for v in rep["projections"].values()), str(rep))
    check("the planning assumption is reported by the same formula",
          rep["planning_assumption_half_width_20_20"] == round(S.half_width(5, 0.3, 20, 20, 12), 3))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
