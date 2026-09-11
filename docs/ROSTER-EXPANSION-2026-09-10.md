# Roster expansion to 50, and the withdrawal of C.C. Wei

Prepared in `repo-4` on 2026-09-10. `repo-4` may not write `data/`, so the
artifacts sit outside both repos at
`~/Code/misc/verbatim-index/roster-expansion-2026-09-10/` and **`repo-0` applies
them**. Nothing in `data/` was changed by the work this file records.

## What changed and why

The operator asked for three things: add Tobi Lütke, remove C.C. Wei, and grow
the roster from 40 to 50. 39 survivors plus Lütke plus 10 new names is exactly
50.

The 10 were selected on **recognition among a technology audience on X**. That is
a different criterion from the general technology-business fame that chose the
original 40, and the difference is the reason five names the original process had
already rejected are now in. Every reversal names the sentence it overturns, in
that person's own `selection_rationale`.

## C.C. Wei: what was actually on the board

14 transcripts were fetched under `cc-wei`. Two mention TSMC at all.

| source | channel | who is speaking | "TSMC" |
|---|---|---|---|
| `the-wellth-channel-opxr-s` | The Wellth Channel | **C.C. Wei, TSMC** | 67 |
| `yale-university-q1b-fn` | Yale University | **C.C. Wei, TSMC** | 17 |
| `bankless-tik8am` | Bankless | Eugene Wei | 0 |
| `sha-xin-wei-sl9kac` | Sha Xin Wei | Sha Xin Wei | 0 |
| `danny-haiphong-k-c3ae` | Danny Haiphong | Zhang Weiwei | 0 |
| `han-wei-shen-ughuv0` | Han-Wei Shen | Han-Wei Shen | 0 |
| `micad-e9hwxk` | MICAD | Prof. Linwei Wang | 0 |
| `mit-civil-and-environmen-rwmwc3` | MIT CEE | Wei Chen | 0 |
| `usacm-juvcrj` | USACM | Wei Chen | 0 |
| `newton-free-library-9aab7z` | Newton Free Library | William Wei | 0 |
| `adobe-creative-cloud-1l--yn` | Adobe Creative Cloud | Jing Wei | 0 |
| `george-daniel-swpx7b` | George.Daniel | Weivy Wei | 0 |
| `six-five-media-rmprp4` | Six Five Media | Wei Li, Intel | 0 |
| `ted-hahs-iyee3v` | Ted Hahs | Lord Nat Wei | 0 |

12 of the 14 were on the published board at rank 32 with `confidence: "high"`,
and 10 of those 12 are the wrong person.

**Root cause.** `discover_sources.name_in()` takes the surname as
`person["name"].split()[-1]`, so the identity test for this leader was the
three-letter token `wei`. The subject-share filter cannot catch this: a
wrong-person recording answers "is someone speaking" with maximum confidence.
Han-Wei Shen's lecture scored 100% subject share on all three judges.

`scripts/wrong_person_screen.py` already exists and already reads the judges'
`identity_guess` for exactly this class of defect. It was run read-only during
this work and its verdicts agree with the table above.

## The identity screen, and its control

Availability was re-measured with `yt-dlp` through `discover_sources`' own
duration, clip and third-person filters, plus an identity screen: a hit counts
as **confirmed** only when the full name, or the surname together with a company
token, appears in the title or channel. Surname-only hits are the C.C. Wei
failure class and are counted separately.

The screen was validated against controls before any candidate was judged by it.

| control | confirmed | surname-only | purity |
|---|---|---|---|
| C.C. Wei (known bad) | 3 | 11 | **20%** |
| Matthew Prince (known good) | 24 | 0 | 100% |
| Aravind Srinivas (known good) | 30 | 0 | 100% |

Across the 39 surviving leaders the only purity below 90% is Clem Delangue at
83%, caused by "Clément" against "Clem". C.C. Wei is not a borderline case on
this measure. He is the only outlier.

## The availability number now means one thing

`longform_availability` is now the measured confirmed count for all 50. The
scout medians that chose the original 40 are preserved per person as
`longform_availability_scout_median`.

The two scales are correlated but **not interchangeable**: Pearson r = 0.75 over
the 39 surviving leaders, scout mean 74 across a 7-200 range against measured
mean 39 across a 19-65 range. The measured scale is compressed because the search
pool is capped near 90 results. Musk's recorded 200 measures 62; Altman's 180
measures 63. Do not compare a measured number against a scout median.

