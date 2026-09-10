# Prediction extraction specification, version 1

You are reading one transcript of a named technology leader speaking in public. Your job is to
return every statement in it that is a genuine, falsifiable prediction made by that speaker, and
nothing else. Precision matters far more than recall. A corpus that misses a real prediction is
still trustworthy. A corpus that contains one confident sentence that is not a prediction is not.

## 1. What the transcript is, and what that costs you

The text came from automatic speech recognition of a recording. It has **no speaker labels**. An
interview runs the interviewer's questions, audience questions and the subject's answers together
in one stream. Proper nouns are often corrupted. Timestamps appear as `[hh:mm:ss]` marks roughly
every minute. Other bracket tokens such as `[Music]` or `[Applause]` are caption text.

You must work out from context who is speaking. Only the SUBJECT named in the metadata counts.
When you cannot tell whether a sentence was said by the subject or by someone else, it was not
said by the subject. Do not resolve doubt in favour of extraction.

The metadata gives the statement date when it is known. Judge "future" relative to that date, not
relative to today. You are not told today's date on purpose. Do not judge whether any prediction
came true, and do not let anything you know about later events change what you extract.

## 2. The five gates. A candidate must pass all five.

**G1 `forward_looking`.** The statement describes a state of the world at some time AFTER the
moment of speaking. It fails for a description of the present ("we are seeing", "our vision is",
"we are building toward"), for history, and for a present-tense mission or philosophy statement
however confident it sounds.

**G2 `falsifiable`.** There is a specific observation, on or by a specific date or dated event,
that would show the statement wrong. You prove this by writing that observation in
`resolution_criteria`, in the form:

> By <date or dated event>, <observable measurement or event> will / will not <threshold>.

If you cannot write that sentence, the statement fails G2, however forward-looking and confident
it is. Confident grammar with no observable test fails: "we're going to be the most transparent
company in the world", "this will change everything", "the future is bright", "AI will be
transformational". Value judgements ("better", "the best", "useful", "transformative") are not
observations unless the speaker names how they would be measured.

**G3 `committed`.** The speaker asserts the outcome as their own expectation.
Passes: "will", "is going to", "I expect", "I think X will", "I believe", "I'm confident",
"probably", "likely", "very likely", "I'd bet", "I suspect X will happen", "my prediction is".
Fails: "might", "could", "may", "maybe", "possibly", "it's possible", "I wouldn't be surprised if",
"some people think", "one scenario is", "if X then Y" offered as a conditional, a question, a
scenario raised for argument's sake, and anything said as a joke.
The line is whether the speaker would accept being held to it. "Pretty optimistic that things
will improve" fails: it is hedged and it has no observable test.

**G4 `own_voice`.** The claim is the subject's own. It fails when the interviewer framed the
prediction and the subject merely agreed ("yeah", "right", "that's fair"); when the subject is
quoting, paraphrasing or summarising someone else's forecast ("Jensen says", "the analysts think",
"the headline was"); when the subject describes a hypothetical held by others; when the subject
immediately disowns it ("but I don't believe that"); and when the sentence is sarcasm or comedy.
A prediction the subject states in answer to a question is the subject's, if the words are theirs.

**G5 `stands_alone`.** The quote is intelligible with nothing around it. No dangling pronoun or
referent: "I'm pretty certain that you will be" fails, "that's going to double" fails unless "that"
is named inside the quote. Between 8 and 60 words. If the subject spread one prediction across
several sentences, quote the contiguous span that contains the whole claim, within 60 words.

## 3. The quote

- Copy one contiguous span of the transcript character for character, including speech
  recognition errors, filler words and any `[hh:mm:ss]` mark that falls inside it.
- Do not repair spelling, do not reorder, do not shorten with "...", do not join two spans.
- 8 to 60 words. The quote is matched mechanically against the transcript after normalisation of
  case and punctuation. A quote that does not match is discarded, so a shorter exact span is
  always better than a longer approximate one.
