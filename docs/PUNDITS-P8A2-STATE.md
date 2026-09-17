# Pundits: where P8a2 ended, and the exact next step

Written 2026-09-16 as a compaction handoff. Read this first if you are picking
the pundits study up cold. The plan is `docs/PUNDITS-PLAN.md`; this file is the
current position within it and the command that moves it forward.

## Position

**P8a2 is complete and the board ranks for the first time.** 10 pilot people,
5 complete recordings each, 200 of 200 panel cells filled, 0 dropped.

```
 rk person            blinded    95% interval   open    halo     n
  1 Ezra Klein           72.5     [63.4,78.4]   72.1   -0.46     5
  2 Coleman Hughes       63.9     [59.8,65.8]   64.1   +0.13     5
  3 Steven Bonnell       59.7     [50.7,66.8]   60.7   +0.91     5
  4 Sam Seder            51.6     [46.1,54.6]   51.7   -0.19     5
  5 Ana Kasparian        47.2     [39.7,52.7]   47.5   +0.25     5
  6 Ben Shapiro          42.8     [33.8,53.3]   41.1   -1.94 *   5
  7 Hasan Piker          36.2     [27.4,45.9]   35.2   -1.09     5
  8 Matt Walsh           33.5     [30.3,37.4]   34.7   +1.42     5
  9 Charlie Kirk         32.6     [28.7,34.3]   32.4   -0.27     5
 10 Zack Hoyt            28.7     [21.2,37.8]   31.2   +2.56     5
 (* the only halo that is a panel finding; see halo_judge_agreement)
```

Scores carry NO format adjustment: the support rule fails on this corpus and the
gate now withholds it. Review page source is rebuilt by
`scratchpad/page2.py` (session scratch, regenerate rather than hunt for it);
the published copy is an Artifact, and a standalone local copy sits at
`/Users/tonygwu/pundits-pilot-board.html`.

An adversarial Fable audit of this board is `docs/PUNDITS-P8A2-AUDIT.md`. It
reproduced every published number exactly and found 1 CRITICAL, 6 MAJOR and 10
MINOR defects. Six are fixed (commits `203d63b`, `fb97bbb`); the rest are listed
under "Open" below.

## The next step: grade the remaining 39 verified recordings

The P6 pilot verified **89** recordings; 50 are graded. The remaining 39 cost
about **156 calls** (39 x 2 judges x 2 modes).

**Check quota BEFORE launching. This is the lesson of P8a2**, where a run was
started into a 5-hour window at 8% and lost 22 of 64 Fable calls to
`auth_or_quota`:

```
quotapick status          # read the `fable` column, not the 5h or 7d column
```

Pin the rotation to accounts that actually have Fable headroom, then:

```
.venv/bin/python scripts/schedule.py build --study pundits \
  --transcripts data-pundits/transcripts_blind \
  --lean-labels data-pundits/private/lean_labels.json \
  --judges fable,gemini --seed 20260916 \
  --graded data-pundits/grades --target-per-person 12 \
  --verified data-pundits/logs/pilot/report.json \
  --out data-pundits/logs/schedule/p9_topup.jsonl

nohup .venv/bin/python scripts/grade.py --study pundits \
  --transcripts data-pundits/transcripts_blind \
  --roster data-pundits/roster/final.json \
  --out data-pundits/grades \
  --schedule data-pundits/logs/schedule/p9_topup.jsonl \
  --judges fable,gemini --workers 6 --timeout 2400 \
  --fable-accounts <accounts with headroom> \
  --errors data-pundits/logs/p9/grade_errors.jsonl \
  >> data-pundits/logs/p9/run.log 2>&1 &
```

`--target-per-person 12` is the P5 target and counts what is already complete
rather than adding a fixed number. The pool is very uneven (Ben Shapiro 22
verified, Charlie Kirk 5), so the scheduler will report a shortfall for most
people. That is expected and is printed, not silent.

The retry cap is now live: a judge stops once its failures pass 15% of its own
scheduled calls, and the run summary reports `skipped_over_retry_cap` and
`retry_cap_stopped_judges`. If a judge stops, read the taxonomy before relaunching.

Then: `aggregate.py`, `build_site.py`, and rebuild the review page.

## Open decisions, none of which block the run

1. **The 25-word quote cap.** Measured skew: gemini 19 of 24 rejections, 19.0%
   against fable's 5.0%, a ratio of 3.8x. Changing the cap re-grades the whole
   corpus because it is hashed into `contract_id`. Three options and their costs
   are in `BACKLOG.md`. Decide before P9 proper, while the cost is 200 cells.
2. **What halo measures.** All 100 blinded grades named the speaker correctly,
   and the blinded and open prompts differ by a whole instruction block, not
   just a name. Fixing that means re-grading every open cell.
3. **Seven recordings have zero blinding substitutions**, four of them
   Asmongold's. Fixing means re-blinding and re-grading those.
4. **The open score has no bootstrap interval**, which plan P5 requires.
5. **The bootstrap at n=5** has only 126 distinct resamples; "20,000 resamples"
   overstates the precision five recordings can carry.

## Standing constraints

- Never call a judge through `cl`: it injects `--dangerously-skip-permissions`.
  Raw `claude` only.
- Private lean labels never enter a public commit, a prompt, or the page. Stage
  files by name; never `git add -A`.
- No deploy. P11 publication to the pundits domain needs explicit approval at
  the time it happens. The domain itself is still unconfirmed:
  wrangler and the plan say `verbatim-pundits.tonygwu.com`, the operator once
  wrote `verbatim.pundits.tonygwu.com`. Ask before deploying.
- Subscription quota (claude, codex) needs no approval. Metered APIs do.
- Do not touch other clones' running jobs.
