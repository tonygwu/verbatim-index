# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Verbatim Pundits

- **The 25-word quote cap costs about 9% of judge calls.** Filed 2026-09-16.
  In P8a, 7 of 80 panel cells failed validation, and every one failed on the same
  rule: `d1_steelmanning` or `d3_good_faith` quote exceeds 25 words. It hits both
  arms (6 Gemini, 1 Fable), so it is the rubric's ask rather than one judge's
  habit, and `AGENTS.md` records the same failure mode on the leaders board
  ("Astra failed schema validation three times here, so the quote-cap overrun is
  not unique to the new arm"). Each failure costs a full re-grade of a 20k-word
  transcript. Options, none yet measured: raise the cap; keep the cap but have
  the judge truncate its own quote to the cap; or accept the re-grade cost and
  budget for it. Measure before changing anything, because the cap is part of
  the grading contract and changing it makes new grades incomparable with the
  ones already collected.

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
