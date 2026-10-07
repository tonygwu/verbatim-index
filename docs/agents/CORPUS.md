# The corpus: discovery, fetching and withdrawal

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you change discovery,
fetching, QA, normalize or dedupe; retire or re-grade a transcript; or act on a
wrong-person flag.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Rules that exist because something broke

- **A judge's `identity_guess` is read, not just stored.** MEASURED 2026-09-10:
  31 recordings on the board were a different person from the leader they were
  filed under, and on every one at least two judges had named the real speaker
  in `identity_guess`: "Eugene Wei", "Adam Dell", "Mario Draghi", "Sebastian
  Mallaby". Astra wrote "This record must not be aggregated" inside one grade,
  and it was aggregated. The subject-share filter cannot catch these because it
  asks whether SOMEONE is speaking. `scripts/wrong_person_screen.py` classifies
  every guess against the roster and flags a recording when two judges disagree
  with the label or two judges put share at 0; it reads no transcript text and
  spends no quota. 44 flagged, 0 false positives on hand review, 0 misses in a
  seeded sample of 40. Run it after each pass; a new flag should stop the render
  the way a failed render does. The matching traps it guards are in its test:
  "Dell" is also a company, "Clément" is "Clem", "the DJ, not the Epic Games
  founder", and a guess that opens with the real speaker and then names the
  leader.
  The screen is the DETECTOR, not the fix; the cause is under "Discovery still
  matches on the surname alone" in Known limits. Two shapes it catches that a
  simple "do the judges agree with the label" test does not: the leader can be
  the INTERVIEWER, as in `alexandr-wang/cohere-u8fjas`, where the speaker is
  Aidan Gomez and one judge wrote "interviewed by Alexandr Wang of Scale"; and
  the speaker can be a genuine NAMESAKE, as in
  `eric-schmidt/the-letterman-podcast--c4juv`, a standup comedian of that name,
  where one judge hedged "possibly Eric Schmidt". A labelled fixture of those
  cases is `scripts/test_wrong_person_regressions.py`. RUN 2026-09-11 after the
  withdrawals: 664 recordings screened, 0 flagged, 0 on the board, with 35
  recordings on the softer R3 review list that a human still reads.

- **Withdrawals go through a manifest and a guarded tool.** A retirement is a
  rename in the shared production `data/`, which only repo-0 manages. `scripts/withdraw_sources.py`
  takes a manifest such as `docs/withdrawals-2026-09-10.json`, dry-runs by
  default, refuses `--apply` unless `data/.daemon-clone` names the clone it runs
  from, and reports every entry as done, skipped or failed. `retire` renames the
  source to `.superseded`, the name the fetcher already honours, and the next
  grade-loop normalize prunes the derived copies and orphans the grades;
  `regrade` orphans the grades and keeps the source, for a transcript whose
  derived text changed under an existing grade.

- **The year the judge is told comes from the recording.** FOUND 2026-09-10:
  every manifest row said 2024 because `sources_to_manifest.py` defaulted a
  missing year with `or 2024`, and the fetcher copied it into every record
  while already holding `yt_upload_date`. 479 of 535 dated transcripts read
  "Approximate year: 2024" against uploads from 2009 to 2026, and 29 Happyscribe
  records read "Approximate year: 0". `declared_year()` in the fetcher now takes
  the upload date first, and `grade.py` prints "unknown" for 0. MEASURED with a
  controlled re-grade (docs/CORPUS-INTEGRITY-FOLLOWUP.md, section 1): the true
  year moves a grade -0.7 points (se 0.4, n=18) and a leader at most 0.2, inside
  Fable's own re-run drift, so the corpus was not re-graded. A default that
  silently invents a value is the accept-and-guess this repo forbids, and this
  one reached every judge on every grade for four days.

- **A transcript that leaves the corpus must be withdrawn, not just skipped.**
  `data/transcripts_blind` and `data/transcripts_open` are derived. `grade.py`
  grades every file it finds there and `aggregate.py` counts every grade it
  finds, so a transcript that is retired as a duplicate or rejected by QA keeps
  scoring until its derived copy AND its grades go. `normalize_transcripts.py
  --grades` does both. It refuses if the removal looks like a wrong path rather
  than a withdrawal. Found 2026-09-07: 27 withdrawn transcripts were still on
  the leaderboard, and one appearance was counted three times.

