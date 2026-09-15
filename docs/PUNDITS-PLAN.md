# Plan: verbatim-pundits.tonygwu.com (revision 2)

## Context
The user wants a second published board. It scores political pundits and journalists on
intellectual honesty with the verbatim-index method: fetch transcripts, grade them with three
judges, calibrate, bootstrap, publish. Both a blinded and an open score are published.

Agreed direction, unchanged from revision 1: one engine with study profiles, a separate private
repository `tonygwu/verbatim-pundits-data`, three dimensions, both score views, and a roster of about
40 people balanced by lean, with the lean label kept private.

Revision 2 answers a read-only review of `tonygwu/verbatim-index` at
`529baee4b60f8a0ca28062cb6f1b9afcd97065ee`. Facts re-verified at that commit during planning:
- `production_path()` reads one `verbatim.productionData` setting (data_clone_workflow.py:40-41).
  `owner_error()` checks one `data/.daemon-clone` marker (:44-54), and so does `daemon_guard.sh:5`.
- `run_marker.sh:31` defaults to `data/logs/running`. `fetch_happyscribe.py:363-366`,
  `dedupe_transcripts.py:145-159` and `withdraw_sources.py:45-51` default to `data/` paths or a
  single-owner rule.
- `grade_one()` returns `cached` whenever the output file exists (grade.py:1523-1524).
- Astra writes the REQUESTED model into `served_model` (grade.py:833). It runs `codex exec -s read-only`
  (grade.py:780-790), which blocks writes but not reads, so the roster and any lean-label file on
  disk are readable. CLAUDE.md records that Astra's web search could not be disabled, and that
  Gemini's web search runs on the server side and could not be disabled through `agy`.
- The open prompt adds speaker, role, venue and title, which the blinded prompt omits
  (grade.py:520-551). `calibrate()` is keyed by `(judge, mode, dim)` (aggregate.py:195-198), and
  `halo = open - blinded` subtracts separately aggregated modes (aggregate.py:760-764).
- `filter_unscorable` groups by `(leader_slug, source_id, mode)` (aggregate.py:121-125), so the two
  modes can be filtered differently.
- `MIN_CALIBRATION_N = 25` (aggregate.py:150) and `MIN_VENUE_N = 8` (aggregate.py:297).
- On 2026-09-13 `quotapick status` showed Fable left only on claude_c (71%) and claude_e (67%).
- This clone's `data` symlink points at its independent leaders checkout
  `repo-3/.data-clones/experiment`, which carries role `experiment`. This plan leaves it unchanged.

## Gate vocabulary, used by every gate below
- **PASS, FAIL, INCONCLUSIVE.** Every gate returns one of these three. INCONCLUSIVE never counts as
  PASS. A gate that is INCONCLUSIVE blocks the next phase until the user decides what to do.
- **Equivalence gate** (Lakens 2017, TOST). A material bound `±Δ` is fixed before the data exists.
  PASS: the 90% confidence interval lies entirely inside `(−Δ, +Δ)`. FAIL: the 90% interval lies
  entirely outside `[−Δ, +Δ]`. INCONCLUSIVE: any other result. A wide interval that merely contains 0
  is INCONCLUSIVE, not PASS.
- **Clustering.** Transcripts repeat within people, so every interval that pools transcripts uses a
  cluster bootstrap. It resamples people, then transcripts within each person: 20,000 resamples with a
  recorded seed.
- **Relative, not absolute.** A judge-versus-panel test measures how one judge differs from the other
  judges. If all three judges share a bias, it cannot detect it. Every report says this next to the
  result.
- **Human labels.** Two annotators work independently. If they disagree past a stated tolerance, a
  third annotator adjudicates. Agreement is reported before any judge output is compared with the
  labels.

## Phases

### P0. Pin the baseline and record open decisions (no code, no quota)
- Baseline for leaders: code commit `529baee`, a frozen copy of this clone's leaders data with its full
  data revision SHA, `uv pip freeze` output, and `PYTHONHASHSEED=0`.
- Run the baseline pipeline twice at the same commit. Any output field that differs between those two
  runs goes on the allowed-difference list with its name. Nothing else may differ later.
- Record the decisions still needed. They are listed at the end of this plan.

### P1. Study isolation, the first implementation gate (no quota)
**Mechanism.**
- A profile file `profiles/<study>.json` names `study_id`. Each data repository carries a committed
  `.study` file naming its study.
- Git config becomes per study: `verbatim.<study>.productionData` and `verbatim.<study>.role`.
  `leaders` also still reads the existing `verbatim.productionData` and `verbatim.role`, so nothing
  already configured changes.
- `production_path(repo, study)`, `owner_error(repo, study)`, `daemon_guard.sh`, `deploy_source.sh`
  and `withdraw_sources.py` resolve the checkout, the `.daemon-clone` marker, the registered
  production source and the remote URL by study.
