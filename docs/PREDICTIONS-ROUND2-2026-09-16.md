# Getting unscored leaders onto the board, round 2, 2026-09-16

Goal set by the operator: take ten people from no number to a number on
verbatim-predictions.tonygwu.com. The floor is `MIN_SCORED_TO_RANK = 3`,
confirmed live rather than from source (see "The floor" below).

Run directory: `data/predictions/_experiments/supplemental-round2-2026-09-16/`.
Clone: repo-1, `verbatim.role=experiment`. Nothing here is integrated. Only
repo-0 moves any of it into the shared corpus or publishes from it.

## The answer first

**Thirteen leaders crossed the floor, against a goal of ten. The board goes 15
ranked to 28, and 117 scored to 189.** MEASURED end to end on 2026-09-16:

```
slug                live   now   score    hit   mean p
arvind-krishna        0     17   -0.008   0.71   0.70
vlad-tenev            0     11   -0.207   0.55   0.64
satya-nadella         1     10   +0.269   1.00   0.84
bill-gates            1      7   -0.238   0.57   0.66
dylan-field           1      6   -0.326   0.67   0.87
brian-chesky          1      5   +0.233   1.00   0.85
lip-bu-tan            1      5   -0.028   0.80   0.82
sam-altman            0      4   -0.217   0.50   0.62
tim-sweeney           1      4   -0.465   0.00   0.15
patrick-collison      1      3   +0.319   1.00   0.81
thomas-kurian         1      3   +0.119   0.67   0.55
eric-schmidt          1      3   +0.013   0.67   0.63
amjad-masad           2      3   -0.221   0.67   0.76
michael-dell          0      2   +0.160   0.50   0.36   still under
```

Nobody fell below the floor. Five of the thirteen needed no new sourcing at all,
appearing purely from scoring three finished pieces of work together for the
first time. Eight came from round-2 discovery.

Every pass was clean: resolve 84 attempted / 84 succeeded / 0 failed with an
empty taxonomy, prior 84 / 84 / 0. The only failures in the whole run were three
transient upstream timeouts during wave-1 extraction, which retried themselves.

### The measurement was not taken against a moving target

repo-0 was writing to production throughout, so the corpus was fingerprinted
before and after, twice, and came back identical each time:

```
f2afb8e2f719a1abf539c6310ea3d9883970b85b8af2bd6f222e2bb8983419fa   763 files
```

Without that check the number is unfalsifiable. This repo's method note says to
snapshot before running arms against a corpus; the same applies when somebody
else is editing it.

### Four rows sharpen the board rather than pad it

This is the result worth more than the count, and it answers the warning in
`PREDICTION-SOURCING-2026-09-15.md` that recruiting roadmap CEOs pads the board
without sharpening it.

```
SHARPENING, scored on real disagreement
  tim-sweeney   mean p 0.15   hit 0.00   -0.465
  sam-altman    mean p 0.62   hit 0.50   -0.217
  vlad-tenev    mean p 0.64   hit 0.55   -0.207
  bill-gates    mean p 0.66   hit 0.57   -0.238

PADDING, near-zero-information by construction
  satya-nadella mean p 0.84   hit 1.00   +0.269
  brian-chesky  mean p 0.85   hit 1.00   +0.233
  dylan-field   mean p 0.87   hit 0.67   -0.326
```

**tim-sweeney is the single most informative new row.** He made
low-probability calls, priced at a mean of 0.15, and none of them landed. That
is precisely the row the log-score rule exists to price, and it is the opposite
of a CEO restating published guidance. The sourcing that produced him was Epic v.
Apple sworn trial testimony, where he was under oath and defining his own
thresholds under cross-examination.

The roadmap risk was real and it did materialise for three leaders. It did not
dominate, because trial testimony, congressional testimony and dated
contrarian claims entered the corpus alongside the earnings calls.

### Reproduce it

```
.venv/bin/python scripts/score_predictions.py \
    --run  <run dir, with repo-2's resolutions and priors merged in> \
    --predictions <production>/predictions \
    --predictions <run dir>/results \
    --as-of 2026-09-16 --min-lead-days 60 --trend
```

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

## Discovery results, as they land

