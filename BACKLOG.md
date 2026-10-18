# Backlog

Deferred work, one item per heading, in the format the `backlog-protocol`
skill reads and `/run-backlog`, `/improve-code` and `/improve-data` work from.
Items are independent: claim one, finish it, delete it. The protocol itself
(claims, IDs, the difficulty ladder, deletion on completion, the pre-push
review) is that skill; this file holds the parameters that are specific to
this project, and the items.

Until 2026-10-18 this file was a prose ledger: each entry held the reason a
piece of work was deferred and the condition that would bring it back, and
settled entries stayed in place as the record. The settled, withdrawn and
resolved entries are archived verbatim in
[docs/BACKLOG-RESOLVED.md](docs/BACKLOG-RESOLVED.md). An entry whose
bring-back condition still holds is an item below with a `[BLOCKED: ...]` tag
naming that condition; an entry deferred only to ride along with the next
change to its file is an ordinary item.

## Protocol parameters

| Parameter | Value in this project |
|---|---|
| Item files | this file, `## Open items` below; shard into `backlog/<shard>.md` with a routing table in `backlog/README.md` when it passes a few dozen items |
| ID scheme | `VI-<n>` (Verbatim Index), one counter for the file. Next ID = 1 + the highest `VI-` number in this file **and** its git history, because a deleted ID never returns; the command is under this table. Ledger IDs (`VP-`, `VD-`, `CI-`) are a different series, in `docs/LEDGER-*.md` |
| Difficulty ladder | `low`, `medium`, `high`, `xhigh`; `ultra/workflows` is split into normal items when filing. The skill's § 5 maps the running model to a row; claim at or below it |
| Agent handle | `#<n>` from a `repo-<n>` clone directory (`repo-0` is `#0`). Commit subjects: `claim: VI-n (#<n>)`, `backlog: delete VI-n (#<n>)` |
| Priority | file order within `## Open items`: the first unclaimed, unblocked item in the file whose Background's first sentence does not name another clone's lane is the next one to take. Read that sentence before the claim, and never claim a lane item from another clone. Unblocked items come first and `[BLOCKED: ...]` items last, so the picker never reads past an eligible item to reach them. A lane item goes at the head of the unblocked run, so the one clone that can do it reaches it first and every other clone skips it in one read; any other new item goes at the end of the unblocked run unless it must be done sooner |
| Validation gate | `bash scripts/run_tests.sh` from the clone root, the whole output kept, `failed: 0` required. Never pipe it through `tail -1`: the per-file `FAILED <path>` lines are the finding. `test_log_bloat.py` and the `LIVE DATA` checks in `test_render_integrity.py` read the leaders daemon's live checkout, so a red there is reported with its text, never retried until green (VI-12) |
| Pre-push review | `adversarial-self-review` on `origin/main..HEAD` before every push, verdict `ship` required, two fix rounds at most |
| Blocked tag | `[BLOCKED: <what lifts it>]` on the heading. Two kinds: an operator decision, or a measurement or event that has not happened. Nobody claims a blocked item, and the loop never lists one, so a lane is never a block: an item that only one clone can finish (`repo-0` pushes the leaders data repo's owner paths and deploys the leaderboard; `repo-3` does the same for pundits; AGENTS.md, "Clone roles") says so in the first sentence of its Background, and an agent on another clone skips it without claiming, and releases if it claimed before reading. Whoever lifts a block deletes the tag in its own commit and writes the lane sentence for the option chosen |
| Completion | delete the item; git history is the record. A decision or measurement worth keeping goes in the `docs/agents/` file of its topic, under "Rules that exist because something broke" or "Experiments run", never back into this file |
| Doc-gap routing | a standalone `low` item |
| Scan logs / ledgers | `backlog/scan-logs/improve-code/<shard>.md` and `backlog/scan-logs/improve-data/<domain>.md`, tracked, created when those modes first run here |
| Data read path (`improve-data`) | none named: `improve-data` stops |
| Names in items | roster slugs, recording ids and public figures named in the roster or the transcripts are the data's own keys and may appear; no email address, phone number, private person's handle or message text, ever |

The highest ID used so far, in this file and its history; the next ID is this plus one. Derive it at write time after the pull, never earlier:

```bash
{ grep -oE '^### VI-[0-9]+' BACKLOG.md; git log -p --all -- BACKLOG.md | grep -oE '^\+### VI-[0-9]+'; } | grep -oE '[0-9]+$' | sort -n | tail -1
```

## Item format

The skill's § 3, repeated here so a filing agent has it in front of it:

```markdown
### VI-<n>. <one-line problem statement>  `[difficulty: <level>]`  `[filed: YYYY-MM-DD]`  `[BLOCKED: <what lifts it>]`?

**Background:** first sentence, when only one clone can finish the item: which clone, and why. Then what the code or data does today and where; at least one `file:line`. For a doc item, the stale sentence verbatim.

**Impact:** the concrete consequence.

*Root cause:* optional.

**Fix:** `low`/`medium`: one paragraph. `high`+: numbered steps tied to files, tests included.

*Risks and edge cases:* required for `high`+.

*Why <level> not <level-1>:* required for `high`+.

**Touch points:** every `file:line` the fix will modify, tests included.

---
```

The `filed:` date is the UTC calendar date the item was first written down,
kept from the ledger entry it came from, and never updated. "Filed by repo-N"
in a Background is provenance, not a claim and not a lane.

## Open items

### VI-16. The pundits predictions scale-up left three recordings unverified, one unexplained, and the speaker-check page without the model drafts  `[difficulty: medium]`  `[filed: 2026-10-18]`

**Background:** Only the pundits daemon clone, repo-3, can finish this: it pushes `data-pundits` owner paths, which `data_sync.py push` refuses from any other clone, so an agent on another clone skips it. It spends Gemini quota. Filed by repo-3. The scale-up finished 257 of 261 recordings (pundits data `089ac14`, `experiments/predictions-pilot-20261018/README.md`). (1) `brett-cooper-fxe9zz`, `conversations-with-tyler-cusdy0` and `jordan-b-peterson-rkt9up` need re-verifying: Gemini returned `empty_response` after a denied `RunCommand` on every pass. `bret-weinstein-bmwp9g` cannot be extracted on credit: the CLI also sent its prompt to `claude-opus-5` three times, and `credit_run` refuses a mixed-model answer; why is not known. (2) The speaker-check page should carry the model drafts: `scripts/pundits_verify_page.py build` takes `--drafts` (`:16-31`, `load_drafts` at `:341`), to be run with `data-pundits/logs/p6b/speaker_inference.jsonl` and the same `--grades` and `--quote-key` as before, then the pundits data pushed; 65 flagged recordings list first.

**Impact:** Three recordings have extractions nobody verified, one person has none, and the labelling page does not show the drafts that were paid for.

**Fix:** From the pundits daemon clone: re-run verify on the three (Gemini quota only); record the `bret-weinstein-bmwp9g` refusal with its raw answers in the run's README rather than retrying blind; rebuild `data-pundits/logs/p6b/speaker_check.html` with `--drafts` and push with `data_sync.py push --daemon`. The review nits that came with this entry are VI-3.

**Touch points:** `data-pundits/experiments/predictions-pilot-20261018/` (README and the three records), `data-pundits/logs/p6b/speaker_check.html`, `scripts/pundits_verify_page.py:16-31` (read only).

---

### VI-20. Four graded pundits recordings carry blinded grades of text the blinder no longer produces  `[difficulty: medium]`  `[filed: 2026-10-11]`

**Background:** Only the pundits daemon clone, repo-3, can finish this: the grades are `data-pundits` owner paths, which `data_sync.py push` refuses from any other clone, so an agent on another clone skips it. It spends judge quota, about 8 calls. `blind_study()` (`scripts/normalize_transcripts.py:531`) was fixed on 2026-10-11 to leave another person's surname alone when a different given name stands before it (the archived entry "FIXED IN CODE 2026-10-11; repo-3 must re-grade 4 recordings", `docs/BACKLOG-RESOLVED.md`, Verbatim Pundits, holds the measurement: 14 of 367 blinded files change). Four of the 14 are graded, `ben-shapiro/ben-shapiro-ahi_t9`, `ben-shapiro/ben-shapiro-mtbfmw`, `matt-walsh/matt-walsh-9bcva6` and `matt-walsh/matt-walsh-7zhqm9`, two blinded grades each. Checked 2026-10-18 in repo-3's `data-pundits`: all eight blinded grades still date from 2026-09-15 to 2026-09-17, before the fix. The next pundits normalize rewrites the 14 blinded files, and `grade.py` will report those 8 as `stale_cache` and exit 1 until they are re-graded with `--force`. `docs/PUNDITS-RELEASE-PLAN.md:49-51` names this step.

**Impact:** Until the re-grade, the pundits grading loop exits 1 on every cycle after the normalize, and four board scores rest on text in which a judge read "Tim [SUBJECT]" for Tim Walz.

**Fix:** From the pundits daemon clone: run the normalize, then `grade.py --study pundits --force` on the eight cells, then aggregate; record the before-and-after scores in `docs/PUNDITS-RELEASE-PLAN.md`, beside the step at `:49-51` that names this re-grade. One known residual stays: `mehdi-hasan/al-jazeera-english-bwb6x8` keeps "Mary Hassen", a caption corruption after a real given name; it is ungraded.

**Touch points:** `data-pundits/transcripts_blind/` (the 14 files), `data-pundits/grades/{fable,gemini}/{ben-shapiro,matt-walsh}/` (the 8 cells), `docs/PUNDITS-RELEASE-PLAN.md:49-51`.

---

### VI-1. `extract_predictions.py` takes no `--study`, so a pundits run can write into the leaders data repo  `[difficulty: medium]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3. `scripts/extract_predictions.py:747-781` declares every argument and none is `--study`; `--out` defaults to `data/predictions` (`:749`), `--transcripts` to `data/transcripts_open` (`:747`) and `--roster` to `data/roster/final.json` (`:748`), all leaders paths. The speaker script has the guard this needs: `scripts/pundits_speaker_infer.py:337` calls `study_profile.add_study_arg` and `:344` calls `SP.guard(args.study, str(root))` (`scripts/study_profile.py:95` and `:146`). The pundits prediction pilot of 2026-10-18 was written to the leaders `predictions/_experiments/` and moved by hand to the pundits data repo's `experiments/predictions-pilot-20261018/`. `docs/agents/PUNDITS.md:178` tells a pundits extraction to pass every path by hand for this reason.

**Impact:** Nothing stops a pundits run from writing pundits records under the leaders data checkout, where `data_sync.py push` and the leaders predictions aggregate treat them as leaders data.

**Fix:** Add `study_profile.add_study_arg` to the parser and `study_profile.guard(args.study, <out>, <transcripts>, <roster>)` in `main()` before any write, the way the speaker script does. A new check, in `scripts/test_predictions_credit.py` or a new `scripts/test_extract_predictions_study.py`, runs `--study pundits` with a leaders `--out` and asserts the refusal, failing first. Update `docs/agents/PUNDITS.md:178`, which says the extractor has no `--study` yet. Quota-free.

**Touch points:** `scripts/extract_predictions.py:747-781` (parser), `:875` (`main`), `scripts/study_profile.py:95`, `:146` (read only), `scripts/test_predictions_credit.py` or a new test file, `docs/agents/PUNDITS.md:178`.

---

### VI-2. `pundits_speaker_infer.py merge` writes `checked_by: model:<model>` for both harnesses, so the merged store hides which drafts ran on credit  `[difficulty: medium]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3, from the round-2 review of the credit runs. `infer` writes subscription drafts and `--credit-pools` drafts (`scripts/pundits_speaker_infer.py:331`) to the same `speaker_inference.jsonl`, and `merge_drafts` (`:297`) writes `"checked_by": f"model:{model}"` (`:315`) for both. Each draft's `telemetry` block (`:215`) does name the harness, `quotapick run` for a credit draft, so nothing is lost in the drafts file; the merged human store cannot tell them apart. All 218 P6b drafts are credit drafts today.

**Impact:** A reader of the merged store, or of a page built from it, cannot say which harness drafted a row, and VD-19 records that nobody has measured whether the two harnesses draft alike.

**Fix:** `merge_drafts` names the harness beside the model in `checked_by` (for example `model:claude-fable-5-1 (quotapick run)`) or in a field of its own, read from each draft's `telemetry.harness`, and refuses a draft with no harness rather than defaulting one. A check in `scripts/test_pundits_speaker_infer.py` merges one subscription draft and one credit draft and asserts the two rows differ, failing first. Quota-free.

**Touch points:** `scripts/pundits_speaker_infer.py:297-315`, its docstring at `:18-23`, `scripts/test_pundits_speaker_infer.py`.

---

### VI-3. `extract_predictions.main()`'s `code_revision_of` call is untested, and two speaker scripts record HEAD without a `+dirty` mark  `[difficulty: medium]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3 as the review nits of 2026-10-18 round 4. `scripts/extract_predictions.py:890` passes `L.REPO / "scripts"` and the skill directory to `code_revision_of` (`:813`), which appends `+dirty` when either path holds uncommitted changes. `scripts/test_predictions_credit.py:295` and `:305` test the function, but nothing tests the call, so dropping `skill` from it passes the suite. `scripts/speaker_audit_page.py:225-226` (`git_revision`, used at `:286`) and `scripts/speaker_segment_probe.py:176` record `git rev-parse HEAD` as `code_revision` with no dirty mark at all.

**Impact:** A speaker audit or probe run from an edited tree records a revision that did not produce it, the defect `code_revision_of`'s own docstring records (8 pundits pilot metas named one commit and ran another's code), and a regression in what `main()` hashes passes the suite.

