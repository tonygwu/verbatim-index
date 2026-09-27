# P4 status: what is ready, what is parked, and one hazard P3 created

P1, P2 and P3 are done, discovery included. P4 is the phase that fetches the seven's
recordings, extracts and verifies their predictions, and publishes. Most of it
cannot run here, and this records exactly why, what the commands are, and one new
hazard that the roster change introduced.

## What P4 needs, and what it costs

| stage | spends model quota | deploys | can run now |
|---|---|---|---|
| discovery (`discover_sources.py --only`) | no | no | **DONE 2026-09-18**, see `docs/MEMBERSHIP-P3-DISCOVERY.md` |
| fetch (`fetch_transcripts.py`) | no | no | no, same block |
| `extract_predictions.py` | **yes** | no | no |
| verification | **yes** | no | no |
| `market_consensus.py` | **yes**, see correction | no | no |
| `aggregate_predictions.py` | no | no | yes |
| `score_predictions.py --trend` | no | no | yes |
| `build_predictions_site.py` | no | no | yes |
| `deploy_predictions.sh` | no | **yes** | no |

### Correction to the plan: `market_consensus.py` is not quota-free

The plan states it is "public-API only, no model calls". That is wrong as
written. `scripts/market_consensus.py:53` imports `agy_profiles` from `grade`,
and `:605` takes `--matcher {auto,fable,astra,gemini}` with `auto` as the
default, alongside `--fable-bin`, `--agy-bin` and `--astra-model`. The market
lookups may well be public-API, but the MATCHER is a model and the default is on.
Treat this stage as spending until somebody measures a run with the matcher
pinned off.

### Discovery HAS RUN. Fetching is what is still blocked

Discovery completed on 2026-09-18: 98 candidates for the seven, 14 each, the
existing 50 byte-identical, and all 98 screened before any fetch. Full record in
`docs/MEMBERSHIP-P3-DISCOVERY.md`, including three `tom-lee` candidates that are
the One Medical physician rather than Fundstrat's Thomas J. Lee.

It ran because the earlier reason for parking it was wrong. Discovery makes no
caption requests at all: `caption_probe()` is defined in `discover_sources.py`
and never called, and one `ytsearch` probe returned results normally. The block is
per-endpoint. The real problem, found while checking, was that leaders discovery
had NO pacing, because `9925c0e` fixed `discover_pundits.py` and left this path
at eight unpaced workers. That is fixed and the run used three workers at 1.5s.

**FETCHING is still blocked.** `repo-3/data-pundits/logs/NEEDS_IP_ROTATION`
exists and that loop's log reads:

```
[2026-09-18T07:20:57Z]   #  BLOCKED on IP 187.14.233.80
[2026-09-18T07:20:57Z]   #  ROTATE THE VPN TO A NEW EXIT. The loop re-probes every 60s
```

Fetching is exactly the caption endpoint that is blocked, so it must wait for the
rotation. repo-3's loop resumes by itself the moment a new exit works.

**If discovery is ever re-run, `--only` is mandatory.** Without it the other 50
leaders' source lists are replaced by that run alone. `discover_sources.py` now
also refuses a run that would drop anyone the file already holds, and
`scripts/test_discovery_only_merge.py` proves both.

## THE HAZARD P3 CREATED, which is new and is not in the plan

`aggregate_predictions.py:147` unions roster slugs with any slug that has
records. The seven are now on the roster, so a refresh puts them in the
predictions index with nothing in them. MEASURED, written to a scratch path so
production was not touched:

```
live data/predictions/index.json   50 leaders
a fresh aggregate_predictions run  57 leaders
the seven, each:  on_roster True, accepted 0, transcripts_with_accepted 0
```

And the page built from that index:

```
without --scores   "Forward-looking claims that 57 technology leaders ..."   57 rows
with    --scores   "Forward-looking claims that 45 technology leaders ..."   45 rows
the live published page today:                    45 technology leaders
```

