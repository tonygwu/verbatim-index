# Scoring a resolved prediction, decided 2026-09-15

The rule, the pilot that exercised it end to end, and the two things that must be
built before any of it reaches the page.

Implementation: `scripts/prediction_score.py`. Proof:
`.venv/bin/python scripts/test_prediction_score.py`, which pins both tables the
rule was specified with.

## The rule

A point is a bit: one doubling of the odds assigned to what actually happened.
`p` is the ex-ante baseline probability, at the moment of speaking. `q` is the
speaker's own probability.

**Speaker-probability rule**, when `q` is known or inferred:

```
E occurred      S = log2(q / p)
E did not       S = log2((1 - q) / (1 - p))
```

**Baseline-only rule**, when the prediction is a bare assertion:

```
E occurred      R(p) = -log2(p)
E did not       L(p) = -(p / (1 - p)) * log2(1 / p)
```

`L` is fixed by requiring `p*R + (1-p)*L = 0`, so a predictor who calls events at
the baseline rate scores zero in expectation. That is what stops a thousand long
shots from paying: a 1% call is worth +6.64 when it lands and -0.067 when it does
not, and 1(6.64) - 99(0.067) is about zero.

**`q` is almost never stated.** 5 of 475 accepted predictions carry a probability
the speaker said, and only 1 of those is past due. Three of the five state
`q = 1.0`. So the baseline-only rule, or an inferred `q`, is the scoring system;
the stated-`q` path is a rounding error on this corpus.

## p and q are clamped, and every clamp is reported

A log score is unbounded at the ends. `p = 0` with the event occurring is
infinite, and `q = 1` with the event not occurring is negative infinity. The
second is not hypothetical: three of the five stated probabilities are exactly
1.0. Both inputs are clamped into `[0.01, 0.99]` and the result names which input
was clamped. A caller that drops that field is discarding a warning.

The clamp is visible in the tables. At `p = 0.001` the specification gives
+9.97 / -0.010; this implementation gives +6.64 / -0.067, because 0.001 is beyond
the clamp. Tightening `CLAMP` punishes a wrong certainty harder and lets one
record dominate a leader's mean. It is a judgement, set in one named constant.

## The pilot, 13 predictions resolved and scored by hand

Past due, high specificity, at least six months of lead time, and inside the
resolver's knowledge. Outcomes and evidence are in the commit that added this
file; `p` is assessed per record with its reason.

```
leader               out     p      pts   claim
aaron-levie         TRUE  0.85   +0.234   Box revenue nearly a billion in 2022
andy-jassy          TRUE  0.85   +0.234   AWS opens 4 announced regions by end 2016
andy-jassy          TRUE  0.85   +0.234   S3 Glacier Deep Archive in early 2019
andy-jassy          TRUE  0.70   +0.515   Inferentia available in 2019
andy-jassy          TRUE  0.75   +0.415   Outposts available in 2019
andy-jassy         false  0.65   -1.154   Habana Gaudi EC2 instances in H1 2021
arvind-krishna      TRUE  0.70   +0.515   IBM revenue growth +5% in 2022
bill-gates         false  0.15   -0.483   Robots move a patient bed to bed within 10 years
dara-khosrowshahi   TRUE  0.55   +0.862   Uber EBITDA profitable by end of 2021
dario-amodei       false  0.25   -0.667   SWE-bench reaches 90% within a year
elon-musk          false  0.10   -0.369   FSD safer than the average driver in 2022
elon-musk          false  0.35   -0.816   Cybertruck deliveries by mid-2023
elon-musk           TRUE  0.75   +0.415   SpaceX 60-70 launches in 12 months
```

Per leader, mean points: dara-khosrowshahi +0.862, arvind-krishna +0.515,
aaron-levie +0.234, **andy-jassy +0.049**, elon-musk -0.257, bill-gates -0.483,
dario-amodei -0.667.

Andy Jassy is the result worth reading. He carries more predictions than anyone
on the board, 41, and five of them scored here average +0.049, which is
indistinguishable from zero. They are keynote roadmap items: announced weeks
earlier, so `p` is high, so keeping the promise earns about +0.23 and the one he
missed cost -1.15. **A corporate roadmap is a near-zero-information forecast, and
this rule says so without anyone having to special-case it.** That is a better
outcome than the earlier `subject_control` filter, which threw such predictions
away entirely.

## Two things that must be built before this reaches the page

