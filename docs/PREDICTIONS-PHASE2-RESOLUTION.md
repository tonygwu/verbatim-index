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

MEASURED: 0 decided outcomes carry an empty source list, and every source carries
a URL.

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

<!-- CALIBRATION TABLE -->

## Open questions

1. **The hindsight probe has not been run yet.** Until it has, the blindness of
   the published p rests on the structural wall and the zero web searches, which
   bound the leak from two directions and do not measure it.
2. **One resolver, no second arm.** Resolutions are single-sourced. An agreement
   rate against a second harness with its own search, such as Gemini, would put a
   number on how often two independent resolvers disagree about the same claim.
3. **The resolver counts a late delivery as a miss**, which is the right rule for
   a dated claim and does push the hit rate down against a prior that priced the
   event rather than the deadline. Whether the assessor should be told to price
   the deadline explicitly is a real design question and is not settled here.