**Today's production is safe**, because `data/predictions/scores.json` exists and
`deploy_predictions.sh` passes it, so the past-due floor filters the seven out and
the page renders 45. The hazard is conditional: `build_predictions_site.py` only
filters rows when scores are supplied (`person_rows`, the
`past_due < MIN_PAST_DUE_TO_LIST` branch), and `scores.json` is UNTRACKED. A clone
without it, or a deploy after that file is lost, publishes a masthead claiming 57
people while seven of them contribute nothing.

**Deliberately NOT fixed here.** The obvious fix, skipping any row with zero
accepted predictions, is not neutral: five leaders already on the board sit at
zero accepted (`fei-fei-li`, `ilya-sutskever`, `jack-dorsey`, `sergey-brin`,
`tobi-lutke`, per `docs/PREDICTION-SOURCING-2026-09-15.md`), and hiding them
changes what the board says about coverage. That is a publication decision, not a
bug fix, and the deploy rail was not granted for this run.

**The condition that brings it back:** before any predictions deploy, either
confirm `scores.json` is present under the production checkout, or decide whether
a zero-record person should be a row at all.

## What was run, and what it proved

Nothing under `data/predictions/` was modified. Both runs wrote to a scratch
directory.

```
aggregate_predictions.py --out <scratch>
  files 843  records 2018  accepted 699  rejected_by_verifier 1303  pending 16
  leaders 57  consensus {'failed': 3, 'no_match': 653, 'unavailable': 43}

build_predictions_site.py --index <scratch> --scores data/predictions/scores.json
  scores: 189 of 377 past due scored, 28 people ranked, 349 outcomes attached
  45 people, 699 accepted, 1303 rejected
```

So the pipeline is healthy against the 57-name roster and produces the same 45-row
board it produces today.

## The order P4 must run in, once the rails allow it

Serialised, repo-0 only, from the plan's P4 revision:

1. ~~discovery~~ DONE 2026-09-18, and the candidates are already screened
2. **REBUILD THE FETCH MANIFEST FIRST.** The seven's 98 sources are in
   `discovered.json` and NOT in `data/sources/all.jsonl`, which is what
   `fetch_transcripts.py --manifest` reads. Checked 2026-09-18: the manifest
   holds 801 rows across 50 slugs and 0 rows for any of the seven, so a fetch
   today would silently fetch nothing for them.

   `sources_to_manifest.py` writes the manifest WHOLESALE from discovered.json
   (`open(args.manifest, "w")`), unlike the aliases beside it, which merge. That
   is the behaviour `coverage_table.py` already warns about: "rebuilding
   data/sources/all.jsonl from discovered.json drops candidates already
   fetched". It costs nothing real, because those transcripts and their grades
   are already on disk and valid, but the IDENT column will move for the 17
   leaders currently over 100% on FET%.

   Not done here, because the manifest is only needed for fetching and fetching
   is blocked. Running it now would change production data for no benefit.

3. fetch into `data/transcripts_web/<slug>/`, **never** `data/transcripts/`; if
   web transcripts enter the graded shelf, `normalize` derives them, `grade`
   scores them, `calibrate` pools them and all 50 leaders' scores move
4. `identity_screen.py` over the new transcripts BEFORE extraction, since
   extraction is the first stage that spends
5. `extract_predictions.py --leaders <the seven>`, `--force` forbidden
6. verification, then `market_consensus.py --leaders <the seven>`
7. `aggregate_predictions.py`
8. `score_predictions.py --trend` — **`--trend` is not optional**: omitting it
   scores 114 instead of 117 and drops Aaron Levie and Dara Khosrowshahi off the
   board, which reads as the supplemental corpus deleting two unrelated leaders
9. build, then `deploy_predictions.sh --production-data ../data --data-revision <FULL SHA>`

Step 4 is an addition to the plan. The screen did not exist when the plan was
written, and running it before step 5 is what makes the seven's identity problem
cheap instead of judge-priced.

## HANDOFF 2026-09-25: steps 5 and 6a are done; next is the verifier-mix diagnostic

Pinned: public `main` at the commit that adds this section, data `main` at
`7166d6c5`, both pushed. Nothing is running.

