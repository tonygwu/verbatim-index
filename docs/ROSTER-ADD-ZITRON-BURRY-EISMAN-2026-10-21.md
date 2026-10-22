# Add Ed Zitron, Michael Burry and Steve Eisman to predictions

The operator requested all three people for Verbatim Predictions on 2026-10-21,
then explicitly requested source collection, extraction, scoring and publication.
All three belong to the predictions board only. Their slugs are `ed-zitron`,
`michael-burry` and `steve-eisman`.

## Integration status

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

The text below describes the state before integration.

Public membership and a private roster branch are prepared for integration.
The production roster and live site have not changed. Public membership has 62 entries,
including 53 leaders-board members. The prepared private roster has 61 people,
with the three additions appended at ranks 59 through 61. Existing roster rows
and all other roster fields are unchanged. These counts describe the prepared
changes until the production owner integrates the private roster.

The private roster is an owner path. Repo-7 must not push it to private main or
write into the production checkout. The reviewed private branch must be
integrated by its owner after public membership lands, following the Nate Silver
precedent. The private experiment `add-zitron-burry-eisman-20261021-repo7` holds
the source manifest, execution plan and stage evidence. Its initial pilot is one
source per person; it is not a claim of representative coverage or completion.

The bounded source pilot is starting; model work and production integration are pending. No scored predictions or live
site changes are claimed by the membership addition. Before publication, apply
the existing date, attribution, two-family verification and scoring rules,
advance the scoring as-of date as required by the integration commit, resolve
and price all newly due records, regenerate through `data_sync.py`, review,
and use the guarded predictions deployment from fresh origin/main.

## Verification

`python3 scripts/test_membership.py` before adding membership: `58 passed, 6 failed`.
After membership and the prepared roster: `70 passed, 0 failed`.
A comparison to the private base confirms exactly three appended records and
byte-equivalent parsed content for all 58 existing rows and other fields.

Independent review: `ship`, no findings above nit. Membership, current-state
documentation, agreement-size, study-scope and grade-gate checks passed.
