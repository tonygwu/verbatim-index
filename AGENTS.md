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
.venv/bin/python scripts/test_grade_harness.py     # pure checks, no quota
.venv/bin/python scripts/test_pipeline_dedupe.py  # pure checks, no quota
.venv/bin/python scripts/test_shared_data.py      # pure checks, no quota
.venv/bin/python scripts/test_venue_calibration.py # pure checks, no quota
.venv/bin/python scripts/test_blinding.py
.venv/bin/python scripts/test_coverage_table.py   # per-judge columns in the table
.venv/bin/python scripts/test_render_integrity.py # invalid records, and a loud render
for t in shared lib schema driver markets eval aggregate site; do .venv/bin/python scripts/test_predictions_$t.py; done  # predictions, no quota
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

Two Antigravity accounts serve it. A profile follows `$HOME`, because `agy` has
no `AGY_CONFIG_DIR`:

| Invocation | HOME | Identity |
|---|---|---|
| `agy` | `~` | tonygwu@gmail.com |
| `agy-b` | `~/.agy-homes/gptwufamily` | gptwufamily@gmail.com |

`agy-profiles` derives that table rather than restating it. `grade.py` sets
`HOME` per subprocess and records which account served each grade in
`telemetry.profile_identity`.

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

- **Per-judge calibration.** `calibrate()` maps each judge's score distribution
  onto the pooled one, per dimension, and only when that judge's spread is
  meaningful (`sd >= 3.0`), because rescaling a flat judge amplifies noise.
  Fable currently runs 9.0 points below Astra on clarity, 4.9 on insight and
  2.4 on technical depth. What calibration cannot fix is an uneven judge MIX
  per leader, so watch `judge_call_counts` when a quota window closes.

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
  What it shows: 0 of 39 adjacent pairs separate at 95%, and the median leader's
  rank range is 13 places wide. The board distinguishes the top from the bottom
  and does not distinguish rank 9 from rank 12.

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

Four experiments settled questions that guesswork would have got wrong. Each is
recorded with its method, because the conclusions are only as good as the setup
and a later agent should be able to challenge them.

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
- Verbatim Predictions (extract, verify, market consensus, validate, aggregate, page): skill in
  `.claude/skills/prediction-extractor/`, records in `data/predictions/<slug>/<sid>.jsonl`, design and limits in
  `docs/PREDICTIONS.md`, page built by `scripts/build_predictions_site.py` and deployed with
  `bash scripts/deploy_predictions.sh` to `verbatim-predictions.tonygwu.com`
- Grader validation (reliability, bias probes): `scripts/validate_grader.py`
