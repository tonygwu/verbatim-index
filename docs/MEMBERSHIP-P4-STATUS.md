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
