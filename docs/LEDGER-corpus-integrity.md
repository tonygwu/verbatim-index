# Ledger: corpus-integrity workstream

Standing state for the four-defect follow-up in `docs/CORPUS-INTEGRITY-FOLLOWUP.md`.
Updated when an item changes state, not at poll time. Every open item carries the
command that verifies it. Last verified 2026-09-11T02:54Z from repo-3.

Status words: `succeeded`, `attempted` (with what ran), `failed`, `blocked-on-<artifact>`.

## Items

| ID | What it is, in one line | Status | Verify |
|---|---|---|---|
| CI-1 | Year constant: judges were told 2024 for every recording | **succeeded**, fix pushed (476d973), effect measured -0.73/grade, no re-grade | `.venv/bin/python scripts/test_declared_year.py` |
| CI-2 | Wrong-person recordings on the board | **succeeded** as analysis, 31 found; withdrawal is CI-6 | `.venv/bin/python scripts/wrong_person_screen.py --sample 0 \| head -2` |
| CI-3 | Share cutoff averaged a zero away | **succeeded**, any-judge-zero rule pushed (60ec078), live in repo-0 | `git -C ../repo-0 log --oneline -1` is at or after 60ec078 |
| CI-4 | Caption looping, 10 transcripts | **succeeded**, collapse pushed (b348d0f), live in repo-0; re-grade of the 9 is inside CI-6 | `.venv/bin/python scripts/test_loop_collapse.py` |
| CI-5 | Leaderboard floor of 5 transcripts | **succeeded** (fork, 170f908), live in repo-0 | `.venv/bin/python scripts/test_rank_floor.py` |
| CI-6 | Withdraw the recordings in `docs/withdrawals-2026-09-10.json` | **succeeded for the corpus, re-checked 2026-10-11 by repo-0; 4 leftover files remain.** The dry run still prints `attempted 45, done 4, skipped 41, failed 0`, but each of the 4 was retired on 2026-09-11: its `transcripts/` copy is `.superseded` and its grades are `.orphaned`, and none has a `transcripts_open` or `transcripts_blind` copy, so none is graded or on the board. What the dry run finds is a second Happyscribe copy, `transcripts_hs/<slug>/<id>.json` (tracked), fetched at 07:18Z on 2026-09-11 beside the `.json.superseded` fetched at 05:49Z the same day, with the same word count. It is a one-day double fetch, not an ongoing spend. `--apply` would rename onto the existing `.superseded` name, so it was NOT run. Removing the 4 tracked leftovers (`git rm`) is the clean fix and is left for whoever owns `transcripts_hs/`. The 9 re-grade entries were REMOVED 2026-09-11, verified already satisfied | `.venv/bin/python scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json \| head -1` (2026-09-11T06:05Z: `attempted 45, done 4, skipped 41`) |
| CI-7 | Re-grade records for CI-1 and CI-4 into the private data repo | **succeeded, re-checked 2026-10-11 by repo-0** (the row said blocked since 2026-09-10): `data/experiments/2026-09-10-year-deloop/` is committed on data main, 312 tracked files (`git -C data ls-files experiments \| grep -c deloop`). The inbox copy under `experiments-inbox/` still exists and is now redundant | `ls ~/Code/misc/verbatim-index/experiments-inbox/2026-09-10-year-deloop/` shows 7 entries |
| CI-8 | repo-0 pull of the year fix and the Gemini identity guard | **succeeded, re-checked 2026-10-11 by repo-0**: `git merge-base --is-ancestor 476d973 HEAD` holds in repo-0, so the year fix and the Gemini identity guard are in the code every loop runs | `git -C ../repo-0 log --oneline -1` |
| CI-9 | Gemini: two profiles serve one account (shared Keychain item) | **succeeded 2026-09-11**: the two accounts are now separate, see CI-14. The warning in `grade.py` stays as the guard. Since 2026-09-10T09:00Z: 115 Gemini grades, all gptwufamily@gmail.com | `python3 -c` tally of `telemetry.profile_identity` over `data/grades/gemini` |
| CI-10 | C.C. Wei source rediscovery, company name required in title or description | **moot, re-checked 2026-10-11 by repo-0**: C.C. Wei is not in `data/roster/final.json`, and `data/transcripts/cc-wei/` holds 0 live files (every one `.superseded`), so there is nobody to rediscover sources for. Reopen only if he returns to the roster | `ls data/transcripts/cc-wei/ \| grep -vc superseded` (2 real sources plus 2 unscreened) |
| CI-11 | Fable re-run drift, +2.44 against 1-4 day old grades, sd 3.24 | **not started**: recorded in AGENTS.md Known limits; needs its own experiment, same transcripts and account a day apart | `docs/CORPUS-INTEGRITY-FOLLOWUP.md` section 1, re-run noise table |
| CI-12 | Two wrong-person tools now exist: `wrong_person_screen.py` (repo-3) and `identity_audit.py` (09e23ef, another clone) | **settled 2026-09-10 in b836e56, row updated 2026-10-11:** `identity_audit.py` was deleted and `wrong_person_screen.py` kept (AGENTS.md, docs/agents/MAP.md). Earlier status: blocked-on-operator choosing one to keep; both pass their tests, neither is wired into the loop | `ls scripts/wrong_person_screen.py scripts/identity_audit.py` |
| CI-14 | Second Gemini account via the `tonyagents` macOS user | **succeeded, verified end to end 2026-09-11**: one call through each profile returned SUCCESS and named a different account, and `grade.py --single` graded a transcript through `user:tonyagents`. Redundant HOME profiles are now skipped. **blocked-on-repo-0 setting** `GEMINI_USERS=tonyagents` on `grade_loop.sh` and restarting it. Depends on the `tonyagents` session staying logged in. | `GEMINI_USERS=tonyagents .venv/bin/python -c "…agy_profiles()"` lists exactly `/Users/tonygwu` and `user:tonyagents` |
| CI-13 | HANDOFF.md still says `agy` = tonygwu@gmail.com | **succeeded, re-checked 2026-10-11 by repo-0**: `grep -n "tonygwu@gmail.com" HANDOFF.md` prints nothing; the wrong statement is gone | `grep -n "tonygwu@gmail.com" HANDOFF.md` |
| CI-15 | Two duplicate-sweep findings carried over from predictions ledger VP-13 (2026-10-11) | **open, documentation and design**: (1) data commit `2003509e` is titled for `lisa-su/times-now-world-v2pddh` alone but also rewrote `logs/dedupe_sweep.log` and `logs/dedupe.json`, so the reasons for the other retirements in that commit live only in the sweep log; (2) the sweep is not order-independent: a recording can be the KEPT side of a strong pair and later be retired against a third copy, e.g. `game-time-fvqitw` kept over `lex-fridman--l3gna` at containment 0.959 and `zenvora-productions-v5tqvz` kept over `lex-fridman-13czpw` at 0.833, three such recordings later retired against a HappyScribe copy at 0.458-0.582. Which copy survives depends on arrival order | `grep -n 'game-time-fvqitw\|zenvora-productions' data/logs/dedupe_sweep.log` |

