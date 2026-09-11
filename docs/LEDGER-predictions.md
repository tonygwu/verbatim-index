# Ledger: Verbatim Predictions workstream

Standing state for the predictions product in `docs/PREDICTIONS.md`. Updated
when an item changes state, not at poll time. Every open item carries the
command that verifies it. Last verified 2026-09-11T04:36Z from repo-2.
Last poll answered: 2026-09-11T04:36Z. VD-1 decided 2026-09-11 (keep strict).

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

## Decisions waiting

| ID | Decision | Options and costs | Recommendation | If undecided |
|---|---|---|---|---|
| VD-3 | Whether the page gets a market-surprise column | (a) none for V0: the table stays descriptive counts, and the contemporaneous market shows per prediction inside the drawer. (b) add a surprise column, the distance between the speaker's claim and the contemporaneous market price, once the market pass has run. It needs no outcome, so it is available in V0, but 3 of 3 searched pilot records came back `no_match`, and a column blank for most rows invites ranking on noise. | (a) until the corpus market pass reports its exact-match rate; build (b) only if exact matches exceed about 20% of accepted predictions. A real forecasting score needs resolution and stays Phase 2. | (a) is what ships |
| VD-2 | When to run the corpus verification if Fable is spent | (a) run when extraction ends and accept `auth_or_quota` failures, re-run after the reset (claude_c resets ~2026-09-12T02Z, claude_e ~2026-09-13T15Z). (b) pin `--verifier gemini` for the whole pass: one account behind two profiles, unmeasured quota, higher empty-answer rate on long windows. | (a); the pass is resumable and the taxonomy shows exactly what failed | (a) is what the handoff's next-action block does |

## Decided

| ID | Decision | Choice | Date |
|---|---|---|---|
| VD-1 | Verifier strictness on undated claims | keep strict for V0; revisit with human labels in Phase 2 | 2026-09-11 |
| VD-0a | Where predictions are written | `data/predictions/` from any clone; writer refuses other data paths | 2026-09-10 |
| VD-0b | Extraction strategy | extract with one model, verify with a different family, accept only on agreement | 2026-09-10 |
| VD-0c | Where the page lives | `verbatim-predictions.tonygwu.com`, its own Worker | 2026-09-10 |
| VD-0d | Market evidence in V0 | separate stage after verification, public APIs only, `P_market(t^-)`, exact and proxy kept apart, speaker probability never touched | 2026-09-10 |
| VD-0e | Roadmap statements | extracted and tagged `subject_control: own`, not gated | 2026-09-10 |
