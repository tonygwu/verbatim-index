# Plan: every clone pushes private `main` itself, without clobbering

## Context

Today only repo-0 may commit the private data repo's `main` and deploy. Every
other clone works on its own `codex/*` branch in its own checkout
(`.data-clones/experiment`) and waits for repo-0 to merge it. Tonight that blocked
publishing the investor scores while repo-0 was busy with unrelated work.

The rule dates from when all clones shared ONE checkout and ONE Git index, so one
agent's commit could sweep in another's staged files. The 2026-09-14 rollout
already gave every clone its own checkout, which removed that mechanism. History
shows no lost commit on `main` ever (75 commits, all agent-typed; no script runs
`git commit`/`push` in `data/`). What remains are four smaller risks, and this plan
closes each one explicitly:

1. **Lost commits on a push race.** Git already refuses a non-fast-forward push; the
   tool fetches, merges and retries.
2. **Textual conflicts in derived files** (`predictions/index.json` changes on every
   rebuild because of `generated_at_utc`). They are never hand-merged; they are
   regenerated from the merged inputs.
3. **Clean-but-wrong merges and stale derived files.** Line-level merges of
   in-place-rewritten JSONL, or a derived file committed over newer inputs. Blocked
   by `merge=binary` attributes and by freshness hashes checked against the commit.
4. **Collisions with repo-0's daemons**, which write uncommitted files into repo-0's
   checkout. Other clones never touch daemon-owned paths, and repo-0 only
   fast-forwards or merges; it never rebases or autostashes.

Operator decisions (2026-09-27): any clone pushes `main`; daemon-owned paths stay
owner-only; `scores.json` becomes declarative via a committed config; any clone may
deploy from pushed `origin/main`.

**One decision narrowed by the code.** Opening deploys works for the PREDICTIONS
site only. The leaderboard and pundits sites render from repo-0's uncommitted daemon
output (`grade_loop.sh:292` deploys `results.json` and `grades/` over HEAD), so any
other clone's `origin/main` copy is older than what repo-0 serves. Those two sites
keep their current owner-mode deploy. Opening them would first need the daemons to
commit their own output, which is a separate project.

## Design

**Ownership manifest, in the data repo** (`ownership.json` at the data-repo root, one
per study repo). It maps path globs to `shared` or `owner`, and marks each derived
file with the command that regenerates it. It lives in the data repo, not the public
repo, so every clone enforces the same version (read from `origin/main`). It is
itself owner-only. Unlisted paths are refused.

- `owner`: `transcripts_open/`, `transcripts_blind/`, `transcripts/`,
  `transcripts_hs/`, `grades/`, `logs/`, `sources/`, `roster/`, `results.json`,
  `results_audit.json`, `ownership.json`, `.gitattributes`.
- `shared`: `predictions/**` (records, `_runs`, `_raw`, `_inputs`, `_experiments`),
  `experiments/**`, and `transcripts_web/`. Prediction agents place
  `transcripts_web/` by hand during sourcing, and no daemon writes it.
- `derived`: `predictions/index.json` (aggregate_predictions) and
  `predictions/scores.json` (score_predictions `--config`).
- Pundits (`verbatim-pundits-data`, owned by repo-3) gets a manifest where
  everything is `owner`, so nothing changes there.

**Data-repo `.gitattributes`**: `merge=binary` on `predictions/**/*.jsonl`,
`predictions/**/*.meta.json`, `predictions/index.json`, `predictions/scores.json` and
`predictions/scoring.json`. Two edits to the same file then conflict instead of
merging line by line into records no single run produced. This covers a raw
`git pull` too. The glob is recursive on purpose: a depth-3 glob misses 46 of
the 1,914 record files, all under `_experiments/<run>/`, which are the files
contributors edit most. A test counts the attribute's matches against
`git ls-tree`. (Review item 1.)

**`scripts/data_sync.py`**, one tool with these subcommands:

- `check <range>`: fetches first, and says which `origin/main` SHA it read. It
  validates every path in `origin/main..HEAD` against the manifest and this clone's
  role, including deletes, renames and mode changes. It hashes from the COMMIT
  (`git ls-tree` / `cat-file`), never from disk, and checks freshness of the derived
  files. If `origin/main` has no `ownership.json`, it REFUSES; it never defaults to
  all-owner or all-shared. (Review item 6.)
