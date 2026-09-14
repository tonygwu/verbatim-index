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

## Decisions waiting

| ID | Decision | Options and costs | Recommendation | If undecided |
|---|---|---|---|---|
| VD-2 | When to run the corpus verification if Fable is spent | (a) run when extraction ends and accept `auth_or_quota` failures, re-run after the reset (claude_c resets ~2026-09-12T02Z, claude_e ~2026-09-13T15Z). (b) pin `--verifier gemini` for the whole pass: one account behind two profiles, unmeasured quota, higher empty-answer rate on long windows. | (a); the pass is resumable and the taxonomy shows exactly what failed | (a) is what the handoff's next-action block does |

## Decided

| ID | Decision | Choice | Date |
|---|---|---|---|
| VD-1 | Verifier strictness on undated claims | keep strict for V0; revisit with human labels in Phase 2 | 2026-09-11 |
| VD-3 | Whether the page gets a market-surprise column | **no**, settled by measurement rather than judgement: the corpus market pass returned 0 exact matches of 475 (451 `no_match`, 22 `unavailable`, 2 `failed`) against the 20% threshold this ledger set. Public prediction markets and interview claims are close to disjoint | 2026-09-13 |
| VD-0a | Where predictions are written | `data/predictions/` from any clone; writer refuses other data paths | 2026-09-10 |
| VD-0b | Extraction strategy | extract with one model, verify with a different family, accept only on agreement | 2026-09-10 |
| VD-0c | Where the page lives | `verbatim-predictions.tonygwu.com`, its own Worker | 2026-09-10 |
| VD-0d | Market evidence in V0 | separate stage after verification, public APIs only, `P_market(t^-)`, exact and proxy kept apart, speaker probability never touched | 2026-09-10 |
| VD-0e | Roadmap statements | extracted and tagged `subject_control: own`, not gated | 2026-09-10 |
