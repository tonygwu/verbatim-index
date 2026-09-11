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
