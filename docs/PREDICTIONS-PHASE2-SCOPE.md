# Phase 2 scope: what a prediction score could honestly cover

Written 2026-09-13. **Revised 2026-09-14: the original funnel was wrong, and the
gate changed.** Scoping only. No model calls were spent and no resolution code
was written. Every number here comes from one read-only pass over
`data/predictions`, re-derivable with:

```
.venv/bin/python scripts/phase2_resolvability.py --as-of 2026-09-14
```

`--as-of` is required rather than defaulted, because "past due" depends on the
day the reader asks. Reading it from the local clock is the mistake this repo
already paid for twice.

## What changed on 2026-09-14, and why the earlier numbers are void

**A parser bug hid 68 predictions.** `prediction.target_date` is documented in
`prediction_record.schema.json` as "YYYY, YYYY-MM or YYYY-MM-DD". The first
version of `phase2_resolvability.py` parsed only the third form, so a bare year
such as `2019` or a year and month such as `2024-06` was discarded as if the
record had no date at all. 68 of 475 accepted predictions are in that state, and
they are not the weak ones: 65 have `horizon: explicit`, meaning the speaker
named the date out loud, and 60 have `specificity: high`. A partial date now
expands to its LAST day, because the claim is a deadline. "In 2019" is false only
once 2019 is over. Any figure in this document's earlier revision that begins
"325 carry a parseable target date" or "38 of 475" is a record of that bug and
must not be quoted.

**The gate is now a lead-time floor, not `subject_control`.** Control separates
"about my company" from "about the world". It does not separate a forecast from
an announcement, and the earlier revision used it for the second job. Both of
these are `control: own` and past due:

> elon-musk, 2022-08-05: "we launch more satellites almost every week so... next 12 months probably do 60 70 launches maybe more"

> andy-jassy, 2020-12-11: "our G4ad instances which are coming in a week"

The first is a real forecast with real uncertainty. The second is a press
release. What separates them is how far out the claim reaches, and the measured
lead times say so: within the past-due high-specificity set, `own` has a median
lead of 220 days and a bottom tenth of 11 days, while `external` has a median of
849 days. The floor is **180 days**, six months, decided by the operator on
2026-09-14. Control is now REPORTED at every stage instead of deciding
membership, so a reader can discount the mix themselves.

**A deadline may be DERIVED from a relative horizon.** A record with no
`target_date` but a stated horizon such as "in the next few years" is anchored on
its statement date. A range closes at its upper bound, because "10 to 15 years"
is falsified only after 15. Whole years and months move by the calendar rather
than by 365.25 days, so the deadline lands on the anniversary. Text that names no
closing date is REFUSED with its reason and counted, never guessed at:
`open_ended` ("in my lifetime", "or more", "five plus years"), `recurring`
("every three months"), `event_anchored` ("as we introduce Mountain Lion"),
`no_statement_date`, `no_horizon_value`. Pass `--no-derive` to switch it off.

## The answer first

**A foresight score is still not available, and the reason has moved.** It is no
longer the size of the past-due set, which is now 225 rather than 174. It is that
a proper scoring rule has nothing to work with: only 5 of 475 accepted
predictions carry a probability the speaker actually said, 1 of those is past
due, and the market pass found 0 exact matches in 475. Those two numbers did not
change and they are what a Brier score and a market-relative edge need.

What IS available is a **resolvable set of 108 predictions across 32 leaders**,
of whom 9 clear a floor of five. That is a real board, and it mixes claims about
the speaker's own company with claims about the world in a ratio of roughly 83 to
25. Whether those belong in one number is a product decision, not an engineering
one, and it is the decision this document exists to put in front of an operator.

## The funnel, measured

```
    475  accepted predictions
           control=own 251  control=external 168  control=partial 56
    398  carry a deadline                          (-77)
           control=own 222  control=external 130  control=partial 46
    225  deadline on or before 2026-09-14          (-173)
           control=own 169  control=external 28  control=partial 28
    214  deadline not BEFORE the statement date    (-11)
           control=own 161  control=external 27  control=partial 26
    191  specificity high                          (-23)
           control=own 148  control=partial 23  control=external 20
    108  lead time >= 180 days                     (-83)
           control=own 83  control=external 16  control=partial 9
```