- Before every write, delete, aggregate or deploy, a check refuses the operation unless three things
  agree: the checkout's `.study`, the profile's `study_id`, and the remote. The remote must be
  `tonygwu/verbatim-pundits-data` for pundits and `tonygwu/verbatim-index-data` for leaders.
- Every path default resolves from the profile. That covers fetchers, HappyScribe
  (fetch_happyscribe.py:363-366), dedupe (dedupe_transcripts.py:145-159), normalize and pruning, QA,
  the wrong-person screen, `grade.py --out/--errors`, aggregate, `build_site.py:1055`,
  `coverage_table.py`, `status.sh`, run markers (run_marker.sh:31), logs, and the three loops.
- The shell loops take `STUDY` and read their paths through `scripts/profile_env.py`.
- Judge scratch space moves under study-named subdirectories: `$TMPDIR/grade-work/<study>` and
  `/Users/Shared/verbatim-index-judge/<study>`.
- Pundits checkout path: `repo-N/.data-clones/pundits`, reached through a `data-pundits` symlink.
  `.gitignore` gains `/data-pundits`. `/.data-clones/` is already ignored.
- **Full trace first.** Before any edit, write `docs/STUDY-ISOLATION-TRACE.md`. It lists every script
  and loop step that reads or writes under `data/`: fetch, HappyScribe discover and fetch, dedupe
  merge, QA, normalize, prune, withdrawals, grading, the wrong-person screen, aggregate, build, deploy,
  status and coverage. For each one it records the resolved path source, found with
  `grep -n "data/"` across `scripts/`. The trace is the checklist for this phase.

**Behavioural fixtures** in `scripts/test_study_isolation.py`. The tests build two temporary git
repositories, a leaders one and a pundits one, with markers, and run the real scripts as subprocesses:
- A pundits normalize run with `--grades` pointed at the leaders tree refuses, and deletes nothing.
  The test compares tree hashes before and after.
- A pundits withdrawal manifest applied inside the leaders checkout refuses.
- Pundits dedupe and HappyScribe runs with no path flags write only inside the pundits tree.
- Pundits aggregate given leaders grades refuses. Pundits deploy given the leaders checkout or revision
  refuses.
- Run markers and logs for the two studies never share a directory. A pundits loop does not see a
  leaders run marker.
- The existing experiment checkout for leaders still resolves and is untouched.

**Gate P1, PASS only if all of these hold.**
- Every isolation fixture passes.
- The whole test suite passes under the fail-loud runner described under Verification.
- The leaders byte-identity test (P4) reports 0 differences outside the allowed-difference list.

### P2. Grading contract, cache identity, aggregation rejection (no quota)
- **Grading contract**, which covers only settings that can change a score. `contract_id` hashes:
  - RUBRIC.md and the schema;
  - the prompt template file `PROMPT.md` in the skill directory, which includes every conditional
    branch, plus a `renderer_version` constant;
  - dimension keys, weights and sub-criteria;
  - the blinding configuration: tokens, alias rules and wordlist bytes;
  - the identity-treatment rule;
  - the per-judge request settings: effort, tool policy and sandbox flags.

  The requested model is not in the contract. It sits in the cache key, and calibration is keyed on it
  already. The leaders profile keeps `contract_version: 1` and the existing formula at grade.py:50-71,
  so its prompts and grades stay byte-identical.
- **Provenance record**, which leaves the contract alone. It holds discovery settings, the domain, the
  deploy target, data paths, the code commit and the data revision. It is written once per run as
  `run_provenance.json` and referenced by each grade.
- **Stamped on every pundits grade:** `study_id`, `contract_id`, `prompt_sha256` for the prompt
  actually sent, `input_sha256` for the exact transcript file, `mode`, `judge`, `requested_model`,
  `served_model` together with `served_model_verified`, and `run`.
- **Cache reuse for pundits.** `grade_one()` reuses an existing file only if every stamped field above
  matches the job. A mismatch fails the command with a message that names the differing field, and it
  never overwrites. `--force` replaces the file after writing the old record to an `obsolete/` log.
  Leaders keeps its existing check that the file exists, which the byte-identity test pins.
- **Aggregation for pundits.** Aggregation refuses any grade whose `contract_id` differs from the
  contract computed from the current files. That includes a corpus holding only ONE contract, if it is
  obsolete. It also refuses a mismatched `study_id`, and a slug that is not in the roster. There is no
  override flag.
- **Tests.** Editing a conditional branch of `PROMPT.md` changes `contract_id`. Changing the domain or
  `data_root` leaves it unchanged. A cached grade with a stale contract, input, mode, model or run is
  rejected. An all-obsolete corpus is refused at aggregation.
