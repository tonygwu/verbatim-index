# Corpus integrity follow-up, 2026-09-10

Written by repo-3 against `docs/CORPUS-INTEGRITY-2026-09-10.md`, which repo-2
wrote from a prediction probe over 80 transcripts. Every count there was a
floor. This document re-derives each count from the corpus, answers the four
questions the operator asked, and records a fix with its cost for each.

Nothing under `data/` was written. Every re-grade below wrote to a scratch
directory outside the repository.

## Method

Every number here comes from ONE frozen copy of the corpus, taken at
2026-09-10T07:17:14Z from the shared `data/` checkout at data commit `91356d5`
plus its 60 uncommitted files. The grading loop rewrites `data/` every few
minutes, so a before-and-after against the live tree would mix the change under
test with new grades. The snapshot held 569 transcripts, 1,988 grade files, and
a board of 40 leaders over 536 included recordings, built with
`scripts/aggregate.py` at code commit `48b0bb8`.

Verdicts use three words. CONFIRMED: repo-2's number reproduces and the
conclusion stands. REVISED: the defect is real and the number is different.
REFUTED: the claim does not hold.

| # | Defect | Verdict | repo-2 | This document | Fix | Cost |
|---|---|---|---|---|---|---|
| 1 | `declared_year` is a constant | CONFIRMED; effect under 1 point | 469 of 524 wrong | 479 of 535 wrong; true year moves a grade -0.7 points (se 0.4, n=18), a leader at most 0.2 | Year from `yt_upload_date`, "unknown" never 0 (shipped) | No re-grade needed |
| 2 | Wrong-person transcripts | REVISED upward | 15 | 31 on the board, 44 in the corpus | `scripts/wrong_person_screen.py`; withdraw 31 | 31 withdrawals, 0 quota; Bezos 7th to 2nd, Sweeney 13th to 3rd, C.C. Wei n=2 |
| 3 | Share cutoff averages a zero away | CONFIRMED | 10 recordings | 10 recordings, all 10 subject-absent | Any judge at 0 drops the recording (shipped) | Drops 10; 21 of 40 ranks move, mean 0.8 places |
| 4 | Caption looping | REVISED upward; effect under noise | 3 transcripts, worst 19.6% | 10 transcripts, worst 96.5%; collapse moves a grade +0.7 (se 0.7, n=8), a leader at most 0.3 | `collapse_paragraph_loops` in the normalizer (shipped) | 10 transcripts change; 30 short judge calls to re-grade |
| 5 | Evan Spiegel | Not a defect, as repo-2 concluded | | The one recording where he never speaks is at 0 on all three judges and is off the board | none | none |

## 1. `declared_year`: CONFIRMED as a defect, and it does not move the board

### The defect reproduces

On the snapshot, 540 of 569 transcripts carry `declared_year: 2024` and the
other 29 carry 0. All 662 manifest rows say 2024. Of the 535 transcripts that
have a `yt_upload_date`, 56 agree with their declared year and 479 do not.
The offsets run from 15 years early to 2 years late:

```
offset (upload year - declared year), count
-15:2 -13:1 -12:6 -11:11 -10:7 -9:9 -8:14 -7:9 -6:16 -5:28 -4:21 -3:30 -2:33 -1:48 +1:128 +2:116
```

The constant is born in `scripts/sources_to_manifest.py`, which turned a
missing year into 2024 with `or 2024`. The discovery workflow wrote `year: 0`
for every source. The fetcher copied the manifest year into each record while
already holding `yt_upload_date` from the same fetch. `scripts/grade.py`
printed it as "Approximate year: 2024" in both the blinded and the open prompt,
and "Approximate year: 0" for the 29 Happyscribe records, which have no date at
all.

### Does it move the score? The controlled test

A wrong year could plausibly move the insight dimension: a 2011 talk judged as
2024 reads as stale, and a 2026 talk judged as 2024 reads as prescient. Width is
not effect size, so this was measured.

