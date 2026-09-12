# Predictions policy reconciliation and pilot rerun

Claimed by `repo-4`, 2026-09-12. The operator authorized code updates and a
rerun of the original extractions, following the recommendation to verify
their new candidates with Fable. Existing live results remain unchanged.

- PR-1 (shared policy and compatible contract release): succeeded; both prompts expand one policy and validate the release pins.
- PR-2 (cache provenance and acceptance reporting by contract pair): succeeded; stale results fail without a call or overwrite.
- PR-3 (frozen pilot, 11 Astra extractions followed by Fable verification): attempted; preparation only, no calls yet.

Source evidence: public code `eb9e3b0`, private data `06f1ec2`.
The 11 original successful extraction jobs produced 24 reviewed candidates
across 10 transcripts; the remaining transcript produced none.
The other 655 successful jobs used extraction contract `d795f6f1d88b`.

Run bounds: the original 11 transcripts only, extraction pinned to
`gpt-6-astra`, verification pinned to Fable, no Gemini or model fallback.
Run one transcript through both stages first and inspect its raw outputs.
Then run the remaining transcripts with two workers. Each stage gets one
initial attempt and at most one retry for a classified transient failure.
Quota or authentication failures stop dependent work and are reported.
No corpus verification, market pass, deployment, or live-result replacement.

The runner records Astra's requested model, not an independently verified
served identity. That limitation applies to the old and new extraction.

Validation commands and run locations will be recorded here before launch.

## Release and checks

Release `predictions-2.0` pins extraction `99d9132159a2` and verification
`820583f899f6`. It keeps the newer strict policy and clarifies the remaining
boundaries. Named undated milestones can qualify but have no deadline for an
outcome score. Both stages use the same comparison and evidence rules.
This is a substantive policy revision. Existing records remain historical
results, including the 655 extractions under the previous current contract.

The full quota-free suite returned `40/40 test files passed`. The two initial
regressions failed before implementation: the old cache returned `cached`,
and no shared policy existed. Nine new tests now cover those cases, changed
inputs/prompts/model requests, successful cache reuse, compatible verification,
empty outputs, contract-pair reporting, and complete CLI response capture.
Four unrelated tests needed local socket/process/file-mode permissions.
The harness signature check was updated for its optional response-capture path.

Pilot location: `data/predictions/_experiments/policy-2-2026-09-12/`.
It contains a frozen snapshot, separate results, exact prompts and raw responses.
No file in the live candidate directories is replaced. Only repo-0 can commit
these private artifacts; their commit status will be checked after the run.

The first case is `george-hotz/mapbox-n9wxlr`. It covers the distant map
details and measured-comparison cases from the audit. This is a regression
pilot on cases that informed the policy, not a held-out generalization test.
