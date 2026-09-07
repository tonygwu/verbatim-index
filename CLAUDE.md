# Verbatim Index — working agreement for agents in this repo

Several Claude Code agents work this project at once, one per clone, under
`~/Code/misc/verbatim-index/repo-N`. Git is the only channel between them.
The `agent-fleet-git` skill governs how you commit; this file records what is
specific to this repo.

## Two repositories, nested

| Repo | Visibility | Where it is checked out | Holds |
|---|---|---|---|
| `tonygwu/verbatim-index` | public | the clone root, `repo-N/` | code, rubric, tests, docs |
| `tonygwu/verbatim-index-data` | private | **one** checkout at `verbatim-index/data`, reached from every clone through a `repo-N/data` symlink | transcripts, grades, logs, roster, results |

There is exactly one data checkout. Every clone points at it, so all clones
read the same bytes at the same instant and any clone can deploy a current
leaderboard with `bash scripts/deploy.sh`. Before 2026-09-07 each clone held
its own copy, which drifted: repo-0's live tree ran hundreds of grades ahead of
what the others could see, and only repo-0 could publish.

The sharing has a cost. A loop started in the wrong clone now writes the live
corpus instead of a private copy, so the three loops refuse to start unless
`data/.daemon-clone` names the clone they are in. Git commands are not
guarded, and one shared checkout means one `.git`: two agents running
`git -C data ...` at once contend on `index.lock`. **Only `repo-0` commits
`data/`.** That one stays a rule, not a precondition.

The root `.gitignore` lists `data/`, so `git status` at the root never shows
data changes and a public commit cannot sweep in a transcript. Data commits
are made inside `data/` with `git -C data ...`, by `repo-0` only. Scripts
address data as `data/...` relative to the root, unchanged from the single-repo
days. `site/index.html` is a build artifact, rendered from `data/results.json`
and gitignored; deploy it from disk.

Until 2026-09-06 code and data shared one private repo. Its full history is
kept read-only as `tonygwu/verbatim-index-archive`.

Author email in every clone, root and `data/`, is the GitHub noreply address
`446441+tonygwu@users.noreply.github.com`; GitHub rejects pushes carrying the
personal one.

## Clone roles

| Clone | Role | What it must not do |
|---|---|---|
| `repo-0` | Runs the three daemons (`fetch_loop`, `happyscribe_loop`, `grade_loop`), is the **only writer** of `data/`, and the only clone that commits it. | Feature work that another clone is already doing. |
| `repo-1`, `repo-2`, … | Code, tests, docs, analysis. Read `data/` freely. Deploy with `scripts/deploy.sh`. | Start any loop. Write under `data/`. Commit `data/`. |

Why one writer: the loops rewrite `data/transcripts`, `data/grades`, `data/logs`
and `site/index.html` every few minutes. A second clone writing there produces
merge conflicts on multi-megabyte JSON with no meaningful resolution. If you
need new data, ask the operator to pull it through `repo-0`.

## Setup in a fresh clone

```
git clone git@github.com:tonygwu/verbatim-index.git repo-N && cd repo-N
ln -s ../data data          # ONE shared checkout, cloned once at verbatim-index/data
git config user.email 446441+tonygwu@users.noreply.github.com
git -C data config user.email 446441+tonygwu@users.noreply.github.com
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/test_grade_harness.py     # pure checks, no quota
.venv/bin/python scripts/test_pipeline_dedupe.py  # pure checks, no quota
.venv/bin/python scripts/test_shared_data.py      # pure checks, no quota
.venv/bin/python scripts/test_blinding.py
.venv/bin/python scripts/test_coverage_table.py   # per-judge columns in the table
```

Python 3.12 or newer: `llm-quota-router`, which `grade.py` imports to route
Fable calls by measured quota, requires it.

## Daemons (repo-0 only)

```
TARGET=14 nohup bash scripts/fetch_loop.sh >> data/logs/fetch_loop.log 2>&1 &
nohup bash scripts/happyscribe_loop.sh >> data/logs/happyscribe_loop.log 2>&1 &
OPEN_PER_LEADER=0 nohup bash scripts/grade_loop.sh >> data/logs/grade_loop.log 2>&1 &
bash scripts/status.sh                 # live state of all three, plus coverage
```

