#!/usr/bin/env python3
"""speaker_turns.py: the Astra "who spoke" step and its check-only report.

Spends no quota: the Astra call and the quota router are fakes. Proves the prompt is
pinned to the measured one; that "new" is read from fetched_at_utc and never from a
file's mtime; that the call is Astra, sandboxed, on the router's account; that a
second model failure is written as final while an infrastructure failure writes
nothing so the next cycle retries it; and that the check flags a published
prediction, a judge's evidence quote and a judge's share that Astra's turns
contradict, while leaving agreeing ones alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import speaker_turns as T  # noqa: E402

FAILED = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


# word 0 timestamp, 1..5 host, 6..15 subject, 16 timestamp, 17..20 host
TEXT = ("[00:00:01] so tell us more please "
        "well I think the answer is clearly more power sooner "
        "[00:00:09] thanks that was great")
GOOD = json.dumps({"turns": [{"marker": 0, "first_words": "so tell us more", "speaker": "other", "who": "host"},
                             {"marker": 0, "first_words": "well I think the answer", "speaker": "subject"},
                             {"marker": 10, "first_words": "thanks that was great", "speaker": "other"}]})
ROUTE = {"harness": "astra", "account_id": "codex_b", "config_dir": "/fake/codex-b"}


class Router:
    def __init__(self, fail=False):
        self.fail = fail

    def pick(self, pin, exclude):
        assert pin == "astra", pin
        if self.fail:
            class RouterUnavailable(RuntimeError):
                pass
            raise RouterUnavailable("router_unavailable: every codex account measured out of quota")
        return ROUTE


def make_data(root: Path, fetched="2026-09-29T10:00:00Z") -> Path:
    (root / "roster").mkdir(parents=True)
    (root / "roster" / "final.json").write_text(json.dumps({"roster": [{"slug": "jane-roe", "name": "Jane Roe",
                                                                       "role": "CEO"}]}))
    d = root / "transcripts_open" / "jane-roe"
    d.mkdir(parents=True)
    rec = {"leader_slug": "jane-roe", "source_id": "talk-1", "text": TEXT, "yt_title": "Talk"}
    if fetched:
        rec["fetched_at_utc"] = fetched
    (d / "talk-1.json").write_text(json.dumps(rec))
    return root


def fake_call(responses, seen):
    """A stand-in for grade.call_astra that returns or raises each response in turn."""
    it = iter(responses)

    def call(prompt, timeout, workdir, model, raw_response_path, wrapper, config_dir):
        seen.append({"model": model, "wrapper": wrapper, "config_dir": config_dir, "prompt": prompt})
        r = next(it)
        if isinstance(r, BaseException):
            raise r
        return r, {"served_model": model, "reasoning_output_tokens": 10}
    return call


def run_one(root, responses, router=None):
    seen = []
    row = T.segment_one(root, "jane-roe/talk-1", {"name": "Jane Roe", "role": "CEO"}, router or Router(),
                        root / "work", fake_call(responses, seen))
    out = T.turns_path(root, "jane-roe/talk-1")
    return row, (json.loads(out.read_text()) if out.exists() else None), seen


def main() -> int:
    print("[PIN]")
    check("the prompt is the one measured on 2026-09-28", T.sha(T.PROMPT) == T.PROMPT_TEMPLATE_SHA256)
    saved = T.PROMPT
    T.PROMPT = saved + " "
    try:
        T.assert_prompt_pinned()
        refused = False
    except SystemExit as exc:
        refused = "unmeasured segmenter" in str(exc)
    T.PROMPT = saved
    check("a changed prompt refuses to run", refused)
    import speaker_segment_probe as P
    check("the experiment and the step share one prompt and one parser", P.PROMPT is T.PROMPT and P.resolve is T.resolve)

    print("\n[SELECT]")
    with tempfile.TemporaryDirectory() as td:
        root = make_data(Path(td), fetched="2026-09-11T04:49:05Z")
        f = root / "transcripts_open" / "jane-roe" / "talk-1.json"
        future = 4102444800  # 2100-01-01: a touched file must not look new
        os.utime(f, (future, future))
        todo, skipped = T.select(root, T.SEGMENT_SINCE_UTC)
        check("a transcript fetched before the cutoff is not segmented, however recently its file was touched",
              todo == [] and skipped["before_cutoff"] == 1)
    with tempfile.TemporaryDirectory() as td:
        root = make_data(Path(td), fetched=None)
        todo, skipped = T.select(root, T.SEGMENT_SINCE_UTC)
        check("a transcript with no fetched_at_utc is refused and named, never dated by mtime",
              todo == [] and skipped["missing_fetched_at"] == ["jane-roe/talk-1"])
    with tempfile.TemporaryDirectory() as td:
        root = make_data(Path(td))
        check("a new transcript is selected", T.select(root, T.SEGMENT_SINCE_UTC)[0] == ["jane-roe/talk-1"])

        print("\n[SEGMENT]")
        row, rec, seen = run_one(root, [GOOD])
        check("the call is Astra at the pinned model, on the router's account, inside the sandbox",
              seen[0]["model"] == "gpt-6-astra" and seen[0]["config_dir"] == "/fake/codex-b"
              and seen[0]["wrapper"][:2] == ["sandbox-exec", "-p"] and str(T.DENIED_ROOT) in seen[0]["wrapper"][2])
        check("a good answer is stored with its turns, ranges, share and provenance",
              rec["status"] == "ok" and [r["start"] for r in rec["ranges"]] == [1, 6, 17]
              and rec["subject_share_pct"] == round(100 * 10 / 19, 1) and rec["account_id"] == "codex_b"
              and rec["prompt_template_sha256"] == T.PROMPT_TEMPLATE_SHA256 and rec["text_sha256"] == T.sha(TEXT))
        check("a segmented transcript is not selected again", T.select(root, T.SEGMENT_SINCE_UTC)[0] == [])
        f = root / "transcripts_open" / "jane-roe" / "talk-1.json"
        r = json.loads(f.read_text())
        f.write_text(json.dumps({**r, "text": TEXT + " again"}))
        check("a transcript whose text changed under its turns is selected again",
              T.select(root, T.SEGMENT_SINCE_UTC)[0] == ["jane-roe/talk-1"])
        f.write_text(json.dumps(r))

        row, rec, _ = run_one(root, ["not json at all", GOOD])
        check("an unparseable first answer is retried once", rec["status"] == "ok" and rec["attempts"] == 2
              and rec["errors"][0]["label"] == "unparseable")
        T.turns_path(root, "jane-roe/talk-1").unlink()
        row, rec, _ = run_one(root, [RuntimeError("empty_response: nothing"), RuntimeError("empty_response: again")])
        check("a second model failure is final and written, with its label",
              rec["status"] == "failed" and rec["failure"] == "empty_response" and row["outcome"] == "failed")
        T.turns_path(root, "jane-roe/talk-1").unlink()
        row, rec, _ = run_one(root, [subprocess.TimeoutExpired("codex", 2400), subprocess.TimeoutExpired("codex", 2400)])
        check("a timeout is labelled cli_timeout", rec["failure"] == "cli_timeout")
        T.turns_path(root, "jane-roe/talk-1").unlink()
        row, rec, _ = run_one(root, [RuntimeError("auth_or_quota: weekly limit"), RuntimeError("auth_or_quota: weekly limit")])
        check("an exhausted quota writes nothing, so the next cycle retries it",
              rec is None and row["outcome"] == "infra_retry_next_cycle")
        row, rec, _ = run_one(root, [], router=Router(fail=True))
        check("a router that refuses every account writes nothing either",
              rec is None and row["label"] == "router_unavailable")

        print("\n[CHECK]")
        run_one(root, [GOOD])
        g = root / "grades"
        for judge, share, quote in (("fable", 50, "well I think the answer is clearly"),
                                    ("gemini", 95, "so tell us more please")):
            (g / judge / "jane-roe").mkdir(parents=True)
            (g / judge / "jane-roe" / f"talk-1__{judge}__blinded__r0.json").write_text(json.dumps({
                "judge": judge, "validation_errors": [], "grade": {"subject_speech_share_pct": share,
                "dimensions": {"d1_clarity": {"evidence": [{"quote": quote}]}}}}))
        q_host, q_subj = "thanks that was great", "more power sooner"
        preds = [{"prediction_id": "p-host", "accepted": True, "source": {
                      "quote": q_host, "quote_original": q_host, "quote_char_start": TEXT.index(q_host),
                      "quote_char_end": TEXT.index(q_host) + len(q_host)}},
                 {"prediction_id": "p-subj", "accepted": True, "source": {
                      "quote": q_subj, "quote_original": q_subj, "quote_char_start": TEXT.index(q_subj),
                      "quote_char_end": TEXT.index(q_subj) + len(q_subj)}},
                 {"prediction_id": "p-rejected", "accepted": False, "source": {
                      "quote": q_host, "quote_original": q_host, "quote_char_start": TEXT.index(q_host),
                      "quote_char_end": TEXT.index(q_host) + len(q_host)}}]
        (root / "predictions" / "jane-roe").mkdir(parents=True)
        (root / "predictions" / "jane-roe" / "talk-1.jsonl").write_text("\n".join(json.dumps(p) for p in preds) + "\n")
        T.check(SimpleNamespace(data=str(root), out=str(root / "report.json")))
        rep = json.loads((root / "report.json").read_text())
        fl = rep["flags"]
        check("a published prediction Astra gives to the host is flagged; the subject's and the rejected one are not",
              [x["prediction_id"] for x in fl["prediction_quotes"]] == ["p-host"]
              and rep["checked"]["prediction_quotes"] == 2)
        check("a judge's evidence quote Astra gives to the host is flagged; the subject's is not",
              [(x["judge"], x["astra_says"]) for x in fl["evidence_quotes"]] == [("gemini", "other")])
        check("a judge whose share sits the gap or more from Astra's is flagged; a close one is not",
              [x["judge"] for x in fl["share_dissent"]] == ["gemini"])
        f.write_text(json.dumps({**r, "text": TEXT + " again"}))
        T.check(SimpleNamespace(data=str(root), out=str(root / "report.json")))
        rep = json.loads((root / "report.json").read_text())
        check("turns whose transcript changed are reported stale and checked for nothing",
              rep["stale"] == ["jane-roe/talk-1"] and rep["segmented"] == 0)

    print("\n[LOOP]")
    loop = (Path(__file__).resolve().parent / "grade_loop.sh").read_text()
    stage = loop[loop.index("# 6. Who spoke"):loop.index("g1=$(count_grades)")]
    check("grade_loop.sh runs segment then check, for leaders only, after the render",
          'if [ "$STUDY" = "leaders" ]' in stage and "speaker_turns.py segment" in stage
          and "speaker_turns.py check" in stage and loop.index("# 6. Who spoke") > loop.index("leaderboard re-rendered"))
    check("each half names its own failure, and neither can stop the loop",
          "SPEAKER SEGMENT FAILED" in stage and "SPEAKER CHECK FAILED" in stage and "exit" not in stage)

    print(f"\n{'FAILED ' + str(len(FAILED)) if FAILED else 'all passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