Design. Three arms per transcript, all three judges, blinded mode, the
production rubric and flags, grading contract `f2b7da9b9fa2` as in the corpus:

- **disk**: the grade already in the snapshot.
- **ctrl**: a fresh call with the identical prompt. `ctrl - disk` measures
  re-run noise, which had never been measured for Fable.
- **year**: a fresh call whose prompt differs from ctrl by exactly one line,
  `Approximate year: <true year>` from `yt_upload_date`. Verified before launch
  with a unified diff of the two built prompts: one line removed, one added.

Subset. 18 transcripts, chosen with `random.Random(20260910)` from the 429
eligible ones (3-judge, on the board, dated, under 25,000 words, not in the
wrong-person set, under 2% repeated text). Two strata: 12 uploaded in 2015 or
earlier, offsets -9 to -15, and 6 uploaded in 2026, offset +2. The 29
Happyscribe records could not be tested: no field on them carries a date.

Both fresh arms ran concurrently, on the same two Fable accounts, so time of
day and account could not favour one arm. Attempted, succeeded and failed per
arm are in the table.

| Arm | Attempted | Succeeded | Failed | Taxonomy |
|---|---|---|---|---|
| ctrl | 54 | 48 | 6 | 5 `schema_validation_failed` (all Gemini, a 26-word quote against the 25 cap), 1 `cli_nonzero_exit` (Astra stream disconnect) |
| year | 54 | 51 | 3 | 1 `schema_validation_failed` (Gemini), 1 `cli_nonzero_exit` (Astra, same transcript), 1 `model_identity_mismatch` (Astra: no reasoning tokens reported, so max effort did not take effect; refused rather than written) |

No quota failures on any arm. 18 transcripts have Fable in all three arms,
16 Astra, 12 Gemini.

**Year effect**, true year minus control, per transcript, positive means the
true year raised the score:

| Judge | n | Mean | sd | se | Clarity | Insight | Technical |
|---|---|---|---|---|---|---|---|
| Fable | 18 | -1.02 | 2.82 | 0.66 | -0.8 | -0.8 | -1.4 |
| Astra | 16 | -0.31 | 1.88 | 0.47 | -0.4 | -0.4 | -0.2 |
| Gemini | 12 | -0.87 | 4.68 | 1.35 | -0.4 | -1.2 | -0.8 |
| Pooled, judge-mean per transcript | 18 | **-0.73** | 1.67 | 0.39 | | | |

t = -1.87 on 17 degrees of freedom, two-sided p about 0.08. The smallest
effect this design detects at 80% power is 1.10 points, so the test rules out
an effect of a point or more and does not rule out zero. The direction is the
same in both strata, -0.55 on the 12 uploads from 2015 or earlier and -1.09 on
the 6 from 2026, so a wrong year is not making old talks read as stale or new
talks as prescient. Telling the judge the true year makes it slightly harsher,
on every judge and every dimension, by well under a point.

**Board effect.** Substituting the 18 true-year grades into the snapshot and
rebuilding with the current `aggregate.py`: 6 of 40 leaders change rank, none
by more than one place, and no score moves more than 0.2 points. Substituting
the 18 control grades, the same prompt re-run, changes 4 ranks by up to two
places and the same 0.2 points. The year line is inside re-run noise at the
board level.

**Re-run noise, measured on the way.** Control minus the on-disk grade:

| Judge | n | Mean | Within-transcript sd | Max |
|---|---|---|---|---|
| Fable | 18 | +2.44 | 3.24 | 7.3 |
| Astra | 17 | +0.17 | 1.53 | 4.5 |
| Gemini | 13 | -0.43 | 4.30 | 8.9 |

Fable had never been measured for this. Its re-run spread, 3.2, is twice
Astra's and its MEAN moved +2.4 against grades made 1 to 4 days earlier, with a
standard error of 0.8. That is drift, not sampling, and it is larger than the
year effect this test was built to find. Astra is stable. Gemini's spread of
4.3 is nearly four times the 1.15 measured on 2026-09-07 with six transcripts.
This belongs under Known limits: the published interval treats each grade as
fixed.