`TARGET=14` is the transcripts-per-leader goal. Without it the loop defaults
to 5, sees every leader already there, and exits at once; that happened on
the 2026-09-06 restart. `OPEN_PER_LEADER=0` skips the unblinded control pass. It competes with the
blinded pass for the same Fable quota and the blinded pass is the published
score.

`WORKERS` is a judgment call between 6 and 10, and the loop defaults to 8.
The number does not change how much quota a pass spends, because the work is
the same either way. It changes how fast the pass spends it, and Fable
quota is the binding constraint. Read the two signals before choosing:

- `quotapick status` prints a `slack` figure per window. Negative slack means
  the account is being consumed faster than the budget that would carry it to
  its reset. If slack on the 5h window is negative, drop toward 6.
- `grep "accounts in rotation" data/logs/grade_loop.err | tail -1` names the
  Claude accounts that still have measured Fable headroom. If only one account
  is carrying the whole Fable load, extra workers queue against that one
  account and exhaust its window sooner, so stay at 6 to 8. If three or more
  accounts are in rotation, 10 is safe.

Raising `WORKERS` when Fable is already short does not fail loudly. The jobs
run, hit the limit, and land in the taxonomy as `auth_or_quota`, so the pass
looks busy while producing nothing. Check `data/logs/grade_errors_blind.jsonl`
for that label before assuming a slow pass is a healthy one.

`FABLE_ACCOUNTS` pins the Fable rotation to named accounts, for example
`FABLE_ACCOUNTS=default`. Use it when only some accounts can serve Fable.
Measured headroom cannot see paid usage credits: an account whose weekly
Fable window is 100% used reports 0.00 remaining whether or not credits let
it keep answering. Without the pin, `grade.py` rotates over every account and
each job that lands on one without credits fails with `auth_or_quota`.
Anthropic enforces the monthly credit cap server-side, so an unattended run
stops on its own rather than overspending.

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
- **A transcript that leaves the corpus must be withdrawn, not just skipped.**
  `data/transcripts_blind` and `data/transcripts_open` are derived. `grade.py`
  grades every file it finds there and `aggregate.py` counts every grade it
  finds, so a transcript that is retired as a duplicate or rejected by QA keeps
  scoring until its derived copy AND its grades go. `normalize_transcripts.py
  --grades` does both. It refuses if the removal looks like a wrong path rather
  than a withdrawal. Found 2026-09-07: 27 withdrawn transcripts were still on
  the leaderboard, and one appearance was counted three times.
- **Only `grade_loop.sh` prunes.** `fetch_loop.sh` normalizes with
  `--no-prune` and no `--grades`. Both loops normalize the same two
  directories and each lists the corpus once at the top, so a second pruner
  deletes what the first just wrote and orphans its grades. `prune_orphans`
  also re-reads the shelf at deletion time, so it is safe even under a race.
  Found by adversarial review of a78baf5, after that commit made a previously
  write-only path destructive.
- **A retirement must be visible to the fetcher.** The sweep renames a source
  to `<source_id>.json.superseded`, which `dest.exists()` does not match, so
  the fetcher re-downloaded it every cycle and the sweep retired it every
  cycle. `fetch_one` now honours that name, and reports the skip as its own
  `superseded` category rather than letting the tally stop adding up.
- **The duplicate sweep runs in `grade_loop.sh`, before normalize.** Most
  duplicates are one talk re-uploaded to several YouTube channels, and those
  arrive through `fetch_loop.sh`. The sweep used to run only in
  `happyscribe_loop.sh`, which adds nothing on YouTube's side, so a re-upload
  was graded before the next sweep saw it.
- **Outputs that cross clone boundaries are written atomically.**
  `data/results.json`, its audit file and `site/index.html` go through
  `scripts/atomicio.py`. `Path.write_text` truncates first, so a clone
  deploying while the grading loop rewrites results.json would read a prefix.
- **Stage by name.** `git add -A` in a shared clone sweeps in another agent's
  untracked work.
- **Data commits happen inside `data/`.** The root repo is public; nothing
  under `data/` may be committed there. `git -C data add <paths>` and
  `git -C data push`, from `repo-0` only.

## Where things are

- Rubric and schema (the grading contract, fingerprinted into every grade):
  `.claude/skills/leader-transcript-grader/`
- Published site: `site/index.html`, deployed with `npx wrangler deploy` to
  `verbatim-index.tonygwu.com`
- Per-leader pipeline coverage: `.venv/bin/python scripts/coverage_table.py`
- Grader validation (reliability, bias probes): `scripts/validate_grader.py`
