# Speaking-transcript rubric for political commentators: intellectual honesty

Version pundits-1.0. This rubric scores **the argumentative behaviour shown in one
transcript**. It does not score a person, a career, a politics, or a sincerity.

## The rule that governs everything else

**Score only what is in the transcript.**

Do not use anything you know about the speaker, their show, their outlet, their
audience, their past statements, their reputation, or what happened after they
spoke. Do not search for any of it. If the transcript is blinded and you
recognise the speaker anyway, record that in `identity_guess` and then set the
recognition aside.

**This is not a fact-check.** A claim that is false is not penalised because it
is false, and a claim that is true earns nothing because it is true. What is
scored is whether the support the speaker gives in this recording matches how
confidently they state the claim. Agreement with your own view earns nothing.
Disagreement with it costs nothing.

## What the transcript is, and what that costs you

Transcripts come from automatic speech recognition:

- **No speaker labels.** Work out which turns are the subject's. Score only the
  subject. A host's sharp question, a guest's rebuttal, a caller, or a **clip**
  the subject plays and reacts to is not the subject's speech. Label every
  evidence quote with its speaker: `subject`, `interlocutor` (anyone else
  speaking live) or `clip` (played media). Only `subject` quotes support a score.
- **Mangled proper nouns.** Read through the corruption. Do not penalise it.
- **Disfluency is not confusion.** A halting answer that engages the other side
  fairly beats a fluent one that caricatures it.

## Three headline dimensions, scored 1–100

Each dimension has sub-criteria scored 1–5, or 0 meaning **not observed**.
Assign the 1–100 score holistically from the observed sub-criteria, then check
it against the anchors.

`overall = 0.35 × d1_steelmanning + 0.35 × d2_epistemic_rigor + 0.30 × d3_good_faith`

### d1_steelmanning — Steel-manning and charity (35%)

*Does the subject represent the other side fairly, at its strongest?*

**Opportunity.** An opposing position is present in the transcript: an
interlocutor, a clip or a quoted text states it, or the subject describes it.
With no opposing position anywhere, mark S1–S3 `not_observed`.

| Sub | Name | What it measures |
| --- | --- | --- |
| S1 | Accuracy of representation | The subject's account of an opposing argument matches that argument **as it appears in this transcript**. Scorable only when the opposing argument itself is in the transcript to compare against. When the subject describes an absent opponent, accuracy cannot be known here: mark S1 `not_observed`. |
| S2 | Engages the strongest version present | When a stronger form of the opposing view appears in the transcript, the subject answers that form and not a weaker one. |
| S3 | Locates the real disagreement | Names the premise, value or empirical question where the two sides actually part, rather than talking past it. |
| S4 | Motive attribution | Does not assert bad motive, bad faith or hidden agendas of a person or group without evidence stated in the recording. |

**Precedence.** Any claim about someone's intent or motive ("they only say this
because…", "they want X to fail") is scored under **S4 only**. It is never also
scored under G4.

**Anchors.** 1–20: opponents appear only as caricatures or villains. 21–40: the
other side is named but misstated or answered at its weakest. 41–60: opposing
views are stated recognisably and some are answered on their merits. 61–80: the
strongest opposing case present is stated fairly and engaged, and the real
disagreement is named. 81–100: an informed opponent would accept the subject's
statement of their view and find the reply aimed at what they actually believe.

### d2_epistemic_rigor — Epistemic rigor and calibration (35%)

*Does the subject's confidence match the support they give?*

| Sub | Name | What it measures |
| --- | --- | --- |
| E1 | Support | States evidence, a source, an example or a mechanism for load-bearing claims, rather than assertion alone. |
| E2 | Calibration | Confidence matches the support shown: strong claims carry strong support, and uncertainty is stated where the support is thin. |
| E3 | Separates fact, interpretation and speculation | Makes clear which statements are reported facts, which are readings of them, and which are guesses. |
| E4 | Care with numbers and sources | Numbers and sources are used consistently within the recording: no quantity contradicts another, no source is made to say more than was quoted. **Internal consistency only — not a fact-check.** |
| E5 | Names what would change their mind | States the evidence or the unknown that would move their view. |

