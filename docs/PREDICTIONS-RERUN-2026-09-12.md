# Predictions policy reconciliation and rerun, 2026-09-12

Implemented release **predictions-2.0** and reran the **11 original transcripts**
with GPT-6 Astra extraction and Fable verification. The new run produced
**24 candidates: 19 accepted, 5 rejected, 0 pending**. All 11 extractions and
10 nonempty verification jobs succeeded. Cook returned no candidates and needed
no verifier call. There were no failed calls, retries, ungrounded quotes,
deduplicated candidates, or candidate-cap hits.

The incompatible-contract and stale-cache defects are fixed. The new **79.17%
verifier acceptance rate is not an accuracy score**. The old and new candidate
sets differ, and this pilot uses cases that informed the policy. Some semantic
judgments remain unsettled, including accepted candidates.

Owner: `repo-4`. The operator authorized the code changes and this bounded rerun.

- PR-1 (shared policy and compatible release): succeeded.
- PR-2 (cache provenance and acceptance by contract pair): succeeded.
- PR-3 (original-transcript extraction, verification and offline audit): succeeded.
- PR-4 (private artifact durability): blocked-on-repo-0-commit; repo-4 may
  write predictions but may not commit the private data repository.

The original live candidates and index remain unchanged. The live check still
returns exactly `11 13 0.4583`. No corpus-wide pass, market call or deployment
was performed. The other 655 successful extractions remain historical results
under extraction contract `d795f6f1d88b`; this release does not silently reuse
or automatically replace them.

## Policy and code decision

Keep the newer strict baseline, with the shared clarifications in
[ELIGIBILITY.md](../.claude/skills/prediction-extractor/ELIGIBILITY.md), rather
than restoring the older permissive extraction contract to raise acceptance.
Both stages now receive exactly the same eligibility rules. Their tasks still
differ: extraction finds proposals; verification checks each proposal's
attribution, eligibility and claim fidelity.

The shared policy distinguishes generic undated announcements from specified
milestones, allows a comparison when the evidence supplies its measure, limits
claim details to the quote and the verifier's 400-word window on each side,
and makes timestamps, interpretable ASR errors and company-controlled outcomes
explicit. Undated accepted milestones have no false-by deadline; six of the
19 accepted records are undated and cannot yet receive time-bounded outcome
scores. A model's belief that an event is inevitable is not an eligibility test.

[POLICY_RELEASE.json](../.claude/skills/prediction-extractor/POLICY_RELEASE.json)
pins extraction `99d9132159a2` and verification `820583f899f6` to the name
`predictions-2.0`. Both specs expand the shared policy before hashing and
prompting. Editing the shared policy changes both hashes; stale release pins
stop the runner before calls. Git preserves earlier spec and schema versions.

The runner now checks contract, release, source input, full prompt and model
request before using a successful cache entry. It preserves a stale result and
returns `cache_stale`, without a paid call or overwrite. Verification refuses
an incompatible extraction even with `--force`. An intentional extraction
rerun can use a separate output directory or explicit `--force`; successful
re-extraction resets verification. Each stage retains input/prompt hashes,
code revision, model provenance, exact prompts and complete CLI responses.

The aggregate reports verifier acceptance separately for each extraction and
verification contract pair. The site uses directional acceptance wording;
the legacy `agreement_rate` field remains for compatibility. No page was deployed.

## What changed in the proposals

The sets share **10 exact quote-based IDs**. Each has 14 IDs absent from the
other, and all ten shared quotes have rewritten normalized claims. A recut
quote creates a new ID for the same underlying forecast, so these counts do
not establish 14 newly discovered or lost predictions. The private
`comparison.md` retains every old/new quote and both models' recorded
explanations. These explanations are not access to internal reasoning.

Several known cases changed as intended:

- Hotz's map claim now uses a quote containing the lane-line and US interstate
  coverage details, which were outside the old verifier window. Fable accepted
  it and the measured Super Cruise comparison.
- The rerun omitted Amodei's generic video-analysis claim, Altman's generic
  model launch and persistent-agent claims, Krishna's indefinite construction
  total and incomplete 65% quote, and Huang's broad protein-design and
  human-language programming claims. Omitting the IBM quote does not establish
  that the underlying 65% target is invalid or that recall improved.
