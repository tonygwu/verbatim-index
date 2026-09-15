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
