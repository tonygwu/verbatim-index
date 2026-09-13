# Verbatim Index — session handoff, 2026-09-13 01:50Z

Written from `repo-2` while the Verbatim Predictions corpus extraction is
running. Every line here has a check command; do not trust one without
running it.

## Pinned revision

| Repo | Commit | Pushed |
|---|---|---|
| code (`repo-2`, public) | `git log --oneline -1` after this file's commit | see `git status --short --branch` |
| data (`data/`, private) | moves every grade cycle; `git -C data log --oneline -1` | repo-0 commits it; `data/predictions/` is uncommitted until repo-0 adds it |

Verify: `git status --short --branch` in repo-2; `git -C data status --short | head`.

## What this session did

Built Verbatim Predictions V0, documented in `docs/PREDICTIONS.md`:
extraction, verification by a second model family, a market-consensus stage,
validator, golden eval, descriptive aggregate, and the page at
`verbatim-predictions.tonygwu.com`. Eight `scripts/test_predictions_*.py`
suites guard it. The existing leaderboard is unchanged except for a link in
its eyebrow and the design tokens moving byte for byte into
`scripts/site_theme.py` (render diff: one line).

## Background process STILL RUNNING (from repo-2)

| Process | Started | Check |
|---|---|---|
| `extract_predictions.py --stage verify --workers 4` over the whole corpus | 2026-09-13 01:32Z | `pgrep -f "stage verify --workers 4"`; log `data/predictions/_runs/verify-20260913T013224Z.log` |

Extraction is DONE. Two passes: the 02:56Z corpus pass and a fill pass that
retried its failures. Combined result, 664 transcripts, 0 outstanding failures,
1470 candidates, 0 ungrounded. The 46 failures of the first pass were 36
transcripts repo-0 withdrew under the running pass and 10 transient Astra
websocket disconnects; all 10 succeeded on the retry.

Verification runs on Fable, because every extraction ran on Astra and the
verifier must be another model family. Only `claude_c` has Fable headroom, and
its FIVE-HOUR window is the binding constraint, not its Fable weekly window:
27% left at 01:48Z, 63% over pace. Expect `auth_or_quota` or a Gemini fallback
later in the pass. Re-running the same command fills whatever failed.

Watch for `model_identity_mismatch` in the taxonomy. One call has already
failed that way, with telemetry naming `claude-haiku-4-5` and `claude-opus-5`
and no Fable model. That is the identity assertion working: a call served by
another model is refused rather than recorded as a Fable verification.

## The single next action

When extraction exits:

```
.venv/bin/python scripts/extract_predictions.py --stage extract --workers 4   # fills any failures
nohup .venv/bin/python scripts/extract_predictions.py --stage verify --workers 4 > data/predictions/_runs/verify-corpus.log 2>&1 &
.venv/bin/python scripts/market_consensus.py --workers 2
.venv/bin/python scripts/validate_predictions.py
.venv/bin/python scripts/aggregate_predictions.py
bash scripts/deploy_predictions.sh --dry-run && bash scripts/deploy_predictions.sh
```

Verification needs a model family other than the extractor's per transcript;
with extraction on Astra that means Fable or Gemini. If Fable is spent, the
pass will fail into `auth_or_quota` and can be re-run when a window resets
(`quotapick status`). Then ask the operator to commit `data/predictions/`
from repo-0: `git -C data add predictions && git -C data commit`.

## Live numbers at handoff time

```
verification: 29/449 transcripts at 01:48Z, 28 ok, 1 failed, all fable;
              59 candidates verified, 31 accepted, 53% acceptance; ETA about 04:46Z
extraction: DONE, 664 transcripts, 0 failures, 1470 candidates, 0 ungrounded
old extraction line: 183/682 transcripts, 174 ok, all astra, ~459 left, ETA about 16:52Z today
            336 candidates written, 0 ungrounded
pilot: 13 files, 26 candidates from 407 weighed, 11 accepted, 13 rejected, 2 pending
golden eval (live): precision 1.000, recall 0.929, 0 false positives on 24 negatives
page: deployed with the pilot's 11 predictions; index page redeployed with the cross-link
```

Two facts the running pass cannot see. repo-0 began applying the withdrawal
manifest at about 06:00Z, so transcripts keep disappearing under the pass; the
corpus on disk fell from 702 to 670 within the hour. And the pass enumerated
its file list at 02:56Z, so the newer transcripts repo-0 has fetched since are
not in it. The follow-up extract run re-lists the corpus and picks them up.

