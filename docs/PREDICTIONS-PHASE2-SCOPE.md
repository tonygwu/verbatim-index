# Phase 2 scope: what a prediction score could honestly cover

Written 2026-09-13. Scoping only. No model calls were spent and no resolution
code was written. Every number here comes from one read-only pass over
`data/predictions`, re-derivable with:

```
.venv/bin/python scripts/phase2_resolvability.py --as-of 2026-09-13
```

`--as-of` is required rather than defaulted, because "past due" depends on the
day the reader asks. Reading it from the local clock is the mistake this repo
already paid for twice.

## The answer first

**A foresight score is not available on this corpus, and adding one would
publish a number carried by one or two people.** Under a definition that keeps
only genuine forecasts, 38 of 475 accepted predictions are scorable today, they
span 21 leaders, and exactly ONE leader reaches five of them. A Brier score, the
proper scoring rule the design reserved, has n=1 across all 50 people.

Relaxing the definition does not rescue it. It changes what the number means.
That is the decision this document exists to put in front of an operator, and it
is a product decision rather than an engineering one.

## The funnel, measured

```
  475  accepted predictions
  325  carry a parseable target date            (-150)
  174  target date on or before 2026-09-13      (-151)
  166  target date not BEFORE the statement date  (-8)
  150  specificity high                          (-16)
   38  outcome NOT under the speaker's own control  (-112)
```

Two stages do almost all the work, and they are different in kind.

**150 predictions carry no target date.** That is by design. `docs/PREDICTIONS.md`
admits undated claims, because "we will get there" is still a falsifiable
prediction. It is not resolvable on a schedule, so it cannot enter a score that
closes on a date. These are not defects and they should not be discarded.

**112 of the past-due, well-specified predictions are under the speaker's own
control.** This is the finding that decides the shape of Phase 2. A CEO saying
"we will ship this next year" is making a commitment about their own company,
not a forecast about the world. Scoring it measures delivery, which is a real
and interesting thing, and it is not foresight. The field already exists per
record as `prediction.subject_control`, so the split costs nothing to apply. The
corpus is 129 own, 24 external and 21 partial among the past-due.

## Per-leader coverage, which is what kills the board

| set | leaders with at least one | leaders reaching 5 | the top of the distribution |
|---|---|---|---|
| past due, any control | 38 of 50 | 12 | andy-jassy 21, lisa-su 20, elon-musk 11, sundar-pichai 11 |
| scorable as foresight | 21 of 50 | 1 | lisa-su 9, elon-musk 4, michael-saylor 4 |

The leaderboard's own floor is `MIN_TRANSCRIPTS_TO_RANK = 5`, chosen as the
high-confidence band. Applied here it leaves a board of one. The Verbatim Index
already refuses to rank a leader on two transcripts; the same reasoning forbids
ranking anyone on four resolved predictions.

## What each scoring framework can actually cover

| framework | what it needs | available today |
|---|---|---|
| Brier `(p - o)^2` | a probability the speaker SAID, plus an outcome | **n=1**. Only 5 of 475 records carry a stated probability, and 1 of those 5 is past due |
| market-relative edge | a contemporaneous market price for the same claim | **n=0**. 0 exact matches of 475; 451 `no_match`, 22 `unavailable`, 2 `failed` |
| hit rate on declarative claims | an outcome, and nothing else | 174 past due, 38 of them foresight rather than commitment |

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

The 174 past-due predictions are concentrated in two categories, and both are
resolvable from public written record rather than from a model's memory.

| category | n | where the outcome is written |
|---|---|---|
| company_business | 113 | earnings releases and 10-K/10-Q filings, company newsrooms, the company's own investor-relations pages |
| technology_product | 43 | product launch pages, release notes, developer blogs, dated press coverage |
| ai_capability | 6 | model cards, benchmark leaderboards, paper release dates |
| market_industry | 5 | industry analyst reports, which are mostly paywalled |
| macro_economy, society, policy_regulation, other | 7 | official statistics, legislative records |

Each record already carries `resolution_criteria` written by the extractor and a
`verifier_criteria` written independently by the verifier. Those are the input to
resolution, and where the two disagree the record needs a human, not a tiebreak
model. That disagreement rate has not been measured and should be, before any
resolution pass is designed: it is free to compute and it sizes the human cost.

## Clear these 8 date defects before resolving anything

Eight past-due predictions target a date BEFORE the statement date of their own
recording, across 5 leaders:

```
andy-jassy   said 2013-05-15 -> target 2011-12-31  ("in 2011")
bill-gates   said 2013-12-29 -> target 2006-12-31  ("by the end of the year") x3
jeff-bezos   said 2015-08-05 -> target 2001-12-31  ("in the year 2001")
lisa-su      said 2019-09-04 -> target 2019-02-07  ("February 7th")
vlad-tenev   said 2026-03-03 -> target 2025-12-31  ("this year") x2
```

The cause is known and is recorded in `CLAUDE.md`: the statement date is the
recording's UPLOAD date, an upper bound rather than the date of speech. A talk
given in 2006 and uploaded in 2013 makes "this year" resolve to 2013 in the
extractor's hands, or to 2006 when the extractor reads the year from the content
and the mismatch surfaces. Either way the resolution window is wrong.

Eight of 325 dated predictions is 2.5%, so this is small. It is also the cheapest
possible signal that the same error is present, undetected, in records where the
target date lands AFTER the statement date and is still the wrong year. The
detector above only catches the direction that is provably impossible.

## Recommendation

Do not build a score. Build resolution, and publish outcomes without a ranking.

A resolved prediction is worth reading on its own: "on 2019-09-04 she said X by
February, and here is what happened." That is the same editorial stance the page
already takes, extended one step. It needs no floor, no calibration, and no
defence of a sample size, and it does not force the own-control question.

If a number is wanted later, the honest first one is a **delivery rate on
own-control claims**, reported separately from anything called foresight and
labelled as what it is. 129 past-due records support it and 12 leaders clear a
floor of five. That is a real measurement about whether these people ship what
they say they will ship. It is not the thing the page currently promises not to
be, so the disclaimer would have to change with it.

## What is not decided here

1. **Resolution by model, by human, or by both.** Not costed. The 174 past-due
   records at three calls each is roughly 520 calls, which is affordable; the
   question is whether a model reading public sources can resolve a claim without
   the hallucination failure this repo has already documented in the judges.
2. **Whether an own-control delivery rate ships at all.** It changes what the
   site claims to be.
3. **Whether the undated 150 are resolved on a rolling basis** or left pending
   for ever. They are a third of the corpus.