### Fix

Three changes, all under `scripts/test_declared_year.py`, 16 checks:

- `sources_to_manifest.py` writes 0 for a missing year. The `or 2024` is gone.
- `fetch_transcripts.py` gains `declared_year(src, meta)`: YouTube's upload
  date first, the manifest second, 0 when neither says.
- `grade.py` prints "Approximate year: unknown" for 0 or a missing value.

Deploy without re-grading the corpus. The measured effect is under a point on
a transcript and under 0.2 on a leader, and Fable's own re-run drift is three
times larger, so a corpus mixing old-year and true-year grades is not
distinguishable from the corpus as it stands. New grades will carry the true
year; the 1,870 existing ones keep the prompt they were made with, and the
audit file records `declared_year` per record so the two can be told apart.
The alternative, re-grading 1,870 records to remove a 0.7-point offset that
sits inside the noise, costs about 700 Fable calls and buys nothing the board
can show.

## 2. Wrong-person transcripts: REVISED, 15 becomes 31 on the board

### Reproduction

All 15 of repo-2's cases reproduce from the source metadata and, more usefully,
from the judges. On every one of the 15, at least two of the three blinded
judges named the person who was actually speaking in `identity_guess`:
"Eugene Wei", "Adam Dell", "Han-Wei Shen", "Tim Sweeney, the DJ and Beats in
Space radio host". The judges cannot fix a wrong-person transcript, but they
report it, and nothing was reading the report.

### The detector

`scripts/wrong_person_screen.py` classifies every blinded `identity_guess`
against the roster:

| Class | Meaning |
|---|---|
| MATCH | the leader's full name or a company alias appears |
| SURNAME_ONLY | the surname appears, the given name and every company do not |
| NAMESAKE | the company appears only after a negation: "the DJ, not the Epic Games founder" |
| OTHER | a different person, "unknown", "no executive speaks" |

A recording is flagged when at least two judges are non-MATCH or any judge is
NAMESAKE (rule R1), or when at least two judges put subject share at 0 (R2).
Three review lists catch the rest: one judge at 0 while the mean clears the
cutoff (R5), one judge naming someone else (R6), and the bare full name
everywhere with the company nowhere (R3). It reads titles, channels and
descriptions for cross-checks and never reads transcript text, so it spends
no quota and runs in seconds.

The screen went through five versions during this work, and each version was
caught by a recording it had missed. Those are the tests:

- "Adam Dell" and "John Roese of Dell Technologies" passed, because "Dell" is
  also the company alias. A surname that is a company no longer counts as
  company evidence.
- "Clément Delangue" read as a stranger to "Clem Delangue". Given names now
  match as accent-stripped prefixes.
- "C.C. Wei" made the given name "C", which matched any capital C. Initials
  match literally.
- "Tim Sweeney, the DJ, not the Epic Games founder" matched on the company.
  A company after a negation is now a NAMESAKE verdict.
- "Chip Conley is the actual interviewee; the supplied transcript ID names
  Brian Chesky" matched on the leader's name. The person the guess OPENS with
  now decides.

### Measured performance

On the snapshot, 558 recordings with blinded grades:

| | Flagged | Hand-verified true | False positives | On the board |
|---|---|---|---|---|
| R1 identity | 26 | 26 | 0 | 24 |
| R2 absent | 20 | 20 | 0 | 6 |
| R1 or R2 | 44 | 44 | 0 | 30 |
| R5 review | 4 | 4 | 0 | 4, of which 1 not already flagged |

Every flagged recording was verified by reading its title, its channel, and
each judge's `identity_guess` and `attribution_notes`. The 14 R2 flags that
are off the board are recordings ABOUT the subject with all judges at 0,
which the share filter already drops; they are counted because they show how
often the source discovery mistakes "about" for "by".

