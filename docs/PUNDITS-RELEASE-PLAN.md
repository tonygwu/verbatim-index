# Verbatim Pundits: from pilot board to full public release

Written 2026-10-12 by repo-2's overnight run, at code `d9e843e` and pundits data `dced184`.
The approved study plan is [PUNDITS-PLAN.md](PUNDITS-PLAN.md), and this file does not
replace it. This file answers one question: what must still happen before
pundits.tonygwu.com is a full public release rather than a pilot?

## Bottom line

**pundits.tonygwu.com is already public, as a PILOT board.** It went live on 2026-09-16 with
the operator's approval. It ranks 10 of the 39 roster people on 5 to 12 recordings each, with
two judges, Fable and Gemini, and the page says that it is a pilot.

**A full release is gated by human work, not by code or quota.** The critical path is:

1. A person checks 207 recordings for the other 29 people (P6b speaker check).
2. People label attribution windows, quotes and probes (P7).
3. repo-3 grades the full corpus (P9) and runs the probe calls (P8b to P8g).
4. Any clone runs the P10 gate report, and the operator approves P11 publication.

Six decisions are the operator's. Three should come before step 3: the sample size, who does
the P7 labels, and whether to publish before the P7 and P8 gates exist. Three should come before
P11: how much of the lean-split figures to publish, which of two contradicting P5 rules
governs a recording with an unsupported dimension, and how a reader reports an error. Each is set out under "Decisions for the
operator", with its cost.

## Where each phase stands

| Phase | Status | Evidence |
|---|---|---|
| P0 baseline | done | [PUNDITS-P0-BASELINE.md](PUNDITS-P0-BASELINE.md) |
| P1 study isolation | done | [STUDY-ISOLATION-TRACE.md](STUDY-ISOLATION-TRACE.md) |
| P2 grading contract | done | contract `3844dd2693acd471`, [PUNDITS-P2-CONTRACT.md](PUNDITS-P2-CONTRACT.md) |
| P3 judge harness | done | [PUNDITS-P3-PROBES.md](PUNDITS-P3-PROBES.md). The panel is Fable and Gemini, because Astra refuses to score political content ([PUNDITS-P8A-PILOT.md](PUNDITS-P8A-PILOT.md)). |
| P4 profile and site | done | `profiles/pundits.json`, `scripts/build_study_site.py` |
| P5 frozen rules | done, with one contradiction (decision 4 below) | `docs/PUNDITS-PLAN.md` P5 |
| P6 pilot (10 people) | **PASS** | `logs/pilot/report.json` in the pundits data repository |
| P6b the other 29 people | **INCONCLUSIVE**: 207 recordings await a person; 9 verified; 1 wrong person found | `logs/p6b/report.json` |
| P7 human labels | **not started** | no label file exists |
| P8a pilot production | done: 77 complete recordings, 308 grades, 0 refusals by the two published judges | `results.json` diagnostics |
| P8b to P8g (re-run noise, attribution windows, mirror and intervention probes) | **not run**; each needs a P7 input | |
| P9 full run | **not started**; needs P6b | |
| P10 full-corpus validation | **only the sample-size check**: a projected 2.49 half-width against the plan's 2.0 | [PUNDITS-P10-SAMPLE-SIZE.md](PUNDITS-P10-SAMPLE-SIZE.md) |
| P11 publication gate | **not started**. The pilot went live under a separate approval. | |

### Work already owed to the data

- **8 blinded grades are stale.** The blinder fix of 2026-10-11 (`8691906`) changes the
  blinded text of 4 graded recordings, so `grade.py` reports them as `stale_cache`. repo-3
  re-grades them with `--force`: two Ben Shapiro and two Matt Walsh recordings, about 8
  calls. See BACKLOG, "Verbatim Pundits".
- **The open score's interval and the resample count** are in the code since `31dffd9` and
  appear on the next pundits aggregate.
- **The next pundits deploy needs a `results.json` from the 2026-10-12 code** (the loop's next
  cycle, or `--refresh`): the deploy now checks `grade_files_sha256`, the bytes the aggregate
  read, and refuses a `results.json` that predates it.
- **The next pundits deploy needs `--first-revision-deploy`, once.** Since 2026-10-12 the
  deploy refuses when the live page's `revision.json` is missing or newer, and the live page
  predates `revision.json`.
- **P9 must schedule drift anchors.** No anchor has been scheduled yet, so G-drift has never
  run. `schedule.py build` takes `--anchors` and `--anchor-every`.

