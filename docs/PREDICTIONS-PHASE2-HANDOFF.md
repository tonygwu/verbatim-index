# Phase 2 handoff to repo-0: what to integrate, and what to check first

Written 2026-09-15 by repo-2. Nothing here is integrated. The run lives in
repo-2's private data checkout at
`data/predictions/_experiments/phase2-scoring-20260915/`, on branch
`codex/repo-2-data-2026-09-14`, and only repo-0 may move it into the shared
corpus or publish from it.

The findings behind every number are in
[PREDICTIONS-PHASE2-RESOLUTION.md](PREDICTIONS-PHASE2-RESOLUTION.md). This file
is only the operational part.

## What the run contains

```
resolutions/          225 of 225 past-due predictions, each with a cited source
priors/               the published priors, which price the DEADLINE
priors_v1_event/      the first pass, which priced the EVENT; kept for the A/B
criteria_repairs/     all 39 screen-flagged records, all already_correct
repair_control.json   6 planted defects, 6 caught
hindsight_probe.json  20 disclosed-outcome calls and the separation arithmetic
scores.json           the joined result: what the page reads
_raw/                 the full CLI response behind every call
_runs/                per-pass attempted / succeeded / failed with a taxonomy
```

Pass results, all clean:

```
criteria repair       39 attempted   39 succeeded   0 failed
resolver (eligible)  105             105            0
resolver (rest)      117             117            0
prior (deadline)      96              96            0
prior (60-day floor)  40              40            0
prior (remainder)     67              67            0
```

Every one of the 225 past-due predictions carries BOTH a resolution and a prior,
so nothing on the page is missing data. 113 are scored and the other 112 are
excluded for a stated reason, never for want of a number:

```
  47  not_eligible                      (the lead-time and specificity gate)
  28  unresolvable: no_public_evidence
  15  unresolvable: criterion_ambiguous
  12  unresolvable: threshold_unmeasurable
  10  unresolvable: deadline_incoherent
```

That matters for review: a reader opening any past-due prediction sees its
outcome, its evidence, the probability it was priced at, and, if it is not
scored, which of those five reasons applies.

## How to regenerate `scores.json` and the page

Neither step spends a model call.

```
.venv/bin/python scripts/score_predictions.py \
    --run <run-dir> --as-of <YYYY-MM-DD> --min-lead-days 60
.venv/bin/python scripts/build_predictions_site.py --scores <run-dir>/scores.json
```

`deploy_predictions.sh` picks up `scores.json` ONLY from inside the production
checkout, and refuses a path outside it. So integration means copying the scored
run under the production data root; there is no flag that publishes an experiment
directly, deliberately.

Without a scores file the page renders the Score column empty and says why. That
stays the safe default and needs no flag.

## Read these three before publishing

**1. Every outcome is single-sourced.** One resolver, no second arm, so there is
no agreement rate. The evidence discipline is real as far as it goes: 0 decided
outcomes with an empty source list, all 351 cited sources carrying a URL, every
resolution running at least one web search. But nobody has measured how often two
independent resolvers would disagree about the same claim. That is the cheapest
remaining check and it has not been run.

**2. Residual hindsight is bounded, not excluded.** The blind assessor separates
hits from misses by more than calibration alone allows, and the excess is 73% of
what FULL hindsight would produce. It biases every score toward zero rather than
toward any person, so a near-zero score means "no foresight demonstrated", never
"foresight disproved". The clean test needs a model whose knowledge cutoff
precedes the deadline.

**3. The assessor is calibrated overall and not by bin.** Overall gap -0.006
against a 1.96 se of 0.092. But every bin below p=0.6 overshoots and every bin
above undershoots, which is under-extremity. It is measured and deliberately NOT
corrected: recalibrating on the same predictions that measured it would be
circular.

## The lead-time floor is a policy dial, and it moves the board a lot

`MIN_LEAD_DAYS` in `scripts/phase2_resolvability.py` is 60, set by the operator on
2026-09-15, replacing 180 the day before. It is the single most consequential
number here:

```
180 days    77 scored    3 people ranked
 60 days   113 scored    9 people ranked
```

The constant carries the reasoning and the measurement. If repo-0 disagrees with
60, change the constant and re-run `score_predictions.py`; no model calls are
needed, because every past-due prediction is already resolved and priced.

## What is NOT in this run, and must not be added yet

Nothing from repo-1's supplemental web sources
(`supplemental-sources-2026-09-14`). **repo-1 has asked that their run not be
integrated yet, and that stands.** It was briefly integrated here on 2026-09-16
and then withdrawn in full; the data branch carries the removal and the reason.

What the trial measured, for whoever does integrate it later. Their records were
still being extracted at the time, so these are a snapshot rather than the final
figures:

```
              main only    with supplemental
past due            225                  246
eligible            152                  163
scored              113                  121
ranked                9                    9
```

Nobody crossed the floor. Patrick Collison went 1 -> 4 and Brian Chesky 1 -> 4,
both one short. My projection beforehand said Collison would reach 5, and it was
wrong because it applied the corpus-wide 74% resolve rate to a handful of
records. Their run was still producing when it was measured, so a later
integration will find more than this.

Scoring the two corpora together needs the RENDER GUARD that trial produced. The
page embeds only the corpus named by `--predictions`, so scoring two and
rendering one averages a person's number over predictions their own drawer
cannot show. `check_scores_are_renderable` refuses that and names the people. It
found 8 such predictions across 4 people, invisible only because all four sat
below the rank floor. Integrate both corpora into the page's inputs, not just
into the scorer.