False negatives. A seeded sample of 40 unflagged recordings held 0 misses.
The 31st on-board case, the Lenny's Podcast episode filed under Brian Chesky,
was found through the R6 review list, not through a flag, and the screen was
changed until it flagged it. The rule of three puts the miss rate among the
remaining 444 unflagged recordings at most 7.5% at 95% confidence; the point
estimate is 0. The screen run over the live corpus on 2026-09-10 (569
recordings) flags the same 44.

### The 31 on the board

Three kinds. A is the kind repo-2 found: a different person with the same
surname or the same full name. B is a recording about the subject in which the
subject never speaks, and which is on the board only because at least one
judge scored the host, a co-guest or a biographer as if they were the subject.
C is a recording in which the subject is the interviewer and the judges scored
the guest.

| Kind | Transcript | Who is speaking | Share per judge (gemini, fable, astra) | Rule | Found by |
|---|---|---|---|---|---|
| A | `cc-wei/adobe-creative-cloud-1l--yn` | Jing Wei, illustrator | 60, 65, 68 | R1 | repo-2 |
| A | `cc-wei/bankless-tik8am` | Eugene Wei | 35, 37, 36 | R1 | repo-2 |
| A | `cc-wei/danny-haiphong-k-c3ae` | Zhang Weiwei | 78, 74, 73 | R1 | repo-2 |
| A | `cc-wei/george-daniel-swpx7b` | Weivy Wei, DJ | 14, 15, 17 | R1 | repo-2 |
| A | `cc-wei/han-wei-shen-ughuv0` | Han-Wei Shen, Ohio State | 100, 100, 100 | R1 | repo-2 |
| A | `cc-wei/mit-civil-and-environmen-rwmwc3` | Wei Chen, Northwestern | 95, 95, 93 | R1 | repo-2 |
| A | `cc-wei/newton-free-library-9aab7z` | William Wei | 88, 88, 85 | R1 | repo-2 |
| A | `cc-wei/six-five-media-rmprp4` | Wei Li, Intel | 62, 60, 60 | R1 | repo-2 |
| A | `cc-wei/ted-hahs-iyee3v` | Lord Nat Wei | 68, 52, 65 | R1 | repo-2 |
| A | `cc-wei/usacm-juvcrj` | Wei Chen, Northwestern | 92, 92, 91 | R1 | repo-2 |
| A | `michael-dell/project-nanda-wj3xga` | John Roese, Dell CTO | 81, 80, 81 | R1 | repo-2 |
| A | `michael-dell/pursuit-jtc6uo` | Adam Dell | 83, 83, 80 | R1 | repo-2 |
| A | `tim-sweeney/kaput-magazin-f-r-insolv-nddwao` | Tim Sweeney, DJ | 68, 72, 76 | R1 | repo-2 |
| A | `tim-sweeney/steven-fiorillo-qvbsxi` | "Milton", a SoFi retail investor | 54, 62, 71 | R1 | this pass |
| A | `tim-sweeney/sudsy-monchik-rk2gnv` | Tim Sweeney, racquetball champion | 40, 45, 50 | R1 | this pass |
| A | `brian-armstrong/r2e2-npc-vhsmtm` | Brian Armstrong, South African academic | 100, 100, 100 | R1 | this pass |
| A | `brian-armstrong/eth-us-8d2nbg` | Vitalik Buterin | 65, 60, 62 | R1 | this pass |
| A | `lip-bu-tan/stanford-institute-for-e---xk1g` | Mario Draghi | 70, 65 | R1 | this pass |
| A | `yann-lecun/moneycontrol-ogj3eb` | Demis Hassabis; LeCun never appears | 30, 33, 35 | R1 | this pass |
| A | `arvind-krishna/preetika-rao-and-s-aishw-n-i6g5` | V. Srinivasan, a devotional talk | 58, 0, 60 | R1 | repo-2 |
| B | `jeff-bezos/hal-sparks-olznjg` | two hosts discussing Bezos | 42, 0, 0 | R2 | repo-2 |
| B | `jeff-bezos/this-week-in-startups-l2l5fn` | Jason Calacanis and co-host | 70, 0, 0 | R2 | this pass |
| B | `jeff-bezos/bigdeal-by-codie-sanchez-8jqujp` | Ethan Evans, ex-Amazon VP | 68, 0, 73 | R1 | this pass |
| B | `lip-bu-tan/oxide-computer-company--syvyy` | Bryan Cantrill and panel | 68, 0, 0 | R1 | this pass |
| B | `mark-zuckerberg/hs-sacha-baron-cohen-has-a-message-for-mark-zuc` | Sacha Baron Cohen | 65, 0, 0 | R2 | this pass |
| B | `mustafa-suleyman/madras-management-associ-shtk7f` | three panelists discussing his book | 71, 0, 0 | R2 | this pass |
| B | `tim-cook/the-compound-wl6bbk` | Josh Brown and Michael Batnick | 62, 0, 0 | R2 | this pass |
| B | `tim-cook/the-bulwark-and-the-prof-zi07-f` | Scott Galloway | 68, 0 | R5 | this pass |
| B | `demis-hassabis/metis-strategy-fu1xty` | Sebastian Mallaby, his biographer | 86, 0, 78 | R1 | this pass |
| B | `brian-chesky/lenny-s-podcast-r5-ypw` | Chip Conley | 76, 64, 68 | R1 | this pass |
| C | `marc-benioff/dws-news-1g-x70` | Sundar Pichai; Benioff is the host, 2 of 3 judges scored Pichai | 58, 32, 58 | R1 | this pass |

