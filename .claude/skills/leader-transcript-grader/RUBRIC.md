# Speaking-transcript rubric for technology business leaders

Version 1.0. This rubric scores **the thinking demonstrated in one transcript**.
It does not score a person, a company, or a career.

## The one rule that governs everything else

**Score only what is in the transcript.**

Do not use anything you know about the speaker, their company, their products,
their funding, their stock price, their reputation, or their track record. If
the transcript is blinded, do not try to defeat the blinding. If you recognise
the speaker anyway, say so in `identity_guess` and then set that recognition
aside. A correct prediction that later came true earns nothing here unless the
reasoning behind it is visible in the transcript. A claim that history has
falsified is not penalised either, unless the transcript itself shows the
reasoning was careless at the time.

A well-run company does not raise a score. A struggling one does not lower it.

## What the transcript is, and what that costs you

Transcripts come from automatic speech recognition. Expect three artefacts, and
do not penalise any of them:

- **No speaker labels.** In an interview the questions and the answers run
  together. Infer turn boundaries from context. Score **only the subject's
  speech**. An interviewer's sharp question is not the subject's insight.
- **Mangled proper nouns.** Names, products and technical terms get corrupted.
  Read through the corruption. "Cuber netties" is Kubernetes.
- **No punctuation of thought.** Spoken language is full of restarts and
  filler. Do not confuse disfluency with confusion. A halting answer carrying a
  precise model beats a fluent answer carrying nothing.

## Three headline dimensions, scored 1–100

Each headline dimension is supported by sub-criteria scored 1–5, or marked
`not_observed`. Assign the 1–100 score holistically, anchored by the
sub-scores, then check it against the anchors below.

### D1 — Clarity of communication (weight 20%)

*Can a competent listener reconstruct the speaker's model from what was said?*

| Sub | Name | What it measures |
| --- | --- | --- |
| C1 | Directness | Answers the question actually asked. Does not evade, filibuster, or substitute a different question they preferred. |
| C2 | Structure | The answer has a shape you can follow. Claims are ordered and their relationship is stated, not left implicit. |
| C3 | Concrete language | Plain words with specific referents, instead of slogans, category nouns, and buzzwords standing in for content. |
| C4 | Economy | Signal per unit of speech. Reaches the point without padding, and stops when finished. |

**Anchors.** 1–20: evasive or incoherent; the listener cannot say what was
claimed. 21–40: on-topic but slogan-driven; you retain a mood, not a model.
41–60: clear and followable; ordinary competent executive communication. 61–80:
precise and well-organised; distinctions are drawn explicitly and land. 81–100:
you could restate their position accurately from one hearing, including the
qualifications.

**Do not reward here:** speaking quickly, charisma, humour, a pleasant voice,
sophisticated vocabulary, or confident delivery. Fluency is not clarity. A
polished non-answer scores low on C1 no matter how smooth it is.

### D2 — Unique insight (weight 45%)

*Are the points made non-obvious, load-bearing, and honestly held?*

| Sub | Name | What it measures |
| --- | --- | --- |
| I1 | Causal and counterfactual reasoning | Explains the mechanism by which one thing produces another. Distinguishes competing explanations. Derives what changes if a condition changes. |
| I2 | Originality | Reaches a non-obvious, supported implication that changes what you would predict, investigate, or do. Not mere contrarianism. |
| I3 | Strategic judgment and tradeoffs | Compares the strongest alternatives, names opportunity costs, addresses timing and reversibility, and still commits to a choice. |
| I4 | Systems, incentives, people | Represents customers, employees and rivals as agents with their own goals who adapt, rather than as passive or irrational. |
| I5 | Epistemic calibration | Matches confidence to evidence. Separates what is known from assumed from hoped. Names the unknown that matters most and what would change their mind. |
| I6 | Engagement with opposition | Can state why an informed person would choose differently, locates the real disagreement, and addresses it rather than a weaker version. |
| I7 | Adaptive reasoning | When a premise is changed by a follow-up, recomputes the implications rather than repeating the original answer or quietly switching claims. |

**Anchors.** 1–20: conventional wisdom, slogans, or unsupported contrarianism.
21–40: sensible but predictable; anything an informed observer would already
say. 41–60: at least one useful connection or genuine tradeoff, adequately
supported. 61–80: several non-obvious points with visible mechanism, and
uncertainty placed where it belongs. 81–100: gives you a model you can use to
predict their choices in a situation they did not discuss, and that model
survives the pushback they received.

