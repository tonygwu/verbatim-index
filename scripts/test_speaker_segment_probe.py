#!/usr/bin/env python3
"""speaker_segment_probe.py scores a model's speaker turns against a person's word ranges.

Spends no quota: the model responses are written by hand. Proves that a turn's start
is fixed by its first words rather than its marker, that a start the words cannot
fix is counted rather than hidden, that a malformed response is refused, that the
score compares only words the person labelled as subject or other, that quote
answers come from the same `quote_review` the page uses, and that a recording is
counted against that arm alone when the model failed, and dropped from EVERY arm
only when the infrastructure failed.
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
        (run / "manifest.json").write_text(json.dumps({"arms": {"a1": {}, "a2": {}}, "repeats": 1}))
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
        check("recall is reported per speaker, beside the all-subject baseline",
              rows["a2"]["recall"] == {"subject": 0.5, "other": 1.0} and rows["a2"]["baseline_all_subject"] == round(10 / 15, 4)
              and rep["arms"]["a2"]["other_recall"] == 1.0 and rep["arms"]["a2"]["subject_recall"] == 0.5)
        check("a late boundary costs exactly the words it misplaced, and the quote becomes 'both'",
              rows["a2"]["confusion"].get("subject->other") == 5 and rows["a2"]["quotes"][0]["model"] == "both")
        # Operator's rule, 2026-09-28: a model that fails both attempts is dinged, and
        # only an infrastructure failure removes the recording, from every arm.
        results[1] = {"arm": "a2", "key": key, "repeat": 0, "outcome": "failed", "attempts": 2,
                      "errors": [{"attempt": 1, "error": "empty_response: x"}, {"attempt": 2, "error": "empty_response: y"}]}
        (run / "results.json").write_text(json.dumps(results))
        P.score(SimpleNamespace(run=str(run), answers=str(td / "answers.json"), page=str(page), report=None))
        rep = json.loads((run / "score.json").read_text())
        rows = {r["arm"]: r for r in rep["per_run"]}
        check("a model failure scores 0 on every labelled word and disagrees on every quote, for that arm only",
              rows["a2"]["word_accuracy"] == 0.0 and rows["a2"]["words_compared"] == 15
              and rows["a2"]["quotes"][0]["model"] == "failed" and rows["a1"]["word_accuracy"] == 1.0)
        check("the failure is named, and completed-runs accuracy is reported beside the headline",
              rep["arms"]["a2"]["failed_runs"] == ["p/a r0: empty_response"]
              and rep["arms"]["a2"]["word_accuracy_completed_runs"] is None and not rep["not_scored"])
        results[1]["errors"][-1]["error"] = "auth_or_quota: weekly limit"
        (run / "results.json").write_text(json.dumps(results))
        P.score(SimpleNamespace(run=str(run), answers=str(td / "answers.json"), page=str(page), report=None))
        rep = json.loads((run / "score.json").read_text())
        check("an infrastructure failure removes the recording from EVERY arm, and says so",
              rep["per_run"] == [] and rep["arms"]["a2"]["excluded_infra"] == ["p/a r0: auth_or_quota"])
        # A top-up may replace an infrastructure failure, and nothing else.
        top = td / "top"
        top.mkdir()
        (top / "results.json").write_text(json.dumps([{**results[1], "outcome": "parsed", "turns": good, "errors": []}]))
        P.merge(SimpleNamespace(base=str(run), topup=str(top), out=str(td / "merged")))
        merged = json.loads((td / "merged" / "results.json").read_text())
        check("a top-up replaces an infrastructure failure and records what it replaced",
              merged[1]["outcome"] == "parsed" and merged[1]["topped_up_from"]["errors"][-1]["error"].startswith("auth_or_quota")
              and json.loads((td / "merged" / "manifest.json").read_text())["topups"][0]["replaced"])
        results[1]["errors"][-1]["error"] = "empty_response: z"
        (run / "results.json").write_text(json.dumps(results))
        try:
            P.merge(SimpleNamespace(base=str(run), topup=str(top), out=str(td / "merged2")))
            refused = False
        except SystemExit as exc:
            refused = "only those may be topped up" in str(exc)
        check("a top-up for a MODEL failure is refused: that failure is final", refused and not (td / "merged2").exists())
        (run / "results.json").write_text(json.dumps(results[:1]))
        P.score(SimpleNamespace(run=str(run), answers=str(td / "answers.json"), page=str(page), report=None))
        rep = json.loads((run / "score.json").read_text())
        check("a recording whose runs are not all in yet is scored for no arm",
              rep["per_run"] == [] and "a2 r0: not yet run" in rep["not_scored"][0]["reason"])

    print(f"\n{'FAILED ' + str(len(FAILED)) if FAILED else 'all passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
