# Add Ed Zitron, Michael Burry and Steve Eisman to predictions

The operator requested these three people for Verbatim Predictions on 2026-10-21,
then explicitly requested source collection, extraction, scoring and publication.
All three belong to the predictions board only. Their slugs are `ed-zitron`,
`michael-burry` and `steve-eisman`.

## Roster integration

**Integrated into the production roster on 2026-10-22 at 04:14Z UTC** by the owner
checkout (repo-0), after public membership landed at `b778026`. Data main was
fast-forwarded onto the reviewed commit itself, `d36f3a85` (branch
`codex/repo-7-predictions-roster-additions`), so its SHA is unchanged. It was
re-checked before the merge: it changes only `roster/final.json`, appends ranks 59
to 61 with `boards: ["predictions"]`, and leaves the 58 existing rows and every
other field equal. `data_sync.py push --daemon` then regenerated the derived files
as `ed4bb658`: `predictions/index.json` lists 61 people, and `predictions/scores.json`
changed only its `inputs_sha256`, with all 917 prediction rows identical. With this
roster, `test_agents_md_current_state.py` passes 14 of 14, `test_membership.py` 70 of
70 and `test_membership_study_scope.py` 19 of 19. The leaders fetch loop keeps only
leaders-board members, so these three are not fetched for the leaderboard. The live
site has not changed: no deploy was made.

## Collected source coverage

The prepared addition contains nine source files, 41 extracted candidates and
15 accepted predictions: five for Zitron, four for Burry and six for Eisman.
Two model families must agree before acceptance; all 26 rejected candidates
remain in the private audit data. One Zitron interview produced no candidates
and remains part of the coverage record. This is a bounded collection, not a
representative sample of anyone's forecasting record.

Sources include authored essays, shareholder correspondence, a university
speech, interviews, Senate testimony and Eisman's dated 2010 Sohn presentation.
A separate Eisman interview remains excluded because its recording date was
uncertain and its fetched text duplicated the interview. Two attempts at a
blocked publisher were stopped on access challenges. No transcript was created
from a search snippet, and no access barrier was bypassed.

## Scoring and publication requirements

Scoring uses the existing policy, with an as-of date of 2026-10-22. The listing
and ranking thresholds stay unchanged. A person needs three scored predictions
to receive a ranked score. Accepted predictions can remain unscored when their
window, context or outcome evidence does not support a valid comparison.

The audit retains scoring holds for post-publication context, source attribution
truncated by the existing prompt, a prior containing later information, two
housing outcomes that used inconsistent statistical vintages, a prior and outcome
check that used different reporting deadlines, and an undated
promise to publish a post. These results are not silently repaired or counted
as misses. Roster role and organisation fields describe people currently, so
historical scoring prompts can carry a later role; this inherited limitation
is recorded rather than corrected through an unreviewed roster change.

Private records and raw model responses remain in the private data repository.
Bulk market catalogue/search responses are preserved in a local hash-verified
archive; price histories supporting published probabilities stay in private Git.
The archive is local evidence rather than a remote backup. Source and scoring
evidence is under `predictions/_experiments/*2026102*-repo7`.

Before publication, complete all admitted scoring and market calls, merge only
the new people’s summaries, regenerate the index and scores, review the concrete
combined diff, and publish with `deploy_predictions.sh` from fresh origin/main
in both repositories. A source collection or data commit alone does not confirm
a live deployment.

## Verification

Membership checks before the addition returned `58 passed, 6 failed`; after
membership and owner roster integration they returned `70 passed, 0 failed`.
The owner confirmed that existing roster rows and other fields were unchanged.
The prepared nine-source validation returned `files 9 records 41 accepted 15`,
with all 22 invariants passing. The policy suite returned `9 tests OK`, and the
scoring-date suite returned `17/17 passed`. Final publication evidence is kept
in the private `additions-publication-20261022-repo7` audit folder.