## The critical path, with owners

| Step | Owner | Size | Needs |
|---|---|---|---|
| Speaker check of 207 recordings (P6b) | the operator, on the local review page | about 7 hours at 2 minutes a recording (an estimate, not a measurement) | nothing |
| P7 attribution windows (30), quote audit (300), probe audits | two annotators and an adjudicator | about 55 hours in total, by the plan's estimate | decision 2 |
| Re-grade the 8 stale blinded grades | repo-3 | about 8 calls | nothing |
| P9 grading of 29 people at 12 recordings | repo-3 | about 1,400 calls (29 x 12 x 2 judges x 2 modes), plus drift anchors | P6b; decision 1 |
| P8b to P8g probe calls | repo-3 | about 530 calls with two judges | P7 |
| P10 gate report | any clone | quota-free | P9 |
| `docs/PUNDITS.md` with every gate result (P11 step 1) | any clone | quota-free | P10 |
| Rebuild, dry run, operator approval, deploy (P11 steps 2 to 4) | repo-3, with the operator | minutes | P11 step 1 |

The probe call count assumes the manifest with two judges instead of three:
P8b 80, P8c 120, P8d 32, P8e 96, P8f 40 and P8g 160 nominal calls.

## The P9 command

Dry-run on a copy of the pundits data at `dced184` on 2026-10-12, with no judge call:

```
.venv/bin/python scripts/schedule.py build --study pundits \
    --transcripts data-pundits/transcripts_blind --lean-labels data-pundits/private/lean_labels.json \
    --judges fable,gemini --block-size 20 --seed 20260914 \
    --graded data-pundits/grades --target-per-person 12 \
    --verified data-pundits/logs/pilot/report.json data-pundits/logs/p6b/report.json \
    --anchors ana-kasparian/the-young-turks-ltpts-,coleman-hughes/the-free-press-and-colem-qafgvv,ezra-klein/the-majority-report-w-sa-qsqw6x,hasan-piker/hasanabi-k3lzr1,matt-walsh/matt-walsh-i-hnib,sam-seder/the-majority-report-w-sa-sni00x \
    --anchor-every 4 --out data-pundits/logs/schedule/p9.jsonl
```

- **Two fixes were needed first, both made on 2026-10-12.** `--verified` took one report, so
  P9 could have scheduled only the pilot's verified set or the rest of the roster's, not both.
  The second fix: `build_schedule` refused any anchor that the top-up did not schedule, which
  rejected every already-complete recording, and those are exactly the recordings an anchor
  should be.
- **Anchors.** The six above. The dry run drew 6 complete pilot recordings by seed 20260914, one each from
  6 different people, with lean playing no part, so the list reveals nothing private.
  `--anchor-every` must leave at least 2 anchor groups in the run (blocks / anchor-every of 2
  or more), or G-drift has nothing to compare.
- **Today the command refuses, by design.** Only 9 recordings verified outside the pilot need
  grading (36 calls), which make 1 block, and `--anchor-every 4` places no anchor group in
  1 block. Until 2026-10-12 the tool then dropped the anchors without a word; now it refuses
  and says how many blocks there are. Run today's 36 calls without `--anchors` and report
  drift as a limit, or wait for P6b: at about 200 more recordings (10 or more blocks) the
  command places 2 or more anchor groups as written. Either way it schedules each person up to
  12, and lists by name and shortfall the ten people already short of material.

## Decisions for the operator

1. **Sample size before P9.** At 20 left and 20 right people, G-judge-lean projects to a 2.49
   half-width, and a pass needs about 2.0. **The roster has 13 left and 13 right people**
   (and 13 heterodox; counted from the private labels, group sizes only), and at 13 / 13 the
   projection is 3.09, wider than the bound of 3 itself
   ([PUNDITS-P10-SAMPLE-SIZE.md](PUNDITS-P10-SAMPLE-SIZE.md)). So at the current roster
   G-judge-lean is very unlikely to PASS, unless the full corpus shows less between-person
   spread than the pilot did.
   - (a) Add people: about 31 per side, against 39 in the whole roster today. Cost: more
     discovery, more speaker checks and about 50% more grading.
   - (b) Accept a likely INCONCLUSIVE and disclose it. Cost: the board cannot claim that the
     judges treat left and right alike; it can only say the test could not tell.
   - (c) Re-measure after P9. Cost: none now, but the choice of (a) comes back later at a
     higher price.
   - **Recommendation: (c), then (b) if the full-corpus projection still exceeds 2.0.** The
     pilot's ICC rests on 10 people, so its projection is wide: 1.50 to 3.06.