- **A retirement must be visible to EVERY fetcher.** The sweep renames a source
  to `<source_id>.json.superseded`, which `dest.exists()` does not match, so
  the fetcher re-downloaded it every cycle and the sweep retired it every
  cycle. `fetch_one` now honours that name, and reports the skip as its own
  `superseded` category rather than letting the tally stop adding up.
  The same rule arrived on the SECOND fetcher on 2026-09-10. `withdraw_sources.py`
  retires by that same rename and YouTube honoured it, but the Happy Scribe path
  never looked at the marker, so `dedupe_transcripts.py --merge` re-created the
  live copy on the next cycle. OBSERVED: four sources sat as both `<id>.json`
  and `<id>.json.superseded` at once, and the withdrawal manifest reported them
  actionable again within the hour, so the ledger read as a command repo-0 had
  failed to run rather than as a bug. The marker is now read twice, once at the
  decision stage, which records a `withdrawn` verdict with action `none`, and
  once immediately before the write, because a withdrawal can land between the
  two. `prune_orphans` re-reads for the same reason. The hold is counted as
  `withheld_already_withdrawn`, never skipped silently, because silence is how
  this hid. Guarded by `scripts/test_hs_withdrawal.py`, 9 checks, verified
  failing 4 of them against the pre-fix code.

## Experiments run, and what they showed

**Are the graded transcripts really unique?** (2026-09-07) Compared every pair
within each leader in `data/transcripts_blind` on 5-gram containment, the same
measure `dedupe_transcripts.py` uses. 23 pairs scored above the 0.40 threshold
and nothing landed in the grey band, so the split was clean. 10 duplicate
appearances across 10 leaders; Reed Hastings' Greylock talk appeared three
times and moved him 3.2 points and four ranks. `dedupe_transcripts.py` was not
at fault: it had scored every one of those pairs correctly. Two other defects
let them through, both now fixed and guarded.

**Does the wrong year move the score?** (2026-09-10) No, not enough to see on
the board. 18 transcripts spanning offsets of -15 to +2 years, three arms per
transcript and judge: the on-disk grade, a fresh control with the identical
prompt, and a fresh call whose prompt differed by exactly the year line. True
year minus control: -0.73 pooled, se 0.39, t -1.87, MDE 1.10 at 80% power;
Fable -1.0, Astra -0.3, Gemini -0.9; same sign in both upload strata. Substituting
the 18 true-year grades into the board moved no leader more than 0.2 points or
one place. Full tables in docs/CORPUS-INTEGRITY-FOLLOWUP.md.

The control arm measured Fable's re-run noise for the first time: sd 3.24
within transcript, twice Astra's 1.53, and a MEAN shift of +2.44 (se 0.76)
against grades 1 to 4 days old. That is drift, larger than the effect the test
was built to find, and it is not explained. Gemini's re-run sd was 4.30 on 13
transcripts, against 1.15 measured on six.

**Does paragraph-scale looping move the grade?** (2026-09-10) No. The 8
transcripts over 20% repeated, collapsed and re-graded by all three judges
against their on-disk grades: Fable +1.2, Astra +1.6, Gemini -1.7 on five,
pooled +0.65 (se 0.70). The judges had already read through the replays and
said so in their notes. What the loop costs is quota and Gemini's retry budget:
every judge read all 64,068 words of the worst one on every call, and the
collapse cuts it to 1,803.

## Known limits of the published score

