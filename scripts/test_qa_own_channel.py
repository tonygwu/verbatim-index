#!/usr/bin/env python3
"""A pundit's own-channel upload skips only the name-density rejection, and only when the channel id proves it.

Pundits plan, P6. QA rejects a recording whose subject is named more than
1.6 times per 1000 words after the introduction, because for leaders that reads
as a show ABOUT the person. On a pundit's own show the host is named constantly
by guests and callers, so the plan skips that one rejection for own-channel
sources. The proof of an own-channel upload is the video's channel id, which
the fetcher now records as `yt_channel_id`.

  FETCH      fetch_metadata records yt_channel_id from yt-dlp's channel_id
  SKIP       a matching yt_channel_id with a high name density is not rejected
             for density, and the report says the check was skipped
  NO-SKIP    a different channel id, or no channel id at all, is still rejected
  OTHERS     every other rejection still applies to an own-channel upload
  LEADERS    a leaders roster entry (no own_channels) is never skipped

No network, no quota.

  .venv/bin/python scripts/test_qa_own_channel.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
OWN = "UC554eY5jNUfDq3yDOJYirOQ"
PERSON = {"slug": "steven-bonnell", "name": "Steven Bonnell",
          "own_channels": [{"url": "https://www.youtube.com/@destiny", "channel_id": OWN, "channel_name": "Destiny"}]}


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def density_rejected(reasons: list[str]) -> bool:
    return any("subject named" in r for r in reasons)


def main() -> int:
    print("QA own-channel skip")
    import fetch_transcripts as F
    import qa_transcripts as Q

    print("\n[FETCH]")
    payload = {"title": "t", "channel": "Destiny", "channel_id": OWN, "duration": 3600, "upload_date": "20250101"}
    real = F.subprocess.run
    F.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(payload), "")
    try:
        meta = F.fetch_metadata("abcdefghijk")
    finally:
        F.subprocess.run = real
    check("fetch_metadata records yt_channel_id", meta.get("yt_channel_id") == OWN, str(meta))

    base = {"name_per_1k_after_intro": 12.0, "word_count": 20000, "oov_rate": 0.02,
            "loop_token_fraction": 0.0, "mattr": 0.7, "words_per_minute": 150}

    print("\n[SKIP]")
    sig = dict(base)
    Q.apply_own_channel_skip(sig, {"yt_channel_id": OWN}, PERSON)
    verdict, reasons = Q.gate(sig, 50, 0)
    check("a matching channel id is not rejected for name density", not density_rejected(reasons), str(reasons))
    check("the report says the density check was skipped for an own channel",
          sig.get("name_density_check") == "skipped_own_channel" and sig.get("name_per_1k_after_intro_measured") == 12.0, str(sig))

    print("\n[NO-SKIP]")
    for label, rec in (("a different channel id", {"yt_channel_id": "UC" + "x" * 22}), ("no channel id", {})):
        sig = dict(base)
        Q.apply_own_channel_skip(sig, rec, PERSON)
        check(f"{label} is still rejected for name density", density_rejected(Q.gate(sig, 50, 0)[1]), str(sig))

    print("\n[OTHERS]")
    sig = {**base, "oov_rate": 0.9}
    Q.apply_own_channel_skip(sig, {"yt_channel_id": OWN}, PERSON)
    verdict, reasons = Q.gate(sig, 50, 0)
    check("an own-channel upload failing another check is still rejected", verdict == "reject" and reasons, str(reasons))

    print("\n[LEADERS]")
    sig = dict(base)
    Q.apply_own_channel_skip(sig, {"yt_channel_id": OWN}, {"slug": "tim-cook", "name": "Tim Cook", "company": "Apple"})
    check("a roster entry without own_channels is never skipped", density_rejected(Q.gate(sig, 50, 0)[1]), str(sig))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
