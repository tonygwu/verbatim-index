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


GOOD = {"subject_present": True, "main_speaker": True, "venue": "guest_interview", "political_content": True,
        "confidence": "high", "reason": "The host welcomes her by name.", "evidence": ["welcome Ana"]}


def main() -> int:
    print("pundits speaker inference")
    import pundits_speaker_infer as S

    print("\n[PARSE]")
    check("a well-formed answer parses, even wrapped in prose",
          S.parse_answer("Here:\n" + json.dumps(GOOD))["venue"] == "guest_interview")
    for label, bad in (("a non-boolean", {**GOOD, "main_speaker": "yes"}), ("an unknown venue", {**GOOD, "venue": "host_interview"}),
                       ("an unknown confidence", {**GOOD, "confidence": "sure"}), ("an empty reason", {**GOOD, "reason": " "})):
        check(f"{label} is refused", refused(lambda b=bad: S.parse_answer(json.dumps(b))))
    check("no JSON is refused", refused(lambda: S.parse_answer("I think she is present.")))
    check("an answer without a true/false political_content is refused (operator topic rule, 2026-09-15)",
          refused(lambda: S.parse_answer(json.dumps({k: v for k, v in GOOD.items() if k != "political_content"}))))
    check("the drafting instructions ask the political-content question", "political_content" in S.RULES)

    print("\n[MERGE]")
    human = {"p/a": {"subject_present": False, "venue": "other", "political_content": True, "checked_by": "operator"}}
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
    human = {"subject_present": True, "main_speaker": True, "venue": "panel_show"}
    check("a venue disagreement with the operator is queued", any("venue" in w for w in S.needs_review(d, human)))

    print("\n[VENUE]")
    absent = {"subject_present": False, "main_speaker": False, "venue": "other"}
    draft_absent = {**d, "subject_present": False, "main_speaker": False, "venue": "hosted_interview"}
    check("a venue disagreement on a row the operator marked absent is ignored",
          not any("venue" in w for w in S.needs_review(draft_absent, absent)))

    print("\n[CALIBRATE]")
    drafts = {"a": d, "b": {**d, "venue": "debate"}, "c": draft_absent, "e": {"error": "x"}}
    humans = {"a": {"subject_present": True, "main_speaker": True, "venue": "guest_interview"},
              "b": {"subject_present": True, "main_speaker": True, "venue": "guest_interview"},
              "c": absent, "e": absent}
    cal = S.calibration(drafts, humans)
    check("rows with an error are not compared", cal["rows_compared"] == 3, str(cal))
    check("presence agreement counts every compared row", cal["subject_present"] == {"agree": 3, "of": 3}, str(cal))
    check("venue agreement counts only rows where the subject is present", cal["venue"] == {"agree": 1, "of": 2}, str(cal))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
