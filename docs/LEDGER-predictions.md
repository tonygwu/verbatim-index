# Ledger: Verbatim Predictions workstream

Standing state for the predictions product in `docs/PREDICTIONS.md`. Updated
when an item changes state, not at poll time. Every open item carries the
command that verifies it. Last verified 2026-09-13 from repo-0.
Last poll answered: 2026-09-13. VD-1 decided 2026-09-11 (keep strict);
VD-3 decided 2026-09-13 (no market-surprise column, 0 exact matches of 475).

Status words: `succeeded`, `attempted` (with what ran), `failed`, `blocked-on-<artifact>`.

## Items

| ID | What it is, in one line | Status | Verify |
|---|---|---|---|
| VP-1 | Pipeline code: extract, verify, market consensus, validate, aggregate, page, deploy, and eight test suites | **succeeded**, 21 commits pushed, merged with origin at 037e49f, 28 suites green | `git status --short --branch`; `for t in shared lib schema driver markets eval aggregate site; do .venv/bin/python scripts/test_predictions_$t.py \| tail -1; done` |
| VP-2 | Golden eval, live, on four synthetic transcripts | **succeeded**: precision 1.000, recall 0.929, 0 false positives on 24 negative spans; one soft metric (confidence type 0.846) was a spec gap since fixed, not re-run | `.venv/bin/python scripts/eval_predictions.py --scored <scratch>/eval-live/tree` (report in `docs/PREDICTIONS.md` section 9) |
| VP-3 | Ten-transcript pilot plus the first live transcript | **succeeded**: 26 candidates from 407 weighed, 11 accepted, 13 rejected, 0 ungrounded; 2 Gemini verify failures retried to success | `.venv/bin/python scripts/validate_predictions.py` (exit 0, 13 files, 26 records) |
| VP-4 | Corpus extraction over all 682 transcripts, 4 workers, detached from repo-2 | **attempted**: at 04:36Z 87 succeeded, 0 failed, 4 excluded, all on Astra; about 1.6 hours in; roughly 8 to 11 hours total; resumable | `LOG=$(ls -t data/predictions/_runs/extract-corpus-*.log \| head -1); grep -c '"status": "ok"' $LOG; grep -o '"error_type": "[a-z_]*"' $LOG \| sort \| uniq -c; pgrep -f "stage extract --workers 4"` |
| VP-5 | Corpus verification pass (a different model family per transcript) | **blocked-on-VP-4 finishing**. Extraction is all Astra, so verification lands on Fable or Gemini; Fable was near 0% on three of five accounts at launch, so some jobs may fail `auth_or_quota` and need a re-run after a window resets | `quotapick status`; then the verify command in `HANDOFF.md` |
| VP-6 | Market-consensus pass on accepted records | **succeeded on the pilot** (3 records, 3 `no_match`, 0 failures after the degraded-pick fix); corpus pass waits on VP-5 | `.venv/bin/python scripts/market_consensus.py --workers 2` |
| VP-7 | Page at verbatim-predictions.tonygwu.com | **succeeded**, deployed with the pilot's 11 predictions; answers 200, a wrong path 404; index page redeployed with the cross-link | `curl -s -o /dev/null -w '%{http_code}\n' https://verbatim-predictions.tonygwu.com/` |
| VP-8 | Commit of `data/predictions/` into the private data repo | **blocked-on-repo-0 running** `git -C data add predictions && git -C data commit` (only repo-0 commits data); best done after VP-5 | `git -C data status --short \| grep -c predictions` |
| VP-9 | Live golden eval re-run under the final specs (belief verbs, undated rule, relative dates) | **not started**: costs about 8 calls; the saved tree predates three spec clarifications | `PREDICT_LIVE=1 .venv/bin/python scripts/eval_predictions.py --out <dir>` |
| VP-10 | 35 wrong-person recordings still on disk; skipped by the exclusion list | **blocked-on-CI-6** (repo-0 applying the withdrawal manifest); harmless meanwhile | `.venv/bin/python -c` count of excluded ids present under `data/transcripts_open` |
| VP-11 | A transcript withdrawn by repo-0 mid-pass crashed the job instead of being skipped | **succeeded**: `extract_one` read the file before the exclusion check, so three withdrawn recordings failed as `cli_nonzero_exit` with `"id": "?"`; the id now comes from the path, a missing file raises `transcript_missing`, and the pass names the transcript | `.venv/bin/python scripts/test_predictions_driver.py` (MISSING labels) |
| VP-12 | Audit of the 36 transcripts that vanished under the extraction pass | **succeeded**: all 36 legitimate, each traced to a commit and a reason (30 withdrawal manifest, 2 wrong-person screen, 3 duplicate sweep, 1 identity audit); all retained as `.superseded`, 500,716 words, none truncated, none in `results.json` | `find data/transcripts -name '*.json.superseded' \| wc -l`; the ids are in the extract-corpus log's failed rows |
| VP-13 | Two sweep findings to carry to repo-0 and `docs/LEDGER-corpus-integrity.md` | **open, not a predictions defect**: (1) commit `2003509` names only `lisa-su` but retired five recordings, the other reasons only in `data/logs/dedupe_sweep.log`; (2) the duplicate sweep is not order-independent, three recordings were the KEPT side of earlier pairs at containment 0.833-0.959 and were later retired against a HappyScribe copy at 0.458-0.582 | `grep -n 'game-time-fvqitw\|zenvora-productions' data/logs/dedupe_sweep.log` |
| VP-14 | Index table cut from eleven columns to six | **succeeded** 2026-09-13: the five horizon and confidence breakdown columns were three ways of splitting one count, and a nine-number table read as a scoreboard on a page that scores nothing; they moved into the drawer as one summary line, and the counts stay in DATA | `.venv/bin/python scripts/test_predictions_site.py \| tail -1` (29 checks; the three new ones fail against the pre-change builder) |
| VP-15 | Phase 2 scope: what a score could honestly cover | **succeeded** 2026-09-13, scoping only, no calls spent: 38 of 475 accepted predictions are scorable as foresight, across 21 leaders, and 1 leader reaches a floor of 5; Brier has n=1 and market-relative has n=0. Recommendation is resolution without a ranking. `docs/PREDICTIONS-PHASE2-SCOPE.md` | `.venv/bin/python scripts/phase2_resolvability.py --as-of <YYYY-MM-DD>`; `.venv/bin/python scripts/test_phase2_resolvability.py` |
| VP-16 | 8 past-due predictions target a date BEFORE their own statement date | **open**, 5 leaders, 2.5% of the 325 dated records; cause is the upload date standing in for the date of speech, so a 2006 talk uploaded in 2013 resolves "this year" to the wrong year. Must be cleared before any resolution pass, and the detector only catches the provably-impossible direction | `.venv/bin/python scripts/phase2_resolvability.py --as-of $(date -u +%F) \| tail -12` |
| VP-17 | Six-column table is committed but NOT deployed | **open**: the live site at verbatim-predictions.tonygwu.com still shows the eleven-column table. The staleness gate was checked on 2026-09-13 and passes (index 666 files / 1494 records / sha fddfb8e6f55d, disk identical), so the deploy is a one-command job from repo-0 | `bash scripts/deploy_predictions.sh --production-data ../data --data-revision $(git -C data rev-parse HEAD) --dry-run` to re-check the gate, then without `--dry-run` to publish |
| VP-14 | Corpus published at verbatim-predictions.tonygwu.com | **succeeded** 2026-09-14: 50 people, 475 accepted predictions from 285 transcripts, 666 transcripts scanned, 96% carrying a statement date; home 200, a wrong path 404 | `curl -s -o /dev/null -w '%{http_code}' https://verbatim-predictions.tonygwu.com/` |
| VP-15 | Three routing and taxonomy defects that cost 31 wasted calls | **succeeded**: a spent router pick now refuses before any call while Antigravity still routes; failures name their account; `classify_cli_failure` matches the limit FAMILY; `router_version_ok()` refuses a stale venv. Root cause was repo-2 running llm-quota-router 0.1.0 against a 0.1.1 floor. All five clones now on 0.1.1 | `.venv/bin/python scripts/test_predictions_driver.py`; `.venv/bin/python scripts/test_grade_harness.py` |
| VP-18 | The live board states a lead-time rule the scorer does not use, in TWO places | **open**, found by repo-1 2026-09-16, corrected and confirmed by repo-0 the same day. `MIN_LEAD_DAYS` has been 60 since the operator lowered it from 180 on 2026-09-15, and `scores.json` carries `min_lead_days: 60`, but the page still says six months, which is 180. Two sites, and the SECOND is the larger: `build_predictions_site.py:980` is unconditional methodology prose ("when it was said less than six months before its own deadline") that renders once per page for every reader; `:995` is the `score_why` tooltip, which reaches only the 6 rows in the `n_scored == 0 and eligible == 0` branch (alexandr-wang, arthur-mensch, brian-armstrong, greg-brockman, matthew-prince, sam-altman). repo-1 first logged this as 10 rows and one site; both were wrong. 10 conflated that branch with the 5-row `eligible > 0` branch, which renders different text. The fix is to import and render `MIN_LEAD_DAYS`, NOT to retype 60: both functions already derive `{MIN_SCORED}` from the constant at :981 and :996, which is exactly why floor 3 followed the operator's change and six months did not. Not fixed by repo-1 or repo-0 unilaterally because it edits published page text; repo-0 has taken it to the operator as a decision | `grep -n 'six months' scripts/build_predictions_site.py` (expect 2 hits); `grep -n '^MIN_LEAD_DAYS' scripts/phase2_resolvability.py`; `python3 -c "import json;print(json.load(open('data/predictions/scores.json'))['rule']['min_lead_days'])"` |
| VP-19 | `score_why()` returns "below the floor" text for rows that are ABOVE the floor | **open**, latent, same owner as VP-18. Its docstring scopes it to "when a row carries no number", but line 856 calls it for every row, so `andy-jassy` at 22 scored carries "22 scored, below the floor of 3; a number on so few is a placeholder, not a score" in the embedded DATA. NOT user-visible today: line 425 renders `score_why` only when `r.score == null`, so no reader sees it. Recorded because the next use of that field, a drawer line or an export, would publish it. repo-1 first reported this to two peers as a live user-visible bug and that was WRONG; the correction is the difference between a payload defect and a published one | `curl -s https://verbatim-predictions.tonygwu.com/ \| grep -o '"n_scored": 22, [^}]*score_why[^"]*"[^"]*"'` |
| VP-20 | The index page's link OUT to the predictions board is switched OFF | **open by design**, 2026-09-16 at the operator's request. verbatim-index.tonygwu.com is about to be posted publicly, and the predictions board's Score column is still empty for 25 of the 40 listed people, so a link off the finished page lands a reader on an unfinished one. `SHOW_PREDICTIONS_LINK = False` in `build_site.py`; restoring it is that one word. The back-link the OTHER way is deliberately unchanged, because it sends a reader from the unfinished board to the finished one. NOT YET LIVE: `site/index.html` is gitignored and rebuilt at deploy time, so the link stays on the published page until the index site is next deployed. Restore this before or with the round-2 scoring that fills the column | `grep -n '^SHOW_PREDICTIONS_LINK' scripts/build_site.py`; `curl -s https://verbatim-index.tonygwu.com/ \| grep -c verbatim-predictions` |


