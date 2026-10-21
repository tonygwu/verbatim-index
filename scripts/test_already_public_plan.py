#!/usr/bin/env python3
"""A plan excludes a prediction only when it states everything the prediction claims (release resolution-2026-10-21).

Operator decision of 2026-10-20 (ledger VD-24, BACKLOG VI-50): "Announcing that "X will happen" vs. announcing
"I/We have a current plan for X to happen" are two distinct facts. In general, we shouldn't conflate these two."
They chose the reading "Same outcome only": a plan still excludes a prediction that restates the plan's own
outcome, and never one that claims more. They approved the text below, with its five examples, word for word, and
release resolution-2026-10-20 appended it to ALREADY_PUBLIC_NOT_A_PRECURSOR, the block the resolver's rule 8 and
the early-call check's rule 7 share.

The same day the operator reversed the Sweeney ruling (VD-27): Epic's own 2025-01-24 post had already planned open
self-publishing "later this year", so Sweeney 5c16324b2d6126ea is already public, and the fourth example taught the
opposite. Their decision on the example (BACKLOG VI-56): "REmove the Sweeney example". Release
resolution-2026-10-21 removes that bullet and nothing else, so the block keeps the two rule sentences and four
examples. The five ruled rows (Ellison 94522ddc8049659a, Cook 897e1fe74a77f88c, Gelsinger 1e869ff2affb0357, Sweeney
5c16324b2d6126ea, Hastings 9df7d48a5a1e187a) are all operator-adjudicated, Sweeney included, so they stay out of any
measurement of the resolver's accuracy.

Offline checks:
  RULE      the approved text with its four remaining examples, word for word, closes the shared block, and both
            outcome prompts carry it inside their already-public rule
  REMOVED   the Sweeney example is in neither the block nor either outcome prompt, and putting its exact lines back
            gives release resolution-2026-10-20's block and prompts byte for byte, so nothing else moved
  LAYOUT    the block keeps its 3-space indent and its line width
  UNCHANGED every other part of the policy (prior, prior trend rule, lead test, labels, judged rules, leak
            words, schemas, the judged block) is byte-identical to releases resolution-2026-10-19 and
            resolution-2026-10-20, so no prior or lead test priced under them goes stale
  RELEASE   the release is resolution-2026-10-21, and KNOWN_RELEASES ends with it

  .venv/bin/python scripts/test_already_public_plan.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolution_lib as R  # noqa: E402

FAILED = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def flat(text: str) -> str:
    """Whitespace-normalized, because the prompt wraps lines."""
    return " ".join(text.split())


# The two rule sentences of the operator's approved text, verbatim from the decision of 2026-10-20.
RULE_SENTENCES = (
    'A plan, schedule or announcement makes a prediction already public only if it states everything the '
    'prediction claims: the same event, at least as large, by the same deadline or an earlier one, and against the '
    'same comparison. A schedule whose date passed before the statement, without the event, no longer counts: a new '
    'date given after a missed schedule is a forecast. Examples:\n')
# The four examples that remain, in order, verbatim from the same decision.
KEPT_EXAMPLES = (
    '- Not already public. Oracle\'s 2019-09-16 release planned 36 Oracle regions by the end of 2020. On 2020-06-16 '
    'Larry Ellison said "Soon we will have more regions live than AWS". The release names no AWS count, and Oracle '
    'could open all 36 while AWS opened 37.\n',
    '- Not already public. Bloomberg reported on 2020-06-09 that Apple would move the Mac to its own chips. On '
    '2020-06-22 Tim Cook said "we expect the transition to take about two years". The report gave no timetable, so '
    'the two years is a forecast.\n',
    '- Not already public. Intel\'s 2006-09-07 release said its vPro features would reach laptops in 2007. On '
    '2006-09-27 Pat Gelsinger said this would happen in the first half of 2007. A narrower window than the '
    'announcement is a forecast, even when the announcement makes it likely.\n',
    '- Already public. Netflix announced on 2019-08-27 that The Two Popes would open in theaters on November 27. On '
    '2019-09-20 Reed Hastings said it was "coming out this fall". The announcement states everything he claimed, at '
    'a more precise date.\n')
APPROVED = RULE_SENTENCES + "".join(KEPT_EXAMPLES)

# The removed example, byte for byte as release resolution-2026-10-20 laid it out, and where it stood: right
# before the Netflix example.
REMOVED = ("   - Not already public. Epic said on 2024-03-20 that its mobile store would\n"
           "     launch later that year with self-publishing tools. That year ended without\n"
           "     open self-publishing. On 2025-04-02 Tim Sweeney said developers could submit\n"
           "     their games directly by the end of 2025. That is a new date after a missed\n"
           "     schedule.\n")
AFTER_REMOVED = "   - Already public. Netflix"

# Hashes of release resolution-2026-10-20 (POLICY_RELEASE sha 9f1fe156...), taken on 2026-10-21 before the
# example was removed.
BLOCK_SHA_1020 = "0793a743bdb79ffe894be4ac865c0315e7e4c306fe67626f3f97b6db0ba7c80d"
RESOLVER_TASK_SHA_1020 = "5ac024dcf49047c39e26853108ddeec79222357ed5cfd3aba837438b099549c1"
EARLY_TASK_SHA_1020 = "01a7768ed88ec699d11e16a61f451a275ddee24c53621032d56cbf24e70e568e"

# Hashes of the parts that must not move, taken on 2026-10-20 from release resolution-2026-10-19
# (POLICY_RELEASE sha 8709e712...) before the approved text was added; release resolution-2026-10-20 left them
# as they were, which the same values confirmed on 2026-10-21.
PRIOR_TASK_SHA = "4eec819170007dd9e5ef154e73ee02e508ec1b7383f56a6a71ab736cc7a2b1b9"
PRIOR_TREND_RULE_SHA = "f9315a8994a370f67981d5ea45e86903c2bacacad5d96fe1eef59d57ec8d06f7"
LEAD_TEST_TASK_SHA = "508d226b714fefeae926c5401b3101de9b676b325fb5ef12a84ad22e5212713a"
# Every part of the policy hash except the resolver and early-call tasks.
OTHER_PARTS_SHA = "e26e346833d1d3ec9dfee77d34d1478c99a53c65b689966a061c00f312f4a662"
# The prior prompt for the policy fixture, hashed on 2026-10-11 under release resolution-2026-09-30.
PRIOR_PROMPT_SHA_BEFORE = "4d1435e9dc22eb9795a046cf1176229d026466fbea9c24f8f1767ed0c8aa28c5"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def restored(text: str) -> str:
    """The text with the removed example put back where it stood, or '' when that place is not there once."""
    if text.count(AFTER_REMOVED) != 1:
        return ""
    return text.replace(AFTER_REMOVED, REMOVED + AFTER_REMOVED)


def rule_section(name: str) -> str:
    """The already-public rule of an outcome prompt, from its heading to the next rule."""
    text = getattr(R, name)
    at = text.find("ALREADY PUBLIC BEFORE IT WAS SAID")
    end = text.find("\n9. " if name == "RESOLVER_TASK" else "\n8. ", at)
    return text[at:end] if 0 <= at < end else ""


block = R.ALREADY_PUBLIC_NOT_A_PRECURSOR
print("the rule")
check("the shared block ends with the approved text and its four remaining examples, word for word",
      flat(block).endswith(flat(APPROVED)), flat(block)[-400:])
check("the two rule sentences before \"Examples:\" are unchanged",
      flat(RULE_SENTENCES) in flat(block), flat(block)[-1500:])
at = [flat(block).find(flat(x)) for x in KEPT_EXAMPLES]
check("each of the four remaining examples is present, in order", all(a >= 0 for a in at) and at == sorted(at), str(at))
check("each remaining example is its own bullet line in the block",
      all(f"\n   - {x}" in block for x in ("Not already public. Oracle's", "Not already public. Bloomberg",
                                          "Not already public. Intel's", "Already public. Netflix")), block[-1500:])
check("the block has exactly four example bullets", block.count("\n   - ") == 4, str(block.count("\n   - ")))
for name in ("RESOLVER_TASK", "EARLY_TASK"):
    check(f"{name} carries the approved text inside its already-public rule",
          flat(APPROVED) in flat(rule_section(name)), rule_section(name)[:400])
check("the approved text comes after the precursor rule's last sentence, which stays as it was",
      0 <= flat(block).find("does not establish a revised window.") < flat(block).find(flat(APPROVED)[:60]),
      block[-800:])

print("the Sweeney example is gone, and nothing else moved")
for words in ("Epic said on 2024-03-20", "Tim Sweeney", "That is a new date after a missed schedule"):
    check(f"neither the block nor an outcome prompt says {words!r}",
          all(words not in flat(t) for t in (block, R.RESOLVER_TASK, R.EARLY_TASK)))
check("the block with the removed example put back is release resolution-2026-10-20's block, byte for byte",
      sha(restored(block)) == BLOCK_SHA_1020, sha(restored(block)))
check("RESOLVER_TASK with it put back is release resolution-2026-10-20's, byte for byte",
      sha(restored(R.RESOLVER_TASK)) == RESOLVER_TASK_SHA_1020, sha(restored(R.RESOLVER_TASK)))
check("EARLY_TASK with it put back is release resolution-2026-10-20's, byte for byte",
      sha(restored(R.EARLY_TASK)) == EARLY_TASK_SHA_1020, sha(restored(R.EARLY_TASK)))

print("the layout")
lines = block.split("\n")
check("every line of the block keeps the 3-space indent", all(l.startswith("   ") for l in lines if l), repr(lines))
widest = max(len(l) for l in lines)
check("no line of the block is wider than the widest line it had before (83)", widest <= 83, str(widest))
check("the block still ends with a newline, so the next rule line starts clean", block.endswith("\n"))

print("everything else is unchanged")
check("PRIOR_TASK is byte-identical to releases resolution-2026-10-19 and -10-20", sha(R.PRIOR_TASK) == PRIOR_TASK_SHA,
      sha(R.PRIOR_TASK))
check("PRIOR_TREND_RULE is byte-identical to releases resolution-2026-10-19 and -10-20",
      sha(R.PRIOR_TREND_RULE) == PRIOR_TREND_RULE_SHA, sha(R.PRIOR_TREND_RULE))
check("LEAD_TEST_TASK is byte-identical to releases resolution-2026-10-19 and -10-20",
      sha(R.LEAD_TEST_TASK) == LEAD_TEST_TASK_SHA, sha(R.LEAD_TEST_TASK))
parts = {k: v for k, v in R._policy_parts().items() if k not in ("resolver_task", "early_task")}
other = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
check("every policy part but the resolver and early-call tasks is byte-identical to resolution-2026-10-20",
      other == OTHER_PARTS_SHA, other)
prior = R.build_prior_prompt(R._policy_fixture(), dt.date(2020, 12, 31))
check("the fixture's prior prompt is unchanged, so no existing prior turns stale",
      sha(prior) == PRIOR_PROMPT_SHA_BEFORE, sha(prior))
# A record that triggers the sequence rule, the one rule whose prior text depends on the release, so this check can
# fail: under resolution-2026-10-11 the same record's prior prompt lacks the rule.
seq = R._policy_fixture()
seq["source"]["quote"] = "We will open the developer center before the first kits ship."
d = dt.date(2020, 12, 31)
new_prior = R.build_prior_prompt(seq, d, release="resolution-2026-10-21")
check("a prior built under the new release equals one built under resolution-2026-10-20, sequence rule included",
      "A STATED SEQUENCE" in new_prior and new_prior == R.build_prior_prompt(seq, d, release="resolution-2026-10-20")
      and new_prior != R.build_prior_prompt(seq, d, release="resolution-2026-10-11"))
check("the rule's text is not in the prior or lead-test prompt",
      "Same outcome" not in prior and "Two Popes" not in prior and "Two Popes" not in R.LEAD_TEST_TASK)

print("the release")
check("the release is resolution-2026-10-21", R.POLICY_RELEASE[0] == "resolution-2026-10-21", str(R.POLICY_RELEASE))
check("KNOWN_RELEASES ends with it, and every earlier release stays known, so their sidecars still load",
      R.KNOWN_RELEASES == ("resolution-2026-09-30", "resolution-2026-10-11", "resolution-2026-10-19",
                           "resolution-2026-10-20", "resolution-2026-10-21"), str(R.KNOWN_RELEASES))
check("the release hash matches the texts", R.policy_release()[1] == R.POLICY_RELEASE[1],
      f"{R.policy_release()[1]} vs {R.POLICY_RELEASE[1]}")
check("the new release is not a pre-sequence release, so its priors keep the sequence rule",
      "resolution-2026-10-21" not in R.PRE_SEQUENCE_RELEASES, str(R.PRE_SEQUENCE_RELEASES))

print(f"\n{'OK' if not FAILED else 'FAILED'}: {len(FAILED)} failing check(s)")
sys.exit(1 if FAILED else 0)
