# Sourcing more scoreable predictions, swept 2026-09-15

Twelve parallel web sweeps: 5 backfilling thin roster members, 7 screening 51
adjacent candidates. Every verdict below is a subagent claim unless marked
VERIFIED, which means the main session re-derived it. Working files and the full
near-miss backlog are in the session scratchpad; the durable conclusions are here.

## The answer first

**The bottleneck is not predictions per person. It is PAST-DUE predictions per
person.** Computed from `data/predictions/`:

```
475 accepted predictions
  230 target date already past
  157 target date still future
   88 no target date at all
```

The site resolves 113 of 225 past-due, about half. So the effective bar for a
scored row is roughly **10 past-due predictions**, not 5 predictions.

## Who clears the bar

**Read the funnel before reading the table.** A subagent LEAD is not an accepted
prediction, and an accepted prediction is not a resolved one. Corpus evidence:

```
verifier acceptance          475/1494 = 0.32
past-due resolution          113/225  = 0.50
a scored row needs           5 resolved
=> 12 to 31 past-due LEADS per person, depending on how much better a
   pre-screened lead behaves than a raw candidate
```

**Nobody in this sweep returned that many.** The best was 8. So the lead counts
below are a DENSITY SAMPLE, not an inventory. Each agent mined a handful of
recordings. Rank by density times remaining archive, not by lead count.

| person | leads | recordings mined | density | archive | projects to |
|---|---|---|---|---|---|
| Mary Barra | 8 | ~3 | 2.7 | ~40 GM calls + keynotes | **very strong** |
| Cathie Wood | 7 | ~4 | 1.75 | ~90 ITK episodes | **very strong** |
| Emad Mostaque | 7 | ~4 | 1.75 | 70 videos >=20min | **very strong** |
| Brian Chesky | 6 | ~5 | 1.2 | ~20 Airbnb calls | strong |
| Chamath / Sacks | ~30 | 2 episodes | high | 4 past-due annual episodes | strong |
| Alex Karp | 5 | 12 | 0.42 | ~20 Palantir calls | moderate |
| Peter Beck | 5 | ~3 | 1.7 | ~8 calls per 2 years | moderate |
| Dario Amodei | 7 | ~6 | 1.2 | already on roster | moderate |
| Ray Kurzweil | 6 | ~3 | 2.0 | deep but re-upload-heavy | moderate |
| Hock Tan | 5 | 1 | 5.0 | replay likely EXPIRED | **blocked** |
| John Chambers | 6 | ~2 | - | 4 of 6 videos NOT FOUND | **blocked** |
| Steve Ballmer | 7 | 240 transcripts | 0.03 | **EXHAUSTED** | **weak** |

**Ballmer inverts on inspection.** A strict filter for 8-60 word windows carrying
a number, a horizon and a commitment marker returned 5 hits across all 240
Microsoft transcripts. The archive is huge and already mined out, and 5 of his 8
leads have no located recording. He looked like the safest name here and is one
of the weakest.

Unknown but promising, each with one untested seam that press coverage proves is
productive: **Gwynne Shotwell** (2019 Baron Investment Conference video) and
**Jim Farley** (Ford earnings calls, never reached).

**Nat Friedman produced the single best-shaped lead found anywhere**, at only 4
past-due: "running our numbers we predict by 2025 there will be over a hundred
million developers on github", GitHub Universe 2019, 2019-11-13, no serious gate
risk. TechCrunch reported it as "aiming for", which would have failed the gate.

## The five mechanisms that decide everything

1. **The CFO problem (G4).** On earnings calls the finance chief states the
   number and the CEO states strategy. MEASURED on five Block calls: CFO Amrita
   Ahuja produces 22 dated-and-numeric forward sentences, Jack Dorsey produces 1.
   Killed Narayen, Ek and most of Yuan too.
2. **The horizon problem.** Khosla, Ek, Son, Vitalik and post-2023 Hinton are
   real forecasters whose forecasts land 2028-2049. Being a good forecaster is
   not the qualification. Having already been right or wrong is.
3. **The translator problem (G4).** Masayoshi Son's two most quotable "English"
   uploads are simultaneous interpretation and dubbing. Proof from the caption
   text: the interpreter says "my name is Sun". The words are not his.
   This is a live corpus hazard for any non-English-native roster member.
4. **Transcript is not an ingestible recording.** Ballmer has 240 verbatim
   Microsoft transcripts and 5 of his 8 leads have no located recording.
5. **Speaker-labelled captions make G4 decidable.** Human caption tracks carry
   `>> NAME:` markers; auto-captions do not. In a multi-speaker recording the
   absence makes own-voice unprovable. One yt-dlp pull tells you which you have.

## The zero-prediction leaders: VERIFIED, and it is not a fetching problem