## The 11 added

| person | company | sector | measured | note |
|---|---|---|---|---|
| Tobi Lütke | Shopify | Enterprise Software | 32 | operator-mandated |
| Michael Saylor | MicroStrategy | Fintech | 73 | off the bench; largest supply measured |
| Eric Schmidt | Google | Cloud & Platforms | 67 | bench said "the first name I would add at 41" |
| Aaron Levie | Box | Enterprise Software | 54 | bench cut him on general fame |
| Dylan Field | Figma | DevTools & Infra | 48 | bench cut him on fame outside design |
| George Hotz | tinygrad | Hardware & Mobility | 46 | not comma.ai; see below |
| Amjad Masad | Replit | DevTools & Infra | 40 | reverses an explicit rejection |
| Greg Brockman | OpenAI | AI Labs | 36 | third OpenAI seat |
| Ilya Sutskever | SSI | AI Labs | 34 | bench estimate of 14 understated by 2.4x |
| Vlad Tenev | Robinhood | Fintech | 33 | |
| Alexandr Wang | Meta | AI Labs | 27 | bench cut him at a median of 40 |

Sector counts after, computed from the roster array: AI Labs 12, Cloud &
Platforms 8, Consumer Internet 6, Enterprise Software 6, Fintech 5, Hardware &
Mobility 5, Semiconductors 4, DevTools & Infra 4. Largest bucket 12 of 50.

## Roster strings are load-bearing, and were measured

The `name` and `company` fields drive discovery queries AND blinding, so a
plausible-looking string can cost supply or leak identity. Four were chosen by
measurement rather than by what the person is usually called.

**Tobi Lütke, not Tobi Lutke.** Measured confirmed hits by spelling: `Tobi
Lütke` 32, `Tobi Lutke` 10, `Tobias Lütke` 6, `Tobias Lutke` 6. A 3.2x spread
that the roster field controls directly. The umlaut form also blinds strictly
better: it reduces `Lutke`, `Lutkey` and `Luttke` to `[SUBJECT]` through the
phonetic pass, while the ASCII spelling leaves `Lütke` standing in plain text.
`Tobias` is added to `aliases.json` because the short given name does not cover
it.

**George Hotz's company is `tinygrad`, not `the tiny corp`.** He left comma.ai in
November 2025 and keeps only a board seat, so comma.ai would have been wrong on
the facts as well. `company="the tiny corp"` replaced the ordinary word "tiny" 3
times in a two-sentence neutral test, because `blind()` applies company forms
unconditionally and does not consult the English dictionary on that path.

**Michael Saylor's company is `MicroStrategy`, not the current legal name
`Strategy`.** `company="Strategy"` redacted the ordinary word "strategy" 3 times
in a neutral 80-word paragraph. Accuracy of the legal name was traded for not
destroying every business interview in his corpus.

**Ilya Sutskever's company is `SSI`, and Alexandr Wang's is `Meta` alone.** Both
words of "Safe Superintelligence" are ordinary English, and "superintelligence"
is a core topic word in AI interviews.

Two hand-written aliases were removed after the same screen caught them: bare
`comma` for Hotz and bare `Scale` for Wang. Alias lists are now sorted
longest-first, because `blind()` applies aliases in list order and `Meta` was
stealing the match from `Meta Superintelligence Labs`, stranding
"Superintelligence Labs" in the blinded text.

Verified: all 11 new leaders blind with zero identifying tokens left standing.

**Two costs accepted rather than fixed.** `Box` is Aaron Levie's actual company
and `Field` is Dylan Field's actual surname, both ordinary English words, so
`blind()` will over-redact them. Four of the existing 40 already carry the same
defect (`Meta`, `Oracle`, `Face`, `Machine`). This degrades their transcripts
rather than leaking identity, so it costs coverage and not blinding.

## A stale sentence found in the existing file

`finalize_note`'s "Final counts" line does not describe the file it is attached
to, and did not before this expansion. It claims DevTools and Infra 4 and
Consumer Internet 4; the 40-name file actually held DevTools and Infra 2 and
Consumer Internet 6. The other six sectors match. Its SECTOR ASSIGNMENT paragraph
assigns Ali Ghodsi to DevTools and Infra, and Ghodsi was later moved to
`dropped_for_no_transcripts` without the counts being recomputed. The stale
sentence is left in place as a record of what was decided at the time, and the
correction is recorded alongside it in `sector_note_correction_2026_09_10`.