- `push` (contributor mode):
  1. Fetch, then MERGE `origin/main` into `main`. It does not rebase: run manifests
     pin `input_data_commit` (`data_clone_workflow.py:417`), and a rebase would
     orphan a pinned SHA. Cost: `main` history is non-linear. (Review item 4.)
  2. If the only conflicted paths are derived files, finish the merge and regenerate
     them. If any other path conflicts, abort the merge, restore the branch, and
     report the paths. It never resolves with `ours` or `theirs`.
  3. Refuse if a `<sid>.jsonl` / `.meta.json` pair changed on both sides since the
     merge-base, even when git merged it cleanly.
  4. Regenerate derived files in a throwaway detached worktree at the merged HEAD,
     so untracked files cannot leak in. Commit them as "Regenerate derived files",
     with the generation time in the commit message.
  5. Run `score --config` and `validate_predictions.py` over the merged tree. Refuse on a
     duplicate sidecar across runs (the existing `load_across` guard) or on records
     without their `_runs` manifests.
  6. Push. Git's push is a compare-and-swap on the ref. On a non-fast-forward
     rejection, retry from step 1, up to 3 times. Report attempted, succeeded and
     failed with the reason.
- `push --daemon` (repo-0): `git fetch && git merge --ff-only origin/main` to pull
  in others' work, and a merge commit (never a rebase, never `--autostash`) when
  repo-0's own commits need to land on a moved `main`. Both leave dirty daemon files
  untouched. Before committing, it checks that `results.json`'s `grade_files_read`
  equals the grade count in the tree being committed.
- `adopt-main`: moves a clone from its `codex/*` branch to `main` with
  `verbatim.role=contributor`. It clones fresh at `origin/main` and carries over only
  whole `_experiments/<run>` directories, reusing `copy_owned()`. It REPORTS every
  path on the old branch that is missing from `origin/main` and was not carried,
  each as skipped with its reason. Example: repo-1's branch has 9 commits missing
  from `origin/main`, including `7e27ea63`, which edits the owner-only
  `roster/final.json`. Old `codex/*` branches are left alone as archive refs, never
  rebased. (Review item 3.)

**Pre-push hook** at `scripts/git-hooks/data/pre-push`. `adopt-main` and `setup`
install it through `core.hooksPath` in each data checkout. It runs
`data_sync.py check`, so a raw `git push` gets the same checks. It prevents
accidents, not abuse: `--no-verify` bypasses it, and the repo rules already forbid
that.

**Deterministic derived files**, so a rebuild with unchanged inputs changes no bytes
and cannot cause a retry loop:
- `aggregate_predictions.py`: DROP `generated_at_utc`, and put the time in the
  commit message instead. There is no compare-around-a-field path. Readers of the
  field, such as the deploy log line, change with it. Add
  `transcripts_listing_sha256` over the transcript roots it lists, which today
  escapes the freshness check. (Review item 5.)
- `score_predictions.py`: a `--config predictions/scoring.json` mode (runs, as_of,
  trend, min_lead_days), and run paths stored relative to the repo. An
  `inputs_sha256` covering records, sidecars, `criteria_repairs`, `index.json` and
  `scoring.json`. `generated_at_utc` is dropped here too.

**Roles.**
- `data_clone_workflow.guard_prediction_write()` (`:377`) also blocks a
  `contributor` from writing into the live repo-0 checkout.
- Production requires an explicit `verbatim.role=daemon` instead of "not
  experiment". That test lives in two places today, `daemon_guard.sh:36` and
  `owner_error()` at `data_clone_workflow.py:65`. The shell guard will call one
  Python predicate so there is a single source. Both production checkouts have NO
  role today, repo-0's `data` and repo-3's `.data-clones/pundits`. So `role=daemon`
  is set on BOTH before the P4 change merges; otherwise every production loop
  refuses on its next start. (Review item 2.)
- `setup()` keeps refusing `main` for experiment clones; `adopt-main` is the only
  path onto `main`.

