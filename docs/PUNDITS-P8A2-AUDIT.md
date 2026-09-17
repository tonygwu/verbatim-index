# Adversarial audit of the P8a2 pundits pilot board

Audited 2026-09-16 against `data-pundits/results.json` (200 grades, 50 recordings, 10 people),
`scripts/aggregate.py`, `scripts/grade.py`, `scripts/schedule.py`, `docs/PUNDITS-PLAN.md`,
`docs/PUNDITS-P8A-PILOT.md`, and `/Users/tonygwu/pundits-pilot-board.html`. No repo file was
modified (`git status --short --branch` printed only `## main...origin/main`). No judge quota was
spent. Scratch work is under `$TMPDIR/audit-agg/` and `$TMPDIR/audit_recompute.py`.

## Verdict

The arithmetic is right and the page is wrong in places. An independent recomputation from the
raw grade files reproduces every published score, dimension, interval, open score and halo to the
printed digit, and the real `aggregate.py` run on a temporary copy reproduces the leaders block
exactly. What does not hold up is the method around those numbers and the copy that describes
them. The venue adjustment was applied although the plan's own support rule fails on two of its
three conditions, and it rests on a contrast identified by 15 of 38 rows from four people, with two
venues pinned to zero by a centring convention that moves people by up to 2.6 points. The page's
drawer shows per-dimension open-minus-blinded deltas that mix a venue-adjusted blinded score with an
unadjusted open score, which inverts the sign for two people and prints a +4.8 "halo" for Ezra
Klein where the true value is 0.0. The halo itself is a judge-level disagreement dressed as a panel
effect: the two judges' halos have opposite signs for 8 of 10 people, and the one "significant"
positive halo (Asmongold) is Fable +6.6 against Gemini -1.4 with an interval that never sees the
judge axis. The retry cap the plan prescribes was not enforced (Fable retried 39% of nominal
calls, Gemini 28%), and a latent bug lets drift-anchor repeats leak into published scores as soon
as the plan's anchors are used.

## CRITICAL

### C1. The page's per-dimension "Δ" column and its Open column mix venue-adjusted blinded scores with unadjusted open scores; two deltas have the wrong sign

`aggregate.py` adjusts only blinded rows for venue (lines 925-931) and `agg()` picks
`cal_<dim>_venue_adj` only when the key exists (line 955), so `leaders[].blinded` is adjusted and
`leaders[].open` is not. The page then prints `dims_open - dims` in the drawer and shows `open`
beside `blinded` in the main table. Recomputed from `results.json` transcripts, both sides
unadjusted (`round(wmean(open)) - round(wmean(blinded))`):

```
person           dim              page shows   true (both unadjusted)
ezra-klein       d3_good_faith      +4.8          +0.0
coleman-hughes   d3_good_faith      +4.1          +0.3
sam-seder        d3_good_faith      +3.9          -0.9     SIGN FLIP
charlie-kirk     d3_good_faith      +3.3          +0.4
asmongold        d3_good_faith      -2.4          +2.5     SIGN FLIP
hasan-piker      d3_good_faith      -1.0          +0.0
```

The +4.8 for Ezra Klein is the d3 conversation effect (4.822) exactly. The main-table implication
is wrong in sign too: page open minus blinded for Ezra Klein is +0.9, Sam Seder +1.3, Charlie Kirk
+0.6, while the published halos are -0.46, -0.19 and -0.27. A reader who subtracts the two columns
the tooltip tells them to subtract ("Halo = open - blinded") gets the opposite sign from the halo
column three rows over. The `results.json` open block carries the same inconsistency, so this is a
data-shape defect, not only a rendering one.

## MAJOR

### M1. The venue adjustment was applied although the plan's support rule fails, and the rule is not implemented anywhere

`docs/PUNDITS-PLAN.md` lines 325-329: the adjustment "needs every venue type to have n >=
MIN_VENUE_N and to appear for at least 3 people, and 80% of people to have at least 2 venue types.
Otherwise the board publishes unadjusted scores and says why. In both cases a leave-one-venue-out
sensitivity is reported."

