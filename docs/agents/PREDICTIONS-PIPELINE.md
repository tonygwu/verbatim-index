# Verbatim Predictions: pipeline and operations

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you add, extract, verify,
price, resolve or score predictions; move the scoring as-of date; change a
policy release; run a case eval; or deploy the predictions site.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Experiments run, and what they showed

**Does the verifier, or the new rules, cost a re-extraction its predictions?** (2026-10-05)
The verifier, mostly. On 2026-10-03 the 137 re-dated recordings were re-extracted with Fable
extracting and Gemini verifying, and 26 of them had been extracted by Astra and verified by
Fable. Those 26 lost accepted records heavily (ledger VD-13). Re-run with their ORIGINAL pair,
Astra extracting and Fable verifying, under the same release 2.3 and the same corrected dates:

```
accepted records    corpus extraction   after 2026-10-03   re-run, original pair
all 26                     74                  39                   84
andy-jassy                 37                  23                   47
cathie-wood                11                   6                   11
david-sacks                 7                   1                    6
vinod-khosla                5                   1                    8
```

So the new rules and dates did not cost these recordings their predictions; the swapped
verifier did. Since then a re-dated recording is re-extracted with the pair its production meta
names (`redate-20261005n/make_lists.py`). Not yet done: the 107 recordings first extracted
Astra+Gemini still carry their 2026-10-03 Fable+Gemini records. Data
`predictions/_experiments/redate-vd13b-20261005/compare.txt`.

## Where things are

- Verbatim Predictions (extract, verify, market consensus, validate, aggregate, page): skill in
  `.claude/skills/prediction-extractor/`, records in `data/predictions/<slug>/<sid>.jsonl`, design and limits in
  `docs/PREDICTIONS.md`, page built by `scripts/build_predictions_site.py` and deployed with
  `bash scripts/deploy_predictions.sh --production-data "$(cd data && pwd -P)" --data-revision "$(git -C data rev-parse HEAD)"`
  to `verbatim-predictions.tonygwu.com`, from any push-role clone at exactly origin/main.
  This is a SECOND published site with its own domain and its own index, and it
  goes stale independently of the leaderboard: `data/predictions/index.json` is
  rebuilt only by `aggregate_predictions.py`, which nothing runs on a loop.
  `deploy_predictions.sh` compares the index's `files_read`, `records_read` and
  `inputs_sha256` against the files on disk and refuses publication when any differs.
  The digest is what catches verification and market consensus, which rewrite
  records in place and leave both counts unchanged. The index also fingerprints the
  roster and the transcript listing, and `scores.json` fingerprints every input it read
  and is rebuilt from the committed `predictions/scoring.json`. The deploy regenerates
  nothing: `--refresh` is gone, and `data_sync.py push` regenerates both files.
  **The scoring as-of date always moves up when predictions are added. Do not ask the operator
  first** (operator rule, 2026-09-27). The as-of in `data/predictions/scoring.json` decides what
  counts as past due, so an old one silently leaves out every prediction that fell due since. On
  2026-09-27 moving it 11 days added 2 scored predictions and ranked Chamath Palihapitiya. When
  you add predictions, in the same integration: set `as_of` to the UTC date of the commit that will
  carry them; resolve and price every eligible prediction that became past due; re-score
  (`data_sync.py push` regenerates `scores.json` from `scoring.json`). A trend record's window
  freezes at its first resolution (operator decision, 2026-09-27): its end is the `deadline` in that
  resolution sidecar, and a later as-of does not move it. So moving the as-of date costs no model
  calls unless new predictions fell due or new trend records qualified. An unresolved trend record
  still runs to the current as-of until it is resolved. `resolve_predictions.select` applies the
  freeze, refuses a trend resolution with no usable `deadline`, and `score_predictions.py` refuses
  a prior and a resolution that name different windows. Proof:
  `.venv/bin/python scripts/test_trend_window_freeze.py`.
  If the commit lands after UTC midnight, the date moved, so repeat. `deploy_predictions.sh`
  refuses when `as_of` is older than the newest commit that added predictions data under
  `predictions/`. Not predictions data: `scores.json`, `scoring.json`, `year_summaries.json`, and an
  experiment folder under `predictions/_experiments/` that no run named in `scoring.json` lives in
  (since 2026-09-29, when a research folder moved the bar and a move would have resolved a mis-dated
  record). The check is `scores_asof_lag()` in
  `data_clone_workflow.py`, and it reads the commit date in UTC, never an mtime or the local clock.
  Proof: `.venv/bin/python scripts/test_scores_asof_current.py`.

