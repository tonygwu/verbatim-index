# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Judges

- **Two code paths call `quotapick run`: `grade.call_fable_pool` and
  `credit_run.run`.** Filed 2026-10-18 by repo-3. Both landed the same night
  from two concurrent sessions. `grade.call_fable_pool` (repo-0) is the judge
  path: one pool, Fable at max effort, labels from grade.py's taxonomy.
  `credit_run.run` (repo-3) is the general path for the pundits speaker drafts
  and `extract_predictions.py --fable-credit-pools`: a SET of pools for the
  router to choose among, any model and effort, its own labels. They check the
  same `served` fields today, and two copies of an identity check drift. Fix:
  make `call_fable_pool` call `credit_run.run` with `pools=[pool]`, and map
  `PoolsExhausted` and `CreditRunError` onto its labels, so `test_fable_pool.py`
  and `test_credit_run.py` both stay green. Comes back when the CI-11 drift
  experiment in `data/experiments/fable-credit-drift-20261018/` has finished,
  because that run imports grade.py from repo-0's working tree.

- **Gemini retries on the six longest transcripts.** Filed 2026-10-11 by repo-0
  (overnight run). Six blinded transcripts of 32,912 to 38,858 words have never
  had a Gemini grade, and every `grade_loop.sh` cycle calls Gemini up to 3 times
  on each of them. Since 2026-09-06 three of them have failed in 142 cycles
  each. The measurement and the six ids are in `docs/agents/JUDGES.md`, under
  "Gemini's coverage gap is a RETRY BUDGET". Each of the six leaders has that
  recording scored by Fable and Astra only. The options:
  (a) Change nothing. Cost: about 18 long Gemini calls per cycle, every cycle,
  for a chance per call that is close to zero (one 50,025-word transcript
  succeeded once in 119 cycles).
  (b) A per-transcript cap across runs. After N cycles of `empty_response`
  with a denied tool, skip that (judge, transcript) and list it in the run
  summary as skipped, with its count. Cost: a code change in `grade.py` and a
  test, and the six stay at two judges unless the cap is reset by hand.
  (c) A Gemini prompt that gives the transcript in parts, so the judge does not
  reach for a tool. Cost: a new prompt, which changes the measured judge and
  must be measured against the current one before it is used.
  Recommendation: (b), because it stops the spend and keeps the record
  honest; (c) only if two-judge coverage on these six becomes a problem.
  Comes back when the operator picks one.

- **A Fable stage without `--fable-accounts` runs on the default account.**
  Filed 2026-10-11 by repo-0. `resolve_predictions.py --stage lead_test`
  with no `--fable-accounts` ran its one call on `~/.claude`
  (`accounts=['default']` in `rebuild-20261011/lead_test-1.log`); it served
  `claude-fable-5-1` and cost $0.21. Nothing failed, but the operator has said
  account A has no Fable, and batch Fable work is meant to go to the accounts
  named for it. Option: refuse a Fable stage that names no accounts, or route
  it by measured quota the way `grade.py` does when `FABLE_ACCOUNTS` is unset.
  Cost: every caller must pass the flag, or the stage gains the router.
  Comes back with the next change to `resolve_predictions.py`.

## Speaker segmentation and caption text

- **Re-checked 2026-10-11: still WAITING, at 15 corrections over 5 recordings
  of the 50 over 10 it needs.** Counted with `pundits_text_corrections.py` over
  every speaker-check answers file on this Mac: leaders 9 edits over 2
  recordings, predictions 5 over 2, pundits 1 over 1. The entry below says the
  first session saved 5, which is the predictions half only. The newest edit
  is from 2026-09-28T05:07Z, and no later session exists in either data repo.
  The "correct every error you notice" convention the condition depends on is
  written nowhere except this entry, so it has never been in force. Put it in
  `docs/PUNDITS-LABELLING-GUIDE.md` before the next session if this should
  ever come back.