2. **Who labels P7** (plan decision 2). The plan recommends model pre-labels with two human
   correctors, and the page must then disclose the pre-labels.
3. **Publish before the P7 and P8 gates exist?** The plan excludes from the published corpus
   any format whose attribution gates do not PASS, so a strict reading publishes nothing
   until P7 is done.
   - (a) The full plan: P6b, P7, P8, P9, P10, then P11. Cost: about 60 hours of human labelling
     and weeks of calendar time.
   - (b) The full roster with the missing gates disclosed: P6b, P9 and P10, then publish with
     every gate that never ran marked NOT RUN on the page. Cost: a departure from the
     approved plan, and attribution errors are unmeasured.
   - (c) Keep the pilot as it is and redeploy it with tonight's page fixes. Cost: 10 people
     only.
   - **Recommendation: (b) as the next public step, then (a)'s gates as they arrive.** The
     pilot already publishes under the same limits, and the page states them.
4. **Disclosure of lean-split figures.** The lean labels are private, and every P10 lean gate
   is a figure split by lean. With few people, such a figure next to public per-person facts
   can reveal who is in which group. On the pilot, the one lost recording is Asmongold's, and
   BACKLOG names it; a lean-split loss table would then name his lean.
   - (a) Publish the group figures, as the plan intends. Cost: a reader may infer some leans.
   - (b) Publish verdicts only, and withhold the estimates, intervals and lean-group tables.
     Cost: a reader cannot check a verdict's size.
   - (c) Publish the lean labels themselves. Cost: the plan's privacy promise.
   - **Recommendation: (b) for any group under 10 people, and (a) above that.** That is the
     size at which the report also stops warning that its intervals are optimistic.
     `pundits_gate_doc.py --withhold-lean` implements (b).
5. **A contradiction inside P5.** "Anchors and minimum evidence" says a recording with an
   unsupported dimension still counts toward the dimensions it supports. "Complete cells" says
   a recording needs every dimension supported. The code follows "Complete cells", and that
   costs one pilot recording today (`asmongold-tv-ks77-g`, BACKLOG). Choose one rule and
   delete the other sentence from the plan.

6. **A corrections path.** The board scores named people, and neither this page nor the
   leaders page tells a reader, or a subject, how to report an error.
   - (a) Link "Report an error" to the public repository's issue form. Cost: corrections
     arrive in public.
   - (b) Give a contact address. Cost: an inbox to watch, and the address is public.
   - (c) No path. Cost: a subject who disputes a score has no route but the press.
   - **Recommendation: (a).** It needs no new infrastructure, and the record of a correction
     is itself evidence that the method can be checked in the open.

## What the 2026-10-12 overnight run did (repo-2)

Code and documents only: no judge call, no data write, no deploy. Every item was test-first.

**The page, for a public audience** (`scripts/build_study_site.py`):
- A real HTML document: doctype, language, UTF-8 and a viewport. The live page has none of
  them, so a phone lays it out at desktop width.
- On a phone, rank, person and the blinded score show without sideways scrolling. At 390 px
  the live page cuts the score off. Proof in a real browser:
  `scripts/check_pundits_phone_layout.py`, which passes at 320, 360, 390, 430 and 1024 px.
- Each person's venue mix (plan P5), the open score's interval, and the halo's interval and
  paired count (plan P5 "Published per person").
- A description, a canonical URL (`https://pundits.tonygwu.com/`), Open Graph and Twitter
  tags, and an inline icon.
- The data revision, in a meta tag and the footer.

- Every board recording listed under its person, linked to its source video, with venue,
  upload date and score. Metadata only: the transcript text never reaches the page.
- The Method section links the public rubric, and the code and tests.
- A social card (`site-pundits/og.png`) that says "Pilot board".
- The blinding sentence states the CORRECT-identification rate (a judge named the speaker),
  not a judge's confidence. On the pilot both are 100%. The page also states each judge's
  measured web searches, blinded and open apart: 0 of 77 and 0 of 77 for each on the pilot.
- A Sensitivity section states plan P5's three sensitivities from `results.json`: each format
  dropped in turn, the archival subject removed with calibration refitted, and the era slope.
- A recording whose format the two judges disputed (a 1-1 tie) says "format disputed" instead
  of its alphabetical tie-break label. On the pilot that is 4 of 77 recordings.

