# Verbatim Pundits

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you work on the pundits
study: its data repository, contract v2, judge harness, roster, discovery,
pilot, speaker-check pages, labelling kit or deploy.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Where things are

- **Verbatim Pundits is PUBLISHED** (2026-09-16, operator-approved): two custom domains on
  one Worker, `pundits.tonygwu.com` and `verbatim-pundits.tonygwu.com`, both serving
  `site-pundits/index.html`. Deploy with
  `bash scripts/deploy_pundits.sh --production-data data-pundits --data-revision "$(git -C data-pundits rev-parse HEAD)"`,
  and `--dry-run` first. A bare `npx wrangler deploy` reads `wrangler.toml` and publishes the
  LEADERS board instead, never this one.
  Since 2026-10-12 the page and `site-pundits/revision.json` carry the data revision. The
  deploy refuses when the live `revision.json` names a revision this checkout does not descend
  from, or, at the same data revision, public code this checkout does not descend from. After
  publishing it reads the live `revision.json` back and fails unless it equals the one this
  deploy wrote, whole, and the live page carries the data revision's meta tag. The page live
  on 2026-10-12 predates `revision.json`, so the NEXT deploy adds `--first-revision-deploy`,
  once. That flag covers only a site with no `revision.json` (HTTP 404); any other failure to
  read still refuses. When the published inputs differ from the data HEAD (owner mode renders
  the daemon's uncommitted output), the footer says "plus uncommitted changes" and
  `revision.json` records `data_uncommitted: true`. The staleness check compares
  bytes as well as counts: `results.json` must carry `grade_files_sha256` (written by
  `aggregate.py` since 2026-10-12) matching the grade files on disk, so the first deploy
  after repo-3 pulls that code needs a fresh aggregate (the loop's next cycle, or `--refresh`). Proof: `scripts/test_deploy_pundits.py`. Right after a trigger deploy the new hostname can
  return Cloudflare error 1104 for a minute; it clears on its own, so re-check before
  debugging it.
  The board is a PILOT and says so on the page. `status_banner()` in
  `build_study_site.py` renders the coverage, the recordings-per-person range, the measured
  blinding leakage and whether the format adjustment was withheld, all DERIVED from
  `results.json`. `status_label` and `status_note` are required copy keys so the notice
  cannot vanish by omission, and no figure may be typed into `profiles/pundits.site.json`.
  Guarded by `scripts/test_pundits_site_banner.py`.

- Release plan: `docs/PUNDITS-RELEASE-PLAN.md` says what still stands between the pilot board
  and a full public release, phase by phase, with owners and the operator's open decisions.
  Read it before you pick up pundits work, so you take a step on its critical path.

- Pundits study plan: `docs/PUNDITS-PLAN.md` is the approved plan (revision 2, with the
  P3 decisions folded in). It is the contract every clone works from: phases P0-P11,
  their PASS/FAIL/INCONCLUSIVE gates, and the call-budget manifest. Edit the committed
  copy, not a private one.

- Pundits study (verbatim-pundits.tonygwu.com, in progress): the P0 leaders
  baseline in `docs/PUNDITS-P0-BASELINE.md`, re-run with
  `.venv/bin/python scripts/leaders_baseline.py --code DIR --snapshot DIR --run-dir NEW --python .venv/bin/python`
  (quota-free; two identical runs differ only in `normalization.normalized_at_utc`
  and `summary.generated_at_utc` in the QA report).
  The P1 study-isolation checklist is `docs/STUDY-ISOLATION-TRACE.md`.

- Pundits data and ownership (set up 2026-09-14): private repository
  `tonygwu/verbatim-pundits-data`, checked out in repo-3 at `.data-clones/pundits`
  behind the `data-pundits` link, registered with
  `git config verbatim.pundits.productionData`. repo-3 owns pundits production: it
  alone runs `STUDY=pundits` loops and commits pundits data, and its local
  `.daemon-clone` there says so. That ownership is separate from leaders, where
  repo-3 remains an experiment clone. Any clone may change pundits CODE and the
  pundits dashboard through this public repository as usual; only data writes are
  owned. The pundits board is a separate site (verbatim-pundits.tonygwu.com) with
  its own data repository, and it never reads the leaders corpus.

- Grading contract v2 (pundits; leaders stays on v1): `scripts/grading_contract.py`,
  recorded in `docs/PUNDITS-P2-CONTRACT.md`. The contract hashes the skill's
  RUBRIC.md, schema and PROMPT.md, plus the profile's scoring, identity, blinding
  and judge-request blocks. Paths and domains go in `_provenance/`. A stored v2
  grade is reused only if study, contract, prompt hash, input hash, mode, judge,
  requested model and run all match. Otherwise `grade.py` reports `stale_cache`,
  exits 1, and leaves the file alone; `--force` moves the file to `_obsolete/`
  first. `aggregate.py` refuses a v2 corpus with any grade from another study or
  contract, including a corpus that holds only one obsolete contract.
  `VI_PROFILES_DIR` is a test seam only. Proof:
  `.venv/bin/python scripts/test_pundits_contract.py`.

- P3 judge probe (pundits, SPENDS QUOTA with `--run`): `scripts/p3_judge_probe.py`.
  It runs each judge's real argv under `sandbox-exec`, in a jail outside the
  verbatim-index container, with reads and writes denied under that container. It
  asks the judge to search the web, read planted canaries, run a shell command and
  fetch a URL. Each call gets PASS, FAIL or INCONCLUSIVE, and the judge's
  served-model identity is marked VERIFIED or UNVERIFIED. Raw responses go to
  `data-pundits/logs/p3_probes/<run>/`. Without `--run` it is a dry run that
  only proves the sandbox denies the canaries:
  `.venv/bin/python scripts/p3_judge_probe.py --fable-config-dir ~/.claude-e --gemini-home ~`.

- Pundits judge harness (P3, decided 2026-09-14, `docs/PUNDITS-P3-PROBES.md`): every judge
  of a contract v2 study runs under `sandbox-exec`, which denies reads and writes under
  the verbatim-index container. Fable also gets `--tools ""`, and its session transcript
  must show zero tool calls, or the grade fails as `tool_attempt` or
  `tool_audit_unavailable`. Astra and Gemini keep provider-side web search by the user's
  decision; searched grades are kept and measured, never discarded. Under the sandbox,
  Gemini accepts HOME profiles only. Leaders judge argv is unchanged. Proof:
  `.venv/bin/python scripts/test_pundits_harness.py`.

- Pundits roster (P6): `data-pundits/roster/final.json` holds only public fields. Lean
  labels live in `data-pundits/private/lean_labels.json` as `{slug: lean}`, the shape
  `scripts/schedule.py` reads, and their cited outside sources live in
  `data-pundits/private/lean_sources.json`. Never copy a lean field into the roster,
  a prompt or a public commit. Check all three files before any discovery run:
  `.venv/bin/python scripts/pundits_roster.py --study pundits --roster data-pundits/roster/final.json --lean-labels data-pundits/private/lean_labels.json --lean-sources data-pundits/private/lean_sources.json`.
  Proof: `.venv/bin/python scripts/test_pundits_roster.py`.

- Pundits discovery (P6): `scripts/discover_pundits.py`, never `discover_sources.py`, for
  the pundits study. It lists each roster own channel by canonical id and requires the
  full name or a handle plus a second identity token for any other channel; no surname
  or fuzzy match. Flat listings carry no upload date, so the date window is applied
  after fetch. Proof: `.venv/bin/python scripts/test_discover_pundits.py`.

- Pundits QA own-channel skip (P6): the fetcher records `yt_channel_id`, and
  `qa_transcripts.apply_own_channel_skip` skips ONLY the name-density rejection when that id
  matches a roster own channel. Leaders entries have no `own_channels`, so leaders QA is
  unchanged. Proof: `.venv/bin/python scripts/test_qa_own_channel.py`.

- P10 gate report (no quota): `scripts/pundits_gates.py --data <pundits data> --lean-labels <the
  private lean file> --out <scratch>/gates.json` computes Fable tool calls, identity (confident
  and correct), G-search, G-coverage, G-judge-lean, G-halo-lean and G-drift, each PASS, FAIL or
  INCONCLUSIVE, with a few-clusters warning under 10 people a group. It refuses an `--out`
  inside the data checkout. `scripts/pundits_gate_doc.py --report ... --data-revision ...
  --withhold-lean --out ...` renders it as Markdown (P11 step 1). Keep `--withhold-lean` for
  anything public until the operator sets a disclosure rule (`docs/PUNDITS-RELEASE-PLAN.md`,
  decision 4): a lean-split figure next to public per-person facts can name a person's lean.
  Pilot dry run: `docs/PUNDITS-P10-PILOT-GATES.md`. Proof: `scripts/test_pundits_gates.py`,
  `scripts/test_pundits_gate_doc.py`.

- P5 sensitivities, in `results.json` diagnostics for a contract-v2 study only:
  `venue_leave_one_out` (each venue dropped in turn), `archival_excluded` (calibration
  refitted without archival subjects, proved against a real re-run) and `era_covariate` (the
  within-person slope of the blinded score on `yt_upload_date`, in points a year, with a
  person-resampled 95% interval; reported, never applied). `era_covariate` reads the dates
  from the records under `--transcripts`, and without that flag it says so. The page states
  all three in its Sensitivity section (`build_study_site.sensitivity_section`), every number
  read from `results.json`. Proof: `scripts/test_pundits_sensitivity_page.py`,
  `scripts/test_venue_leave_one_out.py`, `scripts/test_archival_sensitivity.py`,
  `scripts/test_era_covariate.py`.

- Phone layout: after any change to the page's CSS or columns, run
  `.venv/bin/python scripts/check_pundits_phone_layout.py --page site-pundits/index.html` (needs
  Google Chrome, so it is a check_ script outside the globbed suite).

- P10 sample-size check (no quota): `scripts/pundits_sample_size.py --data <pundits data>` projects
  G-judge-lean's 90% half-width from the pilot's grades. Result of 2026-10-11 in
  `docs/PUNDITS-P10-SAMPLE-SIZE.md`: 2.49 at 20 left and 20 right people, above the plan's 2.0, so the
  operator decides before P9 whether to add people. Proof: `scripts/test_pundits_sample_size.py`.
- P6 discovery pilot: `scripts/pundits_pilot.py sample | precheck | report`. `precheck` fails
  only what the record proves (no upload date, outside the window, after an archival
  subject's last recording, a substitute host in the opening) and writes a checklist that a
  PERSON must fill for every other recording; `report` stays INCONCLUSIVE until every label
  exists, then applies the P5 caps and gives yield with exact bounds. Proof:
  `.venv/bin/python scripts/test_pundits_pilot.py`.

- Model drafts for the P6b speaker check: `scripts/pundits_speaker_infer.py infer --study pundits
  --set p6b --credit-pools anthropic_api_e,anthropic_api_b,anthropic_api_a` drafts the three
  answers for each of the 218 P6b recordings with Fable on prepaid API credit, through
  `quotapick run` (`scripts/credit_run.py`), and keeps each attempt's full response under
  `logs/p6b/_raw/speaker_inference/<slug>/<sid>.<n>.json` (the first run of 2026-10-18 wrote
  `<sid>.json`, which counts as attempt 1). Re-running retries only rows with an error. Once the
  named pools are out, no further call is made and the remaining rows are left to do; any error or
  skipped row exits 1. "Out" can also mean calls in flight hold the last of the money, so re-run
  with `--workers 1` to spend the rest. `review --set
  p6b` writes `speaker_review_queue.json`: calibration against the operator's labels, and the
  rows a person should still check. A P6b label has no `main_speaker`, because the guide stopped
  asking on 2026-09-15, so review and calibration compare only the fields a person labelled. A
  draft is never a label: `merge` marks each one `drafted_by_model`. The review page shows the
  drafts when built with `--drafts` (next item). Calibration counts only blind labels: one saved
  with a draft on screen carries `draft_shown` and is left out, and counted as
  `assisted_labels_left_out`. Proof: `scripts/test_pundits_speaker_infer.py`,
  `scripts/test_credit_run.py`.

- Pundits predictions pilot: `experiments/predictions-pilot-20261018/` in the pundits data repo,
  with a README. Fable extracted on prepaid API credit (`extract_predictions.py --extractor fable
  --fable-credit-pools ...`) and Gemini verified, because Astra refuses political content. 20
  recordings gave 14 candidates and 4 accepted predictions for $18.72. An experiment only: the
  extractor has no `--study` yet (BACKLOG.md VI-1), so pass the pundits transcripts,
  roster and an `--out` under that folder by hand.

- P6 speaker check (human labels for the full roster): an annotation session of the `pundits`
  project, built and served by `scripts/annotations.py`. The tool, its modes, storage, commands
  and rules are in [ANNOTATIONS.md](ANNOTATIONS.md); what is pundits-specific is here. Build
  it into the pundits data checkout, never this repository, with
  `annotations.py build --data data-pundits --project pundits --checklist
  data-pundits/logs/p6b/human_checklist.json --grades [--drafts
  data-pundits/logs/p6b/speaker_inference.jsonl] --out data-pundits/logs/p6b`, and serve it
  with `annotations.py serve --session data-pundits/logs/p6b`. ONE screen per recording: the
  checklist (subject present, format, political content) and, below it, any flagged evidence
  quotes for that recording, so a video is opened once. `--grades` flags evidence quotes the
  judges credited to the subject that mechanical signals mark as suspect (a caption turn mark
  inside the quote, a question inside a conversation or debate, the subject's own name) and
  shows the judges' located evidence as suggestions, so these are ASSISTED labels; their
  rates describe FLAGGED quotes only and do not replace the P7 random quote audit.
  With `--drafts` each recording also shows the model's draft and the list puts first every
  recording that `pundits_speaker_infer.needs_review` flags, then the confident ones, then
  quote-only recordings. A draft is never an answer; a label saved while a draft was on
  screen records `draft_shown` with the model's name, and calibration leaves it out.
  `annotations.py export labels --session data-pundits/logs/p6b --out
  data-pundits/logs/p6b/human_labels.json` writes what `pundits_pilot.py report` and
  `pundits_speaker_infer.py review` read; a partly answered recording is left out and
  counted, never filled. The session built before 2026-10-18 (`speaker_check.html`,
  `quote_check_key.json`, no manifest) is adopted with `annotations.py migrate --session
  data-pundits/logs/p6b --project pundits`, which writes `manifest.json` only; repo-3 runs it,
  because this data repository is owner-only.

- P7 labelling kit: `scripts/pundits_label_kit.py windows | quotes`, with the rules for the
  people who label in `docs/PUNDITS-LABELLING-GUIDE.md`. Windows are cut only from recordings a
  person verified, by the human venue label; quotes hide the judge and its speaker label in a
  separate answer key. Every label field is written empty, and a short format is reported, never
  topped up. Proof: `.venv/bin/python scripts/test_pundits_label_kit.py`.

- Pundits verification (plan, Verification section): `bash scripts/run_tests.sh` is the
  fail-loud suite runner (globbed, exits nonzero on any failure). Since VI-29 it keeps every
  test's stdout and stderr under `.gate/<utc>-<pid>/<test>.log` (git-ignored; never pruned,
  about 1 MB a full run, delete the folders yourself) and prints only a failing test's last
  20 lines under its `FAILED` line, so a warning a test printed to the terminal is now in its
  log;
  `bash scripts/run_tests.sh <test>...` runs only the named tests. Proof:
  `scripts/test_run_tests_sh.py`.
  `scripts/test_private_label_leak.py` plants a lean-label canary and proves it is absent
  from both prompt modes, the blinded text and the page, and that only `schedule.py`,
  `pundits_roster.py` and the P3 probe name the private lean files; adding a reader fails it.
  `scripts/test_judge_jail.py` runs a fake judge under the real sandbox wrapper and proves
  read, list, write and child-shell access to the container are denied (network is not
  denied, by the P3 decision). Leaders byte identity:
  `.venv/bin/python scripts/leaders_identity_compare.py --a RUN1 --b RUNN` over two
  `leaders_baseline.py` runs, tolerating only `normalization.normalized_at_utc` and
  `summary.generated_at_utc`; a raw hash
  diff overstates change (1,328 false differences on 2026-09-14).

- P4d Fable tools-off measurement (SPENDS QUOTA with `--run`):
  `scripts/p4d_fable_tools_off.py`. Result in `docs/PUNDITS-P4D-FABLE-TOOLS-OFF.md`:
  12/12 valid, 95% interval [0, 26.5%], so not yet evidence of a low rate; P8a decides.

- Pundits panel is TWO judges, Fable and Gemini (decided 2026-09-16,
  `docs/PUNDITS-P8A-PILOT.md`). Astra declined 42 of 44 production calls, 4 of 4 re-runs on
  byte-identical prompts, and all 5 truthful prompt variants, explicitly refusing the
  "evidence levels" framing. Do NOT delete Astra from `profiles/pundits.json`:
  `judge_requests` is hashed into `contract_id` (`V2_PROFILE_KEYS`), so editing it would make
  every grade already collected incompatible. Astra is dropped by not being called
  (`--judges fable,gemini`), and `aggregate.py` derives the panel from the grades present.
  The operator explicitly approved publishing two-judge scores; the P11 deploy approval is
  separate and still required. Reproduce the prompt experiment with
  `.venv/bin/python scripts/astra_prompt_probe.py --out DIR` (SPENDS CODEX QUOTA).