**1. `p` must be assessed blind to the outcome.** In this pilot the same reader
knew the answer and then chose `p`, which is not an ex-ante probability. The bias
has a direction: knowing a prediction failed invites a lower `p`, which shrinks
the penalty, and knowing it landed invites a higher `p`, which shrinks the
reward. Both compress the board toward zero. The fix is a separate stage whose
prompt carries the quote, the statement date and the surrounding context, and
carries NO outcome, the way the verifier never sees the extractor's reasoning.
Until that exists, no score computed this way may be published.

**2. Resolution needs evidence, not recall.** Every outcome above is an assertion
from one reader's memory. This repo does not accept that anywhere else and should
not start here. A resolution record needs a cited source and a date, and the
resolver must be able to return `unresolvable` rather than guess. 220 of the 225
past-due predictions fall inside a 2026-05 knowledge cutoff, so recall gets you a
long way and is exactly why it is dangerous: it is fluent and unverifiable.

Two further notes for whoever builds it. The market branch is dead: 0 exact
matches across all 475 records, so `p` comes from an assessor in essentially every
case. And the 26 broken criteria in `PREDICTIONS-CRITERIA-AGREEMENT.md` must be
repaired first, because 18 of them cannot be resolved either way and 8 would
resolve to the opposite answer.

## Medium specificity is eligible, decided 2026-09-27

The operator widened the eligibility rule from `specificity == "high"` to high or
medium. The rule lives in one constant, `ELIGIBLE_SPECIFICITY` in
`scripts/phase2_resolvability.py`, which both the funnel and
`resolve_predictions.select()` read. LOW stays out, a missing value is not read as
medium, and the lead-time floor and the coherent-window check still apply to a
medium record. Proof: `.venv/bin/python scripts/test_eligibility_specificity.py`.

What prompted it: Bill Gurley's "I do think you'll see some dead unicorns this
year" (SXSW, 2015-03-20) is a dated, falsifiable call that the extractor rated
medium because "some" names no count. Under the old rule it could never score.

MEASURED before the change, with `select()` over production data `12d3df0a` at
as-of 2026-09-16 and `--trend`, 417 past-due predictions:

```
already resolved AND priored, blocked only by the rule    33   (other leaders)
the seven investors' 40 unresolved, eligible after        34   (6 stay out on lead time or window)
other leaders, eligible after, still unresolved           11   (5 of them newly eligible)
```

The cost is latitude in the criterion. "Some unicorns will die" can be settled,
but a resolver must choose how many is "some" and what "die" means. That choice
is visible in each resolution's reasoning, and a criterion that cannot be settled
comes back `criterion_ambiguous` and is excluded rather than scored as a miss.

## What the page lists and prints, decided 2026-09-27

Operator request, implemented in `scripts/build_predictions_site.py`.

**Who gets a row.** A person needs `MIN_PREDICTIONS_TO_LIST` (4) accepted
predictions. With a scores file, they also need at least one past-due
prediction (`MIN_PAST_DUE_TO_LIST`). The count floor is a rule, not a list of
names, so a person who gains predictions returns on the next render. On
2026-09-27 it removed Clem Delangue (1), Tobi Lütke (2) and Sergey Brin (3),
and kept Alex Karp (4). Everyone without a row is named under the table with
the reason, because "not listed" and "missing" are different facts.

**Which totals the prose uses.** Every score figure on the page (the intro, the
eyebrow, the Score legend and its help panel) describes the LISTED people only.
`listed_corpus()` sums them from scores.json's per-person rows, and it refuses
the render if those rows do not add up to the file's corpus block. The strip's
corpus totals (predictions, transcripts scanned, percent dated) still describe
everything the pipeline read, which is also what the social card draws. The
note under the table says the unlisted people's predictions still count there.

**Default sort.** With a scores file, Score, highest first. Unscored rows come
after every scored row, in name order, whichever way the column is sorted.
Without a scores file, name order.

**The prior explanation.** The page names the model that set each prior and the
model that decided each outcome. It reads both from the prior and resolution
sidecars in scores.json's `run_dirs`, resolved inside the checkout that holds
scores.json. It refuses the render if a run directory is missing, if a scored
prediction has no sidecar, or if a sidecar's `p` differs from the scored `p`.
The worked example calls `prediction_score.score()` at render time and checks
that the expected points are zero at each p shown.

**Year-square popover.** A square's shade encodes how many accepted predictions
carry a statement date in that year (bands 1, 2-3, 4-7, 8+; grey for none). The
popover says the year and the count. Its text takes the square's colour; where
that colour is under WCAG AA (4.5:1) on the popover, the page keeps the hue and
moves only the lightness until it reaches 4.5:1. MEASURED on 2026-09-27: in
both themes every band except the darkest (8+) needs that adjustment.