## Still excluded, deliberately

**Marc Andreessen and Garry Tan** were the two strongest candidates on the
criterion actually in use, and both are still out under the rule this roster
already states: a venture investor is not an operating technology business
leader. Andreessen measured 59 confirmed and Tan 47. That rule is the operator's
to change; it was not changed here. Flipping it is a one-line decision, and both
have the supply to be graded immediately.

**Six bench names measure well and stay benched** because they are recognised
inside their industries rather than on a technology timeline: Werner Vogels 59,
Eric Yuan 39, Bill McDermott 36, Cristiano Amon 35, Sebastian Siemiatkowski 27,
Rene Haas 16.

**Scott Wu was rejected on identity, not on fame.** He measures 23 confirmed
against 9 surname-only, a purity of 72%. "Wu" is the same short-common-surname
failure class as "Wei", and this roster has just paid for that once.

**Andrej Karpathy was rejected on role.** He joined Anthropic in May 2026 to lead
a pre-training team, so he is no longer running a technology business. He is also
an employee of the company whose models serve two of the three judges.

**Fidji Simo** stepped down from OpenAI in July 2026 for health reasons.

## Converges with the parallel wrong-person work

While this was being prepared, another clone landed `withdraw_sources.py`, the
`docs/withdrawals-2026-09-10.json` manifest, `identity_audit.py`, and a rank
floor of 5 included transcripts. That work reached the same conclusion about
C.C. Wei from the judges' `identity_guess`, independently: its manifest names 10
wrong-person recordings under `cc-wei` with speaker attributions identical to the
table above.

Two differences, both resolved here rather than left to collide.

**Their manifest is board-deep; the shelf is deeper.** It covers the 10
wrong-person recordings that were ON the board. Two more sit on the shelf,
`micad-e9hwxk` (Prof. Linwei Wang) and `sha-xin-wei-sl9kac` (Sha Xin Wei), which
the subject-share filter had already dropped. A source left on the shelf is
re-fetched and re-graded, so leaving them is a slow leak rather than a closed
withdrawal.

**Retiring beats deleting, and it is what the operator's choice needs.** The
instruction was to withdraw the 12 wrong-person recordings and KEEP the 2 genuine
TSMC ones. Keeping them under `data/transcripts/cc-wei/` is not possible once he
leaves the roster: `normalize_transcripts.py` raises `transcript cc-wei/... has
no roster entry; refusing to guess identity`, and both loops call it every cycle.
Verified by running it.

`withdraw_sources.py --apply` solves this exactly. `retire` renames
`<sid>.json` to `<sid>.json.superseded`, which is not matched by
`rglob("*.json")` and IS honoured by `fetch_one`. So the two genuine recordings
stay on disk, stay invisible to the pipeline, do not get re-downloaded, and come
back with a single rename. Verified end to end: `normalize` completes with
`cc-wei` off the roster and both files present as `.superseded`.

An earlier draft of this runbook said `git -C data rm transcripts/cc-wei/*.json`.
That was wrong, and wrong in a way this repo has already paid for once: a deleted
source does not match `dest.exists()`, so the fetcher downloads it again every
cycle. The rule is in AGENTS.md as "a retirement must be visible to the fetcher".
Use the tool.

`aggregate.MIN_TRANSCRIPTS_TO_RANK` is now 5, so 2 transcripts would leave him
scored-but-unranked. That is a weaker action than the operator asked for. He is
removed from the roster here, which removes him from `by_slug` and therefore from
the board entirely.

## Two traps in the fetch path, both found by following this document

The first version of the runbook below had three defects. All three were caught
by `repo-0` while applying it, and all three are fixed above. They are recorded
because each is a silent failure rather than an error.

**`discover_sources.py` is not the fetch input.** It writes
`data/sources/discovered.json`; `fetch_loop.sh` reads `data/sources/all.jsonl`
and never reads the other file. `sources_to_manifest.py` bridges them. Without
that step the loop reported `cycle 1: 614 transcripts, 39/50 leaders at target`
and then `no new transcripts this pass`: it knew eleven leaders were short and
fetched nothing, because the manifest still held 662 rows for the old 40 and not
one row for any new name. A quiet no-op, not an error.