Measured on this board (`venue_counts` in results.json; per-person venue sets from transcripts):

```
solo 7, debate 4          -> below MIN_VENUE_N=8: condition 1 FAILS
people with one venue type: ezra-klein, sam-seder, asmongold -> 70% have >= 2: condition 3 FAILS (needs 80%)
leave-one-venue-out sensitivity: absent from results.json
```

`venue_effects()` checks only `n >= min_n` and `len(fittable) >= 2` (aggregate.py:513-516).
`grep -n "80%\|at least 3 people\|leave-one-venue" scripts/*.py` finds nothing. The page lists
"The venue adjustment fires" under "What changed since the 20-recording pilot" as an improvement.

Size of what it did (recomputed with the adjustment removed): every score moves, no rank changes.

```
                 published  unadjusted
ezra-klein          71.2       72.5
asmongold           30.0       28.7
hasan-piker         36.5       36.2
ben-shapiro         43.1       42.8
```

The docstring's claim that centring "so the overall level of the leaderboard does not move" is
false with 13 reaction against 26 conversation rows: the mean adjustment over the 50 blinded rows is
-0.361 points.

### M2. The venue model is identified by four people and 15 rows, and the two pinned venues sit at an arbitrary midpoint

The exact-negative pairs (reaction -4.822, conversation +4.822 on d3) are a centring artifact and
not a bug: with two free levels centred to sum to zero there is one parameter, the contrast. The
contrast itself is correct. Alternating means gives -9.644 and an exact within-person least-squares
solve (Frisch-Waugh, demeaned by person) gives -9.643.

What carries it: only people who have BOTH venues inform the contrast.

```
people with both reaction and conversation: steven-bonnell, matt-walsh, hasan-piker, ana-kasparian
rows carrying within-person information: 15 of 38 fitted rows
within-person d3 reaction minus conversation: -1.1, -7.5, -13.5, -13.4
```

That contrast is then applied to Ezra Klein (5 conversation), Sam Seder (5 conversation) and
Asmongold (5 reaction), none of whom contributed to it. Solo (Ben Shapiro 3, Matt Walsh 3, Ana
Kasparian 1) and debate (Charlie Kirk 2, Coleman Hughes 1, Steven Bonnell 1) get exactly 0, which
under the sum-to-zero centring means "exactly halfway between reaction and conversation". Nothing
measured that. Re-centring is a free choice and it moves people:

```
convention               ezra-klein  asmongold  hasan-piker  charlie-kirk
midpoint (published)        71.2       30.0       36.5         31.8
conversation pinned at 0    72.5       31.3       37.8         32.6
reaction pinned at 0        69.9       28.7       35.2         31.0
```

Ranks do not change under any of the three. The numbers on the page do, by up to 2.6 points, on a
convention the page does not disclose.

### M3. The halo interval ignores the judge axis; the two judges disagree in sign for 8 of 10 people

`paired_halo()` resamples transcripts and averages the two judges' pairs inside each transcript, so
judge disagreement never widens the interval. From `results.json` `halo.by_judge_calibrated`:

```
person           halo   95% CI            fable   gemini   judge gap
ezra-klein      -0.46  [-1.42,+0.50]      -1.59   +0.67     2.26  opposite signs
coleman-hughes  +0.13  [-1.87,+1.91]      -0.36   +0.61     0.97  opposite signs
sam-seder       -0.19  [-1.07,+0.63]      -1.81   +1.43     3.24  opposite signs
ana-kasparian   +0.25  [-0.96,+1.53]      +1.85   -1.34     3.19  opposite signs
hasan-piker     -1.09  [-2.68,+0.23]      -3.06   +0.89     3.95  opposite signs
matt-walsh      +1.42  [-0.22,+3.03]      -1.07   +3.92     4.99  opposite signs
charlie-kirk    -0.27  [-1.21,+0.67]      -0.63   +0.09     0.72  opposite signs
asmongold       +2.56  [+1.64,+3.67]      +6.57   -1.45     8.02  opposite signs, CI excludes 0
ben-shapiro     -1.94  [-3.84,-0.08]      -1.83   -2.06     0.23  agree, CI excludes 0
steven-bonnell  +0.91  [-2.31,+5.03]      +0.74   +1.08     0.34  agree
```