Counted from `<run>/findings/<slug>.json`. A PAST-DUE QUOTE is a verbatim
sentence the agent believes passes all five gates AND whose deadline had passed
by 2026-09-16. It is a lead, not an accepted prediction: the extractor and the
verifier still have to agree, and the corpus keep rate is about a third.

```
leader            scored need  srcs  past-due  fetched 
satya-nadella     1      2     14    18        13      
vlad-tenev        0      3     13    9         13      
arvind-krishna    0      3     11    13        11      
tim-sweeney       1      2     12    6         9       
demis-hassabis    0      3     10    3         9       
mustafa-suleyman  1      2     10    3         9       
bill-gates        1      2     7     8         7       
sam-altman        0      3     8     8         7       
eric-schmidt      1      2     10    4         7       
michael-dell      0      3     8     7         5       
dylan-field       1      2     13    8         4       
brian-armstrong   0      3     8     5         0       
dario-amodei      1      2     10    1         0       
george-hotz       1      2     8     1         0       
yann-lecun        1      2     8     1         0       
TOTAL                          150   95        94      
```

All sixteen agents reported. `srcs` is what the agent judged usable, `past-due`
is verbatim quotes it believes pass all five gates with a deadline already
passed, and `fetched` is what survived robots, paywalls, the 400-word floor and
the verbatim cross-check. A past-due quote is a LEAD, not an accepted
prediction.

**Four leaders are real negatives and were never fetched.** Each returned one
past-due gate-passing quote against a need of two or three, so even a perfect
pipeline run leaves them short. dario-amodei hedges his near-dated claims with
"could" and "may" and dates his firm ones to 2027 and beyond. george-hotz's
agent crawled all 143 posts of his blog and all 93 of comma.ai's, and across 236
first-person documents found five sentences pairing a commitment verb with a
time marker, four landing in 2031 or later. yann-lecun's read about 200,000
words over 26 transcripts. demis-hassabis has two distinct past-due predictions
and one of them is six words long, which will not survive the stands-alone gate.
These are properties of how these people speak, not shortfalls of searching.

**brian-armstrong was lost at FETCH, not at discovery**, and that is a different
failure worth separating. His agent found 5 past-due quotes, then two things
killed the sources. Coinbase's quarterly shareholder letters are not signed by
him at all: grepping all five EX-99.1 filings for "Armstrong", "Brian" and
"Sincerely" returns zero hits, so the densest lead in his brief fails own-voice.
His fallback, MarketBeat's speaker-labelled transcripts, serves nav-only bodies
to a plain fetcher, and 7 of 8 came back under the 400-word floor. Nothing was
written for him.

**Two veins found here are worth reusing.** Every vlad-tenev quote is a
Robinhood earnings call on fool.com, whose pages print their own call date,
which is the direct cure for the `deadline_incoherent` failures his existing
predictions died of. And michael-dell's material sits in SEC Rule 425 merger
filings, where Dell filed a 38,000-word analyst-meeting transcript as open
verbatim text. Both are dated, primary and speaker-labelled by construction.
arvind-krishna is the same shape: IBM publishes a prepared-remarks PDF per
quarter, which separates him from CFO Jim Kavanaugh cleanly, and his IBM Quantum
roadmap commitments name a qubit count and a year that IBM itself then reports
against.

**The CFO problem was handled at discovery rather than at verification** for
tenev, krishna and dell, by checking each quote against its nearest preceding
speaker label. This repo has historically caught that at the verifier, after
paying for the call.

**dario-amodei is a genuine negative and is dropped from the target list.** Ten
sources read, twenty-two URLs checked, and exactly one past-due gate-passing
quote. The cause is specific and is not a shortage of material: his near-dated
claims hedge, with "could", "may" and "a substantial risk", so they fail the
COMMITTED gate even though their deadlines have passed, while the claims he
states firmly point at 2027 and beyond and so fail past-due. Both of the leads
this run briefed him with failed on inspection. The interpretability target is
2027, and the biological-weapons uplift claim is a risk statement inside a
conditional. He cannot reach three from this sweep and no amount of further
searching changes the shape of how he speaks.

**Two date defects worth inheriting**, both caught by discovery agents rather
than downstream.

