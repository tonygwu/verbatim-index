# P10 sample-size check for G-judge-lean (2026-10-11)

**Result: the projection is above 2.0, so at the planned size G-judge-lean will likely be INCONCLUSIVE.**
The plan (`docs/PUNDITS-PLAN.md`, P10) asks for this check after the pilot and before P9, so that the operator
can add people or accept a likely INCONCLUSIVE. This is that report. It needs a decision before P9 starts.

## What was measured

From the P8a pilot's blinded grades in the pundits data repository (`grades/fable`, `grades/gemini`):
77 recordings of 10 people that both judges graded with no validation error.
For each recording, d is Fable's `overall` minus Gemini's. With two judges, "each judge's left-minus-right gap
minus the other judges' gaps" is the left-minus-right difference in d.

| Quantity | Plan's assumption | Pilot |
|---|---|---|
| Spread of d across recordings (sd) | 5 | 7.029 |
| Share of d's variance between people (ICC) | 0.3 | 0.414 |

## Projected 90% half-width at 12 recordings per person

| Left / right people | Half-width | Bootstrap 5% to 95% (people resampled, 2,000 times) |
|---|---|---|
| 20/20 | 2.488 | 1.497 to 3.063 |
| 16/16 | 2.782 | 1.674 to 3.425 |
| 13/13 | 3.086 | 1.857 to 3.799 |

The equivalence margin is 3, so a half-width above 2.0 leaves too little room for a pass, and at 13 / 13 the
half-width is above the margin itself. Heterodox people do not enter the left-minus-right gap, so the split is
the number of left and right people, not the roster size. No lean label was read: the split is a parameter.

**What would bring it to 2.0.** About 31 people per side at 12 recordings each. More recordings per person
barely help, because the person-level share dominates: 29 per side at 24 recordings, and still 28 per side
with unlimited recordings.

## Options for the operator

- Add people before P9: about 62 left and right people, against the roster's 39 in all.
- Accept a likely INCONCLUSIVE for G-judge-lean and disclose it, which the plan allows.
- Re-measure after P9 on the full corpus. Ten pilot people make the ICC uncertain: its bootstrap range puts the
  20 / 20 half-width anywhere from 1.497 to 3.063.

## Method and stated choices

`scripts/pundits_sample_size.py` (test: `scripts/test_pundits_sample_size.py`). Raw `overall` scores, because
calibration adds a constant per judge that the model's judge term absorbs. ICC(1) from a one-way ANOVA with
unequal group sizes, floored at 0. A person's mean d has variance sd^2 x (ICC + (1 - ICC) / m), and the half-width
is 1.645 x sqrt(that x (1/nL + 1/nR)).

**A discrepancy with the plan.** The plan says its assumption (sd 5, ICC 0.3) gives "about 2.0". This formula
gives 1.557 for it at 20 / 20. Either the plan used another formula or
a smaller split; the pilot figures above exceed 2.0 under either reading.

Reproduce: `.venv/bin/python scripts/pundits_sample_size.py --data <pundits data checkout>`.
