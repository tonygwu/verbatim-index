# Phase 2: resolving predictions and scoring them. Built 2026-09-15

`docs/PREDICTIONS-SCORING.md` left the scoring rule verified and unusable, for
two reasons it named itself: the outcomes came from one reader's recall with no
cited source, and the probabilities were chosen by that same reader after already
knowing how each prediction turned out. This is the build that closes both.

Re-derive any number here with:

```
.venv/bin/python scripts/resolve_predictions.py --stage resolve --as-of 2026-09-14 \
    --out data/predictions/_experiments/phase2-scoring-20260915 --eligible-only --dry-run
.venv/bin/python scripts/score_predictions.py \
    --run data/predictions/_experiments/phase2-scoring-20260915 --as-of 2026-09-14
.venv/bin/python scripts/repair_control.py --n 3        # spends 6 model calls
.venv/bin/python scripts/hindsight_probe.py --run <run> --as-of 2026-09-14 --n 20
```

## Two stages, and why they run on different harnesses

The choice of harness is doing real work here, and it is the part most likely to
be undone by a later change that looks like tidying.

**The resolver runs on Astra, through `codex exec`, because that harness has live
web search.** A resolution has to cite something, and a harness that can only
recall cannot cite. MEASURED over the run: every resolution ran at least one
search, mean 5.2 per call, and 0 ran none.

**The prior assessor runs on Fable, through `claude` with `--permission-prompts
none`, because that harness is measured to have no working tools.** A prior
assessor that can search will look up what happened, and its answer stops being a
prior. MEASURED by reading `server_tool_use.web_search_requests` out of all 156
raw prior responses on disk: **0 web searches in 156 calls.**

That number is not decoration. One prior call, on a 2017 Jeff Bezos claim about
rooftop solar, shows two entries in `permission_denials`, and the queries are

```
Amazon March 2017 announces rooftop solar 15 fulfillment centers 2017 50 by 2020
Amazon rooftop solar fulfillment centers progress completed 2017 sustainability
```

The model reached for exactly what it must not have, twice, and was refused both
times. The sandbox is not a formality on this stage; it is the stage.

## The wall between them

`build_prior_prompt` reads a fixed list of fields through `prompt_facts` and
cannot reach `rec["resolution"]` or any sidecar. `test_resolution_lib.py` proves
it behaviourally rather than by inspection: it attaches a full resolution to the
record, including the outcome and the reasoning, and asserts the prompt does not
move by one byte.

What the wall does NOT do is remove what the model already knows from training,
and 220 of the 225 past-due predictions fall inside its knowledge cutoff. That
is why `hindsight_probe.py` exists and why the blindness claim is published with
a measurement beside it rather than on its own.

### The leak screen reads only what this repo writes

A second, weaker guard scans the prompt for outcome vocabulary. Its first version
scanned the whole prompt and refused the record on a hit, which is fail-loud and
was wrong. MEASURED: 7 of 225 records trip it, and all 7 are the word sitting
inside a quote, a context window or the recorded criterion. Elon Musk and Lisa Su
say "outcome", Patrick Collison says "turned out", Sundar Pichai says "in
hindsight", and one Jeff Bezos criterion contains "occurred" as ordinary English.
Refusing those would have dropped seven real predictions to guard against a leak
that was never there. The screen now masks the quoted fields; 0 of 225 trip it,
and the test proves the mask is load-bearing by showing the same prompt still
trips an unmasked scan.

## "Unresolvable" is an answer, and a resolution with no source is refused

The resolver may answer `occurred`, `not_occurred`, or `unresolvable` with a
reason from a fixed list. Two rules are enforced at validation rather than asked
for in the prompt:

- a decided outcome that cites no source is **rejected**, so no outcome can enter
  the corpus on recall;
- `unresolvable` must carry a reason, and a decided outcome must not.

MEASURED over all 225 resolutions: 0 decided outcomes carry an empty source list,
all 351 cited sources carry a URL, and every resolution ran at least one web
search (mean 5.3, none ran zero).

Declining matters more than it looks. The Aaron Levie record that opened the run
is the case: "our guidance was nearly a billion in revenue this year", said in
May 2022 against a 2022-12-31 deadline. Box's fiscal 2023 revenue was $990.9m,
which looks like a match and is the answer I gave by hand in the earlier pilot.
The resolver noticed that fiscal 2023 **ended on 31 January 2023**, after the
deadline, found no separately reported calendar-2022 figure, and answered
`unresolvable / threshold_unmeasurable`. The hand pilot had scored that
prediction true.

## The criteria repair found nothing to repair, and that is the finding

`docs/PREDICTIONS-CRITERIA-AGREEMENT.md` claimed 26 records carried a criterion a
resolver would act on incorrectly. That headline is now withdrawn in that file.

A resolver reads one field, `prediction.resolution_criteria`, written by the
extractor. The screen flags a record when EITHER that field or the verifier's
carries a defect, and the earlier reading reported the second as the first. Split
by field:

