# Verbatim Index — working agreement for agents in this repo

`CLAUDE.md` is a symlink to this file. One working agreement, whichever
tool reads it.

The project skills follow the same rule. `.agents/skills/` is the one real
directory, which Codex reads, and `.claude/skills` is a symlink to it, which
Claude Code reads. Edit skills under `.agents/skills/`. Code that names a
`.claude/skills/...` path still works through the link, and every contract hash
covers file bytes and names, never the directory, so the move on 2026-09-27
changed no contract ID. Before that date each tool had its own copy, and the
Codex copy was an untracked import in which a blind "Claude" to "Codex"
rewrite had turned a measured result, "GPT-4o against Claude at phi=0.588",
into a false one. Two copies drift; do not recreate one.

**A clone that still holds an untracked `.agents/` directory must delete it
before it pulls this change**, or `git pull` refuses with "untracked working
tree files would be overwritten". On 2026-09-27 that was repo-2 and repo-3.
Their copies hold nothing the tracked files lack: they match byte for byte
except for the corrupted line above. `rm -rf .agents && git pull`.

Several Claude Code agents work this project at once, one per clone, under
`~/Code/misc/verbatim-index/repo-N`. Git is the only channel between them.
The `agent-fleet-git` skill governs how you commit; this file records what is
specific to this repo.

## Where the rest of this agreement lives

This file holds only what every agent needs on every task. Claude Code and Codex
load it at the start of every session, so its size is paid on every task. The
rest of the agreement is in `docs/agents/`, one file per part of the system.
Nothing loads those files for you: open the one that matches your task before
you change that part. Each one names, at its top, the work that needs it.

| Read this file | before you |
|---|---|
| [docs/agents/DAEMONS.md](docs/agents/DAEMONS.md) | Start, stop, restart or tune `fetch_loop.sh`, `happyscribe_loop.sh` or `grade_loop.sh`; set `TARGET`, `WORKERS`, `OPEN_PER_LEADER`, `PUBLISH_ON_COMPLETE` or `FABLE_ACCOUNTS`; or change how a loop prunes, detects a running source or decides it is COMPLETE. |
| [docs/agents/JUDGES.md](docs/agents/JUDGES.md) | Change `grade.py` or any judge call; touch the Gemini (`agy`) rotation, its accounts or its wrapper; read a judge's failure taxonomy; or add, drop or compare a judge. |
| [docs/agents/CORPUS.md](docs/agents/CORPUS.md) | Change discovery, fetching, QA, normalize or dedupe; retire or re-grade a transcript; or act on a wrong-person flag. |
| [docs/agents/BLINDING.md](docs/agents/BLINDING.md) | Change `blind()`, an alias list or `scripts/blind_wordlist.json`, or reason about what a judge can infer about the speaker. |
| [docs/agents/SCORING.md](docs/agents/SCORING.md) | Change `aggregate.py`, calibration, the venue adjustment, the subject-share cutoff, the rank floor or the bootstrap, or quote a number from `results.json`. |
| [docs/agents/SITES.md](docs/agents/SITES.md) | Change `build_site.py`, `build_predictions_site.py` or anything that sets the size or shape of a published page. |
| [docs/agents/MAP.md](docs/agents/MAP.md) | Look for the rubric, the roster, board membership, coverage, grader validation, study profiles, speaker turns or the leaders and predictions speaker-check pages. |
| [docs/agents/PREDICTIONS-PIPELINE.md](docs/agents/PREDICTIONS-PIPELINE.md) | Add, extract, verify, price, resolve or score predictions; move the scoring as-of date; change a policy release; run a case eval; or deploy the predictions site. |
| [docs/agents/DATING.md](docs/agents/DATING.md) | Run or change `date_recordings.py`, `dating_lib.py`, a merge version or the promotion of a dating run. |
| [docs/agents/PUNDITS.md](docs/agents/PUNDITS.md) | Work on the pundits study: its data repository, contract v2, judge harness, roster, discovery, pilot, speaker-check pages, labelling kit or deploy. |

Where each section of the old single-file agreement went, for a comment or a
document that still cites it by name:

| Section | Now in |
|---|---|
| Daemons (repo-0 only) | DAEMONS |
| The third judge: Gemini 3.8 Flash via Antigravity | JUDGES |
| Rules that exist because something broke | the rules for every task are below; each other rule is in the file of its topic, under this heading |
| Measurement decisions, and why | SCORING; the refusal-retry decision is in JUDGES |
| Experiments run, and what they showed | the file of each experiment's topic; the method notes are below |
| Known limits of the published score | SCORING, JUDGES, CORPUS and BLINDING |
| Where things are | MAP, CORPUS, SITES, PREDICTIONS-PIPELINE, DATING and PUNDITS |

Status and open work are not in this agreement. Deferred work is in
`BACKLOG.md`, and the status of each workstream is in its `docs/LEDGER-*.md`.