One more is a partial: `marc-benioff/exacttarget-9game7` has Benioff hosting
will.i.am. Fable and Astra scored Benioff at 12-13% share, Gemini scored
will.i.am at 89%. The recording stays on the board with the true share and one
of its three grades is of the wrong speaker. It is on the R6 review list.

Astra wrote, inside the Hassabis biographer grade, "This record must not be
aggregated." It was aggregated. Nothing reads the notes.

### What kinds B and C mean for the share estimate

Kind B is the same defect as section 3 seen from the other side. Gemini
reports the share of the DOMINANT speaker, not of the named subject: 42, 70,
68, 65, 71, 62 and 86 on recordings where the subject never speaks, and it
names that speaker in `identity_guess` at the same time. Astra did it twice
(the biographer, the ex-Amazon VP). Fable did it once (Chip Conley). A share
number is only evidence of the subject speaking when the judge that produced
it also believed it was scoring the subject.

### Cost of withdrawing the 31

Measured by rebuilding the snapshot board with the 31 recordings' grades
removed:

| Leader | n before | n after | Rank | Score |
|---|---|---|---|---|
| Tim Sweeney | 13 | 10 | 13 to 3 | 65.2 to 72.7 |
| C.C. Wei | 12 | 2 | 33 to 24 | 53.0 to 57.6, confidence drops to low |
| Jeff Bezos | 14 | 11 | 7 to 2 | 68.7 to 73.2 |
| Arvind Krishna | 13 | 12 | 14 to 11 | 65.0 to 67.2 |
| Tim Cook | 11 | 9 | 39 to 39 | 44.7 to 47.2 |
| Brian Armstrong | 16 | 14 | 19 to 19 | 62.6 to 60.8 |

26 of 40 leaders change rank, mean 1.6 places, maximum 10. The board keeps 40
leaders, but C.C. Wei on 2 transcripts is a placeholder, not a score.

Withdrawal is a `data/` operation and belongs to repo-0. It is one command
there: `scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json --apply`,
which retires each source to `.superseded`, the name the fetcher already
honours, and lets the next grade-loop normalize prune the derived copies and
orphan the grades. The tool refuses `--apply` in any clone but the one named in
`data/.daemon-clone`, dry-runs by default, and reports every entry as done,
skipped or failed. The manifest carries the 31 above, the 14 subject-absent
recordings already off the board, and 9 re-grades for section 4. A dry run
against the live corpus at 08:35Z: 44 would be done, 10 already superseded,
because C.C. Wei's ten had been retired in repo-0 since the snapshot, 0 not
found.