```
undirected, by WHICH criterion carries it:
   18  verifier only
    0  extractor
```

All 39 flagged records were sent through a repair stage that reads the quote. All
39 came back `already_correct`. That is worth nothing unless the stage can fail,
so it was given a negative control: both defects planted into three real records,
six cases, through the identical prompt. **6 of 6 caught**, every one repaired
back to the original text, including two cases where the correct repair was to
KEEP the speaker's negation rather than flip it.

The spec repair in `cfec9e6` was still right. The verifier was being told to
write "will / will not" by the same G2 line. It simply never reached the field
that gets resolved.

## What gets scored, and what does not

A prediction reaches the published number only if it is past due, resolved to a
decided outcome, carries a prior, and clears the operator's eligibility rule:
specificity high, at least 180 days between the statement and the deadline, and a
deadline that does not precede its own statement. The lead-time floor is what
separates a forecast from an announcement, and it is the operator's call from
2026-09-14.

Everything excluded is counted and named in `scores.json` under
`not_scored_because`, so the buckets always add up to the corpus.

`unresolvable` is excluded, never scored as a miss. A claim nobody can settle
says nothing about the speaker, and scoring it as a failure would punish people
for making claims about things the public record does not track.

## Is the assessor calibrated? The question the board depends on

The scoring rule has expected value zero at every p **only if p is the real
probability**. If the prior assessor runs high, every speaker scores negative and
the board measures the assessor rather than the speaker, with nothing on the page
to say so. `score_predictions.py` therefore prints a reliability table on every
run: mean p against hit rate, overall and in five bins, with a binomial interval
so a small corpus does not read as a bias.

```
IS THE PRIOR ASSESSOR CALIBRATED?  n=77  mean p 0.580  hit rate 0.545  gap -0.034
  hit rate and mean p agree within noise (1.96 se 0.112)
      p bin    n  mean p    hit     gap   points
    0.0-0.2    9    0.08   0.00   -0.08   -0.300
    0.2-0.4   14    0.31   0.00   -0.31   -0.814
    0.4-0.6   12    0.52   0.33   -0.19   -0.373
    0.6-0.8   18    0.69   0.83   +0.14   +0.243
    0.8-1.0   24    0.87   0.96   +0.09   +0.136
```

**Overall it is calibrated; by bin it is not.** The gap of -0.034 sits well inside
noise, so the board's mean is not systematically shifted. But the bins are
monotone: everything below 0.6 overshoots and everything above undershoots. That
is the signature of **under-extremity**, the most common miscalibration there is:
the assessor orders predictions well and squashes its probabilities toward 0.5.

The same thing shows up in a second, independent way. `hindsight_probe.py`
computes the separation the assessor achieves between hits and misses, against
the separation a PERFECTLY CALIBRATED assessor would achieve on the same p
distribution, which is fixed at `E[p^2]/E[p]` minus `(E[p]-E[p^2])/(1-E[p])`:

```
                          observed  if calibrated
  mean p | came true        0.759         0.674
  mean p | did not          0.343         0.415
  separation               +0.416        +0.260      excess +0.156
```

An excess means the assessor discriminates better than its own stated confidence
allows. Under-extremity produces exactly that, and so does hindsight, so the
excess alone does not choose between them.

## Did the deadline correction explain it? No, and that is the substantive finding

The first pass priced the EVENT, not the deadline. MEASURED on the 17 scored
misses priced between 0.2 and 0.6: **12 of them happened, just late.** Cybertruck
deliveries, New Shepard's first crewed flight, New Glenn's first launch, Comma's
Navigate on Openpilot, UALink 1.0, AWS Trainium framework support, SWE-bench at
90%. The assessor was pricing "will this happen" while the resolver tests "did
this happen BY the date", so every slipped timeline was charged to the speaker
twice.

The prompt was corrected to say outright that late is false, and both passes are
kept (`priors_v1_event` and `priors`). MEASURED over the 99 predictions priced by
both:

```
  mean p   priors_v1_event: 0.631
  mean p   priors:          0.596
  mean shift -0.035   sd 0.060
  lowered 68, raised 20, unchanged 11
  on predictions that occurred      n=42  mean shift -0.027
  on predictions that not_occurred  n=28  mean shift -0.046
```

Two things follow, and the second matters more.

**The correction is real but small, and it is not hindsight.** It moved p by 3.5
points and moved it in the same direction on hits and misses, -0.027 against
-0.046. Hindsight leaking in would have lowered p on the misses and left the hits
alone.

**Three and a half points cannot explain a thirty-point gap.** So the mid-band
shortfall is not the assessor failing to price slippage. These speakers miss
their own stated deadlines far more often than a well-informed observer standing
on the statement date would predict. That is a real foresight failure and the
score is right to charge it.

## What the gate excludes, measured rather than argued

