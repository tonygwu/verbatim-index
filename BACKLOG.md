# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Board membership (P1 shipped, P2 pending)

Reviewed 2026-09-17 against `docs/plans/board-membership-2026-09-16.md`, at
`240d472` with the whole suite green (`bash scripts/run_tests.sh` -> `failed: 0`).
P1 itself is sound and nothing reads `membership.json` yet, so none of this moves
a published number today. Every entry below is P2's, and each one is a place the
plan was right when it was written and the tree has moved since.

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

- **The floor the plan proposes for `deploy.sh` refuses publication for ever on
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

- **The plan's P2 test inventory counts `aggregate.py` invocations and never
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

- **Every `file:line` in the plan's P2 section is stale, and one of them now
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

- **After P2, `membership.json` is a render input that the deploy fingerprint
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

## Site rendering

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

  Still open: raising the number itself to 40 would move the contract to
  `7aa8f163de1f0b2e` and re-grade everything. Not done, and not needed unless
  the recorded overruns turn out to be large rather than one or two words.

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
  `_obsolete/` and says so. Guarded by `check_invalid_record_is_not_reused` in
  `scripts/test_pundits_contract.py`.
  (An earlier version of this entry named the function `reuse_or_none()`, which
  has never existed in this repo. I invented it while writing a test and then
  quoted my own invention back here as if it were the code. Check the name
  against `grep` before filing, not against memory.)
  **Still open: leaders (v1) uses a plain `dest.exists()` check and has the same
  hazard.** Its fix is the same shape but it is not the same code path, and any
  change there must keep `test_profile_leaders_identity.py` at 0 differences.

- **Blind lowercase uses of handles that are ordinary words.** Filed 2026-09-15.
  `blind_study()` redacts a handle that is an ordinary English word only where it is
  capitalised, so "Destiny" goes and "destiny" stays. Captions write names in
  lowercase often: `steven-bonnell/destiny-bklnf_` kept "destiny" 16 times in its
  blinded copy, including a sponsor URL "slash destiny". That recording is excluded
  as not political, and none of the 20 P8a picks leaks, so P8a is unaffected. Fix it
  before the P8 full grade: for a handle, the corpus-spread signal used by
  `scripts/build_blind_wordlist.py` can decide when a lowercase use means the person.
  Needs a failing-then-passing test and a re-blind of any affected transcripts.

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