- **Let the speaker-segmentation call also correct obvious caption errors.**
  Filed 2026-09-28 at the operator's request. `scripts/speaker_segment_probe.py`
  asks a model to split a whole transcript into speaker turns, and the first
  speaker-check session (`predictions/_experiments/speaker-audit-20260927/` on
  repo-3's private data branch) scores it against the operator's word ranges.
  While labelling, the operator also used the page's "Correct text" and saved 5
  corrections. The idea is to have the SAME call that finds the turns also return
  caption corrections, rather than a second pass over the raw YouTube text: one
  read of the recording serves both, and knowing who is speaking helps with the
  commonest fixable error, a misheard name ("Grock" for "Grok").

  Why it waits. There is too little ground truth to score it. Of the 5
  corrections, at most 3 are recoverable from text: "Grock" to "Grok", "dial" to
  "dial-up", perhaps "but definitely" to "but I definitely". The other 2 restore
  words the captions DROPPED ("Wow." to "Wow. That's crazy."), which only the audio
  holds, so no text-only model can be expected to make them. Segmentation itself
  was adopted on 2026-09-28 as `scripts/speaker_turns.py`, pinned to Astra, check
  only and for new transcripts only; the correction task would extend that call,
  and its prompt is pinned by hash, so the extension is a new measured prompt.

  Three constraints, whichever way it is built:
  1. Corrections are OVERLAYS keyed to the original token offsets, in the shape
     `pundits_text_corrections.py` already stores (`start`, `end`, `original`,
     `replacement`). The original text stays the source of truth. The operator's
     word ranges, the judges' evidence quotes and every published prediction's
     `quote_char_start` point into it, and an in-place rewrite would break all
     three.
  2. Measure that the second job does not degrade the first. The 2026-09-28
     segmentation-only runs are the baseline: same recordings, same scorer, turns
     with and without the correction task.
  3. Score corrections both ways: how many of the operator's text-recoverable
     corrections a model finds, and how many of its own edits are wrong. The second
     needs negatives, so it needs the convention below.

  The condition that brings it back: at least 50 operator corrections across at
  least 10 recordings, made under the convention that every caption error noticed
  in a reviewed passage is corrected, so that a reviewed word left alone counts as
  correct. Both numbers are a judgement, not a measurement: enough corrections that
  one model finding 3 more than another is not noise, spread over enough
  recordings that one speaker's accent or one caption track does not dominate.
  Count them with `pundits_text_corrections.py` over the answers files.

## Board membership (P1, P2 and most of P3 shipped 2026-09-18)

Reviewed 2026-09-17 against `docs/plans/board-membership-2026-09-16.md`, at
`240d472` with the whole suite green (`bash scripts/run_tests.sh` -> `failed: 0`).
P1 itself is sound and nothing reads `membership.json` yet, so none of this moves
a published number today. Every entry below is P2's, and each one is a place the
plan was right when it was written and the tree has moved since.

- **RESOLVED 2026-10-11: the second and third observations came, both named,
  and the proven one is fixed.** Two later commits recorded red suite runs that
  nobody filed here:

  ```
  b80ef3b 2026-09-26  test_run_marker.py "a plain kill removes the marker",
                      load average about 470, the check allowed 5 seconds
  d9f2321 2026-09-27  test_pundits_verify_serve.py failed once in a concurrent
                      run and passed 24/24 alone; its output was not kept
  ```

  The entry below was wrong that `test_normalize_qa_race.py` is the suite's only
  wall-clock assertion: `test_run_marker.py` predates it with a 5-second
  `wait_for`, and it is a plausible cause of the original unnamed failure too.
  FIXED there, test-first. A new STALLED case SIGSTOPs a loop, kills it, and
  continues it 6 seconds later; with the old 5-second bound it failed, `38
  passed, 2 failed`, and with the bound at 20 seconds it passes, `40 passed, 0
  failed`. A wait returns the moment its condition holds, so a healthy run pays
  nothing. The loop body now runs 120 seconds, far past any wait, so a loop
  exiting by itself can never satisfy a check meant for a signal, and the
  CLAIM case holds its loop on a release file instead of racing a 1.5-second
  sleep. Mutation check: with the EXIT trap removed from `run_marker.sh`, EXIT,
  TERM and STALLED all fail. `test_pundits_verify_serve.py` was first given
  wider HTTP timeouts on a guess; the same night its failure was REPRODUCED and
  it was not a timeout. Looping the file 60 times failed 3, every one a
  connection reset at the oversized-body check: the server refused before
  reading the body, so the socket closed with unread bytes and the kernel sent
  a reset. A 1 MiB body was reset 30 times in 30. The server now reads and
  discards a refused body up to `DRAIN_LIMIT` before answering; a new check
  sends 4x the cap five times and wants five 400s, and it failed first. After
  the fix, 60 runs, 0 failed. Then every test file that sleeps, times out,
  opens a socket or starts a process, 19 files, ran 20 times each: 380 runs, 0
  failed. A full suite ran beside the loop, adding load. If any of them goes
  red again, keep the whole output.

- **`bash scripts/run_tests.sh` returned `failed: 1` once and has not
  reproduced in five attempts. The failing file's name was lost.** Filed
  2026-09-17. One red run between two green ones, with nothing changed in
  between but `BACKLOG.md` prose. Five subsequent full runs are green, including
  one against a freshly rebased tree:

  ```
  --- run 1   failed: 0
  --- run 2   failed: 0
  --- run 3   failed: 0
  (after git pull --rebase onto 2505df7)   failed: 0
  ```

  The runner DOES print `FAILED <path>` per file. The name was lost because the
  caller piped it through `tail -1` and kept only the summary. That is the
  operator error, not a runner defect, and the lesson is that this suite's
  output must never be truncated to its last line.

  RULED OUT, not by argument but by running it: `test_normalize_qa_race.py`,
  which is the only test in the suite carrying a real wall-clock assertion. Five
  timed runs at 3.43 to 3.53 seconds, all rc=0, and the check refuses to pass
  vacuously below 1.0s rather than silently weakening. So the most plausible
  candidate is not the cause.

  NOT chased further, because this repo's own precedent says a failure that
  repeats is not the same as a failure that is deterministic, and here it did
  not even repeat. Chasing an unnamed one-off costs more than it returns.
  The condition that brings it back: a SECOND observation. If `run_tests.sh`
  reports a nonzero count again, capture the whole output, not the summary, and
  file the named file here. A flake in the verification gate for the membership
  change is worth naming precisely once it can be named at all.

- **RESOLVED 2026-09-18 (62e79f5). The floor the plan proposes for `deploy.sh` refuses publication for ever on
  the first cycle after P3.** Filed 2026-09-17. The plan says to derive the floor
  as the roster size, "which `aggregate.py:1169` writes as
  `len(leaders) + len(unranked) + len(unscored)`", and to compare it against the
  count `deploy.sh` already prints. Those two numbers are not comparable.
  `aggregate.py:1341-1347` writes `"leaders": scored`, so `leaders` holds only
  the scored-and-ranked people, while `unranked` and `unscored` are disjoint
  lists beside it. `deploy.sh:36-38` counts `status == "scored"`, which is
  exactly `len(leaders)`. So the floor equals the count only while `unranked` and
  `unscored` are both empty.

  They do not stay empty. `leaders_out` is built by iterating the whole roster
  (`aggregate.py:1109`), and a roster person with no grades is appended with
  `status: "no_grades"`, which lands in `unscored`. P3 appends seven such people.
  MEASURED on synthetic corpora built from `test_render_integrity.a_grade`,
  three leaders graded, run through the real `scripts/aggregate.py`:

  ```
  A_baseline_all_graded        leaders=3 unranked=0 unscored=0 | deploy led=3 PLAN_FLOOR=3 -> ok
  B_P3_seven_added_nograde     leaders=3 unranked=0 unscored=2 | deploy led=3 PLAN_FLOOR=5 -> REFUSE
  C_one_under_rank_floor       leaders=2 unranked=1 unscored=0 | deploy led=2 PLAN_FLOOR=3 -> REFUSE
  ```

  Arm B is P3. Arm C is one leader falling under `MIN_TRANSCRIPTS_TO_RANK`, which
  a withdrawal is enough to cause and which this repo has already done once, to
  C.C. Wei. Either way the operator sees `REFUSING` on every deploy and, with
  `PUBLISH_ON_COMPLETE=1`, `grade_loop.sh` exits 1 on a board it could otherwise
  have published. That is the same shape the plan spent a paragraph keeping out
  of `membership.py`, arriving one file further down.

  NOT fixed here, because P2 is not implemented.

  **DECIDED BY THE OPERATOR 2026-09-17: the floor is derived from the PREVIOUS
  PUBLISHED COUNT, not from the roster and not from the membership board.** The
  two derivations offered alongside it were rejected with their costs understood.
  Counting the membership leaders board is the tightest guard and still refuses
  when a real leader legitimately drops under `MIN_TRANSCRIPTS_TO_RANK`, which is
  arm C above. `len(leaders) + len(unranked)` survives that but is blind to slow
  erosion. The previous published count is the only one of the three that catches
  a board eroding 50 -> 40 over weeks, and the operator took its costs
  deliberately: it needs state that `deploy.sh` does not keep, a first-run
  bootstrap, and a tolerance that is itself a typed number.

  **THE CONSTRAINT THAT DECIDES WHERE THE STATE LIVES, and it is not in the
  plan.** `AGENTS.md:127` records that `deploy.sh` stays READ-ONLY ON DATA, and
  the only write to `PRODUCTION_DATA` in the script is the `--refresh` aggregate
  at `scripts/deploy.sh:18`. So the previous published count may NOT be written
  into the data repository, which is the obvious place and the wrong one. It has
  to live where `deploy.sh` already writes, or be read without being written.
  Three candidates, in the order I would try them:

  1. `site/published.json`, written beside `site/index.html`, which `deploy.sh`
     already writes, and committed to the PUBLIC repo so every clone sees the
     same number through git. Records the count, the `results.json` digest and
     `published_at_utc`. Breaks no documented rule. Its failure mode is a deploy
     from a clone that has not pulled, reading a stale count; `--data-revision`
     already pins the data side and code staleness is an existing hazard.
  2. Read the live site over the network and count the rows. No state at all and
     it cannot drift, because it IS the published board. Costs a network
     dependency and HTML parsing inside a publication guard, which is a poor
     place for either.
  3. Extend `site/og.meta.json`, which already records the rows that were drawn
     (`scripts/test_og_card_rows.py`). Cheapest diff, but it overloads a social-
     card sidecar with a publication guard, and the two will be edited by
     different people for different reasons.

  **The tolerance is a typed number and there is no way to derive it**, so put it
  in ONE place, name it, and print it on every deploy whether or not it fires. A
  guard whose threshold is invisible until it refuses is one an operator
  bypasses. The plan's own reasoning applies: too tight and `grade_loop.sh:237`
  prints AGGREGATE FAILED every cycle while the site serves the last good build.

  **The first run has no previous count.** Bootstrap must be explicit and loud,
  not a silent pass. An absent `site/published.json` should print that it is
  bootstrapping and name the count it is recording, so the one deploy that cannot
  be guarded says so rather than looking guarded.

  Change `test_data_clone_workflow.py:177-178` in the same commit whatever the
  derivation: its fixture writes `{"leaders": [], "diagnostics": {...}}` with no
  `unranked` or `unscored` key at all, so a floor reading those keys raises
  `KeyError` there rather than failing the assertion the plan expects. Under the
  decided derivation that fixture also needs a previous-count file, or the
  zero-leader deploy it asserts will take the bootstrap path and pass for the
  wrong reason.


### How the four above were resolved, 2026-09-18

All four were filed by the P1 review and all four are now addressed. Evidence in
`docs/MEMBERSHIP-P2-AUDIT.md` and in each commit.

- **The deploy floor** is the PREVIOUS PUBLISHED COUNT, decided by the operator
  on 2026-09-17 over the two cheaper derivations. `scripts/publication_floor.py`,
  state in `site/published.json` because `deploy.sh` stays read-only on data.
  The baseline was seeded from the live board's own row count, not assumed:
  50 rows, ranks 1 to 50, LeCun first and Benioff last. 38 checks.
- **The test inventory** was re-derived rather than trusted. MEASURED: 7 files
  failed once the aggregate reader landed, and 6 of them inherit one seam through
  `test_render_integrity.run_aggregate`; only `test_site_ci.py` shells out
  directly. Three `build_site` fixtures gained the `leader_slug` the plan's own
  rule requires.
- **The stale citations** were re-derived at the top of the work and recorded in
  the audit. Two things the plan does not carry: `roster_n` lives inside
  `build_method()`, not `main()`, so membership has to be passed down; and the
  word count now reads `transcripts_blind`, not `transcripts`.
- **The fingerprint gap** is closed by `SITE_REPO_INPUTS`, declared per site.
  MEASURED before the fix: retyping every board name in `membership.json` left
  the fingerprint byte-identical. Only `leaderboard` names it, because
  `build_predictions_site.py` does not read membership, and one arm asserts that
  non-coverage deliberately.

**Still open from that review:** nothing. The two LOW findings were fixed the day
they were filed (50aeaac).

- **SETTLED, re-checked 2026-10-11: nothing to do, and the code matches the
  decision.** `aggregate.py` builds `by_slug` from the whole roster, appends a
  person with no grades as `no_grades`, applies membership to the grades only,
  and writes `unscored`. None of the three readers reads `unscored`.
  `deploy.sh` counts `leaders` with status `scored`, `build_site.py` iterates
  `leaders`, and `coverage_table.py` reads `leaders + unranked` and filters the
  roster by membership. repo-0's committed `results.json` at data `65de79c7`
  holds 50 scored, no unranked, and exactly the seven investors in `unscored`,
  all `no_grades`, with 0 off-board grades.

- **`aggregate.py` applies membership to the GRADES only, never to the roster
  iteration. DECIDED BY THE OPERATOR 2026-09-17.** Filed 2026-09-17. The plan
  specifies the grade filter at `usable = grades` and says nothing about the
  roster loop at `aggregate.py:1109`, which iterates every roster person and
  appends one with no grades as `status: "no_grades"`. The review could not tell
  from the plan which behaviour was intended, because filtering the roster too
  would have made the plan's original floor work.

  The operator chose NOT to filter the roster. So from P3 the seven investors
  appear in the leaders `results.json` under `unscored` with `status:
  "no_grades"`, visible in diagnostics and absent from the page. The reason is
  that `results.json` stays a faithful record of what the roster held, and
  membership decides only what is RENDERED. That reading is consistent with the
  plan's decisive rule, which is about reads and writes rather than about what
  the record may mention.

  Two consequences to carry into P2, neither of them blocking:

  - `unscored` becomes non-empty for the first time. Anything that treats an
    empty `unscored` as normal will see seven entries. `results.json` is read by
    `deploy.sh`, `coverage_table.py` and `build_site.py`; check each before the
    P3 commit, not after.
  - This is WHY the floor could not be derived from the roster sum. The two
    decisions are linked and were taken together: the roster sum stays 57 after
    P3 while the published count stays 50, so the previous-published-count
    derivation above is doing the work the roster sum cannot.

  Nothing to do until P2 wires the aggregate reader. Recorded so the next pass
  does not re-open a settled question.

- **RESOLVED 2026-09-18 (239f934, 5549f15). The plan's P2 test inventory counts `aggregate.py` invocations and never
  counts `build_site.py` invocations, and `build_site.py` is one of the three
  readers.** Filed 2026-09-17. Three leaders-mode test files run `build_site.py`
  directly against rosters whose slugs `membership.json` does not know:

  ```
  scripts/test_render_integrity.py:352   live roster padded with pad-0..pad-6
  scripts/test_site_social_and_exclusions.py:109   synthetic roster
  scripts/test_site_evidence_split.py:104          synthetic roster
  ```

  The last two did not exist when the plan was written: `7b77b20` (2026-09-16)
  and `4e954ba` (2026-09-17) added them. Worse for the word-count reader, both
  write their blinded-transcript fixtures as `{"word_count": N}` and nothing
  else, with no `leader_slug` in the record at all:

  ```
  scripts/test_site_evidence_split.py:89           (d / f"src{t}.json").write_text(json.dumps({"word_count": 1000}))
  scripts/test_site_social_and_exclusions.py:86    ... WORDS_PER_GRADED
  scripts/test_site_social_and_exclusions.py:94    ... WORDS_PER_UNGRADED
  ```

  The plan's rule is "every lookup takes the slug from a record, never a path
  component", so those three write sites must gain a `leader_slug` before the
  word-count gate can read one. Taking it from `p.parent.name` instead would
  break the rule quietly, which is why this is recorded rather than left to be
  discovered mid-implementation.

  Re-derived at the same time: the leaders-mode `aggregate.py` inventory is now
  **ten call sites across six files**, not "eleven across five".
  `test_site_evidence_split.py:94` and `test_site_social_and_exclusions.py:99`
  are new, and both go through `ri.run_aggregate`, so the plan's chosen seam
  (put the fixture inside `run_aggregate` at `test_render_integrity.py:148`)
  still covers them for free. Two invocations are direct and need their own
  patch: `test_site_ci.py:109`, which the plan names, and
  `test_venue_calibration.py:408`, which it does not. The second is harmless,
  because it runs against the real `data/roster/final.json` and the real
  `data/grades`, but it is an argv the implementer will otherwise miss.

- **RESOLVED 2026-09-18 (899493b). Every `file:line` in the plan's P2 section is stale, and one of them now
  names a different directory.** Filed 2026-09-17. The plan's own revision note
  says "only `build_site.py` moved". That was true at `b8a8a73`. Re-derived at
  `240d472`:

  ```
  plan says                              actually now
  aggregate.py:740  grade_files_read     :866      (+126)
  aggregate.py:831  usable = grades      :957      (+126)
  aggregate.py:839  accounted = ...      :965      (+126)
  grade.py:2063  paths = sorted(...)     :2116     (+53)
  grade.py:2064  if not paths            :2117
  grade.py:2092  fable_accounts()        :2145
  build_site.py:815  roster_n            :1045     (+230)
  build_site.py:1079 tdir = .../"transcripts"  :1326, and the directory is now
                                          "transcripts_blind"
  build_site.py:1025 study dispatch       :1267
  build_site.py:778  SHOW_PREDICTIONS_LINK :1008
  grade_loop.sh:211  AGGREGATE FAILED     :237
  grade_loop.sh:283  COMPLETE             :305
  ```

  Every anchor still exists and every ordering the plan depends on still holds:
  the transcript list is loaded before `fable_accounts()`, `usable = grades` is
  upstream of calibration, and the bare `except Exception: pass` is still there
  at `build_site.py:1334-1335` swallowing the parse in the word-count loop. The
  `transcripts_blind` change matters on its own, because the plan's "measured
  no-op" argument was computed over `data/transcripts` (720 shelf files) and the
  page now counts `data/transcripts_blind` (664 derived files, 50 slugs, every
  record carrying `leader_slug`). The conclusion is unchanged, the arithmetic
  behind it is not, and it must be recomputed rather than quoted.

  One wording trap worth naming while it is cheap. "Read `leader_slug` and decide
  membership OUTSIDE the `try`" cannot be followed literally: the parse that
  yields `leader_slug` is the thing the `try` guards. The implementable shape is
  to narrow the except to `(json.JSONDecodeError, OSError)`, parse inside it, and
  put the membership decision after it in the loop body.

- **RESOLVED 2026-09-18 (38e0c04). After P2, `membership.json` is a render input that the deploy fingerprint
  cannot see.** Filed 2026-09-17. `check_publication_unchanged` in
  `scripts/deploy_source.sh:32-40` compares `data_clone_workflow.fingerprint()`
  before and after the render, and that function hashes only paths under the
  production DATA source (`SITE_SHELVES`, `data_clone_workflow.py:297-325`).
  `membership.json` lives at the public repo root, so an edit to it between
  `PUBLICATION_BEFORE` and `check_publication_unchanged` changes the rendered
  page and the guard still prints `content sha256` and passes. The same hole
  already exists for every script in `scripts/`, so this is not new in kind; it
  is new in that a one-line config edit now moves the board. Deferred because the
  fix is a separate decision (fingerprint the code revision, or add the public
  repo's tracked inputs to the shelf list) and it should not be bolted onto P2.
  Bring it back the day `membership.json` is read by `build_site.py`.

- **Three of the 67 checks in `scripts/test_membership.py` cannot fail.
  RESOLVED 2026-09-17, same day, in the commit below.** Filed
  2026-09-17. `raises(..., naming="leader")` asserts that the message contains
  the substring `leader`, and every one of those messages also echoes the
  whitelist `['leaders', 'predictions']`, so the assertion is satisfied by the
  word `leaders` whatever the message says about the offending board. The three
  are at `scripts/test_membership.py:115`, `:150` and `:152`. MEASURED by
  mutation: rewriting both messages to name no board at all leaves them green.

  ```
  M10: the error messages STOP naming the offending board/slug
    PASS      ... and says so, naming 'leader'     (x3)
    FAIL      ... and says so, naming 'sam-altman'
  66 passed, 1 failed
  ```

  The parent assertions, that the call raises at all, are real and do
  discriminate. Nine other mutations were caught, three of them reproducing the
  commit message's own numbers exactly: `boards_for` as `data.get(slug, [])`
  fails 2, dropping the board whitelist fails 2, anchoring `DEFAULT_PATH` to the
  working directory fails 1.

  THE FIX was the assertion, not the message: the three now assert the REPR
  `'leader'`, which the whitelist echo does not contain, rather than the bare
  substring, which it always does.

  ```
  .venv/bin/python -c "print('leader' in str(['leaders','predictions']), \
                             repr('leader') in str(['leaders','predictions']))"
  True False
  ```

  Re-run of the same mutation against the repaired test, which was green before
  the fix and is red after it:

  ```
  MUTATION: the board-name messages stop naming the rejected board
    FAIL      ... and says so, naming "'leader'"   (x3)
  66 passed, 3 failed
  ```

- **`membership.load()` accepts a duplicated slug key and keeps the last one.
  RESOLVED 2026-09-17, same day, in the commit below.** Filed 2026-09-17. `json.loads` silently collapses duplicate object keys, and
  `load()` validates the parsed dict, so a hand edit that leaves
  `"sam-altman"` in the file twice loses the first entry without a word.
  MEASURED: duplicating `"sam-altman"` with an empty board list in the shipped
  file gives `64 passed, 3 failed` — caught, but only by the section [5]
  cross-check against `data/roster/final.json`, not by `load()`. So the shipped
  file is protected and a fixture built inside a reader's test is not. Fixed
  rather than deferred, because P2 adds the first readers that could be handed
  such a fixture and the repair is one hook: `_no_duplicate_slugs` is passed as
  `object_pairs_hook` and raises on the second sighting of a key, and the
  `ValueError` it raises is wrapped as a `RuntimeError` naming the path.
  `json.JSONDecodeError` is caught first, since it is itself a `ValueError`.
  Proof, the hook removed and restored:

  ```
  MUTATION: drop the duplicate-slug hook
    FAIL  a SLUG declared twice raises rather than keeping the last
          -- returned {'sam-altman': ['predictions']} instead of raising
  67 passed, 1 failed
  ```

- **Checked and clean, recorded so the next pass does not re-derive it.** Filed
  2026-09-17.
  `cc-wei` really is unreachable by any reader: 14 `.json.superseded` and zero
  live `*.json` on the shelf, `data/transcripts_blind/cc-wei` and
  `data/transcripts_open/cc-wei` present and empty, 44 `.orphaned` and zero
  `*.json` under `data/grades/{astra,fable,gemini}/cc-wei`, and no
  `data/predictions/cc-wei` at all. `aggregate.py` and `deploy.sh` both glob
  `*.json`, so the entry is insurance, exactly as the plan says.
  `membership.json`'s 58 are exactly `roster + seven + cc-wei`, and its key order
  matches the roster's, which is what makes the list-equality assertion in
  section [5] load-bearing rather than decorative.
  Nothing at the repo root sweeps it: the Worker serves `./site` only
  (`wrangler.toml`), `SITE_SHELVES` paths are all relative to the data source,
  and `.gitignore` does not name it. Nothing imports it
  (`grep -rn "import membership" scripts/` is empty outside `membership.py` and
  its test), so P1 cannot move a published number.
  `leaders_baseline.py` needs **no** change at P2, contrary to the plan's terse
  "Add `leaders_baseline.py`": it runs every stage inside
  `shutil.copytree(a.code, code, symlinks=True)`, which copies the tracked
  `membership.json` along with `scripts/`, and `membership.py` resolves its
  default from its own `__file__`. Passing an explicit `--membership` pointing at
  the live repo would break the copy isolation the baseline exists to provide.
  `check_exclusions()` (`build_site.py:986`) is a P3 tripwire the plan does not
  name: it `sys.exit`s when a person is both seated on the roster and listed in
  `dropped_for_no_transcripts`. None of the seven is in that list today, so P3 is
  safe, but a later edit that puts one there kills the leaders render rather than
  warning.

- **RESOLVED, re-checked 2026-10-11: both bring-back conditions are closed.**
  `predictions/scores.json` is tracked, and was already tracked when this was
  filed: it was added in data `ba86d83b` on 2026-09-16, so "UNTRACKED" below
  was wrong. It is a derived file regenerated by `data_sync.py push`, and the
  predictions deploy requires a clean tracked `predictions` path at exactly
  origin/main, so a deploy cannot run without it. The zero-record question was
  decided by `MIN_PREDICTIONS_TO_LIST = 4` in `build_predictions_site.py`
  (702614d, 2026-09-27), which applies with or without scores. A scratch render
  said People 50 without `--scores` and 49 with. The difference is one person
  with nothing past due, and a clean deploy always has scores. The seven
  investors now hold 15 to 50 accepted records each.

- **The predictions page claims 57 people when `scores.json` is absent, and the
  seven have no records.** Filed 2026-09-18. `aggregate_predictions.py:147` unions
  roster slugs with any slug that has records, so P3 putting the seven on the
  roster puts them in the predictions index empty. MEASURED, to a scratch path so
  production was untouched:

  ```
  live data/predictions/index.json   50 leaders
  a fresh aggregate_predictions run  57 leaders
  the seven: on_roster True, accepted 0, transcripts_with_accepted 0

  page built WITHOUT --scores   "Forward-looking claims that 57 technology leaders"
  page built WITH    --scores   "Forward-looking claims that 45 technology leaders"
  the live published page today  45 technology leaders
  ```

  Today's production is SAFE: `data/predictions/scores.json` exists,
  `deploy_predictions.sh` passes it, and the past-due floor filters the seven out.
  `build_predictions_site.person_rows` only filters when scores are supplied, and
  `scores.json` is UNTRACKED, so a clone without it publishes a masthead claiming
  57 people while seven of them contribute nothing.

  NOT fixed, because the obvious fix is not neutral. Skipping any row with zero
  accepted predictions would also hide five leaders already on the board who sit
  at zero (`fei-fei-li`, `ilya-sutskever`, `jack-dorsey`, `sergey-brin`,
  `tobi-lutke`), and what the board says about its own coverage is a publication
  decision rather than a bug. The condition that brings it back: before any
  predictions deploy, either confirm `scores.json` is under the production
  checkout, or decide whether a zero-record person should be a row at all.
  Full context in `docs/MEMBERSHIP-P4-STATUS.md`.

- **RESOLVED 2026-10-11: measured from the records, recorded on every run, and
  a run can now be priced before it spends.** Counted over
  `data/predictions/*/*.jsonl` at data `bc03047c`: 1115 accepted records, 489
  with a `matcher` block (Astra 405, Fable 84), 610 ended at `no_candidates`
  with no call. So the first P4 run did spend, and nothing recorded how much.
  Every run summary now carries `matcher_calls` (attempted, by harness; a pick
  the router refuses is not counted), and `--matcher none` searches the
  markets, reports `would_call_matcher`, makes no model call and writes no
  record. The default is unchanged. Guarded by
  `scripts/test_market_consensus_cost.py`, 13 checks; against the parent it
  fails 4 and then crashes on the argument. The plan's two claims and its stale
  line numbers are corrected, and `docs/PREDICTIONS.md` stage 3 says the stage
  spends.

- **`market_consensus.py` is not quota-free, and the plan says it is.** Filed
  2026-09-18. `docs/plans/board-membership-2026-09-16.md` states it is
  "public-API only, no model calls". `scripts/market_consensus.py:53` imports
  `agy_profiles` from `grade`, and `:605` takes
  `--matcher {auto,fable,astra,gemini}` with `auto` as the default, beside
  `--fable-bin`, `--agy-bin` and `--astra-model`. The market lookups may well be
  public-API; the MATCHER is a model and it is on by default. Anyone planning P4
  under a no-spend constraint will read the plan and get this wrong.

  NOT fixed here because the fix is a measurement, not an edit: run it once with
  the matcher pinned off and record what it actually costs. Until then treat the
  stage as spending. The condition that brings it back is the first P4 run.

- **RESOLVED, re-checked 2026-10-11: dated, and down to one flagged row.**
  Statement dates can now carry a range: `STATEMENT_DATE_HEADER.json` has
  `override_range`, and `test_statement_range.py` passes. Four of the five
  recordings below carry exact sourced dates, `sourced_override`:
  jeff-bezos/src-pnsjkt 1998-02-26, bill-gates/thurrott-com--sfi3q 1996-03-12,
  bill-gates/microsoftces2005-5vjge2 2005-01-05 and
  bill-gates/carnegie-mellon-qatar-sgrx7x 2009-04-18. The fifth,
  vlad-tenev/cnbc-events-bgjbuj, keeps its upload date and does not matter: it
  holds 1 record and 0 accepted, so the dating scope excludes it. In
  `scores.json` at data `4cd18a45`, the rows flagged `deadline_before_statement`
  or `deadline_incoherent` fell from 13 across 6 leaders on 2026-09-29 to 1,
  `arvind-krishna` prediction d7c413366d077633, and none is under the rank
  floor. The VP-16 row in `docs/LEDGER-predictions.md` is updated to match.

- **VP-16 is now blocked on a representation question, not on research.** Filed
  2026-09-18. `scripts/statement_date_evidence.py` finds the real year for five
  of the affected recordings, each verified against its own title:

  ```
  jeff-bezos  src-pnsjkt         2019 -> 1998   "Jeff Bezos - March 1998, earliest long speech"
  bill-gates  thurrott-com       2023 -> 1996   "Microsoft PDC 1996 Keynote with Bill Gates"
  bill-gates  ...ces2005-5vjge2  2013 -> 2005   "CES 2005 - Microsoft Keynote - Bill Gates"
  bill-gates  carnegie-mellon    2012 -> 2009   "Bill Gates - Keynote Address- ICTD 2009"
  vlad-tenev  cnbc-events        2022 -> 2021   "Watch CNBC's 2021 D50 Summit Interview"
  ```

  It was NOT applied, and the reason is worth reading before anyone tries.
  `source.statement_date` is a FULL ISO DATE, today carrying the upload date with
  `statement_date_basis: "youtube_upload_date"`. The evidence gives a YEAR:

  ```
  carnegie-mellon-qatar   kind=year   '2009'
  microsoftces2005-5vjge2 kind=year   '2005'
  thurrott-com--sfi3q     kind=year   '1996'
  src-pnsjkt              kind=year   '1998'
  cnbc-events-bgjbuj      kind=year   '2021'
  ```

  Writing `1996-01-01` would invent a day and a month. That is not cosmetic:
  `phase2_resolvability.py:179` adds a horizon span FROM the statement date, so a
  fabricated January shifts every relative deadline by up to a year, and the
  whole point of VP-16 is that a wrong statement date flips whether a prediction
  came true. Using the true year with a wrong day trades one wrong answer for a
  quieter one.

  So the repair needs a DECISION rather than more research: either
  `statement_date` gains a companion precision field, or the resolver learns to
  take a year-only statement date, or each of the five gets its exact date found
  by hand. The first two are schema changes and that rail was not granted for
  this run.

  The condition that brings it back: the operator picks one of those three. The
  evidence is already gathered and reproducible with
  `.venv/bin/python scripts/statement_date_evidence.py --only bill-gates,jeff-bezos,andy-jassy,lisa-su,vlad-tenev,arvind-krishna`.

- **Re-checked 2026-10-11: still WAITING, but the predicted merge has already
  happened.** All seven investors are still `predictions` only in
  `membership.json`, so the bring-back condition is unmet. Data
  `sources/aliases.json` changed between the curated blocks at `cd7225a0` and
  the manifest rebuild at `f13cd3e4` (2026-09-19). For example,
  chamath-palihapitiya gained `Capital`, `Palihapitiya` and `Social`, and
  david-sacks gained `Craft`, `David`, `Sacks` and `Ventures`, exactly as
  predicted below, at no measured blinding cost. Re-curate the blocks when one
  of the seven is promoted.

- **Discovery will re-pollute the seven's curated alias lists, and it costs
  nothing.** Filed 2026-09-18. `discover_sources.aliases_for()` honours
  `GENERIC_COMPANY_WORDS`, but that set holds `cloud`, `labs`, `technologies` and
  the like, not `capital`, `social`, `craft` or `ventures`. So the 2026-09-18
  discovery run wrote these into `discovered.json`, and the next
  `sources_to_manifest.py` will merge them into the hand-curated blocks:

  ```
  chamath-palihapitiya  would add  Capital, Palihapitiya, Social
  david-sacks           would add  Craft, David, Sacks, Ventures
  vinod-khosla          would add  Khosla, Ventures
  tom-lee               would add  Lee, Tom
  ```

  MEASURED, and this is why it is filed rather than fixed: the merge adds ZERO
  incremental blinding damage for all seven. Every one of those words is already
  redacted by the NAME and COMPANY paths, so the curated list and the merged list
  remove exactly the same words from a probe paragraph:

  ```
  chamath-palihapitiya  curated ['social','capital']  merged ['social','capital']  added []
  david-sacks           curated ['craft','ventures','sacks']  merged same  added []
  tom-lee               curated ['lee']  merged ['lee']  added []
  ```

  So the curation was never buying a smaller blast radius; it was buying a list
  that says what it means. Widening `GENERIC_COMPANY_WORDS` to cover these is NOT
  the fix, because that set is shared with the leaders blinder and changing it
  re-blinds a corpus under 2,260 grades.

  The condition that brings it back: promoting any of the seven to the leaders
  board, at which point the whole company-string question reopens and is already
  recorded against each person in `data/roster/final.json`.

## Grader validation

- **`validate_grader.py` says it "mirrors aggregate.py's own gates" and no
  longer does.** Filed 2026-10-11. It was last changed on 2026-09-06, and
  `load()` has drifted from `aggregate.py` in four ways since then. (1) It
  drops a GRADE whose own subject share is under `MIN_SUBJECT_SHARE`, while
  `aggregate.filter_unscorable` drops a whole RECORDING when the judges' mean
  share is under the cutoff or any judge says 0, the rule `docs/agents/SCORING.md`
  records with its measured cost. (2) It skips `_raw/` and not `_obsolete/`.
  (3) It applies no board membership. (4) It swallows any unreadable grade or
  transcript file (`except Exception: continue` and `pass`) and reports
  nothing. No test covers it and no loop runs it, so nothing published reads
  it today, but its V1-V5 figures are quoted as grader validation. The
  condition that brings it back: the next time its numbers are quoted or
  re-run. Then make `load()` call aggregate's own loaders and filters rather
  than restating them, which is the drift this entry records.

## Site rendering

- **`test_log_bloat.py` reads repo-0's LIVE production checkout, so it goes red
  while repo-0 is mid-rebuild.** Filed 2026-10-11. Its market-cache section
  takes `production_path(REPO)`, the shared `verbatim-index/data` the daemons
  write, not this clone's `data` link. At 04:00 PDT the suite at `c323fb8`
  reported `FAILED scripts/test_log_bloat.py`: "9 of 1124 accepted records
  lack consensus status, cutoff or searched_at_utc". All 9 are in the shared
  checkout, jack-dorsey 8 and bill-gurley 1, all `not_searched`, beside
  repo-0's uncommitted `_experiments/rebuild-20261011/`. This clone's data
  checkout has none, and the check passed here earlier the same night, 13/13.
  It is the same class as the render check above: a suite verdict that
  depends on data another agent is writing. NOT changed, because a
  provenance check on production data is the point of that section. The
  condition that brings it back: a second red from it that is not a rebuild
  in progress. Then split it into a fixture proof and a named LIVE DATA check,
  as `test_render_integrity.py` was.

  **Update 2026-10-11, repo-0: this red was a TRUE POSITIVE.** The 9 records
  are the VP-5 remainder that repo-0 integrated in data `a8212d25`, and the
  integration skipped `market_consensus.py`, which the 2026-10-10 rebuild had
  run. They were committed and deployed without market provenance, so the red
  would have stayed after the rebuild finished. Fixed by running
  `market_consensus.py --leaders jack-dorsey,bill-gurley --router-exclude
  claude,claude_e`: 9 attempted, 9 `no_match`, 0 errors, 5 Fable matcher calls.
  The test then printed `13 passed, 0 failed`. The check did its job. The
  integration step (`integrate.py` in an experiment folder) is where the gap
  is: anything that adds accepted records must run market consensus before
  commit.

- **RESOLVED 2026-10-11: the derived-number proof runs on a fixture, and the
  live render is its own named data check.** The bring-back condition was met:
  the same data-caused red was recorded again in 9aad5a6 (2026-09-17), e7f056e
  (2026-09-19) and f6ea3f8 (2026-09-20, another session), each time filed as a
  code failure. `test_the_method_section_counts_the_roster` now aggregates the
  file's own synthetic corpus and renders it against two roster sizes, reading
  nothing under `data/`. Mutation check: with `roster_n = 4` typed into
  `build_site.py`, "a roster of 11 renders as 11" and "the two renders
  disagree" both fail, `22/25 passed`. The live render is
  `test_this_clones_data_renders`, every check prefixed `LIVE DATA:` and its
  message saying to pull before blaming code; it also asserts the page's count
  equals the roster people on the leaders board in `membership.json`, 50 today.

- **`test_the_method_section_counts_the_roster` renders against whichever data
  checkout the clone is linked to, so the suite's verdict is clone-dependent.**
  Filed 2026-09-17. The check in `scripts/test_render_integrity.py` reads
  `REPO/data/results.json`, `results_audit.json`, `logs/calibration.json` and
  `roster/final.json`, which is each clone's OWN private data link rather than
  a fixture. It proves a real property: the page's "A roster of N" is derived
  from the roster and is not a literal, shown by rendering the same results
  against two rosters of different sizes.

  What it cost here: repo-1's private roster still carried the Amjad Masad
  exclusion-list contradiction that repo-0 fixed in production on 2026-09-16 at
  data `b55217a9`. `bash scripts/run_tests.sh` therefore reported
  `FAILED scripts/test_render_integrity.py` in this clone while the published
  board was correct and every other clone was green. The message named the real
  problem, `REFUSING: seated on the roster and named on the exclusion list at
  once: Amjad Masad`, so the canary worked; it was filed under a code test.
  Fixed by taking the production file, not by changing the test.

  NOT changed, deliberately, and this is the decision to revisit. Two readings,
  and they disagree. A render from self-contradicting inputs SHOULD fail, so a
  stale clone failing is arguably correct. Against that, a suite whose result
  depends on private data is not reproducible across clones, and this repo
  already holds `leaders_baseline.py` and `test_site_social_and_exclusions.py`
  as proof that the same property can be proven on a fixture with no data link
  at all. Bring it back the next time a clone goes red for a data reason: if
  that happens twice, move the derived-number proof onto a fixture and keep the
  live render as a separately named data-staleness check, so the two failures
  stop sharing one line.

## Shared fetcher

- **WITHDRAWN 2026-09-17: "`fetch_loop.sh` runs 10.8x over the documented
  request ceiling."** Filed earlier the same day and wrong in its conclusion. It
  read the loop's `PACE=2 WORKERS=6` as a trap that caused the P6 pilot block.
  Two things contradict it. The loop's own comment says the pace is deliberate:
  "Fetch fast, trip early, ask for a new IP." And the measurement taken after
  filing: at one request every 6 seconds on one worker, four IPs still blocked
  after 60, 14, 14 and 9 fetches. The caption endpoint enforces a per-IP volume
  budget, so pace does not decide when a block arrives, and a fast pace simply
  finds the block sooner. Nothing to fix in the loop. `pacing_warning()` in
  `fetch_transcripts.py` now says the same thing and no longer claims the pace
  caused a block.

## Verbatim Pundits

- **Pundits grading on prepaid API credit waits on the operator.** Filed
  2026-10-18 by repo-3. `quotapick run` (the router's only way to spend a credit
  pool) runs Fable with tools removed, on an API key, with no sandbox wrapper.
  Contract v2's `judge_requests.fable` names `sandbox_exec_deny_container`, and
  `judge_requests` is part of the hash that makes the contract ID. So a credit
  grade filed under today's contract ID would claim a sandbox it never ran in.
  If instead the contract is amended to name the credit harness, the contract ID
  changes, `grade.py` reads all 312 pundits grades (156 Fable, 156 Gemini) as
  `stale_cache`, and `aggregate.py` refuses to mix contracts, so the whole pilot
  is graded again (about $380 by the 2026-10-18 estimate). Options: (A) keep
  pundits grading on the subscription harness, at no cost; (B) amend the contract
  and re-grade; (C) decide after the CI-11 drift experiment in
  `data/experiments/fable-credit-drift-20261018/` shows whether credit-served
  Fable scores match subscription-served ones. Recommend C, because B spends
  $380 to answer a question CI-11 answers for free. Comes back when CI-11 has
  results.

- **`extract_predictions.py` takes no `--study`.** Filed 2026-10-18 by repo-3.
  Nothing stops a pundits run from writing into the leaders data repo: the
  pundits prediction pilot of 2026-10-18 was written to the leaders
  `predictions/_experiments/` and then moved by hand to the pundits data repo's
  `experiments/predictions-pilot-20261018/`. Fix: `study_profile.add_study_arg` and `study_profile.guard(args.study,
  out)`, as the speaker script does, with a test that a pundits run into a leaders
  path refuses. Quota-free.

- **RESOLVED 2026-10-12, same night, with option (a): when the published inputs differ
  from HEAD the footer says "plus uncommitted changes" and revision.json records
  `data_uncommitted`. Option (b) stays the operator's call. The pundits page names the
  HEAD data commit while it renders the daemon's uncommitted output.** Filed 2026-10-12, from an independent review of that
  night's commits. Owner mode (`deploy_pundits.sh`) renders results.json and grades
  as they sit in repo-3's data checkout, which the grading loop writes without
  committing. The footer and `verbatim:data-revision` meta say "data revision X of
  <X's commit date>", so a page built from grades added after X names a commit that
  does not reproduce it. `revision.json` does carry `content_sha256`, the input
  fingerprint, so the deploy guard is not fooled; only the reader-facing stamp is.
  Options: (a) the deploy states "plus uncommitted grades" when
  `git status --porcelain` shows the published inputs dirty, and records it in
  `revision.json` (cheap, honest, needs one test); (b) refuse a deploy with dirty
  inputs, so the daemon commits and pushes before publishing (strongest, but it
  changes repo-3's routine and needs the operator). Recommend (a). Quota-free.

- **RESOLVED 2026-10-12, same night: the fixture now carries calibration_params, one
  test runs the rescaled path (-12/+12 where raw gives -6/+6), and a missing key or
  missing params refuses. G-judge-lean's calibrated path is untested, and a key miss
  falls back to raw scores silently.** Filed 2026-10-12, same review. `test_pundits_gates.py` gives
  `calibration_params: {}`, so `apply_calibration` returns every raw score. If the
  key `pundits_gates.py` rebuilds (`judge|served_model|shared|dim`) stopped matching
  the one aggregate writes, every judge-lean test would still pass and production
  would quietly compare raw scores. The keys match on the pilot today. Fix: a
  fixture with real `calibration_params` (one judge rescaled), an expected
  calibrated estimate, and a refusal when a used key is missing. Quota-free.

- **`judge_searched` can count a local file read as a web search.** Filed
  2026-10-12, same review; plausible, not seen in data. `grade.py`'s
  `count_gemini_tool_events` puts any completed tool step with a `query`, `Url` or
  `AbsolutePath` parameter into `web_search_queries`, so a `view_file` step would
  count. The error runs toward disclosing more searches than happened, never fewer.
  The `tool_use_counts["web_search"]` branch matches only codex (Astra, dropped);
  agy names its tool `search_web`. Fix: record the tool name per step in grade.py
  and count only search tools; needs a recorded agy transcript with a file step as
  the fixture. Quota-free.

- **A grade_loop.sh render can still replace site-pundits/index.html between the
  deploy's render and its upload.** Filed 2026-10-12. Since that night the
  post-publish confirm fails loudly when it happens (the live page lacks the data
  revision's meta tag), so it is reported, not silent. Removing the race needs the
  deploy to render into its own directory and upload that, or the loop to stop
  rendering while a deploy runs. Quota-free.

- **The pundits page has no evidence drawer; do it after the P7 quote audit, not
  before.** Filed 2026-10-12. The leaders page shows, per person, each judge's
  reasoning and evidence quotes for every graded transcript. The pundits page
  lists each board recording with its link, venue and score (since 2026-10-12),
  but not what the judges wrote. The data is in `results_audit.json`. NOT done,
  deliberately: the quotes would appear credited to a named political commentator,
  and attribution is not yet measured. 89 judge quotes credited to the subject do
  not place in the transcript (entry below), and the P7 quote audit (300 quotes,
  G-attribution-quotes) has not run. Publishing the drawer first would put
  possibly misattributed words beside a person's name. Size: a port of
  `build_site.py`'s drawer into `build_study_site.py`, plus the quote filter that
  the audit decides.

- **RESOLVED 2026-10-12, same night: `aggregate.era_covariate()` (`diagnostics.era_covariate`) fits
  upload date within person; on the pilot, +0.63 points a year, 95% interval -2.77 to 3.49.
  Plan P5's era covariate is not implemented.** Filed 2026-10-12. P5 "Sampling
  rules": "The board reports era as a covariate, and a sensitivity analysis
  excludes archival subjects." The archival sensitivity exists since 2026-10-12
  (`diagnostics.archival_excluded`; on the pilot it moves no score). Era does not:
  nothing fits recording year. It needs a definition first (upload year from
  `yt_upload_date`, or years before the subject's last recording), then a fit
  shaped like `venue_effects()`: an additive person + era model, reported and not
  applied. Quota-free.

- **An unsupported dimension removes the whole recording, though the plan says
  it should still count toward the dimensions it supports.** Filed 2026-10-11,
  found while asking why `asmongold/asmongold-tv-ks77-g` is missing from
  `results.json` despite four schema-valid grades. Three of its four grades
  mark `d1_steelmanning` `unsupported` (fable/blinded, gemini/blinded,
  gemini/open). `aggregate.py` marks each such grade `_excluded =
  "unsupported_dimension"`, which removes the whole grade, and then
  `drop_partial_panels` drops the fourth, fully supported fable/open grade as
  an incomplete panel. The recording contributes to no dimension. The plan
  says otherwise: `docs/PUNDITS-PLAN.md`, "Anchors and minimum evidence", has
  "A transcript with any unsupported dimension has no `overall`. It still
  counts toward each dimension it supports. Ranking by overall uses only
  transcripts with all three dimensions supported." Re-running today's
  `aggregate.py --study pundits` on a scratch clone of data-pundits at
  `dced184` reproduces the committed result: 154 transcripts, the same one
  partial panel, and `grades_excluded_unsupported_dimension 3`, so the loss is
  counted rather than silent. The panel report's reason, "incomplete panel:
  missing fable/blinded, gemini/blinded, gemini/open", never says the cells
  were removed for an unsupported dimension.
  Size today: 3 grades, 1 recording. NOT fixed, because the change moves the
  published pundits board and pundits scoring is repo-3's lane. Per-dimension
  counting also has to decide what a partial panel means per dimension: here
  d1 has one supported cell out of four, while d2 and d3 have all four. The
  condition that brings it back: the pundits full grade, or a second recording
  with an unsupported dimension. The reporting half is DONE the same night:
  `drop_partial_panels` now names a cell removed earlier and why, so the
  report reads "missing gemini/open (removed: unsupported_dimension)".
  Re-aggregating a scratch clone of data-pundits with the old and new code
  gives results identical apart from that text.

- **FIXED IN CODE 2026-10-11; repo-3 must re-grade 4 recordings (8 blinded
  grades).** `blind_study()` now leaves a surname, or a caption corruption of
  any part of the name, alone when a DIFFERENT person's given name stands right
  before it. The given name must be on `scripts/given_names.txt`, a frozen copy
  of `/usr/share/dict/propernames` (sha256 recorded in the file), and must not
  be the subject's own given name in any form, by prefix, spelling or consonant
  skeleton, nor a word-like entry such as "Will", "The" or "Sir". A bare title
  ("Governor Walsh") is still redacted. Leaders `blind()` is untouched:
  664 of 664 leaders files blind identically under the old and new module.
  MEASURED over the whole pundits corpus by re-blinding all 367 files with
  both versions (the old one reproduces every file on disk, 367 of 367): 14
  files change, keeping Tim Walz 16 times, Marco Rubio 4, Josh Shapiro 2,
  Jimmy Kimmel 2, Jim Mattis 2, Jeff Walz 2, Alan Cullison 2, and Harvey
  Weinstein, Victor Davis Hanson, James Comey, Narendra Modi and one unknown
  "Tony Tima". The first version accepted any capitalised word and leaked the
  subject 40 times ("Love Megan", "Camille Foster" for Kmele, "Uh Asmond");
  `test_pundits_blinding.py` now holds those as cases, and a mutation back to
  that rule fails 4 of 28. ONE KNOWN RESIDUAL: Mehdi Hasan introduces himself
  as "I'm Mary Hassen" in the captions of
  `mehdi-hasan/al-jazeera-english-bwb6x8`, and "Mary" is a real given name, so
  that one surname is now left in. It is ungraded.
  For repo-3 after pulling: the next pundits normalize rewrites those 14
  blinded files. Four are graded, `ben-shapiro/ben-shapiro-ahi_t9`,
  `ben-shapiro/ben-shapiro-mtbfmw`, `matt-walsh/matt-walsh-9bcva6` and
  `matt-walsh/matt-walsh-7zhqm9`, two blinded grades each, and `grade.py`
  will report those 8 as `stale_cache` and exit 1 until they are re-graded
  with `--force`.

- **The blinder turned two OTHER people's names into [SUBJECT].** Filed 2026-09-19,
  found while building the quote check. Tim Walz became "Tim [SUBJECT]" 8 times in
  `matt-walsh/matt-walsh-9bcva6` (Walz fuzzy-matches Walsh), and Josh Shapiro became
  "Josh [SUBJECT]" twice in a Ben Shapiro recording (an exact surname). A judge then
  reads "[SUBJECT] is a bad guy ... a total creep" as the subject describing himself.
  Small: 10 occurrences in 2 recordings. Fixing it means re-blinding those two and
  re-grading them, because their input hash moves. The leaders board measured blinder
  defects of this kind as not moving scores; do it before the full grade, with a
  failing-then-passing case for a first name followed by the subject's surname.

- **RE-MEASURED AND PARTLY FIXED 2026-10-11; one decision left for the
  operator.** Three matcher misses are fixed in `pundits_verify_page.py`, each
  test-first in `test_pundits_verify_page.py`. First, `[AFFILIATION]` is now a
  placeholder, standing for up to five words. Second, `_norm()` strips quote
  marks at word edges and treats curly apostrophes as straight, so a judge's
  'Oh, you love war.' matches the captions' "Oh, you love war.". Third, an
  empty quote is counted as `empty`, not as a quote the matcher missed.
  Re-run of `suspect_quotes()` over the 312 live grades:

  ```
  against transcripts/       located 3159  not_located 128  empty 3   (was 3153 / 137)
  against transcripts_open/  located 3198  not_located  89  empty 3   (was 3192 /  98)
  ```

  The 137 depended on the folder: the judges read the normalized text, where
  loops are collapsed. Of the 89 left against `transcripts_open`, 84 share at
  least 80% of their three-word sequences with the transcript, and 5 share 73
  to 77%. All 5 were read in context, and every one is a judge tidying the
  captions, never a paraphrase. Two dropped a filler ("uh", "yeah"), one
  joined a caption-split number ("71,9 54" to "71,954") across both modes, and
  one corrected a caption typo ("healthare"). 86 of the 89 are Gemini. A
  matcher that also skipped fillers and immediate repeats would place 29 of
  the 89. That is not done, because it makes "located" fuzzier and the
  remaining 60 differ in more varied ways. THE DECISION LEFT: does a quote with
  fillers removed or a caption error corrected count as verbatim under the
  rubric? If it does, these are matcher misses. If not, they are rubric
  violations by the judge, and so mostly Gemini's.

- **137 judge quotes credited to the subject do not appear in the transcript.** Filed
  2026-09-19. Of 3,290 subject quotes, `pundits_verify_page.locate` found 3,153; 137 (4%)
  it could not place even allowing for [SUBJECT] tokens and "..." elisions. Some are
  paraphrase, which the rubric forbids ("verbatim from the transcript"); some may be
  matcher misses. Not yet read one by one. The quote cap and the minimum-subject-quotes
  rule both assume quotes are real.


- **The 25-word quote cap is uneven. RESOLVED 2026-09-16 by moving the PENALTY,
  not the number.** Filed 2026-09-16, measured the same day, decided by the
  operator during the P9 top-up run.

  The cap limits how much of the transcript a judge may paste back as evidence.
  The judge always read the whole transcript. Until now one over-long quote
  appended a validation error, which invalidated the whole record and threw away
  the score, the reasoning and both other dimensions.

  Measure the incidence any time with:

  ```
  .venv/bin/python scripts/filter_incidence.py --logs data-pundits/logs/p8a2 \
      data-pundits/logs/p8a --obsolete data-pundits/grades/_obsolete \
      --match "exceeds 25 words" --attempted 50
  ```

  Across eight P8a2 rounds it rejected **24** grades:

  ```
  by judge   fable 5 (5.0%)   gemini 19 (19.0%)     ratio 3.8x, flagged SKEWED
  by cell    gemini/blinded 12, gemini/open 7, fable/open 4, fable/blinded 1
  ```

  The P9 top-up then showed WHERE it bites. All four rejections in its first 69
  calls landed on `d3_good_faith`, for both judges and two different people. D3
  asks whether a person applies one standard, answers the question asked, and
  concedes when warranted. None of that is showable in one sentence, because it
  takes a back-and-forth to demonstrate a shift of position. D1 and D2 are
  showable in a single claim. So the penalty selected D3 grades for quote
  brevity, on the dimension carrying 0.30 of the overall score. The audit put
  that selection at +1.07 points (se 0.77, n=24).

  **THE FIX, and why it cost no re-grade.** `grading_contract.quote_overruns()`
  now records each over-long quote with its dimension, word count, speaker and a
  head of the text, and `validate_v2` no longer rejects for it. `grade.py` writes
  them to the record as `quote_cap_overruns`, and `aggregate.quote_cap_report()`
  publishes the incidence by judge and by dimension, so the cap still reports
  what it cut. The number 25 stays in `profiles/pundits.json`, `RUBRIC.md` and
  the schema, all of which are hashed; only the consequence moved, and it lives
  in code no hash covers. VERIFIED: `contract_id` is still `3844dd2693acd471`,
  so the 267 grades already collected stay poolable. Guarded by
  `scripts/test_quote_cap_handling.py`, 24 checks, verified failing first.

  **Known cost, stated rather than hidden:** the corpus now mixes two regimes.
  Grades collected before this change survived reject-and-regrade, so their D3
  quotes are selected for brevity; grades after it are not. `quote_cap` in
  diagnostics is how a later reader tells the two apart.

  CLOSED 2026-10-11, the condition below is not met. Of 312 live grades, 49
  were collected after this change and 6 recorded an overrun, at 26, 26, 26,
  26, 30 and 31 words. The overruns are one to six words, not large, so the
  cap stays at 25 and no re-grade is needed. The sample is small; re-count it
  with the `filter_incidence.py` line above after the full grade.
  Still open: raising the number itself to 40 would move the contract to
  `7aa8f163de1f0b2e` and re-grade everything. Not done, and not needed unless
  the recorded overruns turn out to be large rather than one or two words.

- **LEADERS HALF FIXED 2026-10-11 as an opt-in: `grade.py --regrade-invalid`.
  Turning it on is the operator's call.** Counted in the shared leaders data:
  35 records failed validation while still carrying an attempt at scores, 26
  with `dimensions` and 9 in a judge-invented shape with `overall`. Six more
  failed validation as refusals or non-answers ({reason, status}, {error},
  {limitation}), and those stay put by the refusal rule in
  `docs/agents/JUDGES.md`. With the flag, a malformed record is moved under
  `grades/_obsolete/` byte for byte and graded again, and the queue's depth
  ordering and its "not yet on disk" count include it. Without the flag nothing
  changes, which keeps the leaders-reuse check in `test_pundits_contract.py`
  green. `grade_loop.sh` does not pass the flag, and a test pins that. It is
  opt-in rather than default because default-on would make repo-0's daemon
  spend about 35 calls and move the published board on its next code pull.
  `aggregate.py`, `coverage_table.py` and now `wrong_person_screen.py` all skip
  `_obsolete/`. Guarded by `scripts/test_leaders_regrade_invalid.py`: 6 of 12
  failed before, 16/16 after. The note below that names
  `test_profile_leaders_identity.py` is stale; no such file ever existed. The
  plan's identity check was built as `scripts/leaders_identity_compare.py`
  over two `scripts/leaders_baseline.py` runs, and leaders `blind()` identity
  was also checked directly, 664 of 664, in the other-person entry above.
  TO TURN IT ON: one manual pass from repo-0, `grade.py ... --modes blinded
  --regrade-invalid`, or add the flag to `grade_loop.sh`'s grade call.

- **A grade record that failed validation counts as a cache hit. FIXED for
  pundits (v2) 2026-09-16; LEADERS (v1) still has it.** Filed 2026-09-16.
  `_v2_stored()` in `scripts/grade.py` returned `cached` whenever the stored
  record's identity matched (study, contract, prompt, input, mode, judge, model,
  run). It never asked whether the stored record was a usable grade, so a record
  with `validation_errors` was skipped forever on re-runs and the cell could only
  be repaired with `--force`. Found live: 6 Gemini cells that failed the 25-word
  quote cap in P8a were reported `CACHED` when scheduled again, which would have
  left six permanent holes in a two-judge panel. It now treats a record with
  validation errors, or with no scored dimensions, as absent, moves it to
  `_obsolete/` and says so. Guarded by the check "a stored grade that failed validation is not reused as a cache hit" (no function of the name `check_invalid_record_is_not_reused` exists; corrected 2026-10-11) in
  `scripts/test_pundits_contract.py`.
  (An earlier version of this entry named the function `reuse_or_none()`, which
  has never existed in this repo. I invented it while writing a test and then
  quoted my own invention back here as if it were the code. Check the name
  against `grep` before filing, not against memory.)
  **Still open: leaders (v1) uses a plain `dest.exists()` check and has the same
  hazard.** Its fix is the same shape but it is not the same code path, and any
  change there must keep `test_profile_leaders_identity.py` at 0 differences.

- **RESOLVED 2026-10-11, by a different rule than the one proposed below.**
  `blind_study()` now redacts a HANDLE in any case in the subject's own
  recordings; affiliations ("Twitch") keep the capitalised-only rule. The
  corpus-spread signal was measured and answers the wrong question: lowercase
  "destiny" has spread 0.65 over the pundits corpus, but about 13 of the 30
  uses outside Steven Bonnell's recordings are other pundits naming him, and
  17 are "manifest destiny" or "the destiny of America". Blinding acts only on
  the owner's recordings, and there 16 of 16 lowercase uses are the person
  ("promo code destiny", lowercase auto-captions). Destiny is the only
  single-word handle on the roster that is a dictionary word. Re-blinding all
  367 pundits files changes exactly one, `steven-bonnell/destiny-bklnf_`, 16
  substitutions, 0 grades, so nothing goes stale. `test_pundits_blinding.py`
  asserted the old behaviour; that check now asserts the new one and failed
  first.

- **Blind lowercase uses of handles that are ordinary words.** Filed 2026-09-15.
  `blind_study()` redacts a handle that is an ordinary English word only where it is
  capitalised, so "Destiny" goes and "destiny" stays. Captions write names in
  lowercase often: `steven-bonnell/destiny-bklnf_` kept "destiny" 16 times in its
  blinded copy, including a sponsor URL "slash destiny". That recording is excluded
  as not political, and none of the 20 P8a picks leaks, so P8a is unaffected. Fix it
  before the P8 full grade: for a handle, the corpus-spread signal used by
  `scripts/build_blind_wordlist.py` can decide when a lowercase use means the person.
  Needs a failing-then-passing test and a re-blind of any affected transcripts.

- **RESOLVED to the target of 12, re-checked 2026-10-11; the entry below is
  stale.** Of the 89 verified pilot recordings, 78 hold all four valid grades
  (2 judges x 2 modes, no refusal, no validation error), which is 312 cells
  ok and 44 missing. The 11 left are 10 Ben Shapiro recordings and
  `asmongold-tv-2vktfl`, and both people are already at 12, as data `bd7edf2`
  records ("P9 top-up ... target of 12"). `results.json` counts 77, not 78,
  because `asmongold-tv-ks77-g` marks `d1_steelmanning` unsupported in three of
  its four grades; see the next entry. The full 39-person roster is a separate job:
  `logs/p6b/report.json` says `INCONCLUSIVE | 207 recordings await human
  verification`, and none of the 29 newer people is graded.

- **Grade the rest of the verified pilot recordings.** Filed 2026-09-15,
  re-counted 2026-09-16.
  The P6 pilot verified **89** recordings across 10 people, not 93, and the panel
  is **two** judges, not three, so both figures in the first version of this entry
  were wrong. Counted from `data-pundits/logs/pilot/report.json`:

  ```
  ana-kasparian 6   asmongold 13   ben-shapiro 22   charlie-kirk 5   coleman-hughes 7
  ezra-klein 7   hasan-piker 8   matt-walsh 8   sam-seder 7   steven-bonnell 6
  ```

  P8a graded 20 and P8a2 tops up to 5 each, which is 50. The remaining **39**
  cost about **156 calls** (39 × 2 judges × 2 modes). Schedule them with
  `schedule.py build --target-per-person 12 --graded ... --verified ...`, which
  counts what is already complete rather than adding a fixed number; 12 is the
  P5 target. Note the pool is very uneven: Ben Shapiro has 22 verified and
  Charlie Kirk has 5, so a target of 12 leaves a reported shortfall for most
  people and the equal-format-weighting question (option c in
  `docs/PUNDITS-PLAN.md`) has to be settled against that imbalance, not assumed
  away.
