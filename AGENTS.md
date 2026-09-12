# Verbatim Index — working agreement for agents in this repo

`CLAUDE.md` is a symlink to this file. One working agreement, whichever
tool reads it.

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
| `repo-1`, `repo-2`, … | Code, tests, docs, analysis. Read `data/` freely. Deploy with `scripts/deploy.sh`. One exception since 2026-09-10: the prediction pipeline (`extract_predictions.py`, `market_consensus.py`, `aggregate_predictions.py`, `validate_predictions.py`) writes under `data/predictions/` from any clone, because no loop touches that directory; the writer refuses every other path under `data/`. | Start any loop. Write under `data/` outside `data/predictions/`. Commit `data/`. |

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

Python 3.12 or newer: `llm-quota-router`, which `grade.py` imports to route
Fable calls by measured quota, requires it.

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
`results.json` is current, and `deploy.sh` stays read-only on `data/`. A failed
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

`GEMINI_USERS=tonyagents` adds a macOS user as a Gemini profile, which is the
only way to get a second Antigravity account on one machine. See the
Antigravity section for the three preconditions and why `sudo -u` alone fails.

`FABLE_ACCOUNTS` pins the Fable rotation to named accounts, for example
`FABLE_ACCOUNTS=default`. Use it when only some accounts can serve Fable.
Measured headroom cannot see paid usage credits: an account whose weekly
Fable window is 100% used reports 0.00 remaining whether or not credits let
it keep answering. Without the pin, `grade.py` rotates over every account and
each job that lands on one without credits fails with `auth_or_quota`.
Anthropic enforces the monthly credit cap server-side, so an unattended run
stops on its own rather than overspending.

## The third judge: Gemini 3.8 Flash via Antigravity

Added 2026-09-07, backfilled over the whole corpus, and **published on
2026-09-08**. `SHADOW_JUDGES` is now empty; it stays in `aggregate.py` because
the next arm will need it.

What promoting it cost, measured on one frozen snapshot with the arm shadowed
and then published: 34 of 40 leaders change rank, mean 1.45 places and at most
5, and the mean score moves 2.08 points with a maximum of 4.10. Jeff Bezos moves
furthest, 2nd to 7th, which is expected rather than alarming: the subject-share
filter already removed 81% of his material, so he is scored on the least
evidence of anyone on the board and is the most sensitive to a new judge.

It was held in shadow until the backfill finished, because a new judge changes
the judge MIX per leader and an uneven mix is the one thing `calibrate()` cannot
repair. While shadowed the exclusion was verified the same way: 40 leaders
compared, 0 changed, the published block byte-identical.

Its gates at promotion, from `diagnostics.shadow_judges`: spread 14.8 / 17.0 /
17.3 across the three dimensions against a floor of 3.0, so `calibrate()`
rescales it rather than passing it through; and it sits +1.85 from Astra and
+6.86 from Fable on paired transcripts, consistent with the ordering already
recorded here. `BLIND_JUDGES` in `grade_loop.sh` now names all three, because a
new transcript graded by a subset would reintroduce the uneven mix and widen it
every cycle.

Two profiles are in rotation, and they are of two different KINDS:

| Profile | Account | How the call is made |
|---|---|---|
| `/Users/tonygwu` | tonygwu@gmail.com | `HOME=...` on the subprocess |
| `user:tonyagents` | gptwufamily@gmail.com | through the root-owned wrapper, in that user's login session |

`grade.py` records which account served each grade in
`telemetry.profile_identity`, read from that call's own log. VERIFIED
2026-09-11: one call through each profile returned SUCCESS and named a
different account.

An extra HOME under one macOS user is SKIPPED, loudly, and `agy-profiles` will
still list it. `~/.agy-homes/gptwufamily` is such a directory and is no longer
in the rotation.

**Two profiles do not mean two accounts.** MEASURED 2026-09-10: all 567 Gemini
grades in the corpus were served by gptwufamily@gmail.com, 282 through `~`
and 285 through the other HOME. `agy` keeps its credential in the macOS
Keychain under service `gemini`, account `antigravity`, one item per macOS
user, so both HOMEs read and refresh the same credential and the last refresh
decides the account for both. A `/login` under one HOME is overwritten by the
next refresh under the other; the operator's re-login of `~` as
tonygwu@gmail.com at 08:25Z lasted until 08:56Z. A second HOME on one macOS
user adds no quota. `grade.py` now prints `gemini_identities` at the end of
every run and warns when every profile served one address. A real second
account is a second macOS user, which has its own login Keychain, and
`grade.py` supports that as a profile of the form `user:<name>` listed in
`GEMINI_USERS`.

**`sudo -u <user>` alone does NOT work, and fails in a way that looks like a
login problem.** MEASURED 2026-09-11: with the sudoers rule correct and the
binary readable, the call still returned `authentication failed or timed out`,
and its log said `You are not logged into Antigravity` followed by
`consumerOAuth: starting OAuth flow`. A process started from another user's
terminal sits in the wrong macOS security session, so the target user's
Keychain is unreachable and the judge concludes it has no credential. The fix
is `launchctl asuser <uid>`, which places the process in that user's login
session; the same call then answered and logged `ChainedAuth: authenticated
via keyring`. That belongs in a root-owned wrapper, `scripts/agy_as_user.sh`,
installed to `/usr/local/libexec/agy-as-user`, because `launchctl asuser`
needs root and the judge must then drop back to the target user.

Three preconditions, all named by the pass before it queues a job:

1. The judge binary sits outside any home directory. A home is mode 700, so
   `/Users/<you>/.local/bin/agy` is unreadable to the other user and the call
   dies with `unable to execute ...: Permission denied`. Copy it to
   `/usr/local/bin/agy`, and repeat that copy after an Antigravity update.
2. The wrapper is installed and has one sudoers rule:
   `<you> ALL=(root) NOPASSWD: /usr/local/libexec/agy-as-user`.
3. The target user is logged in, through Fast User Switching, so its login
   Keychain is unlocked. Log that user out and every call routed to it fails.

The jail for such a call lives under `/Users/Shared/verbatim-index-judge`,
because TMPDIR is per user and not traversable by another. A directory created
there inherits group `wheel`, which the operator is not in, so `chmod 2775`
on it fails with EPERM; the jail is re-grouped to `staff` first. Guarded by
`scripts/test_gemini_user_profile.py`.

**There is no quota measurement, and there cannot be.** `agy` exposes no usage
subcommand and writes no quota field to disk, so `llm-quota-router` reports both
Antigravity pools with `confidence=0.0` and `quotapick status` prints
`snapshot carries no usage windows`. The rotation is therefore plain
round-robin. Unlike the Fable arm there is nothing to order by headroom, and
inventing an ordering would send every call to an exhausted pool. A stop shows
up as `auth_or_quota` in the taxonomy, carrying the CLI's own reset wording.

Running the backfill, separately from the loop so a quota stop is attributable:

```
.venv/bin/python scripts/grade.py --transcripts data/transcripts_blind \
    --roster data/roster/final.json --out data/grades \
    --judges gemini --modes blinded --repeats 1 --workers 4 --timeout 2400 \
    --errors data/logs/grade_errors_gemini.jsonl
```

