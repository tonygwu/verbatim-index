---
name: prediction-extractor
description: Turn one public transcript of a technology leader into structured, auditable records of the falsifiable predictions that leader made, each grounded in a verbatim quote at a known offset, with a normalized claim, resolution criteria, time horizon and the speaker's own stated confidence. Two models must agree before a record is accepted. Precision over recall. V0 extracts and verifies only; it never resolves outcomes, never scores, and never ranks anyone.
---

# Extracting a leader's predictions

## What this skill is for

The Verbatim Index grades how leaders think. Verbatim Predictions asks a narrower question of the
same transcripts: what did this person say would happen, in words a stranger could later check?
Every record keeps the exact span of the transcript it came from, the character offsets, the
nearest timestamp, and 400 words of context each side, so a reader can audit the cut without
re-running anything.

## The files, and which ones a model sees

| File | Who reads it | In the contract hash |
|---|---|---|
| `EXTRACTION.md` + `extractor_output.schema.json` | the extractor model, stage 1 | `extraction_contract()` |
| `VERIFICATION.md` + `verifier_output.schema.json` | the verifier model, stage 2 | `verification_contract()` |
| `MATCHING.md` + `matcher_output.schema.json` | the market matcher, stage 3 | `matching_contract()` |
| `prediction_record.schema.json` | `validate_predictions.py`, tests, humans | no |
| this file | agents | no |

Both stage specs include `ELIGIBILITY.md` through the `{{ELIGIBILITY_POLICY}}`
marker. The contract hashes the expanded spec and the output schema, so an
eligibility change changes both hashes. `POLICY_RELEASE.json` names the
compatible pair. The runner refuses a release whose pins do not match its
files. Historical specs without the marker retain their original hashes.
Editing this agent-facing file cannot move a result.

## The pipeline

```
transcript  ->  extract (stage 1)  ->  verify (stage 2)  ->  accepted record
            ->  market consensus (stage 3, accepted records only)  ->  browsing page
Phase 2, not built:  resolution  ->  scoring  ->  forecasting leaderboard
```

- Stage 1 reads the whole transcript with one model, chosen by the quota router, and returns only
  candidates that pass all five gates: forward-looking, falsifiable (it must write the resolution
  criterion), committed, own voice, stands alone. Every quote is grounded mechanically; a quote that
  does not match the transcript exactly after normalisation is discarded, never fuzzed.
- Stage 2 hands each candidate, with a mechanical 400-word window and the extractor's claim, to a
  DIFFERENT model family, which re-judges the gates, attribution and claim fidelity and writes its
  own criterion. `accepted` is true only when both agree. Disagreements stay on file with both verdicts.
- Stage 3 runs only on accepted records. It searches Polymarket and Kalshi through their public
  APIs, lets a model judge semantic match only, and reads the price from the market's own history
  strictly before the publication cutoff. Exact and proxy matches are kept apart. It never touches
  the speaker's stated confidence, and stages 1 and 2 never see a market.

## Rules that must not bend

- `confidence.probability` is a number the speaker said, or null. No stage infers one.
- The statement date is the YouTube upload date, an upper bound on the recording date, or null.
  `declared_year` in the corpus is a hardcoded constant and is never read.
- The models are told the statement date and never today's date, so "future" is judged at the
  time of speaking and nothing about outcomes enters a prompt.
- This clone writes under `data/predictions/` and nowhere else under `data/`; the writer refuses
  any other path. Commits of `data/` stay with repo-0.
- Every write is atomic; every failure carries a taxonomy label; every run has a manifest.
- Successful stages are reused only when the contract, policy release, input,
  prompt set and model request match. A stale stage fails as `cache_stale`
  without overwriting the old result or calling a model. Verification refuses
  an incompatible extraction as `policy_release_mismatch`, even with `--force`.
- A new policy release requires a deliberate update of both contract pins.
  Keep pilot outputs separate before replacing existing corpus records.
- Records keep policy and input provenance in `telemetry.prediction_audit`.
  The metadata stores the same audit block. `_inputs/` preserves exact inputs
  and ordered prompts; `_raw/responses/` preserves complete Astra/Fable CLI
  responses before parsing. The prompt digest hashes the ordered JSON list.
  The code revision is provenance, not a cache key: unrelated commits do not
  invalidate a result whose actual inputs and prompts remain identical.

## Commands

```
.venv/bin/python scripts/extract_predictions.py --stage both --single data/transcripts_open/<slug>/<sid>.json
.venv/bin/python scripts/extract_predictions.py --stage extract --workers 6
.venv/bin/python scripts/extract_predictions.py --stage verify  --workers 6
.venv/bin/python scripts/market_consensus.py
.venv/bin/python scripts/validate_predictions.py
.venv/bin/python scripts/aggregate_predictions.py
PREDICT_LIVE=1 .venv/bin/python scripts/eval_predictions.py --out <tmp>
```

`docs/PREDICTIONS.md` holds the architecture, the schema, the known limits and the Phase 2 boundary.
