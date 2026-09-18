# P4 status: what is ready, what is parked, and one hazard P3 created

P1, P2 and most of P3 are done. P4 is the phase that fetches the seven's
recordings, extracts and verifies their predictions, and publishes. Most of it
cannot run here, and this records exactly why, what the commands are, and one new
hazard that the roster change introduced.

## What P4 needs, and what it costs

| stage | spends model quota | deploys | can run now |
|---|---|---|---|
| discovery (`discover_sources.py --only`) | no | no | **no**, network blocked, see below |
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

### Discovery is blocked on something current, not on caution

`repo-3/data-pundits/logs/NEEDS_IP_ROTATION` exists, and that loop's log reads:

```
[2026-09-18T07:20:57Z]   #  BLOCKED on IP 187.14.233.80
[2026-09-18T07:20:57Z]   #  ROTATE THE VPN TO A NEW EXIT. The loop re-probes every 60s
```

repo-3's pundits fetcher is IP-blocked by YouTube on this machine right now and
is polling for a new exit. A discovery run from the same address would fail and
could deepen a block another clone's production is actively recovering from.

**The command, when the VPN has rotated and repo-3 has resumed:**

```
.venv/bin/python scripts/discover_sources.py \
  --roster data/roster/final.json \
  --out data/sources/discovered.json \
  --only cathie-wood,marc-andreessen,chamath-palihapitiya,david-sacks,bill-gurley,vinod-khosla,tom-lee
```

**`--only` is mandatory and is the whole guard.** Without it the other 50
leaders' source lists are deleted, because `discover_sources.py` builds its
`existing` map only when the flag is present. That is now asserted by
`scripts/test_discovery_only_merge.py`, which proves all four arms including the
destructive one, with `discover()` stubbed so it makes no request.

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

1. discovery, `--only` pinned, after the VPN rotates
2. fetch into `data/transcripts_web/<slug>/`, **never** `data/transcripts/`; if
   web transcripts enter the graded shelf, `normalize` derives them, `grade`
   scores them, `calibrate` pools them and all 50 leaders' scores move
3. `identity_screen.py` over the new transcripts BEFORE extraction, since
   extraction is the first stage that spends
4. `extract_predictions.py --leaders <the seven>`, `--force` forbidden
5. verification, then `market_consensus.py --leaders <the seven>`
6. `aggregate_predictions.py`
7. `score_predictions.py --trend` — **`--trend` is not optional**: omitting it
   scores 114 instead of 117 and drops Aaron Levie and Dara Khosrowshahi off the
   board, which reads as the supplemental corpus deleting two unrelated leaders
8. build, then `deploy_predictions.sh --production-data ../data --data-revision <FULL SHA>`

Step 3 is an addition to the plan. The screen did not exist when the plan was
written, and running it before step 4 is what makes the seven's identity problem
cheap instead of judge-priced.
