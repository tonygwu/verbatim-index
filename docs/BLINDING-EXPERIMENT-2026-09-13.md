# Does the blinding defect move the score?

**Answer: no, not by an amount this board can see.** Pooled over 48 paired
gradings the corrected blinding moves a grade by **-0.14 points**, 95% CI
[-1.15, +0.88], against a minimum detectable effect of 1.45. The corpus is NOT
re-derived. The fix ships for future grades only.

Run 2026-09-13. Fix under test: commit `528509a`.

## What was under test

`blind()` applied every entry of `data/sources/aliases.json` unconditionally
through the NAME path, so a bare part of a multi-word company name was redacted
out of ordinary prose and stamped `[SUBJECT]`. Measured by blinding all 664
transcripts both ways and diffing:

```
ordinary words handed back    1,859   135 transcripts   15 leaders
[SUBJECT] -> [COMPANY]       13,223   every transcript  50 leaders
```

Two treatments, so two pre-specified strata. The split was fixed from the text
diff BEFORE any grading, not chosen after seeing results.

| stratum | leaders | what changes |
|---|---|---|
| PROSE | yann-lecun, fei-fei-li, tim-sweeney, thomas-kurian | 25-100 ordinary words restored per transcript |
| RELABEL | clem-delangue, dara-khosrowshahi | 0-6 words, but 16-63 company references stop reading `[SUBJECT]` |

## Method

18 transcripts, the worst-hit three from each of the six worst leaders. **This
selects the top of the damage distribution deliberately, so the result bounds
the corpus-wide effect from ABOVE rather than estimating its mean.**

Arm A is the blinding on the published board. Arm B is the corrected blinding.
Both arms were graded FRESH and CONCURRENTLY against a frozen snapshot.

Grading arm B against the grades already on disk would have been cheaper and
wrong: Fable's re-run drift is +2.44 points with a within-transcript sd of 3.24
against grades 1 to 4 days old, which is larger than the effect being chased.
Running both arms in the same window puts that drift on both sides of the pair,
where it cancels. This is the trap `docs/CORPUS-INTEGRITY-FOLLOWUP.md` recorded
and it is the reason the design looks more expensive than it needs to be.

VERIFIED before any judge call: arm A reproduces the on-disk blinded text for
all 18 transcripts, byte for byte, 18 verified and 0 mismatched. `word_count`
is held fixed across arms, so the only difference reaching a judge is the text.

## Result

```
POOLED  n=48  mean B-A -0.14  sd 3.58  se 0.52  t=-0.26
        95% CI [-1.15, +0.88]        MDE at 80% power 1.45

PROSE    n=32  -0.35  95% CI [-1.40, +0.71]
RELABEL  n=16  +0.28  95% CI [-1.95, +2.52]

astra    n=16  +0.41  95% CI [-0.36, +1.17]
fable    n=15  +0.43  95% CI [-1.08, +1.95]
gemini   n=17  -1.15  95% CI [-3.56, +1.27]
```

Every stratum, every judge and every leader straddles zero. The largest leader
figure is thomas-kurian at -0.81.

**Dose-response is the check that settles it.** If removing ordinary words
degraded the grade, restoring them would raise it, and restoring more would
raise it more. Across the 18 transcripts the correlation between words restored
and the change in grade is **-0.151**, and against the per-1000-word rate
**-0.089**. Both are near zero and both point the WRONG WAY for a corruption
effect. The transcript with the most damage in the entire corpus,
`yann-lecun/lex-fridman-sgzmel` at 100 words restored, moved -0.65.

The most useful number here is the sd of the paired difference, 3.58. Fable's
own re-run sd on an unchanged transcript is 3.24 and Gemini's is 4.30. The
spread between arms is therefore about what the same judge produces grading the
same text twice. This experiment is mostly measuring judge noise, which is the
honest reading of a null result rather than a weakness in it.

## Why the judges did not care

Consistent with what this repo already knows. Blinding does not work: judges
identify the speaker on 99.5% of transcripts and are right 99.6% of the time,
because what survives redaction is the argument rather than the nouns. A judge
that already knows it is reading Yann LeCun is not confused by
`artificial [SUBJECT]`; it reads through the hole. The smoke-test grade for this
very experiment came back with `identity_guess` = "Thomas Kurian, CEO of Google
Cloud" off a blinded transcript.

## Caveats, each of which limits the conclusion

- **Upper bound, not an average.** The 18 are the worst-damaged in the corpus.
  The typical transcript changes less.
- **MDE 1.45 points.** An effect smaller than that would not have been
  detected. The claim is "nothing the board can resolve", not "exactly zero".
  For scale, 1 of 49 adjacent pairs on the board separates at 95%.
- **6 of 54 pairs were lost**, so n=48. Three to Fable quota, which is why the
  fable arm has n=15 against gemini's 17. The missing pairs are listed below and
  are spread across leaders rather than concentrated, so they do not bias a
  stratum.
- **Gemini's -1.15 is the largest single-judge figure** and it is not evidence
  of anything: its CI is [-3.56, +1.27] and its own re-run sd is 4.30.
- **Single repeat per arm.** `--repeats 1`, as the whole corpus is.

## Failure taxonomy

Never a bare count.

```
arm A   auth_or_quota 2   model_identity_mismatch 1   schema_validation_failed 1
arm B   auth_or_quota 2   model_identity_mismatch 1   json_parse_error 2
```

`auth_or_quota` is Fable's 5-hour window closing mid-run, not an account fault.
Both accounts holding weekly Fable quota, `.claude-c` and `.claude-e`, had spent
their 5-hour windows; the two accounts with 5-hour room hold no Fable quota.
An earlier start of this run also lost 3 calls to a pinning mistake:
`--fable-accounts` was set to `claude-e,claude-c` on the strength of
`quotapick`'s weekly Fable column, but pinning IGNORES measured headroom by
design, and `.claude-c`'s binding 5-hour window was already at 0. Read the
window that binds, not the one that looks reassuring.

`model_identity_mismatch` on the Astra arm does NOT mean another model answered.
`codex --json` names no model at all, so that arm asserts on reasoning tokens
instead (`scripts/grade.py:851`), and zero of them means max effort did not take
effect. It fired twice in about 50 Astra calls.

Unpaired gradings:

```
astra   clem-delangue/the-robot-brains-podcast    arm B missing
astra   thomas-kurian/singapore-fintech-festiv    arm A missing
fable   fei-fei-li/lenny-s-podcast                arm B missing
fable   tim-sweeney/under-ug                      neither arm
fable   yann-lecun/nikhil-kamath                  neither arm
gemini  dara-khosrowshahi/cnbc-television         arm B missing
```

## Decision

Do not re-derive the corpus. Re-grading 664 transcripts across three judges
would cost about 1,992 calls to move a number by an amount smaller than the
noise in the number. That is the same conclusion the wrong-year experiment
reached for the same reason, and the third time in this repo that a defect which
looked alarming in the text turned out not to reach the score.

What the fix is still worth: the blinded text stops being wrong, the next roster
expansion does not repeat it, and a company reference stops being labelled as
the person. Those are correctness wins that do not need a score change to
justify them.

## Re-deriving this

The snapshot, both grade sets and `analyse.py` are under the session scratchpad
`blind-exp/`, which is temporary. The selection and both arms rebuild from
`data/transcripts_open` plus `scripts/blind_wordlist.json`; `blind()` with no
`wordlist` argument is arm A and with it is arm B.
