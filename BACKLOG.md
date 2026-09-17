# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Verbatim Pundits

- **The 25-word quote cap is uneven. RESOLVED 2026-09-16 by moving the PENALTY,
  not the number.** Filed 2026-09-16, measured the same day, decided by the
  operator during the P9 top-up run.

  The cap limits how much of the transcript a judge may paste back as evidence.
  The judge always read the whole transcript. Until now one over-long quote
  appended a validation error, which invalidated the whole record and threw away
  the score, the reasoning and both other dimensions.

  Measure the incidence any time with:

  ```
  .venv/bin/python scripts/filter_incidence.py --logs data-pundits/logs/p8a2 \
      data-pundits/logs/p8a --obsolete data-pundits/grades/_obsolete \
      --match "exceeds 25 words" --attempted 50
  ```

  Across eight P8a2 rounds it rejected **24** grades:

  ```
  by judge   fable 5 (5.0%)   gemini 19 (19.0%)     ratio 3.8x, flagged SKEWED
  by cell    gemini/blinded 12, gemini/open 7, fable/open 4, fable/blinded 1
  ```

  The P9 top-up then showed WHERE it bites. All four rejections in its first 69
  calls landed on `d3_good_faith`, for both judges and two different people. D3
  asks whether a person applies one standard, answers the question asked, and
  concedes when warranted. None of that is showable in one sentence, because it
  takes a back-and-forth to demonstrate a shift of position. D1 and D2 are
  showable in a single claim. So the penalty selected D3 grades for quote
  brevity, on the dimension carrying 0.30 of the overall score. The audit put
  that selection at +1.07 points (se 0.77, n=24).

  **THE FIX, and why it cost no re-grade.** `grading_contract.quote_overruns()`
  now records each over-long quote with its dimension, word count, speaker and a
  head of the text, and `validate_v2` no longer rejects for it. `grade.py` writes
  them to the record as `quote_cap_overruns`, and `aggregate.quote_cap_report()`
  publishes the incidence by judge and by dimension, so the cap still reports
  what it cut. The number 25 stays in `profiles/pundits.json`, `RUBRIC.md` and
  the schema, all of which are hashed; only the consequence moved, and it lives
  in code no hash covers. VERIFIED: `contract_id` is still `3844dd2693acd471`,
  so the 267 grades already collected stay poolable. Guarded by
  `scripts/test_quote_cap_handling.py`, 24 checks, verified failing first.

  **Known cost, stated rather than hidden:** the corpus now mixes two regimes.
  Grades collected before this change survived reject-and-regrade, so their D3
  quotes are selected for brevity; grades after it are not. `quote_cap` in
  diagnostics is how a later reader tells the two apart.

  Still open: raising the number itself to 40 would move the contract to
  `7aa8f163de1f0b2e` and re-grade everything. Not done, and not needed unless
  the recorded overruns turn out to be large rather than one or two words.

- **A grade record that failed validation counts as a cache hit. FIXED for
  pundits (v2) 2026-09-16; LEADERS (v1) still has it.** Filed 2026-09-16.
  `_v2_stored()` in `scripts/grade.py` returned `cached` whenever the stored
  record's identity matched (study, contract, prompt, input, mode, judge, model,
  run). It never asked whether the stored record was a usable grade, so a record
  with `validation_errors` was skipped forever on re-runs and the cell could only
  be repaired with `--force`. Found live: 6 Gemini cells that failed the 25-word
  quote cap in P8a were reported `CACHED` when scheduled again, which would have
  left six permanent holes in a two-judge panel. It now treats a record with
  validation errors, or with no scored dimensions, as absent, moves it to
  `_obsolete/` and says so. Guarded by `check_invalid_record_is_not_reused` in
  `scripts/test_pundits_contract.py`.
  (An earlier version of this entry named the function `reuse_or_none()`, which
  has never existed in this repo. I invented it while writing a test and then
  quoted my own invention back here as if it were the code. Check the name
  against `grep` before filing, not against memory.)
  **Still open: leaders (v1) uses a plain `dest.exists()` check and has the same
  hazard.** Its fix is the same shape but it is not the same code path, and any
  change there must keep `test_profile_leaders_identity.py` at 0 differences.

- **Blind lowercase uses of handles that are ordinary words.** Filed 2026-09-15.
  `blind_study()` redacts a handle that is an ordinary English word only where it is
  capitalised, so "Destiny" goes and "destiny" stays. Captions write names in
  lowercase often: `steven-bonnell/destiny-bklnf_` kept "destiny" 16 times in its
  blinded copy, including a sponsor URL "slash destiny". That recording is excluded
  as not political, and none of the 20 P8a picks leaks, so P8a is unaffected. Fix it
  before the P8 full grade: for a handle, the corpus-spread signal used by
  `scripts/build_blind_wordlist.py` can decide when a lowercase use means the person.
  Needs a failing-then-passing test and a re-blind of any affected transcripts.

- **Grade the rest of the verified pilot recordings.** Filed 2026-09-15,
  re-counted 2026-09-16.
  The P6 pilot verified **89** recordings across 10 people, not 93, and the panel
  is **two** judges, not three, so both figures in the first version of this entry
  were wrong. Counted from `data-pundits/logs/pilot/report.json`:

  ```
  ana-kasparian 6   asmongold 13   ben-shapiro 22   charlie-kirk 5   coleman-hughes 7
  ezra-klein 7   hasan-piker 8   matt-walsh 8   sam-seder 7   steven-bonnell 6
  ```

  P8a graded 20 and P8a2 tops up to 5 each, which is 50. The remaining **39**
  cost about **156 calls** (39 × 2 judges × 2 modes). Schedule them with
  `schedule.py build --target-per-person 12 --graded ... --verified ...`, which
  counts what is already complete rather than adding a fixed number; 12 is the
  P5 target. Note the pool is very uneven: Ben Shapiro has 22 verified and
  Charlie Kirk has 5, so a target of 12 leaves a reported shortfall for most
  people and the equal-format-weighting question (option c in
  `docs/PUNDITS-PLAN.md`) has to be settled against that imbalance, not assumed
  away.