`bash scripts/status.sh` shows backfill progress and both account identities.
Once it reaches the full corpus, read `diagnostics.shadow_judges` before
promoting: `backfill_complete`, then `calibration_readiness` per dimension
(`would_be_rescaled` needs sd >= 3.0 and at least `MIN_CALIBRATION_N` grades),
then `vs_fable` and `vs_astra` for paired agreement. Promotion is deleting the
name from `SHADOW_JUDGES`, deliberately a diff rather than a flag. After that,
set `BLIND_JUDGES=fable,astra,gemini` on `grade_loop.sh` so new transcripts keep
the mix even.

## Rules that exist because something broke

- **A judge's `identity_guess` is read, not just stored.** MEASURED 2026-09-10:
  31 recordings on the board were a different person from the leader they were
  filed under, and on every one at least two judges had named the real speaker
  in `identity_guess`: "Eugene Wei", "Adam Dell", "Mario Draghi", "Sebastian
  Mallaby". Astra wrote "This record must not be aggregated" inside one grade,
  and it was aggregated. The subject-share filter cannot catch these because it
  asks whether SOMEONE is speaking. `scripts/wrong_person_screen.py` classifies
  every guess against the roster and flags a recording when two judges disagree
  with the label or two judges put share at 0; it reads no transcript text and
  spends no quota. 44 flagged, 0 false positives on hand review, 0 misses in a
  seeded sample of 40. Run it after each pass; a new flag should stop the render
  the way a failed render does. The matching traps it guards are in its test:
  "Dell" is also a company, "Clément" is "Clem", "the DJ, not the Epic Games
  founder", and a guess that opens with the real speaker and then names the
  leader.
  The screen is the DETECTOR, not the fix; the cause is under "Discovery still
  matches on the surname alone" in Known limits. Two shapes it catches that a
  simple "do the judges agree with the label" test does not: the leader can be
  the INTERVIEWER, as in `alexandr-wang/cohere-u8fjas`, where the speaker is
  Aidan Gomez and one judge wrote "interviewed by Alexandr Wang of Scale"; and
  the speaker can be a genuine NAMESAKE, as in
  `eric-schmidt/the-letterman-podcast--c4juv`, a standup comedian of that name,
  where one judge hedged "possibly Eric Schmidt". A labelled fixture of those
  cases is `scripts/test_wrong_person_regressions.py`. RUN 2026-09-11 after the
  withdrawals: 664 recordings screened, 0 flagged, 0 on the board, with 35
  recordings on the softer R3 review list that a human still reads.
- **Withdrawals go through a manifest and a guarded tool.** A retirement is a
  rename in `data/`, which only repo-0 writes. `scripts/withdraw_sources.py`
  takes a manifest such as `docs/withdrawals-2026-09-10.json`, dry-runs by
  default, refuses `--apply` unless `data/.daemon-clone` names the clone it runs
  from, and reports every entry as done, skipped or failed. `retire` renames the
  source to `.superseded`, the name the fetcher already honours, and the next
  grade-loop normalize prunes the derived copies and orphans the grades;
  `regrade` orphans the grades and keeps the source, for a transcript whose
  derived text changed under an existing grade.
- **The year the judge is told comes from the recording.** FOUND 2026-09-10:
  every manifest row said 2024 because `sources_to_manifest.py` defaulted a
  missing year with `or 2024`, and the fetcher copied it into every record
  while already holding `yt_upload_date`. 479 of 535 dated transcripts read
  "Approximate year: 2024" against uploads from 2009 to 2026, and 29 Happyscribe
  records read "Approximate year: 0". `declared_year()` in the fetcher now takes
  the upload date first, and `grade.py` prints "unknown" for 0. MEASURED with a
  controlled re-grade (docs/CORPUS-INTEGRITY-FOLLOWUP.md, section 1): the true
  year moves a grade -0.7 points (se 0.4, n=18) and a leader at most 0.2, inside
  Fable's own re-run drift, so the corpus was not re-graded. A default that
  silently invents a value is the accept-and-guess this repo forbids, and this
  one reached every judge on every grade for four days.
- **Never call the judge through `cl`.** It injects
  `--dangerously-skip-permissions`, which gives the judge tool access to this
  repository, including the roster it is blinded against. `grade.py` uses
  raw `claude` with `--permission-prompts none` and refuses `--fable-bin cl`.
  Account routing comes from the `quota_router` library, not the launcher.
- **Never derive time from file mtime or the local clock.** Read
  `fetched_at_utc` out of the record. Loops touch files constantly.
- **Never hand-type the judge list in a diagnostic.** Derive it from the grades
  present. `judge_call_counts`, `judge_raw_means_blinded` and the pairwise
  agreement were all written out as fable-plus-astra. Gemini left
  `SHADOW_JUDGES` on 2026-09-08 and contributed 512 blinded grades to published
  scores, and all three diagnostics kept reporting two judges for two days. The
  leaderboard was correct the whole time and its evidence was not, so anyone
  auditing whether the promotion took effect would have concluded the arm was
  still shadowed. There is no longer a key naming one pair `_overall`: that name
  is what let a single pair stand in for the panel. `judge_pair_agreement`
  reports every pair with its own `n`, and `mean_pairwise_correlation` is the
  one panel-level figure. Guarded by `scripts/test_judge_enumeration.py`, which
  runs a four-judge fixture as well as a three-judge one.
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
- **A retirement must be visible to EVERY fetcher.** The sweep renames a source
  to `<source_id>.json.superseded`, which `dest.exists()` does not match, so
  the fetcher re-downloaded it every cycle and the sweep retired it every
  cycle. `fetch_one` now honours that name, and reports the skip as its own
  `superseded` category rather than letting the tally stop adding up.
  The same rule arrived on the SECOND fetcher on 2026-09-10. `withdraw_sources.py`
  retires by that same rename and YouTube honoured it, but the Happy Scribe path
  never looked at the marker, so `dedupe_transcripts.py --merge` re-created the
  live copy on the next cycle. OBSERVED: four sources sat as both `<id>.json`
  and `<id>.json.superseded` at once, and the withdrawal manifest reported them
  actionable again within the hour, so the ledger read as a command repo-0 had
  failed to run rather than as a bug. The marker is now read twice, once at the
  decision stage, which records a `withdrawn` verdict with action `none`, and
  once immediately before the write, because a withdrawal can land between the
  two. `prune_orphans` re-reads for the same reason. The hold is counted as
  `withheld_already_withdrawn`, never skipped silently, because silence is how
  this hid. Guarded by `scripts/test_hs_withdrawal.py`, 9 checks, verified
  failing 4 of them against the pre-fix code.
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
- **Outputs that cross clone boundaries are written atomically.**
  `data/results.json`, its audit file and `site/index.html` go through
  `scripts/atomicio.py`. `Path.write_text` truncates first, so a clone
  deploying while the grading loop rewrites results.json would read a prefix.
