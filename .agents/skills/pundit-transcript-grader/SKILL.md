---
name: pundit-transcript-grader
description: Score one transcript of a political pundit, journalist, podcaster or streamer speaking on the record on intellectual honesty — steel-manning and charity, epistemic rigor and calibration, and good faith and consistency. Use when asked to grade or re-grade such a transcript, to audit a grade another judge produced, or to explain how the Verbatim Pundits rubric applies. Scores ONLY the argumentative behaviour visible in the transcript, never whether the speaker's positions are true, never their reputation, and never their politics.
---

# Grading a pundit's transcript for intellectual honesty

You are given one transcript of one person speaking, often with other people in
the recording. You return one structured judgement of the argumentative
behaviour that transcript shows.

You are **not** judging whether the speaker is right, whether their politics
are good, or whether they are sincere. You are judging how they argue in this
recording: whether they represent the other side fairly, whether their
confidence matches their support, and whether they argue in good faith.

## Read RUBRIC.md before you score

`RUBRIC.md` in this directory holds the definitions, the sub-criteria, the
opportunity rules, the anchors, and the list of things you must not reward or
penalise. Score from it, not from this summary.

| Dimension | Key | Weight |
| --- | --- | --- |
| Steel-manning and charity | `d1_steelmanning` | 35% |
| Epistemic rigor and calibration | `d2_epistemic_rigor` | 35% |
| Good faith and consistency | `d3_good_faith` | 30% |

## The rules that decide whether a grade is any good

1. **Transcript only.** Do not use what you know or can find about the speaker,
   their show, their audience, or events after the recording. Do not search for
   them. If you recognise them anyway, say so in `identity_guess` and set it
   aside.
2. **Attribute before you score.** Captions carry no speaker labels. Work out
   which turns are the subject's. A host's question, a guest's rebuttal and a
   clip the subject plays are not the subject's speech.
3. **Not a fact-check.** A claim that is false is not penalised for being false.
   What is scored is whether the support offered in the recording matches the
   confidence of the claim.
4. **Not observed is an answer.** A monologue with no opposing view in it cannot
   show accurate representation of an opponent. Mark such sub-criteria 0.
5. **Show the counterevidence.** For every dimension, name the strongest thing in
   the transcript that argues against your score.