Asmongold's halo "excludes zero" with an interval 2.0 wide while the two judges are 8.0 apart in
opposite directions. That is one judge's effect, not a panel finding, and the interval says the
opposite. With two judges, a judge-level resample or a per-judge interval is the honest report.

### M4. With leakage 1.0 the halo measures an instruction change, and the page's "floor" claim is unsupported

All 100 blinded grades named the speaker correctly and confidently (checked every
`identity_guess` against the roster; Fable 50 of 50, Gemini 50 of 50, every guess the right person).
The open prompt therefore tells the judge something it already knows. What actually differs between
the two prompts (`.claude/skills/pundit-transcript-grader/PROMPT.md` lines 8-19) is the whole
condition block: blinded says "Do not try to work out who it is ... If you recognise the speaker
anyway, record that ... then set it aside"; open says "You are told who this is. Do not use
anything you know or could find about this person, their show, their audience, their past
statements or their reputation." The manipulation is a name plus a different instruction about what
to do with recognition, on a judge that has already recognised.

The halo tooltip says halo "is a floor on the true disclosure effect rather than the whole of it".
Nothing supports that. If the judge already knows, telling it adds approximately nothing, so the
measured halo can sit anywhere relative to the true effect of knowing, in either sign. The measured
values are consistent with that: 6 of 10 halos are within +/-0.5 and judges disagree on sign. The
open tooltip's "Everything else is byte-identical" is true of the transcript (100 of 100 pairs share
`identity.input_sha256`) and false of the prompt.

### M5. The plan's retry cap was not enforced, and retry-until-valid is a selection on the judge's output

Plan P8 line 421: "Retry cap per judge: 15% of that judge's nominal calls in each component.
Reaching the cap stops the run with an error taxonomy, rather than retrying further." No code
implements it: `grep -n -i "retry cap\|15 *%\|RETRY_CAP\|max_retries" scripts/grade.py` finds only
the agy empty-answer retry (2). Counted from `data-pundits/logs/p8a2/grade_errors*.jsonl` (43
lines) against the 64 nominal calls per judge in the top-up:

```
fable   25 retries: auth_or_quota 22, schema 2, json_parse 1     -> 39% of nominal
gemini  18 retries: schema 10, cli_nonzero_exit 6, json_parse 2  -> 28% of nominal
p8a (the 20 pilot recordings, 40 nominal per judge): fable 31 more, gemini 10 more
```

Fable's quota stops are exogenous and spread over 7 people. The quote-cap rejections are not
spread evenly: Gemini took 10 of 12; Gemini blinded 8 against Gemini open 2; Steven Bonnell 5 of 12.
They are not length-driven (median 9,307 words on hit recordings against 11,263 on the rest).

Whether the retries biased the scores: 24 rejected records in `_obsolete/` carry full scores.
Accepted minus rejected overall: mean +1.07, sd 3.77, se 0.77, n=24 (Fable -1.7 on 5, Gemini +1.8
on 19). Not distinguishable from zero at this n, so I do not claim a bias. Individual cells are
sensitive to it: `steven-bonnell/destiny-nmkabg` Gemini blinded was rejected twice at 45.1 and
accepted at 53.1 (+8.0); `ezra-klein/the-ezra-klein-show-cdbgiy` Gemini blinded 60.8 -> 67.2. The
halo pair for destiny-nmkabg is -2.4 with the accepted grade and would be +5.6 with either rejected
one. A judge that writes a 26-word quote is not a different judge, so the cap is a filter on
formatting that selects which of the judge's samples enters the corpus.

### M6. LATENT: run>0 repeats leak into the per-transcript consensus (reproduced)

