---
name: grader-validation
description: Validate the LLM-judge rubric without human labels by measuring inter-rater reliability, probing length and order bias, testing construct validity of the three dimensions, and running known-answer degradation probes.
---

# Validating the grader without human labels

Checks are ordered by value per unit of effort. Tier 1 runs on grades already
on disk. Tier 2 needs new judge calls at about 3 USD-equivalent each. Tier 3 is
rejected, with the reason.

Marks on every number: **DOCUMENTED** (published, cited), **COMMUNITY** (a
convention in wide use, no single authority), **MEASURED** (computed in this
repo, with date and n), **UNKNOWN** (nobody has established it).

## Shared loader

Save as `scripts/gv.py`. Needs numpy and scipy, both already installed.
`pingouin` and `statsmodels` are not installed, so nothing below uses them.

```python
import json, glob, itertools, numpy as np
from collections import defaultdict
from scipy import stats
ROOT = "/Users/tonygwu/Code/public-leader-speaking-analysis"
DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]

def grades(mode="blinded"):
    """Every judge call. Refusals and unscorable grades are yielded too, flagged.

    `coverage == 0` means the judge scored nothing and emitted 1/1/1 because the
    schema has no unscorable option. Those are not scores. See V0.
    """
    for p in glob.glob(f"{ROOT}/data/grades/*/*/*.json"):
        r = json.load(open(p)); g = r.get("grade", {})
        r["unscorable"] = "dimensions" in g and g.get("coverage", 1) == 0
        r["ok"] = (not r.get("validation_errors") and "dimensions" in g
                   and g.get("coverage", 0) > 0
                   and g.get("subject_speech_share_pct", 0) > 0)
        if mode is None or r["mode"] == mode:
            yield r

def paired(mode="blinded"):
    """{transcript_id: {judge: grade}} for transcripts BOTH judges scored."""
    by = defaultdict(dict)
    for r in grades(mode):
        if r["ok"]:
            by[r["transcript_id"]][r["judge"]] = r["grade"]
    return {t: v for t, v in by.items() if len(v) == 2}

P = paired(); tids = sorted(P)      # every sketch below assumes these two
```

## The noise floor

Compare every probe result against repeat noise, never against zero.
MEASURED, `data/logs/calibration.json`, 5 repeats of one fixture: composite SD
1.29 Fable, 1.78 Astra.

A paired probe with `r` repeats on `m` transcripts detects
`1.96*sqrt(2)*1.78/sqrt(r*m)` points. MEASURED: r=3 m=1 gives 2.8 points, r=3
m=3 gives 1.6, r=1 m=1 gives 4.9. One unrepeated probe run catches only a large
effect. The SD comes from a single transcript, so noise on an ambiguous one is
UNKNOWN until P7 runs.

---

# Tier 1. Runs today, no model calls

Numbers below are MEASURED on the 2026-09-05 snapshot: 36 judge calls, 31
usable, 4 refusals, 1 unscorable, 8 paired blinded transcripts. The corpus
grows while the fetch loop runs, so re-run rather than trusting these.

## V0. Refuse to average a non-score

**Tests** whether anything in `data/grades` is a placeholder rather than a
judgement. Run this first. It changes every other number.

```python
for r in grades(None):
    if r["unscorable"] or not r["ok"]:
        print(r["judge"], r["transcript_id"], "unscorable" if r["unscorable"] else "refused")
```

**Pass.** Zero unscorable grades reach `aggregate.py`.

**MEASURED 2026-09-05.** One found. `andy-jassy/tech-news-weekly-qpvhgj` is a
podcast *about* Andy Jassy in which he never speaks. Astra detected this
correctly, set all 15 sub-criteria to not observed, `coverage` to 0 and
`subject_speech_share_pct` to 0, then wrote 1/1/1 and said so in its reasoning:
"a schema-required placeholder for an unassessable dimension". `validate()`
passed it, because the schema has no unscorable option.

That single 1 raised the leader's between-transcript SD from 2.6 to 35.1, and
it enters `calibrate()`, where it drags one judge's mean and inflates its
standard deviation for **every** leader in the corpus. Two fixes. Add
`status: "unscorable"` to the schema so a judge can decline without inventing a
number. Gate stage 3 on `subject_speech_share_pct`, which is the detector that
already exists and that nothing reads.

## V1. Split judge agreement into rank and level

**Tests** whether the judges order transcripts the same way, and separately
whether they agree on absolute level. The recentring step only touches level.