The eligibility rule keeps a prediction only if it is specific, reaches at least
180 days out, and has a coherent window. That floor is the operator's call. It is
now testable, because the predictions it EXCLUDES were resolved too:

```
ELIGIBLE               n=108   hit rate among decided 0.55   unresolvable 29%
EXCLUDED by the gate   n=117   hit rate among decided 0.82   unresolvable 29%
```

Predictions the floor excludes land **82%** of the time; the ones it keeps land
55%. They really are announcements rather than forecasts, which is what the floor
was for. Note the unresolvable share is the SAME either side, 29%, so the gate is
separating easy claims from hard ones rather than resolvable ones from murky
ones.

## Where the board stands

All 225 past-due predictions are resolved and 77 carry a score. The other 148 are
named rather than dropped: 65 unresolvable, 8 outside the eligibility rule, and
75 resolved but never priced, because the prior stage ran only over the eligible
set once Fable quota became the binding constraint. Three people clear the floor
of five scored predictions.

```
Mark Zuckerberg   6   +0.018   hit 0.83   mean p 0.81
Lisa Su           8   -0.100   hit 0.62   mean p 0.63
Andy Jassy       17   -0.129   hit 0.59   mean p 0.62
```

All three sit near zero, which is the rule working rather than failing. These are
mostly keynote roadmap items with a high p, so keeping one earns little and
missing one costs a lot. A corporate roadmap is a near-zero-information forecast
and the rule reaches that with no special case for it.

## The hindsight probe, and the limit it puts on every number here

**This is the most important caveat in this file and it is not a clean result.**

The wall is structural and the sandbox is measured: the prior prompt cannot reach
a resolution, and 0 of 156 prior calls reached the web. Neither removes what the
model already knows from training, and 220 of the 225 past-due predictions fall
inside its knowledge cutoff. So the question is whether training knowledge leaks
into p, and it has to be measured.

Two measurements, one free and one costing 20 calls.

**Free: does the assessor separate hits from misses by more than calibration
allows?** If p is the true probability the outcome is Bernoulli(p), so the mean p
among predictions that came true is fixed at `E[p^2]/E[p]` and among those that
did not at `(E[p]-E[p^2])/(1-E[p])`. Over 85 resolved pairs:

```
                          observed  if calibrated
  mean p | came true        0.782         0.715
  mean p | did not          0.340         0.409
  separation               +0.442        +0.306     excess +0.136
```

**Paid: ask the same model again with the outcome disclosed.** n=20:

```
  d = p(told) - p(blind), signed toward what happened
  mean +0.092   se 0.030   95% CI [+0.034, +0.151]
  moved toward the outcome in 15 of 20, away in 1, unchanged in 4
```

### What that does and does not establish

**It establishes that the blind run was not already saturated with the outcome.**
Disclosure still moves p by about nine points and the interval excludes zero. A
model that already knew would have had nothing to update on.

**It does not establish that the blind run was clean.** Disclosure raises p on the
hits and lowers it on the misses, so a shift of d toward the outcome is worth
about 2d of separation, here 0.185. The blind run already shows an excess of
0.136, which is **73% of what full hindsight would produce**. Partial leakage is
not excluded by these numbers, and 73% is a large fraction.

That 73% is an UPPER bound on the leaked share rather than an estimate, because
under-extremity produces excess separation on its own and the reliability table
shows under-extremity plainly: every bin below 0.6 overshoots and every bin above
undershoots. How much of the 0.136 each mechanism supplies is not resolved here.

### Which way it biases the board

Toward zero, not toward anyone. A p that is too high on a prediction that came
true shrinks the reward; a p that is too low on one that failed shrinks the
penalty. Both pull a score toward zero, so residual hindsight makes the board
UNDERSTATE the differences between people rather than invent them. A near-zero
score on this board should therefore be read as "no foresight demonstrated here",
never as "foresight disproved".

## Open questions

1. **Under-extremity is measured and NOT corrected.** Recalibrating p on the same
   77 predictions that measured the miscalibration would be circular, and the
   bins hold 9 to 24 records each. It needs either more data or a held-out split.
   Until then a single person's score carries that compression, while the board's
   mean does not, because the overall gap is inside noise.
2. **Apportioning the excess separation needs a held-out design**, not a bigger
   probe. The clean version asks a model with a knowledge cutoff BEFORE the
   deadline, so training leakage is impossible by construction, and compares its
   p with this one. That is the measurement this file cannot substitute for.
3. **One resolver, no second arm.** Resolutions are single-sourced. An agreement
   rate against a second harness with its own search, such as Gemini, would put a
   number on how often two independent resolvers disagree about the same claim.
4. **The resolver counts a late delivery as a miss**, which is the right rule for
   a dated claim and does push the hit rate down against a prior that priced the
   event rather than the deadline. Whether the assessor should be told to price
   the deadline explicitly is a real design question and is not settled here.