- Prediction policy releases: `.claude/skills/prediction-extractor/POLICY_RELEASE.json`
  pins the compatible extraction and verification contracts. Both load
  `ELIGIBILITY.md`. Run `.venv/bin/python scripts/test_predictions_policy.py`
  for cache and compatibility checks. A stale cache never triggers an automatic
  paid rerun. The bounded release-2 pilot and its frozen inputs are documented
  in `docs/PREDICTIONS-RERUN-2026-09-12.md`.
  Since release `predictions-2.3` (2026-09-30) it also pins the header template,
  `STATEMENT_DATE_HEADER.json`, as `contracts.header`: the date line is prompt
  text outside both specs, so editing it is `policy_release_mismatch`. The line
  says how the date is known, and an unchecked upload or publication date is
  labelled an upper bound only. Relative time words still resolve against an
  unchecked date (the card labels it "not checked"; coordinator decision
  2026-09-30). Both models return `statement_date_doubt`; a
  `recording_older_than_stated` doubt, a placeholder year in a field that names
  no year, a relative year the funnel's reading puts earlier, or "this year" or
  "next year" on a date range that crosses 31 December sets `date_hold`, and a
  held 2.3 record is not accepted. For that last case the funnel derives no
  deadline either: `phase2_resolvability.derived_deadline` calls
  `predictions_lib.relative_phrase_crosses_new_year` first, a three-line hook.
  The hold needs no checkout: `predictions_lib` keeps its own copy of the funnel's
  relative-phrase reading, pinned to the funnel's by a test. A 2.2 record keeps its
  published `accepted` flag. Proof: `.venv/bin/python scripts/test_predictions_release23.py`.

- Tier R case evals: `scripts/eval_prediction_cases.py --gold
  data/predictions/_eval/cases-20260929` replays the operator's audited cases
  offline; `--smoke` runs the Buddy Media `already_public` case first;
  `PREDICT_LIVE=1 ... --live` spends quota (`--estimate` first). A recorded answer
  replays only under its prompt's sha256, from the case's own harness and the
  requested model. A dating repeat calls each dater once and replays only with
  every dater's answer, so a dating case costs two calls per repeat. The gold file
  is private data. Proof: `scripts/test_eval_prediction_cases.py`,
  `scripts/test_eval_dating_daters.py`. The dating audit of 2026-10-04 is its own gold
  set, `data/predictions/_eval/cases-20261004-dating`. A case there with
  `input.pairs` calls each dater in the union once per repeat and judges every pair:
  gemini+fable, gemini+fable_web and gemini+astra, so the pairs share Gemini's
  answer. Stage `dating_stored` replays stored proposals and checks, pinned by
  sha256, through the real merge with no model. The `truth` expectation judges the
  last day. Proof: `scripts/test_eval_dating_pairs.py`. merge-5's gold set is
  `data/predictions/_eval/cases-20261005-merge5`: the seven, Mensch, hs-2394 and
  control (ii) live with astra,fable_web, and stored regressions and controls for each
  merge-5 rule (`make_gold.py` builds it; `logs/stored_table.py` runs each stored case
  under merge-4 and merge-5). An expectation may name `forbid_sources`, pages the
  operator found to be about another occasion: a confirmation from one is a wrong
  auto-confirmation whatever its day. A stored case gives the speaker's company as
  `input.speaker_company` for files made before merge-5. A legacy single-dater case
  (`input.harness`, cases-20260929) runs the daters of its era, gemini and fable.