**Anchors.** 1–20: sweeping claims with no support and no hedging. 21–40:
occasional support, but confidence routinely outruns it. 41–60: main claims
carry some support and some uncertainty is acknowledged. 61–80: claims are
supported in proportion to their weight, and fact, reading and guess are kept
apart. 81–100: a listener can see exactly what the subject knows, infers and
guesses, and what would change their mind.

### d3_good_faith — Good faith and consistency (30%)

*Does the subject argue in good faith and hold one standard?*

| Sub | Name | What it measures |
| --- | --- | --- |
| G1 | One standard | Applies the same standard to cases **the transcript itself sets side by side**, including cases involving their own side. |
| G2 | Concedes and updates | Concedes a good point or a correction when something in the recording warrants it, rather than ignoring or deflecting it. |
| G3 | Answers the question asked | Responds to the question or objection actually put, without moving the goalposts or retreating from a bold claim to a modest one under challenge and then reasserting the bold one. |
| G4 | Rhetorical fairness | Avoids insults, loaded labels, mockery in place of argument, and insinuation. Rhetoric that makes no claim about motive is scored here, never also under S4. |
| G5 | Independent thought | Departs from their own side or audience **with stated reasons**. Scorable only when the transcript itself shows the subject's **affiliation** or audience — for example "as a conservative", "my audience won't like this", "people on my side get this wrong". Without that, mark G5 `not_observed`. No outside knowledge of the speaker and no assumption by you may open this opportunity. |

**Anchors.** 1–20: dodges, goalpost shifts and insults carry the argument.
21–40: frequent deflection or double standards. 41–60: mostly answers what is
asked, with some loaded rhetoric or an unacknowledged point. 61–80: holds one
standard, concedes when warranted, argues without insult. 81–100: consistently
fair even under provocation, and willing to say where their own side is wrong,
with reasons.

## Not observed, unsupported, and why they matter

Mark a sub-criterion **0 (`not_observed`)** when the recording gave no
reasonable opportunity to show it. Do not fill a gap with a middling number.

A dimension is **supported** only when at least **2** of its sub-criteria are
scored above 0 **and** you can cite at least **2** quotes spoken by the subject.
Otherwise set `dimension_status` to `unsupported`, set its `score` to null, and
explain why in `reasoning`. If any dimension is unsupported, `overall` is null.
An unsupported dimension is missing evidence, not a low score.

`coverage` is the share of the 14 sub-criteria you scored above 0.

## Venue and challenge

Record `venue_type` from the format the transcript shows. Decide by counting the
other live voices in the conversation, not by who hosts or which channel or
network airs it. Played clips are not live voices. If a recording mixes formats,
record the format that fills most of it.

| Venue | Definition |
|---|---|
| `own_show_monologue` | The subject speaks to the audience on their own show, with no other live voice. |
| `reaction_stream` | The subject plays other material and comments on it, with no other live voice. |
| `debate` | An organised exchange with at least one named opponent, usually with a moderator or turns. |
| `guest_interview` | Exactly one other live voice: an interviewer who runs the conversation and questions the subject. |
| `hosted_interview` | The subject runs the conversation and questions exactly one guest. |
| `panel_show` | Two or more other live voices trade views with the subject, whoever hosts: a split-screen panel, a roundtable, a co-hosted show. |
| `tv_segment` | An anchor-led broadcast news segment, one-on-one or pre-packaged, that is not a multi-guest panel. |
| `speech_or_lecture` | A prepared talk to a live audience, with or without questions afterwards. |
| `other` | None of these. |

Record `venue_challenge` from 1 to 5. It does not change the scores:

1. Monologue or friendly audience, no pushback.
2. Friendly conversation, open prompts, no challenge.
3. Real follow-ups or a disagreeing voice.
4. An informed opponent who presses and returns to dodged points.
5. Adversarial debate where premises are contested directly.

## Evidence requirements

Every dimension needs `reasoning` in your own words, `evidence` of two to four
quotes of **25 words maximum** each with the nearest timestamp and its speaker,
and `counterevidence`: the strongest thing in the transcript against your score.

## Calibration reference

Use the whole scale. 50 means ordinary for a professional commentator arguing on
the record: recognisable but uneven fairness, some support, some loaded language.
Do not bunch scores in the 60s and 70s because the speakers are famous or
articulate. Fluency, humour, confidence and a large audience earn nothing here.
