# Recording dates

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you run or change
`date_recordings.py`, `dating_lib.py`, a merge version or the promotion of a
dating run.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Experiments run, and what they showed

**Which second dater finds the date?** (2026-10-04) The operator's seven audited
recordings, three repeats each, under the merge-4 prompt. One repeat called Gemini,
Fable without tools, Fable with WebSearch and WebFetch (`fable_web`) and Astra once
each, and each pair was judged on the same Gemini answer. That was 96 calls plus a
4-call pilot. A case passes when 2 of 3 repeats confirm a statement date inside the
operator's true range, as `cases-20261004-dating` defines it. Judged under the final
merge-4:

```
pair               cases passed  repeats right / wider bound / queued / wrong
gemini+fable       3 of 7        9 / 3 / 9 / 0      (production, VD-11)
gemini+fable_web   6 of 7        17 / 0 / 4 / 0
gemini+astra       7 of 7        19 / 0 / 2 / 0
```

Five of the right repeats are two-dater agreements, which name no source: one for
gemini+fable, one for gemini+fable_web and three for gemini+astra. Alone, Fable
without tools answered `cannot_date` in 9 of 21 repeats and was right in 2. The
judged results include four merge rules that came from this run, so they are
in-sample. Judged under merge-4 as it stood before those rules, the pairs pass 3, 5
and 6 of 7. Every served model was the one requested; Astra's is an unverified echo,
and `fable_web`'s responses also name `claude-haiku-4-5`, which WebFetch uses.
Recordings, logs and the per-repeat table are in the data repository under
`predictions/_eval/cases-20261004-dating/`. The production daters were not changed by
this run. On 2026-10-05 the operator changed them to astra and fable_web.

**Does merge-5 date the operator's cases live, with the production daters?**
(2026-10-05) Mostly, and it confirmed no wrong date. Ten cases, three repeats each,
astra and fable_web, with Fable's account picked per call by the quota router (no
pin): the seven, Mensch, hs-2394 and control (ii). The cap was 60 calls and the run
made 60: astra 30 ok, fable_web 30 ok, no failure. Every Fable call served
`claude-fable-5-1`, verified from its telemetry, and every one also names
`claude-haiku-4-5`, which WebFetch uses. Astra's `gpt-6-astra` is an unverified echo.
The router picked `claude_d` for all 30 Fable calls. Astra searched 7.9 times per call
(2 to 26) and Fable 13.6 times (4 to 20), with 15.9 page fetches. Judged by the code
at `90a1c6b` plus the channel rule above, 9 of 10 cases pass: 22 repeats right, 5
queued, the control held 3 of 3, none wrong and none a wider bound. OP7 queued all
three. Astra answered 2025-12-04 each time from "two days ago" of a 2025-12-02 event,
which is not a day word, from a page that does not name Tenev, with a quote that
leaves out an "uh". Fable's floor page shows 2 December where its floor said 1
December. hs-2394 passed 3 of 3 by the day word. That counts the sentence rule, which
came from this run's third repeat, so that one repeat is in-sample. The workers' own
verdicts, judged by the code at launch, give 2 of 3 for hs-2394 and agree on every
other case. Recordings, logs and the table (`logs/live-table.txt`) are in
`predictions/_eval/cases-20261005-merge5/` in the data repository.

## Where things are

