---
name: leader-transcript-grader
description: Score a single transcript of a technology business leader speaking in public — an interview, podcast appearance, keynote, fireside chat, or panel — on clarity of communication, unique insight, and technical and industry depth. Use whenever asked to evaluate how impressive, insightful, or substantive a leader is from what they said, to grade or re-grade a speaking transcript, to audit a grade another judge produced, or to compare two leaders on demonstrated thinking. Scores ONLY from the words in the transcript, never from knowledge of the speaker or how their company is performing. Produces per-dimension scores with written reasoning, short attributed evidence quotes, counterevidence, and an explicit coverage figure.
---

# Grading a leader's speaking transcript

## What this skill is for

You are given one transcript of one person speaking in public. You return a
structured judgement of the thinking that transcript demonstrates.

You are **not** assessing intelligence, character, or fitness to lead. You are
assessing what this particular transcript shows about how the speaker frames
problems, reasons about mechanisms, handles uncertainty, and understands their
industry.

## Before you score, read `RUBRIC.md`

`RUBRIC.md` in this skill directory carries the full definitions, the 1–5
sub-criteria, the 1–100 anchors for each dimension, and the list of things you
must **not** reward. Read it. Do not score from the summary below.

The three dimensions and their weights:

| Dimension | Weight | Question it answers |
| --- | --- | --- |
| D1 Clarity of communication | 20% | Can a listener reconstruct the speaker's model? |
| D2 Unique insight | 45% | Are the points non-obvious, load-bearing, and honestly held? |
| D3 Technical and industry depth | 35% | Do they understand the machinery, magnitudes, and terrain? |

`overall = 0.20 × D1 + 0.45 × D2 + 0.35 × D3`

## The five rules that decide whether a grade is any good

1. **Transcript only.** Nothing you know about the speaker or their company
   enters the score. Not their results, not their reputation, not what happened
   after they spoke. If the transcript is blinded and you recognise the speaker
   anyway, record that in `identity_guess` and set it aside.

2. **Attribute before you score.** Auto-generated captions carry no speaker
   labels. Work out from context which turns are the subject's and which are
   the interviewer's, and score only the subject's. An interviewer's incisive
   question is not the subject's insight. State your attribution confidence.

3. **Not observed is an answer.** A keynote cannot show how someone handles a
   changed premise. Mark those sub-criteria `not_observed` instead of assigning
   a middling number. Coverage is reported; a thin score is more honest than a
   padded one.

4. **Fluency is not insight.** A confident, well-delivered non-answer scores
   low. A halting answer carrying a precise causal model scores high. This
   inversion is the whole point of the exercise, and it is the error most
   easily made.

5. **Show the counterevidence.** For every dimension, name the strongest thing
   in the transcript that argues against your score. A score with no
   counterevidence was not examined.

## Procedure

1. Read the whole transcript before scoring anything. Note the format, roughly
   how much of the talking the subject does, and how hard the questions are.
2. Set `venue_type` and `venue_challenge` (1–5, defined in `RUBRIC.md`).
3. Score the 15 sub-criteria, each 1–5 or `not_observed`.
4. Assign D1, D2 and D3 on the 1–100 scale, anchored by the sub-scores and the
   band descriptions. Check each against the anchors before committing.
5. For each dimension write `reasoning` in your own words, then two to four
   `evidence` quotes of **25 words or fewer each** with timestamps, then
   `counterevidence`.
6. Compute `overall` with the weights above.
7. Set `coverage` (share of sub-criteria scored) and `confidence` (low, medium
   or high) with a stated reason.

## Calibration

Use the full scale. 50 is genuinely ordinary for a senior technology executive.
Short promotional television segments should mostly land in the 30s and 40s on
insight, because a six-minute hit cannot demonstrate more than that. Resist
compressing everyone into the 70s because they are accomplished people.

## Output

Return one JSON object matching `judge_output.schema.json` in this directory.
No prose outside the JSON. Every score carries its reasoning, because the whole
record is meant to be audited by a human who may disagree with you.
