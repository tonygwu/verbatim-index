# The judges

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you change `grade.py` or
any judge call; touch the Gemini (`agy`) rotation, its accounts or its wrapper;
read a judge's failure taxonomy; or add, drop or compare a judge.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

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
`grade.py` supports that as a profile of the form `user:<name>`, declared in
the router config.

**Since 2026-10-04 there are two real accounts, and every call proves its
own.** The default macOS user serves tonygwu@gmail.com and `tonyagents` serves
gptwufamily@gmail.com. `gemini_rotation_from_config()` builds the rotation,
taking only the Gemini pool, because each macOS user also has a Claude-pool
account on the same Keychain item. After each call `grade.py` compares the
account named in that call's log with the config's `identity_email`. A
different address, or none, fails the call as `account_identity_mismatch`
instead of writing a grade: a running Antigravity desktop app can write a
stale login back into the Keychain item that agy reads. If the wrapper exits
75, that user has no login session, so the profile is benched for the whole
run with a WARNING. If it exits 77, the binary is wrong and the pass stops at
preflight. VERIFIED 2026-10-04 on a 2-call smoke: one grade from each address,
both `profile_identity_verified`. Guarded by
`scripts/test_gemini_config_rotation.py`.

**All four Gemini callers share one entry point, and every call records its agy
build (2026-10-04).** `grade.py`, `date_recordings.py`, `extract_predictions.py`
and `market_consensus.py` build the rotation with
`grade.gemini_rotation_preflight()`, which reads the router config, runs the
exit 75/77 preflight, and prints each profile's account and `agy --version` in
its header. Every `call_gemini` passes `expected_identity`, and every
`--agy-bin` defaults to `grade.AGY_JUDGE_BIN`, `/usr/local/bin/agy`. Before
this the three prediction scripts used `agy_profiles()`, with no identity check,
no preflight, and a bare `agy` that the wrapper refuses with exit 77.
`call_gemini` reads `agy_version` from that call's own `--log-file`, the line
`Language server version: X`, and never from the binary. A log with no such
line, or two different ones, fails the call as `agy_version_unreadable`. The
version lands in a grade's `telemetry`, a prediction record's extraction or
verification `telemetry`, the prediction meta file (`extract.agy_version`, and
`verify.agy_versions` with one entry per batch), a dating proposal's
`telemetry`, and a market match's `matcher.agy_version`. The prediction scripts
preflight Gemini only when the router could reach it: a run pinned to another
harness, or with every Gemini account excluded, skips it. In
`extract_predictions.py` the round-robin, not the quota router, picks the
profile, so a Gemini route's `account_id` is the account of the profile it
runs. VERIFIED 2026-10-04 on a 2-call `extract_predictions.py` smoke: one call
served by each address, both `agy_version` 1.2.0. Guarded by
`scripts/test_gemini_rotation_everywhere.py`.

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

## Measurement decisions, and why

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
  removed. Removing those production grade records belongs to repo-0.
  Calibration is still keyed by `(judge, model, mode, dim)`, because a judge
  whose model is BUMPED mid-corpus is the same hazard arriving another way, and
  `diagnostics.judge_models` warns when one judge served more than one model.
  Note that `codex --json` reports no model anywhere in its response, so
  `served_model` records what was REQUESTED; it is not independently verified.

## Experiments run, and what they showed

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

## Known limits of the published score

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

- **Every Gemini grade came from one account.** See "Two profiles do not mean
  two accounts" above. The round-robin was even and both HOMEs resolved to
  gptwufamily@gmail.com, so the arm's quota exposure is one account's, and the
  per-grade `profile_identity` is the record of it.