**Adding to the agreement.** Put new text in the file of its topic, under the
heading it fits. Add to this file only a rule that every agent needs on every
task. `scripts/test_agents_md_shards.py` refuses this file above 32,768 bytes.
That number is Codex's default `project_doc_max_bytes`: Codex reads no further
into this file, so anything past it is lost to every Codex agent. The test also
refuses a file in `docs/agents/` that the table above does not name, and an
`@`-import of one: Claude Code expands an `@path` import into every session,
which would put the whole agreement back into context.

## Two repositories, and who may push private `main`

`tonygwu/verbatim-index` is public and holds code, specifications, tests, and docs.
`tonygwu/verbatim-index-data` is private and holds transcripts, grades, logs, and results.
Both `/data` and `/.data-clones/` are ignored by the public repository.
Private records must never enter public commits. Stage named files in the correct repository.
Author email remains `446441+tonygwu@users.noreply.github.com` in both repositories.

**Since 2026-09-27 any clone may push the private data repo's `main` itself**, through
`scripts/data_sync.py`. Before that, only repo-0 could, and a busy repo-0 blocked
everyone else. The plan, its independent review, and the phase status are in
[docs/plans/shared-data-push-2026-09-27.md](docs/plans/shared-data-push-2026-09-27.md).

Every clone's `data` link points at its own checkout of the data repo. repo-0's is the
shared `verbatim-index/data`, where the daemons write. Every other clone has its own
under `.data-clones/`, so no two agents ever share a Git index.

`ownership.json` at the data repo's root decides who may change which path, and a
missing manifest refuses every push rather than defaulting:

- **owner** paths (transcripts, grades, logs, sources, roster, results) belong to the
  daemon clone, because its loops write them uncommitted and a push from anyone else
  would collide with a running loop.
- **shared** paths (`predictions/**`, `transcripts_web/**`, `experiments/**`) belong
  to every clone.
- **derived** files (`predictions/index.json`, `predictions/scores.json`) are
  regenerated from their inputs, never hand-merged. Both carry no timestamp, so the
  same inputs give the same bytes in any clone.

How to work with it:

- Commit, then **push with `data_sync.py push`** (`push --daemon` in repo-0). It merges
  origin/main (never rebases, so a pinned `input_data_commit` stays reachable),
  refuses a record file changed on both sides, regenerates derived files, validates
  every record the push adds or changes, checks the paths, and pushes. A lost race
  retries up to three times. Every refusal restores HEAD.
- **Take other clones' work with `data_sync.py pull`**, never `git pull --rebase` or
  `--autostash`, which would put a running loop's files back to HEAD.
- Never push data `main` by hand. The pre-push hook (`scripts/git-hooks/data/`,
  installed as `core.hooksPath`) runs the same check on a raw `git push`, but
  `--no-verify` skips it and this repository forbids that.

**Migration status, 2026-09-27.** Live for leaders. Data main carries
`ownership.json` and `.gitattributes` since `ceba3cba`. The shared checkout has
`role=daemon` and the hook installed. repo-2 has moved to `.data-clones/main` as a
contributor. repo-1 and repo-3, for leaders, still work on
`.data-clones/experiment` and move with
`.venv/bin/python scripts/data_sync.py adopt-main --apply` when idle. Read the dry
run's skipped lines first. Until a clone moves, it keeps the old workflow:
experiment output under `data/predictions/_experiments/<unique-run>/` on its own
`codex/*` branch. Pundits data has `role=daemon` but no manifest yet; repo-3 runs
`data_sync.py bootstrap --data data-pundits --study pundits`. See
[docs/DATA-CLONE-WORKFLOW.md](docs/DATA-CLONE-WORKFLOW.md) for the old workflow.

Until 2026-09-06 code and data shared one private repo. Its full history remains
read-only as `tonygwu/verbatim-index-archive`.

## Clone roles

A clone's role is `git config verbatim.role` in its DATA checkout. Every production
guard asks one predicate, `data_clone_workflow.daemon_role_error()`, which wants the
role spelled out; a checkout with no role can never run production work.

- **daemon**: repo-0 for leaders, repo-3 for pundits. Runs the daemons, withdrawals and
  production aggregation, pushes owner paths, and deploys the leaderboard and pundits
  sites, which render its uncommitted daemon output. Also needs its `.daemon-clone`
  marker naming the clone.
- **contributor**: any other clone, with its data checkout on `main`. Pushes shared and
  derived paths through `data_sync.py push`. Never writes into the daemon's live
  checkout, and never pushes an owner path.
- **experiment**: the older setup, on its own `codex/*` branch, writing only
  `data/predictions/_experiments/<unique-run>/`. `data_sync.py adopt-main` moves it to
  contributor. It carries whole experiment runs and reports every other path it
  leaves behind.

**Deploys.** The predictions site deploys from ANY push-role clone, but only from
exactly origin/main. The data and public checkouts must both be at their freshly
fetched origin/main, with the published paths clean. The deploy refuses if either
remote moves during rendering. It also refuses if the live page was built from a
revision we do not descend from, read from its no-store `revision.json`. The first
deploy after that check existed needs `--first-revision-deploy` once. The
leaderboard and pundits sites still deploy from the daemon clone only. Every
deploy script requires `--production-data` and `--data-revision`. Never bypass
them with a direct `npx wrangler deploy`.

## Setup in a fresh clone