**The Predictions column.** The cell shows the total, then where each
prediction stood at scores.json's `as_of`. The builder derives the buckets per
person and refuses the render if a row's lines do not add up to its total,
naming the person. Only lines above zero are shown, in this order:

| Line | A prediction lands here when |
|---|---|
| Scored | scores.json has it with `scored: true` |
| Not yet due | scores.json does not have it, and its deadline is after `as_of`. If `phase2_resolvability.funnel_flags` says it fails a clause, the card says it will not be scored and why |
| No deadline | scores.json does not have it, and `phase2_resolvability` reads no deadline under the scorer's trend rule. A directional claim that rule judges later says from which date, never "never checked" |
| Awaiting check | `not_scored_because` is `no_resolution` or `no_prior` on an eligible row; also an ELIGIBLE record past due at `as_of` that scores.json lacks, which the builder counts and prints |
| Not testable | the row's flags say it is not eligible; the card names the first clause it fails in `phase2_resolvability.INELIGIBLE_REASONS` order, which must be the clause a `not_eligible:<clause>` string names (see "Eligibility is checked first" below). Also an ineligible record past due at `as_of` that scores.json lacks. Before 2026-09-29 the scorer wrote a bare `not_eligible` |
| Couldn't check | `not_scored_because` is `unresolvable:<reason>`, which the scorer now writes only for an ELIGIBLE row; the reasons are split on hover and in the column's help |
| Restated | a non-specific member of a restatement cluster in scores.json's `restatements` block, past due or not |

A not-scored reason with no bucket, or a scores.json row that is no record on
the page, refuses the render. So does a row with no funnel flags, a scores file
that states no trend rule (`rule.trend`, or `settings.trend` in a file written
before 2026-09-29), and a `corpus.unresolvable_by_eligibility` block that the
rows do not reproduce. The score panel's count of "cannot be resolved" answers
is the eligible half of that split, the same number as Couldn't check, and it
names the answers given on records that were not testable anyway. Sidecars
listed under `replacements.replaced_sidecars` are left out when the page reads
which models set each price and outcome, as the scorer left them out.

Proof: `.venv/bin/python scripts/test_predictions_site.py`. Browser check,
which needs Playwright and a rendered site directory:
`python scripts/check_predictions_site_ui.py --site <dir> --absent "<names>" --shots <dir>`.

## Eligibility is checked first, and named in one order, 2026-09-29

Rescue round 4, design 3.5, and the reviews of the funnel change.
`score_predictions.join` checks eligibility before anything else, so an
ineligible row reads `not_eligible:<clause>` whether or not it was resolved. The
resolve and prior stages skip ineligible records by default, so "no resolution"
no longer reads as "awaiting a check" for a record no stage will ever check.

**One order.** A record that fails several clauses is named by the first of
`phase2_resolvability.INELIGIBLE_REASONS`: `deadline_before_statement`, then
`specificity`, then `undated` (no statement date, so no lead time), then
`lead_under_floor`. That is the order of the funnel's own stages.
`phase2_resolvability.ineligible_reason` names it and `failing_clauses` lists
every clause a record fails. `funnel_flags` computes the flags themselves:
`resolve_predictions.select` writes them onto every past-due record, and the page
asks it about a record scores.json does not carry. Every reader, the resolver,
the scorer and the page, must call those functions and keep no order of its own. Proof: the ORDER checks in
`scripts/test_phase2_resolvability.py` and the SHARED checks in
`scripts/test_resolve_selection.py`.

**What changed in the counts.** `corpus.by_outcome` and
`corpus.unresolvable_reasons` count what the resolver answered, so they still
include the ineligible rows it answered before the default changed. On the
production data of 2026-09-28 that is 118 unresolvable outcomes, and only 93
rows read `unresolvable:<reason>`. `corpus.unresolvable_by_eligibility` splits
them: `eligible` (93) and `not_eligible` (25), each with its `n` and its
`reasons`. The eligible half is the page's "Couldn't check".

**The trend rule is in the file.** `rule.trend` is `{"enabled", "min_years"}`:
whether an undated directional claim is judged over the window since it was
said, and how many years must pass first (`phase2_resolvability.MIN_TREND_YEARS`).
It is there so the page can state the rule from the file rather than restate it.

**Replacements.** A re-resolved or re-priced sidecar in a newer run replaces an
older run's only through the manifest named by the optional `replacements` key
of `predictions/scoring.json` (`score_predictions.read_replacements`). The
manifest must lie under `predictions/`, because `data_sync.py` regenerates the
scores from `predictions/` and `roster/` only; `load_scoring_config` and
`data_sync.py` refuse any other path by name. `replacements.replaced_sidecars`
reports each replaced sidecar with its outcome or p before and after, and the
window it judged before and after (`deadline_was`, `deadline_now`).