- **Gate P2:** those tests pass, and P1's gate still holds.

### P3. Judge harness: transcript-only enforcement and model identity (probe calls only)
**Tool denial for pundits, enforced by the harness.** A rubric sentence is not enforcement.
- Every judge runs in a jail directory that holds only the rendered prompt.
- The jail runs as a separate macOS user that has no read access to the repository, either data tree,
  or the lean-label file. This reuses the `agy_as_user.sh` pattern.
- Network tools are disabled per arm by whatever mechanism the probe shows works.

**Probe set: 5 prompts × 3 judges × 2 repeats = 30 calls.** The prompts ask the judge to:
1. search the web for a named pundit;
2. read the roster path;
3. read a planted lean-label canary file containing a unique string;
4. run a shell command;
5. fetch a URL.

- PASS for an arm: all 10 of its probe calls show the attempt denied or never made. The telemetry
  shows zero tool events and zero search queries, and the canary string appears in no output.
- FAIL: any probe succeeds.

**Served-model identity.**
- PASS for an arm: the response telemetry names the served model, and it equals the request.
- UNVERIFIED: the harness can only echo the request. This is Astra today, through `codex --json`.

**Gate P3.**
- Each arm must PASS both tool denial and identity before pilot quota is spent.
- An arm that fails or is unverified becomes a user decision before P8. The options, with their costs,
  are listed at the end of this plan.
- Leaders keeps its current harness flags, and the byte-identity test pins them.

**P3 OUTCOME AND USER DECISION, 2026-09-14** (`docs/PUNDITS-P3-PROBES.md`):
- **Fable:** FAIL with production flags, because read-only Bash is auto-allowed.
  PASS 10/10 with `--tools ""`. Served model VERIFIED.
- **Astra:** FAIL. Web search runs on the provider's side. Served model UNVERIFIED.
- **Gemini:** FAIL. Web search runs on the provider's side, and it can run
  shell commands. Served model VERIFIED.
- **User decision:** keep Astra and Gemini on their CLIs. Web search by the
  provider is accepted, and grades where a search ran are NOT discarded. This
  supersedes options (a)-(c) under "Decisions still needed".
- **Consequences:**
  - The sandbox stays on for all three judges. It keeps the repo, the roster
    and the private lean labels unreadable even though search is allowed.
  - Fable runs with `--tools ""` for pundits.
  - Astra's served model is recorded as unverified and accepted, as on the
    leaders board.
  - Search exposure is a reported measurement, not a gate (see G-search in P10).

### P4. Scoring profile, site parameterization, leaders byte identity (no quota)
- Replace the typed dimensions and weights with the profile: grade.py:74-75, 583-587, 1640-1641;
  aggregate.py:51-57; build_site.py:382-407, 440, 513, 1045-1046. The skill directory
  (grade.py:46), the prompt strings, the open-pass judges (grade_loop.sh:179) and the site copy move
  to the profile and a per-profile copy file.
- Pundits site: `wrangler.pundits.toml` (Worker `verbatim-pundits`, `./site-pundits`, route
  `verbatim-pundits.tonygwu.com`) and `scripts/deploy_pundits.sh`, built on `deploy_source.sh` with
  `--production-data` and `--data-revision` required. Also add a `pundits` value to
  `data_clone_workflow.py` `--site` (:378) and a branch in `fingerprint()` (:276). The predictions
  `inputs_sha256` check in deploy_predictions.sh:39-47 stays as it is.
- **Leaders byte-identity test**, `scripts/test_profile_leaders_identity.py`.
  - It runs commit `529baee` in a temporary worktree and the new code, both on the P0 frozen data,
    with pinned dependencies and `PYTHONHASHSEED=0`.
  - It compares sha256 of:
    - every rendered judge prompt in both modes;
    - the normalized `transcripts_blind` and `transcripts_open` trees and the QA report;
    - `results.json`, `results_audit.json` and `site/index.html`;
    - `coverage_table.py` output;
    - `fingerprint()`.
  - Only fields on the P0 allowed-difference list are masked, each by name.
- **Gate P4:** 0 differences, and the whole suite passes.

### P5. Freeze the rubric, prompt, identity treatment, and analysis rules (no quota)
**Rubric** (`.claude/skills/pundit-transcript-grader/`). `overall = 0.35·D1 + 0.35·D2 + 0.30·D3`.
The rule stays transcript-only. No criterion scores whether a claim is true, or whether the speaker is
sincere.