## Decisions waiting

**D-1. Which Gemini account setup?** Decided 2026-09-11: a second macOS user, `tonyagents`, logged into Antigravity as gptwufamily@gmail.com (done by the operator, 21:49 local). Now CI-14.
- One account, one profile: log in once, rename `~/.agy-homes/gptwufamily` away, restart `grade_loop.sh`. Cost: the quota you have had all along. Gain: the identity stops flipping and the record is honest.
- A second macOS user for the second Google account, with `grade.py` running `agy` as that user. Cost: setup work and a subprocess change. Gain: real second quota.
- Do nothing. Cost: the default profile follows whichever HOME refreshed last; every grade since 09:00Z is gptwufamily regardless of profile.
- API-key mode (2026-09-11 probe): `agy` carries a `geminiAPIKeyAuth` provider reading `GEMINI_API_KEY`, and a fresh HOME never touches the Keychain, so two HOMEs on API keys would be two accounts. Not reachable headlessly: env var, two settings keys and two token-file `auth_method` values all fell through to OAuth or the Keychain; the method appears to be chosen in the interactive `/login` menu. Unknowns: whether that build offers it, whether `gemini-3.8-flash-high` is served under an API key, and the per-token Gemini API bill for ~570 calls per pass. Cost to find out: one interactive `/login` in the second HOME and one real key.
Recommendation: one account, one profile, now; the second user or the API-key route only if Gemini quota ever binds.
If undecided: nothing breaks, the corpus stays single-account, and the `gemini_identities` warning prints on every run once repo-0 pulls.

**D-2. Which wrong-person tool to keep** (CI-12). Undecided.
- `wrong_person_screen.py`: classifies every guess, flags on two dissenting judges or two zeros, review lists for one, negation-aware namesakes, feeds the withdrawal manifest, registered in AGENTS.md. 35 checks.
- `identity_audit.py`: flags when every opining judge names someone else, negation window of 60/40 characters. 17 checks.
Recommendation: keep the screen and fold the audit's negation window into its tests if it catches anything the screen misses; run whichever survives in `grade_loop.sh` after each pass and stop the render on a new flag.
If undecided: both sit unused; the next wrong-person recording scores until someone runs one by hand.

## Decided

- 2026-09-10: keep the `agy` default profile on tonygwu@gmail.com. Superseded by the finding that the Keychain item is shared; re-opened as D-1.
- 2026-09-11: D-1 decided, second macOS user `tonyagents` for gptwufamily@gmail.com (CI-14).
- 2026-09-10: withdraw all 45, not only the 31 on the board. Manifest written.
- 2026-09-10: stage the re-grade records outside the public repo (CI-7).
- 2026-09-10: leaderboard floor is 5, tied to the high-confidence band (fork).

## Poll log

- 2026-09-11T06:05Z: repo-0 is at b87b519 and its grade loop runs with `GEMINI_USERS=tonyagents`, so CI-14 is live. CI-6 is down to 4 Happyscribe retirements; its 9 re-grades were verified satisfied and removed. CI-7 still waits: `data/experiments/` does not exist.

- 2026-09-11T02:54Z: state above verified; delta since 2026-09-10T09:40Z: repo-0 pulled to f5971da, C.C. Wei's derived copies pruned, 115 more Gemini grades all on one account, nothing else moved.