`gatesfoundation.org` serves JSON-LD `datePublished` of `2012-11-13` for the
2012 annual letter and `2013-11-13` for the 2013 one. The identical 11-13 on
both is a content-management migration stamp, not a writing date; each letter's
own text places it in January. The agent took the LATER reading, which is the
conservative one for lead time, recorded the caveat in the source, and checked
that no gate outcome depends on the choice because every deadline involved is
2015-12-31. That matters here more than elsewhere: four of Bill Gates's existing
past-due predictions are already lost to `deadline_incoherent`, which is this
same failure arriving through a YouTube upload date.

Microsoft's annual-report letters carry NO date the page will admit to, so six
of Nadella's sources are written with basis `unknown`. A dateless record cannot
carry a horizon, so those predictions cannot become eligible. This is the
fetcher refusing to invent a date, which is correct, and the cost is visible
rather than hidden.

## How to finish this run

Written down because the run outlives a session and the next person should not
have to reconstruct the argument list. Every command is resumable. `--as-of` is
always passed explicitly, never taken from the clock.

```
RUN=data/predictions/_experiments/supplemental-round2-2026-09-16

# 1. extract and verify. Re-running RESUMES: only status=="ok" is cached, so the
#    transient timeouts retry by themselves. Do NOT pass --force; round 1
#    recorded that forcing a resume marked completed extractions as failed while
#    their records survived on disk, leaving the meta disagreeing with the data.
.venv/bin/python scripts/extract_predictions.py --stage both \
    --transcripts $RUN/transcripts --out $RUN/results \
    --extractor astra --verifier gemini --allow-degraded --workers 4

# 2. resolve the past-due ones. Astra, because it has live web search and a
#    resolution must cite a source rather than recall one.
#    --codex-homes IS NOT OPTIONAL. It defaults to empty, which means the
#    AMBIENT CODEX_HOME, which is ~/.codex, which is the account sitting at 0%.
#    Omitting it spent 15 calls in about 3 seconds each on auth_or_quota before
#    the pass was stopped. The startup line tells you which you got:
#    `accounts=['ambient']` is wrong, `accounts=['.codex-b']` is right. Read it
#    before walking away, because the failure is fast, loud in the log and
#    completely silent if nobody looks.
.venv/bin/python scripts/resolve_predictions.py --stage resolve \
    --predictions $RUN/results --out $RUN --as-of 2026-09-16 --workers 4 \
    --codex-homes "$HOME/.codex-b"

# 3. price them. Fable, because it is MEASURED to have no working tools, so the
#    assessor cannot look up what happened and stop being a prior.
.venv/bin/python scripts/resolve_predictions.py --stage prior \
    --predictions $RUN/results --out $RUN --as-of 2026-09-16 --workers 4

# 4. score. --trend is NOT optional; see the trap recorded above.
.venv/bin/python scripts/score_predictions.py --run $RUN \
    --predictions data/predictions \
    --predictions $RUN/results \
    --as-of 2026-09-16 --min-lead-days 60 --trend
```

Both harnesses were verified by TELEMETRY rather than liveness before the pass
was committed to them, because round 1 lost all 38 of its Gemini verifications
when the Antigravity accounts silently left the router config:

```
astra   real call on codex_b; raw response carries the answer
gemini  served_model == requested_model == gemini-3.8-flash-high,
        profile gptwufamily@gmail.com, zero tool calls
```

A trivial probe to Astra is REFUSED by the pipeline's own guard with
`model_identity_mismatch: no reasoning tokens reported`. That is the guard
working. The name reads as "another model answered" and it means "your prompt
was too easy to reason about"; it is already recorded at
`docs/BLINDING-EXPERIMENT-2026-09-13.md:124`.

## Cross-leader contamination, checked rather than assumed

Two discovery agents independently reported that a sibling agent overwrote a
shared scratch file, and in one case two of Mustafa Suleyman's quotes reached
Dylan Field's working draft. Both caught it, moved to private subdirectories and
re-verified every quote they report. This is the wrong-person failure this repo
has already paid 44 recordings for, arriving from a new direction: not a wrong
video, but one person's words under another's name because two processes shared
a filename.

Verified over the whole run rather than taken on the agents' word:

```
quotes claimed by more than one leader        0
source URLs claimed by more than one leader   0
fetched evidence quotes                      76 claimed, 73 ground byte-exact
                                              in their own source text
```

The three that miss are recorded as `missing` and never become evidence. The
exact-match grounding check is what makes this survivable, because a quote must
appear verbatim on its own fetched page. **A fuzzy match here would let this
class through**, which is the reason `locate_quote` has no fuzzy fallback.

