# Do the two resolution criteria agree? Measured 2026-09-14

`docs/PREDICTIONS-PHASE2-SCOPE.md` asked for this number before any resolution
pass is designed, on the grounds that a record whose two criteria disagree needs
a human rather than a tiebreak model. It is free to compute, so there was no
excuse for leaving it unmeasured. Re-derive with:

```
.venv/bin/python scripts/criteria_agreement.py
.venv/bin/python scripts/criteria_agreement.py --flag polarity --sample 5
```

No model calls were spent and nothing was written to `data/`.

## The answer first

**The headline is not the rate. It is that 26 of 475 records carry a criterion a
resolver would act on incorrectly, and 18 of those carry one that cannot be
resolved at all. Both trace to ONE line in the shared spec.**

A mechanical screen flags 81 of 475 records, 17.1%. That number is not the
disagreement rate and must not be quoted as one. It is a screen, not a judgement:
it reads deadlines, numeric thresholds and polarity, and it cannot tell whether
two differently worded observables mean the same thing. I read the flagged
records by hand and the flags fall into three very different piles.

| pile | n | what it means for a resolution pass |
|---|---|---|
| **the criterion states no direction** | 18 | not resolvable either way; the criterion must be rewritten |
| **the two criteria assert OPPOSITE outcomes** | 8 | resolving one true resolves the other false; a human must pick |
| the verifier pinned a date the extractor left open | 11 | not a contradiction; the pass needs a rule for which date closes |
| equivalent wording in two house styles | 10 | no action |
| the screen is wrong | 9 + some | no action, and the flag needs narrowing |

## The flag table, as the screen prints it

```
     23  threshold_dropped
     21  polarity
     18  deadline_missing_in_one
     18  undirected_criterion
      6  deadline_year
     62  (both call it open-ended: agreement, not a flag)

     81  records carry at least one flag  (17.1% of 475)
    394  records agree on every part a machine can read
```

## The root cause is one line, shared by both models

`ELIGIBILITY.md` G2 is injected into the extractor prompt AND the verifier prompt
through the `{{ELIGIBILITY_POLICY}}` marker. It says:

> write "By \<date or dated event\>, \<observable\> **will / will not** \<threshold\>."

The "will / will not" is meant as "choose one". It is read as text to copy, and 18
verifier criteria copied it verbatim. All 18 are on the verifier side; the
extractor's criterion is directional in every one of the 18, so no record is lost.

The inversions have the same origin. The one field is described three different
ways in three files, and none of the three states the polarity convention:

| file | what it says the criterion is |
|---|---|
| `extractor_output.schema.json` | "By \<date or dated event\>, \<observable\> will / will not \<threshold\>." |
| `prediction_record.schema.json` | "What observation, on or by what date, would show the claim **wrong**." |
| `verifier_output.schema.json` | "In your own words, without reference to the extractor's." |

The second describes a FALSIFICATION condition and the first describes the
PREDICTED OUTCOME. They are opposites. Nothing anywhere says whether a criterion
that resolves TRUE means the speaker was right or wrong. On a prediction whose
content is already negative, such as "machines will not surpass humans", the two
models pick different conventions and the record ends up with two criteria that
assert opposite things.

This is a spec defect, not a model failure. Neither model was told the rule.

## 1. Eighteen criteria state no direction and cannot be resolved

The verifier wrote the test as "X will / will not happen". That is not a
falsifiable criterion, whatever the outcome turns out to be:

> By December 25, 2025, NVIDIA DGX Spark systems **will / will not** be commercially available for customers to obtain.

> By 2029-02-05, the total cost per unit of operating AI compute in space **will / will not** be lower than in any location on Earth.

The extractor's criterion is directional in all 18 cases, so the record is not
lost. A resolution pass must either use the extractor's criterion alone for these
or send them back to the verifier. Detection is mechanically exact, so this count
carries no false positives.

They are not spread evenly across the board, so a per-leader number computed over
unrepaired records would be biased against the leaders carrying most of them.

## 2. Eight pairs assert opposite outcomes

These are the dangerous ones. The two criteria are directional, and they point in
opposite directions, so a resolver that happened to read one rather than the other
would publish the opposite answer about the same quote.

