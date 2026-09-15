# Supplementing thin leaders with non-YouTube sources, 2026-09-14

Run directory: `data/predictions/_experiments/supplemental-sources-2026-09-14/`
Clone: repo-1, `verbatim.role=experiment`. Nothing here is integrated. Only
repo-0 can move any of it into `data/predictions/<slug>/`.

## The question

14 of the 50 leaders carry fewer than 5 accepted predictions, which is
`MIN_TRANSCRIPTS_TO_RANK`, the floor the leaderboard already uses. Five carry
zero. Can they be supplemented from sources outside the YouTube corpus?

## What the shortage actually is

It is NOT a shortage of transcripts, and that had to be measured before spending
anything. Every thin leader already holds 7 to 16 transcripts and 70k to 330k
words, which is the same supply the top of the board has.

```
leader              accepted  transcripts  kwords   accepted per 10k words
tobi-lutke                 0           12   222.9                     0.00
fei-fei-li                 0           14   206.5                     0.00
jack-dorsey                0           14   219.9                     0.00
sergey-brin                0           12    74.4                     0.00
ilya-sutskever             0            7    70.9                     0.00
...
andy-jassy                41           10   147.7                     2.78
lisa-su                   39           14   187.9                     2.08
```

Yield runs from 0.00 to 2.78 per 10k words at roughly constant supply. The
corpus average is 0.54 per 10k words over 8.8M words.

Where the thin leaders' candidates die is a single gate. Across the 14 thinnest,
94 candidates passed extraction and were then rejected by verification:

```
falsifiable      83
stands_alone     54
committed        22
forward_looking  12
own_voice        10
```

These people speak in confident sentences that carry no test. More interview
transcripts of the same kind would be rejected at the same rate. The run
therefore targeted a different KIND of source: documents that carry dated,
numeric, thresholded claims.

## Method

**Discovery.** 14 subagents, one per leader, each briefed with the five gates
and each leader's existing source list. They searched, fetched candidate pages,
and reported sources with 1 to 3 VERBATIM sentences copied from the page as
evidence. `AGENT-BRIEF.md` in the run directory is the brief they all read.

**Fetch.** `scripts/fetch_web_sources.py` fetches each reported source, extracts
verbatim text, and writes it as a transcript-shaped record so
`extract_predictions.py --transcripts <dir>` reads it with no change. Extraction
and verification then apply the same five gates, the same two model families and
the same mechanical quote grounding as every YouTube transcript.

**Arm.** Extraction is pinned to `astra` and verification to `gemini`, because
that is what the existing corpus ran: all 1,494 baseline records are
astra-extracted, and 1,333 of them are gemini-verified. A first sweep used
fable, which would have made any yield comparison partly a comparison of models.
It was stopped and re-run with `--force` on the matching arm.

## Verbatim, and how it is enforced

The pipeline finds each model-written quote by an EXACT span match and records
character offsets. A quote that does not match is dropped, never repaired. So
the text must be verbatim or the source silently yields nothing and reads as a
low-yield source rather than as a bug.

- `scripts/web_source_text.py` extracts HTML text with the standard library
  only, so `requirements.txt` stays pinned to what repo-0 ran. It may unescape
  entities and normalise whitespace, and nothing else.
- `assert_verbatim()` cross-checks every extraction against a deliberately
  different naive strip, comparing the LETTER STREAM so the two may disagree
  about whitespace and not about content.
- PDFs are read with `pdftotext`, an external binary, cross-checked between its
  default and `-layout` modes.
- 132 of 139 evidence quotes the discovery agents copied from pages ground
  exactly in the text this fetcher retrieved, which is the integrity check on
  the discovery pass. That check matters: two agents independently caught the
  page-reading tool PARAPHRASING quotes, and one caught it attributing a
  sentence to Jack Dorsey that was not on the page at all.

## Fetch results

```
attempted 115 / written 91 / failed 24  (79%)
taxonomy: http_403 4, http_429 1, not_verbatim 4, robots_disallow 3,
          too_short 5, identity_not_verified 2, bad_date_basis 1,
          dateless 6 (written, basis "unknown")
```

