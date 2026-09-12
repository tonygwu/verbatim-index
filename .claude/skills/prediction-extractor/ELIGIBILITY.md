# Shared prediction eligibility policy, release 2

The extractor and verifier apply these same rules. Precision matters more than
recall. Judge eligibility from the supplied recording, not whether you believe
the forecast or know what happened later. Do not use outside knowledge to
declare an event already achieved, inevitable, or impossible.

## The five gates

**G1 `forward_looking`.** The subject describes a state after the moment of
speaking. Present descriptions, history, missions and aspirations fail. Judge
"future" relative to the statement date. An upload date is an upper bound on
the recording date, not proof of the exact date spoken.

**G2 `falsifiable`.** The words supply an observable outcome and a success
condition. There are two permitted forms:

- Dated prediction: write "By <date or dated event>, <observable> will / will
  not <threshold>." The date can come from an explicit phrase or unambiguous
  surrounding context. A nearby date does not automatically date every claim.
- Undated milestone: a specified numerical threshold, named deliverable, or
  completed task with an observable success condition can qualify without a
  deadline. Write "At an unspecified date, <observable milestone>." Mark the
  horizon `none`. Such a record has no deadline at which non-occurrence makes
  it false, and cannot yet receive a time-bounded outcome score.

An undated generic announcement ("our new model soon", "we will announce more
things"), generic capability ("we'll be able to analyze video"), or subjective
improvement ("better", "useful", "constantly helping") fails without a named
deliverable or testable success condition. A phrase like "long-term persistent
agents" gives no minimum duration or task-success requirement. Do not invent one.
An unspecified future accumulation with no observation period, or a count
whose population is not identifiable, does not supply a usable numerical test.

An explicit measure can make a comparison qualify. "Better than Super Cruise"
can use "fewer unplanned disengagements" when the speaker supplies that measure
in the evidence window. Do not require a named testing protocol unless the
claim cannot be interpreted without one. Preserve an approximate quantity as
approximate; do not manufacture precision or a deadline.

Examples of permitted undated milestones: a treatment restores independent
walking after spinal cord injury; an application is created by assembling
AI agents with no manual programming. The latter has a success condition:
an application exists and no manual code was required. Natural-language task
instructions alone do not count as manual programming. Do not weaken a broad
claim about widespread adoption into one demonstration.

A company's roadmap or guidance can qualify: a named release by June,
annual revenue of about 140 billion, or solar generation covering about 80%
of identified facilities' annual energy use. A third party can observe a
company's published report; direct access to internal meters is not required.
Tag company control separately. Personal intentions with no external observable
fail. Do not reject a numerical or capability milestone merely because you
consider its eventual achievement likely. Explain the missing test instead.

**G3 `committed`.** The speaker asserts an expectation: "will", "is going to",
"I expect", "I think X will", "I believe", "probably", "likely", "I'd bet".
"Might", "could", "may", "maybe", "possibly", a question, a joke, or an
if-then scenario without commitment fails.

**G4 `own_voice`.** The subject states the prediction in their own words.
An answer can qualify. Merely agreeing with the interviewer's prediction,
quoting someone else's forecast, a disowned claim, sarcasm and comedy fail.
Unclear attribution fails. Metadata can identify the named subject; it cannot
turn the host's words into the subject's.

**G5 `stands_alone`.** The quote itself contains the predicted event, its
subject matter and any numerical measure. No dangling "that will double" or
"65 percent" with no identifiable measure. Between 8 and 60 words. Select a
contiguous span that includes the necessary referent. Speaker metadata can
resolve "I" or "we"; surrounding text cannot repair an otherwise incomplete
quote. Timestamps and interpretable speech-recognition errors alone never
cause rejection. Preserve them verbatim.

## Evidence boundary and claim fidelity

The extractor reads the full transcript to find and select quotes. The
normalized claim, its quantities, entities, dates and success conditions must
be supported by the quote and the 400 words on each side that the verifier
receives. Do not import a detail from a distant passage. Select an earlier or
longer quote, or omit that extra detail without changing the prediction.

The verifier checks this same boundary. Resolving a pronoun from the window
is faithful. Adding a number, entity, direction, threshold or scope absent
from the window is not. Losing a qualification or changing a general adoption
claim into a single demonstration is not faithful either.

Resolve explicit relative dates against the metadata date. "Next year" with
a known statement year can supply the following year. "In a few years" cannot
supply an invented exact year. If the recording appears older than its upload,
record that limitation in notes; do not reject a correctly resolved relative
date for following the supplied metadata.
