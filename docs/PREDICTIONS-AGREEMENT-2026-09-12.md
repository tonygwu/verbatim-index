# Predictions acceptance audit, 2026-09-12

The 11/24 figure is a **45.83% verifier acceptance rate on extractor proposals**.
It does not measure symmetric agreement, extraction precision, recall, or forecasting accuracy.
The records reveal a material mismatch: every reviewed candidate came from an
older extraction contract, before the rule against generic undated announcements.
Every verifier used a newer contract that included that rule.

This review classifies the 13 rejections as **2 extractor wrong, 1 verifier wrong,
and 10 spec ambiguous**. These are this auditor's assessments, not independent
human labels or estimates of either model's error rate. The detailed assessments
below identify both the main reason and defects in otherwise defensible verdicts.

Work owner: `repo-4`. Status: review complete.
The audit used saved records and source code. It made no model calls and changed
no private data. It preserves the existing decision to keep a strict verifier
(`VD-1` in [the predictions ledger](LEDGER-predictions.md)).

## Evidence and scope

The public code pin is `0a3b32c` in `tonygwu/verbatim-index`.
The private data pin is `06f1ec2a1b41aeed5cec0d1c4f0ae85cd180c399` in
`tonygwu/verbatim-index-data`. The live data check returned exactly
`11 13 0.4583` before review. The case review then read the committed JSONL
records through `git show 06f1ec2:<path>`, so later data changes cannot alter
this audit's evidence.

The pinned index reports 666 successful extractions and 5 exclusions.
Verification metadata reports 10 successful transcripts, 660 not run, and
1 with nothing to verify. Candidate records contain 1,494 proposals:
11 accepted, 13 rejected, and 1,470 with verification not run.
The 24 reviewed candidates span 10 transcripts. Five come from Krishna's
`economist-enterprise-eve-e3go5g` recording.

All 24 recorded pairs are extraction `astra` → verification `fable`.
The extraction records name `gpt-6-astra` and have
`served_model_verified: false`. The verification records name
`claude-fable-5-1` and have `served_model_verified: true`.
Thus Astra's identity is requested-model provenance, not an independently
verified served identity. There is no Gemini verdict in these 24.
Earlier Gemini call failures described in [PREDICTIONS.md](PREDICTIONS.md)
are not additional candidate verdicts.

## Do the two specs ask the same question?

**They share an eligibility policy, but their full tasks and evidence differ.**
The runner loads `EXTRACTION.md` and `VERIFICATION.md` through the constants
in [predictions_lib.py](../scripts/predictions_lib.py), using the selected
`--skill-dir`. It builds separate prompts in `build_extraction_prompt` and
`build_verification_prompt`.

The [extraction spec](../.claude/skills/prediction-extractor/EXTRACTION.md)
asks for every qualifying prediction in the full transcript, with all five
gates true. It explicitly favors precision over recall. The
[verification spec](../.claude/skills/prediction-extractor/VERIFICATION.md)
asks whether each supplied candidate qualifies, with three requirements:
attribution to the subject, the same five gates, and a faithful normalized claim.
It sees the quote, about 400 words **on each side**, metadata, and the normalized
claim. It does not see the extractor's gate notes or resolution criterion.

The five shared gates require a future statement, falsifiability, commitment,
the subject's own voice, and a quote that stands alone. Both permit observable
company guidance. Both use the statement date rather than later outcomes.
The verifier's explicit fidelity decision adds a check on the extractor's
work, rather than another extraction of the same transcript.

Three differences matter here:

1. **The recorded specs differ in time.** The current extraction contract is
   `d795f6f1d88b`. None of these 24 candidates used it. The 22 candidates under
   `3a54940218c0` match the files at `05d70a0`. The two Hotz candidates under
   `8aeda1ba6395` match `ab05764`. Both predate `984110b`, which tightened
   undated claims. Seven verdicts use `63aa6e366a85`, matching `1e1555a`.
   Seventeen use `102275d44824`, matching `1ee170c` and the current verifier.
   Both verifier versions contain the stricter undated rule.
