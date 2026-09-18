# Explicit board membership

## Context

Three boards publish from one engine: leaders (`verbatim-index.tonygwu.com`,
graded, contract v1), predictions (`verbatim-predictions.tonygwu.com`, same data
directory, records scored against market baselines) and pundits (a separate
contract-v2 **study**, own private repo, live in repo-3).

**Nobody is a member of anything today.** `grade.py` scores every file under
`--transcripts`; `--roster` is optional and only fills open-mode speaker names.
`aggregate_predictions.py:147` unions roster slugs with any slug that has records.

That hole cost something. A sentence written by an agent during the roster
finalize step on 2026-09-05 — "Pure investors and commentators are out", under
`tie_break_rules` in `data/roster/final.json` — became a governing rule by being
quoted three times. No code read it. The operator never approved it. It blocked
seven people from the predictions board.

### Outcome

Membership becomes explicit and is read by the pipeline. Seven investors join
**predictions only**: Cathie Wood, Marc Andreessen, Chamath Palihapitiya, David
Sacks, Bill Gurley, Vinod Khosla, Tom Lee. `verbatim-index` does not move.

**Nine adversarial review passes.** Passes 1 to 8 each returned "not sound as
written" and the plan was rewritten after each. Pass 9 returned **CONVERGED, no
serious findings**, and independently re-derived both requirements rather than
trusting pass 8's measurement. The architecture has been stable since pass 3;
later passes found coverage gaps and two of my own fixes pointing the wrong way,
not design faults.

Every claim in this plan carrying a number or a `file:line` was verified in the
working tree, not taken from a review agent. Two agent claims were wrong on
checking and are corrected here: the extraction-cache count (0 of 671, not 11 of
693) and the tip of `origin/main` (`2f02346`, not `01ba57c`).

## REVISION 2026-09-18: P1, P2 and most of P3 are BUILT. Read this before the plan.

Everything below this section is the plan as approved. It is still the reasoning
of record. Four of its claims are now wrong, and two phases are done, so read
this first.

### What landed

  P1  membership.json (58) and scripts/membership.py            240d472, 50aeaac
  P2  three readers, study-scoped through membership.for_study  239f934, 851909b,
                                                                5549f15, 23ff9e4
      the publication floor                                     62e79f5
      the pre-push audit, docs/MEMBERSHIP-P2-AUDIT.md           899493b
  P3  the seven appended at ranks 51-57, bench corrected        data ea1ba9ca
      their alias blocks, curated and measured                  data cd7225a0
      a grade-free identity screen, scripts/identity_screen.py  ee27927

**The leaders board did not move.** aggregate before and after: results.json
identical as whole objects apart from two added diagnostics keys, 50 leaders, 0
ranks or scores changed. The rendered page is byte-identical. Evidence and the
commands are in `docs/MEMBERSHIP-P2-AUDIT.md`.

### Four claims in this plan are wrong

1. **"`market_consensus.py` is public-API only, no model calls" is false.**
   `scripts/market_consensus.py:53` imports `agy_profiles` from `grade`, and
   `:605` takes `--matcher {auto,fable,astra,gemini}` with `auto` as the default.
   Treat the stage as spending until somebody measures it with the matcher
   pinned off. Anyone planning P4 under a no-spend constraint will otherwise
   read this plan and get it wrong.

2. **The proposed `deploy.sh` floor, `len(leaders) + len(unranked) +
   len(unscored)`, refuses publication for ever from P3.** That sum is the
   ROSTER; `deploy.sh` counts only the scored. The two diverge the moment a
   roster member is not scored, which P3 causes deliberately and a withdrawal
   causes by accident. The operator decided on 2026-09-17 to derive the floor
   from the PREVIOUS PUBLISHED COUNT instead; see `scripts/publication_floor.py`.

3. **Every `file:line` in the P2 section is stale**, and two of the moves matter
   rather than being bookkeeping. `roster_n` lives inside `build_method()`, not
   `main()`, so membership has to be passed down; and the word count now reads
   `transcripts_blind`, not `transcripts`, so the plan's measured-no-op
   arithmetic must be recomputed rather than quoted.

4. **The P2 test inventory counts `aggregate.py` invocations and never
   `build_site.py`**, which is one of the three readers. MEASURED: 7 files broke,
   not 5, and 6 of them inherit one seam through
   `test_render_integrity.run_aggregate`. Two `build_site` fixtures also wrote
   transcripts with no `leader_slug`, which the plan's own rule requires.

