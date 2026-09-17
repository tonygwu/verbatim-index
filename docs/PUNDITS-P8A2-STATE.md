# Pundits: the current position, and the next step

Written 2026-09-16 as a compaction handoff, and rewritten the same day after the
P9 top-up. Read this first if you are picking the pundits study up cold. The plan
is `docs/PUNDITS-PLAN.md`; this file is the current position within it.

The filename still says P8A2 because commits and other clones reference it. It
now covers the position through the **P9 top-up**.

## Position

**Every pilot person is graded to the P5 target of 12 recordings, or to the limit
of their verified material.** 10 people, 77 recordings, 308 grades used.

```
 rk person            blinded    95% interval   open    halo      n
  1 Ezra Klein           73.5    [67.1,79.1]    71.8   -1.72 *    7
  2 Coleman Hughes       65.0    [62.4,67.8]    64.9   -0.09      7
  3 Steven Bonnell       57.8    [50.8,65.0]    58.1   +0.38      6
  4 Sam Seder            51.6    [48.3,55.5]    53.3   +1.40      7
  5 Ana Kasparian        48.0    [41.8,53.6]    48.5   +0.34      6
  6 Ben Shapiro          42.4    [36.6,48.8]    41.6   -0.94     12
  7 Hasan Piker          34.6    [27.6,42.1]    34.6   -0.13      8
  8 Zack Hoyt            34.2    [26.6,43.2]    35.7   +1.41 *   11
  9 Charlie Kirk         32.5    [29.8,35.1]    32.3   -0.28      5
 10 Matt Walsh           31.3    [26.8,35.3]    32.0   +0.84      8
 (* the only two halos that are panel findings; see halo_judge_agreement)
```

The top seven hold their order against the 5-recording board. Zack Hoyt moved
10th to 8th and Matt Walsh 8th to 10th; nobody else changed rank.

Scores carry NO format adjustment. The support rule still fails, but for ONE
reason now rather than three: `venue 'debate' seen 4 times, under the minimum of
8`. Solo now clears the floor and the 80% mixed-format rule now passes. **Eight
more debate recordings would turn the adjustment on**, and `venue_withheld_effects`
shows what it would do (conversation +6.8 and reaction -5.9 on d3_good_faith, so
it would not be cosmetic).

An adversarial Fable audit of the earlier 5-recording board is
`docs/PUNDITS-P8A2-AUDIT.md`. Six of its findings are fixed (`203d63b`,
`fb97bbb`); the rest are under "Open" below.

## Rebuilding the review page

The page is DERIVED from `data-pundits/results.json` by two session-scratch
scripts. They do not survive a new session, so regenerate them rather than hunt
for them. Both are small and their shapes are recorded here:

```
scratchpad/payload.py <repo> <scratchpad>   # results.json -> board_payload.json
scratchpad/page2.py <scratchpad>            # board_payload.json -> the HTML
```

Local copy `/Users/tonygwu/pundits-pilot-board.html`; artifact
`https://claude.ai/artifact/QRG3zDv64jmnz8ckNKN7XN` (Version 6).

**The page copy goes stale silently.** Nine sentences in `page2.py` asserted the
5-recording board, an audit path that had moved, a halo result that had changed
and a format adjustment that was applied. Every claim that can change with the
data belongs in a `${D.…}` expression or behind `D.venue_applied`, never typed.

## The next step

The pilot pool is exhausted at this target. The options, in the plan's order:

1. **Discovery for the remaining 29 roster people** (P6 for the rest of the
   roster). The roster holds 39; these 10 are the pilot group.
2. **More debate recordings**, which is the one thing standing between this board
   and a format-adjusted one. It needs 4 more to reach `MIN_VENUE_N`.
3. **The P7 human-label work**, which no amount of grading unblocks.

## Quota, and the lesson that keeps costing calls

**Read BOTH windows, not just the `fable` column.**

```
quotapick status
```

P8a2 launched into a 5-hour window at 8% and lost 22 of 64 Fable calls. The P9
top-up then lost 5 more to a subtler version of the same thing: `claude_b`'s
weekly Fable pool read a healthy 67% while its **5-hour** window had gone to 0,
and an account in that state refuses every call. Pin with `--fable-accounts` to
accounts healthy on both windows. A repair run on one good account cleared all
five.

The retry cap is live: a judge stops once its failures pass 15% of its own
scheduled calls, and the summary reports `skipped_over_retry_cap` and
`retry_cap_stopped_judges`. It did not trip on either run.

## Open decisions

1. **The 25-word quote cap: RESOLVED for the penalty, still open for the number.**
   An over-long quote is now recorded rather than rejecting the grade
   (`quote_overruns`, commit `2c5e617`), and `contract_id` is unchanged at
   `3844dd2693acd471`. **The corpus now mixes two regimes**, and
   `diagnostics.quote_cap` is how a later reader tells them apart. Raising the
   number itself to 40 would move the contract to `7aa8f163de1f0b2e` and re-grade
   everything.
2. **What halo measures.** All blinded grades named the speaker correctly, and
   the blinded and open prompts differ by a whole instruction block, not just a
   name. Fixing that means re-grading every open cell.
3. **Seven recordings have zero blinding substitutions**, four of them Zack
   Hoyt's. Fixing means re-blinding and re-grading those.
4. **The open score has no bootstrap interval**, which plan P5 requires.
5. **The bootstrap at small n.** Charlie Kirk sits at 5, where there are only 126
   distinct resamples, so "20,000 resamples" overstates the precision.
6. **Whether a gameplay stream belongs in the corpus.** Three cells are excluded
   as `unsupported_dimension`, all from one Zack Hoyt recording where both judges
   independently found no opposing argument to score under D1. That is the rubric
   working. It was deliberately NOT re-graded: re-running a judgement until it
   changes is the same selection effect the quote cap had. The lever, if any, is
   the discovery rules, applied to everyone.

## Standing constraints

- Never call a judge through `cl`: it injects `--dangerously-skip-permissions`.
  Raw `claude` only.
- Private lean labels never enter a public commit, a prompt, or the page. Stage
  files by name; never `git add -A`. The page build is checked for leakage.
- No deploy. P11 publication needs explicit approval at the time it happens. The
  domain is still unconfirmed: wrangler and the plan say
  `verbatim-pundits.tonygwu.com`, the operator once wrote
  `verbatim.pundits.tonygwu.com`. Ask before deploying.
- Subscription quota (claude, codex) needs no approval. Metered APIs do.
- Do not touch other clones' running jobs.