```
bill-gates       E: warming WILL EXCEED 1.5 degrees
                 V: warming WILL NOT EXCEED 1.5 degrees
bret-taylor      E: AI conversations WILL OUTNUMBER website clicks
                 V: AI conversations WILL NOT EXCEED website clicks
brian-armstrong  E: NewLimit WILL HAVE BEGUN human clinical trials
                 V: NewLimit WILL NOT HAVE COMMENCED human clinical trials
tim-sweeney      E: Fortnite WILL NOT HAVE ENTERED an open economy phase
                 V: Fortnite WILL LAUNCH an open economy phase
yann-lecun       E: machines WILL NOT HAVE DEMONSTRATED capabilities surpassing humans
                 V: machines WILL SURPASS humans in all domains
yann-lecun       E: there WILL NOT HAVE BEEN a demonstration of an integrated AI system
                 V: an AI system WILL DEMONSTRATE hierarchical planning
yann-lecun       E: the English translation WILL NOT HAVE BEEN published
                 V: the English translation WILL BE published commercially
sundar-pichai    E: Wing's eligible population WILL REACH 40 million Americans
                 V: the number with access WILL NOT REACH 40 million
```

Three of the eight are Yann LeCun, and the shape is the same each time: he is
predicting that something will NOT happen, the extractor writes the criterion in
his direction, and the verifier writes it in the positive. Whether that is a
disagreement about the claim or two ways of writing one test is exactly the
judgement a human has to make, and it is why this pile cannot be automated away.

## 3. Eleven times the verifier pinned a date the extractor left open

Not contradictions. The extractor wrote "by an unspecified date" and the verifier
committed to one:

> E: By an unspecified date, Replit's reported registered user count will reach double its level at the time of the recording.
> V: Within roughly one year of the recording (by about the end of 2021 to March 2022), Replit's registered user count will reach about 12 million.

A resolution pass needs a written rule for these, because the two criteria close
on different days and the answer can differ between them. The rule is a design
decision, not a defect to fix per record.

## What the screen gets wrong, and why the first version was useless

The first version of `criteria_agreement.py` reported **61.3%** of the corpus as
disagreeing. That was wrong, from three causes, and the sample that exposed it
took two minutes to read. Recorded here because the same three mistakes are easy
to make again:

- **Date components leaked into thresholds.** "By 2013-12-31" against "By
  December 31, 2013" read as the extractor testing a threshold of 12 that the
  verifier dropped. Masking every recognised date span before extracting numbers
  took `threshold_dropped` from 195 to 23.
- **The verifier's falsification rider negates by design.** It habitually appends
  "; a figure short of that would falsify". Comparing polarity across that rider
  flagged 41 records where both were saying the same thing. Polarity is now
  compared on the main clause only.
- **Both saying "unspecified" is agreement.** 62 pairs where neither names a date
  were counted as a disagreement. They agree that the prediction is open-ended.

A fourth mistake came from fixing the third. Treating the open-ended case as an
early return skipped every remaining check, which hid 4 undirected criteria and 4
polarity flags. An undated prediction can still carry a broken criterion. The
counts above are after that fix; an earlier revision of this document said 14 and
7 and was wrong.

`threshold_dropped` is still advisory. I sampled 3 of its 23 and all 3 were
artifacts: a count of 12 restated as a list of 12 cities, and a "5 to 10 year"
horizon read as a threshold. I did not review all 23, so no rate is quoted from
it, and it should be narrowed before anyone leans on it.

## The contract drift, investigated 2026-09-15

While counting the repair cost I found the corpus holds four contract ids and
none matches `POLICY_RELEASE.json`. It is fully explained and nothing is wrong.

```
extraction   d795f6f1d88b (464)   3a54940218c0 (11)      pinned at the time: 99d9132159a2
verification 102275d44824 (472)   63aa6e366a85 (3)       pinned at the time: 820583f899f6
```

Three findings, each checked rather than assumed:

**The current files match the pinned release exactly**, so `load_policy_release`
passes today and no run is failing. The mismatch is between the corpus and the
files, not between the files and the pin.