**Fix:** (1) A check that drives the run-record builder in `extract_predictions.py` with a stubbed `code_revision_of` and asserts it receives both the scripts directory and the skill directory. (2) The two speaker scripts append `+dirty` when `git status --porcelain` on their own paths is non-empty, the way `code_revision_of` does; one check per script in `scripts/test_speaker_audit_page.py` and `scripts/test_speaker_segment_probe.py`, each failing first against a scratch repository with an edited file. Quota-free.

**Touch points:** `scripts/extract_predictions.py:813-830`, `:890`, `scripts/test_predictions_credit.py:295-305`, `scripts/speaker_audit_page.py:225-226`, `:286`, `scripts/speaker_segment_probe.py:176`, `scripts/test_speaker_audit_page.py`, `scripts/test_speaker_segment_probe.py`.

---

### VI-4. `index.json` counts credit extractions as plain `fable`, so it cannot tell the two Fable harnesses apart  `[difficulty: high]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3, from the adversarial review of `--credit-production` (e267bef). `scripts/aggregate_predictions.py:99-118` (`acceptance_by_harness_pair`) keys the extraction-harness breakdown on the record's `extraction.harness`, which stays `fable` for a credit call so that the different-family rule in verify still holds; the harness that actually ran is in `extraction.telemetry.harness` (`quotapick run`). On a copy of the pundits pilot, the 182 reviewed credit records (of 184; 2 have verification `not_run`) came out as one row, `extraction_harness: "fable"`. A second count has the same fault: `coverage.by_harness.extract`, which `summarise_meta` (`:130-138`) builds from each meta's `extract.harness`, read `{"fable": 280}` for the pilot's 280 credit transcripts. Meta files carry no telemetry, but their `router_account_id` starts with `credit:` for a credit run (260 of the 280).

**Impact:** `data/predictions/index.json` cannot show how many extractions ran on prepaid credit against how many on the subscription harness, and VD-19 says nobody has measured whether the two extract alike, so the one derived file that could show the mix hides it.

**Fix:**
1. In `acceptance_by_harness_pair`, key the extraction side on `extraction.telemetry.harness` when it is present and on `extraction.harness` otherwise, and name the credit rows distinctly (for example `fable (quotapick run)`); keep the raise at `:115` for a reviewed record with no harness.
2. In `summarise_meta`, split `by_harness.extract` on whether `router_account_id` starts with `credit:`.
3. A check in `scripts/test_predictions_aggregate.py` builds one subscription and one credit record and one meta of each kind, and asserts two rows and two counts, failing first.
4. Regenerate `index.json` with `scripts/data_sync.py push` on the next data push (it is a derived file; its bytes change); `scripts/test_derived_determinism.py` must stay green.

*Risks and edge cases:* `test_predictions_policy.py`, `test_predictions_index_roster.py` and `test_predictions_site_policy.py` read `index.json` fixtures and may pin the old row shape. `build_predictions_site.py` may read `verifier_acceptance_by_harness_pair`; if it does, the page copy that names harnesses needs the new label.

*Why high not medium:* the naming of the harness key is a judgment call that `docs/agents/PREDICTIONS-PIPELINE.md` and the site copy will quote, and the derived file is read by four test files and the site builder.

**Touch points:** `scripts/aggregate_predictions.py:99-118`, `:130-138`, `scripts/test_predictions_aggregate.py`, `scripts/build_predictions_site.py` (if it reads the pair table), `docs/agents/PREDICTIONS-PIPELINE.md` (the index.json description).

---

### VI-5. `grade.call_fable_pool` and `credit_run.run` each check the served block, and two copies drift  `[difficulty: high]`  `[filed: 2026-10-18]`  `[claimed by: #2]`

