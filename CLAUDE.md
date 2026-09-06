# Verbatim Index — working agreement for agents in this repo

Several Claude Code agents work this project at once, one per clone, under
`~/Code/misc/verbatim-index/repo-N`. Git is the only channel between them.
The `agent-fleet-git` skill governs how you commit; this file records what is
specific to this repo.

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
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/test_grade_harness.py     # 15 pure checks, no quota
.venv/bin/python scripts/test_blinding.py
```

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
  raw `claude` with `--permission-prompts none`. See commit `9f6c144`.
- **Never derive time from file mtime or the local clock.** Read
  `fetched_at_utc` out of the record. Loops touch files constantly.
- **No clone-absolute paths in committed code.** Use
  `git rev-parse --show-toplevel` or `Path(__file__)`.
- **Every failure gets a taxonomy entry**, never a bare count. `grade.py`
  logs `attempted / succeeded / failed` with `error_taxonomy`.
- **Stage by name.** `git add -A` in a shared clone sweeps in another agent's
  untracked work.

## Where things are

- Rubric and schema (the grading contract, fingerprinted into every grade):
  `.claude/skills/leader-transcript-grader/`
- Published site: `site/index.html`, deployed with `npx wrangler deploy` to
  `verbatim-index.tonygwu.com`
- Per-leader pipeline coverage: `.venv/bin/python scripts/coverage_table.py`
- Grader validation (reliability, bias probes): `scripts/validate_grader.py`
