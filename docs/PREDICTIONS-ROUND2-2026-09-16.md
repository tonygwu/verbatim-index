# Getting unscored leaders onto the board, round 2, 2026-09-16

Goal set by the operator: take ten people from no number to a number on
verbatim-predictions.tonygwu.com. The floor is `MIN_SCORED_TO_RANK = 3`,
confirmed live rather than from source (see "The floor" below).

Run directory: `data/predictions/_experiments/supplemental-round2-2026-09-16/`.
Clone: repo-1, `verbatim.role=experiment`. Nothing here is integrated. Only
repo-0 moves any of it into the shared corpus or publishes from it.

## The answer first

**Five of the ten need no new sourcing and no new model calls. They are already
paid for and sitting on disk.** They appear as soon as the existing supplemental
corpus is scored beside the main one:

```
slug                live   with supplemental   change
amjad-masad          2            3             +1   CROSSES
brian-chesky         1            5             +4   CROSSES
lip-bu-tan           1            5             +4   CROSSES
patrick-collison     1            3             +2   CROSSES
thomas-kurian        1            3             +2   CROSSES
michael-dell         0            1             +1   (still under)
```

Board total goes from 15 ranked to 20. Nobody falls below the floor.

Re-derive it, which costs nothing:

```
.venv/bin/python scripts/score_predictions.py \
    --run  <repo-2 phase2-scoring-20260915> \
    --predictions data/predictions \
    --predictions <that run>/corpus-supplemental-gemini \
    --as-of 2026-09-16 --min-lead-days 60 --trend
```

The remaining five have to come from new sourcing, and that sweep is running.

## What the five are made of, and why they were not already on the board

Three pieces of work that already exist and had never been combined.

1. **repo-1's supplemental web sources**, 89 sources for 14 thin leaders,
   `docs/PREDICTIONS-SUPPLEMENTAL-2026-09-14.md`.
2. **repo-2's Gemini re-verification of them**, 216 of 216, which is what makes
   them comparable with a board that is Gemini-verified on 1,333 of 1,478
   records. Committed on `codex/repo-2-data-2026-09-14` as `4196ff05`.
3. **repo-2's resolutions and priors**, 251 and 252 sidecars, which already
   cover most of the supplemental past-due records because they were run over
   the combined selection.

Nobody had scored 1+2+3 together at floor 3. repo-2's own combined run was
measured at floor 5 and read "9 ranked", so the four leaders sitting at 3 and 5
did not show up as gains. The floor moved to 3 afterwards.

## Two flags on that number, both load-bearing

**It does NOT render as it stands, and the repo already refuses to publish it.**
`score_predictions.py --predictions` is repeatable; `build_predictions_site.py
--predictions` takes ONE directory. Score two corpora and render one and a
person's number is averaged over predictions their own drawer cannot show.
`check_scores_are_renderable` refuses exactly that and names the people, and its
docstring records the case that produced it. So integrating these five means the
supplemental records must join the RENDERED corpus, which is the open question
round 1 left for repo-0: whether they may enter `data/predictions/<slug>/`.
Passing a second `--predictions` to the scorer alone is not enough and will fail
loudly, which is the correct behaviour.

**`--trend` is not optional, and leaving it off silently removes people.** The
published board is generated with it. Without it the same corpus scores 114
rather than 117, and Aaron Levie and Dara Khosrowshahi both drop from 3 to 2 and
leave the board. This was found the hard way here: a first combined run without
the flag appeared to show the supplemental corpus REMOVING two unrelated
leaders' scores. It does not. The flag was the variable, and the corpus was the
thing being blamed. That is the repo's own "compare against a moving target"
trap, arriving as a missing argument rather than a moving corpus.

## What is NOT worth doing, measured rather than assumed

24 past-due records carry no resolution at all. Resolving them looked like the
obvious next lever and it is not worth the quota:

```
slug               scored now   unresolved   of which ELIGIBLE
thomas-kurian           3            8              0
brian-chesky            5            4              0
jack-dorsey             0            3              1
patrick-collison        3            3              0
alex-karp               0            2              0
sergey-brin             0            2              0
amjad-masad             3            1              0
larry-ellison           4            1              1
```

Twenty-two of the 24 belong to leaders who already clear the floor, and only 2
of the 24 are eligible at all. No leader reaches 3 by resolving any of them. The
lever is real and it points nowhere.

## The floor

`MIN_SCORED_TO_RANK = 3`, and this was checked three ways because a peer clone
reported 5 from a checkout that was four commits behind.

```
origin/main tip carries 3                 git branch -r --contains 01ba57c
the live page states 3                    "A row shows no number below 3 resolved predictions"
the live DATA array cuts at 3             40 rows, exactly 15 carrying a score
```

A constant read out of a local checkout is a hypothesis about the repo. `git
ls-remote` and the deployed page are the facts.

## Round 2 sourcing: what changed in the brief

Round 1 asked for predictions that pass the five extraction gates. It found 136
and moved almost nobody onto the scoreboard, because passing the gates is not
the bar. Round 2's brief asks for four more conditions on every lead:

- a deadline that has **already passed** before 2026-09-16,
- at least **60 days** from statement to deadline, which is `MIN_LEAD_DAYS`,
- **high specificity**, a nameable number, threshold or event,
- and a **public route to the answer**, named per quote.

Each discovery agent now reports `deadline`, `lead_days`, `past_due` and
`resolvable_how` beside every verbatim quote, rather than the bare sentence
round 1 collected. The brief is `<run>/AGENT-BRIEF.md`.

That schema change broke the fetcher, which had only ever seen a list of
strings, and the fix is `b8a8a73`: `evidence_quotes()` reads either shape and
refuses anything else BY NAME rather than skipping it, because the grounding
rate is the integrity check on the discovery pass and a silent skip would read
as "the agent paraphrased the page". The same commit stops `record_for` stamping
every record with the literal `supplemental-sources-2026-09-14`, which would
have made every round-2 record claim it came from round 1. Guarded by
`scripts/test_gate_evidence_shapes.py`, 20 checks, verified failing first.

## Quota note worth inheriting

A first launch of 16 discovery agents died within seconds, all 16, on an HTTP
429 naming the WEEKLY window. Nothing was lost because no findings had been
written, and the relaunch after the window reset ran normally. Two things follow.
Split a sweep into waves rather than launching every agent at once, and have
each agent write its output file EARLY and update it, so a wall costs progress
rather than everything.

Separately, a trivial probe to Astra on `codex_b` returns

```
RuntimeError model_identity_mismatch: no reasoning tokens reported;
             max reasoning effort did not take effect.
usage={'input_tokens': 19359, 'output_tokens': 9, 'reasoning_output_tokens': 0}
```

The call SUCCEEDED; the raw response carries the right answer. The guard keys on
`reasoning_output_tokens` being non-zero and a prompt with nothing to reason
about produces zero. The error name says "mismatch", which reads as "another
model answered", and it is not. Already recorded at
`docs/BLINDING-EXPERIMENT-2026-09-13.md:124`; repeated here because two sessions
met it fresh on the same day.