- **Nuisance effects are estimated and subtracted, not assumed away.**
  `calibrate()` does it for judges, `venue_effects()` for the format of the
  appearance. Both fit the effect with the other factor held fixed, because raw
  means confound the two: leaders are not spread evenly across venues, so the
  raw 8.2-point spread across formats is only 5.7 once the speaker is held
  fixed. Fitted per dimension, since the score is a weighted sum of the three,
  and the bootstrap interval reads the same adjusted values as the point
  estimate or the dot lands outside its own bar.
- **An account's identity is read from the call that ran, never from the newest
  file by mtime.** `agy` writes one log per invocation into a shared directory,
  and a profile keeps its old logs when it is renamed or reused. Sorting that
  directory by `st_mtime` named the WRONG account on 2026-09-07: a log from a
  previous account sorted newest because the file had been touched, not because
  it was written last. `grade.py` passes `agy --log-file` so each call names its
  own log, and `agy_identity_from_log()` reads exactly that path. Where no call
  is available to attach to, as in `status.sh`, order by the timestamp IN the
  filename. This is the standing mtime rule arriving in a new place.
- **For `agy`, the token file is not the credential.** The default profile
  authenticates from the macOS Keychain (`svce="gemini"`, `acct="antigravity"`)
  and answers normally with `antigravity-oauth-token` deleted outright. Swapping
  those files to swap accounts is a no-op; changing the account means `/logout`
  and `/login`. The log line that says which path was used is
  `ChainedAuth: authenticated via keyring (effective: keyring)`.
  Separately, `~/.gemini/antigravity-cli/conversations/` is SHARED with the
  Antigravity IDE, whose language server holds open SQLite handles there, so
  that directory must not be moved while the app runs.
- **"Try again" and "this account is spent" are different failures, and only
  `quota_router.failure_text` gets to tell them apart.** An OAuth refresh race
  between concurrent headless spawns arrives carrying a 429, and reading that as
  exhaustion benches a healthy account; that is recorded in the router as ~44
  spurious production failures. A first version of `classify_agy_failure` made
  exactly that mistake, filing both `Not logged in - Please run /login` and a
  bare 429 as quota stops. It now delegates, and consults its own patterns only
  where the router returns `unknown`, which is where provider-specific
  knowledge belongs: `RESOURCE_EXHAUSTED` is Google's quota code and the
  router's patterns are tuned to Claude and Codex wordings. Transient failures
  land in the taxonomy as `transient_retryable`, never as `auth_or_quota`.
- **A record that failed validation is not a grade, and nothing may read a field
  off one.** `load_grades` marks it `_excluded`, but the split acting on that
  mark used to run AFTER `filter_unscorable`. On 2026-09-09 Astra refused
  `tim-cook/the-bulwark-and-the-prof-zi07-f` and wrote a record whose `grade`
  held one key, `error`. Fable had scored the same recording at 0% subject
  share, so the whole recording fell under the cutoff and every grade for it
  reached the unscorable report, that record included, and `aggregate.py` died
  with `KeyError: 'subject_speech_share_pct'` on every cycle for the next 13
  hours. The split now runs first. A non-grade that validation did NOT catch
  stops the run with a message naming the file, never a default share, and the
  four buckets are checked to add up to the files read.
- **A render that failed must say so, and a loop may not report COMPLETE over a
  board it could not rebuild.** `grade_loop.sh` chained aggregate and build_site
  with `&&`, so the failure above only skipped the "re-rendered" line. The loop
  graded 96 more transcripts across 58 cycles, never rebuilt the leaderboard,
  then exited 0 saying `COMPLETE: nothing left to grade`. Each stage now names
  its own failure with the last line of `grade_loop.err`, consecutive failures
  are counted, and a stale board exits 1. Guarded by
  `scripts/test_render_integrity.py`.
- **Stage by name.** `git add -A` in a shared clone sweeps in another agent's
  untracked work.
- **Data commits happen inside `data/`.** The root repo is public; nothing
  under `data/` may be committed there. `git -C data add <paths>` and
  `git -C data push`, from `repo-0` only.

## Measurement decisions, and why

These change the published number. Each was measured before it was chosen, and
the measurement is named so a later reader can re-run it rather than trust it.

- **The roster is 50 people, and `longform_availability` means two different
  things.** It was 40 until 2026-09-10, when C.C. Wei was withdrawn and eleven
  were added: Tobi Lütke, Michael Saylor, Eric Schmidt, Ilya Sutskever, Aaron
  Levie, Dylan Field, Amjad Masad, George Hotz, Greg Brockman, Vlad Tenev and
  Alexandr Wang. Any figure in this file that says "of 40" is a record of a
  measurement taken on the smaller board and is left alone; re-running it today
  would give a different number. `docs/ROSTER-EXPANSION-2026-09-10.md` carries
  the selection reasoning, including why Marc Andreessen and Garry Tan are still
  out.
  The field trap is `longform_availability`. It now holds ONE measured quantity
  for all 50: the number of long-form YouTube results that pass
  `discover_sources`' own duration, clip and third-person filters AND an
  identity screen wanting the full name, or the surname together with a company
  token, in the title or channel. The old scout-estimate medians are preserved
  per person as `longform_availability_scout_median`, on the 39 that had one.
  **The two scales are not interchangeable.** RE-COMPUTED 2026-09-11 from
  `data/roster/final.json`: Pearson r is 0.74 over those 39, scout mean 74 on a
  7-200 range against measured mean 39 on a 19-65 range, and
  the measured scale is compressed because the search pool caps near 90 results.
  Read the field name before comparing two leaders. The identity screen is the
  part that earned its keep: C.C. Wei scores 20% purity on it and every other
  leader scores 83% or better, which is how the wrong-person class was sized.

- **A leader is not ranked below `MIN_TRANSCRIPTS_TO_RANK` included
  transcripts, and is kept and scored anyway.** Five, which is the
  high-confidence band, so the floor is one constant rather than a second number
  to keep in step. Below it the leader keeps every grade and every transcript
  and keeps a blinded score in `results.json` under `unranked`, but takes no
  rank and does not appear on the page. Asked for 2026-09-10, when the
  wrong-person withdrawal left C.C. Wei with 2 real transcripts: a
  two-transcript row is a placeholder and the board should not carry it as a
  score. `diagnostics` carries `min_transcripts_to_rank` and `leaders_unranked`,
  `coverage_table.py` still shows an unranked leader's score, and the page
  explains the floor from the constant instead of a typed number. Guarded by
  `scripts/test_rank_floor.py`, 13 checks. On the corpus today the floor binds on
  nobody: `min_transcripts_to_rank 5`, `leaders_unranked []`, 50 of 50 scored.

- **Per-judge calibration.** `calibrate()` maps each judge's score distribution
  onto the pooled one, per dimension, and only when that judge's spread is
  meaningful (`sd >= 3.0`), because rescaling a flat judge amplifies noise.
  Fable currently runs 9.0 points below Astra on clarity, 4.9 on insight and
  2.4 on technical depth. What calibration cannot fix is an uneven judge MIX
  per leader, so watch `judge_call_counts` when a quota window closes. Gemini
  runs above Fable on every dimension and above Astra on insight and technical
  depth. Measured 2026-09-10: raw insight means are Fable 56.0, Astra 60.9,
  Gemini 61.8. Pairwise agreement on the overall score is Astra-Fable 0.895,
  Fable-Gemini 0.869, Astra-Gemini 0.848.