**A withdrawn leader survives in `discovered.json` and the rebuild puts him
back.** `--only` rewrites just the named leaders' blocks, so `cc-wei` stayed in
that file after leaving the roster, and the first manifest rebuild returned 12
`cc-wei` rows. Eleven carry a `.json.superseded` marker and would have been
skipped. The twelfth, `cc-wei/norush-invest-9-odmj`, was never fetched and has no
marker, so the fetcher would have downloaded it and
`normalize_transcripts.py` would then have refused a transcript with no roster
entry, **breaking both loops on every cycle from then on**. Step 6b exists for
this.

**`--qa` is not optional.** `grade_loop.sh:96` passes
`--qa data/logs/transcript_qa.json` to the same script. The runbook omitted it,
so a manual run re-derived 52 QA-rejected transcripts and the loop's next cycle
removed them again: 116 files churned through git for a net corpus change of
zero.

## Applying this, in repo-0 only

The loops rewrite `data/` every few minutes. Stop them first.

```
# 1. stop the three loops (see AGENTS.md), then from repo-0:
ST=~/Code/misc/verbatim-index/roster-expansion-2026-09-10

# 2. retire the 10 on-board wrong-person recordings (the other clone's manifest)
.venv/bin/python scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json
.venv/bin/python scripts/withdraw_sources.py docs/withdrawals-2026-09-10.json --apply

# 3. retire the remaining 4 under cc-wei: the 2 off-board wrong-person ones,
#    and the 2 GENUINE TSMC ones, which retire preserves by rename
.venv/bin/python scripts/withdraw_sources.py $ST/withdrawals-cc-wei-completion.json
.venv/bin/python scripts/withdraw_sources.py $ST/withdrawals-cc-wei-completion.json --apply

# 4. install the roster and the aliases
cp $ST/final.json   data/roster/final.json
cp $ST/aliases.json data/sources/aliases.json

# 5. prune the derived copies and the grades, in BOTH modes.
#    --qa IS REQUIRED. grade_loop.sh:96 passes it; a run without it re-derives
#    every QA-rejected transcript, and the loop's next cycle deletes them again.
#    Cost is 116 files churned through git for a net corpus change of zero.
.venv/bin/python scripts/normalize_transcripts.py \
    --transcripts data/transcripts --roster data/roster/final.json \
    --repairs data/sources/repairs.json --aliases data/sources/aliases.json \
    --qa data/logs/transcript_qa.json \
    --mode blinded --out data/transcripts_blind --grades data/grades \
    --log data/logs/normalize_blinded.json
.venv/bin/python scripts/normalize_transcripts.py \
    --transcripts data/transcripts --roster data/roster/final.json \
    --repairs data/sources/repairs.json --aliases data/sources/aliases.json \
    --qa data/logs/transcript_qa.json \
    --mode open --out data/transcripts_open --grades data/grades \
    --log data/logs/normalize_open.json

# 6a. discover sources for the 11 new leaders only
.venv/bin/python scripts/discover_sources.py --roster data/roster/final.json \
    --out data/sources/discovered.json --target 14 --workers 8 \
    --only tobi-lutke,michael-saylor,eric-schmidt,ilya-sutskever,aaron-levie,\
dylan-field,amjad-masad,george-hotz,greg-brockman,vlad-tenev,alexandr-wang

# 6b. DROP THE WITHDRAWN LEADER FROM discovered.json BEFORE rebuilding the
#     manifest. discover_sources.py --only leaves every other leader's block
#     untouched, so cc-wei survives there even though he is off the roster, and
#     the rebuild would put his rows back. See "Two traps in the fetch path".
python3 - <<'PYEOF'
import json
p = "data/sources/discovered.json"
d = json.load(open(p))
roster = {x["slug"] for x in json.load(open("data/roster/final.json"))["roster"]}
if isinstance(d, list):
    kept = [e for e in d if e.get("leader_slug", e.get("slug")) in roster]
else:
    kept = {k: v for k, v in d.items() if k in roster}
json.dump(kept, open(p, "w"), indent=1)
print("discovered.json now holds", len(kept), "leaders")
PYEOF

# 6c. REBUILD THE FETCH MANIFEST. fetch_loop.sh reads data/sources/all.jsonl and
#     never reads discovered.json, so without this the new leaders are never
#     fetched and the loop says "no new transcripts this pass" with no error.
#     sources_to_manifest.py also REWRITES aliases.json and repairs.json, so send
#     those to scratch and re-check the installed aliases.json afterwards.
.venv/bin/python scripts/sources_to_manifest.py \
    --sources data/sources/discovered.json --manifest data/sources/all.jsonl \
    --aliases /tmp/aliases-scratch.json --repairs /tmp/repairs-scratch.json
shasum -a 256 data/sources/aliases.json | cut -c1-16   # must still be 4126314c60fab7a2

# 7. restart the loops with TARGET=14, then check
bash scripts/status.sh
.venv/bin/python scripts/coverage_table.py
```