## Decisions waiting

| ID | Decision | Options and costs | Recommendation | If undecided |
|---|---|---|---|---|
| VD-2 | When to run the corpus verification if Fable is spent | (a) run when extraction ends and accept `auth_or_quota` failures, re-run after the reset (claude_c resets ~2026-09-12T02Z, claude_e ~2026-09-13T15Z). (b) pin `--verifier gemini` for the whole pass: one account behind two profiles, unmeasured quota, higher empty-answer rate on long windows. | (a); the pass is resumable and the taxonomy shows exactly what failed | (a) is what the handoff's next-action block does |

## Decided

| ID | Decision | Choice | Date |
|---|---|---|---|
| VD-4 | Whether to migrate the corpus to release `predictions-2.0` | **No. Stay on extraction `d795f6f1d88b` / verification `102275d44824`** | 2026-09-14 |
| VD-1 | Verifier strictness on undated claims | keep strict for V0; revisit with human labels in Phase 2 | 2026-09-11 |
| VD-3 | Whether the page gets a market-surprise column | **no**, settled by measurement rather than judgement: the corpus market pass returned 0 exact matches of 475 (451 `no_match`, 22 `unavailable`, 2 `failed`) against the 20% threshold this ledger set. Public prediction markets and interview claims are close to disjoint | 2026-09-13 |
| VD-0a | Where predictions are written | `data/predictions/` from any clone; writer refuses other data paths | 2026-09-10 |
| VD-0b | Extraction strategy | extract with one model, verify with a different family, accept only on agreement | 2026-09-10 |
| VD-0c | Where the page lives | `verbatim-predictions.tonygwu.com`, its own Worker | 2026-09-10 |
| VD-0d | Market evidence in V0 | separate stage after verification, public APIs only, `P_market(t^-)`, exact and proxy kept apart, speaker probability never touched | 2026-09-10 |
| VD-0e | Roadmap statements | extracted and tagged `subject_control: own`, not gated | 2026-09-10 |

