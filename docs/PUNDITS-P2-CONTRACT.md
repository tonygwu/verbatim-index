# Pundits study, P2: grading contract v2, cache identity, aggregation refusal

The P2 record for the pundits plan (revision 2). Leaders is unchanged: it stays
on contract v1, and its outputs match the P0 baseline.

## What changed

**Contract v2** (`scripts/grading_contract.py`). A study whose profile says
`contract_version: 2` gets a `contract_id` that hashes every setting that can
change a score:
- `RUBRIC.md`, `judge_output.schema.json` and `PROMPT.md` from the study's
  skill directory;
- `RENDERER_VERSION`;
- the profile's `scoring`, `identity_treatment` and `blinding` blocks, with the
  wordlist hashed by its bytes;
- `judge_requests`.

`PROMPT.md` carries both modes as `<<<BLINDED>>>` and `<<<OPEN>>>` blocks, so an
edit to either branch moves the hash. Paths, the domain, the site and the
description are excluded. They go in a per-run provenance record,
`<grades>/_provenance/<id>.json`, which also names the code commit and the data
revision. Each grade refers to that record by `provenance_id`.

**Identity on every v2 grade.** Each grade stores eight identity fields: study,
contract, `prompt_sha256` for the prompt actually sent, `input_sha256` for the
exact transcript file, mode, judge, requested model and run. It also stores
`served_model` and `served_model_verified`. The verified flag is true only when
the response itself names the model. That holds for Fable and Gemini. Astra's
harness only echoes the request, so its grades are marked unverified.

**Cache reuse** (`grade.py grade_one`). A stored v2 grade is reused only if all
eight identity fields match the job.
- Any mismatch returns `stale_cache`, names every differing field, leaves the
  file byte-identical, and makes the run exit 1.
- `--force` first moves the old grade to `<grades>/_obsolete/`, then writes the
  replacement.
- Leaders (v1) jobs keep the old rule: an existing file is reused.

**Other `grade.py` checks.** A v2 run refuses to start if a profile's requested
model differs from the model the harness would send. v2 grades are validated
against the profile's scoring. A dimension counts as `supported` only with at
least 2 scored sub-criteria and at least 2 quotes from the subject.

**Aggregation** (`aggregate.py`). For a v2 study, aggregation checks every grade
right after loading. It refuses a grade from another study, a grade under any
other contract, and a slug that is not on the roster. The contract check still
refuses when the corpus holds only one contract, if that contract is obsolete.
There is no override. `load_grades`, `coverage_table.py` and normalize's prune
all skip `_obsolete/`.

## Choices made while implementing

- The pundits `scoring`, `identity_treatment`, `blinding` and `judge_requests`
  values are provisional until P3 and P5 freeze them. No pundits grade exists
  yet, and any change moves the contract id.
- `VI_PROFILES_DIR` is a test seam, like `VI_SHADOW_JUDGES`. It lets a test run
  the real `aggregate.py` against a fixture profile. Production reads
  `profiles/`.
- `guard_aggregate` now treats a study's own link as live when no production
  checkout is registered for that study. It used to refuse every aggregate. The
  owner may still write into the link and no other clone may. This keeps the
  tests independent of each clone's git config.
- `identity_mismatch` reports every differing field, not just the first. A
  changed mode also changes the prompt hash, and naming only the hash would hide
  the cause.
- Two source-reading tests needed updates. `test_grade_harness` now expects the
  new failure label `E_STALE_CACHE` in `ALL_ERROR_TYPES`. `test_refusal_retry`
  now slices from inside `grade_one`. Before, its first fable check matched the
  new v2 helper that sits above `grade_one`.

## Evidence, 2026-09-14

- `scripts/test_pundits_contract.py`: 22/26 before `grade.py` and `aggregate.py`
  were wired, with every failure in the cache and aggregate checks. After:
  41/41.
- `scripts/test_study_isolation.py`: 45/45, including the two new checks for
  aggregating into an unregistered study's link.
- Full suite: `ran 45 python tests + 1 js; failed: 0`.
- Leaders byte identity: `scripts/leaders_baseline.py` on the P2 code, against
  the P0 snapshot. It matched run 1 on all 1,328 prompts, `results.json`, the
  audit file, the site, calibration, the QA and normalize logs, the coverage
  output and the fingerprint. The only difference was
  `normalization.normalized_at_utc`.

## Not done here, by plan

- The aggregation math and the site are still keyed to the leaders dimension
  names. A pundits corpus passes the contract check and then fails on
  `KeyError: 'd1_clarity'`. Making scoring profile-driven is P4.
- Judges are not yet denied tools, and Astra's served model is not verified.
  That is P3.
- The pundits `RUBRIC.md`, schema and `PROMPT.md` do not exist yet, so a real
  pundits grading run is refused with "contract v2 needs ... which does not
  exist". That is P5.