- **Calibration is MARGINAL, and a residual judge-by-length effect survives it.**
  `calibrate()` matches each judge's whole-corpus distribution to the pooled one,
  so it removes a constant offset and a spread difference. MEASURED 2026-09-09 on
  the 470 complete cases: after calibration the residual judge effect is
  essentially zero on the 336 transcripts under 15k words (all three within 0.05
  on `d2_insight`). It is NOT zero at the top end. On 25k-40k transcripts Gemini
  sits about -0.93 points below the three-judge mean, weighted across dimensions,
  and the other two sit above it.

  A single global mean and sd per judge cannot absorb a slope against transcript
  length, which is why this survives. The practical size is small: dropping
  Gemini from a long transcript raises it ~0.47 points, so a leader's score moves
  by that times their share of long transcripts, at most +0.18 for
  brian-armstrong. Against a board where no adjacent pair separates at 95%, that
  is noise. Left uncorrected on those grounds, with n=26 in the top band making
  -0.93 an upper bound.

  Worth knowing for whoever next touches this: `venue_effects()` fits an ADDITIVE
  model and estimates the nuisance effect with the speaker held fixed, which is
  the conditional treatment. `calibrate()` does the marginal one for judges. The
  repo therefore holds itself to a higher standard for venue than for judges. The
  natural upgrade is a two-way `score ~ transcript + judge` fit, which handles
  unbalanced judge coverage natively. Not done, because the measured residual
  does not justify re-deriving 2,000 grades.

- **Venue adjustment.** `venue_effects()` fits an additive leader-plus-venue
  model and subtracts what the FORMAT is worth with the speaker held fixed.
  Leaders are not spread evenly across formats: some are entirely long-form
  podcast, others never appear on one, so raw means confound the two. Measured
  2026-09-07: raw spread across venue types 8.2 points, spread with the leader
  held fixed 5.7 (podcast +3.9, keynote -4.1 on insight). 23 of 40 leaders
  change rank, mean 1.2 places, max 7. Fitted per dimension, because the score
  is a weighted sum of the three; adjusting only the composite would leave the
  dimensions, the score and the interval disagreeing. A venue seen fewer than
  `MIN_VENUE_N` times gets exactly zero rather than one transcript's noise.

- **Subject-speech cutoff is 10%, decided per transcript.** Below this share of
  the words the subject is not really in the recording and the grade describes
  somebody else. MEASURED on 785 blinded grades: the distribution is bimodal.
  47 grades sit at 0-4%, a near-empty band of 3 grades spans 5-9%, then a
  continuum runs from 10% upward (16, 14, 9, 11, 26, 30, ...). The old value of
  15 cut through that continuum, leaving 37 grades within five points of the
  line, so small changes reshuffled who was included. 10 sits in the empty band,
  which makes the cutoff describe the data rather than round a number.
  The decision is made once per RECORDING, on the mean of whatever judges
  estimated it. It used to be per grade, so one judge saying 14% and the other
  16% dropped one and kept the other, silently turning a two-judge transcript
  into a single-judge one, which `confidence` then penalised for an unrelated
  reason. Judges agree closely about share: median absolute disagreement 2
  points, mean 3.6. A grade with no estimate is kept, never guessed at.

  **A zero from any judge drops the recording, whatever the mean.** MEASURED
  2026-09-10 on 558 recordings: 10 were on the board with one or two judges at
  0 and another judge at 42 to 86, and all 10 were subject-absent on
  inspection. The high judge had scored the host, a co-guest or a biographer
  and said so in its own notes; Gemini reports the share of the DOMINANT
  speaker, not of the named subject. A mean cannot express "the subject is not
  here". Under this rule 0 of the 10 survive; a median keeps 4. It drops 10
  recordings and moves Jeff Bezos from 7th to 2nd, because two of his three
  subject-absent recordings had scored their hosts at about 40 points.

- **A refusal is retried on the same model, three times, and that is all.**
  Astra refuses some politically-charged transcripts. MEASURED: the refusals are
  NOT deterministic. A controlled re-run of three found it graded two of them
  the second time, same transcript and byte-identical prompt; only
  `alex-karp/the-free-press-qdqhf7` refused twice.
  There is deliberately NO fallback to a second model. Such grades could not be
  calibrated: there would only ever be a handful, far below
  `MIN_CALIBRATION_N`, so they would enter the leaderboard unrescaled and about
  six points high, and only on the leaders where refusals concentrate. A grade
  that cannot be calibrated is not worth having, so the call is not made.
  A refusal WRITES its grade file and `grade.py` skips any transcript whose dest
  exists, so refusals already on disk never retry until those records are
  removed. That is a `data/` operation, and therefore repo-0's.
  Calibration is still keyed by `(judge, model, mode, dim)`, because a judge
  whose model is BUMPED mid-corpus is the same hazard arriving another way, and
  `diagnostics.judge_models` warns when one judge served more than one model.
  Note that `codex --json` reports no model anywhere in its response, so
  `served_model` records what was REQUESTED; it is not independently verified.

- **Nothing load-bearing may depend on Python's hash seed.** FOUND by running
  `aggregate.py` twice over a frozen grades directory and getting 36 different
  leader scores. Per-transcript venue was picked with
  `max(set(votes), key=votes.count)`, and string hashing is randomised per
  process, so the winner of a TIE changed between runs. 42 transcripts have the
  judges disagreeing about venue and every one is a one-vote-each tie. Harmless
  while venue was display-only; the venue adjustment made it move the published
  score. `resolve_venue()` sorts before the max and reports whether there was a
  real majority, and the adjustment is applied only when there was. A tie means
  the format is unknown, not resolved.

- **Confidence interval by bootstrap.** A leader's score is a coverage-weighted
  mean over the transcripts we happened to collect, so it carries sampling
  error, and a leader on 3 transcripts carries far more of it than one on 14.
  20,000 resamples of that leader's transcripts with replacement, seeded so
  published endpoints do not drift between runs. Calibration is held fixed
  rather than refitted inside each resample, which would mix corpus-level and
  leader-level uncertainty into one interval; `diagnostics.bootstrap` records
  that choice. The interval reads the SAME adjusted values as the point
  estimate, or the published dot lands outside its own bar.
  What it shows, RE-MEASURED 2026-09-11 on the 50-name board in
  `data/results.json`: 1 of 49 adjacent pairs separates at 95%, and it is the
  last one, rank 49 Tim Cook [43.4, 50.4] against rank 50 Marc Benioff
  [35.6, 39.8]. Every other neighbouring pair overlaps. The board distinguishes
  the top from the bottom, over a 75.7 to 37.9 span, and does not distinguish
  rank 9 from rank 12. The earlier reading of this was 0 of 39 on the 40-name
  board, so growing the roster moved the count by one pair and changed nothing
  about the conclusion. The companion figure quoted elsewhere in this file, a
  median rank range 13 places wide, was measured on that 40-name board and has
  not been re-derived on 50; `results.json` carries no `rank_range`, so it needs
  its own pass.