2. **The current undated exception still needs judgment.** G2 first demands
   a date or dated event. Extraction section 5 then permits a specific,
   non-trivial undated observable. Verification G2 permits an undated observable
   that is specific and genuinely uncertain. Neither specifies a consistent
   test for “genuinely uncertain.” The extraction spec lists a spinal-injury
   treatment as a positive example and generic video analysis as a negative.
   Broad capability forecasts fall between those examples.
3. **Context can change the fidelity verdict.** Extraction can use a detail
   from the full transcript. Verification section 4 explicitly limits its
   fidelity evidence to the quote and window. Case 4 demonstrates this mismatch.
   Also, extraction G2 permits “better” when the speaker supplies a measure,
   while verification's shorter wording omits that explicit exception.

The old extraction exception was:

> a claim can still pass G2 with `none` when the criterion names an event that will happen and be observable

The later rule adds specificity and uncertainty, and explicitly rejects generic
undated announcements. Cases 3 and 10 match the new negative examples.
The older extractor can accept them and the newer verifier can reject them
without either model violating its operative undated exception.

The contract-pair counts are 15 reviewed / 8 accepted for
`3a54940218c0 → 102275d44824`, 7 / 3 for
`3a54940218c0 → 63aa6e366a85`, and 2 / 0 for
`8aeda1ba6395 → 102275d44824`. Hashes here are the first 12 hexadecimal
characters of SHA-256 over the spec bytes followed by the schema bytes,
as implemented by `_contract`.

The runner also caches a successful stage without comparing its stored
contract to the current contract. Reading today's specs therefore does not
establish which specs produced cached candidates. This is a limit of the
audit trail's interpretation, and a reason to distinguish contract versions
before any later evaluation. This audit does not change cache behavior.

## Classification of all 13 disagreements

“Extractor wrong” means the saved candidate violates a clear extraction rule.
“Verifier wrong” means the rejection overlooks evidence that satisfies its rule.
“Spec ambiguous” includes unclear policy, a changed contract between stages,
or incompatible evidence boundaries. It does not mean every current rule is
unclear: cases 3 and 10 are now explicit negatives.

Each classification concerns the saved candidate and the rules that produced
its verdict. It does not decide whether the underlying forecast came true.
The quotations below reproduce `source.quote_original`, the normalized claim,
`extraction.gate_notes`, and `verification.notes` exactly. These are recorded
explanations, not access to either model's internal reasoning.

Across the 13 records, Fable sets G2 false 11 times, G5 false twice, and
`claim_faithful` false once. These counts overlap on the Bezos record.
All 13 attribute the statement to the subject and pass G1, G3, and G4.

### 1. Arvind Krishna: future construction — spec ambiguous

ID: `38b2839a4c10ba01`. Record: `data/predictions/arvind-krishna/economist-enterprise-eve-e3go5g.jsonl:2`.
Recorded failure: `falsifiable`.

Candidate quote:

> there's going to be a few trillion square feet of buildings put over all over the globe

Normalized claim:

> New construction worldwide will total a few trillion square feet of buildings at an unspecified future date.

Astra's recorded reasoning:

> Krishna directly asserts future construction with an observable area and worldwide scope. The quote is self-contained, but neither a deadline nor an exact numerical interpretation of 'a few' is supplied.

Fable's recorded reasoning:

