# Annotations: the human transcript-annotation tool

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you build, serve, migrate,
verify or export an annotation session; change `scripts/annotations*.py` or the
page's JavaScript; or add a project, a mode or a checklist field.

Until 2026-10-18 (VI-39) this was three tools: `pundits_verify_page.py` and
`pundits_verify_serve.py` for the pundits P6 speaker check, and
`speaker_audit_page.py` wrapping them for the leaders and predictions boards. The
history of those tools stays in `docs/BACKLOG-RESOLVED.md` and in git under those
names.

## What the tool is

One page and one local server that a person uses to check transcripts. What the
page asks is set by the session, never by the study.

**Modes** are what a person records:

- `speakers`: who said which words. The person marks word ranges as the subject,
  someone else, or unsure. A quote's result (`attribution`) is derived from the
  ranges by the server on every save and every read; no button sets it, and the
  server refuses a direct `attribution` post with 409.
- `captions`: what was actually said. A correction is an overlay on the original
  tokens, so a change in word count never shifts a speaker range.
- `checklist`: questions about the recording, from the project's spec in
  `annotations_select.PROJECTS`. Only `pundits` has one today: subject present,
  format and political content, the P6 questions.

**Projects** say what work a transcript feeds, and each recording carries its
tags:

| Project | Study | Board | Transcripts | Quotes a person checks | Checklist |
|---|---|---|---|---|---|
| `insights` | `leaders` | `leaders` | `transcripts_open` | every evidence quote the judges cited, capped per recording, judges in turn | none |
| `predictions` | `leaders` | `predictions` | `transcripts_open` | every accepted prediction, by its exact character offsets | none |
| `pundits` | `pundits` | | `transcripts` (raw) | judge quotes that mechanical signals mark as suspect | the P6 questions |

`insights` is the leaderboard. The tag name lives in this tool only; the rest of
the code still calls the board `leaders`, and a version-1 manifest's
`study: leaders` migrates to `insights`.

Insights and predictions read the same `transcripts_open` file, so one session
can carry both. A recording built for both is ONE row with both tags and both
projects' quotes, and one set of word ranges serves both. Pundits sessions live
in the pundits data repository, which is owner-only and reads raw `transcripts/`,
whose tokens differ from `transcripts_open` for 202 of 215 P6b recordings. So a
session never mixes pundits with the other two; `serve` shows several sessions in
one interface instead.

### Decisions carried over from the pundits tool (2026-09-20, operator)

- A quote's result follows from the ranges and saves with them, atomically. Unmarked
  quote words leave the quote INCOMPLETE, never uncertain; only a human `unclear` range
  supplies uncertainty. Timestamps, caption gaps, ellipses and `>>` turn marks are not
  speech and are left out of counts and coverage without changing any offset.
- An older whole-quote answer is kept: when ranges arrive, `reconcile_quote_reviews`
  stores it as `legacy_answer`, and the page seeds ranges from it until the first save.
  Reading the file never rewrites it.
- A correction is selected as one anchored phrase, even when its word count changes.
  The browser sends the edits with the revision it saw; the server refuses a stale
  revision and appends the history itself. Restore original reverses an edit without
  removing history. Original captions and grades are never changed, and grades are not
  recomputed by this tool.
- Model suggestions are drawn dashed and need an explicit confirmation, which saves them
  with `origin: model_confirmed`; words nobody marked stay unknown.

## Sessions and storage

A session is one directory in a data checkout, never in this repository (`build`
refuses that):

- the page (`annotations.html`, or `speaker_check.html` for a migrated session);
- one transcript sidecar per recording in `<page stem>.transcripts/<slug>/<sid>.json`:
  the tokens, mark times and any model suggestions;
- the private quote key (`quote_key.json`, or `quote_check_key.json` for the
  migrated pundits session): every judge, extractor and verifier claim, kept off
  the page;
- `human_answers.json`, the answers, in the shape it has always had:
  `{labels, attribution, spans, corrections}`;
- `manifest.json`, version 2: name, projects, modes, `blind`, `transcript_dir`,
  file names, per-recording projects and transcript hashes, and for a migrated
  session `legacy_from` with its whole version-1 manifest.