Ten of the 31 are C.C. Wei's, and the source discovery for him needs to be
redone with the company name required in the title or the description. Under
the five-transcript floor landed in 170f908 he leaves the board until then.
The screen should then run in `grade_loop.sh` after each pass, and a new R1 or
R2 flag should stop the render until someone reads it, the same way a failed
render does.

## 3. The share cutoff: CONFIRMED; replace the mean with "any judge at 0"

### Reproduction

All of repo-2's numbers reproduce on the snapshot: 558 recordings with at
least two share estimates, spread median 5, mean 6.6, p90 11, max 86; 10
recordings where judges disagree by more than 50 points; 11 recordings on the
board with at least one judge under 10, of which 10 have a judge at 0; 3
recordings off the board with a judge at or above 10. Which judge dissents is
mixed: in 6 of the 10, Fable and Astra both said 0 and Gemini said 42 to 71; in
4, Fable alone said 0.

### The 10 are not noise around a value

All 10 were hand-verified in section 2. Every one is a recording in which the
subject does not speak, and the non-zero share is a judge scoring somebody
else. So the question "what summary of the share estimates should decide" has
an answer that does not depend on statistics: a zero from a judge that read
the recording is a report that the subject is absent, and the recording should
go.

### The rules compared, on the whole snapshot

| Rule | Included | Drops vs mean | Adds vs mean | Leaders with a rank change | Mean rank change | Max | Score change, max |
|---|---|---|---|---|---|---|---|
| mean >= 10 (was published) | 536 | | | | | | |
| median >= 10 | 532 | 6 | 2 | 14 of 40 | 0.50 | 5 | 3.3 |
| mean >= 10 AND no judge at 0 | 526 | 10 | 0 | 21 of 40 | 0.80 | 5 | 4.3 |
| every judge >= 10 | 525 | 11 | 0 | 23 of 40 | 0.90 | 5 | 4.3 |

The median keeps 4 of the 10 subject-absent recordings, because on those a
second judge scored the wrong speaker too. "Every judge at or above 10" adds
`lisa-su/tbpn-8jqi1y` at 9, 10, 11, which is a real appearance at a real
borderline share, and drops it for one point. "Any judge at 0" drops exactly
the 10 verified cases and nothing else.

Under it Jeff Bezos moves from 7th to 2nd, 68.7 to 73.0, because two of his
three subject-absent recordings had scored their hosts at about 40 points and
were pulling him down. Arvind Krishna moves 14th to 9th for the same reason.
Everyone else moves by 2 places or fewer.

### Fix, shipped

`filter_unscorable` in `scripts/aggregate.py` now drops a recording when the
mean share is under the cutoff OR any judge reports 0. Three failing-then-
passing checks in `scripts/test_venue_calibration.py`: two judges at 0 with a
mean of 22.7 drop; one judge at 0 with a mean of 47 drops; 1, 80, 70 is still
a mean decision and is kept. The board changes only when repo-0 pulls.

Note that after section 2's withdrawal all 10 are gone anyway. The rule is the
guard for the next one.

## 4. Caption looping: REVISED, 3 transcripts becomes 10, and the worst is 96% repeated

### Reproduction, and why the numbers differ

repo-2's stride-40 block measure gives 16.9%, 9.4% and 2.0% on the snapshot's
blinded copies for the three named transcripts, against their 19.6%, 14.3% and
12.3%, and 20.2% on the raw copy of the worst one. The measure is fragile by
construction: it counts a 40-word block as a repeat only when an earlier block
starts at exactly the same offset modulo 40, so a loop whose period is not a
multiple of 40 words is mostly invisible to it, and the number moves with the
tokenisation.

An alignment-free measure, the share of content tokens inside any 20-word
window that already occurred earlier at any offset, with timestamps excluded,
gives:

| Transcript | Words | Repeated | Words after collapse |
|---|---|---|---|
| `sam-altman/the-economic-times-vfilis` | 64,068 | 96.5% | 1,803 |
| `sam-altman/ani-news-ulh6ww` | 27,811 | 94.4% | 1,371 |
| `dario-amodei/india-today-global-jny7oq` | 6,118 | 80.6% | 1,098 |
| `demis-hassabis/ht-india-mg8tpp` | 42,995 | 78.9% | 8,226 |
| `sam-altman/cnbc-tv18-on-bjz` | 12,206 | 50.4% | 5,897 |
| `sundar-pichai/tracy-heffernan-kogow7` | 3,603 | 45.0% | 1,972 |
| `sergey-brin/badbellabear-9uzqfz` | 5,137 | 36.2% | 3,210 |
| `brian-armstrong/eth-us-8d2nbg` | 26,851 | 24.2% | 20,235 |
| `sergey-brin/leena-buban-5ejtuf` | 7,581 | 10.2% | 6,761 |
| `reed-hastings/tim-ferriss-x6-sfu` | 11,675 | 6.1% | 10,929 |

The median over 569 transcripts is 0.0%. 114 transcripts have some repeat,
almost all under 5%, and those are cold-open teasers and sponsor reads.

The worst transcript is not 19.6% looped. It is an eight-minute interview
replayed 39 times, and every judge read all 64,068 words of it on every call.
The reading of the judges' own notes agrees: on 7 of the 8 transcripts over
20%, all three judges wrote that the recording loops, and Fable counted the
replays ("about 39 times", "about eight times with ads spliced in").

### Does it move the grade? The test

One arm, the collapsed text graded fresh by all three judges, against the
on-disk grades of the looped text. There is no fresh control of its own; the
re-run noise above stands in, with the caveat that it was measured on shorter
transcripts.

| | Attempted | Succeeded | Failed |
|---|---|---|---|
| deloop | 24 | 23 | 1 `empty_response` (Gemini, on a denied `RunCommand`) |

De-looped minus on-disk, per transcript:

| Judge | n | Mean | sd | se |
|---|---|---|---|---|
| Fable | 8 | +1.18 | 2.94 | 1.04 |
| Astra | 8 | +1.64 | 1.80 | 0.64 |
| Gemini | 5 | -1.71 | 5.14 | 2.30 |
| Pooled | 8 | +0.65 | 1.98 | 0.70 |

Fable and Astra score the collapsed text a point or so higher, which matches
their notes on the looped versions: both said they had already discounted the
replays. Gemini scores it lower on the five it completed, with the widest
spread of the three; on the two longest transcripts Gemini has no on-disk grade
at all, because those are the calls its retry budget lost. Substituting the
de-looped grades into the board moves no leader more than 0.3 points and one
rank.

So the grade does not depend on the loop, because the judges read through it.
What the loop costs is quota and reliability: every judge read all 64,068
words of the worst transcript on every call, and Gemini's empty-answer failures
concentrate on exactly these. The collapse cuts that transcript to 1,803 words.

The arm was built with an earlier version of the collapse whose residue rule
was tighter, so its inputs are 6 to 18% longer than the shipped function
produces. The shipped function was measured on the same 10 transcripts; the
table in the reproduction section is its.

### Fix, shipped

`collapse_paragraph_loops` in `scripts/normalize_transcripts.py`, 17 checks in
`scripts/test_loop_collapse.py`. It removes any repeated 20-token window at any
alignment, walks each match back over the recogniser's slips so the head of a
replay goes with it, and is gated at 5% repeat share so a teaser or a sponsor
read is measured and left in place. Without the gate it rewrote 114
transcripts to fix 10. `word_count` follows the collapsed text, because the
judge is told the length. Every transcript records `repeat_share` under
`normalization.paragraph_loop_collapse`, so the measure is visible on every
record and not only on the ones it changed.

