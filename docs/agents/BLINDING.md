# Blinding

Part of this repository's working agreement. [AGENTS.md](../../AGENTS.md) holds
what every agent needs on every task and is loaded at the start of every
session. This file is read on demand. Read it before you change `blind()`, an
alias list or `scripts/blind_wordlist.json`, or reason about what a judge can
infer about the speaker.

The text below moved here unchanged from AGENTS.md, under the heading it had
there. Add new material under the same headings.

## Experiments run, and what they showed

**Can blinding be made to work?** (2026-09-07) Built five progressively harder
redactions of one transcript, from the shipped name-and-company blinding up to
183 removed spans with no company, product, colleague, place or year left, then
asked both judges to name the speaker at each level. Ten calls, ten correct, ten
confident, replicated on a second leader. Redaction was mechanical, by script,
so the prose was unchanged; a model proposed the entity list and never rewrote
the text. CONCLUSION: identity leakage is not fixable by more redaction. What
survives is the argument, not the nouns — a distinctive strategy, a program of a
stated age, a public position taken against a named rival — and that is exactly
what the rubric grades. Fable also reconstructed redacted words and presented
them as quotes, so the model recognises the EVENT, not just the entities.

## Known limits of the published score

- **The blinder replaced ordinary English words, because an alias list carried
  bare parts of a company name. FIXED in code 2026-09-13 (`528509a`), opt-in,
  and MEASURED not to move the score, so the corpus was NOT re-derived.** `blind()` applies every entry in
  `data/sources/aliases.json` unconditionally, case-insensitively, through the
  NAME path, so the replacement token is `[SUBJECT]` and not `[COMPANY]`. The
  alias lists come from the discovery workflow and hold the parts of a
  multi-word company: `yann-lecun` has "Machine", "Intelligence" and "Labs" out
  of "Advanced Machine Intelligence Labs", `tim-sweeney` has "Games",
  `fei-fei-li` has "World", `clem-delangue` has "Face", `thomas-kurian` has
  "Cloud". `company_variants()` can do the same on its own path, and only
  `fuzzy_targets()` consults the system dictionary; neither the exact-form path
  nor the alias path does.

  MEASURED 2026-09-11 over `data/transcripts_blind`, taking every substitution
  whose token is a bare part of a multi-word company name and counting the
  LOWERCASE occurrences of that token in the matching unblinded file under
  `data/transcripts_open`. Lowercase, because that is the ordinary-prose use
  rather than the company reference, and the blinder's regex is case-insensitive
  so it takes both. Two readings, because the wide one is not all damage:

  ```
  any bare company part          2,976 occurrences  176 transcripts  20 leaders
  token also a dictionary word   2,038 occurrences  130 transcripts  15 leaders
  ```

  The wide figure includes "uber" 250 and "google" 109, which really are the
  company said in lowercase and are correctly removed. The narrow one is the
  floor, and its largest entries are "world" 453 for Fei-Fei Li, "machine" 300
  and "intelligence" 230 for Yann LeCun, "face" 225 for Clem Delangue and
  "cloud" 206 for Thomas Kurian. Add "games" 377 for Tim Sweeney, which the
  narrow measure misses only because `/usr/share/dict/words` holds no plurals.
  What the judge actually reads is `"the history of artificial [SUBJECT]"` and
  `"the experience of playing and creating video [SUBJECT]"`.

  Two reasons this is worse than the leakage it sits beside. The damage lands on
  exactly the domain vocabulary the rubric grades, so a game designer loses the
  word "games" and an AI researcher loses "machine" and "intelligence". And the
  token inserted is the one that means "the person being graded", so the judge
  reads an ordinary noun as a reference to the subject.

  `scripts/test_blinding.py` passes and cannot catch this. All five of its cases
  probe the FUZZY path for overreach, no case puts a common word in the alias
  list, and the one bare company part they do assert survives is "cloud", which
  `GENERIC_COMPANY_WORDS` already exempts by hand. The roster works around the
  defect per person in the one place it was noticed, recording Michael Saylor's
  company as "MicroStrategy" rather than its current legal name "Strategy",
  because `company="Strategy"` redacted the ordinary word "strategy" three times
  in an 80-word test paragraph. The reason is written into his
  `selection_rationale`. That is a patch on one name, not a fix.
  RE-MEASURED 2026-09-13 by blinding all 664 transcripts both ways and diffing,
  which is the only figure that counts what a judge actually gets back:

  ```
  ordinary words handed back    1,859   135 transcripts   15 leaders
  [SUBJECT] -> [COMPANY]       13,223   every transcript  50 leaders
  ```

  The 2,976 figure above is the LOOSE one and should not be quoted. It counts
  lowercase occurrences of bare company tokens in the unblinded text, which
  includes every "face" inside "Hugging Face" that the blinder had already
  replaced as a phrase and that was never standalone prose. It over-counts by
  about 50%. The relabel count is the larger defect and the one that reaches
  every leader.

  THE FIX. Two signals decide, because each covers the other's failure.
  `/usr/share/dict/words` is `web2`: 236k entries, no plurals, and it carries
  proper nouns, so alone it calls "Elon" and "Musk" English words and misses
  "games". Corpus spread, the share of a token's lowercase uses falling outside
  the leader who owns the alias, alone frees "google" at 0.80 because everyone
  talks about Google. A token is ordinary only if BOTH agree, and an ordinary
  token is STILL redacted where it is CAPITALISED, which is the same signal
  `fuzzy_targets()` already relies on. VERIFIED in this corpus: "games" is
  capitalised 23 times against 377 lowercase, "uber" 491 against 250.
  The threshold sits in an empty band rather than on a round number: sorted by
  spread the candidates run 0.76 Face, 0.73 Games, then a gap to 0.61
  Playground and 0.42 Epic, so the cutoff is 0.70. Below 20 lowercase uses
  spread is noise and "Prometheus" scored 1.00 on one occurrence, so that floor
  is explicit. 15 of 28 candidates come out ordinary; Google, Uber, Hugging,
  Mistral, Palantir, Anduril, DeepMind and Epic stay fully redacted.
  The decision is FROZEN into `scripts/blind_wordlist.json` with its evidence,
  because spread is a property of the corpus and the corpus grows. Regenerate it
  deliberately with `scripts/build_blind_wordlist.py --write`, never at runtime.

  IT IS OPT-IN AND STILL OFF. `blind()` keeps the original behaviour unless a
  wordlist is passed, because `grade_loop.sh` normalizes every cycle and would
  otherwise re-blind the corpus under 2,260 existing grades. VERIFIED
  byte-identical on 60 randomly sampled transcripts: the default path reproduces
  the substitution map on disk exactly, 60 identical and 0 different. Promotion
  is passing the list at the call site, deliberately a diff.
  `discover_sources.aliases_for()` now honours `GENERIC_COMPANY_WORDS`, imported
  from the blinder rather than restated, so "Cloud" and "Labs" stop entering the
  list at source. That is the weaker of the two guards: it cannot judge
  "Machine" or "Games", which need corpus frequency a new leader does not have.
  Guarded by `scripts/test_blind_common_words.py`, 41 checks, verified failing
  before the fix and passing after BEHAVIOURALLY rather than by import error:
  the three worst real cases survive 0 of 4 assertions on the old code and 4 of
  4 on the new.

  WHY THE CORPUS WAS NOT RE-DERIVED. A controlled A/B on the 18 worst-hit
  transcripts, both arms graded fresh and concurrently against a frozen
  snapshot, all three judges, 48 complete pairs
  (`docs/BLINDING-EXPERIMENT-2026-09-13.md`):

  ```
  POOLED  mean B-A -0.14  95% CI [-1.15, +0.88]  MDE 1.45  n=48
  PROSE   -0.35 [-1.40, +0.71]      RELABEL  +0.28 [-1.95, +2.52]
  ```

  Dose-response settles it: the correlation between words restored and change
  in grade is -0.151, near zero and pointing the WRONG WAY for a corruption
  effect. The sd of the paired difference is 3.58, against Fable's own re-run sd
  of 3.24 on unchanged text, so the experiment is mostly measuring judge noise.
  That is consistent with the limit below: a judge that has already identified
  the speaker reads straight through a hole in the prose.
  The claim is "nothing this board can resolve", not "exactly zero". The 18 are
  the worst-damaged in the corpus, so the figure bounds the effect from ABOVE.
  Re-grading would cost about 1,992 calls to move a number by less than its own
  noise. Third time in this repo that a defect alarming in the text did not
  reach the score, after the wrong year and the paragraph loops.

- **The blinding does not work, and the header still claims it.** Judges are
  confident of the speaker's identity on 99.5% of transcripts and are right
  99.6% of the time. An experiment on 2026-09-07 built five progressively harder
  redactions of one transcript, up to 183 removed spans with no company, product,
  colleague, place or year left, and both judges identified the speaker at every
  level, replicated on a second leader. What survives redaction is the argument,
  not the nouns: a distinctive strategy, a program of a stated age, a public
  position taken against a named rival. That is exactly what the rubric grades.
  Fable also reconstructs redacted words and presents them as quotes.
  `blind()` replaces only the subject's name and company, and nothing else.
  7 transcripts have ZERO substitutions and 80 have fewer than one per 1000
  words; `arthur-mensch/no-priors-ai-machine-lea-emofrd` got 3 in 6044 words
  because `fuzzy_targets` skips tokens that are real English words and the
  surname corrupts to "Munch".