**A trend window freezes across runs.** A resolved trend record keeps the window
of its first resolution in ANY run the scoring config names, not only in the run
a stage writes to. `resolve_predictions.py` reads every run of
`<data>/predictions/scoring.json` (or `--scoring-config`), so `--ids` into a new
run judges the old window, and it refuses a trend record whose runs record
different windows. The scorer refuses a replacement resolution of a trend record
that judged another window than the one it replaces. A dated record's
replacement may move its window. Proof: `scripts/test_trend_window_freeze.py`.

## Restatements score once, decided 2026-09-28

Operator decisions (data run `restatements-20260928/DECISIONS.md`): a person who
says the same thing on several days made ONE prediction. A moved deadline, a
changed threshold or a contradiction is not a restatement, so a missed first call
is never hidden by a later one. The merged prediction is dated at the EARLIEST
member whose own wording is specific enough to imply the merged criterion, its
`specific_member`; earlier, vaguer members are context only.

**The manifest.** `scripts/build_restatement_manifest.py` turns a reviewed
`clusters.json` into a manifest of clusters, each with its `members` and its
`specific_member`. Only `clusters` become clusters; a cluster that holds every id
of a `moved_goalpost`, `uncertain` or `judged_distinct` group is refused. In
production it would live at `predictions/restatements.json` and be named by the
optional `restatements` key of `predictions/scoring.json`. A config without the
key scores byte-identically to one written before the key existed.

**The scorer** (`score_predictions.py --restatements`). The specific member scores
with its own resolution, prior and statement date, so its own lead time decides
eligibility. Every other past-due member stays a row, `not_scored_because`
`restated:<specific_member>`, with its own verdict kept under `own_outcome` and
`own_p` and left out of every outcome count. The corpus and each person carry a
`restated` count, and the reasons still add up to `past_due`. It refuses an
unknown prediction id, a member in two clusters, members of different people, and
a specific member with no resolution or no prior while another member has one.

**A fresh resolution.** A cluster may carry `resolution: {run, supersedes, why}`:
the specific member's resolution is the one in `run`, and each named
`{run, prediction_id}` sidecar is left out and reported in scores.json under
`restatements.superseded_resolutions`. That is the only way one prediction may
have a resolution in two runs. A superseded sidecar that is not on disk is
refused, and a prior priced over a different window than the fresh resolution is
still refused.

**The page.** A restated record carries `restated_by`, is not a card of its own,
and is listed under its specific member as "Also said on <date>: <quote>". The
Predictions column counts it as Restated, and the prose counts each past-due
prediction once. A cluster only partly on the page, or a row whose
`restated:<id>` disagrees with the block, refuses the render.

Proof: `scripts/test_restatements_scoring.py`, `scripts/test_build_restatement_manifest.py`,
and the RESTATED checks in `scripts/test_predictions_site.py`.

## Statement-date overrides, 2026-09-28

VP-16. A YouTube upload date stands in for the date of speech, and on an old
recording it creates a wrong deadline. The fix re-dates the RECORDING, not the
record: a reviewed file, `<data>/predictions/statement_date_overrides.json` in
production or `--date-overrides` for an experiment, maps a transcript id to its
true date, its basis, a source URL, verbatim evidence, and who confirmed it when.

`predictions_lib.apply_statement_date_override` applies it when extraction reads
a transcript, which is the one point both extract and verify pass through. The
prompt header, the input hash and the record therefore agree. The record carries
basis `sourced_override` and a `statement_date_override` block that names the
date it replaced. The loader refuses an unknown transcript, a malformed date, a
date after the transcript's own upload or publication date, and a missing or
unknown field. The transcript must then be re-extracted, because its claim text
and target date were written against the wrong year.

When the override file is read, `phase2_resolvability.load` leaves out every
record of that transcript that was extracted under another date, and names it.
`score_predictions.py` drops and names every resolution or prior that does not
record the override date. So a re-extracted prediction counts once whether or
not its id changed. The scorer reads the production file whenever it exists, a
`scoring.json` that exists alongside it must name it as `date_overrides`, and
the file is hashed into `inputs_sha256`. Proof:
`.venv/bin/python scripts/test_statement_date_override.py`.

First use, experiment `date-override-20260927`: Marc Andreessen's Netscape
keynote, 1996-10-16, uploaded 2013-07-05. Re-extracted, the claim reads "within
the next couple of months after October 16, 1996", deadline 1996-12-31. It was
priced blind at p = 0.40 and resolved `unresolvable: no_public_evidence`, so it
still does not score.
