# Pundits study, P0: the leaders baseline

This fixes what "the leaderboard did not change" means before any refactor for
the pundits study begins. Every later phase compares against it. The plan
itself is in the approved pundits plan (revision 2); this file is only its P0
record.

## What is pinned

| Item | Value |
|---|---|
| Code commit | `529baee4b60f8a0ca28062cb6f1b9afcd97065ee` |
| Data revision | `e2ea42bc1c8dfb74467a74598501537b3e10a52b`, on branch `codex/repo-3-data-2026-09-14` of `tonygwu/verbatim-index-data`, pushed and clean |
| Python | 3.12.4 |
| Hash seed | `PYTHONHASHSEED=0` |
| Dependencies | `certifi==2026.7.22`, `charset-normalizer==3.5.1`, `defusedxml==0.7.1`, `idna==3.19`, `llm-quota-router @ git+https://github.com/tonygwu/llm-quota-router@ce138e1467127d07fa5974d64eaa337b0e913f1b`, `requests==2.34.2`, `urllib3==2.7.0`, `youtube-transcript-api==1.2.4` |

## How it was produced

`scripts/leaders_baseline.py` copies the frozen data into a fresh directory and
runs the quota-free stages with the same arguments `grade_loop.sh` uses: QA,
normalize in both modes with `--grades`, aggregate, build_site and
coverage_table. It then renders every judge prompt with `build_judge_prompt`
and computes the leaderboard `fingerprint()`. No stage calls a judge. The data
copy is named `data-copy`, not `data`, because `production_path()` falls back to
`<code parent>/data` and would otherwise treat the copy as the live checkout.

The baseline ran twice, from the same commit on the same snapshot, 2026-09-14
UTC. Both runs exited 0 at every stage, rendered 1,328 prompts over 664
transcripts, and changed 0 grade files.

## Result: one field differs between two identical runs

| Output | Run 1 vs run 2 |
|---|---|
| 1,328 rendered judge prompts and `grading_contract()` | identical |
| `results.json`, `results_audit.json`, `logs/calibration.json` | identical |
| `site/index.html` | identical |
| `logs/normalize_blinded.json`, `logs/normalize_open.json` | identical |
| `logs/transcript_qa.json` | identical apart from `summary.generated_at_utc` |
| `coverage_table.py` output, leaderboard `fingerprint()` | identical |
| `transcripts_blind/`, `transcripts_open/` | 664 of 664 files differ in each, in one field only |

**The allowed-difference list is two fields:**
`normalization.normalized_at_utc` in each normalized transcript. It is the wall
clock at the moment normalize ran (`normalize_transcripts.py:659`), for example
`2026-09-14T05:28:03Z` against `2026-09-14T05:29:20Z` for the same file. No
prompt reads it, which is why all 1,328 prompts still match.

The byte-identity test in P4 may mask that field by name and nothing else. Any
other difference against this baseline fails it.

## Re-running it

```
python scripts/leaders_baseline.py --code <export of 529baee> \
    --snapshot <copy of the data revision above, without .git> \
    --run-dir <new empty directory> --python .venv/bin/python
```

It refuses an existing `--run-dir`, so a run always starts from a fresh copy.
The manifest it writes holds hashes of private data, so it stays in the run
directory and is never committed here.

## Decisions recorded for later phases

These wait for the gate named against each, as the plan says:

1. At P1: which clone owns pundits production. repo-3 is proposed.
2. At P3: what happens to a judge arm that cannot deny tools or verify its
   served model.
3. At P7: who labels the attribution windows and quote samples.
