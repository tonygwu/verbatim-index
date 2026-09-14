#!/usr/bin/env python3
"""The P7 labelling kit: windows cut on real marks from human-verified recordings, quotes balanced and blind to the judge.

Pundits plan, P7.

  VERIFIED   only recordings a person marked present and main speaker, with a
             checked_by, are used; the format comes from the human venue label
  WINDOW     a window starts on a mark and ends on the first mark at least 600 s
             later, and its text is exactly the text between them
  SHORTFALL  a format with too few recordings is reported and not topped up
  EMPTY      every label field is written empty
  SEEDED     the same seed gives the same kit
  QUOTES     only judge-labelled subject quotes; at most 60 per format; the
             (judge, mode) cells differ by at most one; the judge, mode and
             speaker label are absent from the file people label and present
             in the answer key

No network, no quota.

  .venv/bin/python scripts/test_pundits_label_kit.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def transcript(minutes: int) -> str:
    return " ".join(f"[{m // 60:02d}:{m % 60:02d}:00] minute {m} words here" for m in range(minutes))


def lab(venue, present=True, main=True, by="tg"):
    return {"subject_present": present, "main_speaker": main, "venue": venue, "checked_by": by}


def main() -> int:
    print("pundits labelling kit")
    import pundits_label_kit as K

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "transcripts"
        human = {}
        venues = ["reaction_stream"] * 7 + ["debate"] * 2 + ["guest_interview"] * 3 + ["hosted_interview"] * 3
        for i, v in enumerate(venues):
            (root / "p").mkdir(parents=True, exist_ok=True)
            (root / "p" / f"s{i}.json").write_text(json.dumps({"video_id": f"v{i:010d}", "text": transcript(40)}))
            human[f"p/s{i}"] = lab(v)
        (root / "p" / "bad1.json").write_text(json.dumps({"video_id": "b", "text": transcript(40)}))
        human["p/bad1"] = lab("debate", present=False)
        (root / "p" / "bad2.json").write_text(json.dumps({"video_id": "c", "text": transcript(40)}))
        human["p/bad2"] = {"subject_present": True, "main_speaker": True, "venue": "debate", "checked_by": None}

        print("\n[VERIFIED]")
        ver = K.verified(human)
        check("absent subject and unsigned labels are excluded", "p/bad1" not in ver and "p/bad2" not in ver)
        check("guest and hosted interviews both map to the interview format",
              Counter(ver.values())["interview"] == 6, str(Counter(ver.values())))

        windows, shortfall = K.build_windows(root, human, seed=3)
        print("\n[WINDOW]")
        w = windows[0]
        check("a window starts and ends on marks at least 600 s apart",
              w["text"].startswith("[") and w["end_sec"] - w["start_sec"] >= 600, str((w["start_sec"], w["end_sec"])))
        check("the window text is exactly the span between the two marks",
              w["text"].strip().endswith("words here") and f"[{w['end_sec'] // 3600:02d}:{w['end_sec'] // 60 % 60:02d}:00]" not in w["text"])
        check("no window uses an excluded recording", all(x["source_id"] not in ("bad1", "bad2") for x in windows))

        print("\n[SHORTFALL]")
        by = Counter(x["format"] for x in windows)
        check("formats with enough recordings get 6 windows", by["reaction"] == 6 and by["interview"] == 6, str(by))
        check("debate with 2 recordings is short and reported, not topped up",
              by["debate"] == 2 and shortfall.get("debate", {}).get("got") == 2, str(shortfall))
        check("formats with no recordings are reported", "panel" in shortfall and "monologue" in shortfall, str(shortfall))

        print("\n[EMPTY]")
        check("every label field is empty", all(all(v is None for v in x["labels"].values()) for x in windows))

        print("\n[SEEDED]")
        check("the same seed gives the same windows", K.build_windows(root, human, seed=3)[0] == windows)

        print("\n[QUOTES]")
        grades = Path(td) / "grades"
        n = 0
        for i, v in enumerate(venues[:9]):
            for judge in ("fable", "astra", "gemini"):
                for mode in ("blinded", "open"):
                    ev = [{"quote": f"q{i}{judge}{mode}{k}", "timestamp": "[00:01:00]", "speaker": "subject", "why_it_matters": "x"}
                          for k in range(3)]
                    ev.append({"quote": "host line", "timestamp": "unmarked", "speaker": "interlocutor", "why_it_matters": "x"})
                    rec = {"leader_slug": "p", "source_id": f"s{i}", "video_id": f"v{i:010d}", "judge": judge, "mode": mode,
                           "grade": {"dimensions": {"d1_steelmanning": {"evidence": ev}}}}
                    path = grades / "p" / f"s{i}__{judge}__{mode}__r0.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(rec))
                    n += 1
        to_label, key, qshort = K.build_quotes(grades, human, seed=5)
        check("only subject quotes are drawn", all(q["quote"] != "host line" for q in to_label))
        by = Counter(q["format"] for q in to_label)
        check("at most 60 per format, with reaction capped at 60 from a larger pool", by["reaction"] == 60, str(by))
        cells = Counter((key[q["quote_id"]]["judge"], key[q["quote_id"]]["mode"]) for q in to_label if q["format"] == "reaction")
        check("(judge, mode) cells differ by at most one", max(cells.values()) - min(cells.values()) <= 1, str(cells))
        check("debate with too few quotes is reported as a shortfall", qshort.get("debate", {}).get("got") == 36, str(qshort))
        leaked = [q for q in to_label if {"judge", "mode", "judge_speaker", "grade_file"} & set(q)]
        check("the file people label carries no judge, mode or judge speaker label", not leaked, str(leaked[:1]))
        check("the answer key holds judge, mode and the judge's speaker label for every quote",
              set(key) == {q["quote_id"] for q in to_label} and all({"judge", "mode", "judge_speaker"} <= set(v) for v in key.values()))
        check("every quote label field is empty", all(q["spoken_by_subject"] is None and q["checked_by"] is None for q in to_label))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