**Background:** Filed by repo-3. Both landed the same night from two concurrent sessions. `scripts/grade.py:1163` (`call_fable_pool`, repo-0) is the judge path: one pool, Fable at max effort, labels from grade.py's taxonomy, served checks at `:1211-1216`. `scripts/credit_run.py:96` (`run`, repo-3) is the general path for the pundits speaker drafts and `extract_predictions.py --fable-credit-pools`: a SET of pools for the router to choose among, any model and effort, its own labels, served checks in `check_response` (`:63-93`). They check the same `served` fields today. The ledger deferred this until the CI-11 drift experiment, which imported `grade.py` from repo-0's working tree, had finished; `docs/LEDGER-corpus-integrity.md:23` records CI-11 stopped after day 1 with its day-2 arms cancelled, and on 2026-10-18 no process from `data/experiments/fable-credit-drift-20261018/` was running.

**Impact:** The next change to one identity check (a new served field, a new quotapick outcome) silently leaves the other behind, and a credit grade can then pass one path's check and fail the other's for the same response.

**Fix:**
1. Make `call_fable_pool` call `credit_run.run(prompt, model=..., effort="max", pools=[pool], ...)` and map `PoolsExhausted` and `CreditRunError` onto grade.py's labels (`E_CLI`, `E_MODEL_MISMATCH`, `E_IDENTITY`, `E_POOL_REFUSED` at `scripts/grade.py:81-123`), so the telemetry block it returns (`:1223-1228`) is unchanged.
2. `scripts/test_fable_pool.py` and `scripts/test_credit_run.py` both stay green; add one check that a served-field mismatch produces the same label through both entry points, failing first against a stubbed `credit_run.run`.
3. `docs/agents/JUDGES.md` names the one call path.

*Risks and edge cases:* `call_fable_pool` takes a `spent` tally and a `request_id` (`:1163-1165`); keep them. `FABLE_POOL_MAX_TIMEOUT` (`:1154`, `:1181`) must still refuse a longer timeout before any call. `grade_loop.sh` never passes `--fable-pool`, so production is untouched.

*Why high not medium:* two modules, two test files and a label mapping that decides what the run summary's taxonomy says about a refused credit call.

**Touch points:** `scripts/grade.py:81-123`, `:1163-1228`, `scripts/credit_run.py:63-136`, `scripts/test_fable_pool.py`, `scripts/test_credit_run.py`, `docs/agents/JUDGES.md`.

---

### VI-6. A Fable stage of `resolve_predictions.py` with no `--fable-accounts` runs on the default account  `[difficulty: high]`  `[filed: 2026-10-11]`

**Background:** Filed by repo-0. `scripts/resolve_predictions.py:518` declares `--fable-accounts` with `default="default"`, and `:561-569` turns that into the account list for the `prior` and `lead_test` stages. `--stage lead_test` with no `--fable-accounts` ran its one call on `~/.claude` (`accounts=['default']` in `rebuild-20261011/lead_test-1.log`); it served `claude-fable-5-1` and cost $0.21. Nothing failed, but the operator has said account A has no Fable, and batch Fable work is meant to go to the accounts named for it. `scripts/grade.py:277` (`fable_accounts`) already routes by measured quota through `quota_router` when `FABLE_ACCOUNTS` is unset (`:2569`). The ledger deferred this to the next change to `resolve_predictions.py`.

**Impact:** A Fable stage started without the flag spends the operator's interactive account's quota, on the one account the operator has said should not carry batch Fable work, and nothing in the run summary says so.

**Fix:**
1. Decide between (a) refusing a Fable stage that names no accounts, at the cost that every caller must pass the flag, and (b) routing by measured quota the way `grade.py` does, at the cost that the stage gains the router. Recommended: (b), with the plain `default` account excluded unless named explicitly, because it matches the judge path and the operator's stated intent.
2. Implement it in `scripts/resolve_predictions.py` at `:518` and `:561-569`, logging the chosen accounts at `:733` as today.
3. A check in `scripts/test_predictions_driver.py` or a sibling: no flag, router stubbed, asserts the stage never runs on `default`, failing first.
4. `docs/agents/PREDICTIONS-PIPELINE.md` names the rule.

*Risks and edge cases:* `--fable-pool` (`resolve_predictions.py:524`, `:590`) is a different path (API credit) and must still refuse the other stages. The `ambient` label at `:733` covers a call with no account; keep it honest.

*Why high not medium:* the choice between refusing and routing is a policy decision, and the router import brings `grade.py`'s failure handling with it.

**Touch points:** `scripts/resolve_predictions.py:518-524`, `:561-569`, `:733`, `scripts/grade.py:245-305` (read only), `scripts/test_predictions_driver.py`, `docs/agents/PREDICTIONS-PIPELINE.md`.

---

### VI-7. `judge_searched` can count a local file read as a web search  `[difficulty: high]`  `[filed: 2026-10-12]`

**Background:** Filed from the independent review of the 2026-10-12 pundits commits; plausible, not seen in data. `scripts/grade.py:2027` (`count_gemini_tool_events`) puts any completed tool step with a `query`, `Query`, `url`, `Url` or `AbsolutePath` parameter (`:2055`) into `web_search_queries`, so a `view_file` step would count. The error runs toward disclosing more searches than happened, never fewer. The `tool_use_counts["web_search"]` branch (`:647`, `:700`) matches only the codex harness (Astra, dropped); agy names its tool `search_web` (`:2031-2035`).

**Impact:** A grade's `judge_searched` disclosure, which the page shows beside the score, can say the judge searched the web when it read a file, so the published disclosure overstates what the judge did.

