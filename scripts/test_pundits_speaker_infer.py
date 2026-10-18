#!/usr/bin/env python3
"""Model-drafted speaker labels are parsed strictly, calibrated against the operator, and doubtful rows are queued.

Pundits plan, P6.

  PARSE      a well-formed answer parses; a non-boolean, an unknown venue, an
             unknown confidence, an empty reason, or no JSON is refused
  QUEUE      medium or low confidence, an absent subject, a non-main speaker,
             no usable answer, and any disagreement with the operator are queued;
             a confident present-and-main draft with no human label is not
  VENUE      a venue disagreement on a row the operator marked absent is ignored
  CALIBRATE  agreement is counted per field, venue only where the subject is present
  UNLABELLED a field the operator did not label is neither queued nor counted, and a label
             saved with the draft on screen (draft_shown) is left out of calibration
  SETS       a P6b row is its position in the checklist file; a pilot row is its key table's
  CREDIT     a credit draft asks for Fable at effort max, and each attempt keeps its own raw
             file and request id, counting a legacy `<sid>.json` as attempt 1
  DRIVER     an answer that does not parse keeps its telemetry; once one call finds the pools
             exhausted, later rows are skipped and written nowhere; any error or skip exits 1

No quota.

  .venv/bin/python scripts/test_pundits_speaker_infer.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


def refused(fn) -> bool:
    try:
        fn()
    except (ValueError, json.JSONDecodeError):
        return True
    return False


GOOD = {"subject_present": True, "main_speaker": True, "venue": "conversation", "political_content": True,
        "confidence": "high", "reason": "The host welcomes her by name.", "evidence": ["welcome Ana"]}


def main() -> int:
    print("pundits speaker inference")
    import pundits_speaker_infer as S

    print("\n[PARSE]")
    check("a well-formed answer parses, even wrapped in prose",
          S.parse_answer("Here:\n" + json.dumps(GOOD))["venue"] == "conversation")
    for label, bad in (("a non-boolean", {**GOOD, "main_speaker": "yes"}), ("an unknown venue", {**GOOD, "venue": "host_interview"}),
                       ("an unknown confidence", {**GOOD, "confidence": "sure"}), ("an empty reason", {**GOOD, "reason": " "})):
        check(f"{label} is refused", refused(lambda b=bad: S.parse_answer(json.dumps(b))))
    check("no JSON is refused", refused(lambda: S.parse_answer("I think she is present.")))
    check("an answer without a true/false political_content is refused (operator topic rule, 2026-09-15)",
          refused(lambda: S.parse_answer(json.dumps({k: v for k, v in GOOD.items() if k != "political_content"}))))
    check("the drafting instructions ask the political-content question", "political_content" in S.RULES)

    print("\n[MERGE]")
    human = {"p/a": {"subject_present": False, "venue": "conversation", "political_content": True, "checked_by": "operator"}}
    drafts = {"p/a": {**GOOD, "key": "p/a"}, "p/b": {**GOOD, "key": "p/b", "political_content": False},
              "p/c": {"key": "p/c", "error": "cli exit 1"}}
    merged, rep = S.merge_drafts(drafts, human, "claude-sonnet-5")
    check("a human label is never overwritten by a draft", merged["p/a"] == human["p/a"], str(merged.get("p/a")))
    check("an unlabelled row takes the draft's presence, venue and political content, marked as model-drafted",
          merged["p/b"]["political_content"] is False and merged["p/b"]["drafted_by_model"] is True
          and merged["p/b"]["checked_by"] == "model:claude-sonnet-5" and "main_speaker" not in merged["p/b"], str(merged.get("p/b")))
    check("a draft with an error is not merged and is reported",
          "p/c" not in merged and rep["skipped_errors"] == ["p/c"] and rep["merged_from_model"] == 1, str(rep))
    check("an answer followed by more text or a second object still parses (seen live on rows 52, 96, 101)",
          not refused(lambda: S.parse_answer(json.dumps(GOOD) + "\n{\"note\": \"extra\"}"))
          and not refused(lambda: S.parse_answer(json.dumps(GOOD) + " Hope that helps {:)}")))

    print("\n[HOST-RULE]")
    guide = (REPO / "docs" / "PUNDITS-LABELLING-GUIDE.md").read_text()
    phrase = "runs the conversation counts as the main speaker"
    check("the drafting instructions count a host who runs the conversation as main speaker (operator, 2026-09-15)",
          phrase in S.RULES.replace("\n   ", " "))
    # The guide no longer asks people about main speaker (operator, 2026-09-15); presence
    # is the human label, so the guide must define presence as "enough to be worth grading".
    check("the labelling guide defines presence as enough of the subject to be worth grading",
          "enough that grading this recording says something about them" in guide.replace("\n", " "))

    print("\n[COMMAND]")
    cmd = S.draft_command("PROMPT", "sonnet")
    check("the sonnet command requests claude-sonnet-5 and no Fable model",
          cmd[cmd.index("--model") + 1] == "claude-sonnet-5" and not any("fable" in c for c in cmd), str(cmd))
    check("tools are removed and permissions denied",
          cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--permission-prompts") + 1] == "none")
    check("the binary is raw claude, never cl", cmd[0] == "claude")
    fcmd = S.draft_command("PROMPT", "fable")
    check("the fable command keeps max effort", fcmd[fcmd.index("--model") + 1] == "claude-fable-5-1" and "--effort" in fcmd)

    print("\n[QUEUE]")
    d = dict(GOOD)
    check("a confident present-and-main draft with no human label is not queued", S.needs_review(d, None) == [])
    check("medium confidence is queued", S.needs_review({**d, "confidence": "medium"}, None) != [])
    check("an absent subject is queued", S.needs_review({**d, "subject_present": False, "main_speaker": False}, None) != [])
    check("a non-main speaker is queued", S.needs_review({**d, "main_speaker": False}, None) != [])
    check("no usable answer is queued", S.needs_review({"error": "x"}, None) != [])
    human = {"subject_present": True, "main_speaker": True, "venue": "debate"}
    check("a venue disagreement with the operator is queued", any("venue" in w for w in S.needs_review(d, human)))

    print("\n[VENUE]")
    absent = {"subject_present": False, "main_speaker": False, "venue": "solo"}
    draft_absent = {**d, "subject_present": False, "main_speaker": False, "venue": "conversation"}
    check("a venue disagreement on a row the operator marked absent is ignored",
          not any("venue" in w for w in S.needs_review(draft_absent, absent)))

    print("\n[CALIBRATE]")
    drafts = {"a": d, "b": {**d, "venue": "debate"}, "c": draft_absent, "e": {"error": "x"}}
    humans = {"a": {"subject_present": True, "main_speaker": True, "venue": "conversation"},
              "b": {"subject_present": True, "main_speaker": True, "venue": "conversation"},
              "c": absent, "e": absent}
    cal = S.calibration(drafts, humans)
    check("rows with an error are not compared", cal["rows_compared"] == 3, str(cal))
    check("presence agreement counts every compared row", cal["subject_present"] == {"agree": 3, "of": 3}, str(cal))
    check("venue agreement counts only rows where the subject is present", cal["venue"] == {"agree": 1, "of": 2}, str(cal))

    print("\n[UNLABELLED]")
    # P6b labels carry no main_speaker: the guide stopped asking on 2026-09-15.
    p6b_human = {"subject_present": True, "venue": "conversation", "political_content": True, "checked_by": "operator"}
    check("a field the person never labelled is not a disagreement",
          not any("main_speaker" in w for w in S.needs_review({**d, "main_speaker": False}, p6b_human)),
          str(S.needs_review({**d, "main_speaker": False}, p6b_human)))
    check("a labelled field still disagrees", any("venue" in w for w in S.needs_review({**d, "venue": "solo"}, p6b_human)))
    try:
        cal6 = S.calibration({"a": d, "b": {**d, "subject_present": False}}, {"a": p6b_human, "b": p6b_human})
        check("calibration counts main_speaker only where a person labelled it",
              cal6["main_speaker"] == {"agree": 0, "of": 0} and cal6["subject_present"] == {"agree": 1, "of": 2}
              and cal6["high_confidence"] == {"rows": 2, "all_three_agree": 1}, str(cal6))
    except KeyError as exc:
        check("calibration counts main_speaker only where a person labelled it", False, f"KeyError {exc}")

    cal7 = S.calibration({"a": d, "b": d}, {"a": p6b_human, "b": {**p6b_human, "draft_shown": "claude-fable-5-1"}})
    check("a label made with the draft on screen is left out of calibration, and counted",
          cal7["rows_compared"] == 1 and cal7["assisted_labels_left_out"] == 1
          and cal7["subject_present"] == {"agree": 1, "of": 1}, str(cal7))

    print("\n[SETS]")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "human_checklist.json").write_text(json.dumps({"z/last-first": {}, "a/second": {}, "m/third": {}}))
        check("a P6b row is its position in the checklist file, from 1",
              S.load_keys(root, "p6b") == {1: "z/last-first", 2: "a/second", 3: "m/third"}, str(S.load_keys(root, "p6b")))
        (root / "checklist_table_keys.json").write_text(json.dumps({"7": "p/x", "2": "p/y"}))
        check("a pilot row comes from its own key table", S.load_keys(root, "pilot") == {7: "p/x", 2: "p/y"})
    check("the two sets, and only those, each name a root and a manifest",
          all(set(v) == {"root", "manifest"} for v in S.SETS.values()) and set(S.SETS) == {"pilot", "p6b"})

    print("\n[CREDIT]")
    import credit_run
    calls = []
    real_run = credit_run.run
    credit_run.run = lambda prompt, **kw: calls.append(kw) or ("TEXT", {"harness": "quotapick run"})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            pools = ["anthropic_api_e", "anthropic_api_b"]
            S.call_credit("P", "andrew-yang/podcast-abc", "p6b", pools, raw, None)
            kw = calls[-1]
            check("a credit draft asks for Fable at effort max on the named pools, at most 1800 s",
                  kw["model"] == "claude-fable-5-1" and kw["effort"] == "max" and kw["pools"] == pools
                  and kw["timeout_s"] == 1800 and kw["expected_cost_usd"] == S.CREDIT_EXPECTED_COST_USD, str(kw))
            check("the first attempt is numbered 1 in its raw file and its request id",
                  kw["raw_path"] == raw / "andrew-yang" / "podcast-abc.1.json"
                  and kw["request_id"] == "speaker-p6b-andrew-yang/podcast-abc-1", str(kw))
            d = raw / "andrew-yang"
            d.mkdir()
            (d / "podcast-abc.json").write_text("{}")
            (d / "podcast-abcd.4.json").write_text("{}")
            (d / "podcast-abc.notes.json").write_text("{}")
            check("a legacy `<sid>.json` counts as attempt 1, and another recording's files count for nothing",
                  S.next_attempt(raw, "andrew-yang/podcast-abc") == 2, str(S.next_attempt(raw, "andrew-yang/podcast-abc")))
            (d / "podcast-abc.2.json").write_text("{}")
            (d / "podcast-abc.3.json").write_text("{}")
            S.call_credit("P", "andrew-yang/podcast-abc", "p6b", pools, raw, None)
            check("a retry never reuses a kept file", calls[-1]["raw_path"].name == "podcast-abc.4.json"
                  and calls[-1]["request_id"].endswith("-4"), str(calls[-1]))
    finally:
        credit_run.run = real_run

    print("\n[DRIVER]")
    tel = {"harness": "quotapick run", "credit_pool": "anthropic_api_e", "cost_usd": 0.4}
    entry, outcome = S.draft_row(5, "p/x", "fable", lambda: ("not json at all", tel))
    check("an answer that does not parse keeps its telemetry, so its cost and pool are on record",
          outcome.startswith("error:") and entry.get("telemetry") == tel and "error" in entry, f"{outcome} {entry}")
    entry, outcome = S.draft_row(5, "p/x", "fable", lambda: (json.dumps(GOOD), tel))
    check("a good answer is drafted with its telemetry", outcome == "drafted" and entry["telemetry"] == tel
          and entry["venue"] == GOOD["venue"], f"{outcome} {entry}")

    def boom():
        raise credit_run.PoolsExhausted("no_candidate: attempts []")
    entry, outcome = S.draft_row(5, "p/x", "fable", boom)
    check("an exhausted call is labelled PoolsExhausted", outcome.startswith("error:PoolsExhausted:"), outcome)

    made, written = [], []

    def draft(n):
        made.append(n)
        if n == 2:
            return {"row": n, "key": f"p/{n}", "error": "PoolsExhausted: x"}, "error:PoolsExhausted:no_candidate"
        return {"row": n, "key": f"p/{n}"}, "drafted"
    tally = S.run_rows([1, 2, 3, 4], draft, written.append, workers=1)
    check("after the pools run out no further call is made, and the skipped rows are written nowhere",
          made == [1, 2] and [e["row"] for e in written] == [1, 2]
          and tally == {"drafted": 1, "error:PoolsExhausted:no_candidate": 1, "skipped:pools_exhausted": 2}, f"{made} {tally}")
    check("a run with a failed row exits 1", S.exit_code(tally) == 1)
    check("a run with a skipped row and no failure exits 1, so a partial run never reads as done",
          S.exit_code({"drafted": 3, "skipped:pools_exhausted": 1}) == 1)
    check("a run where every row was drafted exits 0", S.exit_code(S.run_rows([1, 3], draft, [].append, 2)) == 0)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
