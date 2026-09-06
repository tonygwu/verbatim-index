---
name: grader-validation
description: Validate the LLM-judge rubric without human labels by measuring inter-rater reliability, probing length and order bias, testing construct validity of the three dimensions, and running known-answer degradation probes.
---

# Validating the grader without human labels

Tier 1 runs on grades already on disk. Tier 2 needs new judge calls at about 3 USD-equivalent each. Tier 3 is
rejected. Marks: **DOCUMENTED** (published, cited inline), **COMMUNITY** (wide convention), **MEASURED** (computed
here), **UNKNOWN** (nobody has established it). MEASURED figures come from one snapshot of a growing corpus (49 calls,
43 usable, 5 refused, 1 unscorable, 12 paired blinded transcripts). Read them as worked examples of each check's
output. They move: at 8 paired transcripts V5 gave +0.74, p=0.037, and four later +0.48, p=0.112.

These checks measure **reliability**, not **validity**. DOCUMENTED: with zero gold labels no unbiased estimate of
judge accuracy exists, and no debiasing cuts a labelling budget more than 2x ([Dorner et al.
2024](https://arxiv.org/abs/2410.13341)). Save the loader as `scripts/gv.py`.

```python
import json, glob, itertools, numpy as np
from collections import defaultdict
from scipy import stats
ROOT = "/Users/tonygwu/Code/public-leader-speaking-analysis"
DIMS = ["d1_clarity", "d2_insight", "d3_technical_depth"]

def grades(mode="blinded"):
    for p in glob.glob(f"{ROOT}/data/grades/*/*/*.json"):
        r = json.load(open(p)); g = r.get("grade", {})
        r["unscorable"] = "dimensions" in g and g.get("coverage", 1) == 0
        r["ok"] = (not r.get("validation_errors") and "dimensions" in g
                   and g.get("coverage", 0) > 0 and g.get("subject_speech_share_pct", 0) > 0)
        if mode is None or r["mode"] == mode:
            yield r

def paired(mode="blinded"):
    by = defaultdict(dict)
    for r in grades(mode):
        if r["ok"]: by[r["transcript_id"]][r["judge"]] = r["grade"]
    return {t: v for t, v in by.items() if len(v) == 2}

P = paired(); tids = sorted(P)      # every sketch below assumes these two
```

**Noise floor.** Compare probes against repeat noise, never zero. MEASURED, `data/logs/calibration.json`, 5 repeats of
one fixture: composite SD 1.29 Fable, 1.78 Astra. A paired probe with `r` repeats on `m` transcripts detects
`1.96*sqrt(2)*1.78/sqrt(r*m)` points, so r=3 m=1 gives 2.8 and r=1 m=1 gives 4.9.

# Tier 1. Runs today, no model calls

## V0. Refuse to average a non-score, and audit who is missing

**Tests** whether any grade is a placeholder and whether drops are random; run it first. **Pass:** no unscorable grade
reaches `aggregate.py`, and an equal drop rate across leaders.

```python
tally = defaultdict(lambda: [0, 0])
for r in grades(None):
    k = (r["judge"], r["transcript_id"].split("/")[0]); tally[k][1] += 1
    if not r["ok"]:
        tally[k][0] += 1
        print(r["judge"], r["transcript_id"], "unscorable" if r["unscorable"] else "refused")
print({f"{j}/{L}": v for (j, L), v in sorted(tally.items()) if v[0]})
```

**MEASURED.** `andy-jassy/tech-news-weekly-qpvhgj` is a podcast *about* Andy Jassy in which he never speaks. That one
score raised the leader's between-transcript SD from 2.6 to 35.1 and feeds `calibrate()`, shifting a judge's mean and
inflating its SD for **every** leader. Add `status: "unscorable"` to the schema and gate stage 3 on
`subject_speech_share_pct`, the detector that nothing reads. Drops are not random either: Astra lost 5 of 8 Alex Karp
calls and 1 of 12 others, Fable none, every Karp refusal citing US political content, DOCUMENTED behaviour ([Noels et
al. 2025](https://arxiv.org/abs/2504.03803)). Treat an imbalanced leader as single-judge.

## V1. Split judge agreement into rank and level

**Tests** whether the judges rank alike, and separately whether they agree on level, which is all recentring touches.
Headline ICC(3,1), two-way mixed, consistency, single measure, since these two judges are the only judges of interest
and a constant offset is tolerated by design. Publish ICC(2,1), absolute agreement, to price the offset, plus Lin's
Cb, which isolates what recentring removes. DOCUMENTED: name the form, because consistency ignores a rater offset and
absolute agreement does not ([Koo & Li 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4913118/)).

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

**Pass.** ICC(3,1) at or above 0.75 with its 95% interval, on DOCUMENTED bands poor <0.50, moderate 0.50-0.75, good
0.75-0.90, excellent >0.90 (Koo & Li); limits narrower than the leaderboard spread; a non-significant
proportional-bias slope, or one recentring cannot fix the offset ([Bland & Altman
1986](https://www.ajo.com/article/s0002-9394\(08\)00773-3/fulltext)). Krippendorff's alpha cannot separate offset from
disagreement, so it is not the headline here. **MEASURED, n=12:** ICC(3,1)=0.723, ICC(2,1)=0.603, CCC=0.582 with
precision 0.736 and Cb=0.790, bias +5.9, limits [-6.9, +18.7], slope p=0.390. ICC(3,1) sits just below threshold and
the 25-point spread of the limits is six times the published tie band, so the judges agree on the leaderboard's shape
and not on any transcript. **Nor is agreement itself strong evidence:** 9 frontier judges from 7 families carry about
2 independent votes, and cross-family error correlation matches same-family, GPT-4o against Claude at phi=0.588
([Kohli 2026](https://arxiv.org/abs/2605.29800)). Treat **disagreement** as the signal and route it to review.

## V2. Estimate the offset on the paired subset only

**Tests** whether `aggregate.py` measures judge severity or corpus composition. `calibrate()` takes each judge's mean
over everything that judge graded, so a refusal makes the two means come from different corpora. **Pass:** artefact
under 1 point.

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

**MEASURED, n=12.** Clarity +3.70, insight -0.28, technical depth +3.78. Two of three fail, at nearly the whole
4.3-point tie band. Estimate `judge_mean` and `judge_sd` on the paired subset, or fit transcript and judge effects
jointly, the established rater-severity method ([many-facet Rasch](https://www.winsteps.com/facetman/theory.htm)).

## V3. Put the right error bar on the leaderboard

**Tests** the published tie band, set by `calibration_report.py` to `2.77 * within-judge SD` = 4.3, the repeat noise
on one unchanged transcript. A leader averages *different* transcripts, and task variance is a separate, usually
larger error source than rater variance ([generalizability
theory](https://www.sciencedirect.com/science/article/pii/S2666557325000370)).

```python
byl = defaultdict(list)
for r in grades("blinded"):
    if r["ok"]: byl[(r["transcript_id"].split("/")[0], r["judge"])].append(r["grade"]["overall"])
for k, v in sorted(byl.items()):
    if len(v) > 1:
        se = np.std(v, ddof=1) / np.sqrt(len(v))
        print(k, f"n={len(v)} sd={np.std(v,ddof=1):.1f} tie_band={1.96*np.sqrt(2)*se:.1f}")
```

**Pass.** The published band is at least the median leader's `1.96*sqrt(2)*se`. Better, bootstrap the ranking and
publish rank intervals, COMMUNITY practice on LLM leaderboards ([Miller 2024](https://arxiv.org/abs/2411.00640)).
**MEASURED, 4 leaders:** bands run 3.1 to 13.0, so 4.3 understates the noisiest leader by about 3x.

## V4. Discriminant validity of the three dimensions

**Tests** three things or one thing three times, via a multitrait-multimethod matrix, traits = dimensions, methods =
judges (Campbell & Fiske 1959). **Pass:** every same-dimension cross-judge value beats every different-dimension
value, and heterotrait-monotrait stays below 0.85, COMMUNITY.

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

**MEASURED, n=12.** Convergent 0.82 / 0.59 / 0.83, worst cross-judge different-dimension 0.83, worst within a judge
0.89, so the criterion **fails**. Insight fails hardest: one judge's insight predicts the other judge's *other*
dimensions better than its insight. Cronbach's alpha over all 15 sub-criteria is 0.86 for Fable, above every
within-dimension value (0.82 / 0.84 / 0.82), the signature of one general factor.

**This is a known artefact of scoring several attributes in one generation.** DOCUMENTED: attribute scores emitted in
one pass correlate at r=0.979 where the same attributes scored by humans correlate at r=0.315, and the fix is one
attribute per generation ([Stureborg et al. 2024](https://arxiv.org/abs/2405.01724)). Our rubric asks for 15
sub-criteria and 3 dimensions in one call, exactly that condition, so grade each dimension separately and re-run. Halo
and truth cannot be separated while one call emits all three numbers. Do not factor-analyse below n=100 with 15
variables, COMMUNITY, and drop `not_observed` cells, stored as `0`, which is not a score on a 1-5 scale.

## V5. Length, venue and fame confounds

**Tests** whether score tracks anything but content over the 11k-to-30k-word range. Run all three covariates together:
they are one variable wearing three hats.

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

**MEASURED, n=12.** Astra: words +0.48 (p=0.112), partial +0.41 controlling venue challenge, log views +0.37. Fable:
+0.04 and +0.40. Nothing significant, and the +0.74 seen at n=8 did not survive.

**Do not call this length bias, and do not regress length out.** The closest published analogue, pointwise scoring of
long human-authored documents, found both halves at once: observationally a response gained 0.125 points per 10% of
extra length, yet doubling it by repeating its own content **lowered** the score ([Chuang et al.
2025](https://arxiv.org/abs/2502.15094)). Verbosity bias is DOCUMENTED ([Zheng et al.
2023](https://arxiv.org/abs/2306.05685)) but the quality/bias split is provably unidentifiable from scores alone ([Xu
et al. 2026](https://arxiv.org/abs/2607.02104)). Size it here, answer with P1.

## V6. Halo from unblinding

```python
ob = defaultdict(dict)
for r in grades(None):
    if r["ok"]: ob[(r["transcript_id"], r["judge"])][r["mode"]] = r["grade"]["overall"]
dd = np.array([v["open"] - v["blinded"] for v in ob.values() if len(v) == 2])
print("halo", len(dd), dd.mean(), stats.wilcoxon(dd))
v = np.array([r["grade"]["dimensions"][d]["score"] for r in grades(None) if r["ok"] for d in DIMS])
print("scale", v.min(), v.max(), len(set(v.tolist())), np.mean(v % 5 == 0))
```

**Halo** passes if the shift sits inside the tie band with Wilcoxon not significant. MEASURED, n=14 pairs: +0.13, SD
3.29, p=0.98. This is the project's strongest positive result and deserves more prominence than the 100%
blinding-leakage figure: the judges know who is speaking and it does not change the score. MEASURED over 129 dimension
scores the scale is also used properly: range 28-84, 46 distinct values, round-number share 0.209 against a chance
0.20.

# Tier 2. New judge calls, about 3 USD-equivalent each

Write the perturbed transcript as a fixture, then `scripts/grade.py --single <fixture> --judges fable,astra --repeats
3 --mode blinded`. Types follow CheckList: INV means the score must not move, DIR means it must move a stated way
([Ribeiro et al. 2020](https://aclanthology.org/2020.acl-main.442/)).

| # | Probe | Type | Build | Pass |
| --- | --- | --- | --- | --- |
| P1 | Padding | DIR | Duplicate the subject's own filler until word count rises 50%. Add no claim. | Score does not rise past the detectable shift. A rise is length bias and makes V5 unusable. |
| P2 | Degradation | DIR | Replace every mechanism, number and named tradeoff with a vague equivalent. Hold word count within 5%. | Insight and depth fall well past the tie band. If not, the rubric scores style. |
| P5 | Criterion order | INV | Reverse dimension and sub-criterion order in the prompt. | Stable. Movement means anchoring on whichever criterion comes first. |
| P7 | Wider test-retest | n/a | Repeat 3x on five transcripts across the score range, not one. | Per-transcript SD no worse than 2x the fixture SD. Recompute the tie band from the worst case. |
| P6 | Quality ladder | DIR | One transcript, four versions, one layer of substance removed each time. | Spearman between score and constructed rank equals 1.0 for each judge. |
| P3 | Paraphrase | INV | Reword every sentence, keep every claim. | All three dimensions stable inside the tie band. |
| P4 | Shuffle | DIR+INV | Shuffle paragraph order. | Clarity falls, depth stable. Neither moving means structure is not read. |
| P8 | Third judge | n/a | A judge from a third family on the paired subset. | ICC(3,1) holds with three raters, meeting the DOCUMENTED guidance of 3 raters and 30 subjects (Koo & Li). |

P1 and P2 decide whether V5 means anything and whether the rubric reads content at all. **P5 is third and is not
optional:** reordering criteria in rubric-based pointwise judging moved scores 0.23 to 0.53 points on a 5-point scale,
was significant in 56 of 60 tests, and reversed the top candidate in 16% to 39% of prompts ([Xu et al.
2026](https://arxiv.org/abs/2602.02219)). P7 next, since every threshold rests on a noise floor from one transcript,
then P6, the strongest evidence of validity and the most work. P8 buys less independence than it looks. In P3 the
paraphraser must not be a judge, since LLM judges prefer LLM-written text over human ([Laurito, PNAS
2025](https://arxiv.org/abs/2407.12856)).

# Tier 3. Rejected: external social signal as calibration

Do not correlate scores with views, likes, comment sentiment or Reddit volume and call it calibration. **The confound
is the axis the roster varies on.** In the closest published work, 60 physics explainer videos rated by experts, view
count correlates with expert quality at r=0.27 and **loses significance once channel subscriber count is partialled
out**; only content-relevant comment count survives, at r=0.47 ([Kulgemeyer et
al.](https://arxiv.org/abs/2207.05872)). **n=40 cannot resolve it:** a correlation must exceed 0.312 for p<0.05, and
published engagement-quality correlations sit between -0.07 and +0.46. Use engagement as a *negative control* instead:
regress each judge's score on log subscribers, log views and video age, and if the score tracks fame you have found a
defect.

**The real answer is a small human panel.** A criterion-validity study of an LLM rubric against purchase conversion
reached Spearman 0.37 on its best dimension, and its equal-weighted composite scored *worse* at 0.272, an effect the
authors name composite dilution ([arXiv:2604.00022](https://arxiv.org/abs/2604.00022)).