**Predictions deploy from `origin/main`** (`deploy_predictions.sh` and
`deploy_source.sh`). Accept any clone when all of these hold:
- the data HEAD equals freshly fetched `origin/main`;
- published paths are clean;
- derived files are fresh;
- the public HEAD equals public `origin/main` and is clean.

Re-fetch immediately before `wrangler deploy` and refuse if either `origin/main`
moved. Publish the data revision in a small no-store JSON file beside the page, not
in the HTML, because Cloudflare may serve a cached page. Refuse if the live revision
is not an ancestor of ours, because `wrangler` is last-writer-wins. Also refuse if
the file is unreadable or absent. The first deploy after this change passes an
explicit one-time flag, since no live revision exists yet. (Review item 7.) Remove
`--refresh` from `deploy_predictions.sh`; it now fails with a pointer to
`data_sync push`. `deploy.sh`, `deploy_pundits.sh` and the `grade_loop` auto-deploy
stay on `publication_source()` owner mode.

## Phases (each lands test-first, one commit per phase, suite green)

- **P0 Deterministic derived files.** Changes `aggregate_predictions.py` and
  `score_predictions.py` (`--config`, `inputs_sha256`, relative run paths). Adds a
  committed `predictions/scoring.json` carrying today's two runs. Tests:
  `test_index_deterministic`, `test_index_transcript_listing_stale`,
  `test_scores_config_equivalence` (`--config` output byte-equal to the flag form),
  `test_scores_inputs_sha`, `test_derived_no_timestamp` (two rebuilds from the same
  inputs are byte-identical).
- **P1 also covers bootstrap**: `test_check_refuses_missing_manifest`.
- **P1 Manifest and check.** Adds `ownership.json`, `.gitattributes`, and
  `data_sync.py check`. Tests: `test_ownership_paths` (renames, deletes,
  `transcripts_web` shared, roster owner-only, unknown path refused, pundits
  all-owner), `test_check_uses_tree_not_disk`.
- **P2 Contributor push.** Tests: `test_sync_clean_merge`,
  `test_sync_pinned_input_commit_reachable` (a run's `input_data_commit` is still
  reachable from `origin/main` after the push),
  `test_sync_derived_conflict_regen`, `test_sync_jsonl_both_sides_refused`,
  `test_sync_duplicate_sidecar_refused`, `test_sync_nonff_retry_then_report`,
  `test_sync_missing_runs_manifest_refused`. Each builds a bare remote plus two
  clones in a temp dir, following `test_data_clone_workflow.py`.
- **P3 Daemon mode.** Tests: `test_daemon_pull_with_dirty_daemon_paths` (dirty
  files byte-identical afterwards), `test_daemon_pull_untracked_collision_refused`,
  `test_daemon_results_grade_count_gate`.
- **P4 Roles, hook, adopt-main.** Before this merges: set `role=daemon` on repo-0's
  `data` and on repo-3's `.data-clones/pundits` (repo-0 and repo-3 run one
  `git config` each). Tests: `test_role_contributor_guards`,
  `test_daemon_role_single_predicate` (shell and Python agree),
  `test_adopt_main_copies_only_owned` (its fixture branch carries an owner-only
  commit that must be reported as skipped), `test_prepush_hook_matches_sync_check`,
  `test_gitattributes_covers_all_records` (matches equal `git ls-tree` count).
- **P5 Predictions deploy from origin/main.** Tests:
  `test_deploy_origin_mode_dirty_refused`, `test_deploy_origin_moved_refused`,
  `test_deploy_public_code_drift_refused`, `test_deploy_live_revision_ancestor`,
  `test_deploy_live_revision_unreadable_refused` (and allowed only with the
  one-time flag),
  `test_grade_loop_autodeploy_still_owner_mode`.
- **P6 Docs and migration.** Rewrites the ownership sections in `AGENTS.md` and
  `docs/DATA-CLONE-WORKFLOW.md`, adds a ledger. Then, in order: repo-0 sets
  `role=daemon` and commits the manifest and attributes, which is the one step that
  needs repo-0; each other clone then runs `adopt-main` once, when idle.

## Critical files

- `scripts/data_clone_workflow.py`: roles, `guard_prediction_write`,
  `publication_source`, `copy_owned`, `prediction_inputs_sha256`.
