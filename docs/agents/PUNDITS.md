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
  LEADERS board instead, never this one. Right after a trigger deploy the new hostname can
  return Cloudflare error 1104 for a minute; it clears on its own, so re-check before
  debugging it.
  The board is a PILOT and says so on the page. `status_banner()` in
  `build_study_site.py` renders the coverage, the recordings-per-person range, the measured
  blinding leakage and whether the format adjustment was withheld, all DERIVED from
  `results.json`. `status_label` and `status_note` are required copy keys so the notice
  cannot vanish by omission, and no figure may be typed into `profiles/pundits.site.json`.
  Guarded by `scripts/test_pundits_site_banner.py`.

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

- P6 discovery pilot: `scripts/pundits_pilot.py sample | precheck | report`. `precheck` fails
  only what the record proves (no upload date, outside the window, after an archival
  subject's last recording, a substitute host in the opening) and writes a checklist that a
  PERSON must fill for every other recording; `report` stays INCONCLUSIVE until every label
  exists, then applies the P5 caps and gives yield with exact bounds. Proof:
  `.venv/bin/python scripts/test_pundits_pilot.py`.

- P6 speaker check (human labels for the full roster): `scripts/pundits_verify_page.py build`
  turns `pundits_pilot.py precheck`'s checklist into one page, written into the PRIVATE data
  checkout because it carries transcript excerpts. **Serve it locally; do not publish it as an
  Artifact.** `scripts/pundits_verify_serve.py --page <the built page>` serves it on
  127.0.0.1:5001 and saves every answer to `human_answers.json` beside the page, which
  `import` and `import-quotes` both read. The socket binds to loopback and there is no flag to
  widen it, because the page carries private transcript text; that is also why it is not a
  fourth Cloudflare Worker. The server accepts only ids it reads out of the page it is serving,
  so a stale page cannot accumulate answers the import would later throw away.
  The page chooses where to save by asking, never by inspecting its own hostname: it probes
  `api/answers` first and falls back to the Artifact `db` capability. The published Artifact
  https://claude.ai/artifact/9TEivUMn7nhrYZJhkRRnsb still works, but ONLY for the one account
  that owns it. The runtime grants db writes to people who can interact or edit and never to a
  view-only viewer or a link visitor, and a page cannot lower that bar, so a second Google
  account gets a read-only page. That is what sent this local.
  A partly answered recording is left out and counted, never filled.
  ONE screen per recording: the three questions and, below them,
  any flagged evidence quotes for that same recording, so a video is opened once. The page shows
  evidence quotes the judges
  credited to the subject that mechanical signals mark as suspect (a caption turn mark inside
  the quote, a question inside a conversation or debate, the subject's own name); build with
  `--grades` and `--quote-key`. The private key preserves grading provenance,
  and `import-quotes` joins answers to it. Its rates describe FLAGGED quotes only, so it
  does not replace the P7 random quote audit. Proof: `.venv/bin/python scripts/test_pundits_verify_page.py`
  and `scripts/test_pundits_verify_serve.py`, which runs a real server on a real socket and
  reads the bind address off the listening socket rather than off the constant.
  **The page's own JavaScript is not covered by either.** FOUND 2026-09-20: the save adapter
  went in as a module-level `store`, and `setField(store, id, f, v)` already took a parameter of
  that name, so inside setField the parameter won and every save died with
  `store.put is not a function`. `node --check` passed it and no Python test executes the page.
  A browser found it in one keystroke. So after any change to the page's JS, drive it:
  serve the page, load it with Playwright, press `y`, and assert the answer reached the file.
  The globbed suite now carries the static half of that lesson as its SHADOW check.
  **Speaker ranges (2026-09-20, operator requested assisted review):** each quote passage
  has draggable text selection, multiple disjoint ranges, start/end sliders, remove and
  undo; full transcript expansion stays on the same video. `pundits_span_editor.js` is
  embedded at build time. Private `<page-stem>.transcripts/` sidecars hold raw tokens and
  located evidence suggestions; `pundits_speaker_spans.py` records judge provenance and
  withholds ambiguous matches. Model drafts are shown explicitly and require confirmation;
  words without a saved attribution remain unknown. These assisted labels cannot count as
  blind audit labels. Human ranges live in `human_answers.json`'s `spans` section with a
  transcript SHA-256 and end-exclusive word offsets. The server refuses stale hashes,
  overlapping ranges and invalid bounds; existing labels/attribution remain compatible.
  Import using `pundits_verify_page.py import-spans --export <answers> --page <page> --out <output>`.
  This preserves annotations separately; it does not rewrite grades. Verification:
  `test_pundits_speaker_spans.py` plus `.venv/bin/python scripts/check_pundits_span_ui.py`
  (Playwright, isolated synthetic data). Rebuild the page and restart ONLY its local server
  after changing embedded JS; a running server holds its page in memory.
  **One annotation decision (2026-09-20):** quote answers now derive automatically
  from reviewed speech ranges and save atomically with them; there are no independent
  quote-answer buttons or shortcuts. Timestamps, caption gaps/ellipses and turn marks
  are excluded from selection counts and quote coverage without changing raw offsets.
  Unmarked quote words are INCOMPLETE, not an explicit uncertain answer. Only a human
  `unclear` range supplies uncertainty. GET and quote import re-evaluate legacy stored
  answers from ranges without rewriting those ranges; the old answer is retained as
  `legacy_answer` when the reconciled result is saved. `import-quotes --page <page>`
  uses the same calculation (defaults to speaker_check.html beside the answer file).
  Context-only annotations cannot complete the quote, and a stale browser cannot
  override a range-derived result using the old manual answer endpoint.
  **Caption corrections (2026-09-20):** select words and choose Correct text.
  Replacements are overlays in `human_answers.json`'s `corrections` section with
  original token bounds, source hash, revision and server-appended edit history.
  A corrected phrase is selected as one anchored unit, even when word count changes;
  speaker ranges never shift. Restore original reverses an edit without removing
  history. Stale windows cannot overwrite a newer correction. Original captions and
  grade evidence remain intact; grades are not recomputed by this UI. Export with
  `scripts/pundits_text_corrections.py --answers <answers> --page <page> --out <private-output>`
  for corrected reading text and provenance. Verify with
  `test_pundits_text_corrections.py` and `check_pundits_span_ui.py`.

- P7 labelling kit: `scripts/pundits_label_kit.py windows | quotes`, with the rules for the
  people who label in `docs/PUNDITS-LABELLING-GUIDE.md`. Windows are cut only from recordings a
  person verified, by the human venue label; quotes hide the judge and its speaker label in a
  separate answer key. Every label field is written empty, and a short format is reported, never
  topped up. Proof: `.venv/bin/python scripts/test_pundits_label_kit.py`.

- Pundits verification (plan, Verification section): `bash scripts/run_tests.sh` is the
  fail-loud suite runner (globbed, exits nonzero on any failure).
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