```
git clone git@github.com:tonygwu/verbatim-index.git repo-N && cd repo-N
ln -s ../data data          # optional shared read view; opt into an independent clone below
git config user.email 446441+tonygwu@users.noreply.github.com
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || echo "FAILED $t"; done
```

The suite is GLOBBED, not typed out. A typed list is the defect this repo has
already paid for twice, in the hand-written judge list in `aggregate.py` and in
the single fetcher name in `grade_loop.sh`: a name written in one place goes
stale the day something is added beside it. The earlier version of this block
reached 21 of the files, 13 by hand and 8 through a typed predictions loop, and
had fallen 18 behind. RUN 2026-09-11: the glob finds 39 test files, all 39 pass,
and none of them spends judge quota, so the whole suite is safe in a fresh clone
before any account is wired up.

For experiments, follow `docs/DATA-CLONE-WORKFLOW.md` after setup.
`data_clone_workflow.py new-run` creates a unique run with provenance.
`test_data_clone_workflow.py` proves migration and publication guards with temporary repositories.

Python 3.12 or newer: `llm-quota-router`, which `grade.py` imports to route
Fable calls by measured quota, requires it.

## Rules that exist because something broke

- **Never call the judge through `cl`.** It injects
  `--dangerously-skip-permissions`, which gives the judge tool access to this
  repository, including the roster it is blinded against. `grade.py` uses
  raw `claude` with `--permission-prompts none` and refuses `--fable-bin cl`.
  Account routing comes from the `quota_router` library, not the launcher.

- **Never derive time from file mtime or the local clock.** Read
  `fetched_at_utc` out of the record. Loops touch files constantly.

- **No clone-absolute paths in committed code.** Use
  `git rev-parse --show-toplevel` or `Path(__file__)`.

- **Every failure gets a taxonomy entry**, never a bare count. `grade.py`
  logs `attempted / succeeded / failed` with `error_taxonomy`.

- **Outputs that cross clone boundaries are written atomically.**
  `data/results.json`, its audit file and `site/index.html` go through
  `scripts/atomicio.py`. `Path.write_text` truncates first, so a clone
  deploying while the grading loop rewrites results.json would read a prefix.

- **A mutate-restore-retest cycle inside one second can test the WRONG
  BYTECODE.** CPython's timestamp invalidation records the source mtime with
  one-second resolution, so restoring a file and re-importing it in the same
  second reuses the `.pyc` compiled from the version you just replaced.

  OBSERVED 2026-09-18 while mutation-testing `discover_sources.py`: the file on
  disk read `DEFAULT_WORKERS = 3`, `grep` agreed, and `import discover_sources`
  returned 8. Deleting `scripts/__pycache__/discover_sources*.pyc` fixed it.

  This matters because mutation testing is how this repo proves a check is real,
  and it fails in BOTH directions. A restore that silently keeps the mutation
  shows failures you will chase. Worse, a mutation that silently keeps the GOOD
  bytecode shows no failures, and the honest conclusion from that is "this test
  is vacuous", which is a conclusion you may then act on.

  So when a mutation does NOT bite, do not conclude the test is vacuous until you
  have ruled this out. Either `find scripts/__pycache__ -name '*.pyc' -delete`
  first, or run the arm with `PYTHONDONTWRITEBYTECODE=1`, or confirm the finding
  by a route that does not import the module at all. The one conclusion this
  actually threatened, that `test_membership_study_scope.py`'s end-to-end pundits
  arms were vacuous, was re-derived with a cleared cache and stands: a pundits
  aggregate run refuses at "no grades found" without ever reaching the membership
  block.

- **Stage by name.** `git add -A` in a shared clone sweeps in another agent's
  untracked work.

- **Data commits happen inside `data/`.** The root repo is public; nothing
  under `data/` may be committed there. `git -C data add <paths>`, commit, then
  `.venv/bin/python scripts/data_sync.py push`, never a bare `git -C data push`
  to main. The ownership manifest decides which paths a clone may push; see "Two
  repositories, and who may push private `main`".

Every other rule in this section moved to the file of its topic, under this same
heading: DAEMONS, JUDGES, CORPUS, SCORING and SITES.

## Experiments run, and what they showed

These settled questions that guesswork would have got wrong. Each is recorded
with its method, because the conclusions are only as good as the setup and a
later agent should be able to challenge them. The count is deliberately not
written out here: it said "Four" while eleven stood below it.

Each experiment is recorded in the file of its topic, under this same heading:
CORPUS, BLINDING, JUDGES, MAP, DATING and PREDICTIONS-PIPELINE.

**Method notes worth inheriting.** Two of these nearly produced wrong answers,
and both times the cause was the same: comparing against a moving target. The
grading loop writes continuously, so any before-and-after measured against
`data/` mixes the change under test with new grades. Copy the corpus once and
run both arms against the snapshot. Separately, a raw group mean is almost never
the effect you want here, because leaders are not randomly assigned to venues,
formats or judges; fit the nuisance factor with the other held fixed, and expect
the honest effect to be smaller than the raw one. The venue effect fell from 8.2
points to 5.7 that way.
