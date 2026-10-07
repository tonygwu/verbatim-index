# Where things are: leaders board and shared components

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you look for the rubric,
the roster, board membership, coverage, grader validation, study profiles,
speaker turns or the leaders and predictions speaker-check pages.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Experiments run, and what they showed

**Can a model say who spoke each word from the caption text alone?**
(2026-09-28) Yes, when it finishes; the difference between models is whether
it finishes. Ground truth is the operator's word ranges from the first
speaker-check session (`speaker_audit_page.py`): 10 recordings chosen as the
shakiest on both boards, 2,576 labelled words, 39 quotes. Each model read a
whole transcript with the subject's name and the recording's metadata and
returned speaker turns (`scripts/speaker_segment_probe.py`), 2 repeats,
under the P3 sandbox. A run that failed both attempts scores 0 on every word
(the operator's rule); only infrastructure failures were rerun.

```
model    words r0 / r1   quotes   completed runs only   failed runs
astra    98.7% / 99.6%   78/78    99.1%                 0 of 20
opus     95.1% / 62.7%   64/78    99.5%                 5 of 20  (unparseable)
fable    62.0% / 61.1%   52/78    98.9%                 8 of 20  (5 timeouts at 40 min, 2 at the 64k output cap)
gemini   43.9% / 30.7%   30/78    99.9%                15 of 20  (truncated, empty, one persistent 5xx)
all-subject baseline 85.7%
```

Three things to inherit. Every completed run of every model scored 98.9 to
99.9%, including Gemini on marc-benioff/exacttarget-9game7, the recording
where it graded the guest as the host: an explicit segmentation step gets
right what implicit turn-finding inside grading got wrong. Every failure fell
on a long, turn-dense transcript (8,000 to 20,000 words, 100 to 700 turns),
so the output format, one JSON object per turn, is the likely cause and a
compact format or chunking is the untested fix. And the run is expensive:
Fable and Opus at max effort on those transcripts emptied the 5-hour windows
of two Claude accounts. Raw runs, top-ups and scores are under
`predictions/_experiments/speaker-audit-20260927/segmentation/` in the data
repository.

## Where things are

- Rubric and schema (the grading contract, fingerprinted into every grade):
  `.claude/skills/leader-transcript-grader/`

- Per-leader pipeline coverage: `.venv/bin/python scripts/coverage_table.py`

- The roster, 57 people: `data/roster/final.json`, with the expansion reasoning
  and the two meanings of `longform_availability` in
  `docs/ROSTER-EXPANSION-2026-09-10.md`. 50 of the 57 are on the leaders board;
  the seven appended on 2026-09-18 carry `boards: ["predictions"]` and are
  deliberately absent from it. Read `membership.json`, never the roster length,
  to answer "how many are on the board".

- Board membership: `membership.json` at the public repo root, slug to boards
  only so no person metadata leaves the private repo, read through
  `scripts/membership.py` and nothing else. 58 entries: the 48 on the roster
  with both boards, `arthur-mensch` and `yann-lecun` with `leaders` alone (taken
  off the predictions board on 2026-09-29: too few of their predictions can be
  checked yet to score fairly; rescue round 4, ledger VP-24), the seven investors
  with `predictions` alone, and `cc-wei` with none. Since 2026-09-29
  `build_predictions_site.py` reads the predictions board too, lists only people
  on it, and names the rest in its "Not listed" note; the predictions deploy
  fingerprints `membership.json` for that reason. Since P3 the seven are on the roster as well, so the roster holds 57
  and the leaders board holds 50; `cc-wei` is on neither. **THREE READERS READ IT, all study-scoped through
  `membership.for_study`:** `grade.py` drops an off-board transcript before a
  judge is chosen and reports `membership_dropped_by_slug`; `aggregate.py`
  filters `usable` and declares the remainder in an `off_board` bucket that the
  accounting sum and its failure message both name; `build_site.py` counts who is
  on the board rather than how long the roster is, and reads `leader_slug` from
  the record. Editing membership.json now MOVES THE PUBLISHED BOARD.
  The module raises on a missing file, malformed JSON, an unknown slug or a
  board name outside `BOARDS`, and never defaults to empty, because
  `data.get(slug, [])` turning an unknown slug into an empty board is the whole
  defect it exists to refuse. Every reader IS study-scoped, through one function:
  membership is leaders-only and no pundit slug is in this file, so an unscoped
  reader would raise on the first one and stop repo-3's production on its next
  cycle. That half cannot be proved end to end from repo-0, because a pundits run
  refuses at `data-pundits is not a git checkout` before any reader; see
  `scripts/test_membership_study_scope.py`, which says so and tests the rule
  directly instead. Membership decides what
  is READ, never what is WRITTEN, so no writer may consult it; an earlier draft
  that gated normalize's writes would have deleted 153 derived transcripts and
  orphaned 514 grades under `prune_orphans`' 25% ceiling.
  `scripts/publication_floor.py` stops a collapsed board publishing over the one
  that did not: the floor is the PREVIOUS PUBLISHED COUNT in `site/published.json`,
  never the roster size, which would refuse for ever from P3. Proof:
  `.venv/bin/python scripts/test_membership.py`,
  `scripts/test_membership_study_scope.py`,
  `scripts/test_aggregate_off_board_bucket.py`,
  `scripts/test_grade_membership_gate.py`, `scripts/test_deploy_floor.py`.
  Evidence that the leaders board did not move: `docs/MEMBERSHIP-P2-AUDIT.md`.

- Grader validation (reliability, bias probes): `scripts/validate_grader.py`

- Studies: this engine serves more than one study, named by `profiles/<study>.json`.
  Run a loop or script for a study with `STUDY=pundits` or `--study pundits`. With
  neither, the study is `leaders`, which reads the `data` link exactly as before. A
  study other than leaders reads only through `data-<study>`, whose checkout must
  carry a `.study` marker naming it and an origin named `verbatim-<study>-data`.
  Every stage refuses a path from another study (`scripts/study_profile.py`), and
  `.venv/bin/python scripts/test_study_isolation.py` proves it against two
  temporary checkouts. Judge scratch space is split (`grade-work-<study>`). The shared
  Gemini user-profile jail is not split and does not need to be: after P3 a contract v2
  study runs Gemini under `sandbox-exec`, which refuses `user:` profiles
  (`scripts/test_pundits_harness.py`), so only leaders ever uses that jail.

- The "who spoke" step: `scripts/speaker_turns.py`, run by `grade_loop.sh` as stage 6 for
  leaders. Decided 2026-09-28 by the operator from the segmentation experiment above: it
  is HARD-PINNED to Astra (`gpt-6-astra`, max effort, P3 sandbox, no fallback model), it
  is CHECK-ONLY (no grade, score or prediction changes), and it covers only transcripts
  whose `fetched_at_utc` is at or after `SEGMENT_SINCE_UTC`, so the existing corpus is
  not backfilled. `segment` writes `speaker_turns/<slug>/<sid>.json` beside the corpus:
  a second model failure is written as final, an infrastructure failure writes nothing
  and is retried next cycle. `check` writes `logs/speaker_check.json` and prints REVIEW
  lines for published prediction quotes, judge evidence quotes and judge shares that
  Astra's turns contradict. The prompt is pinned by `PROMPT_TEMPLATE_SHA256`; changing
  it means re-measuring against the operator's labels first. `speaker_turns/**` is an
  owner path in `data-repo-templates/leaders/ownership.json`; repo-0 must add the same
  rule to the data repository's own `ownership.json` before its first push of turns.
  Proof: `.venv/bin/python scripts/test_speaker_turns.py`.

- Speaker check for the leaders and predictions boards: `scripts/speaker_audit_page.py build
  --study leaders|predictions --data ../data --keys slug/sid,... --reasons FILE --out PAGE`. It
  reuses the pundits page, `pundits_verify_serve.py` and `import-quotes` unchanged, and only
  chooses the quotes: for leaders, the evidence quotes the judges cited, located in
  `transcripts_open` and capped per recording with the judges taking turns, most suspect judge
  first; for predictions, every ACCEPTED prediction, placed by its exact character offsets. The
  review is blind: sidecars carry no model suggestion, and every judge, extractor and verifier
  claim stays in `quote_key.json`. `manifest.json` pins the data revision, each input's sha256,
  why each recording was chosen and what the cap cut. Write the page into a private data
  checkout and serve it locally, like the pundits page. The first session, 2026-09-27, is under
  `predictions/_experiments/speaker-audit-20260927/` on repo-3's private branch. Proof:
  `scripts/test_speaker_audit_page.py`; drive the page in a browser after any JS change.
