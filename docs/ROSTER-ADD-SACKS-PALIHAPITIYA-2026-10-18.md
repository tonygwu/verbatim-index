# David Sacks and Chamath Palihapitiya join the leaders board (2026-10-18)

The operator asked for both on the leaderboard, "despite them not being tech
CEOs right now", with their transcripts fetched and graded the same way as
everyone else's. Both were already on the roster (ranks 54 and 53) and on the
predictions board since 2026-09-18; `membership.json` now names each on
`["leaders", "predictions"]`. BACKLOG item VI-14 carried the plan; VI-5 was
closed on the way.

Prepared in repo-2 under the one-committer protocol the Nate Silver precedent
used (`docs/ROSTER-ADD-NATE-SILVER-2026-10-11.md`): the owner paths were
prepared in repo-2's contributor data clone and applied into the daemon
checkout, with repo-0's session's written agreement to write nothing there
meanwhile. Grading ran from repo-2 on prepaid API credit (Fable) and on the
Astra and Gemini subscriptions, and the grade files were applied into the
daemon checkout, from which repo-0 aggregated, pushed and deployed (Outcome).

## Decisions taken while adding them

Each can be reversed.

- **Both boards.** The request names the leaderboard. They are the second and
  third leaders-board members chosen outside `tie_break_rules`' "Pure
  investors and commentators are out", after Nate Silver; the roster note
  `sacks_palihapitiya_added_2026_10_18` says so.
- **Company strings stay accurate: `Social Capital` and `Craft Ventures`.**
  The roster rationales asked for this to be revisited before promotion
  because the production blinder redacts the bare parts of a company name.
  Measured on the kept transcripts (see Blinding): 157 bare ordinary-word
  redactions for Chamath, 6 for Sacks. There is no accurate alternative name
  for either firm, and production blinding is kept byte-identical on purpose
  (a blinding change makes new grades incomparable with the corpus), so the
  cost is recorded rather than fixed. Same class as Nate Silver's inherent
  "silver" and "bulletin".
- **The merged alias blocks stay.** Blinding each transcript twice, with an
  empty alias list and with the current one, gave the same redaction count in
  every one of the 21 transcripts: the alias block only moves the label from
  `[COMPANY]` to `[SUBJECT]`. Restoring the curated blocks would change
  nothing and the manifest rebuild re-adds the words.
- **Three ASR name forms were added as aliases, not repairs.** `chamat` and
  `chamathie` (Chamath) and `sax` (Sacks) each survived blinding once in the
  kept set; with them 0 name variants survive. `sources/repairs.json` was the
  natural place, but `sources_to_manifest.py` rewrites that file from
  discovery (`repair_pairs: 0`) and would drop a hand-added repair on the next
  rebuild, while it merges `aliases.json` (rehearsed on copies: `all.jsonl`,
  `aliases.json` and `repairs.json` all unchanged by the rebuild). Filed as a
  backlog item.
- **Roles stay as filed.** David Sacks has held a US government AI and crypto
  role since 2025; the roster role is the one the shelf was built under, and
  the board grades the speech, not the title.
- **Credit grades join the corpus.** `grade.py --credit-production` admits the
  study's `grades/` directory for `--fable-pool` runs, by the operator's
  decision, on the CI-11 day-1 evidence (credit minus production -0.62
  points, 95% CI -1.7 to +0.47, n 34; Spearman 0.939). Every such record names
  `harness: "quotapick run"` and its pool, and `aggregate.py` reports the
  per-judge harness mix in `diagnostics.judge_harness`.

## Curation

No discovery run was needed: `transcripts_web/` already held 14 YouTube
records for each (fetched 2026-09-19 for the predictions board), byte-for-byte
the graded shelf's schema. The precedent cut co-hosted, co-guest and panel
recordings because auto-captions carry no speaker labels, so a judge would
grade every word as the subject's. Cut by hand, from titles, descriptions and
the text:

```
david-sacks
  all-in-podcast-kcmmoz     a tariff debate: the title names Larry Summers and Ezra Klein
  all-in-podcast-lbb-rq     All-In E2, co-hosted with Jason Calacanis and Chamath
  american-moment-yjhavh    gala excerpts: J.D. Vance, Sacks, Steve Bannon, Blake Masters
  orricktotalaccess-yxqyau  a three-person panel per its description
chamath-palihapitiya
  khosla-ventures-tzpya9    co-keynote with Vinod Khosla
  waterloo-engineering-aoznmm  co-keynote with Vinod Khosla
  this-week-in-startups-3ymq-y  E776: the Samsung NEXT president's own interview
                            fills the recording from about 55% on (checked in the text)
```

Then `dedupe_transcripts.py --sweep` retired `axios-qly04q` as the same
appearance as `axios-mci6v9` (containment 0.985: the edited and the full cut of
one Axios conversation). Kept: 10 for david-sacks, 10 for chamath-palihapitiya,
both above the rank floor of 5. The 4 chamath `web-*` records stay
predictions-only, as the Nate Silver supplement did. Each cut row keeps its
`<sid>.json.superseded` marker on the shelf (gitignored) so no fetcher pulls it
back, and stays in `transcripts_web/` for predictions.

## Identity screen and QA, before any judge call