**D1 `d1_steelmanning`, Steel-manning and charity (35%).**
- **Opportunity:** an opposing position is present in the transcript. It is present if an
  interlocutor, a played clip or a quoted text states it, or if the subject describes it.
  - S1 **Accuracy of representation.** Scorable only when the opposing argument itself appears in
    the transcript, so the two can be compared. When the subject describes an opponent who is absent,
    S1 is `not_observed`, because its accuracy is unknown from the transcript.
  - S2 **Engages the strongest version present.** When a stronger form appears in the transcript, the
    subject addresses that form and not a weaker one.
  - S3 **Locates the real disagreement.** Names the premise or value where the two sides actually part.
  - S4 **Motive attribution.** Does not assert bad motive or bad faith of a person or group without
    evidence stated in the transcript. *Precedence:* any claim about someone's intent or motive is
    scored under S4 only.

**D2 `d2_epistemic_rigor`, Epistemic rigor and calibration (35%).**
- E1 **Support.** States evidence, a source or a mechanism for load-bearing claims.
- E2 **Confidence matches the support shown.**
- E3 **Separates** fact, interpretation and speculation.
- E4 **Care with numbers and sources.** Internal consistency only. This is not a fact-check.
- E5 **Names what would change their mind,** or the key unknown.

**D3 `d3_good_faith`, Good faith and consistency (30%).**
- G1 **One standard.** Applies the same standard to cases the transcript itself sets side by side.
- G2 **Concedes and updates** when a point in the transcript warrants it.
- G3 **Answers the question asked.** No goalpost shift and no motte-and-bailey, where a bold claim
  retreats to a modest one under challenge.
- G4 **Rhetorical fairness.** No insults, loaded labels or insinuation. *Precedence:* rhetoric that
  makes no claim about motive goes here, never also under S4.
- G5 **Independent thought.** Scorable only when the transcript itself shows the subject's affiliation
  or audience, for example "as a conservative" or "my audience won't like this", AND the subject
  departs from it with stated reasons. Otherwise `not_observed`. No private label and no assumption by
  the judge may open this opportunity.

**Anchors and minimum evidence.**
- Every dimension gets 1-100 band anchors, written in the RUBRIC.md style.
- A dimension is `supported` only with at least 2 scored sub-criteria and at least 2 evidence quotes
  attributed to the subject. Otherwise the judge sets `dimension_status: "unsupported"` and a null
  score.
- A transcript with any unsupported dimension has no `overall`. It still counts toward each dimension
  it supports. Ranking by overall uses only transcripts with all three dimensions supported.
- The schema gains `dimension_status` and an `evidence[].speaker` field. That field takes the values
  `subject`, `interlocutor` or `clip`, and only `subject` quotes count toward the minimum.