Report four things. ICC(3,1), two-way mixed, consistency, single measure: the
right headline when the two judges are the only judges of interest and a
constant offset is tolerated. ICC(2,1), absolute agreement: shows what the
offset costs. Lin's concordance coefficient split into precision (Pearson rho)
and accuracy (Cb), because Cb isolates exactly what recentring removes.
Bland-Altman bias and limits of agreement, in score units a reader understands.
DOCUMENTED: the ICC form must be named, because consistency ignores a
systematic rater offset and absolute agreement does not ([Koo & Li 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4913118/)).

```python
def icc(M):                              # rows = transcripts, cols = judges
    n, k = M.shape; gm = M.mean()
    MSR = k * ((M.mean(1) - gm) ** 2).sum() / (n - 1)
    MSC = n * ((M.mean(0) - gm) ** 2).sum() / (k - 1)
    MSE = ((M - M.mean(1, keepdims=True) - M.mean(0, keepdims=True) + gm) ** 2
           ).sum() / ((n - 1) * (k - 1))
    return dict(icc21=(MSR - MSE) / (MSR + (k - 1) * MSE + k * (MSC - MSE) / n),
                icc31=(MSR - MSE) / (MSR + (k - 1) * MSE))

M = np.array([[P[t]["fable"]["overall"], P[t]["astra"]["overall"]] for t in tids])
x, y = M[:, 0], M[:, 1]; d = y - x
ccc = 2*np.cov(x, y, bias=True)[0,1] / (x.var() + y.var() + (x.mean()-y.mean())**2)
rho = np.corrcoef(x, y)[0, 1]
print(icc(M), f"CCC={ccc:.3f} precision={rho:.3f} Cb={ccc/rho:.3f}")
print(f"bias={d.mean():+.1f} LoA=[{d.mean()-1.96*d.std(ddof=1):.1f},"
      f"{d.mean()+1.96*d.std(ddof=1):.1f}]", stats.linregress(M.mean(1), d).pvalue)
```