Two duplicates were withdrawn before extraction by
`scripts/dedupe_supplemental.py`, which imports its measure and thresholds from
`dedupe_transcripts.py` rather than restating them:

```
0.887  jack-dorsey   Dorsey's section of Block Investor Day 2025, inside the
                     full 44,494-word corrected transcript of the same event
0.614  fei-fei-li    the TIME reprint of her own Substack essay
```

The longer copy survives in each case, which is the repo's existing convention.
There were ZERO collisions with the existing corpus, so the discovery agents'
own dedupe against each leader's existing source list held.

89 sources remain, about 692k words, a 35% increase over these 14 leaders'
existing 1,980k words.

## Bugs this run found, all fixed with failing-then-passing tests

Three were latent in the repo and none of them was mine.

1. **`call_astra` never created its workdir.** `call_fable` and `call_gemini`
   create theirs. Astra passed a possibly-missing path straight to
   `subprocess.run(cwd=...)`. Invisible for the whole corpus because Astra always
   EXTRACTED while Gemini or Fable verified, so it was never handed the
   per-batch subdirectory `verify_one` creates only the parent of. Surfaced the
   first time measured quota routed Fable to extraction. Cost 7 of 9 transcripts
   in the pilot. `scripts/test_harness_workdir.py`, 8 checks, 3 failing before.

2. **`parse_lines` split JSONL with `str.splitlines()`.** JSON permits NEL,
   U+2028 and U+2029 raw inside a string, and `splitlines()` breaks on all
   three. A Stripe annual-letter PDF carried one U+2028 in an image caption; the
   record was 9,564 bytes, 9,522 characters and ONE `\n` byte, and
   `splitlines()` returned two lines, so the record failed as `Unterminated
   string`. The error named a column, and the character responsible was 555
   characters further on. `scripts/test_jsonl_line_splitting.py`, 34 checks.

3. **`derive_statement_date` could only read `yt_upload_date`,** and hardcoded
   the basis string `youtube_upload_date`. A web source has no upload date, and
   writing one into that field would have produced a record claiming a Palantir
   earnings call was dated from a YouTube upload. Worse, the pre-fix function
   returned `(None, "unknown")` for a declared date, discarding it silently.
   It now honours a declared `statement_date` with a basis of `stated_in_page`
   or `publication_date`, and raises on anything else.
   `scripts/test_statement_date_basis.py`, 19 checks, 11 failing before.

## Choices made while implementing, which are judgement and not fact

- **A missing date does not reject a source.** An earlier version of the gate
  required one, and it dropped 11 sources of which 6 were Sergey Brin's, the
  leader with the least material. A cap that bites one person six times harder
  than everyone else is a bias. Dateless records are written with basis
  `unknown`, counted as `dateless`, and cannot carry a horizon or a market
  cutoff. Nothing infers a date from a URL or a title.
- **PDFs whose two extraction modes disagree on ORDER are accepted, flagged.**
  Several Stripe letters are designed with pull-quotes, and default mode hoists
  the pull-quote above the real opening. The character multisets are identical,
  so nothing is lost and quotes still ground. `-layout` is preferred and the
  record records `layout_preferred_modes_reordered`. The residual risk is that a
  400-word context window may cross a pull-quote boundary. Modes that disagree
  on CONTENT are still refused.
- **A `not_verbatim` failure is retried once.** Some pages serve slightly
  different bytes per request. conversationswithtyler.com passed, then failed by
  ten characters, then agreed exactly. Each attempt validates its own bytes.
- **`MIN_WORDS = 400`.** Below that a page is nav furniture or a paywall stub.
  It bit 5 times, 4 of them Sergey Brin's abc.xyz founders' letters, which are
  JavaScript shells serving 10 words.

## Open question for repo-0

Whether supplemental records may join `data/predictions/<slug>/` at all. They
are the same evidence class by construction, they carry `source_class:
supplemental_web`, and they are separable at any time. They are NOT
YouTube-dated, so `statement_date_basis` takes two new values that
`phase2_resolvability.py` has never seen.

## Results