**The deploy** (`scripts/deploy_pundits.sh`): it writes `site-pundits/revision.json`, refuses
to replace a newer live page, and after publishing reads the live revision back (the P11
verification).

**The P9 schedule** (`scripts/schedule.py`): a dry run of the P9 command found two defects,
both fixed. See "The P9 command".

**The P5 sensitivities** (`aggregate.py`, pundits only; the leaders `results.json` stays
byte-identical): `venue_leave_one_out`, `archival_excluded` and `era_covariate`. On the pilot,
a recording uploaded a year later scores +0.63 points within the same person (95% interval
-2.77 to 3.49), so upload date moves nothing measurable. On the pilot, no remaining
person moves more than 2.4 points when any one format is dropped. The 4 recordings whose format
the two judges disputed stay in every run, because their label is a tie-break, not a format. Dropping Charlie Kirk refits
calibration but moves no remaining score at one decimal, which a real re-run confirms.

**The P10 gate report and the P11 document**: `scripts/pundits_gates.py` and
`scripts/pundits_gate_doc.py`. The pilot dry run is in
[PUNDITS-P10-PILOT-GATES.md](PUNDITS-P10-PILOT-GATES.md), with lean-split figures withheld.
Its verdicts:

| Gate | Pilot verdict |
|---|---|
| Fable tool calls | PASS (156 grades, 0 calls) |
| G-search | PASS (0 searches in 312 grades) |
| G-coverage | INCONCLUSIVE (1 recording of 78 lost) |
| G-judge-lean | INCONCLUSIVE |
| G-halo-lean | PASS |
| G-drift | did not run (no anchors) |

**An independent review of the night's commits**, by two read-only reviewers on other
accounts, found 20 defects (11 and 9). Nineteen were fixed the same night, each with a
failing-then-passing test:
- the gate document still printed lean group sizes under `--withhold-lean` (the pilot split
  was already public, so nothing new leaked; later renders would have);
- tied venues were dropped under their tie-break label in the leave-one-venue-out, and shown
  as known on the page; the largest pilot shift falls from 2.8 to 2.4 points;
- `names_subject` counted "Hasan Piker" as naming Mehdi Hasan, both on the roster;
- the deploy confirm compared only `data_revision`, so an earlier page at the same revision
  passed; `--first-revision-deploy` passed on any read failure; the same data revision with
  older public code passed; the fingerprint missed `transcripts_open`;
- G-drift could PASS with a judge-mode cell missing, and crashed the renderer mid-P9; the gate
  report read a stale `results.json` without noticing; the leave-one-venue-out vanished from
  the gate document without a word;
- identity and search counted drift re-grades twice, and the disclosure verdict read a
  per-grade rate where the page prints a per-recording one;
- the cluster bootstrap resampled people only, where plan P5 says people, then recordings;
- the page's search count pooled open grades, and the card counted unranked people's
  recordings;
- G-judge-lean's calibrated path was untested, and a calibration key that stopped matching
  would have compared raw scores in silence;
- the footer named the HEAD data commit while the page rendered uncommitted output; it now
  says "plus uncommitted changes" when that is so.
One is filed in BACKLOG ("Verbatim Pundits"): a file read can count as a web search.

**A second review, of the fixes themselves**, found 11 more defects, none severe, and all
were fixed with failing-then-passing tests. The four that mattered most:
- the stricter surname rule had started rejecting real namings and search queries ("Shapiro
  Daily Wire", "Likely Walsh"); a roster collision is now caught by name spans instead;
- G-drift passed a cell on 1 of its 6 scheduled anchors;
- a disclosure test could not fail;
- the staleness checks, in the gate report and in the deploy, counted grade files, and
  `grade.py --force` keeps the count while changing the bytes. Both now compare
  `grade_files_sha256`, a hash of the bytes the aggregate read.
The era interval now resamples people and then recordings, as plan P5 prescribes: on the
pilot it widens to -2.77 to 3.49 points a year.

Running the P9 command as written then showed that `schedule.py` silently dropped anchors
it could not place; it now refuses (see "The P9 command"). A fourth entry records what remains of the confirm fix: a loop render
can still race the upload, which the confirm now reports instead of passing. Two
were checked and left as they are: `venue_counts` files a tie under its label, but the leaders
study shares it, so the gate tool counts venues itself; and per-grade identity counts keep a
recording that never reached the board, because they describe judge behaviour.

Every lean test carries a warning that 4 people a side is too few for its interval. Blinded
identity was 100% confident and 100% correct, so the page's "identified" claim holds on the
pilot.
