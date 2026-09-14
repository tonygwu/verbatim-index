# Study isolation trace (pundits plan, P1 checklist)

Every place the pipeline decides where data lives, who owns it, or where a
side file goes. Traced at code commit `529baee` with
`grep -n "data/"` and a second grep for path forms that do not contain that
literal (`/ "data"`, `.daemon-clone`, `grade-work`, run markers,
`.superseded`). Test files and one-off analysis scripts are listed separately
at the end.

P1 is not done until every row in the first four tables resolves by study, and
a fixture in `scripts/test_study_isolation.py` exercises it.

**How a row resolves today:**
- `literal` means the path is typed into the command line.
- `default` means an argparse default that a flag can override.
- `constant` means no flag exists.
- `cwd` means relative to the working directory.
- `repo-rel` means relative to the file location.

## 1. Ownership, production source, publication

| Where | What it decides | Resolves today | Risk if a pundits run uses it unchanged |
|---|---|---|---|
| `data_clone_workflow.py:40-41` `production_path()` | the registered live checkout | one `verbatim.productionData` config key, else `<repo parent>/data` | pundits resolves to the leaders live checkout |
| `data_clone_workflow.py:44-54` `owner_error()` | whether this clone owns production | `<repo>/data/.daemon-clone` | the leaders marker authorizes pundits jobs |
| `data_clone_workflow.py:57-70` `publication_source()` | what a deploy may read | `production_path()` plus the `.daemon-clone` marker | a pundits deploy accepts the leaders checkout |
| `data_clone_workflow.py:274-289` `fingerprint()` | the bytes bound to a render | `site == 'leaderboard'` else predictions shelves | a pundits site falls into the predictions branch |
| `data_clone_workflow.py:321-329` `guard_aggregate()` | whether aggregation may write | `production_path()`, `<repo>/data` | a pundits aggregate is guarded against the leaders owner |
| `data_clone_workflow.py:180-271` `setup()` | experiment migration | `<repo>/data` and `.data-clones/experiment` constants | must keep working unchanged for leaders |
| `daemon_guard.sh:5-23` | whether a loop may start | `cwd` `data/.daemon-clone` and `git -C data config verbatim.role` | the leaders marker starts pundits loops |
| `deploy_source.sh:20-24` | publication source and `--refresh` owner | `publication-source` and `cd data` | the pundits deploy script reads the leaders checkout |
| `withdraw_sources.py:45-51, 61-65, 88, 120` | who may retire sources, and what gets renamed | `root / "data"` constants for the marker, shelves, derived trees and grades | a pundits manifest retires leaders sources |
| `predictions_lib.py:381` `data_root()` | the predictions write guard | `REPO / "data"` | out of scope for pundits, but must not move |

## 2. Loops and markers

| Where | What it reads or writes | Resolves today |
|---|---|---|
| `grade_loop.sh` (45 `data/` references) | sweep, QA, normalize with pruning, grading, aggregate, build_site, publish | `literal`, `cwd` = repo root |
| `fetch_loop.sh` (25) | state and rotate flag, fetch, QA, normalize `--no-prune` | `literal` |
| `happyscribe_loop.sh` (15) | candidates, discovery, fetch, dedupe merge and sweep | `literal` |
| `run_pipeline.sh` (32) | the one-shot version of all stages | `literal` |
| `watch_and_run.sh` (9) | a legacy fetch driver | `literal` |
| `status.sh` (12) | coverage, fetch errors, grades, Gemini backfill | `literal` and embedded Python |
| `run_marker.sh:31` | `RUN_MARKER_DIR`, defaulting to `data/logs/running` | env var with a `cwd` default |

A pundits loop that shares `RUN_MARKER_DIR` with a leaders loop would see the
leaders fetcher as "still running". So the marker directory must come from the
study's data root, never from the shared default.

## 3. Python stages with path defaults

