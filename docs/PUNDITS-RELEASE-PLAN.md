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

Three decisions are the operator's and should come before step 3: the sample size, who does
the P7 labels, and whether to publish before the P7 and P8 gates exist. Each is set out under
"Decisions for the operator", with its cost.

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

## Decisions for the operator

1. **Sample size before P9.** At 20 left and 20 right people, G-judge-lean projects to a 2.49
   half-width, and a pass needs about 2.0.
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
4. **A contradiction inside P5.** "Anchors and minimum evidence" says a recording with an
   unsupported dimension still counts toward the dimensions it supports. "Complete cells" says
   a recording needs every dimension supported. The code follows "Complete cells", and that
   costs one pilot recording today (`asmongold-tv-ks77-g`, BACKLOG). Choose one rule and
   delete the other sentence from the plan.

## What tonight's run did

This section is filled in at the end of the run (2026-10-12, before 08:26 PDT).