Six of the 14 leaders completed before Fable quota ran out. Re-derive with
`scripts/summarize_supplemental.py --run <run> --as-of YYYY-MM-DD`.

```
leader              was  new  now  cand  keep  crossed the floor of 5?
patrick-collison      2   14   16    19   74%  YES
brian-chesky          4    6   10    26   23%  YES
amjad-masad           4    4    8    14   29%  YES
arthur-mensch         4    3    7    11   27%  YES
michael-dell          3    1    4     1  100%  still under (1 of 3 sources run)
alex-karp             1    1    2     8   12%  still under
```

79 candidates produced 29 accepted, a 37% keep rate. Four of the six crossed
the rank floor. Two did not, and for different reasons: michael-dell is
incomplete, while alex-karp is a real negative result.

**Yield by source kind**, over the 34 sources run so far:

```
source kind            srcs  accepted  kwords  per 10k words
letter                    6        15    21.9          6.84
article_with_quotes       3         1     3.5          2.83
testimony                 3         3    24.8          1.21
earnings_call            10         6    86.2          0.70
interview_transcript     10         3    85.3          0.35
keynote_transcript        2         1    36.3          0.28
ALL                      34        29   258.0          1.12
existing YouTube corpus                               0.54
```

This is the transferable finding. Supplementing works, and it works at about
twice the corpus rate overall, but almost all of the gain sits in ONE source
kind. Shareholder and founder letters run 6.84 per 10k words, twelve times the
corpus rate. Interview transcripts and keynotes run at or below it, which is the
same result the thin leaders already had, reached by a different route.

**Earnings calls disappointed, and the reason is countable.** Ten calls produced
6 accepted. The discovery agents expected them to be the densest source, and
they are dense in dated numeric guidance, but the CEO is often not the one
giving it. Alex Karp speaks 1,300 to 3,100 words of each Palantir call and the
CFO carries the guidance. Lip-Bu Tan is 2.3k to 3.7k words of a 10k-word Intel
call. Tobi Lütke has not spoken on a Shopify earnings call since Q4 2022, and
spoke 269 words that time. Michael Dell does not appear on Dell's calls at all.
An earnings call is only a good source when the subject is the one guiding.

**Where the rejected candidates still die**, now measured on supplemental
sources rather than the original corpus:

```
falsifiable      37
stands_alone     19
committed        12
forward_looking   6
own_voice         2
```

The same gate dominates. The run raised the keep rate rather than removing the
constraint, which is the honest reading: these leaders speak in unfalsifiable
terms wherever they speak, and the fix is to find the documents where they are
obliged to commit.

**own_voice is NOT the obstacle it looked like.** Only 2 rejections. The
co-signed Stripe letters, written as "we" over "Patrick and John", passed. That
answers the question the Collison agent raised and could not settle.

## What this is worth to Phase 2

Of the 29 new accepted, as of 2026-09-14:

```
own-control (a delivery rate, not foresight)   15
carrying a valid target date                   22
past due                                       13
past due AND not own-control (scorable)         7
```

Seven scorable-as-foresight predictions against the 38 the whole corpus carries
today, from six leaders and 34 sources. That is a meaningful proportional
addition to the scarcest category in the project, and it does not change the
Phase 2 conclusion: one leader reaching five scorable predictions is still the
binding problem, because 15 of 29 are a CEO promising what their own company
will do.

## Not finished

Fable quota ran out mid-sweep: 26 extractions succeeded and 42 failed
`auth_or_quota` on the same pass. Every Claude account was out of Fable at once.
The run is resumable and nothing needs re-fetching.

```
leader           sources  kwords
jack-dorsey            9   105.5
lip-bu-tan             7    54.1
fei-fei-li             7    40.6
thomas-kurian          6    36.1
tobi-lutke             6    45.8
clem-delangue          5    32.0
ilya-sutskever         4    29.4
sergey-brin            2    15.7
                      46   359.0
```

Resume with the same command; completed stages are cached:

```
.venv/bin/python scripts/extract_predictions.py --stage both \
  --transcripts <run>/transcripts --out <run>/results \
  --extractor fable --verifier gemini --allow-degraded --workers 3
```

