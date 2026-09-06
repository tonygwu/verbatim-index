# Verbatim Index — working agreement for agents in this repo

Several Claude Code agents work this project at once, one per clone, under
`~/Code/misc/verbatim-index/repo-N`. Git is the only channel between them.
The `agent-fleet-git` skill governs how you commit; this file records what is
specific to this repo.

## Two repositories, nested

| Repo | Visibility | Where it is checked out | Holds |
|---|---|---|---|
| `tonygwu/verbatim-index` | public | the clone root, `repo-N/` | code, rubric, tests, docs |
| `tonygwu/verbatim-index-data` | private | `repo-N/data/`, gitignored by the root | transcripts, grades, logs, roster, results |

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
| `repo-0` | Runs the three daemons (`fetch_loop`, `happyscribe_loop`, `grade_loop`) and is the **only writer** of `data/`. Deploys the site. | Feature work that another clone is already doing. |
| `repo-1`, `repo-2`, … | Code, tests, docs, analysis. Read `data/` freely. | Start any loop. Write under `data/`. Deploy. |

Why one writer: the loops rewrite `data/transcripts`, `data/grades`, `data/logs`
and `site/index.html` every few minutes. A second clone writing there produces
merge conflicts on multi-megabyte JSON with no meaningful resolution. If you
need new data, ask the operator to pull it through `repo-0`.

## Setup in a fresh clone

```
git clone git@github.com:tonygwu/verbatim-index.git repo-N && cd repo-N
git clone git@github.com:tonygwu/verbatim-index-data.git data
git config user.email 446441+tonygwu@users.noreply.github.com
git -C data config user.email 446441+tonygwu@users.noreply.github.com
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/test_grade_harness.py     # 33 pure checks, no quota
.venv/bin/python scripts/test_blinding.py
```

Python 3.12 or newer: `llm-quota-router`, which `grade.py` imports to route
Fable calls by measured quota, requires it.

## Daemons (repo-0 only)

```
TARGET=14 nohup bash scripts/fetch_loop.sh >> data/logs/fetch_loop.log 2>&1 &
nohup bash scripts/happyscribe_loop.sh >> data/logs/happyscribe_loop.log 2>&1 &
WORKERS=10 OPEN_PER_LEADER=0 nohup bash scripts/grade_loop.sh >> data/logs/grade_loop.log 2>&1 &
bash scripts/status.sh                 # live state of all three, plus coverage
```

`TARGET=14` is the transcripts-per-leader goal. Without it the loop defaults
to 5, sees every leader already there, and exits at once; that happened on
the 2026-09-06 restart. `OPEN_PER_LEADER=0` skips the unblinded control pass. It competes with the
blinded pass for the same Fable quota and the blinded pass is the published
score.

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