## VD-4, why the corpus did not migrate

A 40-transcript paired sample, seeded, with extraction pinned to Astra and
verification pinned to Gemini so the models are held fixed and the policy is
the only variable. Records under
`data/predictions/_experiments/policy2-sample-20260914T045950Z/`.

`predictions-2.0` accepts 77% more: 118 candidates and 35 accepted became 136
and 62, so 30% acceptance became 46%. Eleven transcripts gained and none lost,
so the direction is not re-run noise. Acceptance alone argued for migrating.

Reading the content reversed that. The growth is undated material. Of the 17
candidates that share an exact `prediction_id` and flipped from rejected to
accepted, 12 carry no target date. The corpus-wide undated share would rise
from 11% to 40%. An undated claim can never be resolved, so Phase 2 could
never score it.

One case is a correctness defect rather than a judgement call. The new policy
tells the verifier to resolve relative time against the metadata statement
year, and the statement year is the YouTube UPLOAD date, documented everywhere
in this repo as an upper bound on the recording date. On a CES keynote from
2005 uploaded in 2013, "office 12 and many other products will come out" was
accepted as "Microsoft will release Office 12 by the end of 2013". The OLD
verifier rejected that same quote for exactly this reason, on `claim_faithful`.
Five accepted records from that one transcript carry 2013 dates. Across the
sample, records whose target year equals the upload year with no year in the
quote went from 9 under the old policy to 17 under the new one.

Revisit when the statement-date basis is handled. repo-4, who owns the
release, has moved to other work, so this is unowned. Their own report says to
"use agreed reference cases to resolve the remaining judgment boundaries
before a broader quality comparison or corpus migration", and no such
reference cases exist. Neither policy has human labels, so every comparison so
far is one model judging another.