Verify: `.venv/bin/python scripts/validate_predictions.py` and
`.venv/bin/python scripts/aggregate_predictions.py`.

## Open decisions, with costs

1. **Verifier strictness.** It rejects undated visions ("computers will write
   the programs") on the falsifiability gate. Loosening the undated rule raises
   recall and admits vaguer claims; the pilot audit in `docs/PREDICTIONS.md`
   section 9 has the examples either way. Recommendation: keep it for V0.
2. **Wrong-person transcripts.** 35 excluded recordings are still on disk in
   `data/transcripts_open`; the extractor skips them by list. They leave when
   repo-0's loop applies the withdrawal manifest.

---

# Leaderboard workstream (repo-0), updated 2026-09-13 01:29Z

Separate from the predictions handoff above, which is repo-2's. This covers
the judge panel, the two fetch sources and the grading loops. Every line has
a check command; do not trust one without running it.

## Pinned revision

| Repo | Commit at handoff | Pushed |
|---|---|---|
| code (public) | `git log --oneline -1` | yes, `git status --short --branch` shows no divergence |
| data (private) | `git -C data log --oneline -1` | yes; `data/predictions/` stays uncommitted for repo-2 |

Commits from this workstream, oldest first:

```
f5971da  Derive every judge diagnostic from the grades, not a typed pair
88cfd25  Let the loop set the fetch pace ceiling, and lower it to 15s
50eb15c  Re-discover HappyScribe candidates when the roster gains a leader
14cb5d0  Guard the stderr-log ignore, including the half that is easy to miss
7f957b7  Split refusals out before the scorable filter, not after
fef03ca  Default the fetch target to 12, the number the sources actually hold
60bb15b  Record what the HappyScribe re-search cost, not only what it gained
e91e33f  Wait for every transcript source before declaring grading complete
af6624a  Give happyscribe_loop the barren-pass guard its sibling already had
0a3b32c  Count a running source, not a mention of its name
```

Plus `7c0f38b` in `data/`, which untracked the 50 MB stderr log.

## What this session fixed, and why each mattered

1. **Judge diagnostics counted two judges, not three.** `judge_call_counts`,
   `judge_raw_means_blinded` and the inter-judge agreement were hand-typed as
   fable-plus-astra. Gemini left `SHADOW_JUDGES` on 2026-09-08 and contributed
   over 500 blinded grades to published scores while all three diagnostics kept
   reporting two judges. The leaderboard was right and its evidence was not.
   All three now derive from the judges present. There is no longer a key
   naming one pair `_overall`; `judge_pair_agreement` reports every pair with
   its own `n`, and `mean_pairwise_correlation` is the one panel-level figure.
   Guarded by `scripts/test_judge_enumeration.py`, which runs a FOUR-judge
   fixture as well as a three-judge one.

2. **The fetch pace ratchet could not be reached from the loop.**
   `Pacer.max_interval` was hardcoded at 90s. Cycle 43 took five throttles in
   its first minutes, pinned the shared gap at 90s, then ground for six hours
   over 6 of 14 leaders while throttling 158 more times. `Breaker` never fired,
   because `record_ok()` clears its consecutive counter on every success and at
   90s most requests do succeed, so a refusing endpoint read as slow rather
   than stopping and nothing raised `NEEDS_IP_ROTATION`. `--max-interval` now
   exposes it and `PACE_CEILING` defaults to 15s. After a restart the same work
   took 8 minutes for 13 leaders with ZERO throttles, which showed the endpoint
   was never the constraint. The ceiling is untested insurance; it has not yet
   been hit.

3. **HappyScribe discovery never followed the roster.** The loop ran discovery
   only when the pool file was missing, so the pool was built once against the
   40-name roster and never revisited. The roster grew to 50 and eleven leaders
   were never searched, while C.C. Wei stayed in the pool after leaving the
   study. The loop reported COMPLETE throughout, truthfully, because every
   candidate it knew of had been fetched. `unsearched_leaders()` and
   `--report-unsearched` now drive it and the loop names who it re-searches. A
   leader present with an EMPTY list counts as searched, so the confirmed-absent
   keynote speakers do not trigger a 38-sitemap walk every cycle.

4. **`data/logs/grade_loop.err` was tracked at 50.1 MB**, 95% of all tracked
   bytes under `logs/`, committed four times and growing every cycle. 616,169
   of about 673,000 lines were `CACHED` notices. Now ignored and untracked;
   still written to disk. Tracked log bytes went 53.0 MB to 3.0 MB. This does
   NOT shrink existing history.

## Background processes

NONE are running as of 2026-09-13 01:29Z. Both loops exited on their own on 2026-09-11:

```
[2026-09-11T07:49:51Z] grade_loop   COMPLETE: nothing left to grade
[2026-09-11T08:24:33Z] happyscribe  EXHAUSTED: 3 cycles with no new transcripts.
                         33 of 92 candidate(s) never fetched (59 fetched).
```

`fetch_loop.sh` exited `EXHAUSTED` at 03:44Z. Do NOT restart any of the three
without a reason: both sources are exhausted, and every gradeable transcript
has at least one grade.

If a restart is needed, pass the environment the script defaults do not supply
for this run's settings:

```
OPEN_PER_LEADER=0 nohup bash scripts/grade_loop.sh      >> data/logs/grade_loop.log 2>&1 &
TARGET=12         nohup bash scripts/happyscribe_loop.sh >> data/logs/happyscribe_loop.log 2>&1 &
```

`OPEN_PER_LEADER` defaults to 2 and this run used 0. `TARGET` now defaults to
12 in both fetch loops, so that part is belt and braces.

## Live numbers at handoff time (2026-09-13 01:29Z)

```
board        50 ranked, 0 unranked, 0 unscored
grades       2260 read by results.json
transcripts  653 blinded    refusals 4
at target    42/50 at TARGET=12
short        ilya-sutskever 7, michael-dell 9, tim-cook 9, andy-jassy 10, lip-bu-tan 10, tim-sweeney 10, alexandr-wang 11, jeff-bezos 11
judge calls  astra 643, fable 652, gemini 619
pair r       astra|fable 0.875 (n=642), astra|gemini 0.846 (n=609), fable|gemini 0.841 (n=618)
```

The drop from 41/50 at the previous handoff is not a regression. Another agent
applied a wrong-person withdrawal manifest (36 transcripts), and QA withdrew
four HappyScribe recordings that were commentary ABOUT the subject.

## Decided since the previous handoff

- **`TARGET` is 12** (operator, 2026-09-11). It is a fetching goal only. It
  appears zero times in `aggregate.py` and `build_site.py`, so it changes no
  score, rank, or board membership.

- **Run markers replace the process-list check** (operator chose option (a),
  2026-09-13 01:59Z; `b6cbb8d`). The grader early exit at 07:49:51Z on 2026-09-11 came
  from `fetcher_running()` reading the process list. That code is gone. Each
  fetch loop now claims `data/logs/running/<script>.marker` at start and
  removes it on exit; `grade_loop.sh` counts a marker only while its pid is
  alive with the recorded UTC start time, and stops loudly on an unreadable
  one. The root cause of the old miss is still unknown, and no longer matters
  to the grader. Two behaviour changes to know: a second copy of a fetch loop
  now refuses to start, and a marker left by `kill -9` is replaced loudly on
  the next start.

## Open decisions, with costs

1. **Existing history still holds about 200 MB of the old stderr log.**
   Shrinking it needs a history rewrite, which is disruptive across clones.
   RECOMMENDATION: leave it; the growth is stopped.
2. **Eight leaders are below 12**, and no fetch run can move them because both
   sources are exhausted. Reaching 12 needs new manifest candidates. Before the
   next discovery run, tighten the HappyScribe third-person filter; see
   `AGENTS.md`, Known limits.

## The single next action

None required. Nothing is running and nothing is blocked.

## Verification command

```
git status --short --branch && git -C data status --short --branch | head -1
ps -Ao comm=,args= | awk '$1 ~ /bash$/ && $3 != "-c" && /(grade|fetch|happyscribe)_loop\.sh/' | wc -l   # expect 0
tail -1 data/logs/grade_loop.log data/logs/happyscribe_loop.log
ls data/logs/running/ 2>/dev/null | wc -l    # expect 0 while no fetch loop runs
for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || echo "FAIL $t"; done
.venv/bin/python -c "import json;d=json.load(open('data/results.json'));print(d['diagnostics']['judge_call_counts'])"
```

The process count uses `ps` with `-c` excluded rather than `pgrep -f`, because
`pgrep -f` also matches any command line that merely names the script,
including the shell running this check. The last line must name THREE judges.
If it names two, the fix in `f5971da` has been reverted or overwritten.
