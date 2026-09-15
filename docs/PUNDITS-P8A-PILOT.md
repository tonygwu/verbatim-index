# P8a pilot grading, run 1 (2026-09-15)

**Outcome: no usable panel data.** 120 calls, 46 valid grades, and **0 of 20
recordings have the complete set of grades the plan requires** (every published
judge, both modes, run 0). The blocking finding is Astra, not quota.

Records: `data-pundits/grades/`, run log and quota snapshots in
`data-pundits/logs/p8a/`, schedule `data-pundits/logs/schedule/p8a_pilot.jsonl`.
Contract `3844dd2693acd471`, provenance `13f6dc20a49572e7`.

## What ran

20 recordings, 2 per pilot person, drawn with seed 20260914 from the verified
P6 set; 3 judges x 2 modes = 120 calls, 4 workers, median 82.8 s per call.

```
attempted 120   succeeded 46   invalid_schema 7   judge_refusals 38   failed 29
error_taxonomy: judge_declined_to_score 38, auth_or_quota 28,
                schema_validation_failed 7, cli_nonzero_exit 1
```

| Judge | Valid | Invalid or refused | Cause |
|---|---|---|---|
| Gemini | 33 of 40 | 6 schema, 1 CLI error | 25-word quote cap; one response returned `status: ERROR` carrying a well-formed body |
| Fable | 11 of 40 | 1 schema, 28 quota | session limit reached mid-run |
| Astra | 2 of 40 | 38 refusals | declines to score political content |

## Astra refuses this study by policy

38 of 40 calls returned a refusal, in 33 distinct wordings that all say the same
thing:

> "I can't assign scores to political content. I can provide a neutral, unscored
> analysis of the transcript..."

This is **not** the leaders-board refusal pattern. There, refusals were sampling
variance on a few politically charged transcripts, and a re-run graded two of
three (`AGENTS.md`, "Are the content refusals deterministic?"). Here the refusal
is the response to the task itself: score a political commentator. Retrying the
same prompt on the same model is not expected to help.

The two that succeeded are the same recording in both modes,
`steven-bonnell/destiny-ev6sjw` (a debate with an evangelist, blinded 59.6, open
59.8). One recording is not evidence about which content Astra will accept.

## Fable stopped on quota, not on the harness

28 failures, all `auth_or_quota`, detail "You've hit your session limit · resets
7:20pm (America/Los_Angeles)". Measured before and after the run:

```
account A   5h 74% -> 0%    fable 40% -> 13%
claude_d    5h 87% -> 68%   fable 98% -> 95%
```

Fable's 11 valid grades carry no harness errors: no tool attempt, no missing
session transcript. Re-running the 28 after the reset is straightforward.

## Gemini worked, and its identity checks pass

Read in full on `ben-shapiro/ben-shapiro-ukzort__gemini__blinded__r0.json`:
`served_model` equals `requested_model` (`gemini-3.8-flash-high`),
`served_model_verified: true`, harness `agy -p`, profile identity recorded
(gptwufamily@gmail.com, all 39 calls). Across all valid grades: **zero tool use
and zero web searches**, so the P10 G-search exposure is 0 so far.

## Blinding does not hold, as on the leaders board

**25 of 25 blinded grades named a person, every one marked confident**, and the
names read correctly: Ben Shapiro, Ezra Klein, Coleman Hughes, Steven Bonnell
(Destiny), Matt Walsh. This repeats the leaders finding: redaction removes the
nouns, not the argument. It is a known limit, to be disclosed on the site, not a
defect introduced here.

## Coverage after run 1

19 of 20 recordings have at least one valid grade; the best have 4 of 6 cells.

```
cells per recording: 4 cells x4 recordings, 3 cells x3, 2 cells x9, 1 cell x3, 0 cells x1
```

Under the plan's eligibility rule (complete run-0 grades from every published
judge in both modes) **nothing is eligible**, so no score, calibration, halo or
gate can be computed from run 1.

## Decisions this forces

Astra cannot be fixed by retrying, so the panel composition is now a decision
for the operator. The plan's prespecified judge-drop rule applies: the study
becomes the remaining judges for every transcript, calibration refits from
scratch, no transcript keeps a partial panel, and **publishing with two judges
needs explicit approval**.