`prune_orphans` removes 14 of roughly 570 derived transcripts, about 2%, well
under `PRUNE_MAX_FRACTION` of 0.25, so the guard will not trip.

`aggregate.py` iterates roster slugs only, so any grade left under
`grades/*/cc-wei/` is ignored rather than miscounted. Confirmed by running
`aggregate.py` against the 50-name roster over the live grades directory: 39
leaders scored, the 11 new ones correctly reported as `unscored`, C.C. Wei
absent, and only the six leaders ranked below him moved, each up exactly one
place.

## State as applied, 2026-09-11

`repo-0` applied this on 2026-09-10 (`data` commit `cabe302`). Verified here
rather than taken on report:

```
python3 -c "import json;r=json.load(open('data/roster/final.json'))['roster'];print(len(r),'cc-wei' in {p['slug'] for p in r})"
# 50 False
shasum -a 256 data/roster/final.json    | cut -c1-16   # 502019a4da8594a0
shasum -a 256 data/sources/aliases.json | cut -c1-16   # 4126314c60fab7a2
ls data/transcripts/cc-wei/*.json 2>/dev/null | wc -l  # 0
```

All 11 new leaders are fetched AND graded. Judge volume is balanced: the
largest fable/astra/gemini spread on any new leader is 1 grade, so the uneven
judge mix that `calibrate()` cannot repair did not appear.

### Three things still open

**The published site is STALE.** `data/` holds the 50-name board and `repo-0`
has a current build on disk, but `verbatim-index.tonygwu.com` still serves the
old page: it says "A roster of 40" and still lists C.C. Wei. Nothing is wrong
with the data; the deploy simply has not been run.

```
curl -s https://verbatim-index.tonygwu.com/ | grep -o "A roster of [0-9]*"
# stale while this prints "A roster of 40"
bash scripts/deploy.sh            # fixes it; runnable from ANY clone, read-only on data/
bash scripts/deploy.sh --refresh  # re-aggregates first; repo-0 ONLY, it writes results.json
```

**`fetch_loop.sh` has finished and will not resume itself.** It exited on its
own stopping condition, not a crash: `EXHAUSTED: 3 passes with no new
transcripts`. Every leader is well past the ranking floor of 5, but 12 are short
of `TARGET=14`: `ilya-sutskever` 7, `michael-dell` 11, then `aaron-levie`,
`alexandr-wang`, `george-hotz`, `greg-brockman`, `larry-ellison`,
`michael-saylor`, `sergey-brin`, `tobi-lutke` at 12, and `eric-schmidt`,
`vlad-tenev` at 13. Restarting the loop unchanged will re-exhaust immediately,
because the candidate lists are spent. Widening means going DEEPER into the
ranked list, `discover_sources.py --candidates-per-leader` above its default of
14, which is the safe widening; lowering `MIN_SEC` or raising `MAX_PER_CHANNEL`
instead admits clips and re-uploads.

```
tail -1 data/logs/fetch_loop.log        # the EXHAUSTED line and who is short
pgrep -fl "fetch_loop.sh" || echo "not running"
```

**Ilya Sutskever is the board's thinnest evidence and its highest score.** 73.6
on 6 graded transcripts, against a corpus median near 14. This is the Jeff Bezos
pattern named under "Known limits of the published score": a top rank resting on
the least material. It is not a defect in the pipeline, and it is a reason not to
read his rank as settled. Topping him up is the fix, and he is the leader the
retry budget should go to first.

## Recommended follow-up, not done here

`discover_sources.name_in()` is still surname-only, so the defect that produced
this incident is still live for every leader. It was left alone deliberately:
changing it alters which sources get fetched for all 50 while the loops are
running, and that deserves to be its own change with its own before-and-after.
The fix is the screen used above, promoted into the rejection path: require the
full name, or the surname plus a company token, and record a surname-only hit as
its own rejection category rather than accepting it.