**Done.** Extraction and verification ran for all seven, committed in data as
`7166d6c5`: 82 transcripts, 260 records, 163 accepted, 0 failures in either
stage. Per-person counts are in that commit message.

**The finding that sets the next action.** Acceptance depends on which model
verifies, and the seven were verified by a different model from the rest:

```
existing 50   gemini 1857 verified   620 accepted  33.4%
              fable   145 verified    79 accepted  54.5%
the seven     fable   246 verified   156 accepted  63.4%
              astra    14 verified     7 accepted  50.0%
```

The router excludes the extractor's harness; extraction ran on astra, and fable
won on measured quota because Antigravity reports no usage. So the seven's rate
is ordinary for fable, not evidence they predict better. Predictions has no
calibration stage to absorb this.

**Next action.** Add a by-verifier-harness acceptance diagnostic to
`scripts/aggregate_predictions.py`, beside `acceptance_by_contract_pair()`
(which groups reviewed records by extraction and verification contract ids
only, so it cannot see this). Test first: a fixture with two verifier harnesses
at different acceptance rates must fail before the change and pass after, and
the harness must be read from `verification.harness` on each record, raising if
a verified record lacks it rather than bucketing it as unknown. Re-verifying on
one harness was rejected: it needs `--force`, which the plan forbids, and costs
about 190 calls to change a number whose direction is already known.

**Whether the page shows it is a separate operator decision.** Diagnostics only
is free and changes nothing published. Showing it on the page makes the
confound visible to readers but changes the rendered predictions page.

**After that, P4 continues:** `market_consensus.py --leaders <the seven>` (spends
quota: its matcher is a model), `aggregate_predictions.py`,
`score_predictions.py --trend`, build, deploy. The deploy is still gated on two
open decisions: whether a zero-record person is a row (now five of the existing
50, none of the seven), and the wording of the retired investor rule.

**Loose ends.** `predictions/_inputs/` (25 MB) and `_raw/responses/` are
untracked with no ignore rule, the shape `_markets/` had before it was swept
into a commit. `.agents/` in the public repo is not mine.

Verify this state:

```
git -C data log --oneline -1          # 7166d6c5 The seven investors' predictions...
git -C data status --short --branch   # in sync; only _inputs/ and _raw/responses/ untracked
ps -Ao args= | grep -E 'extract_predictions|market_consensus' | grep -v grep   # nothing
```

### Update 2026-09-25: diagnostic done (0f7fad9)

`acceptance_by_harness_pair()` in `scripts/aggregate_predictions.py` now writes
`verifier_acceptance_by_harness_pair` into each leader and the corpus in
`index.json`. It is diagnostics only; the predictions page does not render it.
Measured on the corpus in memory, before any index rebuild:

```
existing 50  astra -> fable    54.5%  (79/145)
             astra -> gemini   32.9%  (584/1778)
             fable -> gemini   45.6%  (36/79)
the seven    astra -> fable    63.4%  (156/246)
             fable -> astra    50.0%  (7/14)
```

On the same harness pair the gap is 8.9 points, not the 28.5 the pooled rates
suggested. `test_log_bloat.py` fails with "163 of 862 accepted records lack
consensus status": those are the seven's accepted records, and step 2 clears it.

Next action: `market_consensus.py --leaders <the seven>` (spends quota).

## HANDOFF 2026-09-27: everything but the deploy is done

P4 now stops at one command, the real deploy, which waits for the operator.
Every data step is committed and pushed in `data/`.

