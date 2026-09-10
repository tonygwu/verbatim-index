# Verbatim Index — session handoff, 2026-09-10 08:25Z

Written before a context compaction. Every line here has a check command; do
not trust one without running it.

## Pinned revision

| Repo | Commit | Pushed |
|---|---|---|
| code (`repo-0`, public) | `329fb87` on `main` | yes |
| data (`data/`, private) | `91356d5` (moves every cycle; re-check) | check |

Verify: `git -C /Users/tonygwu/Code/misc/verbatim-index/repo-0 status --short --branch`

## What this session did

Added a THIRD judge — Gemini 3.8 Flash via the Antigravity CLI (`agy`) — and
promoted it to published. It joins Fable 5.1 (`claude -p`) and GPT-6 Astra
(`codex exec`). Everything below is recorded in AGENTS.md; this file is only
the live state.

- Two Antigravity accounts, selected by `$HOME` (there is no AGY_CONFIG_DIR).
  `agy` = tonygwu@gmail.com, `agy-b` = gptwufamily@gmail.com. Run
  `agy-profiles` to derive the mapping; never infer it from the alias.
- Gemini is in `BLIND_JUDGES` in `grade_loop.sh`, so new transcripts get all
  three judges. It was NOT, earlier, and coverage silently drifted to 87%.
- A fork fixed the fetch target to count GRADEABLE transcripts rather than raw
  downloads (`329fb87`). The loop had declared 40/40 at target when the truth
  was 26/40.

## Background processes STILL RUNNING

| Process | Check |
|---|---|
| `fetch_loop.sh` (TARGET=14) | `pgrep -f fetch_loop.sh` |
| `grade_loop.sh` (OPEN_PER_LEADER=0) | `pgrep -f grade_loop.sh` |

Both exit on their own when work runs out. `happyscribe_loop` is stopped.

**The fetch loop needs a human when YouTube blocks the exit IP.** It prints
`BLOCKED on IP <addr>`, re-probes every 60s, and resumes by itself once the VPN
is rotated. Two exits were burned today, each lasting under an hour at the
current 2s pace / 6 workers.

## Live numbers at handoff time

```
corpus     574 gradeable
at target  36/40  short: michael-dell 11/14, cc-wei 12/14, larry-ellison 12/14, sergey-brin 12/14
fable      570/574 (99.3%)
astra      567/574 (98.8%)
gemini     552/574 (96.2%)
```

Verify: `bash scripts/status.sh`

## Open decisions, with costs

1. **Slow the fetch pace?** Exits are lasting <1h at 2s/6 workers with ~9
   transcripts left to fetch. Slower may finish with fewer VPN rotations.
   Cost of doing nothing: more manual rotations.
2. **Add rank agreement to `aggregate.py` diagnostics?** It is computed ad hoc
   today (see AGENTS.md). Recomputing per run would make judge drift visible
   early. Cost: more diagnostics surface to maintain.
3. **Upgrade `calibrate()` to a two-way `score ~ transcript + judge` fit?**
   AGENTS.md records why it is defensible not to. Cost of doing it: re-deriving
   ~2,000 grades for a measured effect of at most 0.18 points.

## Known open issue, upstream

The 20-odd transcripts Gemini cannot grade are all >32k words and hit an
Antigravity CLI bug: an auto-denied tool ends the run with exit 0 and
`status: SUCCESS` and an empty response. Filed and confirmed on macOS 1.1.28 at
https://github.com/google-antigravity/antigravity-cli/issues/794 — it is NOT
deterministic, so re-running recovers some each pass.

## Single next action

Watch for `BLOCKED on IP` in `data/logs/fetch_loop.log` and rotate the VPN when
it appears; otherwise let both loops run to their own completion.

## Verification command

```
\
  git status --short --branch && \
  pgrep -fl 'fetch_loop.sh|grade_loop.sh' && \
  bash scripts/status.sh --brief
```
