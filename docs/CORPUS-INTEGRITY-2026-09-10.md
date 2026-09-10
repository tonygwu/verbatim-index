# Corpus integrity findings, 2026-09-10

Found by repo-2 while running a prediction-extraction probe over 80 transcripts
(2 per leader, seed 20260909, from `data/transcripts_open`). The probe read
1,075,314 words with 16 parallel sub-agents. These defects were incidental to
that probe, not the object of it, so **every count here is a floor, not a total.**

Nothing in `data/` was modified. All findings are read-only observations.

---

## 1. `declared_year` is a hardcoded constant, and it reaches every judge prompt

Every source manifest record carries `year: 2024`:

```
$ python3 -c "...scan data/sources/**/*.jsonl for 'year'..."
manifest records with year: 662 {2024: 662}

$ ...scan data/transcripts_open for declared_year...
declared_year values across 550 transcripts: {2024: 529, 0: 30}
declared_year == yt_upload_date year:  55
declared_year != yt_upload_date year: 469
offset histogram (upload_year - declared_year):
  {-15: 2, -13: 1, -12: 6, -11: 11, -10: 6, -9: 9, -8: 12, -7: 8,
   -6: 15, -5: 28, -4: 21, -3: 29, -2: 33, -1: 47, 1: 128, 2: 113}
```

`scripts/grade.py:525` (blinded) and `scripts/grade.py:543` (open) both emit:

```python
f"Approximate year: {rec.get('declared_year')}\n"
```

So every judge, on every grade in the corpus, was told the recording is from
2024. Real upload years span 2009 to 2026. On 30 transcripts the prompt reads
`Approximate year: 0`.

Set by `scripts/fetch_transcripts.py:343` from `src["year"]`, and by
`scripts/fetch_happyscribe.py:307` as a literal `0`. The correct value is
already on the record as `yt_upload_date` (present on 524 of 559).

**Unknown, and worth measuring:** whether this moves any published score. It
touches 100% of grades, which makes it the widest defect here, but width is not
the same as effect size. A judge may barely use the year.

## 2. Wrong-person transcripts, which the share filter cannot catch

15 transcripts are confirmed to be a different person from the leader they are
filed under. Each is proven by the source's own `yt_title`, not by inference.

| Leader | Transcript | Who is actually speaking |
|---|---|---|
| cc-wei | `adobe-creative-cloud-1l--yn` | Jing Wei (designer) |
| cc-wei | `bankless-tik8am` | Eugene Wei |
| cc-wei | `danny-haiphong-k-c3ae` | Zhang Weiwei (political scientist) |
| cc-wei | `george-daniel-swpx7b` | Weivy Wei |
| cc-wei | `han-wei-shen-ughuv0` | Han-Wei Shen (OSU professor) |
| cc-wei | `mit-civil-and-environmen-rwmwc3` | Wei Chen |
| cc-wei | `newton-free-library-9aab7z` | William Wei |
| cc-wei | `six-five-media-rmprp4` | Wei Li (Intel) |
| cc-wei | `ted-hahs-iyee3v` | Lord Nat Wei |
| cc-wei | `usacm-juvcrj` | Wei Chen |
| michael-dell | `project-nanda-wj3xga` | John Roese, CTO of Dell |
| michael-dell | `pursuit-jtc6uo` | Adam Dell |
| arvind-krishna | `preetika-rao-and-s-aishw-n-i6g5` | a devotional talk on Tirupati Balaji |
| jeff-bezos | `hal-sparks-olznjg` | two hosts discussing Bezos |
| tim-sweeney | `kaput-magazin-f-r-insolv-nddwao` | Tim Sweeney of Beats in Space |

Only 2 of C.C. Wei's 12 transcripts are TSMC's C.C. Wei. He is published at
rank 33 on n=12, so his score is built ~83% from other people.

**All 15 are ON the board.** The subject-share filter is structurally blind to
this, because it measures whether *someone* is speaking, not whether the *right*
someone is:

```
cc-wei  han-wei-shen-ughuv0    {astra: 100, fable: 100, gemini: 100}  100.0  YES
cc-wei  mit-civil-and-environ  {astra:  93, fable:  95, gemini:  95}   94.3  YES
cc-wei  usacm-juvcrj           {astra:  91, fable:  92, gemini:  92}   91.7  YES
```

A wrong-person transcript produces a HIGH share score and maximum agreement.

Two failure modes in source selection: surname collision (13 cases) and
"about the subject" mistaken for "by the subject" (2 cases).