- `scripts/daemon_guard.sh`, `scripts/deploy_source.sh`,
  `scripts/deploy_predictions.sh`.
- `scripts/aggregate_predictions.py`, `scripts/score_predictions.py`.
- New: `scripts/data_sync.py`, `scripts/git-hooks/data/pre-push`, and in the data
  repo, `ownership.json` and `.gitattributes`.

## Verification

- Each phase: its new tests fail before and pass after, and
  `bash scripts/run_tests.sh` reports `failed: 0`.
- End to end in temp repos: two contributor clones push disjoint predictions work
  concurrently, both land, and `index.json` / `scores.json` are fresh. A third push
  touching `grades/` is refused. A daemon clone with dirty `grades/` pulls both,
  and its dirty files are byte-identical afterwards.
- Live dry run after P6: one contributor pushes a trivial `_experiments` run with
  `data_sync push`, then runs `deploy_predictions.sh --dry-run` from that clone.
  The dry run passes, and repo-0's `git merge --ff-only` succeeds while its daemons
  run. No daemon runs today, so the loops must be started first, and their running
  state shown, or this step proves nothing about the dirty-tree pull.

## Out of scope

- Opening the leaderboard and pundits deploys, which needs daemons that commit their
  own output.
- Server-side enforcement. Branch protection is unavailable on this private plan, and
  the hook plus the tool are client-side guards.

## Status

Approved by the operator 2026-09-27, after an independent review whose seven
required changes are folded in above (each marked "Review item N").

| Phase | State | Commit |
|---|---|---|
| P0 deterministic derived files | done: code 020cd25, data a5525e31 (index, scoring.json, scores regenerated from repo-0 on 2026-09-27; content byte-equal apart from bookkeeping keys, score line unchanged; predictions site deployed) | see git log |
| P1 manifest and check | done in code: `data_sync.py check`, templates in `data-repo-templates/` (data repos get them in P6) | 4bb7278 |
| P2 contributor push | done in code: `data_sync.py push` | see git log |
| P3 daemon mode | done in code: `data_sync.py push --daemon`, `data_sync.py pull` | see git log |
| P4-P6 | not started | |

### What P0 changes for the next predictions deploy

P0 is code only. Until the data side catches up, the next predictions deploy
REFUSES, by design, because the live index and scores cannot prove they are fresh:

- `predictions/index.json` must be rebuilt, because it now carries
  `transcripts_listing_sha256` and no longer carries `generated_at_utc` or
  `predictions_root`. The deploy refuses an index without the listing fingerprint.
- `predictions/scoring.json` must be committed beside `scores.json`, and
  `scores.json` regenerated from it, because the deploy now refuses a scores file
  whose inputs it cannot check. The config for the board published on 2026-09-27:

```
{
 "as_of": "2026-09-16",
 "index": "predictions/index.json",
 "min_lead_days": 60,
 "out": "predictions/scores.json",
 "predictions": ["predictions"],
 "runs": [
  "predictions/_experiments/phase2-scoring-20260915",
  "predictions/_experiments/investor-phase2-20260927"
 ],
 "trend": true
}
```

Until P6 moves ownership, those three writes are repo-0's:

```
git pull --ff-only
.venv/bin/python scripts/aggregate_predictions.py            # data/predictions/index.json
# write the config above to data/predictions/scoring.json
.venv/bin/python scripts/score_predictions.py --config data/predictions/scoring.json
git -C data add predictions/index.json predictions/scoring.json predictions/scores.json
git -C data commit -m "Deterministic index and scores, with the scoring config committed"
git -C data push
bash scripts/deploy_predictions.sh --production-data "$(cd data && pwd -P)" \
    --data-revision "$(git -C data rev-parse HEAD)" --dry-run
```

The score line must still read
`417 past due -> 330 eligible -> 389 resolved -> 243 scored across 31 ranked leaders`,
and apart from bookkeeping keys (`run_dir`, `run_dirs`, `settings`,
`inputs_sha256`, and the removed `generated_at_utc`) the content equals today's
`scores.json`. That was verified from repo-2 with the flag form on data `ec5ae558`.
