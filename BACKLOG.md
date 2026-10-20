# Backlog

Deferred work, one item per heading, in the format the `backlog-protocol`
skill reads and `/run-backlog`, `/improve-code` and `/improve-data` work from.
Items are independent: claim one, finish it, delete it. The protocol itself
(claims, IDs, the capability ladder, deletion on completion, the pre-push
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
| Capability ladder | `fast`, `standard`, `premium`, `frontier`, the quota router's capability names; orchestration-sized work is split into normal items when filing, never tagged `ultra/workflows`. The skill's § 5 maps the running model to a row by its family; claim at or below it. The optional `[effort: <level>]` tag never changes who may claim or the pick order. Every legacy `[difficulty: ...]` tag was rewritten through § 5's alias table on 2026-10-19 (`low` to `fast`, `medium` to `standard`, `high` to `premium`, `xhigh` to `frontier`) |
| Agent handle | `#<n>` from a `repo-<n>` clone directory (`repo-0` is `#0`). Commit subjects: `claim: VI-n (#<n>)`, `backlog: delete VI-n (#<n>)` |
| Pick order | file order within `## Open items`, not the skill's default of lowest priority, then highest capability, then file order (owner decision 2026-10-19): the first unclaimed, unblocked item in the file whose Background's first sentence does not name another clone's lane is the next one to take. Read that sentence before the claim, and never claim a lane item from another clone. Unblocked items come first and `[BLOCKED: ...]` items last, so the picker never reads past an eligible item to reach them. A lane item goes at the head of the unblocked run, so the one clone that can do it reaches it first and every other clone skips it in one read; any other new item goes at the end of the unblocked run unless it must be done sooner |
| Priority | `[priority: P0]` to `P3` on every heading, required when filing (the skill's § 3); the 2026-10-19 migration gave every open item `P2`. The tag records urgency and does not reorder the pick: an item that must be done sooner (`P0`, `P1`) is placed earlier in the file, as Pick order says |
| Validation gate | `bash scripts/run_tests.sh` from the clone root, the whole output kept, `failed: 0` required. Never pipe it through `tail -1`: the per-file `FAILED <path>` lines are the finding, and each test's full output is in the printed `logs:` folder under `.gate/` (git-ignored, never pruned), so a red is reported with its log. `test_log_bloat.py` and the `LIVE DATA` checks in `test_render_integrity.py` read the leaders daemon's live checkout, so a red there is reported with its text, never retried until green (VI-12) |
| Pre-push review | `adversarial-self-review` on `origin/main..HEAD` before every push, verdict `ship` required, two fix rounds at most |
| Blocked tag | `[BLOCKED: <what lifts it>]` on the heading. Two kinds: an operator decision, or a measurement or event that has not happened. Nobody claims a blocked item, and the loop never lists one, so a lane is never a block: an item that only one clone can finish (`repo-0` pushes the leaders data repo's owner paths and deploys the leaderboard; `repo-3` does the same for pundits; AGENTS.md, "Clone roles") says so in the first sentence of its Background, and an agent on another clone skips it without claiming, and releases if it claimed before reading. Whoever lifts a block deletes the tag in its own commit and writes the lane sentence for the option chosen |
| Completion | delete the item; git history is the record. A decision or measurement worth keeping goes in the `docs/agents/` file of its topic, under "Rules that exist because something broke" or "Experiments run", never back into this file |
| Doc-gap routing | a standalone `fast` item |
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
### VI-<n>. <one-line problem statement>  `[capability: <level>]`  `[priority: P<n>]`  `[filed: YYYY-MM-DD]`  `[effort: <level>]`?  `[BLOCKED: <what lifts it>]`?  `[claimed by: <handle>]`?

**Background:** first sentence, when only one clone can finish the item: which clone, and why. Then what the code or data does today and where; at least one citation in the form `` `path:line` "phrase" ``, the phrase copied verbatim from that file and occurring in it exactly once. For a doc item, the stale sentence verbatim.

**Impact:** the concrete consequence.

*Root cause:* optional.

**Fix:** `fast`/`standard`: one paragraph. `premium`+: numbered steps tied to files, tests included.

*Risks and edge cases:* required for `premium`+.

*Why <level> not <level-1>:* required for `premium`+.

**Touch points:** every `` `path:line` "phrase" `` the fix will modify, tests included.

---
```

The `filed:` date is the UTC calendar date the item was first written down,
kept from the ledger entry it came from, and never updated. Only the skill's
`claim.py` writes the claim tag, and a blocked item never carries one. The
phrase is the anchor and the line only a hint, so a citation survives a push
that moves lines; the skill's `check_citations.py` checks phrases before a
push. Most items filed before 2026-10-19 cite bare `file:line`, which it
skips.
"Filed by repo-N" in a Background is provenance, not a claim and not a lane.

## Open items

### VI-20. Four graded pundits recordings carry blinded grades of text the blinder no longer produces  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-11]`

**Background:** Only the pundits daemon clone, repo-3, can finish this: the grades are `data-pundits` owner paths, which `data_sync.py push` refuses from any other clone, so an agent on another clone skips it. It spends judge quota, about 8 calls. `blind_study()` (`scripts/normalize_transcripts.py:531`) was fixed on 2026-10-11 to leave another person's surname alone when a different given name stands before it (the archived entry "FIXED IN CODE 2026-10-11; repo-3 must re-grade 4 recordings", `docs/BACKLOG-RESOLVED.md`, Verbatim Pundits, holds the measurement: 14 of 367 blinded files change). Four of the 14 are graded, `ben-shapiro/ben-shapiro-ahi_t9`, `ben-shapiro/ben-shapiro-mtbfmw`, `matt-walsh/matt-walsh-9bcva6` and `matt-walsh/matt-walsh-7zhqm9`, two blinded grades each. Checked 2026-10-18 in repo-3's `data-pundits`: all eight blinded grades still date from 2026-09-15 to 2026-09-17, before the fix. The next pundits normalize rewrites the 14 blinded files, and `grade.py` will report those 8 as `stale_cache` and exit 1 until they are re-graded with `--force`. `docs/PUNDITS-RELEASE-PLAN.md:49-51` names this step.

**Impact:** Until the re-grade, the pundits grading loop exits 1 on every cycle after the normalize, and four board scores rest on text in which a judge read "Tim [SUBJECT]" for Tim Walz.

**Fix:** From the pundits daemon clone: run the normalize, then `grade.py --study pundits --force` on the eight cells, then aggregate; record the before-and-after scores in `docs/PUNDITS-RELEASE-PLAN.md`, beside the step at `:49-51` that names this re-grade. One known residual stays: `mehdi-hasan/al-jazeera-english-bwb6x8` keeps "Mary Hassen", a caption corruption after a real given name; it is ungraded.

**Touch points:** `data-pundits/transcripts_blind/` (the 14 files), `data-pundits/grades/{fable,gemini}/{ben-shapiro,matt-walsh}/` (the 8 cells), `docs/PUNDITS-RELEASE-PLAN.md:49-51`.

---

### VI-1. `extract_predictions.py` takes no `--study`, so a pundits run can write into the leaders data repo  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3. `scripts/extract_predictions.py:747-781` declares every argument and none is `--study`; `--out` defaults to `data/predictions` (`:749`), `--transcripts` to `data/transcripts_open` (`:747`) and `--roster` to `data/roster/final.json` (`:748`), all leaders paths. The speaker script has the guard this needs: `scripts/pundits_speaker_infer.py:374` calls `study_profile.add_study_arg` and `:381` calls `SP.guard(args.study, str(root))` (`scripts/study_profile.py:95` and `:146`). The pundits prediction pilot of 2026-10-18 was written to the leaders `predictions/_experiments/` and moved by hand to the pundits data repo's `experiments/predictions-pilot-20261018/`. `docs/agents/PUNDITS.md:185` tells a pundits extraction to pass every path by hand for this reason. The run also records the wrong data revision: `input_data_revision` comes from the leaders checkout (`scripts/extract_predictions.py:896` "input_data_revision = data_git(L.data_root()"), so the pundits pilot's records name leaders data commits (`c553aed` in the runs of 2026-10-18, `6c64b2f` in the re-verify of 2026-10-19) that do not exist in the pundits data repo. `input_sha256` still pins each input.

**Impact:** Nothing stops a pundits run from writing pundits records under the leaders data checkout, where `data_sync.py push` and the leaders predictions aggregate treat them as leaders data.

**Fix:** Add `study_profile.add_study_arg` to the parser and `study_profile.guard(args.study, <out>, <transcripts>, <roster>)` in `main()` before any write, the way the speaker script does. A new check, in `scripts/test_predictions_credit.py` or a new `scripts/test_extract_predictions_study.py`, runs `--study pundits` with a leaders `--out` and asserts the refusal, failing first. Read `input_data_revision` from the checkout of the transcripts actually read (from `--transcripts`, or from the paths in `--list`, which replaces it), and assert it in the same test. Update `docs/agents/PUNDITS.md:185`, which says the extractor has no `--study` yet. Quota-free.

**Touch points:** `scripts/extract_predictions.py:747-781` (parser), `:875` (`main`), `:892` (`input_data_revision`), `scripts/study_profile.py:95`, `:146` (read only), `scripts/test_predictions_credit.py` or a new test file, `docs/agents/PUNDITS.md:185`.

---

### VI-2. `pundits_speaker_infer.py merge` writes `checked_by: model:<model>` for both harnesses, so the merged store hides which drafts ran on credit  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3, from the round-2 review of the credit runs. `infer` writes subscription drafts and `--credit-pools` drafts (`scripts/pundits_speaker_infer.py:368`) to the same `speaker_inference.jsonl`, and `merge_drafts` (`:334`) writes `"checked_by": f"model:{model}"` (`:352`) for both. Each draft's `telemetry` block (`:215`) does name the harness, `quotapick run` for a credit draft, so nothing is lost in the drafts file; the merged human store cannot tell them apart. All 218 P6b drafts are credit drafts today.

**Impact:** A reader of the merged store, or of a page built from it, cannot say which harness drafted a row, and VD-19 records that nobody has measured whether the two harnesses draft alike.

**Fix:** `merge_drafts` names the harness beside the model in `checked_by` (for example `model:claude-fable-5-1 (quotapick run)`) or in a field of its own, read from each draft's `telemetry.harness`, and refuses a draft with no harness rather than defaulting one. A check in `scripts/test_pundits_speaker_infer.py` merges one subscription draft and one credit draft and asserts the two rows differ, failing first. Quota-free.

**Touch points:** `scripts/pundits_speaker_infer.py:334-352`, its docstring at `:18-23`, `scripts/test_pundits_speaker_infer.py`.

---

### VI-3. `extract_predictions.main()`'s `code_revision_of` call is untested, and two speaker scripts record HEAD without a `+dirty` mark  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3 as the review nits of 2026-10-18 round 4. `scripts/extract_predictions.py:890` passes `L.REPO / "scripts"` and the skill directory to `code_revision_of` (`:813`), which appends `+dirty` when either path holds uncommitted changes. `scripts/test_predictions_credit.py:295` and `:305` test the function, but nothing tests the call, so dropping `skill` from it passes the suite. `scripts/annotations_select.py:343` (`git_revision`, used by `build` and `migrate` in `scripts/annotations.py`) and `scripts/speaker_segment_probe.py:176` record `git rev-parse HEAD` as `code_revision` with no dirty mark at all.

**Impact:** A speaker audit or probe run from an edited tree records a revision that did not produce it, the defect `code_revision_of`'s own docstring records (8 pundits pilot metas named one commit and ran another's code), and a regression in what `main()` hashes passes the suite.

**Fix:** (1) A check that drives the run-record builder in `extract_predictions.py` with a stubbed `code_revision_of` and asserts it receives both the scripts directory and the skill directory. (2) The two speaker scripts append `+dirty` when `git status --porcelain` on their own paths is non-empty, the way `code_revision_of` does; one check per script in `scripts/test_annotations_cli.py` and `scripts/test_speaker_segment_probe.py`, each failing first against a scratch repository with an edited file. Quota-free.

**Touch points:** `scripts/extract_predictions.py:813-830`, `:890`, `scripts/test_predictions_credit.py:295-305`, `scripts/annotations_select.py:343`, `scripts/annotations.py` (`build`, `migrate`), `scripts/speaker_segment_probe.py:176`, `scripts/test_annotations_cli.py`, `scripts/test_speaker_segment_probe.py`.

---

### VI-4. `index.json` counts credit extractions as plain `fable`, so it cannot tell the two Fable harnesses apart  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-3, from the adversarial review of `--credit-production` (e267bef). `scripts/aggregate_predictions.py:99-118` (`acceptance_by_harness_pair`) keys the extraction-harness breakdown on the record's `extraction.harness`, which stays `fable` for a credit call so that the different-family rule in verify still holds; the harness that actually ran is in `extraction.telemetry.harness` (`quotapick run`). On a copy of the pundits pilot, the 182 reviewed credit records (of 184; 2 have verification `not_run`) came out as one row, `extraction_harness: "fable"`. A second count has the same fault: `coverage.by_harness.extract`, which `summarise_meta` (`:130-138`) builds from each meta's `extract.harness`, read `{"fable": 280}` for the pilot's 280 credit transcripts. Meta files carry no telemetry, but their `router_account_id` starts with `credit:` for a credit run (260 of the 280).

**Impact:** `data/predictions/index.json` cannot show how many extractions ran on prepaid credit against how many on the subscription harness, and VD-19 says nobody has measured whether the two extract alike, so the one derived file that could show the mix hides it.

**Fix:**
1. In `acceptance_by_harness_pair`, key the extraction side on `extraction.telemetry.harness` when it is present and on `extraction.harness` otherwise, and name the credit rows distinctly (for example `fable (quotapick run)`); keep the raise at `:115` for a reviewed record with no harness.
2. In `summarise_meta`, split `by_harness.extract` on whether `router_account_id` starts with `credit:`.
3. A check in `scripts/test_predictions_aggregate.py` builds one subscription and one credit record and one meta of each kind, and asserts two rows and two counts, failing first.
4. Regenerate `index.json` with `scripts/data_sync.py push` on the next data push (it is a derived file; its bytes change); `scripts/test_derived_determinism.py` must stay green.

*Risks and edge cases:* `test_predictions_policy.py`, `test_predictions_index_roster.py` and `test_predictions_site_policy.py` read `index.json` fixtures and may pin the old row shape. `build_predictions_site.py` may read `verifier_acceptance_by_harness_pair`; if it does, the page copy that names harnesses needs the new label.

*Why premium not standard:* the naming of the harness key is a judgment call that `docs/agents/PREDICTIONS-PIPELINE.md` and the site copy will quote, and the derived file is read by four test files and the site builder.

**Touch points:** `scripts/aggregate_predictions.py:99-118`, `:130-138`, `scripts/test_predictions_aggregate.py`, `scripts/build_predictions_site.py` (if it reads the pair table), `docs/agents/PREDICTIONS-PIPELINE.md` (the index.json description).

---

### VI-6. A Fable stage of `resolve_predictions.py` with no `--fable-accounts` runs on the default account  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-11]`

**Background:** Filed by repo-0. `scripts/resolve_predictions.py:518` declares `--fable-accounts` with `default="default"`, and `:561-569` turns that into the account list for the `prior` and `lead_test` stages. `--stage lead_test` with no `--fable-accounts` ran its one call on `~/.claude` (`accounts=['default']` in `rebuild-20261011/lead_test-1.log`); it served `claude-fable-5-1` and cost $0.21. Nothing failed, but the operator has said account A has no Fable, and batch Fable work is meant to go to the accounts named for it. `scripts/grade.py:277` (`fable_accounts`) already routes by measured quota through `quota_router` when `FABLE_ACCOUNTS` is unset (`:2569`). The ledger deferred this to the next change to `resolve_predictions.py`.

**Impact:** A Fable stage started without the flag spends the operator's interactive account's quota, on the one account the operator has said should not carry batch Fable work, and nothing in the run summary says so.

**Fix:**
1. Decide between (a) refusing a Fable stage that names no accounts, at the cost that every caller must pass the flag, and (b) routing by measured quota the way `grade.py` does, at the cost that the stage gains the router. Recommended: (b), with the plain `default` account excluded unless named explicitly, because it matches the judge path and the operator's stated intent.
2. Implement it in `scripts/resolve_predictions.py` at `:518` and `:561-569`, logging the chosen accounts at `:733` as today.
3. A check in `scripts/test_predictions_driver.py` or a sibling: no flag, router stubbed, asserts the stage never runs on `default`, failing first.
4. `docs/agents/PREDICTIONS-PIPELINE.md` names the rule.

*Risks and edge cases:* `--fable-pool` (`resolve_predictions.py:524`, `:590`) is a different path (API credit) and must still refuse the other stages. The `ambient` label at `:733` covers a call with no account; keep it honest.

*Why premium not standard:* the choice between refusing and routing is a policy decision, and the router import brings `grade.py`'s failure handling with it.

**Touch points:** `scripts/resolve_predictions.py:518-524`, `:561-569`, `:733`, `scripts/grade.py:245-305` (read only), `scripts/test_predictions_driver.py`, `docs/agents/PREDICTIONS-PIPELINE.md`.

---

### VI-7. `judge_searched` can count a local file read as a web search  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-12]`

**Background:** Filed from the independent review of the 2026-10-12 pundits commits; plausible, not seen in data. `scripts/grade.py:2027` (`count_gemini_tool_events`) puts any completed tool step with a `query`, `Query`, `url`, `Url` or `AbsolutePath` parameter (`:2055`) into `web_search_queries`, so a `view_file` step would count. The error runs toward disclosing more searches than happened, never fewer. The `tool_use_counts["web_search"]` branch (`:647`, `:700`) matches only the codex harness (Astra, dropped); agy names its tool `search_web` (`:2031-2035`).

**Impact:** A grade's `judge_searched` disclosure, which the page shows beside the score, can say the judge searched the web when it read a file, so the published disclosure overstates what the judge did.

**Fix:**
1. Record the tool name per step in `count_gemini_tool_events` and count only search tools (`search_web` and any name agy documents for web search) toward `web_search_queries`; keep every other step in `tool_use_counts` by name.
2. A fixture in `scripts/test_judge_web_search.py`: a recorded agy transcript with one `view_file` step and one `search_web` step, asserting one search, failing first. The fixture must come from a real agy transcript (the per-grade stderr logs under the data repo's `logs/` hold them), not a hand-written guess at the event shape.
3. `docs/agents/JUDGES.md` says what counts as a search.

*Risks and edge cases:* a transcript with a tool name agy has since renamed would then count zero searches; the check must fail loud on an unknown tool name with a `query` parameter rather than drop it.

*Why premium not standard:* the fixture has to be found in real logs and the rule changes a published disclosure.

**Touch points:** `scripts/grade.py:2027-2060`, `:647`, `:700`, `:1340-1343`, `:2231-2232`, `scripts/test_judge_web_search.py`, `docs/agents/JUDGES.md`.

---

### VI-8. A `grade_loop.sh` render can replace `site-pundits/index.html` between the deploy's render and its upload  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-12]`

**Background:** `scripts/deploy_pundits.sh:60` renders into `SITE_DIR`, `:137` uploads it with `npx wrangler deploy`, and the loop's own render (`scripts/grade_loop.sh:244-252`, `$SITE_DIR/index.html`) can run between the two. Since 2026-10-12 the post-publish confirm (`deploy_pundits.sh:138-143`) fails loudly when it happens: the live page lacks the data revision's meta tag. So it is reported, not silent.

**Impact:** A deploy that loses the race publishes a page with no revision stamp, then fails its own confirm, and the operator must run it again while the loop keeps rendering.

**Fix:**
1. Either the deploy renders into a directory of its own (a temporary copy of `site-pundits/` with its `wrangler.pundits.toml` pointed at it) and uploads that, or the loop takes a lock the deploy also takes so the loop skips its render while a deploy runs. Recommended: the private render directory, because it needs no change to the loop's routine.
2. A check in a `scripts/test_deploy_pundits*.py` file that writes a different `index.html` into `site-pundits/` after the render step and asserts the uploaded page is the rendered one, with wrangler stubbed, failing first.
3. The leaders deploy (`scripts/deploy.sh`, `scripts/deploy_source.sh:57-67`) has the same shape; say in `docs/agents/SITES.md` whether it is covered.

*Risks and edge cases:* `revision.json` and its `_headers` rule (`deploy_pundits.sh:117-123`) must land in the same directory the upload reads. The dry run (`:134`) must keep rendering into the visible directory so the operator can read it.

*Why premium not standard:* it changes the publication path of a live site and touches the deploy guard's assumptions about where the rendered page is.

**Touch points:** `scripts/deploy_pundits.sh:60`, `:107-143`, `wrangler.pundits.toml`, `scripts/grade_loop.sh:244-252`, a new `scripts/test_deploy_pundits_render_dir.py`, `docs/agents/SITES.md`.

---

### VI-9. The labelling guide does not state the "correct every caption error you notice" convention VI-13 depends on  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** VI-13 brings back the caption-correction work once 50 operator corrections exist across 10 recordings, made under the convention that every caption error noticed in a reviewed passage is corrected, so that a reviewed word left alone counts as correct. The 2026-10-11 re-check found that convention "written nowhere except this entry, so it has never been in force", and asked for it to go into `docs/PUNDITS-LABELLING-GUIDE.md` before the next session. That guide's "Rules for every label" section (`docs/PUNDITS-LABELLING-GUIDE.md:11-27`) has no rule about the page's "Correct text" field.

**Impact:** Until the convention is written where a labelling session reads it, no session's corrections can count toward VI-13's threshold, and the count (15 over 5 recordings on 2026-10-11) cannot grow.

**Fix:** Add one rule to "Rules for every label": in a reviewed passage, correct every caption error you notice with the page's "Correct text" field, so that a word left alone counts as correct; name the counter, `.venv/bin/python scripts/annotations.py export corrections --session <dir> --out <file>` over each session.

**Touch points:** `docs/PUNDITS-LABELLING-GUIDE.md:11-27`.

---

### VI-25. Polymarket returns 400 for the 30-day `prices-history` window and 403 for some `public-search` queries, and the ladder stops at the first error  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/market_consensus.py:387` is the 30-day step of a three-step window ladder (2 days, 30 days, then from the market's open) at `fidelity=60`; for that step Polymarket answers HTTP 400 `invalid filters: 'startTs' and 'endTs' interval is too long` (endTs minus startTs is 2,592,000 s), and the error aborts the ladder, so the daily step that may succeed is never tried. `:290` (`public-search`) gets an HTTP 403 Cloudflare page for some queries. Across the corpus 8 accepted records fail this way on every run that reaches them, each carrying a consensus block with `status: failed`: `prices-history` 400 for fa01d301325e4243, 2012463b3b01b93d, d13eb0f50e17ffea (this supplement), michael-saylor 9d2d817a08c94853 and bill-gates bfecb68972253ee1; `public-search` 403 for d4b463de73917226 and jensen-huang 22f49209e94ce62f and c023eff1328d99e3. Ledger VP-38 logged the same 400 on 2026-10-05. Logs: data `predictions/_experiments/thin-supplement-20261018/market_consensus-{1,2,3}.log`.

**Impact:** eight accepted records can never get a market observation, and every consensus run counts them as failures.

**Fix:**
1. On a 400 from `prices-history`, fall through to the next ladder step instead of raising; record which step answered.
2. On a 403 from `public-search`, retry once, then record `blocked_by_host` as a terminal status instead of `failed`; that status touches `prediction_record.schema.json`, `validate_predictions.py` and the page's rendering of a consensus block. VI-32 adds a Kalshi retry in `Cache.get_json`; build this retry on that one path, not a second one.
3. Tests for both paths with a fake fetcher.

*Risks and edge cases:* a daily-fidelity observation for an old market may be sparse; the cutoff rule (strictly before publication) must hold for every step.

*Why premium not standard:* a new terminal status crosses the schema, the validator and the site.

**Touch points:** `scripts/market_consensus.py:283-298`, `:379-398`, `.agents/skills/prediction-extractor/prediction_record.schema.json`, `scripts/validate_predictions.py:205-225`, `scripts/build_predictions_site.py` (the consensus block), `scripts/test_predictions_markets.py`.

---

### VI-26. A dating run directory's `overrides.json`, `checks.json` and `queue.json` hold only the last merge's scope  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/date_recordings.py:1017-1040` rewrites the three files for the transcripts in scope of the current merge, so a run directory used for several `--ids` waves keeps only the last wave's entries and queue rows, and `scripts/promote_dating_run.py` would miss the earlier waves. Found by the review of public 698cdee on `dating-thin-supplement-20261018`, which ran in waves; that run avoided the loss by passing the union of every wave's datable ids on the final merge (every id left out was a `stated_in_page` source, which the stage no longer dates). Also, the per-call progress lines go to stderr with `flush=True` (`:102-104`) but the stdout banner and summary are block-buffered under `nohup`: in `dating/run-wave2c.log` the `SPENDS QUOTA` banner is line 106 of 111, after every progress line.

**Impact:** a promotion from a multi-wave run silently drops the earlier waves' confirmed dates, which decide eligibility and lead for their records.

**Fix:**
1. Merge over every transcript that has proposals on disk under the run directory, or refuse a `--stage merge` whose scope is narrower than the proposals directory; decide which (the first keeps old entries alive, the second makes the operator name the union).
2. Print the stdout banner and summary with `flush=True`.
3. Test: two merges with disjoint `--ids` into one run directory must leave both waves' entries on disk.

*Risks and edge cases:* a transcript with proposals from a run whose daters differ is refused before any merge today; the union merge must keep that refusal.

*Why premium not standard:* two design options that change which dates reach production, across the merge, the promotion and the agreement text.

**Touch points:** `scripts/date_recordings.py:905-926`, `:950-1045`, `:1055-1066`, `scripts/test_date_recordings.py`, `docs/agents/DATING.md`.

---

### VI-31. A network error in a market fetch escapes `process_file`, fails the whole file with no error label, and loses every record already finished in it  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/market_consensus.py:111-118` (`http_get`) catches only `urllib.error.HTTPError`. A `URLError`, a `TimeoutError`, a connection reset or an `http.client` error (`IncompleteRead`, `BadStatusLine`; neither is an `OSError`) is not a `RuntimeError`, so it passes `gather_candidates`'s handler at `:548`, the observation handler at `:588` and `process_file`'s handler at `:683`, up to `main`'s catch-all at `:761-762`, which records `{"status": "failed", "error": "<type>: ..."}` for the file with no `errors` list. `:769-772` builds `error_taxonomy` from `errors` only, so the failure is counted in `file_failures` (`:776`) and nowhere in the taxonomy. A second door: `Cache.get_json` writes the cache file at `:177` before it parses the body at `:180`, so a 200 whose body is not JSON is cached and replayed on every later read, and its `JSONDecodeError` escapes the same way. `process_file` writes the file once, at `:694`, after every record in it is done, so a network error on record 40 of 50 discards the 39 finished consensus blocks, including matcher calls that already spent model quota, and the next run redoes them.

**Impact:** one dropped connection costs a whole file's work and shows in the summary as a bare file failure, not as a network error.

**Fix:**
1. In `Cache.get_json` (`:155-180`), catch `urllib.error.URLError`, `TimeoutError`, `OSError` and `http.client.HTTPException` around the fetcher call only, and raise `RuntimeError(f"{E_MARKET_HTTP}: <type>: <reason> for <url>")`, so every handler below sees one exception class. Nothing is cached for it.
2. Parse the body before writing the cache file; a 200 that does not parse raises the same `market_api_error` and is not cached.
3. Write the file after each record's consensus block is set (or every N records), through `L.write_prediction_file`, so finished work survives a later crash; keep the final write.
4. In `main`'s catch-all (`:761-762`) add an `errors` entry with `error_type` from `L.classify_exception_detail`, so the taxonomy counts it. VI-30 (`f998861`) put the `market_api_error` label in `predictions_lib.ALL_ERROR_TYPES` (`scripts/predictions_lib.py:101-103`).
5. Tests: a fetcher that raises `URLError` leaves the record `failed` with `reason: None` and `error` starting `market_api_error:`, the file still holds the records finished before it, and the run summary's `error_taxonomy` names it; a fetcher that returns a non-JSON 200 leaves no cache file; a fetcher that raises midway through a two-record file leaves the first record's block on disk.
6. Optional: re-raise `RefusedDataWrite` from the handlers at `:548` and `:588`, with a test that a cache writer raising it stops the run instead of filing a record error.

*Risks and edge cases:* a per-record write multiplies writes by the records per file (up to a few dozen); `write_prediction_file` is atomic, so a reader in another clone never sees a prefix, and the index's `files_read` and `inputs_sha256` fingerprints (written by `aggregate_predictions.py`, not by this run) already move on the final write. Today a `RefusedDataWrite` raised by the cache write is a `RuntimeError` and is swallowed into a record error at `:548` and again at `:588` (the `observe_*` calls write the cache too); the new catch must sit around the fetcher call only, so it does not widen that.

*Why premium not standard:* it changes when a record file is written, and the choice between per-record and batched writes is a judgment about cost against lost work.

**Touch points:** `scripts/market_consensus.py:111-118`, `:155-180`, `:548`, `:652-695`, `:761-762`, `scripts/test_predictions_markets.py` or `scripts/test_market_consensus_cache.py`.

---

### VI-32. The Kalshi lock serializes fetches but does not re-check the cache, back off, or retry, so one 429 still fails its record for the run  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** since `87c42e3` (VI-24) `scripts/market_consensus.py:155-180` (`Cache.get_json`) fetches Kalshi under a per-process `threading.Semaphore(1)` (`:169-172`) and raises on a transient status (`:175-176`). Three things the lock does not do: (a) it does not look at the cache again after it is taken, so three workers that asked for the same URL at once make three back-to-back Kalshi calls (the one-popular-URL pattern of the `ECLIPSECOVER` incident); (b) it adds no gap between calls and reads no `Retry-After`, so whether one serialized stream stays under Kalshi's limit at the 707-call scale of the first 2026-10-18 run is unproven (the one-worker reruns made 17 and 62 calls); (c) a 429 fails the record for this run and only the next run retries it (`:655-657`). The lock is also per process, so two concurrent runs each have their own. 408 is not in `transient_status` (`:121-130`), so a 408 would be cached and replayed like the original bug.

**Impact:** a burst of identical Kalshi URLs still costs one call each, and a single 429 still costs the record a run.

**Fix:** inside the lock, read the cache again before fetching. `http_get` (`:111-118`) returns only `(status, body)` and drops `exc.headers`, so first pass the `Retry-After` value through, as an optional third tuple element so the 2-tuple fake fetchers in `scripts/test_predictions_markets.py` and `scripts/test_market_consensus_cache.py` keep working. Then on a 429, sleep `min(Retry-After, 5)` seconds when the header is present, else 2 seconds, and retry exactly once before raising; the sleep runs inside the Kalshi lock on purpose (it is the one stream Kalshi sees), and the cap keeps a large `Retry-After` from stalling every worker. Add 408 to `transient_status`. Tests: six workers asking the same Kalshi URL make one fetch; a 429-then-200 fetcher gives a result within the same read (the existing `test_market_consensus_cache.py` check that the first 429 read raises changes to expect the retry); a `Retry-After: 600` sleeps 5 s at most (inject the sleep). Record in the docstring that the lock is per process. VI-25 step 2 adds its own retry for Polymarket; both should share one retry path in `get_json`.

**Touch points:** `scripts/market_consensus.py:111-118`, `:121-130`, `:155-180`, `scripts/test_market_consensus_cache.py`, the fake fetchers in `scripts/test_predictions_markets.py`.

---

### VI-33. The gate's Node test passes without running: `test_site_tooltip.js` prints `SKIP` and exits 0 when jsdom is absent, and no clone has jsdom  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/test_site_tooltip.js:12-13` wraps `require("jsdom")` in a try and, when it is missing, prints `SKIP: jsdom not installed (npm install jsdom)` and exits 0. Its header (`:8-9`) says jsdom "is not a dependency of this repo". `scripts/run_tests.sh:40` counts the test as passed on exit 0, so every gate run reports it green. Verified in repo-1 on 2026-10-18: `node scripts/test_site_tooltip.js` printed the SKIP line and exited 0, and `node -e 'require.resolve("jsdom")'` fails with `MODULE_NOT_FOUND` (no `node_modules` in any of the five clones, nothing on `NODE_PATH`, nothing in the global npm root). Since VI-29 the SKIP line survives in `.gate/<run>/test_site_tooltip.js.log`, where nothing reads it.

**Impact:** the tooltip test does not run in the gate in any clone today (whether it ever did cannot be shown: the old runner sent its output to `/dev/null`); a regression in the site tooltip would pass `failed: 0` in every clone.

**Fix:** make the skip loud and counted: have the runner treat a Node exit code of its own (77, the usual skip code, set by the test on the missing module) as `SKIPPED test_site_tooltip.js (jsdom not installed)` and print a `skipped: N` line beside `failed: N`, still exiting 0, so the gate's output says what did not run; or add jsdom as a dev dependency (`package.json`; the repo has none and the setup block has no `npm install`) and drop the skip. Either way the test reads `site/index.html` (`:15`), a built page that git does not track (`.gitignore`), so a fresh clone has no page and a clone's page is as stale as its last build: option 2 turns a fresh clone's gate red with ENOENT, and the first real run may fail for old reasons because the test has not run in the gate. Decide one, say why in the runner header, and add a check to `scripts/test_run_tests_sh.py` with a fake Node test that exits 77.

**Touch points:** `scripts/test_site_tooltip.js:8-15`, `scripts/run_tests.sh:40`, `scripts/test_run_tests_sh.py`.

---

### VI-34. A matcher answer with no JSON files as `matcher_error`, while the other three stages file the same failure as `no_json_in_response`  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/market_consensus.py:568` calls `L.extract_json(text)` on the matcher's answer with no wrapper, so a `ValueError` ("no opening brace in response", `scripts/grade.py:901`) or a `json.JSONDecodeError` reaches the handler at `:577-582`, which since `f998861` (VI-30) prefixes an unlabelled message with `matcher_error: `. The other stages label that failure before it escapes: `scripts/extract_predictions.py:379-384` (`parse_model_output`) raises `no_json_in_response` or `json_parse_error`, `scripts/grade.py:2479-2483` picks between the two by the message, and `scripts/resolve_predictions.py:409-412` raises `no_json_in_response`. Today the corpus holds no matcher failure of this kind (the 8 failed consensus blocks in the data are all `market_api_error`), so the count is right by luck.

**Impact:** a count of `no_json_in_response` across stages leaves out consensus runs, and a matcher that starts returning prose shows up under the label for "the matcher stage, with no label of its own".

**Fix:** wrap the call at `:568` with grade.py's rule (`:2479-2483`), which picks by message, not by exception type: only "no opening brace" (`grade.py:901`) is `no_json_in_response`; every other `extract_json` failure, a `JSONDecodeError` (`:922`) or the `ValueError("unbalanced braces in response")` of a truncated answer (`:923`), is `json_parse_error`. Raise `RuntimeError(f"{label}: {exc}")` and `matcher_error_text` keeps the label. Do not copy `parse_model_output` (`extract_predictions.py:379-384`), which picks by type and mislabels a truncated answer (VI-35). Test in `scripts/test_market_consensus_taxonomy.py`: a matcher that returns prose files `no_json_in_response`; one that returns `{"a": 1,, }` and one that returns the truncated `{"a": 1, "b": [2, 3` both file `json_parse_error`; a matcher that raises a bare `ValueError` still files `matcher_error`.

**Touch points:** `scripts/market_consensus.py:566-582`, `scripts/test_market_consensus_taxonomy.py`.

---

### VI-35. `extract_predictions.parse_model_output` never files `json_parse_error`: it catches `ValueError` before `json.JSONDecodeError`  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/extract_predictions.py:379-384` catches `ValueError` first and `json.JSONDecodeError` second. `json.JSONDecodeError` is a subclass of `ValueError`, so the second branch never runs: malformed JSON such as `{"a": 1,, }` raises `JSONDecodeError` from `L.extract_json` (`scripts/grade.py:922`) and is filed as `no_json_in_response`, the label for an answer with no JSON at all. A truncated answer, `{"a": 1, "b": [2, 3` (the output-cap case of VI-23), raises `ValueError("unbalanced braces in response")` at `grade.py:923` and is filed the same way, and swapping the two branches would not change that. `grade.py:2479-2483` picks the label by message instead: only "no opening brace" is `no_json_in_response`. `scripts/resolve_predictions.py:409-412` files every `extract_json` failure as `no_json_in_response` too, but it is left out of this item on purpose: it has its own error list (`:68-69`) and its own `classify` (`:335-347`), whose loop at `:344` knows a fixed set of labels and files any other as `other`, so a change there is a second classifier with its own test; that half is VI-38. Found by the VI-30 review on 2026-10-18 with those inputs.

**Impact:** an extraction run's `error_taxonomy` cannot tell a model that answered in prose from one that answered in broken JSON, which are different failures with different fixes (prompt against harness).

**Fix:** in `parse_model_output`, pick the label by message as `grade.py:2481` does: "no opening brace" is `no_json_in_response`, anything else from `extract_json` is `json_parse_error`. Add checks to `scripts/test_predictions_driver.py`, the only test that calls `parse_model_output`: `no JSON here` files `no_json_in_response`; `{"a": 1,, }` and the truncated `{"a": 1, "b": [2, 3` both file `json_parse_error`; failing first.

**Touch points:** `scripts/extract_predictions.py:379-384`, `scripts/test_predictions_driver.py`.

---

### VI-36. `sources_to_manifest.py` rewrites `sources/repairs.json` from discovery, so a hand-added ASR repair does not survive the next rebuild  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** Filed by repo-2 while promoting david-sacks and chamath-palihapitiya (VI-14, closed). Three ASR name forms (`chamat`, `chamathie`, `David sax`) survived blinding and the natural fix was a pair in `sources/repairs.json` for `normalize_transcripts.py --repairs`. Rehearsed on scratch copies, `sources_to_manifest.py --sources ... --manifest ... --aliases ... --repairs ...` reported `repair_pairs: 0` and wrote the file back with every list empty, dropping the hand-added pairs, while it MERGED `aliases.json` (`alias_terms_preserved_by_merge: 17`). Every slug's repairs list is empty today, so nothing has been lost yet; the forms were put in `aliases.json` instead (they blind as `[SUBJECT]`, which is right for a name form). The script builds `repairs` from the discovery payload alone (`scripts/sources_to_manifest.py:57-71`) and writes it whole (`:182`), while `aliases` goes through a merge that keeps hand-added terms (`:130-172`). No loop runs the rebuild: it is stage 1 of `scripts/run_pipeline.sh` (`:36-42`), run by hand on the daemon clone, and the roster-add procedure runs it directly but sends `--repairs` to a scratch file for this reason (`docs/ROSTER-EXPANSION-2026-09-10.md:321-325`); neither `fetch_loop.sh` nor `grade_loop.sh` has ever called it.

**Impact:** The repairs mechanism, which the loop wires on every normalize, cannot hold a curated entry: the first discovery rebuild after a hand edit silently reverts it, and a misspelt surname leaks to the judge again with nothing in a log to say so.

**Fix:** Merge repairs the way aliases are merged (keep every pair the file holds that discovery did not return, name dropped pairs in the report, `--replace-repairs` for the destructive form), with a failing-then-passing check in the manifest test that a hand-added pair survives a rebuild. Then move the three forms from `aliases.json` back to `repairs.json`, or record in BLINDING.md that aliases are the place for ASR name forms.

**Touch points:** `scripts/sources_to_manifest.py:57-71` (repairs from discovery only), `:182` (the write), `:204` (the report's `repair_pairs`), `:38` (beside `--replace-aliases`, for `--replace-repairs`); its test `scripts/test_aliases_subset.py`, whose docstring says at `:28-29` that repairs.json carries no exposure; `docs/agents/CORPUS.md` or `BLINDING.md`, `data/sources/repairs.json`.

---

### VI-37. The blinder applies only the subject's own alias list, so a co-host leader's name forms survive in another leader's transcript  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** Found by the post-push review of the VI-14 data commit. `blind()` (`scripts/normalize_transcripts.py:402`; the live branch is `:427-430`, since no production caller passes a `wordlist`, and `:432-437` is the opt-in split) redacts the subject's name, company and aliases. Normalize passes it only the subject's alias list (`aliases.get(slug, [])`, `:962-963`), and passes `blind_study()` the same list (`:959-960`), so a second roster member named in the recording keeps every form. Measured on chamath-palihapitiya's 10 graded transcripts: `\bsax\b` 5, "David sacks" 5, "sacks" 2 across lex-fridman-kfqudc, mit-vcpe-club-q09n5t and tucker-carlson-erlkcr. The All-In hosts name each other constantly, so this pair is the sharpest case on the board, but it is pre-existing for every leader who appears in another's recording (the Nate Silver record notes the Risky Business co-host for the same reason).

**Impact:** A judge blinded against the subject can still read the co-host's name, which narrows who the subject is (the other All-In host), and the identity-recognition rate the audit reports may be understated for exactly those recordings.

**Fix:** Measure first: over `transcripts_blind/`, count surviving forms of every OTHER roster member's name and alias list per transcript, and report the leaders whose shelves carry the most. Then decide with the operator whether to blind every roster member's forms (changes blinding for the whole corpus, which makes new grades incomparable with old ones unless the corpus is re-blinded and re-graded) or to record it as a known limit in `docs/agents/BLINDING.md`. The measurement alone is the `fast` item; the change is a separate, larger one.

**Touch points:** `scripts/normalize_transcripts.py:402-437` (`blind()`, live branch `:427-430`) and `:959-963` (its call sites), read only for the measurement; `docs/agents/BLINDING.md`; a new measurement script under `scripts/`.

---

### VI-38. `resolve_predictions.py` files broken or truncated JSON as `no_json_in_response`, and its classifier would file `json_parse_error` as `other`  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-18]`

**Background:** `scripts/resolve_predictions.py:409-412` catches `ValueError` and `json.JSONDecodeError` from `extract_json` together and raises `no_json_in_response` for both, so an answer with broken JSON (`{"a": 1,, }`, a `JSONDecodeError` at `scripts/grade.py:922`) or a truncated one (`{"a": 1, "b": [2, 3`, `ValueError("unbalanced braces in response")` at `grade.py:923`) is filed as an answer with no JSON at all. `grade.py:2479-2483` picks the label by message instead: only "no opening brace" (`grade.py:901`) is `no_json_in_response`, everything else is `json_parse_error`. Resolve's own error list `ERROR_TYPES` (`:68-69`) has no `json_parse_error`, and its own `classify` (`:335-347`) matches the label at the front of an error against a fixed set at `:344` (`E_NOJSON, E_SCHEMA, E_RULES, E_LEAK, E_CLI`) and files anything else as `other`. That check comes after a word scan (`:339-343`) that files any message containing "401" or "auth" as `auth_or_quota`, and a JSON error message carries column and character positions (`Expecting ',' delimiter: line 1 column 402 (char 401)`), so today `classify("no_json_in_response: ... (char 401)")` returns `auth_or_quota`. Resolve's own `rule_violation` messages (`:429`) quote text the model wrote, its `unresolvable_reason` and its search queries, so one that mentions "authority" or "FDA authorization" files as `auth_or_quota` and one that mentions "rate limit" as `cli_timeout`, for the same reason. Found by the VI-30 review on 2026-10-18; the same gap in the matcher and the extractor is VI-34 and VI-35. This item carries the resolve half that VI-35 names and leaves out.

**Impact:** a resolve run's `error_taxonomy` cannot tell a model that answered in prose from one that answered in broken or cut-off JSON; and if the handler alone were changed to raise `json_parse_error`, the summary would file those as `other`, which hides them more than today.

**Fix:** one change in four places of the same file, with the by-message rule: define `E_BADJSON = "json_parse_error"` beside `E_NOJSON` (`:64`), add it to `ERROR_TYPES` (`:68-69`), and check every label resolve writes itself (`E_NOJSON`, `E_BADJSON`, `E_SCHEMA`, `E_RULES`, `E_LEAK`) before the word scan (keep only `E_CLI` after it: that text is a CLI's own error output, where those words mean what they say), and at `:409-412` raise `E_NOJSON` only when the message says "no opening brace", else `E_BADJSON`. Test in `scripts/test_fable_pool.py` (its `[CLASSIFY]` section, `:342-345`): `classify("json_parse_error: ...")` returns `json_parse_error`, `classify("json_parse_error: Expecting ',' delimiter: line 1 column 402 (char 401)")` returns `json_parse_error` (one check for the new label and the label order), and a `rule_violation` message quoting "authority" stays `rule_violation`, all failing first; and the handler files `no JSON here` as `no_json_in_response`, and both `{"a": 1,, }` and the truncated `{"a": 1, "b": [2, 3` as `json_parse_error`.

**Touch points:** `scripts/resolve_predictions.py:64`, `:68-69`, `:339-344`, `:409-412`, `scripts/test_fable_pool.py:342-345`.

---

### VI-42. Four Fable `claude -p` harnesses still run under the 64,000-token default cap, with no check for a cut answer  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-19]`

**Background:** since VI-23 (2026-10-19), `credit_run.run` and `grade.call_fable` give their child `CLAUDE_CODE_MAX_OUTPUT_TOKENS` at 128,000 through `credit_run.child_env`, and refuse a cut answer as `continuation_truncated` through `credit_run.truncation_detail`. Four other harnesses start a Fable `claude -p` of their own and copy the environment as it is: `scripts/date_recordings.py:452` "env = dict(os.environ)" (`call_fable_web`, the production `fable_web` dater, which has WebSearch and WebFetch), `scripts/pundits_speaker_infer.py:148` "def call_model(" (the P6b speaker drafts on a subscription; its credit drafts already go through `credit_run.run`), `scripts/speaker_segment_probe.py:97` "env = dict(os.environ, CLAUDE_CONFIG_DIR=config_dir)", and `scripts/p3_judge_probe.py:107` "def run_fable(". MEASURED 2026-10-19: the speaker-audit raw file `data/predictions/_experiments/speaker-audit-20260927/segmentation/leaders-r2/raw/fable__michael-dell__david-senra-9wssls__r1__a2.json` has `usage.output_tokens` 256,000 and one iteration of 64,000, a gap of 192,000, and its result is the CLI's text "API Error: Claude's response exceeded the 64000 output token maximum". The VI-23 review counted 22 cut `seg-work-*-fable` sessions from 2026-09-28. Found by the VI-23 review.

**Impact:** a long answer from one of these harnesses is cut at 64,000 tokens and comes back as its last part, or as an error text, with no label that names the cause. Dating answers are short, so the dater's exposure is small; the speaker-segmentation probe has already lost answers this way.

**Fix:** build each harness's environment with `credit_run.child_env()` (each then adds or drops its `CLAUDE_CONFIG_DIR` as today), and add it to the JUDGES.md VI-23 rule's list of covered harnesses. Do not add the token-gap check to these four yet. The VI-23 round-2 review found that 22 of 24 subscription Fable sessions with a cut turn on this machine were cut while still thinking, after which the CLI asked for a fresh answer; in the speaker-probe sessions that gave 2 whole answers for each fragment at the 128,000 cap, and the gap check refuses all three. Add the check once VI-43's transcript rule can pass a thinking-only cut, and say so in a comment at each site. Tests, failing first: for each of the four, a fake `claude` that records the variable sees 128000.

**Touch points:** `scripts/date_recordings.py:452` "env = dict(os.environ)", `scripts/pundits_speaker_infer.py:148` "def call_model(", `scripts/speaker_segment_probe.py:97` "env = dict(os.environ, CLAUDE_CONFIG_DIR=config_dir)", `scripts/p3_judge_probe.py:107` "def run_fable(", `scripts/test_dating_fable_web.py`, `scripts/test_pundits_speaker_infer.py`, a new test for the two probes, `docs/agents/JUDGES.md`.

---

### VI-43. `grade.call_fable` refuses a whole answer after 128,000 tokens of tool turns, or after a turn cut while still thinking, because the token gap cannot tell those from a cut answer  `[capability: premium]`  `[priority: P3]`  `[filed: 2026-10-19]`

**Background:** `grade.call_fable` refuses an answer as `continuation_truncated` when `usage.output_tokens` minus `usage.iterations` is at least 128,000, or an exact multiple of 64,000 (`scripts/grade.py:1161` "cut_at=credit_run.CLI_DEFAULT_MAX_OUTPUT_TOKENS)"). On this subscription harness a tool call, denied or not, also ends a turn, and its tokens land in the same gap. The VI-23 work and its review measured on this machine's transcripts (2026-10-19): earlier tool turns of 64,868 to 73,007 tokens came before a whole answer in 3 of 442 Fable predictions sessions, and of 75,382 and 101,698 in 2 of 434 `fable` dating sessions. The 101,698 one, the session for chamath-palihapitiya/axios-qly04q in dating run `20261002T033749Z` (Claude Code 2.1.287), had turns of 3,486, 226 and 97,986 tokens, each ending in `tool_use`, then 1,962 ending in `end_turn`. With the turn cap now 128,000, one long tool turn can reach the threshold alone. The session transcript says which turn was cut: a cut turn's assistant message has `stop_reason` `max_tokens`, and `call_fable` already reads that transcript through `scripts/grade.py:1065` "def fable_transcript_tool_calls(" when `require_no_tools` is set.

**Impact:** a paid, whole subscription answer is refused as `continuation_truncated`. The failure is loud and costs one call of subscription quota and a retry; it falls on long transcripts, where tool turns run longest.

**Fix:**
1. In `call_fable`, when `truncation_detail` refuses, read the session transcript (the same lookup as `fable_transcript_tool_calls`) and keep the refusal only if an assistant message before the last one has `stop_reason == "max_tokens"` and holds a text block, a cut in the middle of the answer. A `max_tokens` message with no text and no `tool_use` block is a cut while thinking: the CLI drops that reasoning and asks for a fresh answer, so the answer that follows is whole and passes. The VI-23 round-2 review measured the mix on this machine's subscription Fable transcripts (2026-10-19): of 24 sessions with a `max_tokens` turn, 22 were cut while thinking and 2 mid-text; three dating sessions and two speaker-probe sessions answered whole JSON after a thinking cut, and one speaker-probe session (lisa-su) returned a fragment. A missing transcript, or a message with no `stop_reason`, keeps the refusal, and the message says which.
2. Tests in `scripts/test_continuation_truncated.py`, failing first: tool turns totalling 130,000 with no `max_tokens` pass; a thinking-only `max_tokens` turn passes; a `max_tokens` turn with text is refused; a missing transcript is refused.
3. Update the VI-23 rule in `docs/agents/JUDGES.md`.

*Risks and edge cases:* the transcript is Claude Code's private format and can change, so missing evidence must keep the refusal rather than accept the answer. The credit path keeps the token rule: it runs `--no-session-persistence` and has no transcript. A cut turn after which the model restarted its answer whole is still refused; that is the token rule's known limit and is out of scope here.

*Why premium not standard:* it changes when a paid answer counts on the judge harness, reads a private transcript format, and its failure direction must stay loud.

**Touch points:** `scripts/grade.py:1161` "cut_at=credit_run.CLI_DEFAULT_MAX_OUTPUT_TOKENS)", `scripts/grade.py:1065` "def fable_transcript_tool_calls(", `scripts/test_continuation_truncated.py`, `docs/agents/JUDGES.md`.

---

### VI-47. The predictions resolver runs only on Astra; there is no Gemini 4 Argon (`agy`) resolver to measure beside it  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-20]`  `[effort: xhigh]`  `[claimed by: #0]`

**Background:** Operator request of 2026-10-20, relayed by repo-1: add a Gemini 4 Argon resolver harness as an option and measure it, with Astra staying the default and the production resolver. The resolver has one harness today, `scripts/resolve_predictions.py:17` "The RESOLVER runs on Astra, through `codex exec`". The operator requires the Gemini resolver to open the pages it cites, and the Gemini judge harness cannot: agy ends a run on an auto-denied tool (`docs/agents/JUDGES.md:401` "The mechanism explains the result. agy ends a run when a tool is auto-denied,"), and page access was ruled out before because it would also reach the leaders board's blinded Gemini grader (`scripts/dating_lib.py:2153` "Granting it page access is not an"). The effort floor reads codex events only (`scripts/grade.py:705` "def web_search_actions(events: list[dict]) -> dict:"); the Gemini counter keeps 10 queries (`scripts/grade.py:2083` "def count_gemini_tool_events("), so `scripts/resolution_lib.py:901` "def validate_effort(obj: dict, telemetry: dict)" has nothing to check a Gemini answer against.

**Impact:** No second resolver exists to check Astra's outcomes, or its `already_public` calls, against.

**Fix:**
1. Probe agy live with model `gemini-4-argon-high` (agy's ids are `gemini-4-argon-low`, `-medium` and `-high`): allow web search and page reads for the resolver only, deny file reads and commands, and keep the raw output. If that cannot be done without reaching the grader, stop and report it to the operator.
2. Test first, then add a Gemini equivalent of `web_search_actions` (every query, in order, uncapped) that feeds `validate_effort` unchanged.
3. Add `--resolver gemini` to `resolve_predictions.py`, default `astra`, refused for any `--out` that `scoring.json` names.
4. Run it on 20 to 30 rows Astra resolved under the current release, chosen by a stated outcome-balancing rule, into a new `_experiments/` folder that is never named in `scoring.json`, so no board row's resolver changes. Every compared pair shares one `policy_release` and one `prompt_sha256`; a run takes its checkout's release, so if fewer than 20 qualifying Astra rows carry that release, re-resolve the chosen rows with Astra under it into the same experiment, or stop and report; leave out the five operator-adjudicated rows `94522ddc8049659a`, `897e1fe74a77f88c`, `1e869ff2affb0357`, `5c16324b2d6126ea`, `9df7d48a5a1e187a`. Report row-by-row agreement on `outcome` and `already_public`, with each disagreement's sources.

*Risks and edge cases:* a permission change that reaches the grader's profile config un-blinds the leaders board; Gemini can find the public predictions site's own verdict for the row; repo-1 is cutting a policy release that edits the resolver prompt, so this item edits no prompt text and no release constant.

*Why premium not standard:* new harness wiring across `grade.py` and the resolver, a permission boundary that protects blinding, and an experimental design.

**Touch points:** `scripts/grade.py`, `scripts/resolve_predictions.py`, new tests, `docs/agents/JUDGES.md`, `docs/agents/PREDICTIONS-PIPELINE.md`, and a new folder under the data repo's `predictions/_experiments/`.

---

### VI-49. The predictions build's summary line pairs the page's scored count with its past-due count, so it says "585 of 834" where the page says 546 of 834  `[capability: fast]`  `[priority: P3]`  `[filed: 2026-10-20]`

**Background:** `scripts/build_predictions_site.py:3117` "the page prints {cl['scored']} of {cl['past_due']} past due" prints every scored prediction of the listed people against their past-due count. The page itself (`scripts/build_predictions_site.py:2587` "def score_legend(c: dict) -> str:") counts only the scored predictions that are past due, and names the early-called ones separately. On 2026-10-20 the deploy dry run printed "the page prints 585 of 834 past due scored", while the live page printed "546 of 834 past-due predictions could be checked and scored" and "(585 scored in all)": the 39 between them are predictions called early, scored before their deadline. The `scores:` line just above (`:3114`) pairs corpus `scored` with `past_due` the same way. Found by the review of the VI-45 deploy record on 2026-10-20.

**Impact:** an agent that reads the build log reports a scored share the page does not show. It has already happened: the ledger row VP-45 first quoted "585 of 834", and VD-23 first explained 587 against 862 without the early calls.

**Fix:** test first: a test that builds the summary line and the legend from one fixture with an early-called prediction, and asserts that the line's past-due scored count equals the legend's; red today. Then print on the `listed:` line the counts `score_legend` uses, with the early calls named apart (`listed_corpus` already computes them for the listed people). The `scores:` line reads the `scores.json` corpus block, which has no early-call count, so take that count over all rows of `scores_doc["predictions"]`.

**Touch points:** `scripts/build_predictions_site.py:3114` "past due scored, ", `scripts/build_predictions_site.py:3117` "the page prints {cl['scored']} of {cl['past_due']} past due", and the site test file the new test joins.

---

### VI-51. A scored card whose resolution carries an operator ruling shows no note of it, so two ruled cards end by saying the prediction was already public  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-20]`

**Background:** When the operator rules on a row, the resolution sidecar keeps the resolver's outcome, sources and reasoning, sets `already_public`, and adds an `adjudication` block (VD-22 for Ellison; VD-24 and VP-46 for Gelsinger `1e869ff2affb0357` and Sweeney `5c16324b2d6126ea`). The scorer copies the resolver's reasoning and `already_public` into the row (`scripts/score_predictions.py:168` "Only a sidecar under a release carries the field") but nothing from `adjudication`, and the page notes `already_public` only on a scored row whose date is not exact (`scripts/build_predictions_site.py:2059` "Scored, with an open question"). Since the 2026-10-20 deploy (VD-25), Sweeney's card scores -1.15 and its reasoning ends "Epic separately announced the matching 2025 rollout plan on January 24, before Sweeney spoke"; Gelsinger's ends "already publicly reported by eWeek on August 28, 2006". Found by the pre-deploy review of VD-25.

**Impact:** a reader sees a scored card whose own text says it should have been excluded, with no sign that the operator ruled on it. The reviewer also counted 8 scored cards whose reasoning prints the field name `already_public`.

**Fix:** test first: a fixture resolution with an `adjudication` block must give a row carrying the ruling (who, when, what changed), and the rendered card a one-line note such as "Operator ruling: not already public"; red today. Then carry a small `adjudication` summary into the scores row (score_predictions) and render it on the card (build_predictions_site). Regenerate with `data_sync.py push`; this changes `scores.json`, so it needs a deploy.

**Touch points:** `scripts/score_predictions.py:168` "Only a sidecar under a release carries the field", `scripts/build_predictions_site.py:2059` "Scored, with an open question", their tests.

---

### VI-10. Every `grade_loop.sh` cycle retries Gemini up to three times on six transcripts it has never graded  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-11]`  `[BLOCKED: operator picks option (a), (b) or (c)]`

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

*Why premium not standard:* a cross-run state file in a daemon's path and a change to what the run summary says a judge did.

**Touch points:** `scripts/grade.py:2062-2151`, the run summary writer, a new test file, `docs/agents/JUDGES.md:413-452`.

---

### VI-11. `validate_grader.py` says it "mirrors aggregate.py's own gates" and no longer does  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-11]`  `[BLOCKED: its V1-V5 figures are next quoted or re-run]`

**Background:** `scripts/validate_grader.py` was last changed on 2026-09-06, and its `load()` (`:88`) has drifted from `aggregate.py` in four ways since. (1) It drops a GRADE whose own subject share is under its `MIN_SUBJECT_SHARE` (`:37`, which is 15 while `scripts/aggregate.py:112` is 10), while `aggregate.filter_unscorable` (`aggregate.py:172`) drops a whole RECORDING when the judges' mean share is under the cutoff or any judge says 0, the rule `docs/agents/SCORING.md` records with its measured cost. (2) It skips `_raw/` (`:92`) and not `_obsolete/`, which `aggregate.load_grades` skips (`aggregate.py:232`). (3) It applies no board membership (`aggregate.py:1204-1206`, `:1396`). (4) It swallows any unreadable grade or transcript file (`except Exception` at `:96` and `:249`) and reports nothing. No test covers it and no loop runs it, so nothing published reads it today, but its V1-V5 figures are quoted as grader validation.

**Impact:** The next time its numbers are quoted they describe a different corpus than the board: a different share cutoff, obsolete grades included, off-board people included, unreadable files silently dropped.

**Fix:**
1. Make `load()` call `aggregate.load_grades`, `aggregate.filter_unscorable` and the membership reader rather than restating them, and raise on an unreadable file.
2. A test that builds a small corpus with one obsolete grade, one under-share recording and one off-board person, and asserts the validator's counts equal the aggregate's, failing first.
3. Re-run V1-V5 and record the new figures where the old ones are quoted (`docs/agents/MAP.md`, grader validation).

*Risks and edge cases:* the V1-V5 figures move; quote them with the date and the commit.

*Why premium not standard:* three loaders to replace and published figures to re-derive.

**Touch points:** `scripts/validate_grader.py:37`, `:88-110`, `:249`, `scripts/aggregate.py:172`, `:227-232`, `:1204-1206` (read only), a new `scripts/test_validate_grader.py`, `docs/agents/MAP.md`.

---

### VI-12. `test_log_bloat.py` reads the leaders daemon's live checkout, so the suite goes red in every clone while repo-0 is mid-rebuild  `[capability: standard]`  `[priority: P2]`  `[filed: 2026-10-11]`  `[BLOCKED: a second red from it that is not a rebuild in progress]`

**Background:** The market-cache section of `scripts/test_log_bloat.py` takes `production_path(REPO)` (`:58-60`), the shared `verbatim-index/data` the daemons write, not the clone's own `data` link, and asserts every accepted prediction carries market provenance (`:162-164`). At 04:00 PDT on 2026-10-11 the suite at `c323fb8` reported `FAILED scripts/test_log_bloat.py`: "9 of 1124 accepted records lack consensus status, cutoff or searched_at_utc", all in the shared checkout beside repo-0's uncommitted `_experiments/rebuild-20261011/`. That red was a TRUE POSITIVE: the 9 records were the VP-5 remainder that repo-0 integrated in data `a8212d25`, and the integration skipped `market_consensus.py`. Fixed by running `market_consensus.py --leaders jack-dorsey,bill-gurley --router-exclude claude,claude_e`: 9 attempted, 9 `no_match`, 0 errors, 5 Fable matcher calls; the test then printed `13 passed, 0 failed`. The gap is in the integration step: anything that adds accepted records must run market consensus before commit. `AGENTS.md` ("Setup in a fresh clone") names this test as the one that fails while repo-0 is mid-rebuild.

**Impact:** A suite verdict that depends on data another agent is writing; so far every red was a real defect, so nothing is changed until one is not.

**Fix:** When the condition is met, split the section into a fixture proof and a named `LIVE DATA:` check, as `scripts/test_render_integrity.py` was split on 2026-10-11 (archived entry "RESOLVED 2026-10-11: the derived-number proof runs on a fixture", `docs/BACKLOG-RESOLVED.md`, Site rendering). Until then, a red from this file is reported with its text.

**Touch points:** `scripts/test_log_bloat.py:58-60`, `:135-164`, `AGENTS.md` (the fresh-clone paragraph).

---

### VI-13. The speaker-segmentation call does not correct obvious caption errors, and there is too little ground truth to measure an attempt  `[capability: frontier]`  `[priority: P2]`  `[filed: 2026-09-28]`  `[BLOCKED: at least 50 operator caption corrections across at least 10 recordings, made under the VI-9 convention]`

**Background:** Re-checked 2026-10-11: still waiting, at 15 corrections over 5 recordings of the 50 over 10 it needs. Counted with the corrections export (since VI-39, `scripts/annotations.py export corrections`) over every speaker-check answers file on this Mac: leaders 9 edits over 2 recordings, predictions 5 over 2, pundits 1 over 1. The newest edit is from 2026-09-28T05:07Z, and no later session exists in either data repo. The ledger entry, verbatim:

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
   `annotations_corrections.py` already stores (`start`, `end`, `original`,
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
Count them with `annotations.py export corrections` over each session.

Where the code stands today: `scripts/speaker_turns.py:65-66` pins the segmenter (`gpt-6-astra`, `SEGMENT_SINCE_UTC = 2026-09-28`), `scripts/speaker_segment_probe.py` scores a run, and `scripts/annotations_corrections.py:16-82` holds the overlay shape and the export that counts them.

**Impact:** The commonest fixable caption error, a misheard name, stays in every transcript the judges read, and the operator's corrections are the only repair.

**Fix:** When the threshold is met: (1) a new measured prompt beside `speaker_turns.PROMPT` that returns turns and corrections in the overlay shape; (2) the probe scores turns with and without the correction task against the 2026-09-28 baselines, and scores corrections both ways; (3) adopt only if turns do not degrade. Each a failing-first test.

*Risks and edge cases:* the three constraints in the entry above; the prompt hash moves, so adoption is a new measured segmenter.

*Why frontier not premium:* prompt design, a two-sided measurement and a schema that every published quote offset depends on.

**Touch points:** `scripts/speaker_turns.py:65-66` and `PROMPT`, `scripts/speaker_segment_probe.py`, `scripts/annotations_corrections.py:16-82`, their tests, `docs/agents/PUNDITS.md`.

---

### VI-17. Pundits grading cannot run on prepaid API credit under contract v2 without re-grading the whole pilot  `[capability: frontier]`  `[priority: P2]`  `[filed: 2026-10-18]`  `[BLOCKED: operator picks (A) or (B); CI-11 stopped after day 1, so its day-1 result is all that is coming]`

**Background:** Only the pundits daemon clone, repo-3, can finish option (B): it pushes the re-graded cells; option (A) is a decision with no work. Filed by repo-3. `quotapick run` (the router's only way to spend a credit pool) runs Fable with tools removed, on an API key, with no sandbox wrapper. Contract v2's `judge_requests.fable` names `sandbox_exec_deny_container` (`profiles/pundits.json:41-51`), `scripts/grade.py:998` refuses any other sandbox, and `judge_requests` is part of the hash that makes the contract ID. So a credit grade filed under today's contract ID would claim a sandbox it never ran in. If instead the contract is amended to name the credit harness, the contract ID changes, `grade.py` reads all 312 pundits grades (156 Fable, 156 Gemini) as `stale_cache`, and `aggregate.py` refuses to mix contracts (`scripts/aggregate.py:1429`), so the whole pilot is graded again (about $380 by the 2026-10-18 estimate). That is more than pools d and c hold, and on 2026-10-18 the owner put their spare beyond CI-11's share into the pundits predictions scale-up, so a re-grade would run on the November pools: e (expires 2026-11-10), b (2026-11-11) and a (2026-11-16). CI-11 (`data/experiments/fable-credit-drift-20261018/`) was to grade day 1 on d and day 2 on c; the operator stopped it after day 1 and cancelled day 2 (`docs/LEDGER-corpus-integrity.md:23`), with day 1 showing credit minus subscription -0.62 points, 95% CI -1.7 to +0.47, n 34, Spearman 0.939 (`results.md`).

**Impact:** The pundits full grade either stays on the subscription harness, or costs about $380 of credit and a contract change.

**Fix:** Options: (A) keep pundits grading on the subscription harness, at no cost; (B) amend the contract to name the credit harness and re-grade on the November pools. The ledger recommended waiting for CI-11 before choosing; CI-11 is stopped, so its day-1 result (credit 0.62 points under subscription, the interval straddling zero, n 34) is the evidence the choice rests on unless the operator restarts it. If B: a contract v3 in `profiles/pundits.json`, the migration path for the 312 grades, and `docs/agents/PUNDITS.md`.

*Risks and edge cases:* a contract change invalidates every pundits grade at once; the daemon must be stopped first.

*Why frontier not premium:* a contract hash, $380 of credit and the whole pundits corpus.

**Touch points:** `profiles/pundits.json:41-51`, `scripts/grade.py:576-610`, `:998`, `scripts/aggregate.py:1429`, `docs/agents/PUNDITS.md`, `docs/PUNDITS-RELEASE-PLAN.md`.

---

### VI-18. The pundits page has no evidence drawer  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-12]`  `[BLOCKED: the P7 quote audit (300 quotes, G-attribution-quotes) has run and decided the quote filter]`

**Background:** The leaders page shows, per person, each judge's reasoning and evidence quotes for every graded transcript (`scripts/build_site.py:474-600`, the drawer). The pundits page (`scripts/build_study_site.py:429`, `render`) lists each board recording with its link, venue and score since 2026-10-12, but not what the judges wrote; the data is in `results_audit.json`. Not done, deliberately: the quotes would appear credited to a named political commentator, and attribution is not yet measured. VI-21 holds 89 judge quotes credited to the subject that do not place in the transcript, and the P7 quote audit has not run. Publishing the drawer first would put possibly misattributed words beside a person's name.

**Impact:** A reader of the pundits page cannot see the evidence behind a score.

**Fix:**
1. Port `build_site.py`'s drawer into `build_study_site.py`, reading the pundits `results_audit.json`.
2. Apply the quote filter the P7 audit decides (VI-21's outcome) before any quote is rendered.
3. Tests as for the leaders drawer; `docs/agents/SITES.md` records the page size and shape.

*Risks and edge cases:* the page size limit in `docs/agents/SITES.md`; the leaders drawer is loaded from a separate audit file per person for that reason.

*Why premium not standard:* a port across two site builders plus a filter whose rule is a measurement result.

**Touch points:** `scripts/build_study_site.py:429`, `scripts/build_site.py:474-600` (read only), the pundits site tests, `docs/agents/SITES.md`.

---

### VI-19. An unsupported dimension removes the whole recording, though the plan says it should still count toward the dimensions it supports  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-10-11]`  `[BLOCKED: the pundits full grade, or a second recording with an unsupported dimension]`

**Background:** Only the pundits daemon clone, repo-3, can finish this: step 3 re-aggregates and deploys, and the item is deleted only after it; the code change in step 2 may be prepared on any clone. Found while asking why `asmongold/asmongold-tv-ks77-g` is missing from `results.json` despite four schema-valid grades. Three of its four grades mark `d1_steelmanning` `unsupported` (fable/blinded, gemini/blinded, gemini/open). `scripts/aggregate.py:1248` marks each such grade `_excluded = "unsupported_dimension"`, which removes the whole grade, and then `drop_partial_panels` (`:115`) drops the fourth, fully supported fable/open grade as an incomplete panel. The recording contributes to no dimension. `docs/PUNDITS-PLAN.md:241-246` ("Anchors and minimum evidence") says otherwise: a transcript with any unsupported dimension has no `overall`, still counts toward each dimension it supports, and ranking by overall uses only transcripts with all three supported. Re-running `aggregate.py --study pundits` on a scratch clone of data-pundits at `dced184` reproduces the committed result: 154 transcripts, the same one partial panel, and `grades_excluded_unsupported_dimension 3` (`:1696`), so the loss is counted rather than silent. The reporting half is done: `drop_partial_panels` names a cell removed earlier and why (`:164`), so the report reads "missing gemini/open (removed: unsupported_dimension)". `docs/PUNDITS-RELEASE-PLAN.md:198-201` asks the operator to choose one rule and delete the other sentence from the plan.

**Impact:** Size today: 3 grades, 1 recording. Per-dimension counting also has to decide what a partial panel means per dimension: here d1 has one supported cell out of four, while d2 and d3 have all four.

**Fix:**
1. Decide the rule (plan text or code) and delete the other sentence from `docs/PUNDITS-PLAN.md`.
2. If the plan wins: `aggregate.py` keeps a grade with an unsupported dimension for the dimensions it supports, gives the transcript no `overall`, and `drop_partial_panels` works per dimension; a fixture test with the asmongold shape, failing first.
3. Re-aggregate on a scratch clone and diff against the committed result before the daemon clone deploys.

*Risks and edge cases:* a per-dimension panel rule changes every pundits score's denominator, not just this recording's.

*Why premium not standard:* a scoring rule with a plan decision attached.

**Touch points:** `scripts/aggregate.py:115-164`, `:1248`, `:1696`, its pundits tests, `docs/PUNDITS-PLAN.md:241-246`, `docs/PUNDITS-RELEASE-PLAN.md:198-201`, `docs/agents/SCORING.md`.

---

### VI-21. 89 judge quotes credited to the subject do not place in the open transcript, and nobody has said whether a tidied quote counts as verbatim  `[capability: premium]`  `[priority: P2]`  `[filed: 2026-09-19]`  `[BLOCKED: operator decides whether a quote with fillers removed or a caption error corrected is verbatim under the rubric]`

**Background:** Of 3,290 subject quotes in the 312 live pundits grades, `annotations_text.locate` (`scripts/annotations_text.py:148`) first failed to place 137. Re-measured 2026-10-11 after three matcher fixes (`[AFFILIATION]` as a placeholder for up to five words, `_norm` at `scripts/annotations_text.py:138` stripping edge quote marks and curly apostrophes, an empty quote counted as `empty`): against `transcripts_open/`, located 3,198, not located 89, empty 3 (`suspect_quotes` at `scripts/annotations_select.py:260`; the full re-measurement is the archived entry "RE-MEASURED AND PARTLY FIXED 2026-10-11", `docs/BACKLOG-RESOLVED.md`, Verbatim Pundits). Of the 89, 84 share at least 80% of their three-word sequences with the transcript and 5 share 73 to 77%; all 5 were read in context, and every one is a judge tidying the captions, never a paraphrase (a dropped filler, a joined caption-split number, a corrected typo). 86 of the 89 are Gemini. A matcher that also skipped fillers and immediate repeats would place 29 of the 89; not done, because it makes "located" fuzzier and the remaining 60 differ in more varied ways.

**Impact:** The quote cap and the minimum-subject-quotes rule both assume quotes are real; 89 of them are either matcher misses or rubric violations, mostly Gemini's, and the pundits evidence drawer (VI-18) waits on the answer.

**Fix:**
1. The operator decides. If tidied quotes are verbatim: extend the matcher (fillers, immediate repeats) with a failing-first case in `scripts/test_annotations_page.py`, re-measure, and read the remainder one by one. If not: count them as rubric violations per judge, report the rate in `aggregate.quote_cap_report()`'s neighbourhood, and say so in `docs/agents/PUNDITS.md`.
2. Either way, the 60 that no matcher rule places are read one by one and classified.

*Risks and edge cases:* a fuzzier matcher hides real paraphrase; a stricter rubric penalises Gemini 86 to 3.

*Why premium not standard:* a rubric interpretation with a per-judge consequence.

**Touch points:** `scripts/annotations_text.py:138-192`, `scripts/test_annotations_page.py`, `scripts/aggregate.py` (the quote report), `docs/agents/PUNDITS.md`.

---

### VI-22. `grade.py --regrade-invalid` exists for leaders and is off, so 35 malformed leaders records stay as they are  `[capability: fast]`  `[priority: P2]`  `[filed: 2026-10-11]`  `[BLOCKED: operator decides to turn it on; spends about 35 Fable calls and moves the published board]`

**Background:** The manual pass is the leaders daemon clone's, repo-0; the loop-flag route is a code change any clone can make. Counted 2026-10-11 in the shared leaders data: 35 records failed validation while still carrying an attempt at scores, 26 with `dimensions` and 9 in a judge-invented shape with `overall`; six more failed as refusals or non-answers and stay put by the refusal rule in `docs/agents/JUDGES.md`. `scripts/grade.py:446-473` implements `--regrade-invalid` as an opt-in: a malformed record is moved under `grades/_obsolete/` byte for byte and graded again. `scripts/grade_loop.sh:205` and `:218` do not pass the flag, and `scripts/test_leaders_regrade_invalid.py:150` pins that they do not. It is opt-in because default-on would make repo-0's daemon spend about 35 calls and move the published board on its next code pull. The archived entry "LEADERS HALF FIXED 2026-10-11 as an opt-in" (`docs/BACKLOG-RESOLVED.md`, Verbatim Pundits) holds the count and the proof.

**Impact:** 35 leaders cells that could hold a score hold a malformed record, and the board is computed without them.

**Fix:** When the operator says so: one manual pass from repo-0, `grade.py ... --modes blinded --regrade-invalid`, then aggregate and deploy; or add the flag to the loop's grade calls at `grade_loop.sh:205` and `:218` and change the pin at `test_leaders_regrade_invalid.py:150` in the same commit. Record the before-and-after board as a `CI-n` row in `docs/LEDGER-corpus-integrity.md`, the ledger that holds the leaders grade-validity items.

**Touch points:** `scripts/grade_loop.sh:205`, `:218`, `scripts/test_leaders_regrade_invalid.py:147-150`, `scripts/grade.py:446-473` (read only), `docs/LEDGER-corpus-integrity.md`.

---

### VI-41. The pundits predictions pilot's `conversations-with-tyler-cusdy0` candidate has no verification: Gemini returned an empty answer on every pass that finished  `[capability: fast]`  `[priority: P3]`  `[filed: 2026-10-19]`  `[BLOCKED: the operator picks option (a), (b) or (c)]`

**Background:** Only the pundits daemon clone, repo-3, can finish any option: each one changes the pilot's README or record, a pundits data path, which `data_sync.py push` refuses from any other clone. VI-16 verified again the three recordings whose Gemini verify failed in the pilot's scale-up (pundits data `2b529bc`, `experiments/predictions-pilot-20261018/README.md`, section "Re-verify, 2026-10-19"). `brett-cooper-fxe9zz` and `jordan-b-peterson-rkt9up` are now verified. `tyler-cowen/conversations-with-tyler-cusdy0` failed both passes on 2026-10-19. On 2026-10-18 it failed two completed passes, and three more runs that built its prompt stopped before an answer. Each 2026-10-19 pass made 3 Gemini calls and each call ended in `empty_response`; the last call's denied tool was `RunCommand` in pass 1 and `ReadUrlContent` in pass 2. Its one candidate is an AI-capability prediction with target date 2026-11-05, not political content. The pilot verifies with Gemini only because Astra declines political content (`docs/agents/PUNDITS.md:183` "because Astra refuses political content"). Astra's served model cannot be confirmed: the record always says `served_model_verified: false` for it (`scripts/predictions_lib.py:1531` "Astra's served_model is an echo of the request"). Carries from VI-16 (deleted): the verify of this recording; the evidence goes in that README section. The options:
(a) Leave it unverified. The README records it, and the scale-up's tally reads 98 verified and 1 verify failed. Cost: the candidate never counts toward the yield.
(b) Verify this one candidate with Astra, a different family from the Fable extractor, and name the exception in the README. Cost: Codex quota for one call; one record in a Gemini-verified pilot that another verifier judged; and the only verification in the pilot whose served model cannot be confirmed.
(c) More Gemini passes. Cost: Gemini quota, for a chance that has been zero on every pass that finished.
Recommendation: (a). The pilot is an experiment, the recording is one of the scale-up's 99 with candidates, and (b) mixes verifiers, with an unconfirmed model, for at most one accepted prediction.

**Impact:** one of the scale-up's 99 recordings with candidates has no verdict, so its yield is measured over 98.

**Fix:** (a): change the README's sentence "BACKLOG.md VI-41 of tonygwu/verbatim-index holds the options" to name the decision, push it with `data_sync.py push --data data-pundits --daemon`, change the VI-41 mention in `docs/agents/PUNDITS.md` the same way, and delete this item. (b) or (c): from repo-3, write the one line `data-pundits/transcripts_open/tyler-cowen/conversations-with-tyler-cusdy0.json` to `_driver/verify_vi41.txt` in the pilot folder, and run `.venv/bin/python scripts/extract_predictions.py --stage verify --verifier astra` (or `gemini`, one pass only) `--transcripts data-pundits/transcripts_open --roster data-pundits/roster/final.json --list <that file> --out data-pundits/experiments/predictions-pilot-20261018 >> <pilot folder>/verify_vi41.log 2>&1`. For Gemini, check that the record says `served_model_verified: true`; for Astra, check that `verification.harness` is `astra` and `requested_model` is the model asked for, and write in the README that the served model is not verified. Add the result to the README's re-verify section and to the VI-41 mention in `docs/agents/PUNDITS.md`, commit every file the run wrote by name, and push with `data_sync.py push --data data-pundits --daemon`.

**Touch points:** for (b) or (c), in `data-pundits/experiments/predictions-pilot-20261018/`: `tyler-cowen/conversations-with-tyler-cusdy0.jsonl` and `.meta.json`, `README.md`, `_driver/verify_vi41.txt`, `verify_vi41.log`, and the run's new files under `_runs/`, `_inputs/verify/tyler-cowen/`, `_raw/verify/` and, for Astra, `_raw/responses/tyler-cowen/`; for (a), `README.md` only; for every option, the sentence in `docs/agents/PUNDITS.md` that names VI-41.

---