## The round-2 brief roughly doubles the verifier keep rate

MEASURED on wave 1, which is the first pass whose sources were chosen under the
round-2 brief rather than the round-1 one.

```
                                accepted   judged   rate
satya-nadella, wave 1                 27       53   0.51
corpus baseline (gemini verifier)    396     1333   0.297
```

The verifier is doing its job rather than waving records through, which had to
be checked before the rate meant anything. Its gate verdicts across those 53
records are properly mixed:

```
falsifiable=False  25     committed=False  13
forward_looking=False 12  stands_alone=False 7   own_voice=False 4
```

So the improvement is in the SOURCES, not in a slack verifier. That is what the
brief change was for: round 1 asked for quotes passing five gates, round 2 asked
for quotes that also carry a passed deadline, 60 days of lead, a nameable
threshold and a named public route to the answer. Selecting sources on the
downstream conditions, rather than only on the gates, is what moved the rate.

CAVEAT, and it matters for anyone quoting this. This is ONE leader on ONE pass,
and Nadella is unusually favourable: his material is Microsoft earnings calls and
shareholder letters, where he is the one giving dated numeric guidance. The
number to trust is the one measured across all the round-2 leaders at the end of
the run, not this one.

A second, independent gain sits under the same brief: the funnel from an
ACCEPTED record to an ELIGIBLE one. 14 of Nadella's 27 accepted records are past
due and 9 of those are eligible, because the sources were picked for already
having a passed deadline rather than for being interesting.

## A KeyError was the corpus saying "this is not a record"

While counting how many scored predictions sit outside the rendered corpus, a
glob of `data/predictions/*/*.jsonl` raised `KeyError: 'prediction_id'`. The
reflex was to make the counter defensive with `.get("prediction_id")` and
report "54 records carry no prediction_id" as a finding for repo-0. Both halves
were wrong, and repo-0 measured it:

```
skipping _-prefixed directories   1710 records,  0 without an id
inside _-prefixed directories       54 records, 54 without an id
                                  the files are *_errors.jsonl run logs
```

They are not records. `aggregate_predictions.py`, `prediction_inputs_sha256`,
`build_predictions_site.load_records` and `market_consensus.py` all skip
`_`-prefixed directories for exactly this reason, and this repo already carries
commit `3578d3f`, "Stop reading error logs as prediction records". So this is the
SECOND time the same mistake has been made here.

The lesson is about the reflex rather than the glob. **A KeyError on a field
every real record carries is the data telling you the thing is not that kind of
thing.** Catching it converts a loud, correct signal into a silent wrong count,
and then into a false bug report for somebody else. The repo's own rule against
permissive parsers says the same in different words; this is what it looks like
when the permissive parser is three characters long and written in the moment.

What should have happened: ask why a record had no id, find that its directory
starts with `_`, and discover that four production consumers already agree it
should be skipped.

## `pgrep -f` bit again, in a new place

The repo already forbids `pgrep -f` for detecting a running fetcher, after it
failed twice on 2026-09-11. It bit this run too, in monitoring rather than in
the pipeline, and it is worth recording because the symptom is different.

Every "wait until extraction finishes" loop here was written as:

```
until [ "$(pgrep -f extract_predictions.py | wc -l)" = "0" ]; do sleep 300; done
```

`pgrep -f` matches any process whose FULL COMMAND LINE contains the pattern, and
the agent session issuing these shell commands contains it too. So the check
reported 8 to 10 "extractor processes" when there were only ever one or two, and
it could never reach zero, because one of the things it was counting was the
thing doing the counting. Eight such loops were armed before this was noticed.
None would ever have fired.

```
pgrep -f extract_predictions.py          15252 26345 37206 37840 41444 ... (10)
ps -Ao pid,args | awk '/[P]ython.*extract_predictions\.py/'    15252  (1)
```

That is the house's own six-spinning-poll-loops failure arriving through a
monitor rather than through a daemon. Two lessons, and the second is the one
worth keeping. Match the INTERPRETER and the script, not a bare filename, and
bracket the first character so the pattern cannot match itself. And a liveness
check that can never return zero is indistinguishable from a job that never
finishes, so prefer a check you have seen return BOTH answers.

The eight loops were stopped rather than left running.

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