- **Subject share still predicts the score, and is deliberately NOT corrected.**
  Holding the leader fixed, a transcript where the subject speaks 15-49% scores
  3.4 points below that leader's average and one at 80-100% scores 2.3 above,
  5.7 points end to end. It is a penalty rather than regression toward the mean:
  both strong leaders (-3.8) and weak ones (-2.7) fall on low-share transcripts,
  where regression would have pushed the weak ones up. Left uncorrected because
  less subject speech is genuinely less evidence, so a lower score on it is
  defensible, unlike venue, which says nothing about the quality of thinking.
  Correcting something not understood is worse than leaving it visible.

## Experiments run, and what they showed

These settled questions that guesswork would have got wrong. Each is recorded
with its method, because the conclusions are only as good as the setup and a
later agent should be able to challenge them. The count is deliberately not
written out here: it said "Four" while eleven stood below it.

**Are the graded transcripts really unique?** (2026-09-07) Compared every pair
within each leader in `data/transcripts_blind` on 5-gram containment, the same
measure `dedupe_transcripts.py` uses. 23 pairs scored above the 0.40 threshold
and nothing landed in the grey band, so the split was clean. 10 duplicate
appearances across 10 leaders; Reed Hastings' Greylock talk appeared three
times and moved him 3.2 points and four ranks. `dedupe_transcripts.py` was not
at fault: it had scored every one of those pairs correctly. Two other defects
let them through, both now fixed and guarded.

**Can blinding be made to work?** (2026-09-07) Built five progressively harder
redactions of one transcript, from the shipped name-and-company blinding up to
183 removed spans with no company, product, colleague, place or year left, then
asked both judges to name the speaker at each level. Ten calls, ten correct, ten
confident, replicated on a second leader. Redaction was mechanical, by script,
so the prose was unchanged; a model proposed the entity list and never rewrote
the text. CONCLUSION: identity leakage is not fixable by more redaction. What
survives is the argument, not the nouns — a distinctive strategy, a program of a
stated age, a public position taken against a named rival — and that is exactly
what the rubric grades. Fable also reconstructed redacted words and presented
them as quotes, so the model recognises the EVENT, not just the entities.

**Do the judges have tools?** (2026-09-07) Asked each judge directly, with the
production flags, for something it could not know from training. Fable is
offered `WebFetch`, `WebSearch` and `Bash`, tries all three, and every one is
denied; `web_search_requests: 0`. Astra answers "YES — web.run" and was observed
searching and citing a page that named the blinded subject. Do not infer this
from flags: `-s read-only` restricts the filesystem, not the network, and five
candidate config keys failed to disable it.

**Are the content refusals deterministic?** (2026-09-07) Re-ran three refusing
transcripts under `gpt-6-astra` at production settings, verifying that the
rebuilt prompt was byte-identical to `build_judge_prompt`'s output before
trusting anything. Two of three graded on the re-run. This is sampling variance
on a borderline judgement, not a hard content block, which is why the fix is a
retry rather than a second judge.

**Can the Gemini judge's web search be turned off?** (2026-09-07) No, and the
answer is structural rather than a matter of finding the right flag. Asked
directly with the production flags, the judge ran `search_web` and reported that
it succeeded. A `permissions.deny` block naming the tool five different ways was
read by the CLI and then rejected entry by entry:
`ignoring invalid deny entry "search_web": invalid grant string` and
`unknown action "search_web" in grant string: "search_web(*)"`. The binary
carries `unknown action %q, want %q, %q or %q`, so the grant vocabulary is three
actions wide plus `mcp`, and builtin tools are not in it. Network-level blocking
does not help either, because the search runs behind the model rather than from
this client. Filesystem access IS confined: a read outside the working directory
returns `permission check failed for read_file` and lands in `denied_actions`.
The settings file was restored byte-identical afterwards, verified by sha256.

Two things worth inheriting from this. The CLI SILENTLY DROPPED the invalid
entries when it next wrote the file, so a rule that looks accepted because it
persisted may simply not have been rejected loudly. And a denied tool can end a
turn with `status: SUCCESS` and an EMPTY response, which `call_gemini()` now
raises as `empty_response` rather than writing a silent non-answer as a grade.

**How much does a judge disagree with ITSELF?** (2026-09-07) Nobody had ever
measured it: the whole corpus is `--repeats 1`, so every grade was implicitly
treated as a fixed value. Eight transcripts spanning eight leaders and 3.1k to
27.9k words, three repeats each, all three arms, against a frozen copy of the
corpus rather than the live one.

| arm | transcripts | runs | mean spread | max | within-transcript sd |
|---|---|---|---|---|---|
| astra | 7 | 17 | 1.28 | 2.0 | 0.60 |
| gemini | 6 | 12 | 2.30 | 4.1 | 1.15 |
| fable | - | - | - | - | not measured |

Gemini is about twice as noisy as Astra on a re-run. Both are small next to what
the board can resolve: re-run noise averages down into a leader's score by
sqrt(n), giving +/-1.30 at 95% for a 3-transcript leader on Gemini and +/-0.60
at 14, against a median rank range of 13 places.

Three caveats, each of which matters more than the headline. The Gemini figure
is optimistically biased, because the transcript with the worst observed
variance is the one that failed most often and dropped out of the pairs. Fable
produced no repeatability data at all: 17 of its 24 calls returned
`auth_or_quota` because its weekly window was nearly spent, so no transcript got
two Fable runs and the three-way comparison is really two-way. And Astra failed
schema validation three times here, so the quote-cap overrun is not unique to
the new arm; Gemini is roughly three times worse at it, not alone in it.

**Is the agy empty-answer failure deterministic?** (2026-09-09) No. Parsed the
failure set out of five separate Gemini passes in `data/logs/gemini_backfill.log`
and compared them. 25 transcripts failed at least once; **0 failed in every pass
they were attempted in**. Consecutive passes recovered 4, 4 and 10 transcripts,
the last being 10 of 14. Costs nothing to re-derive: the passes are all in that
log, so this needs no new grading calls.

The mechanism explains the result. agy ends a run when a tool is auto-denied,
and whether the model reaches for a tool is sampled, not fixed. Length raises
the odds without forcing the outcome, which is why the failures concentrate on
long transcripts and still move between passes.

This is the second time in this repo that a repeated failure was mistaken for a
deterministic one, after the Astra refusals. The general lesson is cheap to
apply: before recording a failure as a limit, check whether the SAME items fail
every time, not merely whether the same NUMBER does.

**How much do the three judges agree on ORDER?** (2026-09-09) Rank agreement,
on the 470 transcripts all three graded (complete cases, refusals excluded --
note a refusal writes a grade file with `{reason, status, transcript_id}` and no
scores, so filtering on `validation_errors` alone does not catch them).

Ranks are the right instrument because Spearman and Kendall are invariant to any
monotonic per-judge transform, and `calibrate()` applies a LINEAR rescale. So
these numbers measure disagreement about ORDER, independent of the offsets
calibration already removes. Pearson on raw scores conflates the two.