**Pass.** ICC(3,1) at or above 0.75 with its 95% interval reported, not the
point estimate. Bands poor <0.50, moderate 0.50-0.75, good 0.75-0.90, excellent
>0.90, DOCUMENTED (Koo & Li). Bland-Altman limits narrower than the leaderboard
spread. Proportional-bias slope not significant, otherwise the offset is not
constant and one recentring cannot fix it ([Bland & Altman 1986](https://www.ajo.com/article/s0002-9394\(08\)00773-3/fulltext)).

**MEASURED 2026-09-05, n=8 paired blinded.** ICC(3,1)=0.871, ICC(2,1)=0.666,
CCC=0.636 with precision 0.924 and Cb=0.688, bias +8.2, limits [-1.9, +18.3],
proportional slope +0.358 (p=0.063). The judges rank almost identically, differ
badly on level, and the offset grows with the score.

Do not headline Krippendorff's alpha. It is the right choice for missing data
and varying rater counts, and it is what recent LLM-judge work reports, with
0.800 good and 0.667 tentative, DOCUMENTED ([Rating Roulette 2025](https://arxiv.org/html/2510.27106v1)).
It does not separate offset from disagreement, which is the question here.

## V2. Estimate the offset on the paired subset only

**Tests** whether the recentring in `aggregate.py` measures judge severity or
corpus composition. `calibrate()` takes each judge's mean over everything that
judge graded. When one judge refuses a transcript, the two means come from
different corpora and their difference is not a pure judge effect.

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

**Pass.** Artefact under 1 point. **MEASURED 2026-09-05.** Clarity +1.51,
insight +0.33, technical depth +3.01. Technical depth fails: 3 points of a
9.5-point "judge offset" is corpus composition. Fix by estimating `judge_mean`
and `judge_sd` on the paired subset, or by fitting transcript and judge effects
jointly, which is the established rater-severity method ([many-facet Rasch measurement](https://www.winsteps.com/facetman/theory.htm)).

## V3. Put the right error bar on the leaderboard

**Tests** the published tie band. `calibration_report.py` sets it to
`2.77 * within-judge SD` = 4.3, which is repeat noise on one unchanged
transcript. A leader's score averages several *different* transcripts, and task
variance is a separate error source, usually larger than rater variance
([generalizability theory](https://www.sciencedirect.com/science/article/pii/S2666557325000370), DOCUMENTED).

```python
byl = defaultdict(list)
for r in grades("blinded"):
    if r["ok"]: byl[(r["transcript_id"].split("/")[0], r["judge"])].append(r["grade"]["overall"])
for k, v in sorted(byl.items()):
    if len(v) > 1:
        se = np.std(v, ddof=1) / np.sqrt(len(v))
        print(k, f"n={len(v)} sd={np.std(v,ddof=1):.1f} tie_band={1.96*np.sqrt(2)*se:.1f}")
```

**Pass.** The published band is at least the median leader's `1.96*sqrt(2)*se`.
Better: bootstrap the ranking over transcripts and publish rank intervals,
COMMUNITY practice on LLM leaderboards ([Miller 2024](https://arxiv.org/abs/2411.00640)).

**MEASURED 2026-09-05, 3 leaders.** Per-judge tie bands 4.1 to 21.4 points. The
published 4.3 understates the noisiest leader by 5x.

## V4. Discriminant validity of the three dimensions

**Tests** whether the rubric measures three things or one thing three times.
Build a multitrait-multimethod matrix, traits = the three dimensions, methods =
the two judges (Campbell & Fiske 1959). The same dimension across judges must
beat the same judge across dimensions, and beat different dimensions across
judges.

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

**Pass.** Every convergent value above every different-dimension value.
Heterotrait-monotrait ratio below 0.85, COMMUNITY.

**MEASURED 2026-09-05, n=8.** Convergent 0.91 / 0.81 / 0.91. Same judge across
dimensions reaches 0.98 (Astra clarity against technical depth). Different
dimension across judges reaches 0.94. The criterion **fails**. Cronbach's alpha
over all 15 sub-criteria is 0.85 for Fable, about equal to the within-dimension
values 0.86 / 0.80 / 0.91. One general factor explains most of it.

**A 0.9 correlation between dimensions is not automatically a defect.** Real
speaking ability is correlated across facets, and a single rater adds halo on
top, the classic inflation of inter-dimension correlations in rating data.
Three responses, cheapest first. One, publish a composite plus a residual
profile, since weights of 0.20 / 0.45 / 0.35 do almost nothing once the
dimensions are collinear. Two, grade each dimension in a separate call so one
pass cannot carry halo across dimensions, then re-run this check. Three, keep
them and state plainly that they are not independent. Do not run factor
analysis below n=100 with 15 variables, COMMUNITY.

Before touching sub-criteria: `not_observed` is stored as `0`, which is not a
score on a 1-5 scale. Drop those cells. `calibration_report.py` currently folds
them into a standard deviation.

## V5. Length, venue and fame confounds

**Tests** whether score tracks anything other than content. Transcripts run 11k
to 30k words. Run all three covariates together, because they are the same
variable wearing three hats.

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

**MEASURED 2026-09-05, n=8.** Astra: Spearman with words +0.74 (p=0.037),
partial +0.59 after controlling venue challenge, Spearman with views +0.71.
Fable: +0.36 (p=0.385). Keynotes average 64.8 and fireside chats 47.4, the
opposite of what the rubric's venue guidance predicts.

**Do not report this as length bias.** Length is confounded with format, and
the rubric itself says a six-minute segment cannot demonstrate insight, so short
transcripts *should* score lower. Verbosity bias in LLM judges is DOCUMENTED
([Zheng et al. 2023](https://arxiv.org/abs/2306.05685)) and the standard
correction is a regression that asks what the score would be at equal length
([Length-Controlled AlpacaEval](https://arxiv.org/abs/2404.04475), Spearman
with Chatbot Arena 0.94 to 0.98). Both are pairwise-preference results.
Length bias in pointwise rubric scoring of human text is UNKNOWN. Only a
within-transcript manipulation separates bias from correct behaviour: run P1
and P2. Use V5 to size the problem, not to conclude.

## V6. Halo, distribution, refusals

Three cheap checks with one finding each.

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

**Halo.** Pass is a mean shift inside the tie band with Wilcoxon not
significant. MEASURED, n=14 pairs: +0.13, SD 3.29, p=0.98. Passes. This is the
project's strongest positive result and deserves more prominence than the 100%
blinding-leakage figure, which sounds worse than it is.

**Distribution.** Pass is a round-number share near 0.20 (chance for multiples
of 5) and at least 20 distinct values. MEASURED, n=93: range 28-84, 43 distinct
values, share 0.204. Passes. No bunching in the 70-85 band.

**Refusals.** Pass is an equal refusal rate across leaders. MEASURED: Astra
dropped 4 of 7 Alex Karp calls and 1 of 12 others; Fable dropped none of 17.
Every Karp refusal cites US political content. Refusal on political content is
DOCUMENTED model behaviour
([Noels et al. 2025](https://arxiv.org/abs/2504.03803)). Missingness here is
not random. Publish the per-leader refusal count, and treat any leader with an
imbalance as single-judge rather than averaging an unbalanced pair.

---

# Tier 2. New judge calls, about 3 USD-equivalent each

Write the perturbed transcript as a fixture, then `scripts/grade.py --single
<fixture> --judges fable,astra --repeats 3 --mode blinded`. Types follow
CheckList: INV means the score must not move, DIR means it must move a stated
way ([Ribeiro et al. 2020](https://aclanthology.org/2020.acl-main.442/)).

| # | Probe | Type | Build | Pass |
| --- | --- | --- | --- | --- |
| P1 | Padding | DIR | Duplicate the subject's own filler until word count rises 50%. Add no claim. | Score does not rise beyond the detectable shift. A rise is length bias and makes V5 unusable. |
| P2 | Degradation | DIR | Replace every mechanism, number and named tradeoff with a vague equivalent. Hold word count within 5%. | Insight and depth fall well past the tie band. If not, the rubric scores style. |
| P3 | Paraphrase | INV | Reword every sentence, keep every claim. | All three dimensions stable inside the tie band. |
| P4 | Shuffle | DIR+INV | Shuffle paragraph order. | Clarity falls, depth stable. Neither moving means structure is not being read. |
| P5 | Criterion order | INV | Reverse dimension order and sub-criterion order in the prompt. | Stable. Movement means anchoring on whichever criterion comes first. |
| P6 | Quality ladder | DIR | One transcript, four versions, one layer of substance removed each time. | Spearman between score and constructed rank equals 1.0 for each judge. |
| P7 | Wider test-retest | — | Repeat 3x on five transcripts across the score range, not one. | Per-transcript SD no worse than 2x the fixture SD. Recompute the tie band from the worst case. |
| P8 | Third judge | — | A judge from a third family on the paired subset. | ICC(3,1) holds with three raters, and reaches the DOCUMENTED guidance of at least 3 raters and 30 subjects (Koo & Li). |

Run P1 and P2 first: they decide whether V5 means anything and whether the
rubric reads content. P7 next, because every threshold here rests on a noise
floor measured on one transcript. P6 is the strongest single evidence of
validity and the most work. P5 and P3 are cheap insurance. P8 is dearest.

Self-preference bias is **not** a priority. The documented effect is an
evaluator favouring *its own generated text*. These transcripts are human
speech neither model wrote. It matters only for P3, whose paraphrases one model
will have authored, so the paraphraser must not be a judge.

---

# Tier 3. Rejected: external social signal as calibration

Do not correlate scores with views, likes, comment sentiment or Reddit volume
and call it calibration. Three reasons, all DOCUMENTED.

**The confound is the axis the roster varies on.** In the closest published
work, 60 physics explainer videos rated by experts, the view-count correlation
with expert quality is r=0.27 and **loses significance once channel subscriber
count is partialled out**. Only content-relevant comment count survives, at
r=0.47 ([Kulgemeyer et al.](https://arxiv.org/abs/2207.05872)). Our 40 leaders
differ in fame by orders of magnitude. Related: raw TED rating counts
intercorrelate at 0.56 purely because popular talks get more of every label,
including "Confusing", and scaling by views drops that to −0.03
([Tanveer et al.](https://arxiv.org/abs/1905.08392)). Reddit specifically is
dismissed as a weak quality indicator in every field across 67,030 articles
scored by expert peer review ([Thelwall et al.](https://arxiv.org/abs/2212.07811)).
Popularity is also partly arbitrary: social influence alone changes which items
win ([Salganik, Dodds & Watts 2006](https://www.science.org/doi/10.1126/science.1121066)),
and one seeded upvote raises final ratings by 25% ([Muchnik et al. 2013](https://www.science.org/doi/10.1126/science.1240466)).

**n=40 cannot resolve it.** At n=40 a correlation must exceed 0.312 to reach
p<0.05, and published engagement-quality correlations sit between −0.07 and
+0.46. The study is powered to distinguish almost none of them from zero.

**Our own data already shows the trap.** MEASURED: Spearman between view count
and Astra's composite is +0.71 at n=8. That looks like convergent validity. It
is the same length and format confound as V5.

**What to do instead.** Use engagement as a *negative control*, not a criterion.
Regress each judge's score on log subscribers, log views and video age. If the
score tracks fame, that is a defect you have found. If it does not, you have a
discriminant-validity claim: the grader scores content, not celebrity. This is
cheap and informative either way. Note the practical points: YouTube dislikes
were removed in 2021, so a like ratio no longer exists; `commentThreads.list`
costs 1 quota unit against 10,000 a day, so the API beats yt-dlp, whose comment
path last broke in December 2025; new Reddit OAuth clients now need manual
approval taking weeks. Decide the construct question before any of that.

The real answer is a small human panel. A criterion-validity study of an
LLM rubric against verified purchase conversion reached only Spearman 0.37 on
its best dimension, and its equal-weighted composite scored *worse* than its
best single dimension, 0.272, an effect the authors call composite dilution
([arXiv:2604.00022](https://arxiv.org/abs/2604.00022)). Ten to fifteen
transcripts stratified across our score range, rated by two or three experts
blind to the LLM scores, will settle more than every engagement metric on the
internet.