## 3. The 10% subject-share cutoff averages contradictory judge readings

`CLAUDE.md` records that judges agree closely on share, median absolute
disagreement 2 points. True in aggregate, and it hides a tail:

```
recordings with >=2 blinded judge share estimates: 553
  spread median 5, mean 6.6, p90 11, max 86
  recordings where judges disagree by >50 points: 10

INCLUDED although at least one judge scored it under 10%: 11
  of those, at least one judge said 0%: 10
    jeff-bezos       hal-sparks-olznjg     {astra: 0, fable: 0, gemini: 42} mean=14.0
    tim-cook         the-compound-wl6bbk   {astra: 0, fable: 0, gemini: 62} mean=20.7
    mark-zuckerberg  hs-sacha-baron-cohen  {astra: 0, fable: 0, gemini: 65} mean=21.7
    lip-bu-tan       oxide-computer-compa  {astra: 0, fable: 0, gemini: 68} mean=22.7
    jeff-bezos       this-week-in-startups {astra: 0, fable: 0, gemini: 70} mean=23.3
    mustafa-suleyman madras-management-ass {astra: 0, fable: 0, gemini: 71} mean=23.7
    tim-cook         the-bulwark-and-prof  {fable: 0, gemini: 68}           mean=34.0
    arvind-krishna   preetika-rao-and-s-a  {astra: 60, fable: 0, gemini: 58} mean=39.3
    jeff-bezos       bigdeal-by-codie-san  {astra: 73, fable: 0, gemini: 68} mean=47.0
    demis-hassabis   metis-strategy-fu1xty {astra: 78, fable: 0, gemini: 86} mean=54.7

EXCLUDED although at least one judge scored it >= 10%: 3
```

When one judge says 0 and another says 68, that is not noise around a value.
The judges disagree about whether the subject is in the recording at all, and a
mean is the wrong summary for that. Median would drop 6 of the 10; an
"any judge says 0" rule would drop all 10.

Which judge dissents is mixed, so this is not a single-arm problem:

```
when judges disagree by >20pts, the LOW judge is:  {fable: 5, astra: 6, gemini: 1}
                             the HIGH judge is:  {astra: 4, gemini: 8}
share==0 rate by judge: astra 21/545 (3.9%), fable 24/553 (4.3%), gemini 12/536 (2.2%)
```

Note the filter DOES work when judges agree. `evan-spiegel/group-chat-news-9n0o-s`
is a show about Spiegel where he never speaks; all judges scored it 0 and it is
correctly excluded.

## 4. Paragraph-scale caption looping survives `loop_collapse`

Measured as the share of 40-word blocks that are exact repeats of an earlier
block, at stride 40, over 559 transcripts:

```
  >10% of 40-word blocks are exact repeats:   3 (0.5%)
  median repeat share: 0.00%

  19.6%  sam-altman     the-economic-times-vfilis   64068w  loop_collapse removed=3
  14.3%  sam-altman     ani-news-ulh6ww             27811w  loop_collapse removed=0
  12.3%  dario-amodei   india-today-global-jny7oq    6118w  loop_collapse removed=8
   4.6%  demis-hassabis ht-india-mg8tpp             42995w  loop_collapse removed=137
```

Narrow (3 transcripts) but it hits the largest transcript in the corpus.
`loop_collapse` handles short token runs and not paragraph-scale repetition.
On `dario-amodei/india-today-global-jny7oq` a 120-character probe occurs 6 times.

## 5. NOT a defect: Evan Spiegel

Recorded here because repo-2 asserted it in error and then withdrew it.

The claim was that Spiegel's transcripts do not contain him speaking. **False.**
He has 14 transcripts, 11 included, and he speaks heavily in the included ones
(57-93% share). The one where he never speaks was correctly excluded by all
three judges at 0%.

He scored 0 qualifying predictions in the probe because in
`kleiner-perkins-xkc5xo`, where he holds 60.3% of the words, his forward-looking
statements are vague and unfalsifiable ("Specs will be transformational").
That is a measured trait, not contamination.

---

## Scope, stated honestly

Included recordings on the board: 537 of 559.

- Defect 1 touches 100% of grades. Effect on published scores is UNMEASURED.
- Defect 2 touches 15 of 537 included transcripts (2.8%), destroying 1 leader
  of 40 and denting 4 more.
- Defect 3 touches 10 recordings.
- Defect 4 touches 3 recordings.

Defects 2, 3 and 4 do not invalidate a large fraction of the board on their own.
Defect 1 might, and nobody has measured it.