| pair | Spearman | 95% CI | Kendall tau-b | agree on a random pair |
|---|---|---|---|---|
| fable <> astra | 0.899 | [0.876, 0.917] | 0.729 | 86.5% |
| fable <> gemini | 0.878 | [0.848, 0.901] | 0.701 | 85.1% |
| astra <> gemini | 0.863 | [0.832, 0.887] | 0.679 | 84.0% |

Kendall W across all three at once is 0.920. Gemini is NOT an outlier: the whole
spread across the three pairs is 2.5 percentage points. A paired bootstrap on the
same resamples separates only one comparison, fable<>astra minus astra<>gemini at
+0.036 [+0.012, +0.062]; fable<>gemini is indistinguishable from the incumbent
pair.

Per dimension the pairing structure CHANGES, which the overall number hides.
Clarity is the weakest-agreed dimension for every pair (W 0.868) and is the one
where Gemini sides with Astra (0.805) over Fable (0.780). On technical depth
Gemini<>Fable (0.880) slightly exceeds Fable<>Astra (0.875). Clarity being worst
is corroborated independently: it is also where Fable and Astra differ most in
LEVEL, at 9.0 points. That points at the rubric's clarity criteria being the
least well specified, rather than at any one judge.

**Do agy and cursor-agent grade the same, and can they be mixed?** (2026-09-09)
No. Tested because cursor-agent runs `gemini-3.8-flash-high` without hitting the
agy headless bug, which made a hybrid tempting: agy for short transcripts,
cursor for long ones.

Paired on identical transcripts, n=6 in the 24k-33k word band where a hybrid
would actually deploy: mean signed difference **-4.45** points (cursor lower),
sd 4.35, 95% CI [-9.01, +0.11], negative in 5 of 6. Not significant in
isolation, and three things still point one way: the direction is consistent,
the divergence concentrates in `d2_insight` which carries weight 0.45, and the
weighted per-dimension differences reconstruct the overall mean. A first n=3
spanning all lengths gave mean abs 4.23 and would have looked merely marginal;
restricting to the deployment regime is what made it legible.

Impact had it shipped: Elon Musk -1.37 points, Palmer Luckey -1.03, landing only
on long-form-podcast leaders. Cursor also fails the 25-word quote cap at a
similar rate, so it fixes nothing there. Subject-share agrees closely between
harnesses, so both read the same recording; this is a scoring difference, not
comprehension. The test does not say which harness is closer to truth. It says
they are not exchangeable, which is all a hybrid needed them to be.

**Does the wrong year move the score?** (2026-09-10) No, not enough to see on
the board. 18 transcripts spanning offsets of -15 to +2 years, three arms per
transcript and judge: the on-disk grade, a fresh control with the identical
prompt, and a fresh call whose prompt differed by exactly the year line. True
year minus control: -0.73 pooled, se 0.39, t -1.87, MDE 1.10 at 80% power;
Fable -1.0, Astra -0.3, Gemini -0.9; same sign in both upload strata. Substituting
the 18 true-year grades into the board moved no leader more than 0.2 points or
one place. Full tables in docs/CORPUS-INTEGRITY-FOLLOWUP.md.

The control arm measured Fable's re-run noise for the first time: sd 3.24
within transcript, twice Astra's 1.53, and a MEAN shift of +2.44 (se 0.76)
against grades 1 to 4 days old. That is drift, larger than the effect the test
was built to find, and it is not explained. Gemini's re-run sd was 4.30 on 13
transcripts, against 1.15 measured on six.

**Does paragraph-scale looping move the grade?** (2026-09-10) No. The 8
transcripts over 20% repeated, collapsed and re-graded by all three judges
against their on-disk grades: Fable +1.2, Astra +1.6, Gemini -1.7 on five,
pooled +0.65 (se 0.70). The judges had already read through the replays and
said so in their notes. What the loop costs is quota and Gemini's retry budget:
every judge read all 64,068 words of the worst one on every call, and the
collapse cuts it to 1,803.

**Method notes worth inheriting.** Two of these nearly produced wrong answers,
and both times the cause was the same: comparing against a moving target. The
grading loop writes continuously, so any before-and-after measured against
`data/` mixes the change under test with new grades. Copy the corpus once and
run both arms against the snapshot. Separately, a raw group mean is almost never
the effect you want here, because leaders are not randomly assigned to venues,
formats or judges; fit the nuisance factor with the other held fixed, and expect
the honest effect to be smaller than the raw one. The venue effect fell from 8.2
points to 5.7 that way.

## Known limits of the published score

Documented rather than fixed, deliberately. Changing any of these now would make
new grades incomparable with the corpus already graded.

- **Discovery still matches on the SURNAME alone, so recordings of other people
  keep entering the corpus.** This is the largest single cause behind the
  wrong-person rule above, and it is unfixed. `name_in()` in `discover_sources.py` takes
  `person["name"].split()[-1]`, lowercases it, accepts a bare substring hit in
  the title OR the channel, and then also accepts any 4-letter-or-longer token
  within a 0.85 `SequenceMatcher` ratio of it. Nothing checks the given name and
  nothing checks the company. VERIFIED 2026-09-11 by importing the live
  function: `name_in("Eugene Wei on tech and taste", {"name": "C.C. Wei"})` is
  True, and so is the racquetball champion Tim Sweeney and the standup comedian
  Eric Schmidt.

  What that cost, MEASURED 2026-09-10 (`docs/CORPUS-INTEGRITY-2026-09-10.md`,
  `docs/CORPUS-INTEGRITY-FOLLOWUP.md`): 44 wrong-person recordings in the
  corpus, 31 of them live on the published board. C.C. Wei was the worst and was
  removed from the roster over it. 14 recordings were fetched under his slug and
  only 2 mention TSMC at all; the other 12 are Jing Wei, Eugene Wei, Zhang
  Weiwei, Weivy Wei, Han-Wei Shen, Linwei Wang, Wei Chen twice, William Wei, Sha
  Xin Wei, Wei Li of Intel and Lord Nat Wei. Tim Sweeney carried a DJ, a
  racquetball champion and a SoFi retail investor. PROJECTED before the
  withdrawal, on the 40-leader board and over all 31 cases: Tim Sweeney rank 13
  to 3 and 65.2 to 72.7, Jeff Bezos 7 to 2, 26 of the 40 leaders changing rank
  (`docs/CORPUS-INTEGRITY-FOLLOWUP.md`).
  MEASURED when the sweep actually ran, 2026-09-11T05:50Z, comparing the board
  immediately before and after on the 50-leader roster: Tim Sweeney rank 17 to 4
  and 64.5 to 71.7, 46 of 50 leaders moving but 44 of them by 0.1 to 0.4 points,
  which is calibration reacting to a changed pooled distribution rather than a
  change in anyone's evidence. Lip-Bu Tan went the other way, 40 to 46 and -2.7,
  because his removed Mario Draghi transcript had scored ABOVE his own average.
  The two sets of numbers are kept apart on purpose: the first is a projection
  over a board that no longer exists, and quoting it as the outcome is the kind
  of thing this file exists to stop.

  The corpus review named two failure modes in source selection, and a third
  turned up later. SURNAME COLLISION, 13 cases, where the title names a
  different person whose surname matches: every C.C. Wei entry, Adam Dell under
  `michael-dell`, the Beats in Space DJ under `tim-sweeney`. "ABOUT the subject"
  mistaken for "BY the subject", 2 cases, such as two hosts discussing Bezos.
  And the leader NAMED IN THE TITLE but not the speaker being graded, which
  `name_in()` waves through legitimately: Jensen Huang under `lisa-su`, all
  three judges naming him; Demis Hassabis under `yann-lecun`, where LeCun never
  appears; Vitalik Buterin under `brian-armstrong`; Mario Draghi under
  `lip-bu-tan`; Riccardo Biasini of comma.ai under `george-hotz`; Sundar Pichai
  under `marc-benioff`, where Benioff is the host. The Eric Schmidt standup
  comedian is a fourth shape again, a genuine NAMESAKE carrying the full name.
  The subject-share filter catches NONE of them, because somebody is speaking
  throughout and the share comes back high: three of C.C. Wei's read 100, 94 and
  92 with maximum judge agreement.

  Not fixed here because a tighter gate rejects real material as well, and both
  sources are currently exhausted so no discovery run is pending to exercise a
  new rule. The roster expansion measured the alternative rather than arguing
  it: an identity screen wanting the full name, or the surname plus a company
  token, gives every surviving leader 83% purity or better and C.C. Wei 20%.
  Tighten `name_in()` toward that BEFORE the next discovery run, and keep
  `wrong_person_screen.py` running after every pass either way, because a screen
  that reads the judges' own `identity_guess` catches what a title cannot.

