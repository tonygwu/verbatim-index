# P4d: Fable's unusable-answer rate with every tool removed

Run `20260914T080522Z-e36099`, 2026-09-14, account `~/.claude-e`, seed 20260914.
Raw records, verdicts and quota before and after are in the private data
repository at `logs/p4d_tools_off/20260914T080522Z-e36099/` (commit `0ea6616`).
Tool: `scripts/p4d_fable_tools_off.py`.

## Answer

No call in 12 returned an unusable answer. The 95% Clopper-Pearson interval on
the rate is [0, 26.5%], so this run rules out a gross failure and does NOT show
that the rate is low. It cannot show the rate stays under the P8 retry cap of
15%, because the upper bound is above that cap.

## What ran

Each call was the exact pundits Fable harness: `grade.call_fable` under
`sandbox-exec`, with `--tools ""` and the session-transcript tool audit. The
prompt was the leaders grading prompt, because the pundits rubric did not exist
when the run was designed. The transcripts were a seeded sample of leaders
blinded transcripts, 6 under 10k words and 6 from 10k to 30k words. No grade
entered any corpus.

```
attempted 12   valid 12   schema_invalid 0   no_json 0   tool_attempt 0   infra 0
unusable rate 0/12 = 0.0   ci95 [0.0, 0.2646]   fake tool text in an answer: 0
under_10k   6/6 valid   ci95 [0.0, 0.4593]
10k_30k     6/6 valid   ci95 [0.0, 0.4593]
reference: 1 of 702 leaders Fable grades on disk failed validation (0.14%)
```

## What this does and does not settle

- The P3 probe saw Fable write a fake tool call as text once. On grading-size
  prompts that did not happen in 12 calls, and the transcript audit found 0
  tool calls.
- 12 calls cannot separate a rate of 0.14% from a rate of 20%. The question
  is not closed. P8a runs 80 Fable production cells on pundits transcripts
  under the same harness, and its G-refusal gate counts unusable answers with a
  prespecified bound. That gate, not this run, decides whether the harness is
  fit for the full run.
- The prompt was the leaders prompt. The pundits prompt has a different rubric
  and schema, so a schema-validity rate on it may differ.
- No transcript over 30k words was tested. Pundit transcripts run to 180
  minutes, about 30k words, so the longest ones are at the edge of this sample.