`calibrate()` and `paired_halo()` exclude `run != 0`; the per-transcript consensus loop
(aggregate.py:882-898) does not, and neither do `drop_partial_panels` (line 138) nor
`schedule.scan_panels` (line 163). Plan P5 lines 274-275 prescribe "6 fixed transcripts re-graded in
both modes by all judges once per block group". Reproduced on a temporary checkout under `$TMPDIR`
with the real script: copied the 200 grades, added ONE run-1 Fable blinded grade for
`asmongold/asmongold-tv-vfysz-` with every dimension at 90, ran `aggregate.py --study pundits`.

```
base   | leaders identical to published: True  | asmongold 30.0 rank 10 | vfysz- n_judges 2 raw_d3 9  | grades_used 200
anchor | leaders identical to published: False | asmongold 35.3 rank 8  | vfysz- n_judges 3 raw_d3 36 | grades_used 201
       | calibration n stays 50, halo n_pairs stays 10 (those two exclude run 1 correctly)
```

Not triggered today (all 200 grades are run 0). It will trigger the first time the plan's anchors
are graded.

## MINOR

- **m1. "Four grading rounds and 43 recovered failures" understates.** The 20 p8a recordings on
  this board went through four earlier rounds (`p8a_pilot`, `p8a_repair`, `p8a_repair2`,
  `p8a_panel_fill`) with 41 more Fable/Gemini failures (28 Fable quota, 9 quote-cap, 1 CLI error
  from the p8a error files). Eight rounds and 84 recovered failures fed the 200 grades.
- **m2. Seven of 50 board recordings have zero blinding substitutions.** Counted `[SUBJECT]` and
  `[AFFILIATION]` in `transcripts_blind`: asmongold 4 of 5, hasan-piker 2, steven-bonnell 1;
  median 0.4 substitutions per 1,000 words across the board. The blinded tooltip says the name and
  show were "removed"; for those seven nothing was.
- **m3. Repairs broke the back-to-back mode control for 10 of 100 pairs.** The schedule runs both
  modes of a (transcript, judge) consecutively so drift cannot line up with mode. Repaired cells ran
  alone: 10 pairs are more than 1 h apart, 3 more than 6 h, the longest 9.3 h
  (`hasan-piker/hasanabi-esvtvd` Fable). Small next to Fable's measured day-scale drift, but the
  control the plan relies on is not intact for those pairs.
- **m4. The open score has no interval.** Plan P5 line 323: "blinded score, open score, halo,
  each with an interval". `bootstrap_ci` is called only for the blinded block (line 972-973).
- **m5. "Fable and Gemini agree at r=0.93" is mostly between-person spread.** Within-person
  (demeaned by person) r is 0.832; between the 10 person means it is 0.968. The 0.93 is correct
  as printed and says less about judge agreement on a given recording than it reads.
- **m6. The drawer's "sd" column is of unadjusted values next to adjusted means**
  (`agg()` line 957 uses `cal_<dim>`, the mean uses `cal_<dim>_venue_adj`).
- **m7. Bootstrap at n=5 has 126 distinct resamples.** 20,000 draws over 126 possible multisets
  is exact enumeration with noise; the percentile bootstrap is known to undercover at this n. The
  page's "20,000-resample" wording implies a precision the sample cannot carry. Seeding, fixed
  calibration and use of the adjusted values are all correct.
- **m8. `drop_partial_panels` derives `modes` from the whole corpus.** One stray open grade in a
  blinded-only corpus makes every recording "missing open" and drops all of them. Not triggered
  here. `filter_unscorable` skips a non-integer share silently (`isinstance(v, int)`, line 201);
  none exist today. `select_topup` takes `(repairs + fresh)[:need]`, so a person with more partial
  recordings than `need` keeps some partial for ever; not triggered (0 partial).
- **m9. The "recordings graded" fact is `people x rank_floor`**, a product, not a count of what
  was graded (page line 236). It happens to equal 50.
- **m10. `ben-shapiro/ben-shapiro-flda-n` is a venue tie** (solo vs reaction, `venue_agreed`
  false) and is shown as "solo" on the page and counted as solo in `venue_counts` without a marker.

## Checked and cleared