**Do not reward here:** a conclusion you happen to agree with; a claim that is
merely new to you rather than new to the field; listing many considerations
without saying which dominate; or hedging that never resolves into a position.
"Everything is complicated" is not insight. Neither is false certainty that
erases real complexity.

**I7 and I6 are frequently `not_observed`.** A prepared keynote with no
questions cannot demonstrate adaptive reasoning. Mark it not observed rather
than guessing. This is the single most common scoring error.

### D3 — Technical and industry depth (weight 35%)

*Does the speaker understand the machinery, the magnitudes, and the terrain?*

| Sub | Name | What it measures |
| --- | --- | --- |
| T1 | Technical grounding | Understands how the thing actually works: architecture, constraints, failure modes. Uses technical terms with their real meaning, not as decoration. |
| T2 | Quantitative grounding | Uses magnitudes, rates, denominators and unit economics, and uses them correctly. Knows which numbers are decision-relevant. |
| T3 | Operational and industry specificity | Knows the bottlenecks, the supply chain, the sales motion, the org reality, the regulatory terrain. Concrete about how work actually gets done. |
| T4 | Cross-layer movement | Moves between business objective, user behaviour, product requirement, technical constraint, and organisational decision without losing the thread. |

**Anchors.** 1–20: abstractions only — "scale", "innovation", "execution" —
with nothing underneath. 21–40: correct vocabulary, no demonstrated mechanism;
names a factor but cannot reason with it. 41–60: real details and examples that
are accurate and relevant. 61–80: explains bottlenecks and magnitudes, and the
detail changes the conclusion rather than decorating it. 81–100: moves fluently
between strategy and implementation, and the technical content would satisfy a
practitioner in that field.

**Do not reward here:** jargon density, name-dropping technologies, or reciting
specifications with no argument attached. **Do penalise** confident technical
claims that are wrong on their face, and quantities used incoherently.

## Not observed, and why it matters

Mark a sub-criterion `not_observed` when the conversation gave no reasonable
opportunity to demonstrate it. Do not award a middling score to fill the gap,
and do not penalise the speaker for the format they were in.

`coverage` is the share of sub-criteria you actually scored. A transcript with
low coverage produces a less trustworthy score, and the aggregation step
weights it accordingly. Report it honestly. Silence about a topic is missing
evidence, not weak evidence.

An executive who declines to reveal something confidential has not
demonstrated poor reasoning. That is a gap in the evidence, and nothing more.

## Venue difficulty

Record `venue_challenge` from 1 to 5. This does not change the score; it is
recorded so that aggregation can report whether a leader's high score came from
demanding conversations or friendly ones.

1. Promotional appearance, no pushback, short segment.
2. Friendly long-form interview, open-ended prompts, no challenges.
3. Substantive interview with real follow-ups.
4. Informed interviewer who presses on specifics and returns to dodged points.
5. Genuinely adversarial or expert-level questioning that changes premises.

A prepared keynote is `venue_challenge` 1 or 2 by construction, and should
usually have I6 and I7 marked `not_observed`.

## Evidence requirements

Every dimension score needs `reasoning` — several sentences saying what in the
transcript produced the number, in your own words.

Every dimension also needs `evidence`: two to four short quotations, **25 words
maximum each**, each with the nearest timestamp and each attributed to the
subject rather than the interviewer. Quote only what you need to make the point
identifiable. Where a quote is garbled by speech recognition, quote it as it
appears and note the corruption.

Every dimension needs `counterevidence`: the strongest thing in this transcript
that argues against the score you gave. If there genuinely is none, say so and
explain why. A dimension score with no counterevidence and no explanation is a
score that was not examined.

## The overall transcript score

`overall = 0.20 × D1 + 0.45 × D2 + 0.35 × D3`

Insight carries the most weight because it is what the study is asking about.
Technical depth carries the next most because it is what makes insight
load-bearing rather than rhetorical. Clarity carries the least because a leader
can be worth listening to while being a mediocre speaker, and because rewarding
polish is exactly the error this rubric exists to avoid.

## Calibration reference

Use the whole scale. A score of 50 means genuinely ordinary for a senior
technology executive, which is a competent professional communicator. Do not
bunch everything between 70 and 85 because the speakers are accomplished. Most
promotional television segments should land in the 30s and 40s on insight,
because six minutes of airtime cannot demonstrate more.