- **The blinder replaces ordinary English words, because an alias list carries
  bare parts of a company name.** `blind()` applies every entry in
  `data/sources/aliases.json` unconditionally, case-insensitively, through the
  NAME path, so the replacement token is `[SUBJECT]` and not `[COMPANY]`. The
  alias lists come from the discovery workflow and hold the parts of a
  multi-word company: `yann-lecun` has "Machine", "Intelligence" and "Labs" out
  of "Advanced Machine Intelligence Labs", `tim-sweeney` has "Games",
  `fei-fei-li` has "World", `clem-delangue` has "Face", `thomas-kurian` has
  "Cloud". `company_variants()` can do the same on its own path, and only
  `fuzzy_targets()` consults the system dictionary; neither the exact-form path
  nor the alias path does.

  MEASURED 2026-09-11 over `data/transcripts_blind`, taking every substitution
  whose token is a bare part of a multi-word company name and counting the
  LOWERCASE occurrences of that token in the matching unblinded file under
  `data/transcripts_open`. Lowercase, because that is the ordinary-prose use
  rather than the company reference, and the blinder's regex is case-insensitive
  so it takes both. Two readings, because the wide one is not all damage:

  ```
  any bare company part          2,976 occurrences  176 transcripts  20 leaders
  token also a dictionary word   2,038 occurrences  130 transcripts  15 leaders
  ```

  The wide figure includes "uber" 250 and "google" 109, which really are the
  company said in lowercase and are correctly removed. The narrow one is the
  floor, and its largest entries are "world" 453 for Fei-Fei Li, "machine" 300
  and "intelligence" 230 for Yann LeCun, "face" 225 for Clem Delangue and
  "cloud" 206 for Thomas Kurian. Add "games" 377 for Tim Sweeney, which the
  narrow measure misses only because `/usr/share/dict/words` holds no plurals.
  What the judge actually reads is `"the history of artificial [SUBJECT]"` and
  `"the experience of playing and creating video [SUBJECT]"`.

  Two reasons this is worse than the leakage it sits beside. The damage lands on
  exactly the domain vocabulary the rubric grades, so a game designer loses the
  word "games" and an AI researcher loses "machine" and "intelligence". And the
  token inserted is the one that means "the person being graded", so the judge
  reads an ordinary noun as a reference to the subject.

  `scripts/test_blinding.py` passes and cannot catch this. All five of its cases
  probe the FUZZY path for overreach, no case puts a common word in the alias
  list, and the one bare company part they do assert survives is "cloud", which
  `GENERIC_COMPANY_WORDS` already exempts by hand. The roster works around the
  defect per person in the one place it was noticed, recording Michael Saylor's
  company as "MicroStrategy" rather than its current legal name "Strategy",
  because `company="Strategy"` redacted the ordinary word "strategy" three times
  in an 80-word test paragraph. The reason is written into his
  `selection_rationale`. That is a patch on one name, not a fix.
  Left alone because re-blinding the corpus invalidates every grade already
  collected. Fix it when the grades are next re-derived, and note that a system
  dictionary alone is not enough, since it did not contain "games". The alias
  list is the place to intervene, because the discovery workflow is what put a
  bare company part in it.

- **HappyScribe discovery admits third-person shows that YouTube discovery
  rejects, and the corpus pays for them in judge calls.** `discover()` in
  `fetch_happyscribe.py` applies the same `THIRD_PERSON_TITLE` and
  `COMMENTARY_SLUG` filters as the YouTube path, and they are weaker against
  podcast episode slugs. MEASURED on 2026-09-11, from one re-discovery run
  against the 50-name roster: four admitted recordings were commentary ABOUT the
  subject rather than the subject speaking, and they were caught only by the QA
  `subject named` screen AFTER being graded.

  ```
  hs-sacha-baron-cohen-has-a-message-for-mark-zuc   subject named 12.3 /1000 (limit 1.6)
  hs-elon-musk-begins-training-for-zuckerberg-fig   subject named 12.3 /1000
  hs-charlamagne-tha-god-torches-the-democrats-we   subject named 13.9 /1000
  hs-live-jeff-bezos-rocket-new-glenn-attempting    commentary on a launch
  ```

  The shapes that get through are possessive and narrative rather than
  interrogative: "has a message for X", "begins training for X", "live: X
  attempting". The existing patterns look for the interview forms. Cost was
  about 15 judge calls across three judges before QA withdrew them, so this is
  quota rather than correctness: no third-person recording reached the board.
  A fifth was rejected separately at `oov_rate 0.6789` for being German, which
  the language gate catches and discovery does not.

  Not fixed, because both sources are currently exhausted and no discovery run
  is pending to exercise a new pattern. Fix it before the NEXT roster expansion,
  which is when discovery runs again and the cost repeats.

- **The blinding does not work, and the header still claims it.** Judges are
  confident of the speaker's identity on 99.5% of transcripts and are right
  99.6% of the time. An experiment on 2026-09-07 built five progressively harder
  redactions of one transcript, up to 183 removed spans with no company, product,
  colleague, place or year left, and both judges identified the speaker at every
  level, replicated on a second leader. What survives redaction is the argument,
  not the nouns: a distinctive strategy, a program of a stated age, a public
  position taken against a named rival. That is exactly what the rubric grades.
  Fable also reconstructs redacted words and presents them as quotes.
  `blind()` replaces only the subject's name and company, and nothing else.
  7 transcripts have ZERO substitutions and 80 have fewer than one per 1000
  words; `arthur-mensch/no-priors-ai-machine-lea-emofrd` got 3 in 6044 words
  because `fuzzy_targets` skips tokens that are real English words and the
  surname corrupts to "Munch".

