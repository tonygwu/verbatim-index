# Verbatim Predictions, V0

Verbatim Predictions turns the transcript corpus behind the Verbatim Index into
a corpus of predictions: statements a named leader made in public that a
stranger could later check. Every record keeps the exact span of the transcript
it came from, so a reader can audit the cut without re-running anything.

V0 ends at a trustworthy corpus and a page to inspect it. It does not resolve
outcomes, does not score, and does not rank anyone. Those are Phase 2.

Live page: `verbatim-predictions.tonygwu.com`. Records: `data/predictions/`.
Skill and contracts: `.claude/skills/prediction-extractor/`.

## 1. What counts as a prediction

A candidate must pass five gates, judged twice by two different model families.

| Gate | Passes | Fails |
|---|---|---|
| Forward-looking | a state of the world after the moment of speaking | present tense, "our vision is", history |
| Falsifiable | the model can write "By <date or event>, <observable> will / will not <threshold>" | confident grammar with no test: "we will be the most transparent company in the world" |
| Committed | will, expect, I think X will, probably, likely, I'd bet | might, could, maybe, conditionals, questions, jokes |
| Own voice | the subject's own claim | agreeing with the interviewer, quoting others, disowned claims, sarcasm |
| Stands alone | intelligible with nothing around it, 8 to 60 words | dangling pronouns, fragments |

The falsifiability gate is generative on purpose. The model must write the
resolution criterion. If it cannot, the statement fails, whatever its grammar.
This closes the failure that dominated the 2026-09-09 probe, where 45% of
"qualifying" statements were confident sentences with no observable test.