Cost. On the next normalize in repo-0, 10 derived transcripts change. Their
existing grades describe the looped text. Withdraw those 30 grades and let the
loop re-make them: all 30 calls are on the collapsed text, so the largest is
20,235 words rather than 64,068, and the whole set is cheaper than the two
Sam Altman transcripts were the first time.

## 5. Evan Spiegel

Not re-examined beyond one check. `evan-spiegel/group-chat-news-9n0o-s`, the
episode about him in which he never speaks, is at 0 on all three judges and is
off the board, as repo-2 said in its withdrawal.

## 6. Found on the way: every Gemini grade came from one account

Two Antigravity profiles are in rotation, `~` and
`~/.agy-homes/gptwufamily`, and `grade.py` alternates them round-robin because
`agy` exposes no usage to rank by. Every one of the 567 Gemini grades in the
corpus records `profile_identity: gptwufamily@gmail.com`, 282 through the
default HOME and 285 through the other. The rotation was even, and it was
alternating between two doors into the same account.

The mechanism, verified 2026-09-10: `agy` stores its credential through the
go-keyring library in the macOS Keychain under service `gemini`, account
`antigravity`, one item per macOS user and not per HOME. The operator logged
the default profile in as tonygwu@gmail.com at 08:25:19Z (the item's creation
time); a call under the other HOME refreshed at 08:56:09Z (the item's
modification time) and every call under either HOME since reports
gptwufamily@gmail.com. A second HOME on one macOS user therefore adds no quota,
and the last refresh decides the account for both.

Fix, shipped: `gemini_identity_report()` in `grade.py` tallies the identity
each profile served from the grades a run wrote, and the run warns when more
than one profile resolved to one address. What it cannot do is separate the
accounts; that needs a second macOS user, or one account and one profile.

## What was not done

- The 29 Happyscribe transcripts have no date anywhere on the record, so the
  year test could not include them and the fix prints "unknown" for them. A
  date would have to come from the podcast feed.
- The de-loop arm has no fresh control of its own. Its re-run noise is borrowed
  from the year test's control arm, which is measured on shorter transcripts.
- Fable's re-run drift of +2.4 points against grades 1 to 4 days old was found,
  not explained. Whether it is the model, the account, or the time of day is a
  separate experiment: the same transcripts, the same account, a day apart.
- Whether the judges should be told the year AT ALL was not tested. The
  comparison was wrong year against true year, not year against no year.

## Reproduction

Everything above except the re-grades runs in seconds from a snapshot:

```
# freeze
rsync -a --exclude _raw data/grades/ SNAP/grades/
rsync -a data/transcripts_blind/ SNAP/transcripts_blind/
rsync -a data/transcripts_open/ SNAP/transcripts_open/
rsync -a data/roster/ SNAP/roster/
# baseline board
.venv/bin/python scripts/aggregate.py --grades SNAP/grades --roster SNAP/roster/final.json --out SNAP/results.json
# section 2
.venv/bin/python scripts/wrong_person_screen.py --grades SNAP/grades \
    --transcripts SNAP/transcripts_open --roster SNAP/roster/final.json --out SNAP/screen.json
# section 4, measure only
.venv/bin/python -c "import json,glob,sys; sys.path.insert(0,'scripts'); import normalize_transcripts as n; \
  print(sorted((n.collapse_paragraph_loops(json.load(open(p))['text'])[1]['repeat_share'], p) \
  for p in glob.glob('SNAP/transcripts_blind/*/*.json'))[-10:])"
```

The re-grades used `scripts/grade.py` with `--out` pointing at scratch,
`--fable-accounts .claude-b,.claude-d`, `--workers 2` per arm, `--timeout 2400`,
launched 07:20Z and finished 09:35Z. The first completed call of each judge was
checked for identity from its own telemetry: `claude-fable-5-1` on `.claude-b`
from the CLI's model usage; `gpt-6-astra` as requested, which is all `codex`
reports; and `gemini-3.8-flash-high` from the stream's init event, served by
gptwufamily@gmail.com under both profiles, per section 6.
