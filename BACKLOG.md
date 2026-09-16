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

- **A grade record that failed validation counts as a cache hit.** Filed 2026-09-16.
  `reuse_or_none()` in `scripts/grade.py` returns `cached` whenever the stored
  record's identity matches (study, contract, prompt, input, mode, judge, model,
  run). It never asks whether the stored record is a usable grade, so a record
  with `validation_errors` is skipped forever on re-runs and the cell can only be
  repaired with `--force`. Found live: 6 Gemini cells that failed the 25-word
  quote cap in P8a were reported `CACHED` when scheduled again, which would have
  left six permanent holes in a two-judge panel. A failing test is in
  `scripts/test_pundits_contract.py`
  (`check_invalid_record_is_not_reused`). The fix is to treat a record with
  validation errors, or with no scored dimensions, as absent rather than cached,
  and to say so in the run summary rather than counting it under `cached`.
  Leaders (v1) uses a plain `dest.exists()` check and has the same hazard.

- **Blind lowercase uses of handles that are ordinary words.** Filed 2026-09-15.
  `blind_study()` redacts a handle that is an ordinary English word only where it is
  capitalised, so "Destiny" goes and "destiny" stays. Captions write names in
  lowercase often: `steven-bonnell/destiny-bklnf_` kept "destiny" 16 times in its
  blinded copy, including a sponsor URL "slash destiny". That recording is excluded
  as not political, and none of the 20 P8a picks leaks, so P8a is unaffected. Fix it
  before the P8 full grade: for a handle, the corpus-spread signal used by
  `scripts/build_blind_wordlist.py` can decide when a lowercase use means the person.
  Needs a failing-then-passing test and a re-blind of any affected transcripts.

- **Grade all 93 verified pilot recordings.** Filed 2026-09-15.
  The P6 pilot verified 93 recordings across 10 people. P8a grades only 20 of them,
  2 per person, drawn with a fixed seed, so the harness and first scores can be
  reviewed before quota goes to the rest. Bring this back once the operator has
  looked at the first 20 grades. The remaining 73 are listed in
  `data-pundits/logs/pilot/report.json` under each person's `selected_keys`, minus
  the ones in the P8a schedule. Grading them adds about 438 judge calls
  (73 × 3 judges × 2 modes). The larger set also shows whether format moves
  scores enough to need equal format weighting (option c in `docs/PUNDITS-PLAN.md`).
