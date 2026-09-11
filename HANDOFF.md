# Verbatim Index — session handoff, 2026-09-11 03:10Z

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
| `extract_predictions.py --stage extract --workers 4` over all 682 transcripts | 2026-09-11 02:56Z | `pgrep -f "stage extract --workers 4"`; log `ls -t data/predictions/_runs/extract-corpus-*.log \| head -1` |

It skips transcripts whose meta says extraction succeeded, so re-running the
same command after a stop resumes. Watch `error_taxonomy` in the log's last
line for `auth_or_quota` and `router_no_account` before calling a slow pass
healthy. It competes with `grade_loop` (repo-0) for the same Codex and Fable
quota; Fable was near 0% on most accounts when it started, so it will run
mostly on Astra.

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
pilot: 13 files, 26 candidates from 407 weighed, 11 accepted, 13 rejected, 2 pending
golden eval (live): precision 1.000, recall 0.929, 0 false positives on 24 negatives
page: deployed with the pilot's 11 predictions; index page redeployed with the cross-link
```

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

# Leaderboard workstream (repo-0), 2026-09-11 05:30Z

Separate from the predictions handoff above, which is repo-2's. This covers
the judge panel, the two fetch sources and the grading loops. Every line has
a check command; do not trust one without running it.

## Pinned revision

| Repo | Commit at handoff | Pushed |
|---|---|---|
| code (public) | `git log --oneline -1` | yes, `git status --short --branch` shows no divergence |
| data (private) | `git -C data log --oneline -1` | yes; `data/predictions/` stays uncommitted for repo-2 |

Four commits from this session, newest last:

```
f5971da  Derive every judge diagnostic from the grades, not a typed pair
88cfd25  Let the loop set the fetch pace ceiling, and lower it to 15s
50eb15c  Re-discover HappyScribe candidates when the roster gains a leader
14cb5d0  Guard the stderr-log ignore, including the half that is easy to miss
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

## Background processes STILL RUNNING

Both are detached (`ppid 1`), so they survive `/clear`, this session ending,
and the terminal closing. They were started from repo-0, the daemon clone.

| Process | Started | Check | Restart |
|---|---|---|---|
| `grade_loop.sh` | 2026-09-11 04:49Z | `pgrep -f grade_loop.sh`; `tail -5 data/logs/grade_loop.log` | `OPEN_PER_LEADER=0 nohup bash scripts/grade_loop.sh >> data/logs/grade_loop.log 2>&1 &` |
| `happyscribe_loop.sh` | 2026-09-11 04:49Z | `pgrep -f happyscribe_loop.sh`; `tail -3 data/logs/happyscribe_loop.log` | `TARGET=8 nohup bash scripts/happyscribe_loop.sh >> data/logs/happyscribe_loop.log 2>&1 &` |

`fetch_loop.sh` exited `EXHAUSTED` at 03:44Z and should NOT be restarted: every
YouTube manifest candidate for the short leaders has already been tried.

The restart commands carry environment that the script defaults do NOT supply.
`OPEN_PER_LEADER` defaults to 2 and the running loop uses 0. `TARGET` defaults
to 5 for HappyScribe and the running loop uses 8, inferred from disk because
`ps eww` returns no environment for another process on macOS: Elon Musk stopped
at 8 of 43 candidates and Bill Gates took all 8 of 8. Restarting `fetch_loop`
without `TARGET=14` makes it exit COMPLETE in under a second, which happened
once in this session.

## Live numbers at handoff time

```
board        50 leaders ranked, 0 unranked, 0 unscored
at target    41/50 at TARGET=14       (48/50 would be at target if TARGET were 12)
short        ilya-sutskever 7, michael-dell 11, aaron-levie 12, alexandr-wang 12,
             greg-brockman 12, larry-ellison 12, sergey-brin 12, tobi-lutke 12,
             george-hotz 13
transcripts  667 blinded        grades 2395
judge calls  fable 665, astra 655, gemini 633
pair r       astra|fable 0.875 (n=653), astra|gemini 0.842 (n=621),
             fable|gemini 0.845 (n=631)
```

Ilya Sutskever sits 4th on n=7, the thinnest evidence base in the top five.
Anyone quoting the top of this board should know that.

## Open decisions, with costs

1. **`TARGET=14` or `TARGET=12`.** Both fetch sources are now exhausted, so
   41/50 is the ceiling from existing candidates. At 12 the board reaches 48/50
   today with no new fetching, leaving only Ilya Sutskever and Michael Dell
   short, at a cost of two transcripts of evidence per leader. Ten leaders sit
   at exactly 12 because the YouTube manifest was built with exactly 14
   candidates for a target of 14 and combined fetch-and-QA survival is about
   85%, so 14 candidates yield about 12. Reaching 14 honestly needs roughly 17
   candidates per leader, which is a sourcing run weighted toward recordings
   that survive the `subject named` screen. RECOMMENDATION: 12, because the
   cluster at 12 is the corpus telling you what it supports, and a target the
   data cannot reach mostly burns loop cycles.
2. **Existing history still holds about 200 MB of the old stderr log.**
   Shrinking it needs a history rewrite, which is disruptive across clones.
   RECOMMENDATION: leave it; the growth is stopped.

## The single next action

Wait for `grade_loop` to print `COMPLETE`, then decide the `TARGET` question
above. Nothing else is blocked.

## Verification command

```
git status --short --branch && git -C data status --short --branch | head -1
pgrep -f 'grade_loop.sh|happyscribe_loop.sh' | wc -l        # expect 2
tail -3 data/logs/grade_loop.log
for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || echo "FAIL $t"; done
.venv/bin/python -c "import json;d=json.load(open('data/results.json'));print(d['diagnostics']['judge_call_counts'])"
```

The last line must name THREE judges. If it names two, the fix in `f5971da`
has been reverted or overwritten.