Every offset is an end-exclusive index into the whitespace tokens of the
record's whole `text`, pinned by the text's sha256 and token count. The server
refuses a range or a correction whose hash differs from its sidecar.

Answers go through `annotations_store.Store`. Its one implementation,
`FileStore`, writes the whole answers file atomically under one lock; git then
carries it to the private data repository. Decided with the operator on
2026-10-18: keep git as the system of record, because every consumer reads files
and every range is pinned to a git revision; a remote store such as Supabase is a
second implementation of `Store` if labellers off this machine are ever needed.

Modes default to speakers and captions, plus checklist for pundits; `--mode` picks
them, for example `--mode captions` for a captions-only pass. A session without the
speakers mode shows no quotes, and its quotes do not hold a recording open. A
captions-only session has nothing to complete: its progress is the recordings with
corrections, it opens on the All filter, and it never reports a recording done.

The page saves to this machine only. The old Artifact `db` fallback is gone from
new pages: its `put` sent every collection but attribution to the labels
collection, so a speaker-range save there would have overwritten a recording's
labels. The published pundits Artifact
(https://claude.ai/artifact/9TEivUMn7nhrYZJhkRRnsb) and its db are untouched;
`export labels --source <export>` still reads an Artifact db export. That db was
not readable from the account that tried on 2026-10-18 (outside the Artifact's
organization), so whether it holds labels missing from git is for the owning
account to check.

## Commands

All through `.venv/bin/python scripts/annotations.py`:

| Command | Does | Writes |
|---|---|---|
| `build --data D --project P [--project P] (--keys K,K \| --checklist F) --out DIR [--mode M ...]` | a session from a data checkout; pundits adds `--grades` (suggestions and suspect quotes, so assisted) and `--drafts` (model drafts); `--cap` (insights, predictions; default 6) caps quotes per recording and project, while pundits keeps its selector's fixed 4 | page, sidecars, quote key, manifest; never the answers |
| `serve --session DIR [--session DIR ...] [--port 5001]` | serves each session at `/s/<name>/` on 127.0.0.1; `/` lists them | the answers file, one save at a time |
| `migrate --session DIR [--project P]` | adopts a session built before this tool | `manifest.json` only |
| `verify --session DIR [--expect-answers-sha256 H] [--data D]` | a JSON report; exit 1 on any failed check | nothing |
| `rebuild --session DIR` | the page again with the current template, rows and quotes carried verbatim | the page only |
| `export labels\|quotes\|spans\|corrections --session DIR --out F` | `labels` is `human_labels.json` for `pundits_pilot.py report`; `quotes --project P` splits a two-project session | the named file |
| `status --session DIR` | progress per project and mode | nothing |

`verify` checks: the answers sha256 against the expected one; every saved answer
names an id the page carries; every sidecar matches the page's hash and token
count and the manifest; every range and correction validates; a read returns the
file unchanged; each export the manifest lists (`quote_results.json`,
`human_labels.json`, `human_text_corrections.json`) is reproduced; a live server
on a free port serves the page byte for byte and the same answers; and the
answers file is byte-identical afterwards. It also reports a digest of every
sidecar, so a before and after can be compared.

Proof: `scripts/test_annotations_cli.py` (migrate, verify, rebuild, export, the
public-repo refusal), `test_annotations_page.py` (the page under node, the
checklist from its spec, project tags and filter, no Artifact fallback),
`test_annotations_serve.py` (a real socket, loopback only, mode refusals, several
sessions), `test_annotations_select.py` (quote selection, blindness, the
two-project row), `test_annotations_spans.py`, `test_annotations_corrections.py`
and `test_play_time.py`.

## The sessions on disk

| Session name | Data repo, path | Project | Answers sha256 | State |
|---|---|---|---|---|
| `insights-20260927` | leaders data, `predictions/_experiments/speaker-audit-20260927/leaders` | insights | `4a505bc4…3853` | migrated and rebuilt 2026-10-18 (data `e4a68376`): 5 recordings, 30 quote results, 37 ranges, 2 corrected recordings |
| `predictions-20260927` | leaders data, `predictions/_experiments/speaker-audit-20260927/predictions` | predictions | `e7cb1c41…b27c` | migrated and rebuilt 2026-10-18 (data `e4a68376`): 5 recordings, 9 quote results, 22 ranges, 2 corrected recordings |
| `p6b` | pundits data, `logs/p6b` | pundits | `2e2327ff…e6e3` | not yet migrated (BACKLOG.md VI-40, repo-3's lane): 239 recordings, 11 checklist labels, 6 quote results, 11 ranges, 1 corrected recording |

Both leaders-data sessions passed every `verify` check, with `--data data`, before
and after the rebuild; their answers, sidecars and keys are byte-identical to the
pre-migration files. The pundits session is repo-3's to migrate, because the
pundits data repository is owner-only. Its migration was proven on a copy on
2026-10-18 (every check passed before and after `rebuild`, and with `--data`
against repo-3's `data-pundits`); VI-40 carries the command and the expected
counts. To annotate all three at once:

```
.venv/bin/python scripts/annotations.py serve \
    --session data/predictions/_experiments/speaker-audit-20260927/leaders \
    --session data/predictions/_experiments/speaker-audit-20260927/predictions \
    --session data-pundits/logs/p6b      # once VI-40 has migrated it
```

## Rules that exist because something broke

- **Drive the page in a browser after any change to its JavaScript.** The node
  harness in `test_annotations_page.py` runs the script against a stub page with
  no layout and no click handlers. FOUND 2026-09-20: the save adapter went in as
  a module-level `store`, and `setField(store, id, f, v)` already took a parameter
  of that name, so every save died with `store.put is not a function`. `node
  --check` passed it; a browser found it in one keystroke. The suite's SHADOW
  check now refuses that shape. `scripts/check_annotations_ui.py` drives real
  drags, saves, reloads, corrections and a two-project session; it is outside the
  gate because it needs Playwright and Chromium, so a change to the page's
  JavaScript states in its commit whether it was run. It ran green on
  2026-10-18 from a scratch virtual environment with Playwright 1.64.0.
- **A running server holds its page in memory.** Rebuild the page, then restart
  only that server.
- **A session never mixes transcript directories.** Pundits ranges index raw
  `transcripts/`; `speaker_turns.py` (Astra's turns) indexes `transcripts_open`.
  Comparing the two needs the same text, so `build` refuses a mix and every
  manifest records `transcript_dir`.
- **`assisted` on a range was true for every save until 2026-10-18**, including
  the blind insights and predictions sessions. New saves set it only when the
  editor showed suggestions. The old answers are not rewritten; the manifest's
  `blind` is the truth, and `status` counts the mismatch.
- **`build` into a session that already has answers refuses before writing anything**
  when the new page would drop an answered recording or quote, when a transcript
  under saved ranges or corrections changed, or when an answered quote keeps its id
  but covers other words (a judge's quote grew). A folder that holds answers but no
  version-2 manifest is an older session: `migrate` it first. Found by the 2026-10-18 review: a pundits
  build without `--grades` into `logs/p6b` dropped all 40 quotes and the 21 quote-only
  recordings, stranding 6 quote results, 11 ranges and 1 correction, and a changed
  transcript let one later save turn a completed quote result to `stale`. The old
  builders had the same hazard. Build again with the same projects and flags;
  `--allow-off-page` keeps answers for a recording deliberately dropped from the
  checklist, and nothing overrides a changed transcript. `rebuild` never re-selects
  quotes, so it is always safe.

## Known limits

- The quote results of a pundits session describe FLAGGED quotes only; they do
  not replace the P7 random quote audit.
- An answer saved with a model draft on screen records `draft_shown` and is left
  out of calibration; an assisted range (`origin: model_confirmed`) cannot count
  as a blind audit label.
- Only one person per machine can annotate, because the server binds to
  loopback. Two independent labellers (the P7 rule) need two machines or a remote
  `Store`.
- `predictions` is the leaders study's predictions board. The pundits predictions
  pilot (`experiments/predictions-pilot-20261018/` in the pundits data) has no
  project yet; adding one is a new row in `PROJECTS`.
- A flagged pundits recording with no `video_id` now stops the build, as insights
  and predictions always did, because the page cannot link it to listen to. None
  exists in the data of 2026-10-18.
- Two sessions served together may hold the same recording; `serve` warns, and a
  range saved in one is not seen by the other. Prefer one session per recording.