### What P3 broke that the plan does not anticipate

Adding seven people to the roster broke four counts that derive from its length,
and one of them was fatal. `fetch_loop.sh` exits when
`leaders_at_target >= leaders`; with 57 in the denominator and at most 50
reachable it could NEVER complete and would have re-fetched YouTube for ever.
`status.sh`, `coverage_table.py` and `fetch_happyscribe.py --report-unsearched`
were the other three. All four are fixed and the rule is now in `AGENTS.md`: a
count derived from the roster is not a count of the board.

### Still open

- **P3 discovery has NOT run.** repo-3's pundits fetcher was IP-blocked on this
  machine, so a crawl from the same address would have failed and could have
  deepened it. The pinned command is in `docs/MEMBERSHIP-P4-STATUS.md`, and
  `--only` is now enforced by `discover_sources.py` itself rather than by
  discipline alone.
- **P4 has not started.** Extract, verify and market consensus all spend; the
  publish is a deploy. `docs/MEMBERSHIP-P4-STATUS.md` has the order, the
  commands, and one hazard P3 created: the predictions index now unions the seven
  in, and a page built without `--scores` would claim 57 people.
- **Both operator questions remain.** The identity screen now exists and is
  grade-free, which changes question 1 from "build, review or accept the risk"
  into "review the screen's output". The investor rule is scoped rather than
  rewritten, recorded in `data/roster/final.json` under
  `investor_rule_scoped_2026_09_18`.

## REVISION 2026-09-16 (later the same day): what changed after approval

Thirteen commits landed after this plan was approved, none of them from this
workstream. Of the ten files the plan cites, **only `build_site.py` moved**:

```
roster_n = len(roster["roster"])      :803  ->  :815
tdir = ... / "transcripts"            :1067 ->  :1079
```

Everything else still holds, re-verified. The P0 bugs are all still live:
`dedupe_transcripts.py:334` is still `rglob(f"{r['retired']}__*.json")`, and
`name_in("Hollywood stars", Cathie Wood)` is still True.