Do NOT pass `--force` on the resume. It is what marked Collison's and Michael
Dell's completed extractions `failed` when the quota wall hit, while their
verified records survived on disk. The records were not lost, and the meta now
disagrees with them.

## Two caveats on the numbers above

**The verifier is mixed.** Collison's 14 accepted were verified by Astra, in the
pilot that shook out the `call_astra` bug. The other 15 were verified by Gemini.
Both are baseline verifiers, 145 and 1,333 records respectively, so neither is
novel, but the arm is not uniform and the per-leader counts should not be
compared with each other at fine grain.

**The extractor differs from the baseline's.** All 1,494 baseline records are
Astra-extracted; these are Fable-extracted, because Astra was unreachable. The
`codex_b` account holds 100% of its window and is INVISIBLE to
`select_account`, which ranks only `codex`, so `--router-exclude codex` returns
`router_no_account`. That is an `llm-quota-router` limitation and was not
chased here.

So the headline "1.12 against 0.54 per 10k words" compares web sources read by
Fable against YouTube transcripts read by Astra, and part of that gap could be
the model. The comparison WITHIN this run is clean, because every source here
had the same extractor, and that is where the load-bearing finding sits: letters
at 6.84 against interview transcripts at 0.35, a 20-fold spread on one arm.

A paired check would settle the cross-arm question cheaply: re-extract 6 to 8 of
these same sources with Astra and compare candidate counts on identical text.
`codex` has about 4% of its window left, which is enough. Not run.

## Correction, 2026-09-15: the codex_b diagnosis above was wrong

The `llm-quota-router` owner corrected this, and the correction is verified.

**`codex_b` is not invisible because of a router bug. Every verbatim-index venv
runs a STALE PIN.** `requirements.txt` pins `llm-quota-router@v0.1.1`, and that
release cannot read a second Codex home and predates the reserve entirely:

```
venv:  quota_router.__version__ = 0.1.1
venv:  codex account attrs = ['config_dir', 'tier'];  manual_rate_per_day ABSENT
live:  chosen: codex_b
       excluded: codex - "only 0.0% left in its tightest applicable window"
```

Two claims made above are therefore withdrawn. Calling this "the same bug shape
as account E" was wrong: that bug is fixed, and this is a pin that has not moved.
And `remaining: 0.61, fits: true` was the stale library talking. It has no
`manual_rate_per_day` field to read, so it reports the operator's reserve as
spendable. The live router holds 58 of those 60 points back for the Codex
desktop app.

**So Astra on `codex` is not "available", it is spending a reserve.** Each
extraction costs about one point of the weekly pool. The Astra calls made during
this run took the spendable margin from 6% to 0.0%. Waiting for Fable, which is
what this document already recommended, remains the right call and costs nothing.

**`call_astra` is fixed here, and the ORDER matters.** Raising the pin first
would let the router book `codex_b` while the call still spent `codex`, and
every record would name an account that did not serve it. That is worse than the
present state, so the code fix lands first and the pin does NOT move in this
commit:

- `call_astra` takes `config_dir` and exports it as `CODEX_HOME`.
- `route_from_selection` populates `config_dir` for astra, as it already did for
  fable, and REFUSES an astra account that has none. `str(None)` would have
  exported the literal `"None"`.
- `call_harness` returns `route["account_id"]` instead of the hardcoded
  `"codex"`.
- `scripts/test_astra_codex_home.py`, 13 checks, 8 failing against `origin/main`
  behaviourally rather than by signature error.
- Two existing assertions pinned the old behaviour and were updated in place
  with the reason, not deleted: `ROUTE: codex -> astra, no config dir` in
  `test_predictions_driver.py` and the `call_astra` signature in
  `test_predictions_shared.py`.

Still outstanding, and NOT this repo's to do: `llm-quota-router` must bump
`__version__` and tag `v0.1.2`. Both the venv copy and the live install report
`0.1.1` today while behaving differently, so no version check can tell them
apart. Once tagged, raise the pin here and rebuild every clone's venv.