- Huang's application assembly without manual programming survived and was
  accepted. This is explicitly a permitted milestone in the shared policy;
  its success here is a regression check, not held-out evidence.
- Bezos's solar-energy claim survived with a changed quote and was accepted.
  Fable interpreted `sourcils` as an ASR error and allowed company-reported
  annual energy coverage as an observable.
- Nadella's two undated numeric milestones survived and were accepted. Fable
  acknowledged that connected devices and sensor scope were undefined, then
  suggested internet-user/subscriber proxies and an installed-sensor estimate.
  Those measures are not automatically equivalent to the spoken quantities.
  Acceptance has not settled the population-definition boundary.

Full-transcript extraction also found proposals absent from the original set:
Amodei on animal communication, Musk on the California train's cost, Bezos on
customer preferences, Lisa Su on MI500 performance, and Altman on token use.
Their presence is why repeating verification of the old 24 would have tested
a different question from this rerun.

## Review of the five new rejections

These assessments explain the remaining judgments; they are not independent
human reference labels. All five fail G2 only: Fable passes attribution,
claim fidelity and the other four gates. No verdict was hand-corrected.

1. **Amodei, animal communication — defensible extractor error.**
   `fdd213ff6450f0c5`. Astra treats partial decipherment as an observable task.
   Fable notes that “make sense of” and “decode something” supply a domain but
   no specified translation, behavioral test or other checkable success
   condition. I agree with rejection under the generic-capability rule.
2. **Bezos, customers liking low prices — defensible rejection, with a weak
   additional rationale.** `be0bfe6e47339ba4`. Astra treats the future direction
   of preference as observable. Fable finds no metric or success condition.
   That is a reasonable G2 concern; calling the claim a truism is not by
   itself a valid rejection under the new policy.
3. **Bezos, customers liking faster delivery — the same boundary.**
   `99539620bccf9ca3`. The ten-year horizon is supported by the window, but
   Fable finds no defined preference test. A date alone does not supply that
   test. The policy still needs consistent reference judgments for qualitative
   population preferences, especially alongside accepted discourse forecasts.
4. **Su, compute needing to increase 100-fold — defensible extractor error.**
   `a0f4548d8388a2df`. Astra preserves the claim as a future requirement, not
   promised deployment. Fable correctly distinguishes needing compute from
   actually installing it: non-growth does not falsify a need without a
   defined workload or demand-satisfaction test. The original run accepted
   the corresponding quote; changed normalized claims and fresh model
   decisions prevent attributing this reversal solely to the policy change.
5. **Altman, the largest individual token consumer — observability boundary
   still ambiguous.** `0228193468fb7f3d`. Astra treats the worldwide maximum
   and monthly quantity as a numeric observable. Fable rejects it because
   provider-level usage cannot establish a worldwide maximum and the window
   acknowledges incomplete coverage. That coverage concern is real. Its
   categorical assertion that no tracker exists is not established by the
   supplied evidence, and future publication or audits are not ruled out by
   the policy. Leave the rejection recorded; settle what evidence would count
   before treating this case as a reference label.

Accepted cases also need caution: Fable allows an unspecified discourse proxy
for Altman's “talking about AI” forecast and an unspecified performance metric
for Su's MI500 comparison, while rejecting the preference claims for lacking
a metric. Together with Nadella's proxies, this shows why higher acceptance
cannot establish that all ambiguity or model error is gone. Outcome scoring
would also need dated, agreed resolution rules; this run performs no scoring.

## Evidence, execution and provenance

Public code used for every call:
`b114b24845cc8d33425479c07eb5f80a53fbdddd`.
Private source data:
`06f1ec2a1b41aeed5cec0d1c4f0ae85cd180c399`.
The earlier diagnosis is in
[PREDICTIONS-AGREEMENT-2026-09-12.md](PREDICTIONS-AGREEMENT-2026-09-12.md).

Experiment: `data/predictions/_experiments/policy-2-2026-09-12/`.
The frozen snapshot contains 64,533 transcript words and 35 files: 11 source
records, 11 original prediction files, 11 metadata files, roster and index.
Every SHA256 still matches. All 24 original candidates use
`youtube_upload_date` as their statement-date basis. The rerun preserves that
input; it does not independently establish recording dates. Fable specifically
notes that the Musk recording appears older than its upload, so resolved dates
must not be treated as confirmed recording dates or scored outcomes.

