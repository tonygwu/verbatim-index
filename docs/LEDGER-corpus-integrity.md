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
| CI-6 | Withdraw 45 recordings and re-grade 9, per `docs/withdrawals-2026-09-10.json` | **blocked-on-repo-0 running** `scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json --apply`. C.C. Wei's 10 already retired and pruned; the other 35 retirements and 9 re-grades not yet applied. | `.venv/bin/python scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json \| head -1` (2026-09-11T02:54Z: `done 44, skipped 10, failed 0`, i.e. not applied) |
| CI-7 | Re-grade records for CI-1 and CI-4 into the private data repo | **blocked-on-repo-0 committing** `~/Code/misc/verbatim-index/experiments-inbox/2026-09-10-year-deloop/` under `data/experiments/` | `ls ~/Code/misc/verbatim-index/experiments-inbox/2026-09-10-year-deloop/` shows 7 entries |
| CI-8 | repo-0 pull of the year fix and the Gemini identity guard | **blocked-on-repo-0 pulling**. repo-0 is at f5971da; the fix is 476d973, the ledger f83bcb6 and later. Until then new grades still read "Approximate year: 2024" | `git -C ../repo-0 log --oneline -1` |
| CI-9 | Gemini: two profiles serve one account (shared Keychain item) | **attempted**: warning shipped in `grade.py`; account separation is D-1. Since 2026-09-10T09:00Z: 115 Gemini grades, all gptwufamily@gmail.com | `python3 -c` tally of `telemetry.profile_identity` over `data/grades/gemini` |
| CI-10 | C.C. Wei source rediscovery, company name required in title or description | **blocked-on-a new discovery run** in repo-0; he is at n=2 and off the board under CI-5 | `ls data/transcripts/cc-wei/ \| grep -vc superseded` (2 real sources plus 2 unscreened) |
| CI-11 | Fable re-run drift, +2.44 against 1-4 day old grades, sd 3.24 | **not started**: recorded in AGENTS.md Known limits; needs its own experiment, same transcripts and account a day apart | `docs/CORPUS-INTEGRITY-FOLLOWUP.md` section 1, re-run noise table |
| CI-12 | Two wrong-person tools now exist: `wrong_person_screen.py` (repo-3) and `identity_audit.py` (09e23ef, another clone) | **blocked-on-operator choosing** one to keep; both pass their tests, neither is wired into the loop | `ls scripts/wrong_person_screen.py scripts/identity_audit.py` |
| CI-13 | HANDOFF.md still says `agy` = tonygwu@gmail.com | **not started**: it is repo-0's file; the correct statement is in AGENTS.md under "Two profiles do not mean two accounts" | `grep -n "tonygwu@gmail.com" HANDOFF.md` |

## Decisions waiting

**D-1. Which Gemini account setup?** Undecided as of 2026-09-11T02:54Z.
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
- 2026-09-10: withdraw all 45, not only the 31 on the board. Manifest written.
- 2026-09-10: stage the re-grade records outside the public repo (CI-7).
- 2026-09-10: leaderboard floor is 5, tied to the high-confidence band (fork).

## Poll log

- 2026-09-11T02:54Z: state above verified; delta since 2026-09-10T09:40Z: repo-0 pulled to f5971da, C.C. Wei's derived copies pruned, 115 more Gemini grades all on one account, nothing else moved.
