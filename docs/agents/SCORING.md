# How grades become the published score

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you change `aggregate.py`,
calibration, the venue adjustment, the subject-share cutoff, the rank floor or
the bootstrap, or quote a number from `results.json`.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Rules that exist because something broke

- **Nuisance effects are estimated and subtracted, not assumed away.**
  `calibrate()` does it for judges, `venue_effects()` for the format of the
  appearance. Both fit the effect with the other factor held fixed, because raw
  means confound the two: leaders are not spread evenly across venues, so the
  raw 8.2-point spread across formats is only 5.7 once the speaker is held
  fixed. Fitted per dimension, since the score is a weighted sum of the three,
  and the bootstrap interval reads the same adjusted values as the point
  estimate or the dot lands outside its own bar.

- **A record that failed validation is not a grade, and nothing may read a field
  off one.** `load_grades` marks it `_excluded`, but the split acting on that
  mark used to run AFTER `filter_unscorable`. On 2026-09-09 Astra refused
  `tim-cook/the-bulwark-and-the-prof-zi07-f` and wrote a record whose `grade`
  held one key, `error`. Fable had scored the same recording at 0% subject
  share, so the whole recording fell under the cutoff and every grade for it
  reached the unscorable report, that record included, and `aggregate.py` died
  with `KeyError: 'subject_speech_share_pct'` on every cycle for the next 13
  hours. The split now runs first. A non-grade that validation did NOT catch
  stops the run with a message naming the file, never a default share, and the
  four buckets are checked to add up to the files read.

- **A count derived from the roster is not a count of the board, and since
  2026-09-18 they are different numbers.** The roster holds 57 and the leaders
  board holds 50. Adding seven predictions-only people broke FOUR separate
  counts in the same way, and they were found by sweeping for the pattern rather
  than one at a time:

  ```
  status.sh            leaders at 5+ 50/57, leaders at zero 7, every cycle
  coverage_table.py    leaders with any transcript 50/57
  fetch_loop.sh        exits when leaders_at_target >= leaders. at_target caps
                       at 50 against 57, so COMPLETE was UNSATISFIABLE and the
                       loop would have re-fetched YouTube for ever
  fetch_happyscribe.py --report-unsearched returned the seven every cycle, so
                       happyscribe_loop.sh ran a sitemap crawl every cycle
  ```

  The fetch_loop one is the reason this is a rule and not a note. An unbounded
  fetch loop is how the IP blocks already recorded in `BACKLOG.md` happen, and
  repo-3's pundits fetcher was IP-blocked while this was being fixed. The others
  are the shape this repo already knows: a component reporting a false number
  every cycle teaches the operator to stop reading the line, and the next real
  shortfall lands in an output nobody trusts.

  All four now scope through `membership.for_study(study, path)`, the same one
  function the three P2 readers use, and all four REPORT the excluded people on
  their own line rather than quietly dropping them, because "deliberately not
  here" and "missing" are different facts and they were the same number before.
  A keyed lookup such as `by_slug[slug]` is fine and needs no scoping;
  `normalize_transcripts.py` in fact requires the seven present, since it refuses
  a transcript whose slug has no roster entry. It is the COUNTS that lie.
  Guarded by `scripts/test_coverage_counts_the_board.py`, which extracts and RUNS
  fetch_loop.sh's own coverage block rather than reading it.

## Measurement decisions, and why

These change the published number. Each was measured before it was chosen, and
the measurement is named so a later reader can re-run it rather than trust it.

- **The roster is 57 people and the leaders board is 50, and
  `longform_availability` means two different things.** The two numbers stopped
  being the same on 2026-09-18, when seven investors were appended at ranks 51 to
  57 for the PREDICTIONS board only. `membership.json` is what separates them, so
  a figure below that says "of 50" still describes the leaders board correctly.
  It was 40 until 2026-09-10, when C.C. Wei was withdrawn and eleven
  were added: Tobi Lütke, Michael Saylor, Eric Schmidt, Ilya Sutskever, Aaron
  Levie, Dylan Field, Amjad Masad, George Hotz, Greg Brockman, Vlad Tenev and
  Alexandr Wang. Any figure in this file that says "of 40" is a record of a
  measurement taken on the smaller board and is left alone; re-running it today
  would give a different number. `docs/ROSTER-EXPANSION-2026-09-10.md` carries
  the selection reasoning, including why Marc Andreessen and Garry Tan are still
  out.
  The field trap is `longform_availability`. It now holds ONE measured quantity
  for all 50: the number of long-form YouTube results that pass
  `discover_sources`' own duration, clip and third-person filters AND an
  identity screen wanting the full name, or the surname together with a company
  token, in the title or channel. The old scout-estimate medians are preserved
  per person as `longform_availability_scout_median`, on the 39 that had one.
  **The two scales are not interchangeable.** RE-COMPUTED 2026-09-11 from
  `data/roster/final.json`: Pearson r is 0.74 over those 39, scout mean 74 on a
  7-200 range against measured mean 39 on a 19-65 range, and
  the measured scale is compressed because the search pool caps near 90 results.
  Read the field name before comparing two leaders. The identity screen is the
  part that earned its keep: C.C. Wei scores 20% purity on it and every other
  leader scores 83% or better, which is how the wrong-person class was sized.