Where those deadlines came from:

```
  393 stated in prediction.target_date, 5 derived from a relative horizon
     82  no target_date at all
      0  target_date present but malformed
  68 partial dates expanded to their last day
  relative horizons REFUSED:  52 no_horizon_text, 16 no_statement_date,
                               4 open_ended, 3 recurring, 1 event_anchored,
                               1 no_horizon_value
```

**82 predictions carry no target date, and they are three different things.**
57 have `horizon: none`, which is genuinely open-ended: "at some point people are
gonna spend more than half their time talking to models versus humans". Inferring
a date for those invents one, and they stay out. 21 have `horizon: explicit`,
meaning the speaker DID give a horizon that the extractor recorded in
`target_date_text` without resolving. 4 have `horizon: inferable` with
`horizon_years_inferred` filled in and `target_date` still null, which is a
pipeline inconsistency worth fixing at the source.

**Deriving deadlines for those 25 is the right policy and buys almost nothing
today.** It yields 5 deadlines, 3 of them past due, and 0 reach the final set
because all 3 are `specificity: medium`. The reason is not the policy. 11 of the
21 sit on recordings with NO statement date, so there is no anchor to add a
horizon to, and that is the upload-date problem arriving in a new place. Most of
the rest are not deadlines at all: "in my lifetime", "Every three months",
"every year", "as we introduce Mountain Lion".

**83 predictions are dropped by the lead-time floor.** These are the
announcements: "coming in a week", "we will be at 500,000 by the end of the
week", "Bonnie is going to give a talk later today". Dropping them is the point
of the floor. The cost is visible and adjustable with `--min-lead-days`:

```
     floor    own  partial  external   TOTAL   leaders reaching 5
        0d    148       22        20     190   11 (of 36 with >=1)
       90d    108       11        17     136   10 (of 32 with >=1)
      180d     83        9        16     108    9 (of 32 with >=1)
      365d     49        5        14      68    4 (of 24 with >=1)
```

## Per-leader coverage

| set | leaders with at least one | leaders reaching 5 | the top of the distribution |
|---|---|---|---|
| past due, any control | 40 of 50 | 13 | andy-jassy 31, lisa-su 22, mark-zuckerberg 15, elon-musk 14, pat-gelsinger 13 |
| past due, high specificity, lead >= 180d | 32 of 50 | 9 | andy-jassy 18, lisa-su 9, mark-zuckerberg 9, sundar-pichai 7, elon-musk 6 |
| the old own-control definition, for comparison | 23 of 50 | 2 | lisa-su 9, elon-musk 5, michael-saylor 4 |

The leaderboard's own floor is `MIN_TRANSCRIPTS_TO_RANK = 5`, chosen as the
high-confidence band. Applied here it leaves a board of 9 people, where the
own-control definition left a board of 2. The Verbatim Index already refuses to
rank a leader on two transcripts, and a board of 9 out of 50 still needs the same
care about who is missing and why.

## What each scoring framework can actually cover

| framework | what it needs | available today |
|---|---|---|
| Brier `(p - o)^2` | a probability the speaker SAID, plus an outcome | **n=1**. Only 5 of 475 records carry a stated probability, and 1 of those 5 is past due |
| market-relative edge | a contemporaneous market price for the same claim | **n=0**. 0 exact matches of 475; 451 `no_match`, 22 `unavailable`, 2 `failed` |
| hit rate on declarative claims | an outcome, and nothing else | 225 past due, 108 of them past a six-month lead-time floor |

The design forbids inventing a `p` for an ordinary declarative claim, and that
rule should hold. It means the only broadly-available framework is a hit rate,
which is a coarse instrument: it cannot separate a bold call that landed from a
safe one, which is the entire reason a proper scoring rule exists.

This also settles **VD-3**, the market-surprise column. The corpus market pass
has now run over all 475 accepted records and returned 0 exact matches, against
the 20% threshold the ledger set. The column is not buildable. Public prediction
markets and the claims these people make in interviews are close to disjoint
sets.

## Evidence sources a resolution pass would read

The 225 past-due predictions are concentrated in two categories, and both are
resolvable from public written record rather than from a model's memory.