- **The Astra judge has live web search and keeps it.** `codex exec` with the
  production flags answers "YES - web.run", and the judge was observed searching
  and citing a page naming the blinded subject. `-s read-only` restricts the
  filesystem, not the network, and five candidate config keys failed to disable
  it. Left on so new grades stay comparable with the ~1000 already collected.
  `count_tool_events()` now records `tool_use_counts` and `web_search_queries`
  on every Astra grade, so the exposure is measurable instead of merely accepted.
  Fable is genuinely sandboxed: it is offered the tools, tries all three, and
  every one is denied.

- **Gemini's coverage gap is a RETRY BUDGET, not a ceiling.** On a long prompt
  the judge reaches for a tool to navigate it, the tool is auto-denied, and the
  turn ends with an empty answer, because agy terminates a run on an
  auto-denied tool (upstream bug, see below). Long transcripts fail far more
  often: the ones that failed had a median of ~36,000 words against ~12,000 for
  the corpus.

  MEASURED 2026-09-09 across five passes: **no transcript fails
  deterministically.** 25 transcripts failed at least once and 0 failed in
  every pass they were attempted in, with one pass recovering 10 of 14.
  Whether the model reaches for a tool is a sampling decision, so a long prompt
  raises the probability rather than forcing it. Re-running is therefore the
  fix, exactly as it is for Astra's refusals.

  An earlier version of this entry called these transcripts blocked and put the
  gap at a permanent 5%. That was wrong, and wrong in a way worth remembering:
  a failure that repeats is not the same as a failure that is deterministic,
  and this repo already had the Astra refusal precedent showing the difference.
  What the bug really costs is quota, since every retry is a real call and the
  long transcripts are the expensive ones.

  Watch it in `coverage_table.py`, which shows per-judge columns. If Gemini
  drifts below the other two, run the blinded pass again rather than assuming a
  ceiling.

- **The Gemini judge has live web search too, and it also cannot be disabled.**
  Same position as the Astra arm, reached by a different route: the permission
  system recognises three grant actions plus `mcp`, and a builtin tool is not
  expressible as a rule at all. `count_gemini_tool_events()` records
  `tool_use_counts` and `web_search_queries` on every grade, so the exposure is
  measured rather than assumed. MEASURED over the full backfill: a tool ran on 19
  of 483 grades, 4%, and the recorded queries show the judge searching for the
  blinded subject BY NAME -- `"group chat" "evan spiegel" "screenshop"` and
  `"Group Chat" "Aaron Rodgers" "Screenshop" "Kanye"`. That is active
  de-blinding, not incidental lookup, and it is the same behaviour recorded for
  Astra above. An early note here said the judge used no tools at all; that was
  one data point on three grades and it was wrong.

- **The published interval does not include judge re-run noise.** `bootstrap`
  resamples a leader's transcripts and holds each grade as a fixed value, so it
  captures sampling across transcripts and nothing about the same judge scoring
  the same transcript differently on a second call. MEASURED 2026-09-07: that
  noise is a within-transcript sd of 0.60 for Astra and 1.15 for Gemini, which
  is +/-0.31 and +/-0.60 at 95% for a 14-transcript leader. The published
  endpoints are therefore slightly narrower than the truth. Left as is because
  the effect is small against a median rank range of 13 places, and because
  folding it in would need repeat grades across the whole corpus rather than the
  eight transcripts measured. Recorded because it is an assumption the number
  carries silently, not because it changes a rank today.
  MEASURED AGAIN 2026-09-10 on 18 transcripts: Fable's within-transcript sd is
  3.24 and its mean drifted +2.44 against grades 1 to 4 days old; Astra 1.53;
  Gemini 4.30. The 2026-09-07 figures were optimistic. Fable's drift is the
  largest unexplained number in the pipeline and deserves its own experiment.

- **Every Gemini grade came from one account.** See "Two profiles do not mean
  two accounts" above. The round-robin was even and both HOMEs resolved to
  gptwufamily@gmail.com, so the arm's quota exposure is one account's, and the
  per-grade `profile_identity` is the record of it.

- **Filters bite unevenly, which is a bias and not a detail.** The subject-share
  filter removed 81% of Jeff Bezos's material, and he is scored on what is left.
  Astra refuses politically-charged transcripts, concentrated on Alex Karp and
  Elon Musk, so their evidence has a content-correlated hole. Both appear in
  `diagnostics`; neither appears on the site.

## Where things are

- Rubric and schema (the grading contract, fingerprinted into every grade):
  `.claude/skills/leader-transcript-grader/`
- Published site: `site/index.html`, deployed with `npx wrangler deploy` to
  `verbatim-index.tonygwu.com`
- Per-leader pipeline coverage: `.venv/bin/python scripts/coverage_table.py`
- Wrong-person screen: `.venv/bin/python scripts/wrong_person_screen.py`. It
  replaced `identity_audit.py`, which was deleted on 2026-09-10 after both were
  run on the same corpus: the screen flagged 4 recordings, 2 of them live on the
  board, where `identity_audit` found 0. Its labelled fixture survives as
  `scripts/test_wrong_person_regressions.py`.
- The roster, 50 people: `data/roster/final.json`, with the expansion reasoning
  and the two meanings of `longform_availability` in
  `docs/ROSTER-EXPANSION-2026-09-10.md`
- Corpus-integrity findings and their re-derivation:
  `docs/CORPUS-INTEGRITY-2026-09-10.md`, `docs/CORPUS-INTEGRITY-FOLLOWUP.md`,
  and the withdrawal manifest `docs/withdrawals-2026-09-10.json`. The re-grade
  records behind the follow-up wait in
  `~/Code/misc/verbatim-index/experiments-inbox/2026-09-10-year-deloop/` for
  repo-0 to commit under `data/experiments/`; grades are data and stay out of
  this public repo. Open items and waiting decisions for that workstream:
  `docs/LEDGER-corpus-integrity.md`.
- Verbatim Predictions (extract, verify, market consensus, validate, aggregate, page): skill in
  `.claude/skills/prediction-extractor/`, records in `data/predictions/<slug>/<sid>.jsonl`, design and limits in
  `docs/PREDICTIONS.md`, page built by `scripts/build_predictions_site.py` and deployed with
  `bash scripts/deploy_predictions.sh` to `verbatim-predictions.tonygwu.com`.
  This is a SECOND published site with its own domain and its own index, and it
  goes stale independently of the leaderboard: `data/predictions/index.json` is
  rebuilt only by `aggregate_predictions.py`, which nothing runs on a loop.
  `deploy_predictions.sh` compares the index's `files_read` and `records_read`
  against the files on disk and prints `STALE` when they differ, so read that
  line before publishing. Only repo-0 can refresh it, because `--refresh`
  carries the daemon-clone precondition.
- Grader validation (reliability, bias probes): `scripts/validate_grader.py`
