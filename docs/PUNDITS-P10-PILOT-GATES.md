# Verbatim Pundits: P10 gates run on the pilot (2026-10-12)

Rendered by `scripts/pundits_gate_doc.py` from the report of `scripts/pundits_gates.py`, at pundits data revision `dced184bb278`. Do not edit it by hand: re-run both scripts. The gates and their bounds are defined in [PUNDITS-PLAN.md](PUNDITS-PLAN.md), P10. Published judges: fable, gemini.

A dry run of the P10 gate report on the pilot corpus (10 people, 77 recordings), so the gates are proven before the full run. It is not the P11 document: that is rendered from the full corpus. Its `results.json` is rebuilt by the current code from that revision's grades, because the committed one predates the P5 sensitivities. Re-render: `.venv/bin/python scripts/aggregate.py --study pundits ... --transcripts <pundits data>/transcripts_blind`, then `.venv/bin/python scripts/pundits_gates.py --data <pundits data> --lean-labels <private lean file> --out <scratch>/gates.json`, then `.venv/bin/python scripts/pundits_gate_doc.py --report <scratch>/gates.json --data-revision <data sha> --withhold-lean --out <this file>`.

**Lean-split figures are withheld.** Every verdict is printed, but no estimate, interval or table split by lean. Lean labels are private, and with few people a lean-split figure next to public per-person facts can reveal who is in which group. They will be printed once the operator sets a disclosure rule for them.

## Verdicts

| Gate | Part | Verdict | Estimate | 90% interval | n | Bound |
|---|---|---|---|---|---|---|
| fable_tool_calls | Fable | PASS | 0 nonzero, 0 missing | &ndash; | 156 grades | must be 0 |
| G-search | fable, left minus right | PASS | withheld | withheld | 156 grades | &plusmn;5 |
| G-search | gemini, left minus right | PASS | withheld | withheld | 156 grades | &plusmn;5 |
| G-coverage | loss between lean groups | INCONCLUSIVE | withheld | withheld | 78 recordings | &plusmn;5 |
| G-judge-lean | fable | INCONCLUSIVE | withheld | withheld | 77 transcripts | &plusmn;3 |
| G-judge-lean | gemini | INCONCLUSIVE | withheld | withheld | 77 transcripts | &plusmn;3 |
| G-halo-lean | panel | PASS | withheld | withheld | withheld | &plusmn;3 |
| G-halo-lean | fable (raw) | PASS | withheld | withheld | withheld | &plusmn;3 |
| G-halo-lean | gemini (raw) | PASS | withheld | withheld | withheld | &plusmn;3 |
| G-drift | all | INCONCLUSIVE | did not run | &ndash; | 0 anchors scheduled | &plusmn;3 |

## Blinding: how often a judge named the speaker

`Confident` counts the judge's own `identity_confident`. `Correct` also requires the guess to name the subject.

| Judge | Blinded grades | Confident | Correct |
|---|---|---|---|
| fable | 78 | 100.0% | 100.0% |
| gemini | 78 | 100.0% | 100.0% |
| all | 156 | 100.0% | 100.0% |

At 90% correct or more the site must say that blinded means the name is removed, not that the speaker is anonymous. That applies.

## Losses (G-coverage)

A scheduled run-0 recording is lost when it has no blinded row in results.json; a cell is lost when no usable run-0 grade exists for it. a recording can be lost with every cell graded: aggregate.py drops it for an unsupported dimension or an incomplete panel (results.json partial_panel_detail names which).

### Cells by judge and mode

| Judge | Mode | Scheduled | Lost |
|---|---|---|---|
| fable | blinded | 78 | 0 |
| fable | open | 78 | 0 |
| gemini | blinded | 78 | 0 |
| gemini | open | 78 | 0 |

Excluded, not lost: astra, 40 scheduled cells, is not a published judge.

### By venue

| Venue | Scheduled | Lost |
|---|---|---|
| conversation | 33 | 0 |
| debate | 4 | 0 |
| format disputed | 4 | 0 |
| reaction | 24 | 0 |
| solo | 12 | 0 |
| unknown (never reached the board) | 1 | 1 |

### By person

| Person | Scheduled | Lost |
|---|---|---|
| ana-kasparian | 6 | 0 |
| asmongold | 12 | 1 |
| ben-shapiro | 12 | 0 |
| charlie-kirk | 5 | 0 |
| coleman-hughes | 7 | 0 |
| ezra-klein | 7 | 0 |
| hasan-piker | 8 | 0 |
| matt-walsh | 8 | 0 |
| sam-seder | 7 | 0 |
| steven-bonnell | 6 | 0 |

## Search (G-search)

Queries that name the blinded subject: 0.

| Judge | Mode | Grades | Searched |
|---|---|---|---|
| fable | blinded | 78 | 0 |
| fable | open | 78 | 0 |
| gemini | blinded | 78 | 0 |
| gemini | open | 78 | 0 |

## Venue support

Format adjustment applied: no. Why not: venue 'debate' seen 4 times, under the minimum of 8.

Recordings by venue: conversation 33, debate 4, format disputed 4, reaction 24, solo 12.

Leave one venue out, rescoring every ranked person:

| Venue dropped | Still ranked | Ranks changed | Spearman | Largest shift |
|---|---|---|---|---|
| conversation | 4 | 2 | 0.8 | 2.3 |
| debate | 9 | 0 | 1.0 | 0.6 |
| reaction | 7 | 2 | 0.964 | 2.4 |
| solo | 9 | 0 | 1.0 | 1.2 |

## Limits

- A relative test: a bias every judge shares is invisible to it. With two judges each judge's gap is measured against one other judge, so the two estimates are equal and opposite.
- Some lean groups have fewer than 10 people: a percentile cluster bootstrap is too narrow with so few clusters, so treat its intervals as optimistic.
- No drift anchors were scheduled (plan P5: 6 fixed transcripts re-graded once per block group); drift is unmeasured and must be reported as a limit.

Intervals: 90%, 20000 resamples, seed 20260914, unit person, resampled with replacement inside each lean group.
