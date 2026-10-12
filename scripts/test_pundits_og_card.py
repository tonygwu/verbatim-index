#!/usr/bin/env python3
"""The pundits page's social card: counts drawn from results.json, and a warning when they drift.

FOUND 2026-10-12: a link to pundits.tonygwu.com showed no image, because only the
leaders and predictions sites had a card. build_og_card.py --site pundits draws
site-pundits/og.png from results.json, and the page carries it with a cache key
from the card's bytes. The card is a committed image, so the page builder warns
(never blocks) when its counts no longer match the board.

  COUNTS    people ranked, board recordings and published judges, from results.json
  LABEL     the card carries the board's status label, so a pilot is never shown
            as the finished study
  PAGE      with a card: og:image with a byte-derived version, its size, and a large
            Twitter card; without one: a text-only card and no og:image
  STALE     a card drawn from other counts produces a warning naming each count;
            a matching card produces none

Drawing the picture needs Chrome and is not done here. No quota, no data.

  .venv/bin/python scripts/test_pundits_og_card.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def main() -> int:
    print("pundits social card")
    import build_og_card as O
    import build_study_site as B
    import test_study_site as T

    res = T.results()
    # FOUND 2026-10-12 by review: the card counted transcripts_with_blinded_consensus,
    # which includes unranked people's recordings, while the page lists only the
    # board's. Cy is unranked and has 2 recordings; Ada, ranked, has 8.
    res["transcripts"] += [{"leader_slug": "cy", "source_id": f"cy-{i}", "mode": m, "venue_type": "solo"}
                           for i in range(2) for m in ("blinded", "open")]
    res["diagnostics"].update({"transcripts_with_blinded_consensus": 10,
                               "judge_models": {"fable": {"m": 1}, "gemini": {"m": 1}}})

    print("\n[COUNTS]")
    fn = getattr(O, "pundits_counts_from", None)
    if fn is None:
        check("build_og_card.pundits_counts_from exists", False)
    else:
        counts, stats = fn(res)
        check("people ranked, board recordings and judges come from results.json",
              counts == {"people": 2, "recordings": 8, "judges": 2}, str(counts))
        check("and are drawn as the card's three stats",
              stats == [("People ranked", "2"), ("Recordings", "8"), ("Judges", "2")], str(stats))
    check("build_og_card knows a pundits site writing site-pundits/og.png",
          "pundits" in O.SITES and O.SITES["pundits"]["out"] == REPO / "site-pundits" / "og.png")
    check("the card's eyebrow carries the board's status label",
          "pundits" in O.SITES and T.copy()["status_label"].upper() in O.SITES["pundits"]["domain"].upper(),
          O.SITES.get("pundits", {}).get("domain", ""))

    print("\n[PAGE]")
    with tempfile.TemporaryDirectory(prefix="og-") as td:
        card = Path(td) / "og.png"
        card.write_bytes(b"\x89PNG fake card bytes" * 400)
        v = hashlib.sha256(card.read_bytes()).hexdigest()[:12]
        url = T.copy()["site_url"]
        page = B.render(res, T.profile(), T.copy(), rundate="x", og_card=card)
        check("og:image names the card with a byte-derived version",
              f'<meta property="og:image" content="{url}og.png?v={v}">' in page)
        check("with its size", '<meta property="og:image:width" content="1200">' in page
              and '<meta property="og:image:height" content="630">' in page)
        check("and a large Twitter card", '<meta name="twitter:card" content="summary_large_image">' in page)
        bare = B.render(res, T.profile(), T.copy(), rundate="x", og_card=Path(td) / "missing.png")
        check("without a card file: a text-only card and no og:image",
              '<meta name="twitter:card" content="summary">' in bare and "og:image" not in bare)

    print("\n[STALE]")
    warn = getattr(B, "og_card_drift", None)
    if warn is None:
        check("build_study_site.og_card_drift exists", False)
    else:
        same = warn(res, {"counts": {"people": 2, "recordings": 8, "judges": 2}})
        moved = warn(res, {"counts": {"people": 2, "recordings": 9, "judges": 3}})
        check("a matching card draws no warning", same is None, str(same))
        lacking = warn(T.results(), {"counts": {"people": 2}})
        check("a results.json without the counts warns that the card cannot be checked, never raises",
              lacking is not None and "cannot be checked" in lacking, str(lacking))
        check("a drifted card names each moved count",
              moved is not None and "recordings: card says 9, board has 8" in moved and "judges" in moved, str(moved))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