**`data/transcripts_web/` now EXISTS and is proven.** The plan invented it as the
root the grader never reads. It was created on 2026-09-16 for a different stream
(repo-1's supplemental predictions corpus) and now holds real transcripts. So P4
inherits a directory that already works rather than one this plan has to argue
for. The rule stands unchanged: web transcripts never enter `data/transcripts/`.

**Six operational findings from placing that corpus, which P4 inherits.** Each
cost a debugging cycle; none is in the original plan.

1. **Place run manifests WITH records, or provenance fails wholesale.**
   `validate_predictions.known_contract_ids` is "current skill contracts plus
   every id a run manifest recorded". Records were placed without their
   `_runs/*.json` and 432 provenance failures followed. Copying 12 manifests
   cleared them. This is the designed mechanism, not a workaround.
2. **A passing validator does not mean a stage ran.** All 93 web records passed
   the `consensus` invariant while carrying `consensus.status = "not_searched"`.
   The invariant checks the field's SHAPE. Read the status, not the verdict.
3. **Skip `_`-prefixed directories when counting anything.** A count that did not
   read `_runs/*_errors.jsonl` as 54 id-less records, which is commit `3578d3f`'s
   defect arriving a second time.
4. **The record schema is NOT hashed into any contract id.** Contracts hash
   `extractor_output.schema.json` and `verifier_output.schema.json`;
   `prediction_record.schema.json` is the validator's and is hashed into nothing.
   An earlier revision of this plan said otherwise and made a one-line fix look
   like a release action.
5. **`candidates_written: null` is backfillable from the line count**, because
   the validator's own rule is that the two match.
6. **Fingerprint production before and after any measurement**
   (`prediction_inputs_sha256`), because other clones write to it concurrently.
   A number measured across someone else's write is not reproducible.

**Two standing items now bear on P4.** `VD-4a` is the operator's standing
direction to bias toward admitting predictions, so a marginal admit/withhold call
goes to admit and gets recorded. `VP-20` has the index page's link to the
predictions board switched off (`SHOW_PREDICTIONS_LINK = False`,
`build_site.py:778`) until that board is fuller; restoring it is one word and
should be coordinated with, not separate from, the P4 deploy.

**`market_consensus` has never run on any web-sourced record.** It is a
prerequisite for a clean corpus and it is public-API only, no model calls.

## Citations verified at `b8a8a73`

The plan was drafted against a tree 8 commits behind. **repo-0 has since been
pulled and every load-bearing citation re-verified at `b8a8a73`:**

```
grade.py:265   from quota_router import select_account      (still lazy, inside fable_accounts)
grade.py:2063  paths = sorted(Path(args.transcripts)...)    (was :2035)
grade.py:2092  all_dirs, headroom, ... = fable_accounts()   (was :2064)
aggregate.py:740  grade_files_read = len(grades)            unchanged
aggregate.py:831  usable = grades                           unchanged
aggregate.py:839  accounted = len(excluded) + ...           unchanged
build_site.py:803 roster_n = len(roster["roster"])          unchanged
build_site.py:1067 tdir = ... / "transcripts"               unchanged
dedupe_transcripts.py:334  rglob(f"{r['retired']}__*.json") unchanged
deploy.sh:38  print("about to publish {len(led)} leaders")  unchanged
```

Only `grade.py` moved, by 28 lines, and **the ordering the gate depends on still
holds**: the transcript list is loaded at `:2063`, before the router call at
`:2092`.

**repo-2 commits to `main` actively** — it moved twice during the review. Pull and
re-check these before each phase.

## The decisive design rule

> **Membership decides what is READ, never what is WRITTEN.**

An earlier draft had membership gate normalize's writes. That makes a config file
an input to a delete path: `prune_orphans` deletes a derived copy this run did
not write, and `--grades` orphans the matching grades. The guard needs BOTH
`len(stale) >= 10` and `frac > 0.25`, and 153 of 664 is 23.0% — under the ceiling.
Measured hole: ten omitted leaders deletes 153 transcripts and orphans **514
grades** silently.

*Membership* therefore touches no writer. P0-4 does change
`normalize_transcripts.py`, for an unrelated defect.

## Design

### Membership is LEADERS-ONLY and must be scoped

`grade.py` and `aggregate.py` are **shared by both studies** (`SP.add_study_arg`,
`--study`), and pundits is live: `repo-3/data-pundits/.study` reads `pundits`.
A leaders-only membership file that raises on unknown slugs would raise on every
pundit slug and **stop repo-3's production grading on the first cycle after P2.**

So every membership reader is scoped: membership applies only when
`args.study == SP.LEGACY_STUDY`. For any other study the reader is a no-op.
(Alternative, if you prefer: put `boards` in `profiles/leaders.json`. That is
study-native and safe, because `grading_contract.py:48` hashes only `scoring`,
`identity_treatment`, `blinding` and `judge_requests` into `contract_id`. I kept
the root file to match your earlier choice.)

### The file

`membership.json` at the public repo root, `slug -> boards` only, so no person
metadata leaves the private repo. **58 entries**: the 50, the seven, and
`cc-wei: []`. `cc-wei`'s directories exist but hold no live file: 14 `.json.superseded` on the
shelf, empty directories in both derived trees, and three grade directories
holding 44 `.orphaned` files and zero `*.json`. `aggregate.py` globs `*.json`, so
no reader can reach it today. The entry is insurance against a future
resurrection, not a live contradiction.

`scripts/membership.py` raises on a missing file, malformed JSON, or an unknown
slug; never defaults to empty.

**The lookup shape is specified, because the obvious idioms delete the raise.**
`data.get(slug, [])` and `data.get(slug) or []` both turn an unknown slug into an
empty board. Use `if slug not in data: raise`, then test `"leaders" in data[slug]`
— never `if data[slug]`.

**The empty-board guard splits across three layers, because no single layer knows
enough.** A typo such as `"leader"` for `"leaders"` is valid JSON with no unknown
slug, and would otherwise grade nothing, file all 2,260 grades into `off_board`
with the accounting sum still balancing, render zero leaders, and publish —
`deploy.sh:38` prints the leader count and applies no floor.

- `membership.py`: **structural only.** Malformed JSON, unknown slug, and a board
  name outside a declared whitelist. The whitelist catches the typo at source and
  needs no counts. A hardcoded minimum here would be a typed list, read by three
  scripts, so one stale literal raises in all three on the same cycle and
  `grade_loop.sh:211` prints AGGREGATE FAILED every cycle while the site serves
  the last good build. That is the 2026-09-09 shape returning, and a legitimate
  withdrawal is enough to trigger it.
- `aggregate.py` at `:831`: refuse when the off-board share of `grade_files_read`
  exceeds a ceiling, reporting the count and the share. **Pick the ceiling
  deliberately and record why.** Today the share is 0 of 2,260 and after P3 it is
  still 0, because the seven get no grades. Too tight and `grade_loop.sh:211`
  prints AGGREGATE FAILED every cycle while the site serves the last good build —
  the 2026-09-09 shape, one file away from where the plan refused to put it.
- `deploy.sh` after `:38`: refuse below a floor **derived from `results.json`**.
  The obvious derivation is circular: `len(r["leaders"])` is 0 on an empty board
  and yields a floor of 0. Use the roster size instead, which `aggregate.py:1169`
  writes as `len(leaders) + len(unranked) + len(unscored)` — 50 today.

  **`test_data_clone_workflow.py:177` asserts that a zero-leader board deploys**
  (`'leaders': []`, then `deploy.sh --dry-run`, asserting "published nothing").
  The floor breaks it. **The fixture changes, not the floor.** Writing
  `if led and len(led) < floor` would make the floor skip an empty board, which
  is the one case it exists to catch.

**All 58 are named from P1 onward.** P3 adds roster entries only. Membership
never gates writes, so the seven's blinded copies land before P3 would add their
roster entries, and an unknown-slug raise would fire on the first cycle.

**Every lookup takes the slug from a record, never a path component.**

**`membership.json` is the DEFAULT, `--membership` the override.**
`leaders_baseline.py:24-36` runs the whole chain with hardcoded argv and produces
the byte-identity evidence the pundits study rests on.

The seven get roster entries appended at ranks 51-57. **Invariant:** `final.json`
changes only by appending seven objects to `roster`; every other top-level key
stays byte-identical. **Named exception:** Marc Andreessen is currently in
`bench`. Decide explicitly whether he is removed from it. Nothing reads `bench`,
so the render is safe either way, but the contradiction must not be silent.

### The three readers

| reader | where | why there |
|---|---|---|
| grade | above `fable_accounts()` (`:2092`) | `quota_router` reads the Keychain and spawns `codex app-server`; the transcript list is already loaded at `:2063`, `--single` handled at `:2061`. **Re-assert a non-empty list after the gate**: the existing check at `:2064` runs before it, so a membership file excluding everything exits 0 having graded nothing. Log the dropped count as a taxonomy entry |
| aggregate | at `usable = grades` (`:831`) | **required.** `grade_files_read` is taken at `:740` and `deploy.sh:51` refuses unless it equals the on-disk count, so filtering earlier blocks publication for ever. `:831` is upstream of `calibrate` (`:877`), `transcripts_out` (`:900`), `venue_effects` (`:926`) and the bootstrap |
| site | `build_site.py:815`, word count (`:1079`) | **read `leader_slug` and decide membership OUTSIDE the `try`** at `:1070-1074`, which is a bare `except Exception: pass`; a raise inside it silently drops the transcript from `__N_WORDS__`. Narrow the except to `JSONDecodeError` and `OSError` |

Add an `off_board` bucket to the accounting sum at `:838` and to `diagnostics`,
**and add it to the failure message at `:843`, which already omits
`partial_report`.** Adding a bucket to the sum but not the message leaves the
operator two buckets short exactly when the guard fires.

### Why this is a measured no-op, not an argued one

Every live grade and both derived trees carry only the 50 roster slugs today:

```
live grade files: 2260 | distinct leader_slug: 50 | NOT in roster: []
transcripts_blind: 51 dirs, 664 files, not in roster: ['cc-wei']   (that dir is empty)
transcripts_open:  51 dirs, 664 files, not in roster: ['cc-wei']   (that dir is empty)
results.json: grade_files_read 2260, leaders 50, unranked 0, unscored 0
```

So with the 50 on the leaders board, the `aggregate.py` filter removes nothing
from `usable` and cannot move a calibrated score. The only two places the render
can still move are the roster count at `build_site.py:803` and the word count at
`:1067`, and both are gated above. Independently re-derived on pass 9.

Two structural facts close the largest remaining render-moving path by
construction rather than by argument. `aggregate.py` touches `args.transcripts`
at exactly one line, `:667`, for `SP.guard`, and never reads a transcript — so
the seven's blinded copies cannot reach `results.json`. And `aliases.json` is
consumed **per slug** (`normalize_transcripts.py:731`, `qa_transcripts.py:278`
both use `.get(slug, [])`), so adding seven alias blocks in P3 cannot change any
of the 50's blinding or `oov_rate`, cannot flip a QA verdict, and cannot orphan
a grade.

## Pre-work (P0)

**1. `sources_to_manifest.py` merge mode, asserting SUBSET containment.**
Re-derivation is a strict subset: `terms only on disk: 14, terms only derived: 0`.
Byte equality would strip `Alphabet`, `Sun Microsystems`, `OpenAI`, `comma.ai`,
`geohot`, `Scale AI` across seven slugs. `aliases.json` is **also the QA glossary**
(`grade_loop.sh:150 --glossaries`); `qa_transcripts.py:142` uses it for
`oov_rate`, which drives the reject verdict, which orphans grades.

The assertion guarantees only that the merge cannot drop those 14. It is a
tautology for the 50, and it deliberately freezes 524 generic-word substitutions
across nine leaders (`Cloud` 274, `Labs` 76, `Platforms`, `Global`). Freezing
them is **correct**: changing them would move the render.

**2. `fetch_happyscribe.py --discover` merge + `--only`.** It crawls the whole
roster and replaces the candidate pool; appending seven slugs triggers it via
`happyscribe_loop.sh:93`.

**3. `dedupe_transcripts.py:334` slug scoping.** The orphan glob matches the
source id alone; `taTBjAZ7GN4` sits under both `greg-brockman` and `lip-bu-tan`.
`--sweep` runs every cycle in two loops with no dry run, so capture the
`--report` pair set before and after and require it unchanged before restarting.

**Also: `dedupe --merge` must stamp `shelf_arrived_at_utc`.** A Happy Scribe
record is fetched into `transcripts_hs` and merged into the shelf on a later
cycle, and `dedupe_transcripts.py:352-361` copies the record's original
`fetched_at_utc`. Twelve such records are pending today, the oldest fetched ten
days ago. Without a shelf-arrival stamp, P0-4 misreads a legitimate merge race as
the bug and refuses.

**4. Normalize must distinguish a QA race from a scoped QA run.**

A naive "refuse if QA does not cover every transcript" fires in normal operation.
Three daemons write the shelf and the QA report with no lock, one blinding pass
takes 50 seconds over 720 transcripts, and the QA report carries no timestamp:

```
summary keys: ['transcripts_examined','verdicts','leaders_with_usable_transcripts',
               'min_usable_per_leader','thresholds']
```

*Fix.* `qa_transcripts.py` stamps `generated_at_utc`, **taken immediately before
the first directory listing at `:271`, not when the summary is built at `:311`.**
The scan takes ~6 seconds; a transcript landing during it would otherwise be both
uncovered and pre-stamp, which is the exact false refusal this repairs.

Normalize then refuses only when an uncovered transcript's `shelf_arrived_at_utc`
(falling back to `fetched_at_utc`) predates the stamp. All 720 shelf records carry
`fetched_at_utc`. Equal-second arrivals are not "predates" and are skipped, which
is the safe direction.

Every way this rule can be wrong is a **false refuse, never a false skip.**

**A report with no stamp refuses, naming the QA command to run.** Every report on
disk today lacks one, in both live studies (leaders, and pundits at 116 reports),
and `run_pipeline.sh:52` and `:60` are independent stages so normalize can meet a
report it did not generate. Skipping the check on a missing stamp would be the
silent fallback this repo forbids. Cost: one manual QA run per study after P0-4
lands.

**Order within P0: the `dedupe --merge` stamp lands strictly before this rule.**
The rule falls back to `fetched_at_utc`, and five Happy Scribe records are pending
today with fetch times up to ten days old. If the rule lands first and one merges
during a QA scan, normalize refuses and that cycle's grading is skipped. It
self-heals on the next cycle and loses nothing, but the order is free to get right.

**This breaks a committed baseline, and the repair must be in the same commit.**
`leaders_baseline.py:120-122` sha256s `logs/transcript_qa.json`;
`PUNDITS-P0-BASELINE.md:39` records it as identical between runs and line 43 says
the allowed-difference list is exactly one field;
`leaders_identity_compare.py:29` is `ALLOWED = ("normalization.normalized_at_utc",)`.
Add `summary.generated_at_utc` to `ALLOWED` and amend
`PUNDITS-P0-BASELINE.md:39` and the two `AGENTS.md` restatements (`:1190`,
`:1277`) together.

There are **five** normalize call sites, not four: `grade_loop.sh:155`,
`fetch_loop.sh:216`, `run_pipeline.sh:61`, `:67`, and `leaders_baseline.py:26`.
The uncounted one is the one that breaks.

**`fetch_loop.sh`'s normalize gains a failure branch that logs loudly and falls
through to the existing sleep.** Not `continue`, which jumps past the barren
accounting at `:226-246` **and** past `sleep "$sleep_for"`, spinning hot and
re-fetching YouTube every iteration. Not `exit`, which kills the run marker, so
`grade_loop.sh:64` reports no source running, idles to `COMPLETE` at `:283` and
publishes if `PUBLISH_ON_COMPLETE=1`.

Also refuse a named-but-absent `repairs` / `aliases` / `qa` file.

## The identity problem, which has no clean answer

`name_in()` matches "Hollywood" for Cathie Wood and "s-**lee**-ping" for Tom Lee.
But the rule `AGENTS.md` proposes — full name, or surname plus a company token —
was implemented and replayed: `accepted(bad)=8, rejected(good)=2`. The surviving
shapes are co-guest, interviewer and commentary, where the title names the leader
correctly. `company` cannot carry identity: Michael Saylor's is deliberately
falsified to `MicroStrategy` to stop the blinder redacting "strategy".

**And `wrong_person_screen.py` reads `identity_guess` out of grades, which
predictions-only people will not have.** Operator decision below.

## Phases

- **P0** the four fixes (plus the merge stamp), each its own test and commit.
- **P1** `membership.json` with all 58, `scripts/membership.py`.
- **P2** wire the three readers, study-scoped. Update
  `test_render_integrity.py:341-365` deliberately. Add `leaders_baseline.py`.
- **P3** append the seven roster entries; discovery pinned to `--only`
  (**omitting it is destructive**: `discover_sources.py:355` merges only when
  `--only` is passed, otherwise `discovered.json` is replaced by the seven alone
  and `build_site.py:1061` renders it per row); hand-curate the seven's alias
  terms; commit in `data` **before** P4, since `deploy_predictions.sh` requires
  `--data-revision` to equal the data repo's HEAD and `SITE_SHELVES["predictions"]`
  covers `roster/final.json`.
- **P4** fetch, extract, verify, aggregate, deploy predictions. Pin
  `--leaders <the seven>` on `extract_predictions.py` and `market_consensus.py`.
  **`--force` is forbidden.** The `--leaders` pin does double duty:
  `extract_predictions.py:354-359` replaces `meta["extract"]` wholesale for an
  excluded transcript even without `--force`.

Boundaries verified: P2 before P3 and P3 before P4 are both safe.

### P4 REVISED 2026-09-16: it is now three streams, not one

The operator approved supplemental records entering the **rendered** corpus, so
P4 stopped being "add the seven" and became "integrate three independent streams
and re-derive". The streams are the seven new people, repo-1's round-1
supplemental corpus (`corpus-supplemental-gemini`, 17 slugs, which alone carries
five leaders over the floor), and repo-1's round-2 sourcing, which is live.

**THE ONE RULE THAT PROTECTS THE LEADERBOARD, and it is new.**

Web-sourced records need their transcripts on disk, because
`validate_predictions.py:227` reconstructs `<root>/<slug>/<sid>.json` and fails
`transcript_exists` without it. Those transcripts exist today only inside repo-1's
experiment runs, and there are **two** of them, not one. Both need placing and
they are different sets (counted on disk 2026-09-16):

```
round 1  _experiments/supplemental-sources-2026-09-14/transcripts/<slug>/web-*.json
         14 slugs, 89 transcripts. The set behind the five banked crossings.
         All 14 slugs are on the production roster, so this stream creates no
         off-roster predictions rows.
round 2  _experiments/supplemental-round2-2026-09-16/transcripts/<slug>/web-*.json
         in progress; 3 slugs, 21 transcripts so far.
```

Both are on branch `codex/repo-1-data-2026-09-14` in repo-1's private clone.
repo-1 places neither; repo-0 does, after repo-1 pushes and reports the SHA.

Transcript ids are `web-<host>-<8 hex of sha256 of the URL>`, which is why they
cannot collide with the YouTube or Happy Scribe shelf.

**They must NOT be placed in `data/transcripts/`.** If they are,
`normalize_transcripts.py` derives them, `grade.py` grades them, `calibrate()`
pools them, and all 50 `verbatim-index` scores move. That is the exact mechanism
this whole plan exists to prevent, arriving from a direction the first nine
review passes never considered, and it would look like tidiness to whoever did
it. They go in a root the grader never reads: `data/transcripts_web/<slug>/`,
with `validate_predictions.py --transcripts` pointed at it.

`validate_predictions.py` takes ONE `--transcripts` root and there will be two
corpora, so either run it twice or add multi-root support;
`phase2_resolvability.load` already has that shape.

**Sequence, serialised, repo-0 only.** records land -> `aggregate_predictions.py`
refresh -> `score_predictions.py` **with `--trend`** -> build -> deploy.
`--trend` is not optional: the published board uses it, and omitting it scores
114 instead of 117 and drops Aaron Levie and Dara Khosrowshahi off the board,
which reads as the supplemental corpus deleting two unrelated leaders' scores.
That false signal is repo-1's measurement, not a hypothetical.

**Why the records are safe to merge.** `prediction_id` is derived from the
transcript id plus the normalised quote, and the web corpus has entirely distinct
transcript ids, so the merge is additive with no double-counting. Round-2 records
carry release `predictions-2.2` (`extract bf5f8441c54f`, `verify be28981b6b8b`),
which is what main pins, so they do not reintroduce a contract mix. repo-1 pinned
`--verifier gemini`, the stricter bar: Fable accepts 0.545 against Gemini's 0.297.

**This resolves open question 2.** The three-way choice disappears, because the
corpus grows regardless and the scores must be re-derived. Re-deriving also
disposes of the `scores.json` provenance problem, since a fresh run replaces
bytes that currently exist only as an uncommitted change in repo-2's clone.

## Tests

`test_aliases_subset`, `test_hs_discover_merge`, `test_dedupe_slug_scope`,
`test_normalize_qa_race` (both arms), `test_normalize_refuses_missing`,
`test_membership` (unknown slug, `cc-wei: []`, empty-board refusal),
`test_grade_membership_gate`, `test_aggregate_off_board_bucket`,
`test_membership_study_scope` (a `STUDY=pundits` run is unaffected).

The grade-gate test uses the tripwire PATH from `test_study_isolation.py:192`
**plus** `QUOTA_ROUTER_CODEX_BIN`: the router hardcodes `/opt/homebrew/bin/codex`
and never searches PATH.

**The slug-set assertion is one-way containment — roster slugs are a subset of
membership slugs.** Equality would turn the globbed suite red across P1 and P2,
which trains the operator to ignore it. Put equality in a P3 completion gate.

### The existing suite runs `aggregate.py` on slugs membership will not know

This is the largest piece of P2 work. **Five** leaders-mode test files build
synthetic rosters and shell out, across **eleven** `aggregate.py` invocations:

```
test_render_integrity.py:73    LEADERS = [f"leader-{i}" for i in range(4)]   :213,:227,:254,:255,:273
test_render_integrity.py:347   slug=f"pad-{i}"
test_judge_enumeration.py:52   LEADERS = ["alpha","beta","gamma"]           :118 (x2 under the :115 loop)
test_refusal_ordering.py:68    LEADERS = ["alpha","beta","gamma"]           :132, :154
test_rank_floor.py:44          COUNTS = {"alpha":7,"beta":None,"gamma":None} :72
test_site_ci.py:90-92          roster of "ada","alan"                        :109 (direct, not via the helper)
```

Every one exits nonzero once membership raises on an unknown slug, and
`bash scripts/run_tests.sh` is the verification gate for this whole change.

**Put the fixture `membership.json` and the `--membership` argument inside
`run_aggregate` (`test_render_integrity.py:148`)**, so all four helper callers
inherit the seam from one place, then patch `test_site_ci.py:109` separately.
The seam must be an explicit argument and **never an environment fallback**,
because a fallback is exactly the silently-disabled gate this plan exists to
avoid.

**`build_site.py` must import membership LAZILY, inside the leaders branch.**
`test_deploy_pundits.py:31` builds a synthetic public repo from a typed `SCRIPTS`
tuple and runs `build_site.py` inside it via `deploy_pundits.sh:37`. A
module-level import fails with `ModuleNotFoundError` before the study dispatch at
`build_site.py:1025` can no-op it. The `quota_router` lazy import at
`grade.py:265` is the precedent. Adding `membership.py` to that typed tuple would
be the same stale-list defect this repo has paid for twice.

**`membership.py` owns the default path**, resolved from its own `__file__`.
`test_render_integrity.py:199` writes a modified copy of `aggregate.py` into a
temp directory; a `Path(__file__)` default written inside `aggregate.py` would
resolve into that temp directory and fail, while one inside `membership.py`
resolves correctly because `PYTHONPATH` still points at the real `scripts/`.

Dropped: `test_open_mode_isolation` — it passes today, because `aggregate.py:1027`
already filters `usable` to blinded. A test that cannot fail first is not a test.

## Pre-push audit

Renders are hash-seed deterministic and the page reads a clock in exactly two
places. **Render before and after, diff whole files, require the diff confined to
the two `__RUNDATE__` lines.** The "before" arm is a fresh `aggregate.py` run.

**Plus the transcript comparison, which is the check that catches data loss.**
Compare `transcripts_blind` and `transcripts_open` before and after:

- **Enumerate the 50 from the P0 git tag**
  (`git -C data show <tag>:roster/final.json`), **never from `membership.json`** —
  the artifact under test cannot be its own oracle.
- **Compare parsed JSON field by field, never `diff -r`.**
  `normalization.blind_substitutions` has hash-seed-dependent key order across
  **602 of 664 files**; values and blinded text are stable. Tolerate only
  `normalization.normalized_at_utc`.
- **Compare file SETS.** A QA verdict *flip* adds a file where a withdrawal
  removes one, so direction distinguishes them. There are 56 rejects available to
  resurrect, and a resurrected transcript arrives with no live grade (its grades
  were renamed `.json.orphaned`, and `aggregate.py` globs `*.json`), so the render
  arm cannot see it at audit time. Require the removal set under the 50 to be
  empty or individually explained.
- **Name the required state of all three loops during the audit window.** A
  `pass`-to-`reject` flip looks exactly like a legitimate withdrawal and is caught
  only if nothing writes between the snapshots.

Plus byte-identity of the existing 50's blocks in `discovered.json`,
`aliases.json`, `repairs.json`.

## Safety

- `git -C data tag` before the first run. Both transcript trees (664 each) and
  the grades tree are tracked, so the tag is a real rollback and the audit's
  enumeration source. **The corpus is 2,260 grade files**, matching
  `results.json diagnostics.grade_files_read`; `git ls-files grades` returns
  4,826 because it counts `_raw` judge transcripts and 330 `.orphaned` files.
  Comparing 4,826 against the `deploy.sh:51` gate reads a corpus half missing.
- **Rollback reverts roster AND transcripts together.**
  `normalize_transcripts.py:719` refuses a transcript whose slug has no roster
  entry, inside the write loop, so removing the seven while their transcripts
  remain wedges the grade loop every cycle.
- Stop `happyscribe_loop.sh` across P3 and P4.
- `data/predictions/scores.json` is untracked and not mine. Its exact bytes exist
  only as an uncommitted working-tree change in repo-2, and the committed version
  differs on `leaders_ranked` (9 against 15). It fills the live Score column.
  Stage by name only.

## Open questions for the operator

1. **The seven have no identity screen.** Options: human review of roughly 84
   transcripts before extraction; build a grade-free detector; accept the risk.
2. **The predictions Score column has no staleness gate.** P4 forces a three-way
   choice: publish a denominator excluding the seven, re-run and publish a worse
   ratio with nothing re-resolved, or spend on resolution and priors. The run
   directory needed to re-derive is in repo-2's experiment clone, not production.
   Sharpening: `build_predictions_site.py:1105` derives `__N_PEOPLE__` from the
   live index and would print 57 while a frozen `scores.json` masthead still says
   15 of 40. Nothing refuses that combination.
3. The wording of the retired investor rule: predictions-scoped or retired
   outright.

## Known follow-ups, out of scope

`status.sh:73`, `coverage_table.py:204`, `happyscribe_loop.sh:115`,
`fetch_loop.sh:183` mix roster-derived and on-disk counts. `deploy.sh:46` and
`aggregate.py:216` disagree about `_obsolete`. `sources_to_manifest.py:105` and
`discover_sources.py:362` write non-atomically. `prediction_inputs_sha256` is
blind to roster and transcript changes. `p4d_fable_tools_off.py` sampling drifts
as the blinded corpus grows. QA name-density rejection of podcast hosts bites in
P4.

## On approval

Written to `docs/plans/`, committed and pushed, so repo-2 and repo-3 see the
restructuring before it starts. **repo-3 must be told directly**, because P2
touches code its pundits production runs.