| Script | Defaults | Resolves today |
|---|---|---|
| `grade.py:1650, 1663` | `--out data/grades`, `--errors data/logs/grade_errors.jsonl` | `default`, `cwd` |
| `grade.py:1783` | judge workdirs under `$TMPDIR/grade-work` | constant, shared by both studies |
| `grade.py:875` | `GEMINI_SHARED_JAIL = /Users/Shared/verbatim-index-judge` | constant, shared by both studies |
| `grade.py:46-48` | `SKILL`, `RUBRIC_PATH`, `SCHEMA_PATH` | `repo-rel` constants |
| `dedupe_transcripts.py:145-159` | `--youtube data/transcripts`, `--happyscribe data/transcripts_hs`, `--grades data/grades`, `--out data/logs/dedupe.json` | `default`; happyscribe_loop.sh:111-112 calls it with NO path flags |
| `dedupe_transcripts.py:200-217, 310, 343-358` | writes and honours the `.superseded` marker | derived from the defaults above |
| `fetch_happyscribe.py:363-366` | `--roster`, `--candidates`, `--out data/transcripts_hs`, `--errors` | `default` |
| `fetch_transcripts.py:295-301` | honours `.superseded` beside `--out` | derived from `--out` |
| `normalize_transcripts.py` | every path is a flag; `--grades` enables pruning | flags; the pruning target is whatever `--grades` names |
| `qa_transcripts.py` | flags | flags |
| `aggregate.py:500-510` | required flags, then `guard_aggregate` | flags plus the section 1 guard |
| `build_site.py:1011-1016` | flags | flags |
| `build_site.py:1055` | `Path("data/transcripts")` for word counts | constant, `cwd` |
| `coverage_table.py:78-187` | 8 `Path("data/...")` constants | constant, `cwd` |
| `wrong_person_screen.py:317-320` | `REPO / "data" / grades, transcripts_open, roster` | `repo-rel` default |
| `discover_sources.py`, `sources_to_manifest.py:34` | usage text; `--report data/logs/manifest_report.json` | flags and a `default` |
| `build_blind_wordlist.py:82-88` | `ROOT / "data/roster"`, `aliases`, `transcripts_open` | constant, `repo-rel` |
| `validate_grader.py:136-138` | `--grades`, `--transcripts`, `--out` | `default` |
| `backfill_contract.py:30` | `--grades data/grades` | `default` |
| `atomicio.py` | no path; the docstring assumes one shared checkout | not applicable |

## 4. Implicit defaults that bite silently

Each of these picks a leaders path without anyone typing it:

1. `happyscribe_loop.sh:111-112` runs `dedupe_transcripts.py --merge` and
   `--sweep` with no path flags, so the dedupe argparse defaults decide the
   shelves, the grades it orphans and the report path.
2. `run_marker.sh:31` falls back to `data/logs/running` whenever
   `RUN_MARKER_DIR` is unset, which is every current caller.
3. `production_path()` falls back to `<repo parent>/data` when the config key
   is unset. The P0 baseline had to rename its data copy to avoid this.
4. `grade.py:1783` and `grade.py:875` put both studies' judge scratch space in
   one directory.
5. `build_site.py:1055` and `coverage_table.py` read `data/` relative to the
   working directory, whatever flags were passed.
6. `withdraw_sources.py` hardcodes `root / "data"` for the marker, every shelf
   and the grades it orphans.

## 5. Out of P1 scope, listed so nothing is missed

These are predictions or one-off analysis tools. The pundits study does not
run them. P1 leaves them unchanged, and the byte-identity and existing tests
cover them:
- `aggregate_predictions.py`, `build_predictions_site.py`,
  `extract_predictions.py`, `market_consensus.py`, `validate_predictions.py`,
  `eval_predictions.py`, `predictions_lib.py`
- `padding_analysis.py`, `padding_probe.py`, `retest_analysis.py`,
  `calibration_report.py`

Tests with `data/` references are also out of scope, except where a new
isolation fixture replaces them: `test_coverage_table.py`,
`test_pipeline_dedupe.py`, `test_log_bloat.py`, `test_fetch_target.py`,
`test_deploy_refresh.py`, `test_shared_data.py` and 16 more with one or two
references each.