- **A leader is not ranked below `MIN_TRANSCRIPTS_TO_RANK` included
  transcripts, and is kept and scored anyway.** Five, which is the
  high-confidence band, so the floor is one constant rather than a second number
  to keep in step. Below it the leader keeps every grade and every transcript
  and keeps a blinded score in `results.json` under `unranked`, but takes no
  rank and does not appear on the page. Asked for 2026-09-10, when the
  wrong-person withdrawal left C.C. Wei with 2 real transcripts: a
  two-transcript row is a placeholder and the board should not carry it as a
  score. `diagnostics` carries `min_transcripts_to_rank` and `leaders_unranked`,
  `coverage_table.py` still shows an unranked leader's score, and the page
  explains the floor from the constant instead of a typed number. Guarded by
  `scripts/test_rank_floor.py`, 13 checks. On the corpus today the floor binds on
  nobody: `min_transcripts_to_rank 5`, `leaders_unranked []`, 50 of 50 scored.

- **Per-judge calibration.** `calibrate()` maps each judge's score distribution
  onto the pooled one, per dimension, and only when that judge's spread is
  meaningful (`sd >= 3.0`), because rescaling a flat judge amplifies noise.
  Fable currently runs 9.0 points below Astra on clarity, 4.9 on insight and
  2.4 on technical depth. What calibration cannot fix is an uneven judge MIX
  per leader, so watch `judge_call_counts` when a quota window closes. Gemini
  runs above Fable on every dimension and above Astra on insight and technical
  depth. Measured 2026-09-10: raw insight means are Fable 56.0, Astra 60.9,
  Gemini 61.8. Pairwise agreement on the overall score is Astra-Fable 0.895,
  Fable-Gemini 0.869, Astra-Gemini 0.848.

- **Calibration is MARGINAL, and a residual judge-by-length effect survives it.**
  `calibrate()` matches each judge's whole-corpus distribution to the pooled one,
  so it removes a constant offset and a spread difference. MEASURED 2026-09-09 on
  the 470 complete cases: after calibration the residual judge effect is
  essentially zero on the 336 transcripts under 15k words (all three within 0.05
  on `d2_insight`). It is NOT zero at the top end. On 25k-40k transcripts Gemini
  sits about -0.93 points below the three-judge mean, weighted across dimensions,
  and the other two sit above it.

  A single global mean and sd per judge cannot absorb a slope against transcript
  length, which is why this survives. The practical size is small: dropping
  Gemini from a long transcript raises it ~0.47 points, so a leader's score moves
  by that times their share of long transcripts, at most +0.18 for
  brian-armstrong. Against a board where no adjacent pair separates at 95%, that
  is noise. Left uncorrected on those grounds, with n=26 in the top band making
  -0.93 an upper bound.

  Worth knowing for whoever next touches this: `venue_effects()` fits an ADDITIVE
  model and estimates the nuisance effect with the speaker held fixed, which is
  the conditional treatment. `calibrate()` does the marginal one for judges. The
  repo therefore holds itself to a higher standard for venue than for judges. The
  natural upgrade is a two-way `score ~ transcript + judge` fit, which handles
  unbalanced judge coverage natively. Not done, because the measured residual
  does not justify re-deriving 2,000 grades.

- **Venue adjustment.** `venue_effects()` fits an additive leader-plus-venue
  model and subtracts what the FORMAT is worth with the speaker held fixed.
  Leaders are not spread evenly across formats: some are entirely long-form
  podcast, others never appear on one, so raw means confound the two. Measured
  2026-09-07: raw spread across venue types 8.2 points, spread with the leader
  held fixed 5.7 (podcast +3.9, keynote -4.1 on insight). 23 of 40 leaders
  change rank, mean 1.2 places, max 7. Fitted per dimension, because the score
  is a weighted sum of the three; adjusting only the composite would leave the
  dimensions, the score and the interval disagreeing. A venue seen fewer than
  `MIN_VENUE_N` times gets exactly zero rather than one transcript's noise.

