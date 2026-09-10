#!/usr/bin/env python3
"""Guards for paragraph-scale loop collapse in normalize_transcripts.py.

`collapse_loops` repairs a recogniser stuttering on one token. It cannot see a
live stream that replays the same eight minutes 39 times, which is what
sam-altman/the-economic-times-vfilis is: 64,068 words of which 96.2% sit
inside a 20-gram that already occurred earlier. MEASURED 2026-09-10 on 569
transcripts with an alignment-free 20-gram measure: 8 are more than 10%
repeated, the worst four 76-96%. The stride-40 block measure that first
reported this defect put the worst at 19.6% and saw only 3, because a loop
whose period is not a multiple of 40 words never lines up with the blocks.

  .venv/bin/python scripts/test_loop_collapse.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail and not ok:
        print(f"          {detail}")


spec = importlib.util.spec_from_file_location("nt", REPO / "scripts" / "normalize_transcripts.py")
nt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nt)

WORDS = ("the quick brown fox jumps over the lazy dog while the farmer counts "
         "sheep near the old red barn and the river runs slowly past the mill "
         "where children play until the evening bell rings across the valley at dusk").split()
assert len(WORDS) == 40


def stamped(words: list[str], start_min: int) -> str:
    """Words with a [hh:mm:ss] marker every 20 words, as the fetcher writes them."""
    out = []
    for i, w in enumerate(words):
        if i % 20 == 0:
            m = start_min + i // 20
            out.append(f"[00:{m:02d}:00]")
        out.append(w)
    return " ".join(out)


print("collapse_paragraph_loops")
check("function exists", hasattr(nt, "collapse_paragraph_loops"))
if hasattr(nt, "collapse_paragraph_loops"):
    f = nt.collapse_paragraph_loops

    # 1. Three copies of a 40-word passage, each with fresh timestamps, collapse
    #    to one copy. Timestamps differ between copies, so the match must ignore
    #    them.
    loop = " ".join(stamped(WORDS, k * 3) for k in range(3))
    text, info = f(loop)
    kept = [t for t in text.split() if not t.startswith("[")]
    check("three copies of a passage collapse to about one",
          len(WORDS) <= len(kept) <= len(WORDS) + 2, f"kept {len(kept)} content tokens")
    check("the removal is counted", info.get("tokens_removed", 0) >= 2 * len(WORDS) - 4, str(info))
    check("the repeat share is reported", 0.6 <= info.get("repeat_share", 0) <= 0.7, str(info))
    check("timestamps survive in the kept copy", text.startswith("[00:00:00] the quick"), text[:40])

    # 2. Ordinary speech repeats short phrases all the time. Nothing under the
    #    window is touched, so an interview with a catch-phrase is unchanged.
    speech = " ".join(f"you know I think {w}{i} is important and you know it" for i, w in enumerate(WORDS))
    text2, info2 = f(speech)
    check("short repeated phrases in ordinary speech are left alone",
          text2 == speech and info2["tokens_removed"] == 0, str(info2))

    # 3. A short passage repeated exactly is below the window and kept: a host
    #    reading the same sponsor line twice is not a loop.
    short = " ".join(WORDS[:12])
    twice = short + " and then " + short
    text3, info3 = f(twice)
    check("a 12-word repeat is below the 20-word window and kept", text3 == twice, text3)

    # 4. A window of exactly n tokens repeated once is removed once and the
    #    first occurrence is kept.
    n = f.__defaults__[0] if f.__defaults__ else 20
    para = WORDS[:n]
    text4, info4 = f(" ".join(para + ["interlude"] + para))
    check("an exact window repeat is removed once", text4.split() == para + ["interlude"], text4)

    # 5. The ASR renders each replay slightly differently. A difference at
    #    token 15 of the second copy means no 20-token window covers tokens
    #    0-16 of that copy, so a 17-token hole survives the window match. That
    #    hole is loop residue, not new speech, and goes too.
    variant = list(WORDS); variant[15] = "quikc"; variant[16] = "browne"
    loop5 = " ".join(WORDS) + " " + " ".join(variant) + " " + " ".join(WORDS)
    text5, info5 = f(loop5)
    check("the hole an ASR difference leaves at the head of a replay is removed",
          len(text5.split()) <= len(WORDS) + 2, f"{len(text5.split())} tokens kept: {text5[-120:]}")
    # 5b. A genuine short passage in a transcript with no repeats is untouched,
    #     because islands only exist between removed material.
    check("island removal never fires when nothing repeats",
          f(" ".join(WORDS[:5]))[1]["tokens_removed"] == 0)

    # 5c. A cold-open teaser repeats 40 words of a 2,000-word episode. That is
    #     2% and below the gate: measured and reported, not removed.
    body = " ".join(f"{w}{i}" for i in range(50) for w in WORDS)
    teaser = " ".join(WORDS) + " " + body + " " + " ".join(WORDS)
    text6, info6 = f(teaser)
    check("a 2% repeat is left in place and reported",
          text6 == teaser and info6["tokens_removed"] == 0 and 0.01 < info6["repeat_share"] < 0.05
          and info6.get("below_min_share") is True, str(info6))

    # 6. Empty input is safe.
    check("empty input", f("") == ("", {"repeat_share": 0.0, "tokens_removed": 0, "content_tokens": 0}), str(f("")))

# ---------------------------------------------------------------------------
# 7. The normalizer records what it did, per transcript, next to loop_collapse.
print("normalize_transcripts.py wiring")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = td / "transcripts" / "x"; src.mkdir(parents=True)
    looped = " ".join(stamped(WORDS, k * 3) for k in range(4))
    (src / "s1.json").write_text(json.dumps({"leader_slug": "x", "source_id": "s1", "text": looped,
                                             "word_count": len(looped.split())}))
    (td / "roster.json").write_text(json.dumps({"roster": [{"slug": "x", "name": "Xavier Xu", "company": "Xco"}]}))
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "normalize_transcripts.py"),
                           "--transcripts", str(src.parent), "--out", str(td / "open"), "--roster", str(td / "roster.json"),
                           "--mode", "open", "--log", str(td / "log.json")], capture_output=True, text=True)
    check("normalizer exits 0 on a looped transcript", proc.returncode == 0, proc.stderr[-400:])
    out = td / "open" / "x" / "s1.json"
    rec = json.loads(out.read_text()) if out.exists() else {}
    norm = rec.get("normalization", {})
    check("normalization carries paragraph_loop_collapse", "paragraph_loop_collapse" in norm, str(list(norm)))
    plc = norm.get("paragraph_loop_collapse", {})
    check("it removed the three extra copies", plc.get("tokens_removed", 0) >= 3 * len(WORDS) - 4, str(plc))
    check("word_count is updated to the collapsed text",
          rec.get("word_count") == len(rec.get("text", "").split()) and rec.get("word_count", 0) < 2 * len(WORDS),
          f"word_count={rec.get('word_count')} tokens={len(rec.get('text','').split())}")
    check("the original length is kept for the record",
          plc.get("original_word_count") == len(looped.split()), str(plc))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
