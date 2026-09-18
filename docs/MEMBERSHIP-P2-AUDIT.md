# P2 pre-push audit: verbatim-index did not move

The membership work exists to add seven investors to the predictions board. Its
whole safety claim is that `verbatim-index.tonygwu.com` does not change at all:
same 50 names, same scores, same rendered rows. This is the evidence for that
claim, taken on 2026-09-18 with P2's three readers wired and before anything is
deployed.

Re-run any line here; none of it spends quota or touches the network except the
one live fetch, which is a GET of the published page.

## The corpus was still for the whole window

The grading loop writes continuously, so a before-and-after measured against a
live tree mixes the change under test with new grades. Both ends were
fingerprinted and compared.

```
data/transcripts_blind: 664 files sha256 862256220019f6bb5794ce2f92bf4cd6e0371595c79cf255bbbf7889ed379937
data/transcripts_open:  664 files sha256 fdc0b4aef0b9c1d8df74b560db9c995d9ac66b80690e2ef4365c3e28c84a3054
data/grades:           2260 files sha256 9efa0e1d0aed7ffcb853c707488fae223057ee5b732bd3c16e425bb0bd4f72e8
```

Identical before and after. `_raw` judge transcripts are excluded from the count,
which is why grades read 2,260 and not the 4,826 `git ls-files` reports.

One fetcher WAS running during the window: `bash scripts/fetch_loop.sh`, pid
73058, for 1h01m. It runs in **repo-3**, which owns pundits production, and
`lsof` reported **0** open files under the shared leaders data. The fingerprints
are the proof rather than that reasoning.

## The 50 were enumerated from git, not from membership.json

The artifact under test cannot be its own oracle. The roster was read out of the
tag `pre-membership-p2-2026-09-18` in the data repository.

```
from the git tag:          50 slugs
membership leaders board:  50
IDENTICAL as sets:   True
IDENTICAL in order:  True
on the board but not in the tagged roster:  none
in the tagged roster but not on the board:  none
```

## aggregate.py: two keys added, nothing else changed

`aggregate.py` from `14ba5a5`, the last commit before P2, against the wired
version, over the same corpus with `PYTHONHASHSEED=0`:

```
diagnostics keys added by P2: ['grades_off_board', 'off_board_slugs']
results.json otherwise IDENTICAL: True
leaders: 50 -> 50 | any rank or score moved: False
```

The comparison substitutes the two new keys into the old object and then asserts
whole-object equality, so it covers every leader, every interval, every
diagnostic and the unranked and unscored lists, not a chosen subset.

On the live corpus the reader removes nothing: `grades_off_board` is 0 and
`off_board_slugs` is empty, because all 50 roster slugs are on the leaders board.

## The rendered page is byte-identical

Both arms rendered from their own `results.json`, each given a `transcripts_blind`
neighbour because `build_site.py` derives the corpus path from `--results`'s
parent.

```
diff audit.pre.html audit.post.html  ->  no output
RENDER IDENTICAL: the published page does not move
```

409 KB, 50 leaders, both arms. The page reads `A roster of 50` and
`Words graded 8.8M`.

**The first attempt at this comparison was wrong and is worth recording.**
Diffing the new render against the committed `site/index.html` produced 120 diff
lines. That file is stale: it predates the og-card commits, so the diff was
measuring this change plus everybody else's. A second attempt ran the HEAD copy
of `build_site.py` out of a scratch directory and produced two spurious
differences, because the `og.png` cache-buster resolves relative to the script.
Only the third comparison, both scripts run from `scripts/` against the same
data, is controlled.

## grade.py drops nothing

Run with `--limit-per-leader 0`, so it exits before any judge is chosen and
spends nothing:

```
no membership line printed at all
--limit-per-leader 0: keeping 0 transcripts, dropping 664 across 50 leaders
```

All 664 transcripts passed the membership gate. A membership drop prints a line
naming each slug and its count; the absence of that line is the measurement.

## No writer was touched

`git -C data status --short` is empty and `git -C data diff` against the tag
reports no change to `sources/discovered.json`, `sources/aliases.json`,
`sources/repairs.json` or `roster/final.json`. That is the design rule holding:
membership decides what is READ, never what is WRITTEN. P2 changed three readers
and no writer.

## The publication floor is live and its baseline is seeded

`site/published.json` records 50. It was **seeded, not bootstrapped**, from the
live board rather than from `results.json`:

```
curl https://verbatim-index.tonygwu.com/
embedded DATA array: 50 rows, ranks 1 to 50
first three: Yann LeCun, Jeff Bezos, Tim Sweeney
last: rank 50 Marc Benioff
```

which matches `results.json` exactly. Before seeding, a real `--dry-run` printed:

```
PUBLICATION FLOOR: no previous publication recorded, so this run BOOTSTRAPS the
floor at 50 leaders and is NOT guarded. Every later run is checked against it.
```

and after seeding:

```
publication floor: 50 leaders against 50 previously published, floor 42 (15% tolerance)
```

Seeding closes the one unguarded deploy that would otherwise have followed P2.
Deleting `site/published.json` takes the bootstrap path again, so it is
reversible.

## Rollback

`git -C data tag pre-membership-p2-2026-09-18` marks the corpus. Both transcript
trees and the grades tree are tracked, so the tag is a real rollback as well as
this audit's enumeration source. P2 itself needs no data rollback, because it
wrote nothing to `data/`.

## The loop's own pipeline was run end to end, on a copy

The unit suite covers each changed script in isolation. Nothing ran the CHAIN
`grade_loop.sh` runs, and this day changed ten files in it. So the chain was run,
against a six-leader copy of the corpus in a scratch directory, with the loop's
own argv at each stage.

```
dedupe --sweep      youtube 24 transcripts / 6 leaders; sweep_retired 0,
                    orphaned_grades_removed 0, orphans_skipped_other_slug 0
qa_transcripts      24 examined, summary.generated_at_utc stamped
normalize blinded   698 substitutions, transcripts_with_zero_blind_hits []
normalize open      0 substitutions
grade.py            membership dropped nothing; --limit-per-leader 0 then
                    reported "keeping 0 transcripts, dropping 22 across 6 leaders"
aggregate           6 leaders, grades_off_board 0, grade_files_read 285
build_site          88 KB, 6 leaders, "A roster of 6", "Words graded 324k"
```

Every stage completed. `normalize` accepted the QA report that `qa_transcripts`
had just stamped, which is the P0-4b handshake, and `grade.py` reached its
`--limit-per-leader` accounting, which is past the membership gate and above the
account router.

PRODUCTION WAS NOT TOUCHED. The corpus fingerprint is byte-identical before and
after, and `git -C data status --short` is empty. `dedupe --sweep` did read the
real `transcripts_hs`, because that flag defaults to it, and retired nothing.

## What this audit does NOT cover

- **P3 and P4.** The seven are not on the roster yet and no transcript of theirs
  exists. The transcript-set comparison the plan describes, with its rule that a
  removal under the 50 must be empty or individually explained, belongs to the
  P3 audit, because P3 is the first phase that writes.
- **A deploy.** Nothing was published. The floor was exercised with `--dry-run`
  only.
- **The pundits study end to end.** It cannot be exercised from repo-0:
  `grade.py` refuses at `data-pundits is not a git checkout` and `aggregate.py`
  at the v2 contract check, both before any reader, because repo-3 owns that
  production. The scoping is guarded instead by `membership.for_study` and its
  direct test, with the readers asserted to route through it.