The first case, Hotz, ran both stages with one worker under run
`20260912T074135Z-both-e5ce4710`. Both complete responses were inspected and
its record/provenance validation passed before continuing. Astra took 312.6
seconds and Fable 89.0 seconds. The remaining ten recordings ran with two
workers under `20260912T075018Z-both-b652ba4a`. Both detached supervisors
exited 0; the last finished at `2026-09-12T08:25:33Z`. The timeout was 2,400
seconds per call. The bound permitted at most one classified transient retry
per stage; none was needed. There was no model fallback or Gemini call.

Astra was requested as **gpt-6-astra in all 11 calls**, as in the original
extractions. Its CLI supplies no independent served-model identity, so the
records correctly retain `served_model_verified: false`. All ten Fable calls
requested and reported **claude-fable-5-1**. The audit checks the raw
`modelUsage` and confirms Fable was the dominant output model in each call.
Ancillary Haiku usage from the CLI is retained separately, not attributed to
Fable: 183 output tokens across the ten calls. There were no Astra tool-use
events, Fable subagents, Fable permission denials, or reported provider errors.

Usage, counted once per complete CLI response: Astra 326,458 input tokens
(126,720 cached) and 104,414 output tokens (including 94,855 reasoning);
Fable 96,612 output tokens (including 86,768 thinking), 147,645 cache-created
input tokens, 101,260 cache-read input tokens and 20 uncached input tokens.
The Claude CLI reports $7.873948 total list-price-equivalent usage, including
$0.064933 ancillary usage. This is telemetry, not an assertion of a subscription
cash charge. `usage-final.json` and its script reproduce these figures offline.

## Validation and reproduction

The full quota-free code suite returned **40/40 test files passed**. Nine new
policy tests cover shared hashing and release pins, stale inputs/prompts/model
requests, successful cache reuse, compatible verification, empty outputs,
contract-pair reporting, and full CLI response capture on success and errors.
The initial cache/shared-policy regressions failed before implementation.
Four unrelated existing tests required local socket/process/file-mode
permissions. The harness signature assertion was updated for optional response
capture. Provider failures, quota stops and timeouts were not exercised live.

Real-data dry runs verified two more behaviors without model calls: the first
new result returns `cached` for both stages; the 11 original results return
`cache_stale` for extraction and `policy_release_mismatch` for verification.
Even `--stage verify --force --dry-run` rejects all 11 original extractions.
All 22 original candidate/metadata files remained byte-identical.

Final record validation returned **11 files, 24 records, 19 accepted; all
invariants passed**. The provenance audit passed all 35 snapshot hashes and
22 saved stage-input bundles, including source/roster equality, input/prompt
hashes, contracts, code revision, raw responses and model provenance. The
separate aggregate reports one compatible contract pair: 24 reviewed, 19
accepted, 5 rejected, rate `0.7917`. A local pilot render includes the
directional `19 of 24` label, the release name and both contract IDs; it
embeds 19 accepted records and no rejected records. No page was deployed.

From the public repository root:

```sh
P=data/predictions/_experiments/policy-2-2026-09-12
.venv/bin/python "$P/audit.py" "$P" --output "$P/provenance-final.json"
.venv/bin/python scripts/validate_predictions.py --predictions "$P/results" --transcripts "$P/snapshot/transcripts" --report "$P/validation-final.json"
.venv/bin/python scripts/aggregate_predictions.py --predictions "$P/results" --transcripts "$P/snapshot/transcripts" --roster "$P/snapshot/roster.json"
.venv/bin/python "$P/summarize_usage.py" "$P"
.venv/bin/python "$P/build_comparison.py" "$P"
```

Exact paid-run commands and completion records are saved in `first.started.json`,
`remaining.started.json` and their corresponding finish records. These scripts
refuse duplicate phase launches or a changed code revision. No paid rerun is
needed to reproduce the report.

The new result describes this selected, clustered regression cohort. It does
not measure symmetric model agreement, extraction precision, recall, forecast
accuracy, or a causal improvement over the old 11/24. Keep the new release and
its provenance safeguards; use agreed reference cases to resolve the remaining
judgment boundaries before a broader quality comparison or corpus migration.

The private experiment still needs **repo-0** to commit and push
`predictions/_experiments/policy-2-2026-09-12/` in the data repository. That
operation should preserve the live corpus and spend no further model quota.
