# Prediction extraction specification, release 2.3

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

## 1a. The statement date, and what you may compute from it

The `Statement date` line says HOW the date is known. Read the words in brackets before you use
the date. Judge "future" relative to that date, not relative to today. You are not told today's
date on purpose. Do not judge whether any prediction came true, and do not let anything you know
about later events change what you extract.

- "stated in the source itself", "from a sourced correction", or "a dating check found": this is
  when the words were spoken, or a close upper bound. Resolve relative time words ("this year",
  "next quarter", "in two years") against it. When the line gives a range of days, resolve
  "this year" or "next year" only if the whole range lies inside one calendar year, and a
  quarter phrase only if it lies inside one quarter; otherwise treat the phrase as in the
  "unknown" case below.
- "NOT checked against the event": the date is only an upper bound, and the recording may be
  years older. Test it against the title, the description and the transcript.
  If nothing shows an older recording, resolve relative time words against it as the latest
  possible date, as for any other date; the page labels the date "not checked". If anything
  shows an older recording (a conference name with a year, "welcome to CES 2006", a product that
  launched years before this date, a remark such as "here in 2008"), then:
    1. set `statement_date_doubt.doubt` to `recording_older_than_stated` and copy the words
       that show it into `statement_date_doubt.evidence`;
    2. do not turn a relative time phrase into a calendar date: leave
       `target_date` null and keep the speaker's words in `target_date_text`;
    3. do not write a calendar year into the claim or the criterion unless the speaker said
       that year.
  The pipeline dates the recording and then extracts it again, and it holds every record of a
  transcript with that doubt until then. Guessing the year does not save a prediction; it
  produces a wrong claim.
- "unknown": resolve no relative phrase. Keep the words in `target_date_text`.

`statement_date_doubt` is one answer for the whole transcript. `none` means nothing you read
contradicts the date line. `cannot_tell` means the evidence points both ways; it is recorded and
does not hold records. `evidence_year` is the year your evidence names, or null. A doubt written
only in `gate_notes` or `attribution_notes` is read by nobody.

When the statement date is known, never write a placeholder such as "the statement year" or
"the year following the recording" in a claim or a criterion. Write the year.

## 2. Shared eligibility and evidence rules

{{ELIGIBILITY_POLICY}}

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

A CLAIM ABOUT A PERIOD'S RESULT. When the claim is about a figure for a year, a
quarter or another period (revenue, profit, growth, a share of GDP), the date in
the criterion is the END OF THE PERIOD, and the observable is the figure FOR that
period, whenever it is published. Write: "For <period> (ending <date>),
<observable figure> will be <outcome>, as reported at any time." Never write
"By <period end>, X will report ...": a full-year result cannot be reported
before the year ends, so that sentence can never come true.

## 5. Time horizon

- `explicit`: the quote itself names a date, year, quarter, month or dated event ("by 2030",
  "next year", "this year", "within 18 months", "before the next election", "by re:Invent").
  Fill `target_date` (YYYY, YYYY-MM or YYYY-MM-DD, the latest date the words allow) and
  `target_date_text` (the speaker's exact words). A relative phrase such as "next year" is
  explicit. Compute `target_date` from it only as section 1a allows; where section 1a forbids it,
  `target_date` is null and `horizon` stays `explicit` with the words in `target_date_text`.
  'Next year' means the whole following calendar year, so `target_date` is `<year+1>`, which the
  pipeline reads as 31 December. A company's fiscal year is resolved later, by the resolver.
- `inferable`: the quote has no date but the surrounding context fixes one ("that" refers to a
  named event whose date is known, "once the current fab is done"). Fill `horizon_years_inferred`
  (your best point estimate, in years from the statement date) and `horizon_evidence` (the words
  that fix it). Fill `target_date` only if the evidence gives a date.
- `none`: no time anchor. Apply the shared policy's undated-milestone rule.
  Set `specificity` to `low` or `medium`; never invent a date.
- Vague time words ("soon", "shortly", "in the coming weeks", "in the coming months",
  "eventually", "over time") go into `target_date_text` exactly as said, even though they give
  no date. `horizon` stays `none` and `target_date` stays null.

## 6. Confidence. Never invent a number.

- `explicit_probability`: ONLY when the speaker states a number, percentage or odds: "70% chance",
  "nine times out of ten", "one in three", "fifty-fifty". Set `probability` to that number as a
  fraction in [0, 1] and copy the speaker's words into `verbatim_confidence_language`.
- `qualitative`: the speaker uses words of likelihood or certainty ("very likely", "almost
  certainly", "I'd bet", "I'm sure", "probably"). Copy the words; `probability` is null.
- `none`: a plain assertion. Both fields null. Belief verbs are commitment, not confidence:
  "I think", "I believe", "I expect", "we think", "my prediction is" leave the type at `none`.
  Confidence needs a DEGREE word: "very likely", "almost certain", "I'm sure", "probably",
  "I'd bet", "my bet is", "no doubt".
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
falls, overtakes: "rates will be lower", "open models will catch up"), `comparative` (X will be
the largest, the first, ahead of Y, better than Z on a named measure), `other`.

`claim_form`: `simple` (one outcome), `conditional` (the outcome is claimed only after a stated
precondition: "once the recall passes, the mayor will appoint a Democrat"), `ordering` (one
thing happens before another: "X will ship before Y"), `recurring` (a repeated event: "every
year", "each quarter"). Choose it from the words, not from what you expect to happen.

## 9. Eligibility examples

Use the shared policy above for both positive and negative cases.

## 10. What IS a prediction. Filled examples.

- **Dated, numeric, external.** Quote: "the amount of compute the industry is building this year
  is 10-15 gigawatts and it goes up by roughly 3x a year so next year's 30-40 gigawatts".
  Claim: "The AI industry will build 30-40 gigawatts of compute in <year+1>." Write the year
  itself, for example 2026, never the words "statement year".
  horizon explicit, target_date <year+1>, target_date_text "next year", type numeric,
  category technology_product, subject_control external, confidence none, specificity high.
  Criteria: "For <year+1> (ending <year+1>-12-31), industry compute build-out for that year
  will be between 30 and 40 gigawatts, as reported by a major tracker at any time."
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
  year". subject_control own, category company_business, type numeric, horizon explicit,
  target_date <year> (the resolver reads the company's fiscal year), criteria
  "For fiscal year <year>, reported revenue will be about 140 billion, as reported at any time."
- **Contrarian, qualitative.** Quote: "everyone thinks rates come down next year and I'm quite
  sure they will not". confidence qualitative, language "I'm quite sure"; type trend_direction;
  category macro_economy; target_date <year+1>-12-31.
- **Multi-sentence.** Quote the contiguous span that holds subject and date together, within 60
  words: "Swift will still be there in ten years. It will not be the main rail. Most volume will
  have moved to stablecoin settlement by then."

## 11. Output

Return one JSON object that validates against the schema you are given. Include ONLY candidates
for which all five gates are true; do not include near-misses. `candidates_considered` is the
number of forward-looking statements you weighed, including the ones you rejected.
`statement_date_doubt` is required even when there are no candidates. Return at most
40 candidates. If more than 40 qualify, keep the 40 most specific, set `cap_hit` true, and put
your estimate of the true total in `estimated_total_qualifying`. If nothing qualifies, return an
empty `candidates` list; that is a correct and common result. `subject_speech_share_estimate_pct`
is your estimate of the share of the words in the transcript spoken by the subject.
