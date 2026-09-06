---
name: grader-validation
description: Validate the LLM-judge rubric without human labels by measuring inter-rater reliability, probing length and order bias, testing construct validity of the three dimensions, and running known-answer degradation probes.
---

# Validating the grader without human labels

Ordered by value per unit of effort. Tier 1 runs on grades already on disk. Tier 2 needs new judge calls at
roughly 3 USD-equivalent each. Tier 3 is rejected, with the reason.

Marks: **DOCUMENTED** (published, cited inline), **COMMUNITY** (wide convention, no single authority),
**MEASURED** (computed here), **UNKNOWN** (nobody has established it). MEASURED numbers use the 2026-09-05
snapshot: 36 judge calls, 31 usable, 4 refusals, 1 unscorable, 8 paired blinded transcripts. The corpus grows
while the fetch loop runs, so re-run rather than trust these.

Know the ceiling before starting. Everything here measures **reliability**, meaning the judge repeats itself and
resists irrelevant change. None of it establishes **validity**, meaning the score tracks speaking quality.
DOCUMENTED: with zero gold labels no unbiased estimate of judge accuracy exists by any method, and no debiasing
can cut a labelling budget by more than 2x ([Dorner et al. 2024](https://arxiv.org/abs/2410.13341)). Reliability
and validity genuinely come apart. One judge was more self-consistent than three human experts were with each
other while agreeing with them worse than chance on two of four dimensions ([Chaudhary et
al.](https://arxiv.org/abs/2412.09269)).

Save the loader as `scripts/gv.py`. It needs numpy and scipy only, since `pingouin` and `statsmodels` are not
installed here.

```python
import json, glob, itertools, numpy as np
from collections import defaultdict
from scipy import stats
ROOT = "/Users/tonygwu/Code/public-leader-speaking-analysis"
DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]

def grades(mode="blinded"):
    """Every judge call, refusals and unscorable grades flagged not ok."""
    for p in glob.glob(f"{ROOT}/data/grades/*/*/*.json"):
        r = json.load(open(p)); g = r.get("grade", {})
        r["unscorable"] = "dimensions" in g and g.get("coverage", 1) == 0
        r["ok"] = (not r.get("validation_errors") and "dimensions" in g
                   and g.get("coverage", 0) > 0 and g.get("subject_speech_share_pct", 0) > 0)
        if mode is None or r["mode"] == mode:
            yield r

def paired(mode="blinded"):
    """{transcript_id: {judge: grade}} for transcripts BOTH judges scored."""
    by = defaultdict(dict)
    for r in grades(mode):
        if r["ok"]: by[r["transcript_id"]][r["judge"]] = r["grade"]
    return {t: v for t, v in by.items() if len(v) == 2}

P = paired(); tids = sorted(P)      # every sketch below assumes these two
```

**The noise floor.** Compare every probe against repeat noise, never zero. MEASURED,
`data/logs/calibration.json`, 5 repeats of one fixture: composite SD 1.29 Fable, 1.78 Astra. A paired probe with
`r` repeats on `m` transcripts detects `1.96*sqrt(2)*1.78/sqrt(r*m)` points, so r=3 m=1 gives 2.8, r=3 m=3 gives
1.6, r=1 m=1 gives 4.9. That SD comes from one transcript, so noise on an ambiguous one is UNKNOWN until P7
runs. Temperature 0 does not make a hosted API deterministic, so repeat noise never reaches zero ([Thinking
Machines 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)).

# Tier 1. Runs today, no model calls

## V0. Refuse to average a non-score

**Tests** whether anything on disk is a placeholder rather than a judgement. Run first, because it changes every
other number. **Pass:** no unscorable grade reaches `aggregate.py`.

```python
for r in grades(None):
    if r["unscorable"] or not r["ok"]:
        print(r["judge"], r["transcript_id"], "unscorable" if r["unscorable"] else "refused")
```

**MEASURED.** One found. `andy-jassy/tech-news-weekly-qpvhgj` is a podcast *about* Andy Jassy in which he never
speaks. Astra marked all 15 sub-criteria not observed, set `coverage` and `subject_speech_share_pct` to 0, then
wrote 1/1/1 and called it "a schema-required placeholder". `validate()` passed it. That single 1 raised the
leader's between-transcript SD from 2.6 to 35.1, and it feeds `calibrate()`, shifting one judge's mean and
inflating its SD for **every** leader. Add `status: "unscorable"` to the schema so a judge can decline without
inventing a number, and gate stage 3 on `subject_speech_share_pct`, the detector that exists and that nothing
reads.

## V1. Split judge agreement into rank and level

**Tests** whether the judges order transcripts alike, and separately whether they agree on level. Recentring
touches only level. Headline ICC(3,1), two-way mixed, consistency, single measure, because these two judges are
the only judges of interest and a constant offset is tolerated by design. Publish ICC(2,1), absolute agreement,
beside it to show what the offset costs. Add Lin's concordance coefficient split into precision (rho) and
accuracy (Cb), since Cb isolates what recentring removes, plus Bland-Altman bias and limits, which are in score
units. DOCUMENTED: the form must be named, because consistency ignores a systematic rater offset and absolute
agreement does not ([Koo & Li 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4913118/)).

```python
def icc(M):                              # rows = transcripts, cols = judges
    n, k = M.shape; gm = M.mean()
    MSR = k * ((M.mean(1) - gm) ** 2).sum() / (n - 1)
    MSC = n * ((M.mean(0) - gm) ** 2).sum() / (k - 1)
    MSE = ((M - M.mean(1, keepdims=True) - M.mean(0, keepdims=True) + gm) ** 2
           ).sum() / ((n - 1) * (k - 1))
    return dict(icc21=(MSR - MSE) / (MSR + (k-1)*MSE + k*(MSC - MSE)/n),
                icc31=(MSR - MSE) / (MSR + (k-1)*MSE))

M = np.array([[P[t]["fable"]["overall"], P[t]["astra"]["overall"]] for t in tids])
x, y = M[:, 0], M[:, 1]; d = y - x
ccc = 2*np.cov(x, y, bias=True)[0,1] / (x.var() + y.var() + (x.mean()-y.mean())**2)
rho = np.corrcoef(x, y)[0, 1]
print(icc(M), f"CCC={ccc:.3f} precision={rho:.3f} Cb={ccc/rho:.3f}")
print(f"bias={d.mean():+.1f} LoA=[{d.mean()-1.96*d.std(ddof=1):.1f},"
      f"{d.mean()+1.96*d.std(ddof=1):.1f}]", stats.linregress(M.mean(1), d).pvalue)
```

**Pass.** ICC(3,1) at or above 0.75, with its 95% interval rather than a point estimate. Bands poor <0.50,
moderate 0.50-0.75, good 0.75-0.90, excellent >0.90, DOCUMENTED (Koo & Li). Bland-Altman limits narrower than
the leaderboard spread, and a proportional-bias slope that is not significant, or the offset is not constant and
one recentring cannot fix it ([Bland & Altman
1986](https://www.ajo.com/article/s0002-9394\(08\)00773-3/fulltext)).

**MEASURED, n=8.** ICC(3,1)=0.871, ICC(2,1)=0.666, CCC=0.636 with precision 0.924 and Cb=0.688, bias +8.2,
limits [-1.9, +18.3], slope p=0.063. The judges rank almost identically, differ badly on level, and the offset
grows with the score. Do not headline Krippendorff's alpha: it suits missing data and varying rater counts,
DOCUMENTED with 0.800 good and 0.667 tentative ([Rating Roulette 2025](https://arxiv.org/html/2510.27106v1)),
but it cannot separate offset from disagreement.

**Two judges agreeing is weaker evidence than the README claims.** DOCUMENTED: a panel of 9 frontier judges from
7 families carries about 2 independent votes, and cross-family error correlation is as high as same-family, with
GPT-4o against Claude at phi=0.588 ([Kohli 2026](https://arxiv.org/abs/2605.29800)). Different vendors do not
buy independence. Treat agreement as a shared prior and **disagreement** as the informative signal, so route
high-disagreement transcripts to review rather than averaging them away.

## V2. Estimate the offset on the paired subset only

**Tests** whether `aggregate.py` measures judge severity or corpus composition. `calibrate()` takes each judge's
mean over everything that judge graded, so when one judge refuses a transcript the two means come from different
corpora. **Pass:** artefact under 1 point.

```python
for dim in DIMS:
    allj = defaultdict(list)
    for r in grades("blinded"):
        if r["ok"]: allj[r["judge"]].append(r["grade"]["dimensions"][dim]["score"])
    unb = np.mean(allj["astra"]) - np.mean(allj["fable"])
    pair = np.mean([P[t]["astra"]["dimensions"][dim]["score"]
                    - P[t]["fable"]["dimensions"][dim]["score"] for t in tids])
    print(dim, f"unbalanced {unb:+.2f} paired {pair:+.2f} artefact {unb-pair:+.2f}")
```

**MEASURED.** Clarity +1.51, insight +0.33, technical depth +3.01. Technical depth fails: 3 points of a
9.5-point "judge offset" is corpus composition, close to the whole tie band. Estimate `judge_mean` and
`judge_sd` on the paired subset, or fit transcript and judge effects jointly, the established rater-severity
method ([many-facet Rasch](https://www.winsteps.com/facetman/theory.htm)).

## V3. Put the right error bar on the leaderboard

**Tests** the published tie band. `calibration_report.py` sets it to `2.77 * within-judge SD` = 4.3, which is
repeat noise on one unchanged transcript. A leader's score averages several *different* transcripts, and task
variance is a separate error source, usually larger than rater variance ([generalizability
theory](https://www.sciencedirect.com/science/article/pii/S2666557325000370), DOCUMENTED).

```python
byl = defaultdict(list)
for r in grades("blinded"):
    if r["ok"]: byl[(r["transcript_id"].split("/")[0], r["judge"])].append(r["grade"]["overall"])
for k, v in sorted(byl.items()):
    if len(v) > 1:
        se = np.std(v, ddof=1) / np.sqrt(len(v))
        print(k, f"n={len(v)} sd={np.std(v,ddof=1):.1f} tie_band={1.96*np.sqrt(2)*se:.1f}")
```

**Pass.** The published band is at least the median leader's `1.96*sqrt(2)*se`. Better, bootstrap the ranking
over transcripts and publish rank intervals, COMMUNITY practice on LLM leaderboards ([Miller
2024](https://arxiv.org/abs/2411.00640)). **MEASURED, 3 leaders.** Per-judge tie bands run 4.1 to 21.4, so the
published 4.3 understates the noisiest leader by about 5x.

## V4. Discriminant validity of the three dimensions

**Tests** whether the rubric measures three things or one thing three times. Build a multitrait-multimethod
matrix, traits = the dimensions, methods = the judges (Campbell & Fiske 1959). **Pass:** every same-dimension
cross-judge value beats every different-dimension value, and the heterotrait-monotrait ratio stays below 0.85,
COMMUNITY.

```python
X = {(j, d): np.array([P[t][j]["dimensions"][d]["score"] for t in tids])
     for j in ("fable", "astra") for d in DIMS}
conv = [np.corrcoef(X[("fable", d)], X[("astra", d)])[0, 1] for d in DIMS]
het_mono = [np.corrcoef(X[(j, a)], X[(j, b)])[0, 1]
            for j in ("fable", "astra") for a, b in itertools.combinations(DIMS, 2)]
het_het = [np.corrcoef(X[("fable", a)], X[("astra", b)])[0, 1]
           for a in DIMS for b in DIMS if a != b]
print(conv, het_mono, het_het, "pass:", min(conv) > max(het_het))
```

**MEASURED, n=8.** Convergent 0.91 / 0.81 / 0.91. Same judge across dimensions reaches 0.98 (Astra clarity
against technical depth), and different dimension across judges reaches 0.94, so the criterion **fails**.
Cronbach's alpha over all 15 sub-criteria is 0.85 for Fable, about equal to the within-dimension 0.86 / 0.80 /
0.91, so one general factor explains most of the variance.

**This is a known artefact of scoring several attributes in one generation, and it has a fix.** DOCUMENTED: when
a judge emits consecutive attribute scores in one pass they correlate at r=0.979, while the same attributes
scored by humans correlate at r=0.315, and the authors' recommendation is one attribute per generation
([Stureborg et al. 2024](https://arxiv.org/abs/2405.01724)). Our rubric asks for 15 sub-criteria and 3
dimensions in a single call, which is exactly that condition. Highest-value fix: grade each dimension in its own
call, then re-run this check and see whether 0.98 falls. Cheaper interim: publish a composite plus a residual
profile, since weights of 0.20 / 0.45 / 0.35 do almost nothing once the dimensions are collinear. A 0.9
correlation is not automatically a defect, since real speaking ability is correlated across facets, but you
cannot tell halo from truth while one call produces all three numbers. Do not run factor analysis below n=100
with 15 variables, COMMUNITY. `not_observed` is stored as `0`, which is not a score on a 1-5 scale, so drop
those cells; `calibration_report.py` folds them into an SD today.

## V5. Length, venue and fame confounds

**Tests** whether score tracks anything but content. Transcripts run 11k to 30k words. Run all three covariates
together, because they are one variable wearing three hats.

```python
tr = {f"{t['leader_slug']}/{t['source_id']}": t for t in
      (json.load(open(p)) for p in glob.glob(f"{ROOT}/data/transcripts_blind/*/*.json"))}
wc = np.array([tr[t]["word_count"] for t in tids], float)
vw = np.array([tr[t]["yt_view_count"] for t in tids], float)
vc = np.array([P[t]["fable"]["venue_challenge"] for t in tids], float)
for j in ("fable", "astra"):
    s = np.array([P[t][j]["overall"] for t in tids])
    r_sw, r_sv, r_wv = (np.corrcoef(a, b)[0,1] for a, b in ((s, wc), (s, vc), (wc, vc)))
    part = (r_sw - r_sv*r_wv) / np.sqrt((1 - r_sv**2) * (1 - r_wv**2))
    print(j, stats.spearmanr(wc, s), stats.spearmanr(np.log(vw+1), s), "partial|venue", round(part, 2))
```

**MEASURED, n=8.** Astra: Spearman with words +0.74 (p=0.037), partial +0.59 controlling venue challenge, with
log views +0.71 (p=0.047). Fable: +0.36 (p=0.385) and +0.60 (p=0.120). Keynotes average 64.8 and fireside chats
47.4, the opposite of what the rubric's venue guidance predicts.

**Do not report this as length bias, and do not regress length out.** The closest published analogue is
pointwise scoring of long human-authored documents, and it found both halves at once: observationally a response
gained 0.125 points per 10% of extra length, yet doubling a response by repeating its own content **lowered**
the score ([Chuang et al. 2025](https://arxiv.org/abs/2502.15094)). Length correlates with score through
content, not through bias. Verbosity bias itself is DOCUMENTED ([Zheng et al.
2023](https://arxiv.org/abs/2306.05685)) but has weakened sharply in 2026-era judges. Regressing length out is
also not safe by default: the split between quality and bias is provably not identifiable from scores alone, and
correcting helps only when true quality is weakly correlated with length ([Xu et al.
2026](https://arxiv.org/abs/2607.02104)). Use V5 to size the problem and P1 to answer it.

## V6. Halo, distribution, refusals

```python
ob = defaultdict(dict)                                   # halo: open vs blinded
for r in grades(None):
    if r["ok"]: ob[(r["transcript_id"], r["judge"])][r["mode"]] = r["grade"]["overall"]
dd = np.array([v["open"] - v["blinded"] for v in ob.values() if len(v) == 2])
print(len(dd), dd.mean(), stats.wilcoxon(dd))
v = np.array([r["grade"]["dimensions"][d]["score"]        # scale actually used
              for r in grades(None) if r["ok"] for d in DIMS])
print(v.min(), v.max(), len(set(v.tolist())), np.mean(v % 5 == 0))
c = defaultdict(lambda: [0, 0])                           # refusals
for r in grades(None):
    k = (r["judge"], r["transcript_id"].split("/")[0])
    c[k][1] += 1; c[k][0] += 0 if r["ok"] else 1
print(dict(c))
```

**Halo.** Pass is a shift inside the tie band with Wilcoxon not significant. MEASURED, n=14 pairs: +0.13, SD
3.29, p=0.98. Passes, and this is the project's strongest positive result. It deserves more prominence than the
100% blinding-leakage figure, which sounds worse than it is.

**Distribution.** Pass is a round-number share near 0.20 (chance for multiples of 5) and at least 20 distinct
values. MEASURED, n=93: range 28-84, 43 distinct values, share 0.204. Passes, which is better than the
literature predicts: a judge grading 1,000 essays on 1-100 clustered on multiples of five and favoured 65
([CBEval](https://arxiv.org/abs/2412.03605)), and another concentrated scores in 70-100 with peaks at 90 and 95
([Stureborg et al.](https://arxiv.org/abs/2405.01724)).

**Refusals.** Pass is an equal drop rate across leaders. MEASURED: Astra dropped 4 of 7 Alex Karp calls and 1 of
12 others, Fable none of 17. Every Karp refusal cites US political content, DOCUMENTED model behaviour ([Noels
et al. 2025](https://arxiv.org/abs/2504.03803)), so missingness is not random. Publish the per-leader drop count
and treat an imbalanced leader as single-judge.

# Tier 2. New judge calls, about 3 USD-equivalent each

Write the perturbed transcript as a fixture, then `scripts/grade.py --single <fixture> --judges fable,astra
--repeats 3 --mode blinded`. Types follow CheckList: INV means the score must not move, DIR means it must move a
stated way ([Ribeiro et al. 2020](https://aclanthology.org/2020.acl-main.442/)).

| # | Probe | Type | Build | Pass |
| --- | --- | --- | --- | --- |
| P1 | Padding | DIR | Duplicate the subject's own filler until word count rises 50%. Add no claim. | Score does not rise past the detectable shift. A rise is length bias and makes V5 unusable. |
| P2 | Degradation | DIR | Replace every mechanism, number and named tradeoff with a vague equivalent. Hold word count within 5%. | Insight and depth fall well past the tie band. If not, the rubric scores style. |
| P5 | Criterion order | INV | Reverse dimension and sub-criterion order in the prompt. | Stable. Movement means anchoring on whichever criterion comes first. |
| P6 | Quality ladder | DIR | One transcript, four versions, one layer of substance removed each time. | Spearman between score and constructed rank equals 1.0 for each judge. |
| P7 | Wider test-retest | n/a | Repeat 3x on five transcripts across the score range, not one. | Per-transcript SD no worse than 2x the fixture SD. Recompute the tie band from the worst case. |
| P3 | Paraphrase | INV | Reword every sentence, keep every claim. | All three dimensions stable inside the tie band. |
| P4 | Shuffle | DIR+INV | Shuffle paragraph order. | Clarity falls, depth stable. Neither moving means structure is not read. |
| P8 | Third judge | n/a | A judge from a third family on the paired subset. | ICC(3,1) holds with three raters, meeting the DOCUMENTED guidance of 3 raters and 30 subjects (Koo & Li). |

The table is in run order. P1 and P2 decide whether V5 means anything and whether the rubric reads content. **P5
is third and is not optional insurance**, because criterion order is a measured defect in rubric-based pointwise
judging: reordering criteria moved scores 0.23 to 0.53 points on a 5-point scale, was significant in 56 of 60
tests, and reversed the top-ranked candidate in 16% to 39% of prompts ([Xu et al.
2026](https://arxiv.org/abs/2602.02219)). Permutation averaging buys reproducibility, not accuracy, so treat a
P5 failure as a reason to split the prompt, not to average over orders. P7 next, because every threshold here
rests on a noise floor measured on one transcript. P6 is the strongest single evidence of validity and the most
work to build. P8 is dearest and, per V1, buys less independence than it appears to.

P3 carries a trap. Classical self-preference needs an own-generation candidate and our transcripts are human
speech, so it does not apply. What does apply is that LLM judges prefer LLM-written text over human-written
text, choosing it 0.52 to 0.88 of the time where human raters chose it 0.28 to 0.29 ([Laurito et al., PNAS
2025](https://arxiv.org/abs/2407.12856)). An LLM-written paraphrase may therefore score higher for reasons
unrelated to content, so the paraphraser must not be a judge and a null result should be read cautiously.

# Tier 3. Rejected: external social signal as calibration

Do not correlate scores with views, likes, comment sentiment or Reddit volume and call it calibration. **The
confound is the axis the roster varies on.** In the closest published work, 60 physics explainer videos rated by
experts, view count correlates with expert quality at r=0.27 and **loses significance once channel subscriber
count is partialled out**; only content-relevant comment count survives, at r=0.47 ([Kulgemeyer et
al.](https://arxiv.org/abs/2207.05872)). Our 40 leaders differ in fame by orders of magnitude. Reddit is
dismissed as a weak quality indicator in every field across 67,030 articles scored by expert peer review
([Thelwall et al.](https://arxiv.org/abs/2212.07811)), raw TED rating counts intercorrelate at 0.56 purely
because popular talks collect more of every label ([Tanveer et al.](https://arxiv.org/abs/1905.08392)), and
popularity is partly arbitrary because social influence alone changes which items win ([Salganik et al.
2006](https://www.science.org/doi/10.1126/science.1121066)). **n=40 cannot resolve it:** a correlation must
exceed 0.312 to reach p<0.05, and published engagement-quality correlations sit between -0.07 and +0.46. **Our
own data shows the trap.** MEASURED: Spearman between log views and Astra's composite is +0.71 (p=0.047) at n=8,
which looks like convergent validity and is the same confound as V5.

**Do this instead.** Use engagement as a *negative control*. Regress each judge's score on log subscribers, log
views and video age. If the score tracks fame, that is a defect you have found; if it does not, you have a
discriminant-validity claim that the grader scores content, not celebrity. Practical notes: YouTube removed
dislikes in 2021, so a like ratio no longer exists; `commentThreads.list` costs 1 quota unit against 10,000 a
day, so the Data API beats yt-dlp, whose comment path last broke in December 2025; new Reddit OAuth clients need
manual approval taking weeks.

**The real answer is a small human panel.** A criterion-validity study of an LLM rubric against verified
purchase conversion reached only Spearman 0.37 on its best dimension, and its equal-weighted composite scored
*worse* than its best single dimension at 0.272, an effect the authors name composite dilution
([arXiv:2604.00022](https://arxiv.org/abs/2604.00022)). Twenty to forty hand-labelled transcripts also unlock
the one method that beats every check above: calibrating judge output onto the human scale, which raised
agreement by an average of 142% across 29 tasks ([van den Burg et al. 2025](https://arxiv.org/abs/2502.04997)).