- **Discovery still matches on the SURNAME alone, so recordings of other people
  keep entering the corpus.** This is the largest single cause behind the
  wrong-person rule above, and it is unfixed. `name_in()` in `discover_sources.py` takes
  `person["name"].split()[-1]`, lowercases it, accepts a bare substring hit in
  the title OR the channel, and then also accepts any 4-letter-or-longer token
  within a 0.85 `SequenceMatcher` ratio of it. Nothing checks the given name and
  nothing checks the company. VERIFIED 2026-09-11 by importing the live
  function: `name_in("Eugene Wei on tech and taste", {"name": "C.C. Wei"})` is
  True, and so is the racquetball champion Tim Sweeney and the standup comedian
  Eric Schmidt.

  What that cost, MEASURED 2026-09-10 (`docs/CORPUS-INTEGRITY-2026-09-10.md`,
  `docs/CORPUS-INTEGRITY-FOLLOWUP.md`): 44 wrong-person recordings in the
  corpus, 31 of them live on the published board. C.C. Wei was the worst and was
  removed from the roster over it. 14 recordings were fetched under his slug and
  only 2 mention TSMC at all; the other 12 are Jing Wei, Eugene Wei, Zhang
  Weiwei, Weivy Wei, Han-Wei Shen, Linwei Wang, Wei Chen twice, William Wei, Sha
  Xin Wei, Wei Li of Intel and Lord Nat Wei. Tim Sweeney carried a DJ, a
  racquetball champion and a SoFi retail investor. PROJECTED before the
  withdrawal, on the 40-leader board and over all 31 cases: Tim Sweeney rank 13
  to 3 and 65.2 to 72.7, Jeff Bezos 7 to 2, 26 of the 40 leaders changing rank
  (`docs/CORPUS-INTEGRITY-FOLLOWUP.md`).
  MEASURED when the sweep actually ran, 2026-09-11T05:50Z, comparing the board
  immediately before and after on the 50-leader roster: Tim Sweeney rank 17 to 4
  and 64.5 to 71.7, 46 of 50 leaders moving but 44 of them by 0.1 to 0.4 points,
  which is calibration reacting to a changed pooled distribution rather than a
  change in anyone's evidence. Lip-Bu Tan went the other way, 40 to 46 and -2.7,
  because his removed Mario Draghi transcript had scored ABOVE his own average.
  The two sets of numbers are kept apart on purpose: the first is a projection
  over a board that no longer exists, and quoting it as the outcome is the kind
  of thing this file exists to stop.

  The corpus review named two failure modes in source selection, and a third
  turned up later. SURNAME COLLISION, 13 cases, where the title names a
  different person whose surname matches: every C.C. Wei entry, Adam Dell under
  `michael-dell`, the Beats in Space DJ under `tim-sweeney`. "ABOUT the subject"
  mistaken for "BY the subject", 2 cases, such as two hosts discussing Bezos.
  And the leader NAMED IN THE TITLE but not the speaker being graded, which
  `name_in()` waves through legitimately: Jensen Huang under `lisa-su`, all
  three judges naming him; Demis Hassabis under `yann-lecun`, where LeCun never
  appears; Vitalik Buterin under `brian-armstrong`; Mario Draghi under
  `lip-bu-tan`; Riccardo Biasini of comma.ai under `george-hotz`; Sundar Pichai
  under `marc-benioff`, where Benioff is the host. The Eric Schmidt standup
  comedian is a fourth shape again, a genuine NAMESAKE carrying the full name.
  The subject-share filter catches NONE of them, because somebody is speaking
  throughout and the share comes back high: three of C.C. Wei's read 100, 94 and
  92 with maximum judge agreement.

  Not fixed here because a tighter gate rejects real material as well, and both
  sources are currently exhausted so no discovery run is pending to exercise a
  new rule. The roster expansion measured the alternative rather than arguing
  it: an identity screen wanting the full name, or the surname plus a company
  token, gives every surviving leader 83% purity or better and C.C. Wei 20%.
  Tighten `name_in()` toward that BEFORE the next discovery run, and keep
  `wrong_person_screen.py` running after every pass either way, because a screen
  that reads the judges' own `identity_guess` catches what a title cannot.

- **HappyScribe discovery admits third-person shows that YouTube discovery
  rejects, and the corpus pays for them in judge calls.** `discover()` in
  `fetch_happyscribe.py` applies the same `THIRD_PERSON_TITLE` and
  `COMMENTARY_SLUG` filters as the YouTube path, and they are weaker against
  podcast episode slugs. MEASURED on 2026-09-11, from one re-discovery run
  against the 50-name roster: four admitted recordings were commentary ABOUT the
  subject rather than the subject speaking, and they were caught only by the QA
  `subject named` screen AFTER being graded.

  ```
  hs-sacha-baron-cohen-has-a-message-for-mark-zuc   subject named 12.3 /1000 (limit 1.6)
  hs-elon-musk-begins-training-for-zuckerberg-fig   subject named 12.3 /1000
  hs-charlamagne-tha-god-torches-the-democrats-we   subject named 13.9 /1000
  hs-live-jeff-bezos-rocket-new-glenn-attempting    commentary on a launch
  ```

  The shapes that get through are possessive and narrative rather than
  interrogative: "has a message for X", "begins training for X", "live: X
  attempting". The existing patterns look for the interview forms. Cost was
  about 15 judge calls across three judges before QA withdrew them, so this is
  quota rather than correctness: no third-person recording reached the board.
  A fifth was rejected separately at `oov_rate 0.6789` for being German, which
  the language gate catches and discovery does not.

  Not fixed, because both sources are currently exhausted and no discovery run
  is pending to exercise a new pattern. Fix it before the NEXT roster expansion,
  which is when discovery runs again and the cost repeats.

## Where things are

- Wrong-person screen: `.venv/bin/python scripts/wrong_person_screen.py`. It
  replaced `identity_audit.py`, which was deleted on 2026-09-10 after both were
  run on the same corpus: the screen flagged 4 recordings, 2 of them live on the
  board, where `identity_audit` found 0. Its labelled fixture survives as
  `scripts/test_wrong_person_regressions.py`.

- Corpus-integrity findings and their re-derivation:
  `docs/CORPUS-INTEGRITY-2026-09-10.md`, `docs/CORPUS-INTEGRITY-FOLLOWUP.md`,
  and the withdrawal manifest `docs/withdrawals-2026-09-10.json`. The re-grade
  records behind the follow-up wait in
  `~/Code/misc/verbatim-index/experiments-inbox/2026-09-10-year-deloop/` for
  repo-0 to commit under `data/experiments/`; grades are data and stay out of
  this public repo. Open items and waiting decisions for that workstream:
  `docs/LEDGER-corpus-integrity.md`.
