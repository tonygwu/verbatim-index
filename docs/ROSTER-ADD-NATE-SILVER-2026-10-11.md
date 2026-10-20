# Nate Silver joins both boards (2026-10-11)

The operator asked for Nate Silver on the verbatim-predictions page and on the
leaderboard, with his transcripts and predictions fetched and scored the same
way as everyone else's. He is appended to the roster at rank 58 with
`boards: ["leaders", "predictions"]`, and `membership.json` names him on both.

Prepared in repo-3. The owner paths (roster, sources, transcripts) are applied
in the daemon checkout under the one-committer protocol agreed with repo-0's
session; grading and the leaders deploy run from repo-0, which owns
`grade_loop.sh` and `deploy.sh`. His predictions run from repo-3 in shared
paths.

## Decisions taken while adding him

These are judgment calls made during the work. Each can be reversed.

- **Both boards, not predictions alone.** The request says "on the
  leaderboard too", and the leaderboard is verbatim-index. He is the first
  leaders-board member who is a commentator rather than someone who runs a
  technology business. The roster's `tie_break_rules` sentence "Pure investors
  and commentators are out" still describes how the original 50 were chosen;
  the new top-level note `nate_silver_added_2026_10_11` in
  `data/roster/final.json` says so.
- **Company `Silver Bulletin`, role `Founder and writer`, sector
  `Forecasting and Media`.** Silver Bulletin is his newsletter since he left
  FiveThirtyEight in 2023. The sector is new; no code groups by sector.
- **Aliases.** `Nate Silver`, `Silver Bulletin`, `FiveThirtyEight`,
  `Five Thirty Eight`, `Nate`, `Silver`, `Bulletin`, in that order, because the
  live blinder applies aliases in file order. `538` is deliberately left out:
  in election talk it is also the number of electoral votes, and redacting it
  would remove real content.
- **The masthead still says "technology leaders"** on both sites. It already
  covered the seven investors. Changing the wording is a separate publication
  decision and is not made here.
- **His grades join the calibration pool**, so every leader's calibrated score
  may move slightly when they land, as they did when the board grew on
  2026-09-10.

## Discovery and curation

`discover_sources.py --only nate-silver` against a one-entry scratch roster,
one worker at the default 1.5 s pacing. 95 searched, 60 filtered out by the
script's own rules, 30 passing. Eight of the 30 were cut by hand before any
fetch, and the next ones in the script's ranked order took their places, so
the 14 kept are the script's ranking minus these:

```
ge8IEJbeLRE  353-minute poker livestream (Poker At The Lodge cash game)
O1mu6AguEZQ  co-guest: title names Tom Dwan
_sZU0tQkwnQ  co-guest: title names Scott Alexander
lf1rXa9q25M  NAMESAKE: 'Nate Silver Podcast' channel, 3,010 followers, a different person
Pucj-cSYvxg  NAMESAKE: same channel (seen in the 14-cap run only)
GfOmfTZw-AI  co-hosted: Risky Business, Maria Konnikova an equal co-host
87mAdHSl2bM  co-hosted: Risky Business, Maria Konnikova an equal co-host
I9U4sxrTOO4  panel: title names Galen Druke and Clare Malone
```

The namesake channel is the hazard the roster entry records: `name_in()` takes
the bare word "silver", and a "Nate Silver Podcast" channel exists that is not
him. Its description reads "The Official Podcast of Nate Silver" and its
episodes are "The Culture" and "Against The Odds".

The co-hosted Risky Business episodes are his own show and are rich in
predictions, notably "Nate and Maria's 2026 Predictions". They were cut from
the graded shelf because the auto-captions carry no speaker labels, so neither
a judge nor the extractor can tell his words from his co-host's. If they are
wanted for predictions later, they belong in `transcripts_web/`, not on the
graded shelf, and they need a speaker check first.

## Fetch, identity screen and QA, all before any judge call

`fetch_transcripts.py` on a manifest holding only his 14 rows, 2 workers at the
default 6 s interval, into scratch:

```
attempted 14, succeeded 13, failed 1   error_taxonomy {"transcripts_disabled": 1}
failed: usgbc-u-s-green-building-5watoj (Greenbuild 2013 plenary), subtitles disabled
total words 180,745; uploads 2015 to 2026
```

