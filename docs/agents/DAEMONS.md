# Daemons and loops

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you start, stop, restart or
tune `fetch_loop.sh`, `happyscribe_loop.sh` or `grade_loop.sh`; set `TARGET`,
`WORKERS`, `OPEN_PER_LEADER`, `PUBLISH_ON_COMPLETE` or `FABLE_ACCOUNTS`; or
change how a loop prunes, detects a running source or decides it is COMPLETE.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Daemons (repo-0 only)

```
nohup bash scripts/fetch_loop.sh >> data/logs/fetch_loop.log 2>&1 &
nohup bash scripts/happyscribe_loop.sh >> data/logs/happyscribe_loop.log 2>&1 &
OPEN_PER_LEADER=0 nohup bash scripts/grade_loop.sh >> data/logs/grade_loop.log 2>&1 &
bash scripts/status.sh                 # live state of all three, plus coverage
```

`TARGET` is the transcripts-per-leader goal and now defaults to 12, so the
command line no longer carries it. It used to default to 5 and every real run
passed `TARGET=14`, which made the default a trap: a restart without it read 5,
found every leader already above it, and printed COMPLETE in under a second.
14 was never reachable either. The YouTube manifest was built at a median of
exactly 14 candidates per leader, and MEASURED yield is about 85% end to end
(fetch keeps 93% of candidates, QA keeps 92% of those), so 14 candidates give
about 12. Both sources are now exhausted, so 12 is what the sources hold rather
than a compromise; going back to 14 needs about 17 candidates per leader.
TARGET is a FETCHING goal and gates no published number: it appears zero times
in `aggregate.py` and `build_site.py`, and the board is gated by
`MIN_TRANSCRIPTS_TO_RANK` instead. `scripts/test_target_default.py` asserts that
separation as well as the number.

`OPEN_PER_LEADER=0` skips the unblinded control pass. It competes with the
blinded pass for the same Fable quota and the blinded pass is the published
score.

`PUBLISH_ON_COMPLETE=1` makes `grade_loop.sh` deploy to the live site ONCE, at
the COMPLETE exit and nowhere else, and it is off by default. Plain
`deploy.sh`, not `--refresh`: the last cycle already aggregated and rendered, so
`results.json` is current. The loop supplies its production source and current
data revision explicitly, and `deploy.sh` stays read-only on data. A failed
push says so and exits 1 rather than reading as a clean finish, because silence
there would recreate the stale-board bug it sits next to. Guarded by
`scripts/test_publish_on_complete.py`, which also pins the publish block AFTER
the stale-board check.

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

The Gemini rotation comes from the llm-quota-router config
(`~/.config/quota-router/config.toml`), not from a variable. Every enabled
Antigravity account in the Gemini pool is a profile, and one that declares
`macos_user` becomes `user:<macos_user>`. `GEMINI_USERS` may restate the users
but `grade.py` refuses when it disagrees with the config. `AGY_BIN` defaults to
`/usr/local/bin/agy`, the one path `agy-as-user` runs. See the Antigravity
section for the three preconditions and why `sudo -u` alone fails.

`FABLE_ACCOUNTS` pins the Fable rotation to named accounts, for example
`FABLE_ACCOUNTS=default`. Use it when only some accounts can serve Fable.
Measured headroom cannot see paid usage credits: an account whose weekly
Fable window is 100% used reports 0.00 remaining whether or not credits let
it keep answering. Without the pin, `grade.py` rotates over every account and
each job that lands on one without credits fails with `auth_or_quota`.
Anthropic enforces the monthly credit cap server-side, so an unattended run
stops on its own rather than overspending.

## Rules that exist because something broke

- **A transcript source says it is running; nothing infers it.** Every fetch
  loop calls `claim_run_marker "$(basename "$0")"` from `scripts/run_marker.sh`
  right after the daemon guard, and every such script is listed in `FETCHERS`
  in `grade_loop.sh`. Do not reintroduce `pgrep` or `ps` text matching for
  this. It failed twice on 2026-09-11: one literal name missed the second
  source, and a hardened process-list parse said no source was running for 35
  minutes while one was, and never reproduced. A marker counts only while its
  pid is alive with the recorded start time, read with `TZ=UTC`; never read its
  mtime. Guarded by `scripts/test_run_marker.py`.

- **Only `grade_loop.sh` prunes.** `fetch_loop.sh` normalizes with
  `--no-prune` and no `--grades`. Both loops normalize the same two
  directories and each lists the corpus once at the top, so a second pruner
  deletes what the first just wrote and orphans its grades. `prune_orphans`
  also re-reads the shelf at deletion time, so it is safe even under a race.
  Found by adversarial review of a78baf5, after that commit made a previously
  write-only path destructive.

- **A loop may not declare COMPLETE while another SOURCE is still writing.**
  `grade_loop.sh` decided it was finished with one literal,
  `pgrep -f "fetch_loop.sh"`, written when YouTube was the only source. Happy
  Scribe was added later as a deliberately independent second source and this
  check never learned about it. OBSERVED 2026-09-11: grade_loop finished at
  04:17:37Z, happyscribe_loop merged 8 transcripts at 04:49:11Z, nothing graded
  them and nothing reported it; it was caught only because the coverage numbers
  stopped matching. The sources are declared once in the `FETCHERS` array and
  the exit check iterates it, so a third source is one edit in an obvious place.
  The detector is NOT `pgrep -f`, which matches any process whose full command
  line merely contains the name: on 2026-09-11 `pgrep -f grade_loop.sh` returned
  two pids and only one was the loop, the other a `/bin/zsh -c` wrapper. A false
  positive there makes the grader wait for ever for a source that is not
  running, which is this house's own six-spinning-poll-loops failure arriving
  again. `fetcher_running()` reads `ps -Ao comm=,args=` and drops any shell whose
  third field is `-c`. Guarded by `scripts/test_fetcher_detection.py` and
  `scripts/test_fetcher_false_positive.py`, which start real processes rather
  than inspecting source, because source inspection cannot tell a working
  pattern from one that never matches.

- **The duplicate sweep runs in `grade_loop.sh`, before normalize.** Most
  duplicates are one talk re-uploaded to several YouTube channels, and those
  arrive through `fetch_loop.sh`. The sweep used to run only in
  `happyscribe_loop.sh`, which adds nothing on YouTube's side, so a re-upload
  was graded before the next sweep saw it.

- **A render that failed must say so, and a loop may not report COMPLETE over a
  board it could not rebuild.** `grade_loop.sh` chained aggregate and build_site
  with `&&`, so the failure above only skipped the "re-rendered" line. The loop
  graded 96 more transcripts across 58 cycles, never rebuilt the leaderboard,
  then exited 0 saying `COMPLETE: nothing left to grade`. Each stage now names
  its own failure with the last line of `grade_loop.err`, consecutive failures
  are counted, and a stale board exits 1. Guarded by
  `scripts/test_render_integrity.py`.