- **Arithmetic (task 8).** Independent recompute (`$TMPDIR/audit_recompute.py`, no import of
  aggregate.py) reproduces all 10 blinded overalls, all 30 dimension values, all 10 intervals, all 10
  open overalls, all 10 halos with intervals, and all 20 per-judge raw halos exactly. The real
  `aggregate.py` on a temporary checkout reproduces the leaders block: `identical to published:
  True`.
- **Calibration (task 2).** Six maps match `calibration_params` exactly (means, sds, n=50, all
  `rescaled`). Direction is judge-to-pooled, fitted on blinded run-0 only, applied to both modes as
  the plan says. No calibrated value hits the 1..100 clamp. The halo scaling by pooled-sd/judge-sd
  (Fable x1.12-1.17, Gemini x0.89-0.91) is as the plan and `test_paired_halo.py` describe.
- **Bootstrap (task 4).** Seeded 20260907, calibration and venue effects held fixed, reads the same
  `cal_<dim>_venue_adj` values as the point estimate, halo bootstrap keeps a transcript's pairs
  together. Reproduced to the digit.
- **Panel completeness.** 50 recordings x 4 cells, 0 partial, 0 excluded, 0 unsupported dimensions,
  0 refusals; `scan_panels` on the live tree agrees (50 complete, 0 partial). `_raw` holds only
  `.txt` in both studies (2,566 and 244 files), so `scan_panels`'s `rglob("*.json")` cannot read it.
- **Share filter.** No recording below 10 (minimum pooled mean 13), no zero from any judge, no
  non-integer share.
- **Identity and inputs.** 100 of 100 blinded guesses correct and confident. Blinded and open share
  `input_sha256` on 100 of 100 pairs. One contract (`3844dd2693acd471`) on all 200 grades;
  `served_model_verified` true on the record read in full.
- **Failure correlations (task 5).** Not length-driven: quote-cap hit median 9,307 words vs 11,263;
  Gemini empty/ERROR 11,293 vs 10,889; Fable quota 11,667 vs 10,747. Fable quota stops are
  exogenous session limits.
- **schedule.py (task 7).** `verified_keys` reads 89 keys from `logs/pilot/report.json` (114 on
  disk); `select_topup` and `scan_panels` behave as documented on this corpus; `queue_summary`
  prints the product only when it is a product (the old `114 x 2 x 2 x 1` line is in `run.log`
  from before the fix).
- **Venue fit numerics (task 3).** Alternating means equals the exact least-squares contrast
  (-9.644 vs -9.643). The exact-negative pairs are a centring artifact, not an error.
- **Page numbers that check out.** r=0.93, gap 5.8, n=50; leakage 1.0 and 50 of 50; Astra 42 of 44;
  Ben Shapiro span 19.5 (33.7 to 53.2); 6 of 6 calibration pairs; 200 of 200 grades, 0 dropped;
  roster 39; rank floor 5; venue counts 7/13/26/4 and effects match `results.json`.
- **Tests.** `bash scripts/run_tests.sh` printed `failed: 0`, exit 0 (one SyntaxWarning in
  `test_predictions_site.py:302`, unrelated).
- **Not verifiable here.** The page's "in the 20-recording pilot it was 0 of 6" (no earlier
  results.json retained) and the lean-stratified G-refusal condition (lean labels are private).

## Summary

- CRITICAL 1: page drawer deltas and the Open column mix adjusted blinded with unadjusted open;
  two sign flips, one +4.8 that is really 0.0.
- MAJOR 6: venue adjustment applied against the plan's support rule (M1) on a four-person contrast
  with arbitrary pinning worth up to 2.6 points (M2); halo interval blind to judge disagreement
  that is opposite-signed for 8 of 10 (M3); halo "floor" claim unsupported under total leakage
  (M4); retry cap not enforced, cap-filter uneven by judge and mode (M5); latent run>0 leak
  reproduced, +5.3 points and two ranks from one anchor grade (M6).
- MINOR 10, listed above.
- Cleared: every published number reproduces from raw grades; calibration, bootstrap, panel,
  share filter, identity, inputs, contract, tests.