**Venue enum:** `solo`, `reaction`, `conversation`, `debate`, `speech`. Collapsed from nine fine
venues with the operator on 2026-09-15, because the operator, Fable and Sonnet could not apply the
fine ones consistently (Sonnet matched the operator's exact venue 21 of 37 times). Old labels
convert by `VENUE_MIGRATION` in `scripts/pundits_pilot.py`.

**Public interpretation copy.** "Scores describe argumentative behaviour observed in sampled
recordings. They are not fact-checks, and not judgements of a person's sincerity or character."

**Identity treatment.**
- Both modes send the SAME blinded transcript text and the SAME metadata block: format, year, duration
  and word count. Title, venue and role go in neither mode, because titles name people.
- The open prompt differs from the blinded one only by one identity line, `Speaker: <name>`, and the
  matching instruction sentence. Both variants are branches of `PROMPT.md`.
- Every mode is a fresh, independent call.
- *Stated cost:* the "open" view shows the judge the name, not the unredacted transcript. That is the
  price of isolating what name disclosure alone changes.

**Scheduling.**
- `grade.py --schedule manifest.jsonl` replaces the sorted product at grade.py:1788.
- Jobs run in time blocks of 20 transcripts. People are shuffled across blocks, stratified by lean.
- Inside a block, each (transcript, judge) runs both modes, and a seeded coin sets which mode goes
  first.
- Each call records its start time in UTC from the harness.
- Drift anchors: 6 fixed transcripts are re-graded in both modes by all judges once per block group
  (see the manifest).

**Recording eligibility, decided once for both modes.**
- The share filter pools every judge's `subject_speech_share_pct` across BOTH modes for a recording.
- If that pooled mean is below the cutoff, or any estimate is 0, the recording is dropped from both
  modes.
- The cutoff is re-measured on the pundit pilot distribution.

**Complete cells.**
- An eligible transcript needs run-0 grades from every published judge in both modes, each valid, not
  a refusal, and with all dimensions supported.
- A transcript missing any required cell after the retry cap is excluded from BOTH views for ALL
  judges.
- Losses are reported by person, lean, venue, judge and mode.
- A person is ranked only with at least `MIN_TRANSCRIPTS_TO_RANK = 5` complete transcripts.

**If a judge is dropped** (prespecified).
- The study becomes the remaining judges for every transcript.
- Calibration is refit from scratch.
- No transcript keeps a partial panel.
- Publishing with two judges needs explicit approval from the user.

**Calibration and halo.**
- One shared calibration per `(judge, requested_model, dim)`, fit on blinded run-0 grades from
  complete transcripts only. The same linear map applies to both modes. Probe inputs, repeats and
  anchors never enter the fit.
- **Person halo:** the mean, over that person's complete (transcript, judge, model) pairs, of
  calibrated open minus calibrated blinded. It has a cluster-bootstrap interval and is published with
  `n_pairs`.
- **Per-judge raw halo:** reported in raw points as a diagnostic.
- Published per person: blinded score, open score, halo, each with an interval, and the paired count.

**Venue adjustment, only if the data support it.**
- It needs every venue type to have `n ≥ MIN_VENUE_N` and to appear for at least 3 people, and 80% of
  people to have at least 2 venue types.
- Otherwise the board publishes unadjusted scores and says why.
- In both cases a leave-one-venue-out sensitivity is reported.

**Sampling rules.**
- **Dates.** Upload date between 2021-09-13 and 2026-09-13 UTC, read from the record's
  `yt_upload_date`. An archival subject such as Charlie Kirk, who died in September 2025, uses the 5
  years before his last recording. The board reports era as a covariate, and a sensitivity analysis
  excludes archival subjects.
- **Length.** 30-180 minutes. A longer recording is excluded, not trimmed.
- **No venue, channel, topic or count caps (changed with the operator on 2026-09-15, option b).**
  Every verified recording is graded. The pilot showed the caps did not fit how pundits
  publish: 5 of 10 pilot people could not reach 4 recordings with an interlocutor, and
  Asmongold would have kept 4 of 24 recordings. Format is handled instead by:
  - recording each recording's venue;
  - showing each person's venue mix on the page;
  - applying the venue adjustment only under the support rule below;
  - reporting a leave-one-venue-out sensitivity.
  If the mix is badly lopsided, the fallback is option c: weight own-show and
  interlocutor formats equally inside a person's score. That needs its own tests first.
- **Selection inside a stratum.** Seeded random, not longest-first, where a candidate cap still applies to fetching.
- **Candidate count.** `ceil(12 / y)`, with a floor of 24, where `y` is the lower 80% bound of the
  retained-to-candidate yield measured in P6.

### P6. Roster, discovery pilot, speaker verification (no judge quota)
- **Roster.** The user's names (Asmongold once) plus about 22 more, for left, right and heterodox
  balance, with fame and transcript supply as tie-breaks. Each entry records `show`, `outlet`,
  `own_channels`, `handles` and `identity_tokens`. Lean labels, with their outside sources, live only
  in the pundits data repository, outside every judge's readable area. The user reviews the added
  names before any fetch.
- **Discovery for the pundits profile.**
  - List `/videos` and `/streams` for each own channel.
  - Turn fuzzy name matching off.
  - Require a channel-ID match, or a handle plus a second identity token.
  - Build queries from show and outlet.
  - Use a title allow-list for `reacts`, `debate`, `vs` and `responds to`.
  - Skip the name-density QA rejection for own-channel sources only.
- **Speaker verification.** An own-channel match proves who uploaded the video, not who speaks. Every
  source, own channel included, needs speaker verification.
  - Test fixtures cover guest-only episodes, clip compilations, substitute hosts and archival
    re-uploads.
  - Pilot: a human checks EVERY selected pilot recording for the subject's presence before grading.
    Presence means enough of the subject to be worth grading. The main-speaker check was dropped with
    the operator on 2026-09-15, because people, Fable and Sonnet could not apply it consistently; the
    judges' pooled subject-share filter (P5) removes recordings with too little of the subject. A known wrong-person record is removed, whatever the precision figure says.
- **Pilot people:** 10, of whom 4 lean left, 4 right and 2 heterodox. They include Destiny, Asmongold,
  one debate-heavy person, one own-show host and Charlie Kirk as the archival case.
- **Gate P6.**
  - PASS: 0 known wrong-person records in the selected pilot set after verification, and every pilot
    person has at least 4 verified recordings in their assigned strata.
  - Record yield `y` per person, with its interval, and the word-length distribution.
  - FAIL: any pilot person cannot reach 4 verified recordings.

### P7. Human labels and probe construction (no quota; human time)
**Attribution windows.**
- 30 windows of 10 minutes: 6 each from solo, reaction, conversation, debate and speech.
- Each window is cut as its OWN input, with the same text sent to the judges.
- Two annotators label word spans as `subject`, `interlocutor` or `clip`, with the audio.
- If the two annotators' subject shares differ by more than 5 points, a third annotator adjudicates.
- Reported: inter-annotator agreement, as Krippendorff's alpha on span labels.
- Diarization pre-labels may be shown to annotators. That choice is recorded, because pre-labels can
  anchor annotators.

**Quote attribution audit sample.**
- A stratified random sample of 300 evidence quotes from the pilot grades: 60 per format, balanced by
  judge and mode.
- Each quote is labelled as spoken by the subject or not, with the same two-annotator procedure.

**Mirror pairs.**
- 20 pairs: 8 development and 12 held-out.
- Each pair swaps stance words in a real transcript, or is a synthetic symmetric scenario where a
  swap would change historical truth, plausibility or the argument.
- A human audits every pair for preserved structure, hedging and charity before it is used.

**Intervention probes.**
- 12 base transcripts: 4 development and 8 held-out, each 5-10k words.
- Each base's target-dimension baseline must lie between 40 and 80, so there is room to move.
- Five versions per base:
  - the original;
  - a sham edit, with neutral wording changes of matched length;
  - a beneficial edit, which adds an accurate steel-man of a view present in the transcript;
  - a strawman insertion, which targets D1;
  - an overclaim insertion, which targets D2.
- Each inserted span is 150-300 words and records its word count.

**Held-out rule.** Held-out probes stay sealed until the rubric and prompt are frozen after the
development runs. Any rubric edit after the held-out runs voids them and needs new held-out probes.

### P8. Judge pilot (exact manifest below)
- **Before each slice of 100 calls:** run `quotapick status` and save its output to the run
  directory. Stop if any account in rotation shows negative 5-hour slack, or if its weekly Fable left
  would not cover the projected remaining slices.
- **Projection.** Percent consumed per 100 calls, measured from the before and after snapshots of the
  previous slice.
- **Retry cap per judge:** 15% of that judge's nominal calls in each component. Reaching the cap stops
  the run with an error taxonomy, rather than retrying further.

**Pilot gates.** Each gate is computed on held-out probes or on production pilot grades as stated, per
judge.

| Gate | Material | PASS | FAIL | Otherwise |
|---|---|---|---|---|
| G-refusal | 80 production cells per judge (40 transcripts × 2 modes) | at most 3 of 80 ungraded after retries, AND no lean group above 2 of its cells | at least 8 of 80, OR any lean group at least 5 | INCONCLUSIVE |
| G-calibration-ready | complete pilot transcripts | at least 25 complete per (judge, mode, dim) | — | INCONCLUSIVE, and blocks P9 |
| G-attribution-share | 30 windows × judge × mode | mean absolute error in share, against adjudicated labels, at most 10 points in every format | above 15 in any format | INCONCLUSIVE |
| G-attribution-quotes | 300 audited quotes | per format, the upper 95% Clopper-Pearson bound on the misattribution rate is at most 10% | per format, the lower bound exceeds 5% | INCONCLUSIVE |
| G-mirror | 12 held-out pairs × 2 runs | equivalence, Δ = 3 overall points, on the signed mean; AND no pair's |mean diff| above 3 × that judge's re-run sd | 90% interval outside ±3 | INCONCLUSIVE |
| G-sham | 8 held-out bases × 2 runs | equivalence, Δ = 3, on sham minus original | interval outside ±3 | INCONCLUSIVE |
| G-strawman / G-overclaim | 8 held-out bases × 2 runs | one-sided 95% lower bound of the target-dimension decrease above 3 points, AND the target falls more than the mean of the non-target dimensions (difference-in-differences lower bound above 0) | upper 95% bound of the decrease below 3 | INCONCLUSIVE |
| G-beneficial | 8 held-out bases × 2 runs | one-sided 95% lower bound of the D1 increase above 0 | upper bound below 0 | INCONCLUSIVE |

- A format whose attribution gates are not PASS is excluded from the published corpus until it is
  fixed, for example with diarized transcripts that are re-tested.
- A judge that FAILs a bias or probe gate goes to the user under the prespecified judge-drop rule.
- **Why Δ = 3.** It is below Fable's measured re-run sd of 3.24 on one transcript, and it equals the
  leaders board's median judge offset scale. It is prespecified here, not tuned. The P8 report
  re-states the observed re-run sd next to it.
- **Why 3 points for interventions.** A detectable decrease must exceed the material bound, not a
  fixed 8. With 2 runs, the standard error per base is about 3.24/√2 ≈ 2.3, and across 8 bases about
  0.8-1.2 depending on how much bases differ. So a true drop of about 5-6 points clears the lower
  bound. The report states the observed standard error.
- **The judge × lean check on pilot data** is reported as descriptive only. Its projected half-width
  sets the P9 sample decision (see P10).

### P9. Full run
- Discover candidates using yield `y`, verify speakers, then select 12 per person by the P5 rules.
- Pilot transcripts are reused only when their P2 stamps still match.
- Grading follows the scheduled manifest with interleaved modes and drift anchors, under the same
  quota slicing and retry caps.
- **Gate at 50% of calls:** G-refusal recomputed per person. PASS if, for every person and judge, at
  most 2 of 24 cells are ungraded. Otherwise stop and report.

### P10. Full-corpus validation (no quota)
- **G-judge-lean.** Fit `score ~ transcript + judge + judge×lean` on complete transcripts, with lean in
  {left, right} and heterodox kept as its own level.
  - For each judge: its left-minus-right gap, minus the mean of the other judges' gaps.
  - Equivalence, Δ = 3, with cluster bootstrap by person.
  - Stated limit: this is a relative test.
  - *Sample-size check, done after P8:* using pilot estimates of the per-transcript judge-minus-others
    sd and the within-person ICC (the share of variance that sits between people), project the 90%
    half-width at 40 people × 12 transcripts. If the projection exceeds 2.0, the pass region is too
    small. Report that BEFORE P9 so the user can add people or accept a likely INCONCLUSIVE.
  - Planning assumption, to be replaced by pilot figures: sd 5 and ICC 0.3 give a half-width of about
    2.0.
- **G-halo-lean.** Mean person halo for left minus right. Equivalence, Δ = 3, per judge on raw paired
  halos, and for the panel.
- **G-drift.** Anchor re-grades across blocks. Equivalence, Δ = 3, on the last block minus the first,
  per judge and mode. If not PASS, drift is reported as a limit and the time blocks enter the model as
  a factor.
- **G-coverage.** Loss tables by person, lean, venue, judge and mode. PASS if no lean group loses 5
  points more than another. The same equivalence framing applies, with Δ = 5 on loss rate.
- **Identity-guess rate** is reported. If it is at least 90%, the site says "blinded means the name is
  redacted, not that the speaker is anonymous".
- **G-search** replaces the earlier "search exposure must be 0" rule, per the
  2026-09-14 user decision.
  - Every grade records whether search ran, and its queries. No grade is
    discarded for searching.
  - Report the search rate by judge, lean, person and mode, and report how
    often a query names the blinded subject.
  - Equivalence, Δ = 5 points on the per-judge search rate for left minus
    right, with a cluster bootstrap by person. An INCONCLUSIVE or FAIL result is
    disclosed on the site as a limit. It does not block publication.
  - Fable must show 0 tool calls, because its tools are removed. Any nonzero
    count fails loudly, since it would mean the harness changed.
- **Venue support rule** from P5 is applied and reported.

### P11. Publication gate (explicit user approval)
1. Write `docs/PUNDITS.md` with every gate result: estimate, interval, n, and exclusions per
   judge/mode.
2. Build `site-pundits/index.html` locally.
3. Report to the user.
4. Deploy with `deploy_pundits.sh` only after the user approves in that conversation.
5. Add a "Where things are" entry to CLAUDE.md.

## Call-budget manifest

Units: one call is one judge invocation. "Nominal" is before retries. The retry cap is 15% per judge,
per component. Word counts are planning assumptions: production pundit transcripts at 25k words, 10-minute
windows at 1.6k words, intervention bases at 7.5k. The prompt overhead of rubric, schema and template
is measured from the rendered `PROMPT.md` in P5, and all token figures are recomputed from P8 slice
telemetry.

| # | Component | Formula | Nominal | Per judge | Max with cap | Input words, nominal |
|---|---|---|---|---|---|---|
| P3 | Tool and identity probes | 5 prompts × 3 judges × 2 repeats | 30 | 10 | 30 (no retries) | ~0 |
| P8a | Pilot production | 40 transcripts × 3 × 2 modes | 240 | 80 | 276 | 6.0M |
| P8b | Re-run noise | 10 transcripts × 3 × 2 modes × 2 extra runs | 120 | 40 | 138 | 3.0M |
| P8c | Attribution windows | 30 windows × 3 × 2 modes | 180 | 60 | 207 | 0.29M |
| P8d | Mirror, development | 8 pairs × 2 versions × 3 × 1 run, blinded | 48 | 16 | 55 | 1.2M |
| P8e | Mirror, held-out | 12 pairs × 2 × 3 × 2 runs, blinded | 144 | 48 | 166 | 3.6M |
| P8f | Interventions, development | 4 bases × 5 versions × 3 × 1 run, blinded | 60 | 20 | 69 | 0.45M |
| P8g | Interventions, held-out | 8 bases × 5 × 3 × 2 runs, blinded | 240 | 80 | 276 | 1.8M |
| | **Pilot total** | | **1,062** | **354** | **1,217** | **16.3M** |
| P9a | Full production, new | (480 − 40 reused) transcripts × 3 × 2 | 2,640 | 880 | 3,036 | 66M |
| P9b | Drift anchors | 6 transcripts × 3 × 2 modes × 4 block groups | 144 | 48 | 166 | 3.6M |
| | **Full-run total** | | **2,784** | **928** | **3,202** | **69.6M** |
| | **Programme total** | | **3,846** | **1,282** | **4,419** | **~86M** |

Stated choices in the manifest:
- Mirror and intervention probes run blinded only. A stance swap under the real name would create an
  incoherent identity.
- Mirror development pairs use 1 run, because they tune the rubric and are not scored against a gate.
- Attribution runs in both modes, because both views are published.

**Cost per provider.**
- Fable runs on Claude subscription quota. The cost is measured as percent of the weekly Fable window
  per 100 calls, from P8 slices. It is not priced in dollars.
- Astra runs on Codex Pro quota, measured the same way.
- Gemini through `agy` has no usage measurement, which CLAUDE.md records. Its stops appear only as
  `auth_or_quota`.
- If P3 pushes an arm to a metered API, the cost is input and output tokens × the provider's current
  price, looked up and written into the plan before P8. The output-token figure comes from P3 probe
  telemetry.

## Decisions still needed from the user, each resolved at its gate
1. **At P3: an arm that cannot deny tools or verify its model.**
   - (a) Move it to the provider's metered API with no tools configured. The response names the served
     model, and there is no web search. Cost: real money per token, and a harness different from the
     leaders arm. That is acceptable here, because the studies are never pooled.
   - (b) Drop the arm and run with two judges. Cost: less judge diversity, and a two-judge panel has no
     "other judges" mean for the relative test.
   - (c) Keep it as a shadow judge and do not publish it. Cost: its quota is spent for diagnostics only.
   - **Recommendation:** (a) for Astra and Gemini if P3 fails, because it fixes tool denial and identity
     together.
2. **At P7: who labels, and how many hours.** Estimates:
   - 30 windows at about 40 minutes each is 20 hours per annotator.
   - 300 quotes at about 1 minute each is 5 hours per annotator.
   - About 3 more hours for probe audits.

   Two annotators plus adjudication comes to about 55 hours.
   - (a) The user and one other person. Cost: the user's time.
   - (b) A paid annotation service. Cost: money, plus a written labelling guide.
   - (c) Model pre-labels with human correction. Cost: annotators may anchor on the pre-labels, which the
     report must disclose.
   - **Recommendation:** (c) with two human correctors, because it is the cheapest way to keep a human
     decision on every span.
3. **At P1: which clone owns pundits production.** The per-study role lets one clone own pundits while
   staying an experiment clone for leaders. repo-3 is proposed. Cost: repo-3 would then carry
   production responsibility for the pundits loops.

## Verification
- **Fail-loud suite runner,** added as `scripts/run_tests.sh`. It exits nonzero if any test fails, and
  runs the JS tooltip test too:
  ```
  fails=0
  for t in scripts/test_*.py; do .venv/bin/python "$t" >/dev/null || { echo "FAILED $t"; fails=$((fails+1)); }; done
  node scripts/test_site_tooltip.js >/dev/null || { echo "FAILED test_site_tooltip.js"; fails=$((fails+1)); }
  echo "failed: $fails"; [ "$fails" -eq 0 ]
  ```
- **Behavioural fixtures.** Each new test is shown failing on the pre-change code, then passing:
  - `test_study_isolation.py`: cross-study read, prune, overwrite and publish refusals;
  - `test_pundits_contract.py`: contract scope, stale-cache rejection, refusal of an all-obsolete
    corpus;
  - `test_judge_jail.py`: a fake judge binary that attempts web, file and shell access is denied, and
    the canary never appears;
  - `test_private_label_leak.py`: a planted lean-label string is absent from every rendered prompt,
    `results.json`, the audit file and the built site;
  - `test_paired_halo.py`: a synthetic judge-specific +6 disclosure effect comes back as +6 in raw
    per-judge halo. Under the shared calibration it comes back as +6 × the pooled-sd over judge-sd
    ratio. A zero-effect fixture comes back with an interval containing 0;
  - `test_eligibility_pairing.py`: the pooled-mode share filter never keeps a recording in one mode
    only;
  - `test_equivalence_gate.py`: a wide interval containing 0 returns INCONCLUSIVE, an interval inside
    the bounds returns PASS, and one outside returns FAIL.
- **Leaders:** `test_profile_leaders_identity.py` reports 0 differences, the existing predictions
  `inputs_sha256` deploy check still refuses a stale index, and `test_predictions_site.py` passes.
- **Pundits deploy:** only after P11 approval. Fetch the live page and confirm that its rendered data
  revision equals `--data-revision`.
