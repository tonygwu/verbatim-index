# Verbatim Index — session handoff, 2026-09-07 ~21:20 PDT

Written before a context clear. Everything here is verifiable with the
commands given; do not trust a line without running its check.

## Pinned revision

| Repo | Commit | Pushed |
|---|---|---|
| code (`repo-0`, public) | `9ce441a` on `main` | yes |
| data (`data/`, private) | `0b130a6` on `main` | yes |

Verify: `git status --short --branch && git -C data status --short --branch`
Both should read `## main...origin/main`. The data tree goes dirty again
within minutes because the daemons write continuously; that is normal.

## The single next action

The board is deployed and current as of the commit below. If grades have
accumulated since, redeploy:

    bash scripts/deploy.sh --refresh

`--refresh` re-aggregates `data/results.json` first. A plain `deploy.sh` only
re-renders and will republish stale numbers; it shipped a stale board twice on
2026-09-07 before that flag existed. The command prints a staleness line
either way — read it.

Then verify the LIVE page, not the local file. The Cloudflare edge lags ~10s,
so an immediate curl reads the previous version and looks like a failed
deploy:

    sleep 10
    curl -s "https://verbatim-index.tonygwu.com/?cb=$RANDOM" -o /tmp/live.html
    .venv/bin/python -c "
    import json,re
    d=json.loads(re.search(r'const DATA\s*=\s*(\[.*?\]);', open('/tmp/live.html').read(), re.S).group(1))
    print('scored:', sum(r['n'] or 0 for r in d), 'across', len(d), 'leaders')"

Last published: version `0eace5c1`, 463 transcripts scored, deployed 2026-09-07 ~21:25 PDT.

## Background processes (NOT started by this session, do not stop them)

    ps -eo pid,etime,command | grep -E "fetch_loop|grade_loop|happyscribe_loop" | grep -v grep

Three daemons, running ~11h: `fetch_loop.sh`, `happyscribe_loop.sh`,
`grade_loop.sh`. Only `repo-0` may run them. `grade_loop` rewrites
`site/index.html` every cycle, so the local file can differ from what was last
deployed. Expected, not a bug.

No jobs from this session are running. The 2:55pm wakeup cron (`74d2995b`)
fired, completed, and auto-deleted. The resume lock is released.

## State of the work

- **Judge parity almost closed.** astra-only went 107 -> 14 today; ~16 Fable
  calls remain to give every graded transcript both judges. Check with
  `.venv/bin/python scripts/coverage_table.py | tail -3`.
- **Fable quota is per-account and reopens on its own.** No restart needed;
  `grade.py` re-measures every cycle via the `quota_router` library.
  Account A's monthly usage-based billing was turned OFF by the operator on
  2026-09-07, so A is now window-limited like the rest. Weekly Fable resets:
  `claude-d` Tue Sep 8 ~11am, `claude-b` Wed Sep 9 ~2am, `claude-c` Fri Sep 11
  ~6pm (note: `claude-c` is a max 5x plan, ~1/4 the capacity of the others).
- **Discovery was widened.** `discover_sources.py --candidates-per-leader`
  (new flag) was run at 26 for the ten thinnest leaders, adding 148 candidates.
  These are ranks 15-26, so a HIGHER share should fail QA. Watch the `REJ`
  column in the coverage table.

## Open decisions

1. **Make the duplicate count durable.** `UNIQ` in the coverage table subtracts
   appearances retired as re-uploads, counted from `.superseded` markers on
   disk. `data/.gitignore` excludes those, so a fresh clone sees zero and
   `UNIQ` collapses to `IDENT`. The table prints a NOTE when that happens
   rather than silently reverting.
   - Do nothing: correct on this machine, degraded elsewhere. Free.
   - Commit a retirement log: correct everywhere, costs a new data file the
     sweep must maintain.
   - Recommendation: do nothing until a second clone actually needs it.
2. **Whether to keep widening discovery.** Going deeper in the ranked list is
   the safe lever. Lowering `MIN_SEC` (900) admits clips; raising
   `MAX_PER_CHANNEL` (2) admits more re-uploads, which is already the binding
   constraint. Recommendation: judge the current batch's REJ rate first.

## Things established this session that are easy to re-derive wrongly

- **`FETCH` below `IDENT` is usually duplicates, not failures.** Lip-Bu Tan
  showed 7 of 14 and had a perfect fetch record: 7 live + 7 `.superseded`.
  That is why `UNIQ` exists. Do not "fix" a low `FET%` by widening filters
  before checking `.superseded` counts.
- **`deploy.sh` is two steps, not one.** Rendering matches the page to
  `results.json`; only `aggregate.py` matches `results.json` to the grades.
- **Exit code 0 from the Claude CLI proves nothing.** A quota refusal exits 1
  with the reason in STDOUT as JSON; a wrong-model substitution exits 0.
  Assert `modelUsage` names `claude-fable-5-1`.
- **Jeff Bezos reads 8 transcripts of 16 fetched** — 4 rejected at QA, 4 where
  he speaks under the 10% subject-share floor. Correct behaviour, already
  investigated, not a bug to reopen.

## Verification command

    git status --short --branch && git -C data status --short --branch | head -1 \
      && git log --oneline -1 && git -C data log --oneline -1 \
      && ps -eo pid,command | grep -c "[g]rade_loop"

Expect: code clean at `9ce441a`, data at `0b130a6`, one grade_loop running.