> This is a rhetorical premise used to set up the argument about cement and steel emissions ('are we really going to say we're not going to put up those buildings'). It has no date and 'a few trillion' is not a threshold; over an unbounded horizon it is near-certain as a matter of course, so it fails G2.

Assessment: The extractor followed the older observable-event exception. Fable applied
the later requirement for a genuinely uncertain event. No date or numerical
definition of “a few” appears in the saved window. Rejection fits the strict
policy, but this record does not show the extractor violating the policy it
received. The current spec also says to preserve qualitative quantities.
It needs a clearer distinction between an undated numeric milestone and
indefinite accumulation.

### 2. Arvind Krishna: 65 percent by 2025 — extractor wrong

ID: `873c531ca6618cc8`. Record: `data/predictions/arvind-krishna/economist-enterprise-eve-e3go5g.jsonl:5`.
Recorded failure: `stands_alone`.

Candidate quote:

> contributing no carbon back into the environment we have to make progress on that so we have set 65 percent as our goal [00:21:24] by the midpoint not 50. so we want to be at 65 percent by 2025. you can hold us to that

Normalized claim:

> IBM will achieve 65 percent of its zero-carbon-footprint goal by 2025.

Astra's recorded reasoning:

> The quote identifies the no-carbon objective, its numerical interim target and the deadline. Krishna makes this an accountable IBM commitment by saying 'you can hold us to that'; the percentage is progress toward the stated goal, without an added baseline year.

Fable's recorded reasoning:

> The underlying 2025 target is a genuine corporate commitment ('you can hold us to that'), but the quote as cut fails G5: it opens mid-sentence with a fragment from the prior clause, contains a timestamp token, and never states what the 65 percent is a share of ('make progress on that', 'the midpoint' have no referent inside the quote). A recut that includes the zero-carbon-footprint referent could qualify.

Assessment: G5 is the defensible rejection. The quote starts inside a clause and omits
the zero-carbon-footprint commitment and its relationship to clean energy.
“65 percent” consequently lacks a clear measure within the quote. The
preceding window supplies that material, but G5 requires the quote itself
to stand alone. This is a problem with the selected quote, not an absence of
an accountable forecast.

Fable's timestamp complaint is invalid: the extraction spec requires timestamps
inside a selected span to remain. A timestamp alone must not cause rejection.
That error does not remove the separate G5 problem.

### 3. Dario Amodei: video analysis — spec ambiguous

ID: `8175e093ab678eee`. Record: `data/predictions/dario-amodei/planet-62mtda.jsonl:1`.
Recorded failure: `falsifiable`.

Candidate quote:

> I'm sure we'll be able to analyze video

Normalized claim:

> Anthropic's AI systems will be able to analyze video at an unspecified future date.

Astra's recorded reasoning:

> Amodei confidently asserts a future video-analysis capability in his own words. The capability is demonstrable, and the eight-word quote expresses the complete prediction.

Fable's recorded reasoning:

> Speaker is Amodei (the turn references 'our business model for text' and 'customers', i.e. Anthropic). The line is one of a run of filler assertions ('I'm sure we'll have more advanced types of things', 'I'm sure we'll be able to analyze video', 'I'm sure we'll be able you know there's much more value') gesturing at future value rather than a forecast. It is undated, names no product or threshold, and 'analyze video' is a generic capability that is certain to arrive as a matter of course, so it fails G2. The extractor's resolution of 'we' to Anthropic is reasonable from the window, though the word could also mean the field at large.

Assessment: This is a concrete contract change. The older extractor allowed an
observable undated event. The current extraction spec explicitly lists
“we'll be able to analyze video” as a negative. Fable's newer specification
rejects this generic capability announcement. Its rejection fits that rule.
The old extractor's acceptance is not evidence that it ignored the new rule.
This case requires consistent contract versions before it can test model behavior.

### 4. George Hotz: open-source highway maps — spec ambiguous

ID: `6d1c21328ce40fe2`. Record: `data/predictions/george-hotz/mapbox-n9wxlr.jsonl:1`.
Recorded failure: `claim_faithful`.

Candidate quote:

> we are going to open source all the highway maps by the end of the year

Normalized claim:

> Comma will open-source maps of every lane line and every drivable path on every interstate highway in America by the end of 2018.

Astra's recorded reasoning:

> Hotz directly commits to an observable future release with a year-end deadline. The quote identifies the release and deadline; his earlier description establishes the maps' coverage as every interstate lane line and drivable path in America.

Fable's recorded reasoning:

> Hotz is answering the host's question about his company's focus and cites his own Twitter commitment, so attribution and all five gates hold. Fidelity fails: the extractor's claim adds 'every lane line and every drivable path on every interstate highway in America', and none of those specifics (lane lines, drivable paths, interstate, America) appear in the quote or anywhere in the window. A claim limited to 'Comma will open-source all of its highway maps by the end of 2018' would be faithful and would qualify. 'Comma' is not named in the window or metadata (roster lists tinygrad) but is the correct 2018 referent for 'we'. Recording is from Locate 18 (spring 2018, uploaded June 2018); 'end of the year' resolves to 2018 either way.

Assessment: The full pinned transcript contains the extra map details about 1,478 words
before this quote, beyond the verifier's 400-word window. At character offset
4,941 it says “Lane line”, then specifies paths and interstate highways in America.
The selected quote begins at offset 12,624.

The extractor's stated source for the details therefore exists. Fable correctly
reports that its window lacks them, as its fidelity rule requires. This is a
mismatch between evidence boundaries, not demonstrated fabrication or verifier
inattention. A claim restricted to the quoted highway maps avoids this mismatch.
Passing relevant source evidence to verification is another design option.

### 5. George Hotz: better than Super Cruise — spec ambiguous

ID: `1388330b4466d3b8`. Record: `data/predictions/george-hotz/mapbox-n9wxlr.jsonl:2`.
Recorded failure: `falsifiable`.

Candidate quote:

> we are going to be better than GM supercruise

Normalized claim:

> At an unspecified future date, Comma's driving system will have fewer unplanned disengagements than GM Super Cruise.

Astra's recorded reasoning:

> Hotz independently asserts future superiority over a named competing system, then explains unplanned disengagements as the performance measure. This makes the comparison observable rather than merely subjective; the adjacent year-end deadline expressly dates the map release.

Fable's recorded reasoning:

> Hotz's own words, in the same sentence as the maps commitment. The quote itself asserts only 'better', a value word. The metric comes from the following exchange: the host asks 'better how so', Hotz says Super Cruise has 'very few unplanned disengagements', the host asks 'you mean concretely mathematically disengagement', Hotz answers 'oh yeah'. The extractor's use of that metric is a fair resolution from the window, but there is no defined test, the only evidence Hotz proposes is 'what will hopefully be releasing some comparison statistics', and it is ambiguous whether 'by the end of the year' attaches to this clause (the extractor conservatively left it undated). An undated comparative with no protocol is not falsifiable.

Assessment: The window supplies unplanned disengagements as the comparison measure,
and Fable itself calls that interpretation faithful. Its additional demand
for a defined testing protocol is not explicit in the spec. However, the
date's scope is unclear, and an undated relative performance claim raises
the unresolved “genuinely uncertain” test. The extraction spec's express
exception for measured comparisons is also absent from the verifier's wording.
Neither a categorical extractor error nor a categorical verifier error follows.

### 6. Jeff Bezos: solar energy coverage — extractor wrong

ID: `82a574ce7cac0596`. Record: `data/predictions/jeff-bezos/startupacademy-xtxofh.jsonl:2`.
Recorded failure: `falsifiable`, `stands_alone`.

Candidate quote:

> these are big fulfillment centers there are they're about a million square feet each and so we're covering them with sourcils that'll that'll cover about 80% of the fulfillment centers energy budget on an annual basis

Normalized claim:

> Amazon's fulfillment-center rooftop solar cells will cover about 80% of the equipped centers' energy budget over a full year of operation.

Astra's recorded reasoning:

> Bezos directly asserts future solar performance using 'that'll'. The annual energy share is measurable, and the quote identifies the fulfillment centers and coverage threshold while preserving the transcription error 'sourcils'.

Fable's recorded reasoning:

> Bezos speaking, continuing the solar-rooftop answer. The quote opens with a dangling 'these' (the 15 fulfillment centers named in the preceding sentence) and its key noun is ASR-corrupted ('sourcils' for 'solar cells'), so the quote alone does not make clear what is being installed or at which sites. The 80% figure reads as a design/capacity specification for the installations rather than a dated forecast; there is no date, and the observable (share of a fulfillment center's energy budget) depends on Amazon's internal consumption figures, so a third party could not independently check it. The extractor's claim is faithful to the words, but the candidate fails on falsifiability and stands-alone.

Assessment: The selected quote omits the preceding sentence that identifies rooftop
solar installations and the 15 centers. Its “these” and corrupted “sourcils”
make the independent quote incomplete under a strict G5 reading. Rejection
of this selected span is defensible. A better contiguous span needs to include
the installation referent while remaining within 60 words.

Fable's G2 reasoning is much weaker. The window says “we're doing 15 this
year,” and 80% of annual energy is a numerical observable. The spec permits
company guidance and does not require public access to every internal meter.
It also requires readers to interpret speech-recognition errors. Neither
corruption alone nor company ownership makes this forecast ineligible.
The primary classification rests on G5, not those additional objections.

### 7. Jensen Huang: digital protein design — spec ambiguous

ID: `f484ae2db3719ead`. Record: `data/predictions/jensen-huang/diana-ding-z8caxo.jsonl:1`.
Recorded failure: `falsifiable`.

Candidate quote:

> Engineers uh like like ourselves today will be designing digital will be designing proteins in in a digital way and artificial intelligence will make that possible

Normalized claim:

> Artificial intelligence will enable engineers to design proteins digitally at an unspecified future date.

Astra's recorded reasoning:

> Huang asserts that engineers will design proteins digitally using AI. This describes an observable future engineering capability, and the quotation identifies both the activity and the enabling technology.

Fable's recorded reasoning:

> Subject's own words in a passage on NVIDIA's future applications (chip design analogy, 'we are near the generation where'). Undated vision statement: 'designing proteins in a digital way' carries no threshold, and computational protein design already existed at the time of speaking, so the observable is neither specific nor genuinely uncertain. Fails G2 only.

Assessment: This can be read as a named capability under the older undated exception.
Fable instead reads it as an already available, insufficiently defined
capability under the newer rule. Its claim about prior availability is not
evidence supplied by the transcript.

The window also places protein engineering among developments “in the next
10 years.” Whether that dates this specific capability is debatable.
Neither saved verdict resolves the difference between a first demonstration
and broader engineering adoption. The policy needs that distinction before
this case can serve as a clear model-error label.

### 8. Jensen Huang: human-language programming — spec ambiguous

ID: `f37049c460b28508`. Record: `data/predictions/jensen-huang/diana-ding-z8caxo.jsonl:2`.
Recorded failure: `falsifiable`.

Candidate quote:

> the programming language of the future is human language us talk to it write to to it show it examples and the computer will write the programs to execute it by itself

Normalized claim:

> Computers will write programs and execute the requested tasks themselves from human-language instructions and examples at an unspecified future date.

Astra's recorded reasoning:

> Huang affirmatively predicts computers generating programs to perform tasks specified through human language and examples. The quotation supplies the inputs, computer, and expected behavior, making the undated capability observable and independently intelligible.

Fable's recorded reasoning:

> Subject answering the host's 'next big wave' question. Undated, no threshold; natural-language code-generation tools were already publicly available before the statement date, so the observable is not genuinely uncertain. ASR 'us talk to it' reads as 'you talk to it'. Fails G2 only.

Assessment: The quote specifies inputs and computer behavior. That fits the old
observable-capability exception. The surrounding passage also describes a
broader change in how people program, while the normalized claim can resolve
with one demonstration. Fable treats existing code-generation tools as
sufficient to make the outcome uninteresting. The spec does not define that
novelty test or the required scale of adoption. Rejection is defensible under
the strict interpretation, but it does not isolate a defect in either model.

### 9. Jensen Huang: assembling AIs without programming — verifier wrong

ID: `6846b2c20e73e27a`. Record: `data/predictions/jensen-huang/diana-ding-z8caxo.jsonl:3`.
Recorded failure: `falsifiable`.

Candidate quote:

> whereas we used to write with visual C++ or visual studio and we would create libraries and sdks and and write programs in the future we will assemble AIS there's no programming to do you assemble AIS well what does that mean assembling AIS is like assembling teams

Normalized claim:

> Software applications will be created by assembling teams of AIs without manual programming at an unspecified future date.

Astra's recorded reasoning:

> Huang commits to a future method of creating software by assembling AIs without programming. The quotation contains the software context and the proposed method; creating an application through this process is an observable milestone.

Fable's recorded reasoning:

> Subject's own words. The nearby 'I think in 10 years time a computer will be unrecognizable' is a separate statement and does not date this quote. 'Assemble AIs' and 'no programming to do' are undefined, undated, and carry no threshold. The claim's 'teams of AIs' is a fair rendering of the quote plus the following sentence about assembling teams of specialists. Fails G2 only.

Assessment: The rejection overlooks the explicit threshold “there's no programming to
do.” The quote names the method, and the window explains teams of specialists
that receive a mission and resources. Fable passes every other gate and
marks the claim faithful. Under its own exception for a specific undated
observable, a software application assembled from AIs without manual
programming is a reasonable qualifying milestone. No rule requires a
calendar date for every such milestone.

This is an interpretive classification, not a measured human consensus.
The scope of “programming” and the breadth of the future claim still need
clarification. Those limits warrant a note. They do not support the saved
blanket assertion that the statement supplies no threshold.

### 10. Sam Altman: a new model soon — spec ambiguous

ID: `46545399bdedd998`. Record: `data/predictions/sam-altman/cnbc-tv18-on-bjz.jsonl:1`.
Recorded failure: `falsifiable`.

Candidate quote:

> we're launching our new model soon which is another step forward

Normalized claim:

> OpenAI will launch a new AI model at an unspecified date in the near future.

Astra's recorded reasoning:

> Altman directly asserts an upcoming launch by his company. A model release is observable, and the quote independently identifies the promised event; 'soon' supplies no resolvable deadline.

Fable's recorded reasoning:

> Speaker is clearly Altman (recounting OpenAI's internal GPT-4 history). This is the spec's own example of a non-falsifiable launch announcement. The surrounding text ('three and a half years' since March 2023, 'in 2025 we saw') is consistent with the 2026-09-03 statement date.

Assessment: The verifier correctly recognizes its spec's explicit negative example.
The extractor used a version that still allowed a launch as an undated
observable event. No model must be wrong for those two instructions to yield
opposite decisions. Under the current extraction spec, this candidate must
be rejected. The saved old candidate cannot establish whether the current
extractor follows that instruction.

### 11. Sam Altman: persistent agents — spec ambiguous

ID: `b4fe21191fe076aa`. Record: `data/predictions/sam-altman/cnbc-tv18-on-bjz.jsonl:2`.
Recorded failure: `falsifiable`.

Candidate quote:

> we'll have these long-term persistent agents that can work like a real virtual collaborator constantly helping

Normalized claim:

> Long-term persistent AI agents will become available as continuously working virtual collaborators at an unspecified future date.

Astra's recorded reasoning:

> Altman asserts the future availability of persistent agents in his own answer. Sustained agent operation and ongoing assistance are observable capabilities, and the quote identifies the predicted agents and behavior.

Fable's recorded reasoning:

> Altman's own words ('I think we'll see a third thing soon where...'). Committed and forward-looking, but the observable is a vaguely described product category with no date, so it fails G2 under the strict reading of undated claims. Borderline call; if a later pass treats 'persistent agents as continuous collaborators' as a specific deliverable it could pass, but I judge it too soft.

Assessment: Fable explicitly calls this borderline. “Long-term,” “real virtual
collaborator,” and “constantly helping” lack duration or performance thresholds.
The extractor treats sustained operation as a named capability. The strict
verifier treats it as a vague product category. Both readings are plausible
under the respective contracts. A minimum duration or task requirement would
resolve the boundary only if the speaker supplied it. The extractor must
not invent one.

### 12. Satya Nadella: three billion connected people — spec ambiguous

ID: `db4cd68d504bac2f`. Record: `data/predictions/satya-nadella/winbeta-gmr0wc.jsonl:1`.
Recorded failure: `falsifiable`.

Candidate quote:

> there are going to be over three billion people with connected devices

Normalized claim:

> The number of people with connected devices worldwide will exceed three billion at an unspecified future date.

Astra's recorded reasoning:

> Nadella directly asserts a future, countable population threshold in his own keynote. The quote identifies the population and threshold without requiring surrounding text; no deadline is supplied.

Fable's recorded reasoning:

> Speaker is clearly Nadella (mobile-first cloud-first framing, 'living amongst 30,000 computer scientists at Microsoft', reinvent-productivity mission language). The figure is delivered as market-context scale-setting ('it's a tremendous opportunity we see it today') in a run of round analyst-style numbers (3 billion people, 200 billion sensors, zettabytes of data) with no date anywhere in the window. As an undated threshold on a monotonically growing count, it is not genuinely uncertain: at the time of speaking, contemporaneous estimates of internet users and unique mobile subscribers already sat at roughly this level or above depending on how 'connected device' is read. Fails G2 only; all other gates pass and the extractor's claim adds nothing.

Assessment: A numeric threshold exists. The unresolved questions are the time limit,
the meaning of a connected device, and what makes an undated population
threshold non-trivial. Fable adds claims about contemporary internet and
mobile-subscriber counts that are not sourced in the window. They are model
assertions, not facts established by this audit. The older extractor's rule
permits this observable count. The newer verifier can reject it as routine
growth, but the spec gives no reproducible test for that distinction.

### 13. Satya Nadella: 200 billion sensors — spec ambiguous

ID: `f67f36ebfb866b74`. Record: `data/predictions/satya-nadella/winbeta-gmr0wc.jsonl:2`.
Recorded failure: `falsifiable`.

Candidate quote:

> there's going to be over a 200 billion sensors out there

Normalized claim:

> The number of sensors worldwide will exceed 200 billion at an unspecified future date.

Astra's recorded reasoning:

> Nadella directly predicts a future sensor-count threshold, an observable numerical milestone. The statement is his own assertion and independently identifies what is counted; no deadline is supplied.

Fable's recorded reasoning:

> Same speaker and passage as the 3-billion-people candidate; attribution to Nadella is confident. Undated, round-number market-context figure with an undefined observable: 'sensors' is not a category any standard source counts as an installed base, and analyst counts of connected or IoT devices are not the same measure. Without a date, an undated threshold on a cumulative growing count is a matter-of-course extrapolation rather than a genuinely uncertain observable. Fails G2 only; committed grammar ('there's going to be'), own voice, stands alone at 11 words, and the extractor's claim is faithful.

Assessment: The quote supplies a number, but not a date or a definition of the counted
population. Fable's concern about installed sensors versus shipped or
connected devices is reasonable. Its assumption that the count grows
cumulatively is not guaranteed by “sensors out there,” which can denote an
installed population. Its assertion that no standard count exists is also
unsupported within the supplied evidence. The boundary between a named numeric
observable and an insufficiently defined count remains a spec judgment.

## What n = 24 supports

It supports a description of these reviewed proposals: 11 accepted and 13
rejected. It also supports identifying particular failures or ambiguous rules.
A counterexample can reveal a problem without a large sample.

It does not support a general claim that either current spec is defective
because most proposals fail verification. These cases mix old extraction
contracts with newer verification contracts, and the verifier sees less evidence.
The 24 reviewed records represent only 1.6% of the 1,494 proposals.
They come from the initial pilot, whose documented selection favored short,
dated recordings. They are not a random sample of the pending corpus.
Five candidates share one transcript, and multiple verdicts share prompts.

For 11 successes in 24 independent Bernoulli trials, the 95% Wilson interval
is **0.2789–0.6493**. The equal-tailed exact binomial interval is
**0.2555–0.6718**. These calculations are useful scale indicators.
Their assumptions do not account for the pilot's selection, within-transcript
dependence, or changed contracts.

The saved extractor marked 11 reviewed candidates as undated, and Fable rejected
all 11. All 11 accepted candidates carry explicit or inferable horizons.
The two remaining rejections are the dated IBM quote and the dated Hotz map
claim. This pattern is consistent with the stricter treatment of undated
claims. It does not establish that dates alone caused the verdicts.

There are no shared negative examples in this set: the verifier reviews only
extractor positives. There is no reverse Fable-extracts/Astra-verifies arm.
Neither symmetric agreement nor Cohen's kappa can be inferred from these data.
Precision and recall also require reference labels that this audit does not supply.
The report's classifications must not be converted into a corrected acceptance rate.

## Changes and next action

The page builder previously said:

> The two models agreed on 46% of the candidates they both judged.

It now says:

> Verifier acceptance: 11 of 24 extractor-proposed candidates reviewed (46%).

The displayed denominator is `accepted + rejected_by_verifier`.
With no reviewed proposals, the page says the rate is not yet measured.
The description also now states that the verifier receives 400 words on
**each side**. The stored `agreement_rate` key remains unchanged for compatibility.
This commit changes the builder source. It does not deploy the public page.

The next useful step is to settle a small set of reference labels using this
audit before spending quota. The policy needs explicit treatment of undated
numeric thresholds, named capabilities, context-derived comparisons, and
claim details outside the verifier window. Any later model comparison must
pin both contracts and give each stage sufficient evidence for its task.
The existing strictness decision can remain in force while those rules become
more precise.

No large verification pass is authorized by this audit. A later paid run
requires the operator's approval. Repeating verification alone would still
compare newer rules against these older extraction outputs.

## Reproduction

From the code clone, the supplied live-data check is:

```sh
.venv/bin/python -c "import json;c=json.load(open('data/predictions/index.json'))['corpus'];print(c['accepted'],c['rejected_by_verifier'],round(c['agreement_rate'],4))"
```

Expected output for the reviewed snapshot: `11 13 0.4583`.
If the live output changes, the pinned evidence remains available with:

```sh
git -C data show 06f1ec2:predictions/index.json
```

This read-only command reconstructs the case list, contract pairs, and Wilson
interval directly from the private commit:

```sh
.venv/bin/python - <<'PY'
import collections, hashlib, json, math, subprocess
pin = "06f1ec2"
def data(*args):
    return subprocess.check_output(["git", "-C", "data", *args], text=True)
rows = []
for path in data("ls-tree", "-r", "--name-only", pin, "predictions").splitlines():
    if not path.endswith(".jsonl") or any(p.startswith("_") for p in path.split("/")):
        continue
    rows.extend(json.loads(line) for line in data("show", f"{pin}:{path}").splitlines())
reviewed = [r for r in rows if r["verification"]["status"] == "ok"]
a, n = sum(r["accepted"] for r in reviewed), len(reviewed)
print(a, n-a, round(a/n, 4))
print(collections.Counter((r["extraction"]["harness"], r["verification"]["harness"])
                          for r in reviewed))
print(collections.Counter((r["extraction"]["contract_id"], r["verification"]["contract_id"])
                          for r in reviewed))
for r in reviewed:
    if r["verification"]["agreement"] is False:
        print(r["prediction_id"], r["transcript_id"])
p, z = a/n, 1.959963984540054
mid = (p + z*z/(2*n))/(1 + z*z/n)
half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/(1 + z*z/n)
print("Wilson", round(mid-half, 4), round(mid+half, 4))
for rev in ("05d70a0", "ab05764", "1e1555a", "1ee170c"):
    ids = []
    for spec, schema in (("EXTRACTION.md", "extractor_output.schema.json"),
                         ("VERIFICATION.md", "verifier_output.schema.json")):
        blobs = [subprocess.check_output(
            ["git", "show", f"{rev}:.claude/skills/prediction-extractor/{f}"])
            for f in (spec, schema)]
        ids.append(hashlib.sha256(b"".join(blobs)).hexdigest()[:12])
    print(rev, *ids)
PY
```

The page's existing quota-free checks ran with:

```sh
.venv/bin/python scripts/test_predictions_site.py
```

Actual result: `28/28 passed`.
The local builder produced a page with 11 accepted candidates and 13 rejections
counted but not embedded. Its method text contains the new `11 of 24` label.
A separate check verified that zero reviewed proposals display “not yet measured.”
Before the wording change, the assertion for the directional label failed.
After the change, it passed.

The report check found all 13 rejected IDs and verified all 52 candidate,
claim, and recorded-reasoning quotations against the pinned records.
The reproduction command above ran successfully and returned
`11 13 0.4583` and `Wilson 0.2789 0.6493`.