Company roadmap and guidance ("we will ship X by June", "revenue will pass 2
billion this year") are extracted when a third party can observe the outcome
and tagged `subject_control: own`, so a reader can set them aside. A personal
intention with no external observable is not extracted.

The full definitions, with the negative list and filled examples, are in
`EXTRACTION.md`. That file, with its output schema, is hashed into every record
as the extraction contract. Editing it changes the id, the same way the
grader's rubric works.

## 2. Architecture

```
data/transcripts_open/<slug>/<sid>.json
        |
        v
  extract_predictions.py --stage extract      one model per transcript, chosen by the quota router
        |   full transcript -> candidates that pass five gates; every quote grounded mechanically
        v
  extract_predictions.py --stage verify       a DIFFERENT model family, 400-word window per candidate
        |   re-judges gates, attribution and claim fidelity; writes its own criterion
        v
  data/predictions/<slug>/<sid>.jsonl         one candidate per line; accepted = both agreed
        |
        v
  market_consensus.py                         accepted records only; Polymarket and Kalshi via public APIs
        |   a model judges match only; the price is read from history strictly before publication
        v
  aggregate_predictions.py -> index.json      descriptive counts, no evaluative field
        |
        v
  build_predictions_site.py -> site-predictions/index.html -> deploy_predictions.sh

  Phase 2, not built:  resolution -> consensus comparison -> scoring -> forecasting leaderboard
```

Stages are separate scripts with separate contracts. Extraction and
verification never see a market or an outcome. The market stage never touches
the speaker's stated confidence. Each stage is resumable from its own meta.

### Stage 1, extract

`extract_predictions.py` picks a harness per transcript from the quota router's
measured headroom: `claude` accounts run Fable, `codex` runs Astra, the
Antigravity pool runs Gemini. Nothing defaults: no account, an unknown provider
or a degraded pick fails the job as `router_no_account`.

The harness call functions are imported from `grade.py` unchanged. Raw model
text is written under `_raw/` before it is parsed. The output is checked
against `extractor_output.schema.json` by a stdlib walker, then every quote is
grounded: normalise case, punctuation and timestamp marks, find the span
exactly, map it back to character offsets in the original text. A quote that
does not match exactly goes to `meta.ungrounded`, never to the file. There is
no fuzzy fallback.

Two candidates whose spans share 80% of the longer one are the same prediction
quoted with different boundaries, and the longer survives. Merely overlapping
spans are two records, because two distinct claims can share words. The first
live transcript showed why: a rule that collapsed any overlap silently dropped
"open source all the highway maps by the end of the year" because it sat inside
"we are going to be better than GM supercruise".

### Stage 2, verify

Each qualifying candidate goes to a different model family with a mechanical
400-word window each side, the quote, and the extractor's one-sentence claim,
never its reasoning. The verifier re-judges the five gates, decides attribution
(`subject | interviewer | third_party | unclear`), judges whether the claim adds
anything absent from the quote, and writes its own criterion. Its `qualifies`
is recomputed from those fields, never copied. `accepted` is true only when
both stages qualify. Disagreements stay on file with both verdicts.

### Stage 3, market consensus

Runs only on accepted records. Candidates come from the Polymarket Gamma search
and the Kalshi series catalogue; a market that opened at or after the cutoff or
closed before it is dropped with the reason recorded. One model call judges
semantic match only (`exact | proxy | none`, confidence, direction, rationale)
and never sees a price. Prices come from the Polymarket CLOB price history and
Kalshi candlesticks, as the latest observation strictly before the cutoff.

The cutoff is `P_market(t^-)`. This corpus knows only a YouTube upload date, so
the cutoff is 00:00:00 UTC at the start of that date: every observation before
it precedes the upload whatever time of day the upload happened. Precision is
recorded as `date` and staleness may reach 24 hours. A record with no date is
`unavailable`.

Only an exact match with an observation sets `market_probability`. Proxies are
stored as context and shown as links without a number. `no_match` is the
normal result. Every HTTP response is cached under `_markets/` so a rerun is
free and reproducible.

## 3. The record

One JSON object per line in `data/predictions/<slug>/<sid>.jsonl`, sorted by
quote offset then id, serialised with sorted keys so diffs are line-aligned.
The full schema is `prediction_record.schema.json`. The parts that matter:

- `prediction_id`: sha256 of the transcript id and the normalised quote, 16
  hex characters. Stable across runs and models; offsets are excluded so a
  re-repaired transcript keeps its ids.
- `source`: url, video id, title, venue, `statement_date` (YYYY-MM-DD or null)
  with `statement_date_basis` (`youtube_upload_date`, an upper bound, or
  `unknown`), the quote as written and as it appears, character offsets, word
  count, the nearest `[hh:mm:ss]` mark, and 400 words of context each side.
- `prediction`: normalized claim, category, type (`numeric | milestone |
  binary_event | trend_direction | comparative | other`), target date and the
  speaker's words for it, horizon (`explicit | inferable | none`), resolution
  criteria, specificity, `subject_control`.
- `confidence`: `explicit_probability` only when the speaker said a number
  (recorded as they said it), `qualitative` with the words quoted, or `none`.
  No stage ever infers or modifies a probability.
- `extraction` and `verification`: gates, the derived `qualifies`, harness,
  requested and served model with whether the served model was verified,
  account, contract id, run id, timestamp, and the full call telemetry.
- `resolution`: `{"status": "not_started"}` in V0.
- `consensus`: `{"status": "not_searched"}` until the market stage runs, then a
  block with status, the cutoff and its precision, the exact match with its
  observation, proxies, dropped candidates with reasons, and matcher provenance.

`declared_year` in the corpus is a hardcoded constant and is never read.

## 4. Running it

```
# tests, no quota
for t in shared lib schema driver markets eval aggregate site; do .venv/bin/python scripts/test_predictions_$t.py; done

# one transcript, both stages
.venv/bin/python scripts/extract_predictions.py --stage both --single data/transcripts_open/<slug>/<sid>.json

# the corpus, detached, one stage at a time so a quota stop is attributable
nohup .venv/bin/python scripts/extract_predictions.py --stage extract --workers 6 > data/predictions/_runs/extract.log 2>&1 &
nohup .venv/bin/python scripts/extract_predictions.py --stage verify  --workers 6 > data/predictions/_runs/verify.log 2>&1 &
.venv/bin/python scripts/market_consensus.py

# check, count, render, deploy
.venv/bin/python scripts/validate_predictions.py
.venv/bin/python scripts/aggregate_predictions.py
bash scripts/deploy_predictions.sh --dry-run
bash scripts/deploy_predictions.sh
```

Every stage skips a transcript its meta says is done; `--force` redoes it.
`--dry-run` builds prompts into the workdir and writes nothing. The driver
refuses `--fable-bin cl`, refuses an `--out` anywhere under `data/` other than
`data/predictions`, and prints attempted / succeeded / cached / excluded /
failed with an error taxonomy. Transcripts on the exclusion list
(`scripts/predictions_exclusions.json`, seeded from the 2026-09-10 withdrawal
manifest's retire entries) are marked excluded and never read.

This clone writes only under `data/predictions/`; commits of `data/` stay
with repo-0. The corpus run competes with the grading loop for the same Fable,
Astra and Gemini quota; check `bash scripts/status.sh` first.

## 5. Evals

`eval_predictions.py` scores an extraction tree against synthetic gold in
`scripts/fixtures/predictions/`: four caption-style transcripts with no speaker
labels, 14 positive spans and 24 negative spans across the brief's case list
plus the probe's four failure modes. The builder grounds every gold quote before
writing, so a typo fails loudly rather than lowering recall.

A written candidate matches a gold positive when their character ranges overlap
by at least half the gold span. Metrics, each with a threshold and a verdict:

| Metric | Threshold | Gate |
|---|---|---|
| precision (accepted matched / accepted) | 0.85 | hard |
| recall (gold matched / gold) | 0.60 | soft |
| adversarial: accepted on each probe failure mode | 0 | hard |
| attribution correctness | 1.00 | hard |
| quote fidelity (validator grounding invariants) | 1.00 | hard |
| claim fidelity (must-contain tokens) | 0.90 | soft |
| horizon, confidence type | 0.90 | soft |
| probability exactness | 1.00 | soft |
| schema validity (validator exit 0) | 1.00 | hard |

`PREDICT_LIVE=1 eval_predictions.py --out <dir>` runs the real driver on the
fixtures, about eight calls; without the variable it refuses and scores a saved
tree with `--scored`. The offline test `test_predictions_eval.py` proves the
arithmetic on a hand-built tree with a known miss, a known false positive and a
known wrong probability.

## 6. Validation

`validate_predictions.py` recomputes every mechanical claim in every record
and prints each failure as `file:line: invariant: detail`: the quote is at its
offsets, the id is its hash, the mark and windows are the mechanical cut, the
date came from the upload date, a probability exists only with a stated number
inside the quote, the derived booleans are the rule's values, the Phase 2 blocks
are at their sentinels or hold a valid market block whose every observation
precedes the cutoff, the verifier used a different harness, and every contract
id is known. `test_predictions_schema.py` breaks one thing at a time and demands
the validator name it.

## 7. Known limitations

- **The statement date is an upper bound.** YouTube's upload date is the day
  the recording was published, not the day the words were said. Every horizon
  and every market cutoff inherits that. Thirty-four transcripts, mostly
  HappyScribe-sourced, have no date at all.
- **Two model readings, not ground truth.** Agreement between the extractor
  and the verifier is evidence that a sentence is a prediction, not proof. The
  golden eval measures the extractor against hand-written gold, on synthetic
  text.
- **Astra and Gemini have live web search and it cannot be disabled**
  (AGENTS.md). The specs forbid outcome reasoning, the record has no field for
  it, and `tool_use_counts` and `web_search_queries` stay in the telemetry so
  exposure is measurable per record. Fable is sandboxed.
- **Recall is deliberately secondary.** The extractor returns only candidates
  that pass every gate and reports a count of what it weighed; near-misses are
  not requested. A capped transcript (40 candidates) records `cap_hit`.
- **Ambiguous quotes are dropped, not guessed.** A quote that occurs more than
  once with no usable timestamp hint is `ambiguous_no_hint` in the meta.
- **Market coverage will be low.** Statement years 2024-2026 hold 302
  transcripts; Polymarket has liquid history from 2024 and Kalshi from 2021 on
  a narrow set. Most accepted predictions will be `no_match`.
- **Date-level cutoff.** With only an upload date, the market observation can
  be up to 24 hours stale, and a market that opened on the upload day has no
  valid observation.
- **Restated predictions are two records.** Non-overlapping quotes of the same
  claim in one transcript both survive in V0.

## 8. Phase 1 / Phase 2 boundary

V0 delivers extraction, verification, validation, evals, descriptive
statistics, contemporaneous market evidence on accepted records, and the page.

Phase 2, explicitly not built here:

- **Resolution.** Fill `resolution` with an outcome, a resolved date, evidence
  and notes, per record, from external sources. The `resolution_criteria`
  written by both models is the input.
- **Consensus comparison.** The `consensus` block already holds
  `P_market(t^-)` for exact matches with full provenance. Phase 2 compares it
  with the outcome and, for explicit-probability predictions only, with the
  speaker's stated number.
- **Scoring.** For a binary prediction with an explicit probability `p` and
  outcome `o`, a proper score such as Brier `(p - o)^2`, and a market-relative
  edge `(market - o)^2 - (p - o)^2`. Ordinary declarative predictions need a
  different framework and must not be given an invented `p`.
- **A forecasting leaderboard.** Only after resolution and scoring exist, with
  the same care about sampling error the Verbatim Index applies.

The interfaces are the two reserved blocks and the stage boundaries above.
Nothing in V0 needs a migration to start Phase 2.

## 9. Measured on the pilot

Filled in from the pilot runs of 2026-09-10; see the section of the same name
appended below once the audit is complete.