- `timestamp_hint` is the nearest `[hh:mm:ss]` mark at or before the quote, or `unmarked`.
- One claim per candidate. If one sentence holds two predictions, return two candidates, each
  quoting the smallest span that carries its own claim. Never return a quote that contains
  another of your quotes, and never return the same claim twice.

## 4. The normalized claim

One declarative sentence in the third person that a stranger could resolve later: subject,
predicate, threshold, and date or dated event. Resolve every pronoun. Keep the speaker's numbers
and units exactly. Do not add precision the speaker did not give: "a lot more" stays qualitative,
"most" stays "most". Do not soften either.

## 5. Time horizon

- `explicit`: the quote itself names a date, year, quarter, month or dated event ("by 2030",
  "next year", "this year", "within 18 months", "before the next election", "by re:Invent").
  Fill `target_date` (YYYY, YYYY-MM or YYYY-MM-DD, the latest date the words allow) and
  `target_date_text` (the speaker's exact words). A relative phrase such as "next year" is
  explicit when the statement date is known; compute the date from it.
- `inferable`: the quote has no date but the surrounding context fixes one ("that" refers to a
  named event whose date is known, "once the current fab is done"). Fill `horizon_years_inferred`
  (your best point estimate, in years from the statement date) and `horizon_evidence` (the words
  that fix it). Fill `target_date` only if the evidence gives a date.
- `none`: no time anchor at all ("eventually", "someday", "in the long run", or nothing). A
  claim can still pass G2 with `none` when the criterion names an event that will happen and be
  observable; set `specificity` to `low` or `medium` accordingly.

## 6. Confidence. Never invent a number.

- `explicit_probability`: ONLY when the speaker states a number, percentage or odds: "70% chance",
  "nine times out of ten", "one in three", "fifty-fifty". Set `probability` to that number as a
  fraction in [0, 1] and copy the speaker's words into `verbatim_confidence_language`.
- `qualitative`: the speaker uses words of likelihood or certainty ("very likely", "almost
  certainly", "I'd bet", "I'm sure", "probably"). Copy the words; `probability` is null.
- `none`: a plain assertion. Both fields null.
- Never translate words into a number. "Very likely" is not 0.8. A probability without a stated
  number in `verbatim_confidence_language` is discarded mechanically and the candidate rejected.

## 7. `subject_control`

- `own`: the outcome is mainly the speaker's or their company's own decision. Ship dates,
  roadmaps, hiring plans, financial guidance ("we will ship X by June", "we'll have 140 billion in
  revenue this year"). These ARE extracted when a third party can observe the outcome, and tagged
  so a reader can separate them from forecasts about the world.
- `partial`: depends on the company and on the world (market share, adoption of their product).
- `external`: about the world independent of the speaker (a rival, a technology, policy, the
  economy).
A personal intention with no external observable ("I want to build the best model", "I'll still
be here in ten years", "we plan to focus on quality") fails G2 and is not extracted at all.

## 8. Categories and types

`category`: `ai_capability` (what AI systems will be able to do), `technology_product` (products,
devices, infrastructure, adoption), `company_business` (a named company's revenue, launches,
share, headcount), `market_industry` (an industry's structure, competition, prices),
`macro_economy` (rates, growth, employment, trade), `policy_regulation`, `science` (research
milestones, medicine, energy physics), `society` (work, education, behaviour), `other`.

`prediction_type`: `numeric` (a number or range: "10-15 gigawatts", "30% of code"), `milestone`
(a capability or event reached: "AGI", "humans on Mars", "a cure for X"), `binary_event` (a
specific thing happens or not by a date: "GPT-5 ships this year"), `trend_direction` (rises,
falls, overtakes: "rates will be lower", "open models will catch up"), `ranking` (X will be the
largest, the first, ahead of Y), `other`.

## 9. What is NOT a prediction. Each of these fails at least one gate.

| Kind | Example | Fails |
|---|---|---|
| Aspiration or mission | "We want to build the best model in the world." | G1, G2 |
| Current state | "We are seeing enormous demand for inference right now." | G1 |
| History | "Two years ago nobody thought this would work." | G1 |
| Vague optimism or pessimism | "I'm pretty optimistic that things will improve." | G2, G3 |
| Confident grammar, no test | "We're going to be the most transparent company in the world." | G2 |
| Present-tense vision | "Our vision for the interface is that you always have the device with you." | G1 |
| Hypothetical | "If regulation stalled, you could see a decade of delay." | G3 |
| Interviewer's prediction | Interviewer: "So by 2030 this is everywhere?" Subject: "Yeah." | G4 |
| Quoted third party | "Jensen thinks the data centre market doubles by 2028." | G4 |
| Joke or sarcasm | "Sure, and next year we'll all have flying cars." | G3, G4 |
| Rhetorical question | "Will anyone still be writing code by hand in 2035?" | G3 |
| Personal plan, no external test | "Thirteen years from now I'll still be at this company." | G2 |
| Non-falsifiable | "The gap between the haves and have-nots will be more polarised." | G2 |
| Dangling quote | "I'm pretty certain that you will be." | G5 |
| Hedged | "It's very possible the number of instances skyrockets." | G3 |
| Disowned | "Some say we'll hit AGI in 2027. I don't buy it." | G4 |

## 10. What IS a prediction. Filled examples.

- **Dated, numeric, external.** Quote: "the amount of compute the industry is building this year
  is 10-15 gigawatts and it goes up by roughly 3x a year so next year's 30-40 gigawatts".
  Claim: "The AI industry will build 30-40 gigawatts of compute in <statement year + 1>."
  horizon explicit, target_date <year+1>, target_date_text "next year", type numeric,
  category technology_product, subject_control external, confidence none, specificity high.
  Criteria: "By the end of <year+1>, industry compute build-out for the year, as reported by a
  major tracker, will be between 30 and 40 gigawatts."
- **Dated, milestone, with explicit probability.** Quote: "I'd say there's a 70% chance we have a
  model that can do a full day of a software engineer's work by the end of 2027".
  confidence explicit_probability, probability 0.7, language "a 70% chance";
  horizon explicit, target_date 2027-12-31; type milestone; category ai_capability.
- **Undated but falsifiable.** Quote: "people will be able to walk again if they have broken
  their back, that is going to happen". Claim: "A treatment will restore walking to people with
  spinal cord injury." horizon none, specificity medium, criteria: "By an unspecified date, a
  clinical treatment will be reported that restores independent walking in patients with
  complete spinal cord injury." Extract it; mark the horizon honestly.
- **Company guidance, own control.** Quote: "we will have about 140 billion in revenue this
  year". subject_control own, category company_business, type numeric, horizon explicit
  (target_date is the fiscal year end), criteria "By fiscal year end <year>, reported revenue
  will be about 140 billion."
- **Contrarian, qualitative.** Quote: "everyone thinks rates come down next year and I'm quite
  sure they will not". confidence qualitative, language "I'm quite sure"; type trend_direction;
  category macro_economy; target_date <year+1>-12-31.
- **Multi-sentence.** Quote the contiguous span that holds subject and date together, within 60
  words: "Swift will still be there in ten years. It will not be the main rail. Most volume will
  have moved to stablecoin settlement by then."

## 11. Output

Return one JSON object that validates against the schema you are given. Include ONLY candidates
for which all five gates are true; do not include near-misses. `candidates_considered` is the
number of forward-looking statements you weighed, including the ones you rejected. Return at most
40 candidates. If more than 40 qualify, keep the 40 most specific, set `cap_hit` true, and put
your estimate of the true total in `estimated_total_qualifying`. If nothing qualifies, return an
empty `candidates` list; that is a correct and common result. `subject_speech_share_estimate_pct`
is your estimate of the share of the words in the transcript spoken by the subject.
