# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Verbatim Pundits

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
