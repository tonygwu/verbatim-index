# Predictions policy reconciliation and pilot rerun

Claimed by `repo-4`, 2026-09-12. The operator authorized code updates and a
rerun of the original extractions, following the recommendation to verify
their new candidates with Fable. Existing live results remain unchanged.

- PR-1 (shared policy and compatible contract release): attempted; implementation underway.
- PR-2 (cache provenance and acceptance reporting by contract pair): attempted; implementation underway.
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