**The corpus predates `ELIGIBILITY.md`.** That file was created by `b114b24` on
2026-09-12 07:38 UTC. The three runs that built the corpus finished before it:
the pilot at 2026-09-10T09:54Z, the main run at 2026-09-11T02:56Z, and the top-up
at 2026-09-12T02:50Z. `_contract` now inlines `ELIGIBILITY.md` into the spec
before hashing and did not then, so recomputing an old revision with today's
function cannot reproduce an old id. I walked every revision of the five spec
files and confirmed none yields any of the four.

**The minority ids are the pilot.** All 11 odd extraction records come from run
`20260910T095427Z-both-517d1275`, the eleven-transcript pilot recorded in
`docs/PREDICTIONS.md` section 9, and 3 of them also carry the pilot's verifier
contract. The spec changed between the pilot and the main run, which is ordinary
iteration.

**The corpus is on the older contract deliberately.** `648a045` records VD-4:
predictions-2.0 accepts 77% more predictions, and 12 of the 17 candidates that
flip from rejected to accepted carry no target date, so the undated share would
rise from 11% to 40%. An undated claim can never be resolved. The corpus stayed
put on purpose.

Two things worth inheriting. A record carries `contract_id` but NO
`policy_release` field, so the release a record ran under is not recoverable from
the record; only the contract id is, and that id is not reproducible once the
hashing function changes. And the defect fixed below was present in the corpus-era
specs too: the pre-`b114b24` `EXTRACTION.md` and `VERIFICATION.md` each carried
one "will / will not" template, so the refactor into `ELIGIBILITY.md` carried it
forward rather than introducing it.

## The spec is fixed, as release predictions-2.1

`ELIGIBILITY.md` G2 no longer hands either model an undirected template, and it
now states the polarity convention in its own paragraph:

> *State one direction.* The criterion must assert what happens, not offer a
> choice. Never write "will / will not" [...]
>
> *Write it so that TRUE means the speaker was RIGHT.* The criterion states the
> SPEAKER'S predicted outcome, never its falsification. [...] If the speaker says
> "machines will not surpass humans in ten years", the criterion keeps the
> speaker's negation. Do not flip it.

The three field descriptions now carry that one sentence and point at G2, instead
of describing the field three ways. `POLICY_RELEASE.json` is bumped to
**predictions-2.1**, contracts `f2edf433e24e` and `8d9ae41023b1`, because
`read_spec` inlines `ELIGIBILITY.md` into both prompts and `_contract` hashes it.

**The 475 published records are untouched and still carry both defects.** This
stops the next run reproducing them; it repairs nothing already on disk. Note the
VD-4 tension: the corpus is deliberately not on the 2.x line at all, so a future
production run has to settle that question before this fix reaches any record.

`scripts/test_criterion_spec.py` guards it, verified failing 8 checks against the
pre-fix specs. Its pattern uses `\s+` throughout, because the old file wrapped the
template as "will / will\n  not" and a pattern with a literal space walks past it.

## What this means for the resolution pass

0. **Fix the spec first, or every future run reproduces both defects.** Delete
   the "will / will not" template from `ELIGIBILITY.md` G2, and state the polarity
   convention once: a criterion resolves TRUE when the speaker was RIGHT. Align
   the three field descriptions to that sentence. `read_spec` inlines
   `ELIGIBILITY.md` into both prompts, so this changes BOTH contract ids and needs
   a `POLICY_RELEASE.json` bump; `check_policy_release` raises otherwise. The 475
   published records are unaffected, because each records the contract it ran
   under.
1. **Fix the 18 undirected criteria before resolving anything.** The screen names
   them. Re-verifying costs quota: the 39 records carrying an undirected or
   polarity flag sit on 29 transcripts, and re-verifying those re-judges 49
   accepted records rather than 39, because verification runs per transcript.
2. **Route the 8 inversions to a human.** They are the cases where an automated
   resolver would silently publish the opposite answer.
3. **Write the rule for the 11 pinned dates** into the resolution spec, rather
   than deciding it per record.
4. The remaining 394 records agree on every part a machine can read. That is NOT
   proof that they agree, and the screen says so in its own output. It is the
   floor a human review starts from, not a clearance.