`identity_screen.py`: 11 pass, 2 review, 0 reject. Both reviews are the
exclusivity signal reading a non-speaker as a co-guest, and both were checked
by hand: "Newsom Is Fading" in the All-In title is a topic, and Dax Shepard is
the Armchair Expert host.

`qa_transcripts.py` with the curated glossary: 12 pass, 1 review. The review is
`domino-data-lab-9wsl2f`, flagged because the speaker never says his own name
or company in a keynote. The text is unmistakably him: it opens on the 2016
election forecast and later discusses 538 and poker.

## Blinding, measured rather than assumed

Each transcript was blinded twice, once with an empty alias list and once with
the curated one. On 6 of 13 transcripts, `Bulletin` moves from `[COMPANY]` to
`[SUBJECT]`: the same words are removed, only the label differs. That is the
known relabel defect every leader has. On 1 transcript, `Five Thirty Eight` is
one extra redaction. The curated block adds no ordinary-word damage. Inherent
to the name and company, and not reachable by curation, are the words "silver"
and "bulletin".

## The landing order, and why

`membership.json` lands FIRST. Every membership reader raises on a slug it does
not know, so a roster entry arriving before membership would break production
readers. Membership arriving first only breaks two tests,
`test_membership.py` and `test_agents_md_current_state.py`, and only in a clone
whose data checkout does not yet have the roster entry. Run
`data_sync.py pull` and they pass. Rehearsed: with the roster, sources and
transcripts applied to a contributor data clone, the whole suite passed
(`failed: 0`), and the rehearsal was reverted.

In the data checkout the apply is: roster append, a discovered.json block, an
aliases.json block (every existing block byte-identical), and
`sources_to_manifest.py` rebuilding `all.jsonl`. Rehearsed, the rebuild added
exactly his 14 rows and dropped none. Then his 13 transcripts go into
`transcripts/nate-silver/`.

## Outcome (2026-10-11)

**Leaders board.** repo-0's `grade_loop.sh` graded his 13 transcripts with all three
judges in its first cycle (+39 grades, 2,299 total) and deployed at 10:00Z. He is
rank 7 of 51: overall 69.6, 95% interval 66.6 to 72.7, 13 transcripts, high
confidence, identity recognised by the judges in 13 of 13. Data `459a9983`.

**Predictions board.** Astra extracting and Gemini verifying, as for most of the
corpus. The first pass accepted 2 of 25 verified candidates. Most rejections are the
eligibility policy as written: "slight favorite", "50/50" and a modelled percentage
are judged not committed or not falsifiable. Several candidates that both models
qualified were held by the date rule instead. Dating (astra and fable_web) confirmed
earlier dates for 8 recordings and the upload day of the ninth. Re-extracting those 9
under the corrected dates raised his accepted records from 2 to 6. One transcript,
Conversations with Tyler, was verified by Fable after three identical Gemini
failures; its two accepted records are 2028 calls and are not scored yet.

Scored at as_of 2026-10-11 (run `predictions/_experiments/nate-silver-20261011/`):
4 past due, 3 scored, all occurred, mean points +0.747. The fourth, FiveThirtyEight's
own 2014 House forecasts, is `already_public`. On 2026-10-11 that ranked him first of 46 on three
predictions, a position resting on a very small sample (see the update below). Deployed from a clean data worktree: data `370b88b1`, public `a335def`.

**Update 2026-10-12, ledger VP-40.** On the operator's choice, he got a predictions-only
supplement of 35 older recordings (23 open web transcripts, 12 YouTube recordings; 19 more
YouTube rows wait until YouTube stops refusing requests). Accepted predictions went from 6 to 18 and scored from 3 to
15. With more of his record in view, his mean points went from +0.747 to -0.064 (hit rate
0.73) and his rank from first to 29th of 46: his early lead rested on three calls. Details:
`predictions/_experiments/nate-silver-supplement-20261012/NOTES.md` in the data repository.

**Two things the operator may want to decide.** First, the eligibility policy treats
a stated probability near even, or a "favorite" call, as uncommitted. For a forecaster
whose public speech is mostly probabilities, that leaves most of his forecasts off the
board. Changing it is a policy release that affects everyone. Second, both mastheads
still say "technology leaders".