| category | n | where the outcome is written |
|---|---|---|
| company_business | 153 | earnings releases and 10-K/10-Q filings, company newsrooms, the company's own investor-relations pages |
| technology_product | 51 | product launch pages, release notes, developer blogs, dated press coverage |
| market_industry | 7 | industry analyst reports, which are mostly paywalled |
| ai_capability | 6 | model cards, benchmark leaderboards, paper release dates |
| other | 5 | mixed; read per record |
| macro_economy, society, policy_regulation | 3 | official statistics, legislative records |

Each record already carries `resolution_criteria` written by the extractor and a
`verifier_criteria` written independently by the verifier. Those are the input to
resolution, and where the two disagree the record needs a human, not a tiebreak
model. That disagreement rate has not been measured and should be, before any
resolution pass is designed: it is free to compute and it sizes the human cost.

## Clear these 11 date defects before resolving anything

Eleven past-due predictions target a date BEFORE the statement date of their own
recording, across 6 leaders. This was 8 across 5 before the parser fix; the three
new ones were invisible because their target dates are bare years:

```
andy-jassy       said 2013-05-15 -> target 2011-12-31  ("in 2011")
arvind-krishna   said 2026-01-29 -> target 2025        ("This year")          NEW
bill-gates       said 2013-12-29 -> target 2010        ("by the end of the decade")  NEW
bill-gates       said 2013-12-29 -> target 2006-12-31  ("by the end of the year")
bill-gates       said 2013-12-29 -> target 2006-12-31  ("this year") x2
bill-gates       said 2013-12-24 -> target 2005        ("this fall")          NEW
jeff-bezos       said 2015-08-05 -> target 2001-12-31  ("in the year 2001")
lisa-su          said 2019-09-04 -> target 2019-02-07  ("February 7th")
vlad-tenev       said 2026-03-03 -> target 2025-12-31  ("this year")
vlad-tenev       said 2026-03-03 -> target 2025-12-16  ("December 16th of this year")
```

The cause is known and is recorded in `CLAUDE.md`: the statement date is the
recording's UPLOAD date, an upper bound rather than the date of speech. A talk
given in 2006 and uploaded in 2013 makes "this year" resolve to 2013 in the
extractor's hands, or to 2006 when the extractor reads the year from the content
and the mismatch surfaces. Either way the resolution window is wrong.

Eleven of 398 dated predictions is 2.8%, so this is small. It is also the cheapest
possible signal that the same error is present, undetected, in records where the
target date lands AFTER the statement date and is still the wrong year. The
detector above only catches the direction that is provably impossible.

## Recommendation

Do not build a foresight score. Build resolution, and publish outcomes without a
ranking.

A resolved prediction is worth reading on its own: "on 2019-09-04 she said X by
February, and here is what happened." That is the same editorial stance the page
already takes, extended one step. It needs no floor, no calibration, and no
defence of a sample size.

That recommendation has not changed. What changed is the size of the job and the
shape of any number that comes after it. 225 past-due predictions are the
resolution queue, and 108 of them clear the six-month floor across 32 leaders,
with 9 clearing a floor of five. If a number ships later, report the
`control` split beside it at every level, because the 108 are 83 claims about the
speaker's own company against 25 about the world, and those are different skills
being averaged into one figure.

The page's Score column exists and is empty, which is the honest state until
resolution runs. See `scripts/build_predictions_site.py`.

## What is not decided here

1. **Resolution by model, by human, or by both.** Not costed. The 225 past-due
   records at three calls each is roughly 675 calls, which is affordable; the
   question is whether a model reading public sources can resolve a claim without
   the hallucination failure this repo has already documented in the judges.
2. **Whether an own-control delivery rate ships at all.** It changes what the
   site claims to be.
3. **Whether the undated 82 are resolved on a rolling basis** or left pending
   for ever. 57 of them are genuinely open-ended and should stay pending; the
   other 25 need a statement date or a better horizon resolution at the source.
4. **Whether the extractor should write `target_date` when it already resolved a
   horizon.** 4 records carry `horizon_years_inferred` with `target_date` null,
   and 21 carry the speaker's own horizon words with no resolved date. Fixing
   that in the pipeline is worth more than deriving it downstream, because the
   extractor holds the transcript and this script does not.