**Fix:**
1. Record the tool name per step in `count_gemini_tool_events` and count only search tools (`search_web` and any name agy documents for web search) toward `web_search_queries`; keep every other step in `tool_use_counts` by name.
2. A fixture in `scripts/test_judge_web_search.py`: a recorded agy transcript with one `view_file` step and one `search_web` step, asserting one search, failing first. The fixture must come from a real agy transcript (the per-grade stderr logs under the data repo's `logs/` hold them), not a hand-written guess at the event shape.
3. `docs/agents/JUDGES.md` says what counts as a search.

*Risks and edge cases:* a transcript with a tool name agy has since renamed would then count zero searches; the check must fail loud on an unknown tool name with a `query` parameter rather than drop it.

*Why high not medium:* the fixture has to be found in real logs and the rule changes a published disclosure.

**Touch points:** `scripts/grade.py:2027-2060`, `:647`, `:700`, `:1340-1343`, `:2231-2232`, `scripts/test_judge_web_search.py`, `docs/agents/JUDGES.md`.

---

### VI-8. A `grade_loop.sh` render can replace `site-pundits/index.html` between the deploy's render and its upload  `[difficulty: high]`  `[filed: 2026-10-12]`

**Background:** `scripts/deploy_pundits.sh:60` renders into `SITE_DIR`, `:137` uploads it with `npx wrangler deploy`, and the loop's own render (`scripts/grade_loop.sh:244-252`, `$SITE_DIR/index.html`) can run between the two. Since 2026-10-12 the post-publish confirm (`deploy_pundits.sh:138-143`) fails loudly when it happens: the live page lacks the data revision's meta tag. So it is reported, not silent.

**Impact:** A deploy that loses the race publishes a page with no revision stamp, then fails its own confirm, and the operator must run it again while the loop keeps rendering.

**Fix:**
1. Either the deploy renders into a directory of its own (a temporary copy of `site-pundits/` with its `wrangler.pundits.toml` pointed at it) and uploads that, or the loop takes a lock the deploy also takes so the loop skips its render while a deploy runs. Recommended: the private render directory, because it needs no change to the loop's routine.
2. A check in a `scripts/test_deploy_pundits*.py` file that writes a different `index.html` into `site-pundits/` after the render step and asserts the uploaded page is the rendered one, with wrangler stubbed, failing first.
3. The leaders deploy (`scripts/deploy.sh`, `scripts/deploy_source.sh:57-67`) has the same shape; say in `docs/agents/SITES.md` whether it is covered.

*Risks and edge cases:* `revision.json` and its `_headers` rule (`deploy_pundits.sh:117-123`) must land in the same directory the upload reads. The dry run (`:134`) must keep rendering into the visible directory so the operator can read it.

*Why high not medium:* it changes the publication path of a live site and touches the deploy guard's assumptions about where the rendered page is.

**Touch points:** `scripts/deploy_pundits.sh:60`, `:107-143`, `wrangler.pundits.toml`, `scripts/grade_loop.sh:244-252`, a new `scripts/test_deploy_pundits_render_dir.py`, `docs/agents/SITES.md`.

---

### VI-9. The labelling guide does not state the "correct every caption error you notice" convention VI-13 depends on  `[difficulty: low]`  `[filed: 2026-10-18]`

**Background:** VI-13 brings back the caption-correction work once 50 operator corrections exist across 10 recordings, made under the convention that every caption error noticed in a reviewed passage is corrected, so that a reviewed word left alone counts as correct. The 2026-10-11 re-check found that convention "written nowhere except this entry, so it has never been in force", and asked for it to go into `docs/PUNDITS-LABELLING-GUIDE.md` before the next session. That guide's "Rules for every label" section (`docs/PUNDITS-LABELLING-GUIDE.md:11-27`) has no rule about the page's "Correct text" field.

**Impact:** Until the convention is written where a labelling session reads it, no session's corrections can count toward VI-13's threshold, and the count (15 over 5 recordings on 2026-10-11) cannot grow.

**Fix:** Add one rule to "Rules for every label": in a reviewed passage, correct every caption error you notice with the page's "Correct text" field, so that a word left alone counts as correct; name the counter, `.venv/bin/python scripts/pundits_text_corrections.py` over the answers files.

**Touch points:** `docs/PUNDITS-LABELLING-GUIDE.md:11-27`.

---

### VI-23. A Fable answer that overran one turn's output cap reaches the extractor as its last continuation chunk, and the failure is filed as `schema_validation_failed`  `[difficulty: high]`  `[filed: 2026-10-18]`

**Background:** `scripts/credit_run.py:125` returns `resp.get("text")` from the `quotapick run` response as the whole answer; `quotapick run` starts one `claude -p` child and returns that child's final `result` field (it has no continuation code of its own); the subscription harness reads the same field (`scripts/grade.py:1145`), and `grade.call_fable_pool` (`scripts/grade.py:1163`, the priors' and credit grades' path) runs its own `quotapick run` and reads it too, so all three Fable paths share the exposure (VI-5, claimed by #2, is moving `call_fable_pool` onto `credit_run.run`). For pat-gelsinger/web-fool-com-335b172e (10,861 words) two credit extractions on 2026-10-18 returned a `text` of 652 and 11,400 characters that starts mid-string (`in the span.","resolution_cr...`): data `predictions/_raw/responses/pat-gelsinger/web-fool-com-335b172e__extract__20261018T053831Z-both-499ae6b1.json` ($4.81, pool c) and `...20261018T080210Z-both-b18c577b.json` ($5.03, pool b). In both, `usage.output_tokens` (64,247 and 68,707) minus the one `usage.iterations[].output_tokens` entry (247 and 4,707) is exactly 64,000, the child's `maxOutputTokens`: the first turn hit the cap and the child continued, and only the continuation's text came back. The extractor parsed a fragment (every schema error is at `$`, a missing top-level field) and failed; the third attempt on the subscription harness gave 21 candidates, 4 accepted.

**Impact:** any Fable answer longer than one turn's cap fails after being paid for, and the failure names the model when the harness is at fault; a grade or a prior would fail the same way.

**Fix:**
1. In `credit_run.run`, after `check_response`, compute `usage.output_tokens` minus the sum of `usage.iterations[].output_tokens`; when the gap is at least the cap (64,000, or the response's own `maxOutputTokens` when present; two continuations leave 128,000) raise `CreditRunError("continuation_truncated: ...")`, counted under that taxonomy label by `extract_predictions.py` and `grade.py`.
2. The same check in `grade.call_fable` for the subscription harness's `result` (`scripts/grade.py:1140-1150`) and in `grade.call_fable_pool` (`:1163`) until VI-5 routes it through `credit_run.run`.
3. A test with a fake `quotapick` binary whose response carries a mid-string `text` and the 64,000-token gap; and one for `call_fable`.
4. Name the label in `docs/agents/PREDICTIONS-PIPELINE.md` beside `credit_pool_exhausted`.
5. Coordinate with VI-5, which edits the same served-block check in `credit_run.run`.

*Risks and edge cases:* a prose answer must never be refused for not starting with `{`; the token-gap signal is the check, and a text-shape check only a hint. A response whose `usage` lacks `iterations` must pass as before.

*Why high not medium:* two harnesses, a taxonomy label other scripts count, and an overlap with a claimed item.

**Touch points:** `scripts/credit_run.py:96-140`, `scripts/grade.py:1140-1170`, `scripts/extract_predictions.py:250-272`, `scripts/test_credit_run.py`, `docs/agents/PREDICTIONS-PIPELINE.md`.

---

### VI-24. `market_consensus.py` caches a 429 or 403 and replays it on every later read  `[difficulty: medium]`  `[filed: 2026-10-18]`

**Background:** `scripts/market_consensus.py:127-142` (`Cache.get_json`) writes every HTTP response to `predictions/_markets/<platform>/<sha>.json` whatever its status, and any later read raises `market_api_error: cached <status>` from the file without touching the network (`:134`); `--refresh-cache` is the only way out and it re-fetches every URL. The docstring at `:25-27` promises "Every HTTP response is cached ... so a rerun is free and reproducible". On 2026-10-18 the first consensus run over 25 people (data `predictions/_experiments/thin-supplement-20261018/market_consensus-1.log`, manifest `predictions/_runs/20261018T090006Z-consensus-fc6e8e7f.json`, 4 workers, 707 HTTP calls) failed 19 of 126 records: 14 Kalshi `too_many_requests`, 8 of them replayed from the cache within that same run (all the one `series_ticker=ECLIPSECOVER` URL, cached earlier in the same six-minute run) and 6 live; 2 Polymarket 403s; 3 Polymarket 400s (VI-25). The run's operator deleted the 8 cached 429/403 files by hand and re-ran with one worker, which recovered 14.

**Impact:** a transient rate limit becomes a permanent failure for every record that shares the URL, within the run and across runs, until someone edits the cache by hand.

**Fix:** do not write a 429, 403 or 5xx response into the cache (or treat a cached non-200 as a miss), default `--workers` to 1 for the Kalshi calls, and amend the docstring. Test: a fake fetcher that returns 429 once then 200 must give a result on the second read with no hand edit.

**Touch points:** `scripts/market_consensus.py:25-27`, `:115-145`, `scripts/test_predictions_markets.py`.

---

### VI-25. Polymarket returns 400 for the 30-day `prices-history` window and 403 for some `public-search` queries, and the ladder stops at the first error  `[difficulty: high]`  `[filed: 2026-10-18]`

**Background:** `scripts/market_consensus.py:349` is the 30-day step of a three-step window ladder (2 days, 30 days, then from the market's open) at `fidelity=60`; for that step Polymarket answers HTTP 400 `invalid filters: 'startTs' and 'endTs' interval is too long` (endTs minus startTs is 2,592,000 s), and the error aborts the ladder, so the daily step that may succeed is never tried. `:252` (`public-search`) gets an HTTP 403 Cloudflare page for some queries. Across the corpus 8 accepted records fail this way on every run that reaches them, each carrying a consensus block with `status: failed`: `prices-history` 400 for fa01d301325e4243, 2012463b3b01b93d, d13eb0f50e17ffea (this supplement), michael-saylor 9d2d817a08c94853 and bill-gates bfecb68972253ee1; `public-search` 403 for d4b463de73917226 and jensen-huang 22f49209e94ce62f and c023eff1328d99e3. Ledger VP-38 logged the same 400 on 2026-10-05. Logs: data `predictions/_experiments/thin-supplement-20261018/market_consensus-{1,2,3}.log`.

**Impact:** eight accepted records can never get a market observation, and every consensus run counts them as failures.

**Fix:**
1. On a 400 from `prices-history`, fall through to the next ladder step instead of raising; record which step answered.
2. On a 403 from `public-search`, retry once, then record `blocked_by_host` as a terminal status instead of `failed`; that status touches `prediction_record.schema.json`, `validate_predictions.py` and the page's rendering of a consensus block.
3. Tests for both paths with a fake fetcher.

*Risks and edge cases:* a daily-fidelity observation for an old market may be sparse; the cutoff rule (strictly before publication) must hold for every step.

*Why high not medium:* a new terminal status crosses the schema, the validator and the site.

**Touch points:** `scripts/market_consensus.py:245-260`, `:341-360`, `.agents/skills/prediction-extractor/prediction_record.schema.json`, `scripts/validate_predictions.py:205-225`, `scripts/build_predictions_site.py` (the consensus block), `scripts/test_predictions_markets.py`.

---

### VI-26. A dating run directory's `overrides.json`, `checks.json` and `queue.json` hold only the last merge's scope  `[difficulty: high]`  `[filed: 2026-10-18]`

**Background:** `scripts/date_recordings.py:1017-1040` rewrites the three files for the transcripts in scope of the current merge, so a run directory used for several `--ids` waves keeps only the last wave's entries and queue rows, and `scripts/promote_dating_run.py` would miss the earlier waves. Found by the review of public 698cdee on `dating-thin-supplement-20261018`, which ran in waves; that run avoided the loss by passing the union of every wave's datable ids on the final merge (every id left out was a `stated_in_page` source, which the stage no longer dates). Also, the per-call progress lines go to stderr with `flush=True` (`:102-104`) but the stdout banner and summary are block-buffered under `nohup`: in `dating/run-wave2c.log` the `SPENDS QUOTA` banner is line 106 of 111, after every progress line.

**Impact:** a promotion from a multi-wave run silently drops the earlier waves' confirmed dates, which decide eligibility and lead for their records.

**Fix:**
1. Merge over every transcript that has proposals on disk under the run directory, or refuse a `--stage merge` whose scope is narrower than the proposals directory; decide which (the first keeps old entries alive, the second makes the operator name the union).
2. Print the stdout banner and summary with `flush=True`.
3. Test: two merges with disjoint `--ids` into one run directory must leave both waves' entries on disk.

*Risks and edge cases:* a transcript with proposals from a run whose daters differ is refused before any merge today; the union merge must keep that refusal.

*Why high not medium:* two design options that change which dates reach production, across the merge, the promotion and the agreement text.

**Touch points:** `scripts/date_recordings.py:905-926`, `:950-1045`, `:1055-1066`, `scripts/test_date_recordings.py`, `docs/agents/DATING.md`.

---

### VI-29. `run_tests.sh` discards every test's output, so an intermittent failure leaves no text  `[difficulty: low]`  `[filed: 2026-10-18]`

**Background:** `scripts/run_tests.sh:8` runs each test with `>/dev/null` and prints only `FAILED <path>`. On 2026-10-18 a full run in repo-1 printed `FAILED scripts/test_pundits_contract.py` and `failed: 1`; the same test then passed seven times on its own (`43/43 passed`) and a second full run printed `failed: 0`. Nothing of the failing check survived, and whether two gate runs overlapped in the clone is unknown. BACKLOG.md's own gate parameter says "the whole output kept".

**Impact:** a flaky or load-dependent test cannot be diagnosed from the gate's output, so it gets re-run until green, which the protocol forbids.

**Fix:** keep each test's output in a per-run directory (for example `.gate/<utc>/<test>.log`, git-ignored) and print the failing test's last lines beside `FAILED <path>`; a Node test the same way.

**Touch points:** `scripts/run_tests.sh`, `.gitignore`.

---

### VI-10. Every `grade_loop.sh` cycle retries Gemini up to three times on six transcripts it has never graded  `[difficulty: high]`  `[filed: 2026-10-11]`  `[BLOCKED: operator picks option (a), (b) or (c)]`

**Background:** The ledger entry, verbatim:

Filed 2026-10-11 by repo-0
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

`scripts/grade.py:2062` (`call_gemini`) stops after two empty retries (`:2142-2143`); the cap is per run, and the measurement is `docs/agents/JUDGES.md:413-452`.

**Impact:** About 18 long Gemini calls per cycle, every cycle, for a chance per call that is close to zero.

**Fix:** Option (b), when the operator picks it: a per-(judge, transcript) cap across runs in `grade.py`, after N cycles of `empty_response` with a denied tool, skipping that pair and listing it in the run summary as skipped with its count; a test that fails first; and the cap and its reset recorded in `docs/agents/JUDGES.md`. Option (c) is a new measured prompt and a separate item.

*Risks and edge cases:* the skip list must live where every clone's run can read it (the data repo's `logs/`), be reset by hand, and never hide the six from the coverage table.

*Why high not medium:* a cross-run state file in a daemon's path and a change to what the run summary says a judge did.

**Touch points:** `scripts/grade.py:2062-2151`, the run summary writer, a new test file, `docs/agents/JUDGES.md:413-452`.

---

### VI-11. `validate_grader.py` says it "mirrors aggregate.py's own gates" and no longer does  `[difficulty: high]`  `[filed: 2026-10-11]`  `[BLOCKED: its V1-V5 figures are next quoted or re-run]`

**Background:** `scripts/validate_grader.py` was last changed on 2026-09-06, and its `load()` (`:88`) has drifted from `aggregate.py` in four ways since. (1) It drops a GRADE whose own subject share is under its `MIN_SUBJECT_SHARE` (`:37`, which is 15 while `scripts/aggregate.py:112` is 10), while `aggregate.filter_unscorable` (`aggregate.py:172`) drops a whole RECORDING when the judges' mean share is under the cutoff or any judge says 0, the rule `docs/agents/SCORING.md` records with its measured cost. (2) It skips `_raw/` (`:92`) and not `_obsolete/`, which `aggregate.load_grades` skips (`aggregate.py:232`). (3) It applies no board membership (`aggregate.py:1204-1206`, `:1396`). (4) It swallows any unreadable grade or transcript file (`except Exception` at `:96` and `:249`) and reports nothing. No test covers it and no loop runs it, so nothing published reads it today, but its V1-V5 figures are quoted as grader validation.

**Impact:** The next time its numbers are quoted they describe a different corpus than the board: a different share cutoff, obsolete grades included, off-board people included, unreadable files silently dropped.

**Fix:**
1. Make `load()` call `aggregate.load_grades`, `aggregate.filter_unscorable` and the membership reader rather than restating them, and raise on an unreadable file.
2. A test that builds a small corpus with one obsolete grade, one under-share recording and one off-board person, and asserts the validator's counts equal the aggregate's, failing first.
3. Re-run V1-V5 and record the new figures where the old ones are quoted (`docs/agents/MAP.md`, grader validation).

*Risks and edge cases:* the V1-V5 figures move; quote them with the date and the commit.

*Why high not medium:* three loaders to replace and published figures to re-derive.

**Touch points:** `scripts/validate_grader.py:37`, `:88-110`, `:249`, `scripts/aggregate.py:172`, `:227-232`, `:1204-1206` (read only), a new `scripts/test_validate_grader.py`, `docs/agents/MAP.md`.

---

### VI-12. `test_log_bloat.py` reads the leaders daemon's live checkout, so the suite goes red in every clone while repo-0 is mid-rebuild  `[difficulty: medium]`  `[filed: 2026-10-11]`  `[BLOCKED: a second red from it that is not a rebuild in progress]`

**Background:** The market-cache section of `scripts/test_log_bloat.py` takes `production_path(REPO)` (`:58-60`), the shared `verbatim-index/data` the daemons write, not the clone's own `data` link, and asserts every accepted prediction carries market provenance (`:162-164`). At 04:00 PDT on 2026-10-11 the suite at `c323fb8` reported `FAILED scripts/test_log_bloat.py`: "9 of 1124 accepted records lack consensus status, cutoff or searched_at_utc", all in the shared checkout beside repo-0's uncommitted `_experiments/rebuild-20261011/`. That red was a TRUE POSITIVE: the 9 records were the VP-5 remainder that repo-0 integrated in data `a8212d25`, and the integration skipped `market_consensus.py`. Fixed by running `market_consensus.py --leaders jack-dorsey,bill-gurley --router-exclude claude,claude_e`: 9 attempted, 9 `no_match`, 0 errors, 5 Fable matcher calls; the test then printed `13 passed, 0 failed`. The gap is in the integration step: anything that adds accepted records must run market consensus before commit. `AGENTS.md` ("Setup in a fresh clone") names this test as the one that fails while repo-0 is mid-rebuild.

**Impact:** A suite verdict that depends on data another agent is writing; so far every red was a real defect, so nothing is changed until one is not.

**Fix:** When the condition is met, split the section into a fixture proof and a named `LIVE DATA:` check, as `scripts/test_render_integrity.py` was split on 2026-10-11 (archived entry "RESOLVED 2026-10-11: the derived-number proof runs on a fixture", `docs/BACKLOG-RESOLVED.md`, Site rendering). Until then, a red from this file is reported with its text.

**Touch points:** `scripts/test_log_bloat.py:58-60`, `:135-164`, `AGENTS.md` (the fresh-clone paragraph).

---

### VI-13. The speaker-segmentation call does not correct obvious caption errors, and there is too little ground truth to measure an attempt  `[difficulty: xhigh]`  `[filed: 2026-09-28]`  `[BLOCKED: at least 50 operator caption corrections across at least 10 recordings, made under the VI-9 convention]`

**Background:** Re-checked 2026-10-11: still waiting, at 15 corrections over 5 recordings of the 50 over 10 it needs. Counted with `scripts/pundits_text_corrections.py` over every speaker-check answers file on this Mac: leaders 9 edits over 2 recordings, predictions 5 over 2, pundits 1 over 1. The newest edit is from 2026-09-28T05:07Z, and no later session exists in either data repo. The ledger entry, verbatim:

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

Where the code stands today: `scripts/speaker_turns.py:65-66` pins the segmenter (`gpt-6-astra`, `SEGMENT_SINCE_UTC = 2026-09-28`), `scripts/speaker_segment_probe.py` scores a run, and `scripts/pundits_text_corrections.py:17-72` holds the overlay shape and the counter.

**Impact:** The commonest fixable caption error, a misheard name, stays in every transcript the judges read, and the operator's corrections are the only repair.

**Fix:** When the threshold is met: (1) a new measured prompt beside `speaker_turns.PROMPT` that returns turns and corrections in the overlay shape; (2) the probe scores turns with and without the correction task against the 2026-09-28 baselines, and scores corrections both ways; (3) adopt only if turns do not degrade. Each a failing-first test.

*Risks and edge cases:* the three constraints in the entry above; the prompt hash moves, so adoption is a new measured segmenter.

*Why xhigh not high:* prompt design, a two-sided measurement and a schema that every published quote offset depends on.

**Touch points:** `scripts/speaker_turns.py:65-66` and `PROMPT`, `scripts/speaker_segment_probe.py`, `scripts/pundits_text_corrections.py:17-72`, their tests, `docs/agents/PUNDITS.md`.

---

### VI-14. david-sacks and chamath-palihapitiya are on the predictions board only, and promoting them means a multi-hour grading run on prepaid credit  `[difficulty: xhigh]`  `[filed: 2026-10-18]`  `[claimed by: #2]`

**Background:** repo-2 finishes this, on the operator's instruction of 2026-10-18 ("continue and go fetch their transcripts and podcasts and then run the protocol to grade them so that they can show up on the verbatim-index leaderboard", plus "You are authorized to check in changes to the data repo"), under the one-committer protocol the Nate Silver precedent used: repo-2 prepares in its own data clone and applies steps (1) to (3), (5) and (6) into the daemon checkout `verbatim-index/data`, pushing its owner paths with `data_sync.py push --daemon` from there; repo-0's session agreed on 2026-10-18 to write nothing under that checkout meanwhile. Spends about $50 to $60 of API credit on pools a and b (c, d and e were empty on 2026-10-18). Filed by repo-0 on the operator's instruction of 2026-10-17 and deferred at once. `membership.json` gives each `['predictions']` today. This item also carries the archived entry "Discovery will re-pollute the seven's curated alias lists" (`docs/BACKLOG-RESOLVED.md`, Board membership): its open clause, re-curate the alias blocks when one of the seven is promoted, is step (3) below, and its measurement (zero incremental blinding damage either way) is in the archive. The ledger entry, verbatim except for one refreshed line number:

Filed 2026-10-18 by repo-0, on the
operator's instruction of 2026-10-17, and deferred the same day: the work is a
multi-hour run and the operator chose to pick it up later. STATE FOUND, at
public `3b85ea3` and data `3db9ba3e`: `membership.json` gives each
`['predictions']`; roster ranks 53 and 54 carry `boards: ['predictions']` and a
`selection_rationale` that says revisit the company string BEFORE promotion;
the `aliases.json` blocks are the discovery-merged ones (David, Sacks, Craft,
Ventures; Chamath, Palihapitiya, Social, Capital) and the curated ones are at
data `cd7225a0`; `all.jsonl` holds 14 rows each; `transcripts_web/` holds 14
YouTube records for david-sacks and 14 YouTube plus 4 `web-*` records for
chamath-palihapitiya, the YouTube ones byte-for-byte the graded shelf's schema
(checked against a nate-silver shelf record: no key differs); nothing under
`transcripts/`, `transcripts_open/` or `grades/`. All three daemons stopped.
THE PLAN, following `docs/ROSTER-ADD-NATE-SILVER-2026-10-11.md` (ledger VP-39):
(1) `membership.json` first, both to `['leaders', 'predictions']`, then the
roster `boards`, a top-level note and the two rationales. Counts that move:
`scripts/test_membership.py` (`SEVEN`, "the roster MINUS the seven"),
`docs/agents/MAP.md` ("51 of the 58", "59 entries: the 49 ...", "the seven
investors with `predictions` alone"), `docs/agents/SCORING.md` ("board holds
51"), and whatever `scripts/test_agents_md_current_state.py` matches.
(2) Curate the shelf BY HAND before anything lands in `transcripts/`. The
precedent cut co-hosted and co-guest recordings because auto-captions carry no
speaker labels. Candidates to cut, from titles and `yt_description`:
david-sacks `all-in-podcast-kcmmoz` (a debate; the title names two other
guests), `all-in-podcast-lbb-rq` (All-In E2, co-hosted),
`american-moment-yjhavh` (gala excerpts, four speakers),
`orricktotalaccess-yxqyau` (a three-person panel per its description);
chamath-palihapitiya `khosla-ventures-tzpya9` and `waterloo-engineering-aoznmm`
(co-keynotes with vinod-khosla). That leaves about 10 and 12, both over the
rank floor of 5. The 4 chamath `web-*` records stay predictions-only, as the
Nate Silver supplement did. Copy the kept records into `transcripts/<slug>/`;
for each cut row write `<sid>.json.superseded` there, the marker
`fetch_transcripts.py:348` honours, so no fetcher pulls it onto the shelf; the
rows stay in `transcripts_web/` for predictions.
(3) `identity_screen.py` and `qa_transcripts.py` on the kept set, then blind
each transcript twice (empty alias list, current list) as the precedent did.
MEASURED 2026-10-18 over the YouTube records: lowercase "social" 72 and
"capital" 109 across chamath's 14; "craft" 13, "ventures" 7, "sacks" 13 across
sacks' 14. Decide the company strings, and whether to restore the curated alias
blocks (the archived entry "Re-checked 2026-10-11: still WAITING", in
`docs/BACKLOG-RESOLVED.md`, asks for it on promotion; measured incremental damage is zero either way, so it is a wording
choice, and the merge in `sources_to_manifest.py` re-adds the words on the
next rebuild).
(4) `grade.py`. `--fable-pool` must take a comma-separated pool list:
`call_fable_pool` wants `served.account == pool` (`grade.py:1215-1216`), so a list
fails every call as `account_identity_mismatch` today. It needs a production
opt-in: `fable_pool_refusal` (`grade.py:576`) refuses `--out` outside
`data/experiments/`. At filing, repo-3 held the predictions precedent UNPUSHED:
`e267bef` adds `--credit-production` to `extract_predictions.py`, and `bcfaca8`
records VD-19 (credit records may reach the board) and that CI-11 stopped
after day 1; mirror that flag name, and check both have reached origin before
starting. Failing-then-passing checks in `scripts/test_fable_pool.py`. VI-5
wants `call_fable_pool` to go through `credit_run.run`, which takes a pool SET
already. Add a per-judge
harness count beside `judge_models` in `aggregate.py` (`aggregate.py:1443`)
so the mix is visible in `diagnostics`. Record in `docs/agents/JUDGES.md`
that pooling credit grades with the corpus is the operator's decision, with
the evidence (`data/experiments/fable-credit-drift-20261018/results.md`:
credit minus production -0.62 points, 95% CI -1.7 to +0.47, n 34, Spearman
0.939); that file today says "do not pool these grades with the corpus".
(5) Run `grade_loop.sh`'s stages by hand with its exact flags: QA, normalize
blinded and open; `grade.py --judges fable --fable-pool
anthropic_api_c,anthropic_api_e,anthropic_api_b,anthropic_api_a <opt-in>
--out data/grades --timeout 1800` (the pool maximum; production uses 2400,
and the four transcripts over 28k words may be cut off and still billed), 6
workers then `--workers 1` to drain `no_candidate`; `grade.py --judges
astra,gemini --timeout 2400`; aggregate, build_site, `wrong_person_screen.py`;
`deploy.sh --production-data data --data-revision`. Cost about $2 to $2.5 per
credit grade, so $50 to $60 for about 22 transcripts; pool d ($0.61) admits
nothing. repo-3's thin-supplement extraction
(`predictions/_experiments/thin-supplement-20261018/`) spends the same pools,
and CI-11's day-2 arm on pool c was dropped per `bcfaca8`, so no reserve
needs protecting. Their `fetched_at_utc` (2026-09-19) is before
`SEGMENT_SINCE_UTC`, so `speaker_turns.py` will not cover them; say so in the
record.
(6) Record it as the precedent was: a `docs/ROSTER-ADD-*.md`, a row in
`docs/LEDGER-predictions.md` (VP-41 is taken by repo-3's `bcfaca8`), data
pushed with `data_sync.py push --daemon`, and `adversarial-self-review` on the
`grade.py` change before its push. Comes back when the operator picks it up.

**Impact:** Two people the operator wants on the leaders board are not on it, and every count that names "the seven investors" (`scripts/test_membership.py:60`, `:189-195`; `docs/agents/MAP.md:54`, `:63`; `docs/agents/SCORING.md:37`) moves when they are.

**Fix:** the six numbered steps above, in order; the `grade.py` change in step (4) overlaps VI-5 and should land after it.

*Risks and edge cases:* in the entry above (co-hosted recordings, the pool timeout against four transcripts over 28k words, the `speaker_turns.py` coverage gap, the pooling decision that `docs/agents/JUDGES.md` must record).

*Why xhigh not high:* it spends credit, moves the published board and changes a grading harness's production gate in one run.

**Touch points:** `membership.json`, `data/roster/final.json`, `data/sources/aliases.json`, `scripts/test_membership.py:60`, `:189-195`, `docs/agents/MAP.md:54`, `:63`, `docs/agents/SCORING.md:37`, `scripts/test_agents_md_current_state.py`, `scripts/fetch_transcripts.py:348`, `scripts/grade.py:576`, `:1211-1216`, `:2575`, `scripts/test_fable_pool.py`, `scripts/aggregate.py:1443-1447`, `:1747`, `docs/agents/JUDGES.md`, a new `docs/ROSTER-ADD-*.md`, `docs/LEDGER-predictions.md`.

---

### VI-17. Pundits grading cannot run on prepaid API credit under contract v2 without re-grading the whole pilot  `[difficulty: xhigh]`  `[filed: 2026-10-18]`  `[BLOCKED: operator picks (A) or (B); CI-11 stopped after day 1, so its day-1 result is all that is coming]`

**Background:** Only the pundits daemon clone, repo-3, can finish option (B): it pushes the re-graded cells; option (A) is a decision with no work. Filed by repo-3. `quotapick run` (the router's only way to spend a credit pool) runs Fable with tools removed, on an API key, with no sandbox wrapper. Contract v2's `judge_requests.fable` names `sandbox_exec_deny_container` (`profiles/pundits.json:41-51`), `scripts/grade.py:998` refuses any other sandbox, and `judge_requests` is part of the hash that makes the contract ID. So a credit grade filed under today's contract ID would claim a sandbox it never ran in. If instead the contract is amended to name the credit harness, the contract ID changes, `grade.py` reads all 312 pundits grades (156 Fable, 156 Gemini) as `stale_cache`, and `aggregate.py` refuses to mix contracts (`scripts/aggregate.py:1429`), so the whole pilot is graded again (about $380 by the 2026-10-18 estimate). That is more than pools d and c hold, and on 2026-10-18 the owner put their spare beyond CI-11's share into the pundits predictions scale-up, so a re-grade would run on the November pools: e (expires 2026-11-10), b (2026-11-11) and a (2026-11-16). CI-11 (`data/experiments/fable-credit-drift-20261018/`) was to grade day 1 on d and day 2 on c; the operator stopped it after day 1 and cancelled day 2 (`docs/LEDGER-corpus-integrity.md:23`), with day 1 showing credit minus subscription -0.62 points, 95% CI -1.7 to +0.47, n 34, Spearman 0.939 (`results.md`).

**Impact:** The pundits full grade either stays on the subscription harness, or costs about $380 of credit and a contract change.

**Fix:** Options: (A) keep pundits grading on the subscription harness, at no cost; (B) amend the contract to name the credit harness and re-grade on the November pools. The ledger recommended waiting for CI-11 before choosing; CI-11 is stopped, so its day-1 result (credit 0.62 points under subscription, the interval straddling zero, n 34) is the evidence the choice rests on unless the operator restarts it. If B: a contract v3 in `profiles/pundits.json`, the migration path for the 312 grades, and `docs/agents/PUNDITS.md`.

*Risks and edge cases:* a contract change invalidates every pundits grade at once; the daemon must be stopped first.

*Why xhigh not high:* a contract hash, $380 of credit and the whole pundits corpus.

**Touch points:** `profiles/pundits.json:41-51`, `scripts/grade.py:576-610`, `:998`, `scripts/aggregate.py:1429`, `docs/agents/PUNDITS.md`, `docs/PUNDITS-RELEASE-PLAN.md`.

---

### VI-18. The pundits page has no evidence drawer  `[difficulty: high]`  `[filed: 2026-10-12]`  `[BLOCKED: the P7 quote audit (300 quotes, G-attribution-quotes) has run and decided the quote filter]`

**Background:** The leaders page shows, per person, each judge's reasoning and evidence quotes for every graded transcript (`scripts/build_site.py:474-600`, the drawer). The pundits page (`scripts/build_study_site.py:429`, `render`) lists each board recording with its link, venue and score since 2026-10-12, but not what the judges wrote; the data is in `results_audit.json`. Not done, deliberately: the quotes would appear credited to a named political commentator, and attribution is not yet measured. VI-21 holds 89 judge quotes credited to the subject that do not place in the transcript, and the P7 quote audit has not run. Publishing the drawer first would put possibly misattributed words beside a person's name.

**Impact:** A reader of the pundits page cannot see the evidence behind a score.

**Fix:**
1. Port `build_site.py`'s drawer into `build_study_site.py`, reading the pundits `results_audit.json`.
2. Apply the quote filter the P7 audit decides (VI-21's outcome) before any quote is rendered.
3. Tests as for the leaders drawer; `docs/agents/SITES.md` records the page size and shape.

*Risks and edge cases:* the page size limit in `docs/agents/SITES.md`; the leaders drawer is loaded from a separate audit file per person for that reason.

*Why high not medium:* a port across two site builders plus a filter whose rule is a measurement result.

**Touch points:** `scripts/build_study_site.py:429`, `scripts/build_site.py:474-600` (read only), the pundits site tests, `docs/agents/SITES.md`.

---

### VI-19. An unsupported dimension removes the whole recording, though the plan says it should still count toward the dimensions it supports  `[difficulty: high]`  `[filed: 2026-10-11]`  `[BLOCKED: the pundits full grade, or a second recording with an unsupported dimension]`

**Background:** Only the pundits daemon clone, repo-3, can finish this: step 3 re-aggregates and deploys, and the item is deleted only after it; the code change in step 2 may be prepared on any clone. Found while asking why `asmongold/asmongold-tv-ks77-g` is missing from `results.json` despite four schema-valid grades. Three of its four grades mark `d1_steelmanning` `unsupported` (fable/blinded, gemini/blinded, gemini/open). `scripts/aggregate.py:1248` marks each such grade `_excluded = "unsupported_dimension"`, which removes the whole grade, and then `drop_partial_panels` (`:115`) drops the fourth, fully supported fable/open grade as an incomplete panel. The recording contributes to no dimension. `docs/PUNDITS-PLAN.md:241-246` ("Anchors and minimum evidence") says otherwise: a transcript with any unsupported dimension has no `overall`, still counts toward each dimension it supports, and ranking by overall uses only transcripts with all three supported. Re-running `aggregate.py --study pundits` on a scratch clone of data-pundits at `dced184` reproduces the committed result: 154 transcripts, the same one partial panel, and `grades_excluded_unsupported_dimension 3` (`:1696`), so the loss is counted rather than silent. The reporting half is done: `drop_partial_panels` names a cell removed earlier and why (`:164`), so the report reads "missing gemini/open (removed: unsupported_dimension)". `docs/PUNDITS-RELEASE-PLAN.md:198-201` asks the operator to choose one rule and delete the other sentence from the plan.

**Impact:** Size today: 3 grades, 1 recording. Per-dimension counting also has to decide what a partial panel means per dimension: here d1 has one supported cell out of four, while d2 and d3 have all four.

**Fix:**
1. Decide the rule (plan text or code) and delete the other sentence from `docs/PUNDITS-PLAN.md`.
2. If the plan wins: `aggregate.py` keeps a grade with an unsupported dimension for the dimensions it supports, gives the transcript no `overall`, and `drop_partial_panels` works per dimension; a fixture test with the asmongold shape, failing first.
3. Re-aggregate on a scratch clone and diff against the committed result before the daemon clone deploys.

*Risks and edge cases:* a per-dimension panel rule changes every pundits score's denominator, not just this recording's.

*Why high not medium:* a scoring rule with a plan decision attached.

**Touch points:** `scripts/aggregate.py:115-164`, `:1248`, `:1696`, its pundits tests, `docs/PUNDITS-PLAN.md:241-246`, `docs/PUNDITS-RELEASE-PLAN.md:198-201`, `docs/agents/SCORING.md`.

---

### VI-21. 89 judge quotes credited to the subject do not place in the open transcript, and nobody has said whether a tidied quote counts as verbatim  `[difficulty: high]`  `[filed: 2026-09-19]`  `[BLOCKED: operator decides whether a quote with fillers removed or a caption error corrected is verbatim under the rubric]`

**Background:** Of 3,290 subject quotes in the 312 live pundits grades, `pundits_verify_page.locate` (`scripts/pundits_verify_page.py:191`) first failed to place 137. Re-measured 2026-10-11 after three matcher fixes (`[AFFILIATION]` as a placeholder for up to five words, `_norm` at `:181` stripping edge quote marks and curly apostrophes, an empty quote counted as `empty`): against `transcripts_open/`, located 3,198, not located 89, empty 3 (`suspect_quotes` at `:238`; the full re-measurement is the archived entry "RE-MEASURED AND PARTLY FIXED 2026-10-11", `docs/BACKLOG-RESOLVED.md`, Verbatim Pundits). Of the 89, 84 share at least 80% of their three-word sequences with the transcript and 5 share 73 to 77%; all 5 were read in context, and every one is a judge tidying the captions, never a paraphrase (a dropped filler, a joined caption-split number, a corrected typo). 86 of the 89 are Gemini. A matcher that also skipped fillers and immediate repeats would place 29 of the 89; not done, because it makes "located" fuzzier and the remaining 60 differ in more varied ways.

**Impact:** The quote cap and the minimum-subject-quotes rule both assume quotes are real; 89 of them are either matcher misses or rubric violations, mostly Gemini's, and the pundits evidence drawer (VI-18) waits on the answer.

**Fix:**
1. The operator decides. If tidied quotes are verbatim: extend the matcher (fillers, immediate repeats) with a failing-first case in `scripts/test_pundits_verify_page.py`, re-measure, and read the remainder one by one. If not: count them as rubric violations per judge, report the rate in `aggregate.quote_cap_report()`'s neighbourhood, and say so in `docs/agents/PUNDITS.md`.
2. Either way, the 60 that no matcher rule places are read one by one and classified.

*Risks and edge cases:* a fuzzier matcher hides real paraphrase; a stricter rubric penalises Gemini 86 to 3.

*Why high not medium:* a rubric interpretation with a per-judge consequence.

**Touch points:** `scripts/pundits_verify_page.py:181-238`, `scripts/test_pundits_verify_page.py`, `scripts/aggregate.py` (the quote report), `docs/agents/PUNDITS.md`.

---

### VI-22. `grade.py --regrade-invalid` exists for leaders and is off, so 35 malformed leaders records stay as they are  `[difficulty: low]`  `[filed: 2026-10-11]`  `[BLOCKED: operator decides to turn it on; spends about 35 Fable calls and moves the published board]`

**Background:** The manual pass is the leaders daemon clone's, repo-0; the loop-flag route is a code change any clone can make. Counted 2026-10-11 in the shared leaders data: 35 records failed validation while still carrying an attempt at scores, 26 with `dimensions` and 9 in a judge-invented shape with `overall`; six more failed as refusals or non-answers and stay put by the refusal rule in `docs/agents/JUDGES.md`. `scripts/grade.py:446-473` implements `--regrade-invalid` as an opt-in: a malformed record is moved under `grades/_obsolete/` byte for byte and graded again. `scripts/grade_loop.sh:205` and `:218` do not pass the flag, and `scripts/test_leaders_regrade_invalid.py:150` pins that they do not. It is opt-in because default-on would make repo-0's daemon spend about 35 calls and move the published board on its next code pull. The archived entry "LEADERS HALF FIXED 2026-10-11 as an opt-in" (`docs/BACKLOG-RESOLVED.md`, Verbatim Pundits) holds the count and the proof.

**Impact:** 35 leaders cells that could hold a score hold a malformed record, and the board is computed without them.

**Fix:** When the operator says so: one manual pass from repo-0, `grade.py ... --modes blinded --regrade-invalid`, then aggregate and deploy; or add the flag to the loop's grade calls at `grade_loop.sh:205` and `:218` and change the pin at `test_leaders_regrade_invalid.py:150` in the same commit. Record the before-and-after board as a `CI-n` row in `docs/LEDGER-corpus-integrity.md`, the ledger that holds the leaders grade-validity items.

**Touch points:** `scripts/grade_loop.sh:205`, `:218`, `scripts/test_leaders_regrade_invalid.py:147-150`, `scripts/grade.py:446-473` (read only), `docs/LEDGER-corpus-integrity.md`.

---

### VI-27. VP-41's scored board is not deployed  `[difficulty: medium]`  `[filed: 2026-10-18]`  `[BLOCKED: the operator decides VD-20 (grants the predictions deploy); VD-10, decided 2026-09-29, covered the VP-31 rebuild only]`

**Background:** Any push-role clone at origin/main can do this. The overnight run of 2026-10-18 finished VP-41 through scoring (data `6e142316`, derived `94dfc91f`, diff `225585e4`, notes `7e078af7`, readme `2537af7d`; ledger VP-41, decision VD-20): `scoring.json` names `predictions/_experiments/thin-supplement-20261018` with `as_of` 2026-10-18; `scores.json` has 569 scored rows and 49 ranked people where the live page (data `c553aed7`) has 528 and 46; the per-person table is `predictions/_experiments/thin-supplement-20261018/diff_board.md` (41 rows started scoring, 0 stopped; Tim Cook, Reed Hastings and Evan Spiegel newly ranked; Pat Gelsinger 6 -> 16 scored, rank 10 -> 14). The deploy was not authorized: the operator granted spend, and VD-10 (decided 2026-09-29 for the VP-31 rebuild, live 2026-10-03) says "Scope: this rebuild only"; VD-20 in the ledger asks for the grant. `scores_asof_lag` (`scripts/data_clone_workflow.py:966`) passes for as_of 2026-10-18 while no newer commit adds predictions data; after one does, `as_of` must move and the board re-score before any deploy.

**Impact:** the live page shows a board that main has moved past, and every later predictions commit raises the cost of catching up.

**Fix:** with the data and public checkouts at origin/main, `bash scripts/deploy_predictions.sh --production-data "$(cd data && pwd -P)" --data-revision "$(git -C data rev-parse HEAD)"`, then send the operator `diff_board.md`. No code changes.

**Touch points:** none modified; runs `scripts/deploy_predictions.sh` and reads `data/predictions/_experiments/thin-supplement-20261018/diff_board.md`.

---

### VI-28. The second source pass for the thin predictions people is not run  `[difficulty: xhigh]`  `[filed: 2026-10-18]`  `[BLOCKED: the operator asks for the second pass; spends credit, Codex and subscription quota]`

**Background:** Any push-role clone can do this. Runners-up cut by the 6-source cap of the 2026-10-18 discovery are in each `findings/<slug>.json` of `data/predictions/_experiments/thin-supplement-20261018/` (reed-hastings 4 Netflix earnings calls, tim-cook 4, larry-ellison 4, tom-lee 2 plus about 30 CNBC episodes). The discovery sub-agents shared one web-search budget and ran out early, so most people were searched thinly; `BRIEF.md` lacks the generic User-Agent line that the run's README asks for. Credit at 2026-10-18T13:00Z (`quotapick credits --json`): pool a $169.08 (expires 2026-11-16), b $16.83 (2026-11-11), e $2.46 (2026-11-10); pool c's second grant, $93.71 at 05:51Z, expires 2026-11-20 and is NOT recorded in quotapick (`quotapick credits grant` adds it). `NOTES.md` in that folder is the worked example for every stage.

**Impact:** 22 of the 25 thinnest people are still ranked on fewer than 10 scored predictions or unranked (aravind-srinivas, clem-delangue, sergey-brin and tobi-lutke have no scored row).

**Fix:** the whole pipeline, as in `NOTES.md`: (1) discovery with `BRIEF.md` plus a generic User-Agent line, spread across sessions; (2) `_driver/pipeline.py <slug>` with `POOLS` set to a pool that has money (URL and text duplicate checks, fetch, place, Fable extraction on credit, Gemini verify); (3) dating with `scripts/date_recordings.py --ids` over the datable recordings (stated_in_page sources are skipped), `scripts/promote_dating_run.py --against` the production runs, re-extraction of the re-dated recordings; (4) `worklists.py` in a NEW run folder named in `scoring.json` with `as_of` moved to the carrying commit's UTC date, then lead_test, resolve (Astra), prior (Fable on credit), market consensus and year summaries; (5) `data_sync.py push`, then the deploy and the per-person diff.

*Risks and edge cases:* every hazard the 2026-10-18 run met and VI-23 to VI-26 record; a run folder named in `scoring.json` moves the as_of bar with every commit into it.

*Why xhigh not high:* five pipeline stages, three quota pools and a deploy, with judgment at each hand-off (the rating VI-15 carried).

**Touch points:** `data/predictions/_experiments/thin-supplement-20261018/` (`BRIEF.md`, `_driver/pipeline.py`, `findings/`), a new `data/predictions/_experiments/<run>/`, `data/predictions/scoring.json`.

---