```
slug              candidates   extractor 5/5   verifier ok
fei-fei-li                3          3              0
ilya-sutskever            5          5              0
jack-dorsey              11         11              0
sergey-brin               3          3              0
tobi-lutke                5          5              0
                         27         27              0
verifier-failed gates: falsifiable=23, stands_alone=16, committed=6,
                       own_voice=2, forward_looking=2
```

The extractor passed all 27 at 5 of 5 gates; the verifier rejected all 27.
Corpus acceptance is 0.318, so 0 of 27 has probability 3.3e-05. Either the
verifier is right and these five speak in undated aspiration, or the
extractor's G2 judgement is miscalibrated for speakers of this kind and is
burning verifier quota. Worth its own investigation.

**Michael Dell is the opposite case and a true artefact.** All 9 of his corpus
transcripts are podcasts. No keynotes, no theCUBE, no earnings calls. All 8 of
his leads come from venue classes the corpus does not contain.

## Secondary sources are unreliable in four distinct ways

Found independently by six agents and VERIFIED once by the main session.

1. **Outlets manufacture commitment.** Novogratz's headline AND video title say
   "$40,000 bitcoin by end of 2018". The captions say "Bitcoin COULD be at
   40,000". Thiel's famous 100x quote turns out to be a subordinate if-clause.
2. **Outlets delete the speaker's own disclaimer.** Khosla appends "If I'm
   right, I'm often wrong" in the same breath. No article carries it.
3. **Outlets can make a claim WEAKER than the tape.** TechCrunch says Nat
   Friedman was "aiming for" 100M developers; he said "we predict".
4. **Transcript aggregators misattribute speakers.** podscripts.co filed a Brad
   Gerstner monologue under Bill Gurley. Gurley fell from 4 past-due leads to 1.

VERIFIED instance: the circulating Hinton radiology quote reads "we've got
plenty of radiologists"; the captions read "we got plenty". Statement date
2016-11-24, channel Creative Destruction Lab, video 2HMPRXstSvQ.

## Two new wrong-person shapes, both BETWEEN board members

Not a wrong video. The wrong speaker inside a correctly-attributed one.

- "by 2020 we're going to have a billion cameras all over the world" is JENSEN
  HUANG, in an ANDREW NG-titled GTC China video. Crispest dated claim in 27,000
  words, and not his.
- `bYM_VMs7EO0`, searched as Daniel Gross, is ALEXANDR WANG.

Subject-share cannot catch either: someone is speaking and the share is high.
`wrong_person_screen.py` catches this shape only after the judges are paid.

## Extraction must run per utterance, never per claim

Jesse Powell made the same Kraken-IPO claim three times in six weeks. It passes
G3 exactly once ("we're on track to go public next year"); the other two carry
"possibly" and "no guarantees". **A dedupe step that collapses one claim into
one row picks the wrong wording two times in three.** Dedupe recordings, never
utterances. The gate verdict is a property of the utterance.

## Measured quote accuracy

One agent audited 11 quotes its own sub-researchers reported, against source
captions. Ten verified exactly. One had an ASR gap the researcher silently
filled. **Working accuracy on delegated quotes is about 91%, not the 100%
agents claim.** Every lead in this sweep needs re-verification before
publication.

## The best untapped seams, in order

1. **Earnings calls.** Plain fetchable text on fool.com. Karp went from 1
   accepted prediction to 5 past-due leads on this seam alone. Carries the
   worst G4 risk, per mechanism 1.
2. **"ITK with Cathie Wood".** ~90 monthly episodes, 28-75 min, back to 2020.
   One 43-minute episode yielded three past-due dated claims.
3. **Annual predictions episodes.** All-In has four past-due years at ~10
   prompts per host. They also OPEN by scoring last year's calls aloud, naming
   who made each, which is a free attribution check and a resolution hint.
4. **Ford earnings calls.** Untested; Farley speaks first and Ford gives dated
   EV volume and margin targets quarterly.

## The discrimination warning

Amon's past-due claims are product-launch windows, and a chip company nearly
always ships the chip it announced. `PREDICTIONS-SCORING.md` already found this
for Andy Jassy: 41 predictions, mean +0.049, "a corporate roadmap is a
near-zero-information forecast". **Recruiting more roadmap CEOs pads the board
without sharpening it.** Weight toward people who make external-world calls.

## Decisions waiting on the operator

- **The venture-investor rule.** `ROSTER-EXPANSION-2026-09-10.md:162` excludes
  investors. It blocks Andreessen, Chamath, Sacks, Gurley, Khosla, Wood and Tom
  Lee. Chamath and Sacks are the cheapest large win available; Wood is the most
  productive single name found. Flipping the rule is the one-line decision that
  document already describes.
- **"on track to".** DECIDED 2026-09-15: read as committed. Gains 6 leads
  across Barra, Beck and Amon. "we want to" stays rejected.
