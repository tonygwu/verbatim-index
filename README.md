# Verbatim Index

Ranks 40 well-known technology leaders on the thinking their public speech
demonstrates, scored **only** from transcripts of interviews, podcasts and
keynotes. Nothing about company performance, market value or reputation enters
a score.

## Status

Everything is built and verified except the transcripts themselves. YouTube's
caption endpoint is IP-blocked (see `data/logs/BLOCK_STATE.md`). A watcher is
probing every 30 minutes and will run the rest of the pipeline automatically
when it clears:

```bash
tail -f data/logs/watch.log          # what the watcher is doing
cat data/logs/watch_state.jsonl      # one line per probe
pgrep -fl watch_and_run              # is it still alive
```

Kill and restart it freely. Every stage skips work already on disk.

## What is scored

Three dimensions, each 1-100, supported by 15 sub-criteria that a judge may
mark *not observed* when the format gave no chance to demonstrate them.

| Dimension | Weight | Question |
| --- | --- | --- |
| Insight | 45% | Are the points non-obvious, load-bearing, honestly held? |
| Technical depth | 35% | Do they understand mechanism, magnitudes, terrain? |
| Clarity | 20% | Can a listener reconstruct their model? |

Clarity is deliberately the smallest weight. The rubric explicitly refuses to
reward fluency or confident delivery, because a polished non-answer is the
failure mode it exists to catch. Full definitions and anchors are in
`.claude/skills/leader-transcript-grader/RUBRIC.md`.

## How it runs

```bash
scripts/run_pipeline.sh                    # all eight stages
STAGES="7 8" scripts/run_pipeline.sh       # just re-aggregate and re-render
```

| Stage | Does |
| --- | --- |
| 1 | ranked candidates to fetch manifest, aliases, repairs |
| 2 | fetch verbatim captions, paced and circuit-broken |
| 3 | quality gates: garble, ASR loops, speech rate, name density |
| 4 | repair ASR errors, then blind and un-blind identity |
| 5 | **blinded** grading, both judges, every transcript (published score) |
| 6 | **unblinded** grading, 2 per leader (halo measurement only) |
| 7 | aggregate with per-judge normalisation |
| 8 | render `site/index.html` |

Two judges grade independently: **Claude Fable 5.1** and **OpenAI GPT-6 Astra**,
both at maximum reasoning effort. Model identity is asserted from each call's
telemetry, never assumed.

## What the calibration says

Five repeat gradings of one unchanged transcript per judge, `data/logs/calibration.json`:

- Within-judge standard deviation of the composite: **1.29** (Fable), **1.78** (Astra).
- So differences under about **4 points are ties**. The leaderboard brackets them.
- Coverage and venue-difficulty judgements were identical across all repeats.
- Astra runs **7.5 points more generous** than Fable, which is 4.9x the noise.
  That is an offset, not disagreement, so each judge's distribution is recentred
  on the pooled one before averaging.

## Known limits

- **Blinding removes the name, not the identity.** Both judges named the speaker
  from products and context in 100% of the fixture's blinded runs. Stripping
  product names would gut the dimension being measured. The leakage rate is
  measured and published rather than hidden, and the *Halo* column reports what
  changes when the judges are told who they are.
- **Captions carry no speaker labels.** Judges separate subject from interviewer
  by context and report their confidence and the subject's share of the talking.
- **Venue difficulty is reported, never corrected for.** A leader who only does
  friendly interviews scores lower on insight. Adjusting would mean inventing a
  score for a conversation that never happened.
- **Judges are language models.** Two frontier models agreeing is evidence. It
  is not the same as being right.

## Layout

```
.claude/skills/leader-transcript-grader/   rubric, skill, output schema
.claude/skills/polite-bulk-fetching/       rate-limit discipline, researched
scripts/                                   pipeline, one stage per file
data/roster/final.json                     the 40, with exclusions recorded
data/sources/discovered.json               559 ranked candidates
data/logs/                                 QA, calibration, errors, block state
site/index.html                            the leaderboard
```

Transcripts under `data/` are working data for the analysis. The published page
carries only short attributed evidence quotes, capped at 25 words each and
enforced by the grader's validator, with a link back to each source.