| step | result | commit |
|---|---|---|
| market consensus, `--leaders <the seven>`, no `--force` | attempted 163: no_match 161, unavailable 1, failed 1 (`cli_nonzero_exit`); the retry of the failed one came back unavailable. End state: no_match 161, unavailable 2, nothing failed or unsearched | data `25a50987` |
| `aggregate_predictions.py` | files 925, records 2278, accepted 862, people 57. None of the existing 50 entries changed apart from the new harness key. Freshness against disk is equal on all three checks | data `5a846d1a` |
| `score_predictions.py --trend`, same run dir, `--as-of 2026-09-16` | people 45 -> 52, ranked 28 -> 28, scored 189 -> 189. Existing people changed 0 of 45 and existing predictions 0 of 377. The seven carry 40 past-due predictions with no resolution, so all seven are unranked | data `5dc0b7ff` |
| social card | redrawn: 699 -> 862 predictions, 843 -> 925 transcripts | public `83dad2e` |
| page build, run locally | 52 rows (the live page has 45), all seven present, 200,822 bytes; headless Chromium showed 0 page errors and drawers fetched with 200 | not committed (build artifact) |
| `deploy_predictions.sh --dry-run` | exit 0, "current: index matches disk", "published nothing" | none |
| leaders board audit | a fresh `aggregate.py` plus `build_site.py`, diffed against the LIVE verbatim-index.tonygwu.com, differs only on the 2 `__RUNDATE__` lines; all 50 `audit/<slug>.json` files are byte-identical | none |

To publish, from repo-0:

```
bash scripts/deploy_predictions.sh --production-data "$(cd data && pwd -P)" --data-revision "$(git -C data rev-parse HEAD)" --dry-run
bash scripts/deploy_predictions.sh --production-data "$(cd data && pwd -P)" --data-revision "$(git -C data rev-parse HEAD)"
```

### The two open decisions no longer block the deploy

- **A person with zero records:** none of the seven has zero. Accepted counts
  run from Bill Gurley 7 to Cathie Wood 49. The page already hides anyone with
  nothing past due (`MIN_PAST_DUE_TO_LIST = 1`); today that is Fei-Fei Li and
  Ilya Sutskever.
- **Wording of the retired investor rule:** it lives only in
  `data/roster/final.json`, under `tie_break_rules` and the scoping note
  `investor_rule_scoped_2026_09_18`. Neither page renders either one, so the
  wording changes no published byte.

### Decisions still open, each with its cost

1. **Headline copy.** The page and the social title say "What 52 tech leaders
   predicted in public". Seven of the 52 are investors. Keeping it costs
   accuracy for those seven rows. Changing it to "people" or "technology leaders
   and investors" is a one-line edit to `SOCIAL_TITLE` and the masthead in
   `build_predictions_site.py`. Recommendation: change it before the deploy,
   because the headline is the first thing a reader sees.
2. **Scoring the seven.** They show counts, not scores. Scoring them needs
   resolutions and priors for their 40 past-due predictions, which is the
   phase-2 pipeline and spends quota. Without it they stay unranked, which is
   honest but gives investors no Score column.
3. **The deploy itself.** The operator runs it, or tells the agent to run it.

### Found tonight, and what happened to it

- **FIXED in public `a31dc8e`, data `12d3df0a`.** The drawer said "extraction
  ran on 22 of 15 of their transcripts" for more than 20 of the 50, and the
  live page still says so until the next deploy. `transcripts_on_disk` counted
  `transcripts_open` only, and the numerator counted withdrawn transcripts'
  meta files. Both roots are counted now, and withdrawn ones are reported as
  `transcripts_withdrawn_with_meta` (alexandr-wang 2, andy-jassy 4,
  arvind-krishna 1, none with an accepted prediction). Rendered: Sam Altman
  22 of 22, Alexandr Wang 11 of 11, Cathie Wood 13 of 13.
- **NOT DONE: 9 Demis Hassabis web transcripts were never extracted.** The fix
  made them visible: his drawer now reads 13 of 22. They arrived with the
  round-2 supplemental corpus (data `9f79b419`) and have no meta file. Extracting
  them spends quota, and he is on the leaders board, outside P4, so the operator
  decides. They are `web-achievement-org-e530f53c`, `web-cbsnews-com-220f10f0`,
  `web-possible-fm-f38d9586`, `web-singjupost-com-919fc443`,
  `web-soci-org-53331963`, `web-theguardian-com-7cc1a21c`,
  `web-theverge-com-6ae7ff47`, `web-wired-com-e067a388` and
  `web-yahoo-com-9f29dd43`.
- The deploy log prints "about to publish 57 people" while the page shows 52.
  The log counts the index, and the page counts people with something past due.
  Left as it is: the log is not published.