- Recording dates (rescue round 4, operator decision VD-8 (c)):
  `scripts/date_recordings.py --run-dir data/predictions/_experiments/dating-<name>`
  is a dry run until `--run`, which SPENDS QUOTA. Two daters per recording since
  2026-10-01. Since 2026-10-05 (operator decision) production uses Astra and Fable with
  its web tools, and `--harness astra,fable_web` is the default; it was gemini,fable
  under VD-11. A run directory made with other daters is refused before any call, so
  production's `dating-run-20261001` (gemini,fable) stays as it is and a new production
  dating run uses a NEW `--run-dir`. Fable's account is picked per call by the
  quota-router library, `select_account(model="fable", only=<the enabled Claude
  accounts>, record=True, no_sticky=True)`, as `extract_predictions.Router` picks; never
  the `cl` launcher. A degraded, exhausted or empty pick is refused as
  `router_no_account` unless `--allow-degraded` is given, and the picked account and
  the router's reason are in each proposal's `telemetry.router`. `--fable-config-dir`
  pins the accounts instead. `--router-exclude` keeps named Claude accounts out of
  every pick: the coordinating session's own account, which the router otherwise
  drains (FOUND 2026-10-05: half of a run's fable_web calls went to it). Each dater's
  account rotation counts transcripts, so Astra alternates over `--codex-home`
  (`71e2884`; before it every Astra call took the first home).
  `scripts/promote_dating_run.py --hold-file <json>` holds named entries for a
  person's review ({transcript_id: reason}): reported HELD, never promoted, the way an
  R1 hold is; the overnight run of 2026-10-05 held every two-dater agreement this way
  because only source-checked dates were to go. Since 2026-10-09 agreements are promoted like
  any other entry (operator, ledger VD-16), so no hold file is needed for them. Across runs,
  rule R1 does not read a proposal from a dater with no web tools (`dating_lib.NO_WEB_DATERS`,
  Fable before 2026-10-05, which answered from memory): operator, ledger VD-17 option B. Each
  such proposal skipped is printed as `not read (no web tools)`. Every proposal file records the roster's company for the
  speaker, `speaker_company`, which merge-5 reads; a speaker the roster lacks stops the
  run before any call. Each dater writes its own proposal, `<sid>.<dater>.json`,
  naming the event and its date range with sources. A
  single-dater run such as `--harness astra` is the one-agent rule of VD-8 (c): its
  entries load and re-verify like any other, but it is not how production dates. The
  merge confirms a date when one dater's page or description check passes and no
  other usable dater's range misses that day (rule R1, coordinator 2026-10-01,
  reversible), or when both name exactly the same last day with nothing confirmed and
  that day is not the upper bound, a lead or a page date both prompts showed. An agreed
  date has its own `confirmed_by`, `two_agent_agreement`, names no source, records what
  each agent named as unconfirmed `agents_named`, reads "two dating agents named this
  day; no source confirms it" in the header and on the card, and is never an exact
  date for `score_predictions.exact_statement_date`. Two confirmed days, or a
  confirmed day another dater's range misses, queue as `dater_disagreement`. A
  transcript is merged once every dater's proposal is on disk. An answer that fails
  validation is stored as an invalid proposal, so it never holds a transcript; a
  proposal from a run with other daters stops the run before any call. The recording's
  DESCRIPTION counts when it states the event's date: the dater's
  `description_evidence`, or Tier 0, a description with exactly one full day. Either
  way the day must be strictly before the upload and not next to a cue word (born,
  founded, released, premiered, streamed, "originally", a promo code, before, until,
  the next event) or inside a link, and the title is never read. `dating_lib.py`, with no model, must find each
  cited excerpt with a date inside the range on the fetched page, and a source must
  show the range's LAST day, the statement date. The recording's own page never
  counts, checked on the cited and the final (redirected) address: its video id,
  any YouTube page or front end, archive.today copies, google.com/url redirects,
  the transcript's url whatever its query string, and, under merge-3, a page that
  embeds the recording or carries an uploadDate beside the excerpt (merge-4 below
  relaxes that one). The window must name the
  speaker or the event, a UTC timestamp cannot date a speech, a re-upload's
  publication date is queued, and an undated source is bounded by its
  `fetched_at_utc`. A date earlier than the transcript's own is written to the
  run's `overrides.json`; one that CONFIRMS the transcript's own date to
  `checks.json` (`load_statement_date_checks`, `--date-checks` on the extractor),
  which supersedes no record. The rest go to `queue.json`. Never production's
  files. Every agent entry re-verifies on every load from every proposal file's
  sha256, the window kept around each excerpt and the transcript's stored
  description. Proof: `scripts/test_dating.py`, `scripts/test_dating_description.py`,
  `scripts/test_dating_two_daters.py`, `scripts/test_dating_review_fixes.py`,
  `scripts/test_date_recordings.py`. Header lines `override_agreed_day` and
  `override_agreed_range` are pinned with the rest of the header in release
  `predictions-2.3`'s `contracts.header`.
  **merge-4 (2026-10-04)** was `MERGE_VERSION` until merge-5. The operator audited seven
  recordings the stage failed to date, and every date was findable. merge-3 stays
  re-runnable, because the loader re-merges each entry under
  the version it names, and production holds 205 merge-3 entries. merge-4 changes
  five rules. (a) A page that embeds the recording may confirm a day strictly before
  the upload, if no uploadDate in its window names that day. Such a page is an
  organiser's archive that dates the session, as with the Khosla CEO Summit and Citi
  Legends Live. A page that shows only the upload day is still refused. (b) A
  relative date in the description, such as "last November", is read against the
  upload date as a range. "Originally released ..." stays cued, because a release is
  a ceiling. (c, e) An excerpt under four words counts only when it is a date alone
  and the page names the speaker with the host, interviewer, event or channel within
  400 characters. A date the page writes another way ("12 February 2020" for
  "February 12, 2020") still matches. (f) When the earliest confirmed last day lies
  inside every other confirmed range, it refines them, so a day inside a month is not
  a disagreement. Rule R1 is unchanged. Also, a proposal's optional `bounds` (floors
  and ceilings) must hold its range. The live run added three rules. A UTC
  publication stamp may show the last day of a range of days. Transcript words that
  are not in the transcript are dropped, and the proposal's own page can still
  confirm it, but it takes no part in an agreement or in R1. Words joined with "..."
  are found fragment by fragment. The prompt asks the daters to search for the host,
  the interviewer and the guest together, and to state each bound. MEASURED over all
  482 stored transcripts of `dating-run-20261001` and `dating-astra-20261003`:
  merge-3 equals the old merge on 482 of 482, and merge-4 changes no confirmed date
  and confirms 11 queued ones. Five of the 11 are not among the operator's seven and
  are not audited. `--harness fable_web` is Fable with exactly WebSearch and
  WebFetch under `sandbox-exec`, through `date_recordings.call_fable_web`. It is for
  dating only, and since 2026-10-05 it is one of the two production daters. The judge
  harness and the outcome-blind prior and lead-test stages keep their tools off. Proof:
  `scripts/test_dating_operator_rules.py`, `scripts/test_dating_fable_web.py`,
  `scripts/test_dating_operator_cases.py`, which reads the data link.
  **merge-5 (2026-10-05) was `MERGE_VERSION` until merge-6.** A run then wrote merge-5 entries;
  merge-3 and merge-4 stay re-runnable, and `date_recordings.py --merge-version
  merge-4` re-merges a run whose proposal files lack `speaker_company`. merge-5 closes
  the operator's three gaps and adds the rules drawn from `dating-vp34-20261005`.
  (a) A page confirms only when it names the speaker AND one NAME of this occasion,
  every word of it: the host organization, an interviewer, the channel, the event's
  name (the dater's text before a colon or "about"), or a run of two or more
  capitalised title words. Generic words are optional, the speaker's company (the
  roster's) never counts, and a page on the host's own domain names the host. A run
  that those rules cut down to one word is a name only when the word is a name as
  written ("PandoMonthly", "I/O", "SXSW", "D11", never "Mind"), and a platform, month or
  weekday is never a name. A host or channel cut to one ordinary word keeps its generic
  words: "Big Technology Podcast" needs "big" and "technology". FOUND:
  a casino.org article on Robinhood "dated" the Tenev podcast (OP7 r01), and a Big
  Technology post that never names Mensch dated `arthur-mensch/alex-kantrowitz-xxutdy`.
  (b) A yearless month or month-day counts when the same page shows its publication
  date ("In February" on a page "Published: 03.02.21" is February 2021): the latest
  such day not after it, every reading of a numeric anchor giving one year; an update
  date never anchors and a re-publication anchors only on its "originally published"
  date. A yearless period may end on the range's last day; a dated span must still lie
  inside the range. A numeric date with a four-digit year counts when it has one
  reading ("10/13/2025", never "2/12/2020"). An upcoming yearless day the transcript
  names ("we're doing one on December 16th") is a CEILING once a cited page that
  passed the check gives a floor for its year, and only when no second such day lies
  between the floor and the upper bound. A floor page dates a past event the talk
  mentions and shares a two-word phrase with the transcript; it confirms nothing alone.
  (c) Rule R1: a dissenting dater blocks a confirmed day only when a check of its own
  passed, or the day is a publication date (a publication word or UTC stamp beside it,
  or a `publication_only` verdict). The overruled dater is recorded. Release rule
  (operator): the podcaster's own episode (`publication_only`, `podcast_episode`, not a
  re-upload, channel = host or interviewer) is dated by its release when a podcast
  platform or the show's own site shows the upload day; it is a check, and as a
  publication day R1 still applies in full. Day words (operator): "yesterday", "last
  night", "today", "this morning", "tonight" or "tomorrow" in the transcript words,
  beside an event that a CITED page dates and ties by a two-word phrase, pins the day
  of speech, narrows the range and outranks a later release day
  (`palmer-luckey/hs-2394-palmer-luckey`: AUSA's 2025-10-13 address "yesterday" is
  2025-10-14). The sentence that carries the day word is read on its own when it is in
  the transcript word for word, so it still pins when the rest of the dater's quote is
  not. Sponsor reads date nothing: words within 600 characters of a sponsor
  cue never pin, ceil or tie a floor, and the prompt says so; it also says an upcoming
  day is a ceiling, never a floor. MEASURED by offline replay of every stored answer
  (`data/predictions/_eval/cases-20261005-merge5/logs`): on the operator's seven,
  astra+fable_web passes 8 of 8 cases (seven plus control (ii)) under both merges, now
  without the casino.org confirmation and with OP3 and OP7 confirmed by the script
  rather than by agreement; gemini+fable_web goes from 7 to 8 of 8. Pilot A9 stays
  queued. Over the 487 transcripts of the three stored production runs, merge-5 loses
  45 merge-4 confirmations, gains 1 and changes no confirmed statement date (the
  earliest day moves on 3); most lost pages do not name the speaker (event schedules,
  press releases, Wikipedia pages on a product), and several are about another
  occasion. 119 stored proposals in 79 transcripts use a day word; 3 pin a day, each
  the day merge-4 had confirmed. Proof: `scripts/test_dating_merge5.py`, whose 55 tests
  all fail on the code before merge-5.
  **merge-6 (2026-10-09) is `MERGE_VERSION`** (operator, ledger VD-16). It changes only the
  agreement: when no page or description confirms anything, two daters whose last days are at
  most `NEAR_AGREEMENT_DAYS` (7) apart agree on the LATER day, with the range from the earliest
  first day; under merge-5 they had to name exactly the same day. The later day errs late, never
  early, so a forecast's lead is never overstated. What a source confirms merges exactly as under
  merge-5 (`RULES["merge-6"]` is merge-5's rule). Kept: a day both prompts showed (the upper
  bound, a lead, a page date) is not independent, and a range after the upper bound is never
  eligible, which is the operator's "no date after the upload". X = 7 was MEASURED: on the 69
  recordings of `dating-merge5-20261005a/b` a source confirmed, the 62 exact agreements all equal
  the source's day, and the 4 further pairs within 7 days give a later day 1 to 6 days after it,
  never before; at 14 days one pair is 11 days late. Replayed over halves A and B from their
  stored files: 95 entries kept byte for byte, 0 changed, 3 newly confirmed (1 or 2 days apart).
  A near agreement's entry carries `confirmation.near_agreement` (both last days), its record
  carries `near_agreement_other_day`, and its header is `override_agreed_near` in release
  `predictions-2.4`, because "two dating agents named this day" would be false of it. 2.4 is 2.3
  plus that one line; the extraction and verification contracts are unchanged. A run re-merged
  under a newer version keeps every entry an earlier version confirmed, when that version still
  gives the same entry (`date_recordings.merge_keeping`): otherwise resuming a merge-5 run would
  relabel entries production already holds and promotion would refuse them as conflicts. The
  gold set `cases-20261005-merge5` replays identically under merge-5 and merge-6 code. Proof:
  `scripts/test_dating_merge6.py`, 20 tests, 13 of which fail on the code before merge-6.