- **Subject-speech cutoff is 10%, decided per transcript.** Below this share of
  the words the subject is not really in the recording and the grade describes
  somebody else. MEASURED on 785 blinded grades: the distribution is bimodal.
  47 grades sit at 0-4%, a near-empty band of 3 grades spans 5-9%, then a
  continuum runs from 10% upward (16, 14, 9, 11, 26, 30, ...). The old value of
  15 cut through that continuum, leaving 37 grades within five points of the
  line, so small changes reshuffled who was included. 10 sits in the empty band,
  which makes the cutoff describe the data rather than round a number.
  The decision is made once per RECORDING, on the mean of whatever judges
  estimated it. It used to be per grade, so one judge saying 14% and the other
  16% dropped one and kept the other, silently turning a two-judge transcript
  into a single-judge one, which `confidence` then penalised for an unrelated
  reason. Judges agree closely about share: median absolute disagreement 2
  points, mean 3.6. A grade with no estimate is kept, never guessed at.

  **A zero from any judge drops the recording, whatever the mean.** MEASURED
  2026-09-10 on 558 recordings: 10 were on the board with one or two judges at
  0 and another judge at 42 to 86, and all 10 were subject-absent on
  inspection. The high judge had scored the host, a co-guest or a biographer
  and said so in its own notes; Gemini reports the share of the DOMINANT
  speaker, not of the named subject. A mean cannot express "the subject is not
  here". Under this rule 0 of the 10 survive; a median keeps 4. It drops 10
  recordings and moves Jeff Bezos from 7th to 2nd, because two of his three
  subject-absent recordings had scored their hosts at about 40 points.

- **Nothing load-bearing may depend on Python's hash seed.** FOUND by running
  `aggregate.py` twice over a frozen grades directory and getting 36 different
  leader scores. Per-transcript venue was picked with
  `max(set(votes), key=votes.count)`, and string hashing is randomised per
  process, so the winner of a TIE changed between runs. 42 transcripts have the
  judges disagreeing about venue and every one is a one-vote-each tie. Harmless
  while venue was display-only; the venue adjustment made it move the published
  score. `resolve_venue()` sorts before the max and reports whether there was a
  real majority, and the adjustment is applied only when there was. A tie means
  the format is unknown, not resolved.

- **Confidence interval by bootstrap.** A leader's score is a coverage-weighted
  mean over the transcripts we happened to collect, so it carries sampling
  error, and a leader on 3 transcripts carries far more of it than one on 14.
  20,000 resamples of that leader's transcripts with replacement, seeded so
  published endpoints do not drift between runs. Calibration is held fixed
  rather than refitted inside each resample, which would mix corpus-level and
  leader-level uncertainty into one interval; `diagnostics.bootstrap` records
  that choice. The interval reads the SAME adjusted values as the point
  estimate, or the published dot lands outside its own bar.
  What it shows, RE-MEASURED 2026-09-11 on the 50-name board in
  `data/results.json`: 1 of 49 adjacent pairs separates at 95%, and it is the
  last one, rank 49 Tim Cook [43.4, 50.4] against rank 50 Marc Benioff
  [35.6, 39.8]. Every other neighbouring pair overlaps. The board distinguishes
  the top from the bottom, over a 75.7 to 37.9 span, and does not distinguish
  rank 9 from rank 12. The earlier reading of this was 0 of 39 on the 40-name
  board, so growing the roster moved the count by one pair and changed nothing
  about the conclusion. The companion figure quoted elsewhere in this file, a
  median rank range 13 places wide, was measured on that 40-name board and has
  not been re-derived on 50; `results.json` carries no `rank_range`, so it needs
  its own pass.

- **Subject share still predicts the score, and is deliberately NOT corrected.**
  Holding the leader fixed, a transcript where the subject speaks 15-49% scores
  3.4 points below that leader's average and one at 80-100% scores 2.3 above,
  5.7 points end to end. It is a penalty rather than regression toward the mean:
  both strong leaders (-3.8) and weak ones (-2.7) fall on low-share transcripts,
  where regression would have pushed the weak ones up. Left uncorrected because
  less subject speech is genuinely less evidence, so a lower score on it is
  defensible, unlike venue, which says nothing about the quality of thinking.
  Correcting something not understood is worse than leaving it visible.

## Known limits of the published score

Documented rather than fixed, deliberately. Changing any of these now would make
new grades incomparable with the corpus already graded.

- **The published interval does not include judge re-run noise.** `bootstrap`
  resamples a leader's transcripts and holds each grade as a fixed value, so it
  captures sampling across transcripts and nothing about the same judge scoring
  the same transcript differently on a second call. MEASURED 2026-09-07: that
  noise is a within-transcript sd of 0.60 for Astra and 1.15 for Gemini, which
  is +/-0.31 and +/-0.60 at 95% for a 14-transcript leader. The published
  endpoints are therefore slightly narrower than the truth. Left as is because
  the effect is small against a median rank range of 13 places, and because
  folding it in would need repeat grades across the whole corpus rather than the
  eight transcripts measured. Recorded because it is an assumption the number
  carries silently, not because it changes a rank today.
  MEASURED AGAIN 2026-09-10 on 18 transcripts: Fable's within-transcript sd is
  3.24 and its mean drifted +2.44 against grades 1 to 4 days old; Astra 1.53;
  Gemini 4.30. The 2026-09-07 figures were optimistic. Fable's drift is the
  largest unexplained number in the pipeline and deserves its own experiment.

- **Filters bite unevenly, which is a bias and not a detail.** The subject-share
  filter removed 81% of Jeff Bezos's material, and he is scored on what is left.
  Astra refuses politically-charged transcripts, concentrated on Alex Karp and
  Elon Musk, so their evidence has a content-correlated hole. Both appear in
  `diagnostics`; neither appears on the site.
