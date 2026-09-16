# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Verbatim Pundits

- **The 25-word quote cap is uneven, and moving it costs a full re-grade.**
  Filed 2026-09-16, MEASURED 2026-09-16 after an adversarial audit.
  Measure it any time with:

  ```
  .venv/bin/python scripts/filter_incidence.py --logs data-pundits/logs/p8a2 \
      data-pundits/logs/p8a --obsolete data-pundits/grades/_obsolete \
      --match "exceeds 25 words" --attempted 50
  ```

  Across all eight grading rounds it rejected **24** grades:

  ```
  by judge   fable 5 (5.0%)   gemini 19 (19.0%)     ratio 3.8x, flagged SKEWED
  by cell    gemini/blinded 12, gemini/open 7, fable/open 4, fable/blinded 1
  by person  hasan-piker 5, steven-bonnell 5, ana-kasparian 3, asmongold 3,
             coleman-hughes 3, ezra-klein 2, matt-walsh 2, ben-shapiro 1,
             charlie-kirk 0, sam-seder 0
  ```

  So it is not the uniform ~8% tax the first version of this entry implied. It
  is a filter on ONE judge's formatting habit, and every rejection is re-graded
  until it passes, which selects which of that judge's samples reaches the
  corpus. The audit measured the selection at +1.07 points (se 0.77, n=24),
  which is not distinguishable from zero at this size.

  **Changing the cap re-grades everything.** The number lives in RUBRIC.md and
  judge_output.schema.json, both hashed into `contract_id`. VERIFIED by
  simulation: raising it to 40 words moves the contract from
  `3844dd2693acd471` to `7aa8f163de1f0b2e`, which makes every grade already
  collected incompatible at aggregation. Decide before the full P9 run, while
  the re-grade cost is 200 cells rather than a thousand. Three options, none
  measured yet: raise the cap; keep the cap but relax the HANDLING so an
  overrun is recorded rather than rejecting the whole grade, which does NOT
  change `contract_id` because the check lives in `grade.py`; or accept the
  re-grade cost and budget for it.

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
