#!/usr/bin/env python3
"""speaker_segment_probe.py scores a model's speaker turns against a person's word ranges.

Spends no quota: the model responses are written by hand. Proves that a turn's start
is fixed by its first words rather than its marker, that a start the words cannot
fix is counted rather than hidden, that a malformed response is refused, that the
score compares only words the person labelled as subject or other, that quote
answers come from the same `quote_review` the page uses, and that a recording is
dropped from EVERY arm when any arm failed on it.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import speaker_segment_probe as P  # noqa: E402
from pundits_speaker_spans import build_transcript, sidecar_path  # noqa: E402

FAILED = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


# word 0 timestamp, 1..5 host, 6..15 subject, 16 timestamp, 17..20 host
TEXT = ("[00:00:01] so tell us more please "
        "well I think the answer is clearly more power sooner "
        "[00:00:09] thanks that was great")


def main() -> int:
    toks = TEXT.split()
    print("[RESOLVE]")
    ranges, how = P.resolve([{"marker": 0, "first_words": "so tell us more", "speaker": "other"},
                             {"marker": 0, "first_words": "well I think the answer", "speaker": "subject"},
                             {"marker": 10, "first_words": "thanks that was great", "speaker": "other"}], toks)
    # Word 0 and word 16 are timestamps, which no turn may start on.
    check("the first words, not the marker, fix each start, always on a spoken word",
          [r["start"] for r in ranges] == [1, 6, 17])
    check("turns run to the next start and the last to the end", [r["end"] for r in ranges] == [6, 17, 21])
    r3, how3 = P.resolve([{"marker": 0, "first_words": "[00:00:01] so tell us", "speaker": "other"}], toks)
    check("a timestamp copied into first_words still matches by words",
          how3 == {"by_words": 1, "start_from_marker_only": 0} and r3[0]["start"] == 1)
    _, how2 = P.resolve([{"marker": 10, "first_words": "words that are nowhere", "speaker": "other"}], toks)
    check("a start its words cannot fix falls back to the marker and is counted",
          how == {"by_words": 3, "start_from_marker_only": 0} and how2["start_from_marker_only"] == 1)
    check("the marked text puts a marker before every tenth word",
          P.marked_text(toks).startswith("⟨0⟩ [00:00:01]") and "⟨10⟩ answer" in P.marked_text(toks))

    print("\n[PARSE]")
    check("a fenced JSON answer parses",
          len(P.parse_turns('```json\n{"turns":[{"marker":0,"first_words":"x","speaker":"subject"}]}\n```')) == 1)
    for label, bad in (("prose", "I think the host speaks first."),
                       ("an unknown speaker", '{"turns":[{"marker":0,"speaker":"host"}]}'),
                       ("an empty list", '{"turns":[]}')):
        try:
            P.parse_turns(bad)
            ok = False
        except (ValueError, KeyError, json.JSONDecodeError):
            ok = True
        check(f"{label} is refused", ok)

    print("\n[SCORE]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        page = td / "speaker_check.html"
        key = "p/a"
        side = build_transcript(key, TEXT, [])
        sidecar_path(page, key).parent.mkdir(parents=True)
        sidecar_path(page, key).write_text(json.dumps(side))
        quote = {"qid": "p:a:6", "quote_start": 6, "quote_end": 16}
        page.write_text("const D = " + json.dumps({"quote_rows": [{"key": key, "quotes": [quote]}]}) + ";\n")
        # The person labelled the host question and the answer; nothing after word 15.
        answers = {"spans": {key: {"key": key, "text_sha256": side["text_sha256"], "token_count": side["token_count"],
                                   "checked_by": "operator",
                                   "ranges": [{"start": 1, "end": 6, "speaker": "other", "origin": "human"},
                                              {"start": 6, "end": 16, "speaker": "subject", "origin": "human"}]}},
                   "attribution": {"p:a:6": {"answer": "subject"}}}
        (td / "answers.json").write_text(json.dumps(answers))
        good = [{"marker": 0, "first_words": "so tell us more", "speaker": "other"},
                {"marker": 0, "first_words": "well I think the answer", "speaker": "subject"}]
        # Wrong from "is clearly" on: 5 of the 10 answer words go to the host.
        late = [{"marker": 0, "first_words": "so tell us more", "speaker": "other"},
                {"marker": 0, "first_words": "well I think the answer", "speaker": "subject"},
                {"marker": 10, "first_words": "is clearly more power", "speaker": "other"}]
        run = td / "run"
        run.mkdir()
        results = [{"arm": "a1", "key": key, "repeat": 0, "outcome": "parsed", "turns": good},
                   {"arm": "a2", "key": key, "repeat": 0, "outcome": "parsed", "turns": late}]
        (run / "results.json").write_text(json.dumps(results))
        P.score(SimpleNamespace(run=str(run), answers=str(td / "answers.json"), page=str(page), report=None))
        rep = json.loads((run / "score.json").read_text())
        rows = {r["arm"]: r for r in rep["per_run"]}
        check("only labelled speech words are compared (5 host + 10 subject; the timestamp is not speech)",
              rows["a1"]["words_compared"] == 15)
        check("a correct segmentation scores 1.0 and agrees on the quote",
              rows["a1"]["word_accuracy"] == 1.0 and rows["a1"]["quotes_agree"] == 1)
        check("a late boundary costs exactly the words it misplaced, and the quote becomes 'both'",
              rows["a2"]["confusion"].get("subject->other") == 5 and rows["a2"]["quotes"][0]["model"] == "both")
        results[1]["outcome"] = "excluded_infra"
        (run / "results.json").write_text(json.dumps(results))
        P.score(SimpleNamespace(run=str(run), answers=str(td / "answers.json"), page=str(page), report=None))
        rep = json.loads((run / "score.json").read_text())
        check("a recording one arm failed on is scored for NO arm, and the exclusion is reported",
              rep["per_run"] == [] and rep["not_scored"] and rep["arms"]["a2"]["excluded"])

    print(f"\n{'FAILED ' + str(len(FAILED)) if FAILED else 'all passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