`identity_screen.py` on the kept set: 12 pass, 9 review, 0 reject. Every
review is the exclusivity signal reading a topic (Silicon Valley, First
Principles, Wharton Private Equity, Joe Biden, Growth Stocks) or the
interviewer (Oren Zeev, Dave Levy, Elad Gil, Kara Nortman) as a co-guest; each
was checked by hand against the description and the opening of the text, the
same shape as the precedent's two reviews.

`qa_transcripts.py` with the alias glossary: 6 pass, 15 review, 0 reject. Every
review is "subject surname never appears" or "subject company never appears":
ASR never spells Palihapitiya, and a keynote speaker does not say his own name
or firm. Both slugs clear the 10-usable floor.

## Blinding, measured rather than assumed

Blinded with the production blinder, with the real alias list and with an
empty one, on all 21 pre-sweep transcripts. Redaction counts were identical in
every transcript between the two arms; only the label differs. The inherent
cost of the company names, counted as bare lowercase occurrences in the
original text that the blinded text no longer carries:

```
chamath-palihapitiya   social 63   capital 94   (157 across 11 transcripts)
david-sacks            craft 4     ventures 2   (6 across 10 transcripts)
```

Name variants surviving in the blinded text before the alias additions:
`chamat` and `chamathie` once each (icon-kcwbys), `sax` once ("David sax",
anthony-pompliano-l7zxa5); "goldman sachs" is left alone, correctly. After the
additions, 0 survive.

## The landing order

1. `membership.json` first, on public main (every membership reader raises on
   a slug it does not know; these two were already known, so no reader could
   break either way). `test_membership.py`'s SEVEN became PREDICTIONS_ONLY, the
   five still on predictions alone; MAP.md and SCORING.md say the leaders
   board holds 53.
2. `grade.py`: `--fable-pool` takes a comma list through `credit_run.run`
   (VI-5) and `--credit-production` admits `data/grades`.
3. In the daemon checkout: roster boards, note and rationales; alias blocks;
   the 20 curated transcripts; then the sweep, QA and both normalize passes
   with `grade_loop.sh`'s exact flags.
4. Grading from repo-2's data clone (same inputs), applied into the daemon
   checkout: Fable blinded on pools `anthropic_api_a,anthropic_api_b`
   (`--timeout 1800`, 6 workers; pools c, d and e were empty), Astra and Gemini
   blinded (`--timeout 2400`, 8 workers), then the open pass on 2 per leader.
5. Aggregate, build_site, wrong_person_screen; commit; `data_sync.py push
   --daemon`; deploy.

`speaker_turns.py` does not cover these transcripts: their `fetched_at_utc`
(2026-09-19) is before `SEGMENT_SINCE_UTC` (2026-09-28).

## Outcome (2026-10-18)

**Grading.** Fable on credit pools a and b: 697 jobs attempted across two runs
(677 cached), 20 billed calls, $41.63 (pool a $154.08 to $123.49, pool b $16.83
to $5.78; median elapsed 406 s). The first run ended 691 ok / 6
`cli_nonzero_exit`: those six were my own doing, a `pkill -f 'quotapick run'`
meant for a mistakenly launched open pass (it would have graded 174 jobs across
52 leaders, because production runs with `OPEN_PER_LEADER=0`; killed 20 s in,
no open grade written) that also cut six blinded calls; the second run graded
them 697/697/0. Every Fable record names `harness: "quotapick run"` and its
pool; the raw response of the first grade was read in full: served
`anthropic_api_b`, `claude-fable-5-1` for every model seen, effort max, credit,
API key. Astra and Gemini: 1394 attempted / 1387 ok / 6 `empty_response`, all
six on other leaders' long-standing Gemini gaps that the idempotent pass
retried; plus 1 `schema_validation_failed` (chamath-palihapitiya/axios-mci6v9,
Gemini: an evidence quote of 26 words against the cap of 25), which
`aggregate.py` excludes, so Chamath has 9 valid Gemini grades. Gemini identity
verified per record (`served_model_verified`, `profile_identity_verified`).

**Board.** Aggregated with `grade_loop.sh`'s invocation: 53 scored, 2,359 grade
files read, 2,278 used, 42 excluded for validation errors;
`diagnostics.judge_harness`: fable production 702 + quotapick run 20, astra
906, gemini 650. David Sacks: rank 25 of 53, overall 60.6, 95% interval 56.1 to
65.3, 10 transcripts, high confidence. Chamath Palihapitiya: rank 51 of 53,
overall 48.2, 95% interval 45.9 to 50.8, 10 transcripts, high confidence. Nate
Silver moved from 69.6 to 69.5 as the calibration pool grew. Of the 20 Fable
credit grades, 17 were served on `anthropic_api_a` and 3 on `anthropic_api_b`;
repo-0 asserted on every one that the judge model requested, served and seen
is `claude-fable-5-1` at effort max on an API key. `wrong_person_screen.py`:
0 flagged (6 of the 20 in review with no flag). `speaker_turns.py check`: 13
segmented transcripts, neither person among them, 0 disagreements.

**Deployed** by repo-0 from the daemon checkout on 2026-10-18 at 16:43Z: data
`82a7ec7e` (grades commit `dfe19609` on top of the shelf commit `8d875341`),
Cloudflare version `5feed364-4805-4a4d-bf11-64005e4deba2`; the live page says
"53 technology leaders" and lists both. The masthead still says "technology
leaders", as it did after Nate Silver; changing it is a separate publication
decision.
