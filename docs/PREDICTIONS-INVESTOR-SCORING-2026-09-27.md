# Scoring the seven investors, and medium specificity, 2026-09-27

Operator request, 2026-09-27: make `specificity: medium` eligible for scoring,
then resolve and score the seven investors' 40 past-due predictions that had no
resolution. Both are done in repo-2. **Nothing is published yet.** The data
lives on repo-2's own private branch, and repo-0 incorporates and deploys it
with the steps at the end.

## Result

Scored over production data `12d3df0a`, as-of 2026-09-16, `--trend`, with the
production run and the new run read together:

```
                         past due  eligible  resolved  scored  ranked
production today            417       269       349      189      28
new rule only               417       330       349      222      28
new rule + the 40           417       330       389      243      31
```

The prior assessor stays calibrated on the larger set: mean p 0.652, hit rate
0.642, gap -0.010 against 1.96 se 0.063.

Three investors reach the rank floor of 3:

```
Cathie Wood     #6   +0.221  n=8
David Sacks    #11   +0.030  n=4
Vinod Khosla   #26   -0.238  n=4
```

Bill Gurley, Marc Andreessen and Chamath Palihapitiya score 2, 2 and 1 and stay
unranked. Tom Lee's 2 past-due predictions are ineligible on lead time or
window, not on specificity, so neither scores.

The prediction that started this, Gurley's "I do think you'll see some dead
unicorns this year" (SXSW, 2015-03-20), resolved **not_occurred**. The resolver
found the first unicorn shutdowns in 2016, Powa (administration, February) and
Mode Media (September), and read Fab and Good Technology in 2015 as acquisitions
rather than deaths. It was priced at p = 0.45, so it scores -0.94.

## What moved, and why

**The eligibility change is the larger effect on existing rows.** It admits 33
already-resolved, already-priced predictions, and changes 11 leaders' means. The
largest moves: Arvind Krishna #11 to #23 on the threshold alone, as 7 more of his
predictions score; Bill Gates #23 to #14; Sam Altman #21 to #13; Brian Chesky #6
to #9. Every row is in `logs/board-diff.txt` in the run directory.

**The 40 new resolutions add 21 scored predictions**, all for the seven.

## A defect found on the way, and fixed

On a TREND record the prior and the resolver priced different events. A trend
record has no date the speaker gave, and the resolver's rule 7 judges whether the
claimed DIRECTION held over the window. The prior prompt had no such rule, so it
priced the literal endpoint. Cathie Wood's 2021 claim that genome sequencing
would fall to ten cents was priced at p = 0.02 for the endpoint and resolved
occurred on the direction, about 87% cheaper. It paid +5.64 points and put her
first on the board at +0.825 on that one record.

Fixed in public `964d3f3`: `PRIOR_TREND_RULE` is added to the prior prompt for
trend records only, and every non-trend prior prompt stays byte-identical, so the
350 existing priors are unaffected. The seven's 11 trend records were re-priced;
the genome record moved to p = 0.85 and Wood to +0.221. The first priors are kept
in `superseded-endpoint-priors-20260927/`, where the scorer does not read them.

**Not re-priced: production's 14 trend records** in `phase2-scoring-20260915`.
That run is repo-0's. The 3 of them that score today are direction claims, where
endpoint and direction are the same event (Box's margin rising, Replit's users
doubling, Uber reaching GAAP profit), so the mismatch should be small there. The
operator decides whether to re-price them for consistency; it costs 14 Fable
calls.

## Choices made without the operator

- **as-of stays 2026-09-16**, the production as-of, so the selection is exactly
  those 40. A later as-of would add records that fell due since, unasked.
- **11 other leaders' eligible predictions are still unresolved**, 5 of them newly
  eligible under the medium rule. Resolving them is outside "those 40". One
  command per stage, as below, with those leaders' slugs.
- **Astra ran on `~/.codex-b` only**, because `~/.codex` carries an operator
  budget hold. **Fable ran on `.claude-b` and `.claude-d`**, the two accounts
  with the most Fable headroom.
- **The prior prompt was changed** as above. Reverting `964d3f3` and moving the
  superseded priors back restores the endpoint pricing.

## Tests

Each change was tested first and failed before it was made:

```
test_eligibility_specificity.py   3 failing checks before, 9/9 after
test_score_multi_run.py           5 failing checks before, 9/9 after
test_prior_trend_alignment.py     2 failing checks before, 5/5 after
```

`test_score_multi_run.py` also found that `--run` was last-flag-wins: a second
`--run` silently replaced the first. It is now repeatable, and a prediction
present in two runs stops the scorer naming both.

The full suite has one pre-existing failure, not caused by this work:
`test_run_marker.py` "a plain kill removes the marker" fails 2 of 2 at the
starting revision `fac7967` in a clean worktree.

## For repo-0: incorporate and publish

Production data `main` was still `12d3df0a` when this was written, which is the
branch's parent, so the merge adds one directory and conflicts with nothing. The
index stays fresh: `prediction_inputs_sha256` skips directories starting with `_`,
and it matched `index.json` with the run present.

```
git pull --ff-only                                  # public main at or after 964d3f3
git -C data fetch origin codex/repo-2-investor-scoring-20260927
git -C data log --stat -1 FETCH_HEAD                # ec5ae558; one new directory
git -C data merge --ff-only FETCH_HEAD

.venv/bin/python scripts/score_predictions.py \
    --run data/predictions/_experiments/phase2-scoring-20260915 \
    --run data/predictions/_experiments/investor-phase2-20260927 \
    --predictions data/predictions --as-of 2026-09-16 --min-lead-days 60 --trend \
    --out data/predictions/scores.json
# expect: 417 past due -> 330 eligible -> 389 resolved -> 243 scored across 31 ranked leaders

git -C data add predictions/scores.json
git -C data commit -m "Score the seven investors and medium-specificity predictions"
git -C data push

bash scripts/deploy_predictions.sh --production-data "$(cd data && pwd -P)" \
    --data-revision "$(git -C data rev-parse HEAD)" --dry-run
# then, with the operator's approval, the same command without --dry-run
```

`--trend` is not optional; see `docs/PREDICTIONS-ROUND2-2026-09-16.md`.

A local render from these scores built 52 rows, 243 of 417 scored, 31 ranked, and
389 outcomes in drawers. Headless Chromium showed 0 page errors and 0 failed
requests.
