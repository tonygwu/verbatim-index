# Backlog

Work deliberately deferred, with the reason and the condition that brings it back.
Newest first.

## Board membership (P1 shipped, P2 pending)

Reviewed 2026-09-17 against `docs/plans/board-membership-2026-09-16.md`, at
`240d472` with the whole suite green (`bash scripts/run_tests.sh` -> `failed: 0`).
P1 itself is sound and nothing reads `membership.json` yet, so none of this moves
a published number today. Every entry below is P2's, and each one is a place the
plan was right when it was written and the tree has moved since.

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

  NOT fixed here, because P2 is not implemented and the floor is a design choice
  the plan owes a number and a reason. Two candidate derivations, both cheap:
  count the membership leaders board (`len(slugs_on(data, "leaders"))`, 50 today
  and 50 after P3, which is the number the board is supposed to hold), or compare
  against `len(leaders) + len(unranked)` and leave `unscored` out. Decide it
  before writing the `deploy.sh` guard, and change
  `test_data_clone_workflow.py:177-178` in the same commit: its fixture writes
  `{"leaders": [], "diagnostics": {...}}` with no `unranked` or `unscored` key at
  all, so a floor reading those keys raises `KeyError` there rather than failing
  the assertion the plan expects.

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

## Shared fetcher

- **`fetch_loop.sh` (leaders) runs 10.8x over the documented request ceiling.**
  Filed 2026-09-17. `PACE="${PACE:-2}"` and `WORKERS="${WORKERS:-6}"` give one
  caption request every 0.33s. The yt-dlp wiki documents a guest session at one
  every 3.6s. `fetch_transcripts.py` now prints its effective rate at startup and
  warns with the numbers, so the next leaders run says so out loud:

  ```
  PACING: 2.0s across 6 workers is one request every 0.33s (10800/hour).
  ... This configuration is 10.8x over that ceiling. The P6 pilot ran at 0.33s
  and took six retry passes to clear the block.
  ```

  NOT changed here, because the loop passes `--min-interval` explicitly and its
  operational tuning belongs to repo-0. The fetcher's own default is fixed
  (2.0 -> `DEFAULT_INTERVAL` = 6.0). Both leaders sources are currently
  exhausted, so nothing is fetching and this is not urgent; fix it before the
  next discovery run. Evidence that it bites: the pundits P6 pilot at these
  settings produced 202 IP blocks in 218 first-pass errors and needed six retry
  passes.

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
