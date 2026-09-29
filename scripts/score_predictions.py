#!/usr/bin/env python3
"""Join resolutions and priors into points, and aggregate them per person.

    .venv/bin/python scripts/score_predictions.py --config data/predictions/scoring.json
    .venv/bin/python scripts/score_predictions.py --run data/predictions/_experiments/<run> \
        --as-of 2026-09-14 --out data/predictions/_experiments/<run>/scores.json

`--config` reads every setting from a committed file, so any clone regenerates
the published scores.json identically. The output carries no wall-clock field,
records every path relative to the data root (the parent of the first
predictions directory), and fingerprints every input it read in
`inputs_sha256`, which `scores_staleness()` checks.

Spends no model calls. Everything here is arithmetic over what the two stages
already wrote, so it can be re-run freely and its numbers re-derived.

THE RULE, from `scripts/prediction_score.py`:
  a speaker who states no probability scores  -log2(p)  when right and
  (p/(1-p))*log2(p) when wrong, which is zero in expectation at every p. A
  speaker who states their own q scores log2(q/p) or log2((1-q)/(1-p)).
So a mean above zero is foresight and a mean below zero is worse than the base
rate. Volume earns nothing on its own, which is why the published figure is a
MEAN and not a sum.

WHAT COUNTS TOWARD THE PUBLISHED FIGURE
  - resolved to occurred or not_occurred, so "unresolvable" is excluded rather
    than scored as a miss,
  - carries a prior,
  - clears the eligibility rule: specificity high or medium
    (`phase2_resolvability.ELIGIBLE_SPECIFICITY`, widened from high alone on
    2026-09-27), at least `MIN_LEAD_DAYS` of lead time, and a deadline that does
    not precede the statement.
Everything else is loaded, counted and reported, never silently dropped.
Eligibility is checked first, so an ineligible row reads
`not_eligible:<deadline_before_statement|specificity|undated|lead_under_floor>`
whether or not it was resolved (`phase2_resolvability.ineligible_reason`). A
person below `MIN_SCORED_TO_RANK` keeps their number in this file and does not
get a published one, which is how `MIN_TRANSCRIPTS_TO_RANK` already works on the
leaderboard.

RESTATEMENTS (operator decisions, 2026-09-28). A person who says the same thing on
several days made ONE prediction. `--restatements` (or `restatements` in the
config) names a manifest of clusters, each with its `members` and its
`specific_member`: the earliest member specific enough on its own, which alone
sets the statement date, the lead time, the prior and the resolution. Every other
member stays a row, not scored because `restated:<specific_member>`, so the
accounting still adds up. A cluster may name a fresh `resolution` run that
supersedes named older sidecars; that is the only way one prediction may have a
resolution in two runs, and every superseded sidecar is reported. See
`read_restatements()` for what is refused.

REPLACEMENTS. A re-resolved or re-priced result lands in a new run while the old
run's sidecar stays on disk. `--replacements` (or `replacements` in the config)
names a manifest whose entries each give the stage, the prediction, the run
replaced, the replacement run and the reason; the old sidecar is left out and
reported under `replacements.replaced_sidecars`. An unlisted duplicate still
stops the scorer. See `read_replacements()` and `load_across()`.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2_resolvability as P2  # noqa: E402
import prediction_score as PS  # noqa: E402
import resolution_lib as R  # noqa: E402
import predictions_lib as L  # noqa: E402
from resolve_predictions import date_overrides_for, select  # noqa: E402
from data_clone_workflow import (  # noqa: E402
    load_scoring_config as load_config, scoring_rel as rel, score_inputs_sha256, scores_staleness,
)


# THREE, the operator's call on 2026-09-16. It was five, chosen to match
# MIN_TRANSCRIPTS_TO_RANK on the leaderboard, which was a default rather than a
# measured choice. Three puts fifteen rows on the board instead of nine and lets
# Levie, Collison, Masad, Dell and Kurian show the numbers they have earned.
#
# The cost is honest and worth stating: a mean over three predictions is noisy.
# Levie's -0.255 rests almost entirely on one 2013 miss worth -1.054, and a
# single further resolution could move him either side of zero. The page reports
# n beside every score so a reader can weigh that.
MIN_SCORED_TO_RANK = 3


def speaker_q(rec: dict) -> float | None:
    """The speaker's OWN probability, when they stated one.

    Only 5 records in 475 carry one and three of those state q = 1.0, so this
    branch is rare. It is kept because the rule the operator specified has two
    halves and dropping the rarer half would silently change the rule.
    """
    conf = rec.get("confidence") or {}
    p = conf.get("probability")
    if p is None or isinstance(p, bool) or not isinstance(p, (int, float)):
        return None
    return float(p)


def join(rows: list[dict], resolutions: dict, priors: dict,
         restated: "dict[str, str] | None" = None) -> tuple[list[dict], collections.Counter]:
    """One row per past-due prediction, with its points where all the parts exist.

    `restated` maps a non-specific cluster member to its specific member. Such a
    row keeps its identity and its funnel flags, carries none of its own outcome
    or p in the scored fields (so no count sees one event twice), and records its
    own verdict under `own_outcome` / `own_p` for audit."""
    out, why = [], collections.Counter()
    restated = restated or {}
    for r in rows:
        pid = r["prediction_id"]
        res, pri = resolutions.get(pid), priors.get(pid)
        own = None
        if pid in restated:
            own = {"own_outcome": (res or {}).get("outcome"), "own_p": (pri or {}).get("p")}
            res = pri = None
        row = {
            "prediction_id": pid,
            "leader_slug": r["leader_slug"],
            "transcript_id": r["transcript_id"],
            "claim": r["prediction"].get("normalized_claim"),
            "criterion": r["prediction"].get("resolution_criteria"),
            "criterion_repaired": "resolution_criteria_original" in r["prediction"],
            "quote": (r.get("source") or {}).get("quote"),
            "statement_date": (r.get("source") or {}).get("statement_date"),
            "deadline": r["_deadline"].isoformat(),
            "flags": r["_flags"],
            "outcome": res["outcome"] if res else None,
            "resolution_confidence": res["confidence"] if res else None,
            "unresolvable_reason": (res or {}).get("unresolvable_reason"),
            "sources": (res or {}).get("sources") or [],
            "resolution_reasoning": (res or {}).get("reasoning"),
            "p": pri["p"] if pri else None,
            "p_raw": pri["p_raw"] if pri else None,
            "p_clamped": pri["clamped"] if pri else None,
            "reference_class": (pri or {}).get("reference_class"),
            "prior_reasoning": (pri or {}).get("reasoning"),
            "q": speaker_q(r),
            "points": None, "rule": None, "scored": False, "not_scored_because": None,
        }
        if own is not None:
            row.update(own, not_scored_because=f"restated:{restated[pid]}", restated_by=restated[pid])
            why["restated"] += 1
            out.append(row)
            continue
        # Eligibility FIRST (design 3.5, rescue round 4). An ineligible record is
        # never resolved, since the resolve stage skips it, so checking for a
        # resolution first named it "no_resolution" and it read as awaiting a check.
        # A resolved one keeps its outcome in the row for audit.
        # The one rule and order the resolver and the page also read
        # (phase2_resolvability.INELIGIBLE_REASONS).
        unfit = P2.ineligible_reason(pid, r["_flags"])
        if unfit is not None:
            row["not_scored_because"] = f"not_eligible:{unfit}"
        elif res is None:
            row["not_scored_because"] = "no_resolution"
        elif res["outcome"] == "unresolvable":
            row["not_scored_because"] = f"unresolvable:{res['unresolvable_reason']}"
        elif pri is None:
            row["not_scored_because"] = "no_prior"
        else:
            s = PS.score(res["outcome"] == "occurred", pri["p"], row["q"])
            row.update(points=round(s["points"], 4), rule=s["rule"], scored=True,
                       score_clamped=s["clamped"])
        why[row["not_scored_because"] or "scored"] += 1
        out.append(row)
    return out, why


def is_restated(r: dict) -> bool:
    return str(r.get("not_scored_because") or "").startswith("restated:")


def per_leader(rows: list[dict], names: dict[str, str], with_restated: bool = False) -> list[dict]:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["leader_slug"]].append(r)
    out = []
    for slug, rs in sorted(by.items()):
        scored = [r for r in rs if r["scored"]]
        pts = [r["points"] for r in scored]
        outcomes = collections.Counter(r["outcome"] for r in rs if r["outcome"])
        out.append({
            "slug": slug,
            "name": names.get(slug, slug),
            "past_due": len(rs),
            # A restated row is the same prediction as its specific member, so it is
            # not a second eligible one.
            "eligible": sum(1 for r in rs if r["flags"]["eligible"] and not is_restated(r)),
            "resolved": sum(1 for r in rs if r["outcome"] in ("occurred", "not_occurred")),
            "unresolvable": outcomes.get("unresolvable", 0),
            "occurred": outcomes.get("occurred", 0),
            "not_occurred": outcomes.get("not_occurred", 0),
            "n_scored": len(scored),
            # The numerator the page prints. Stored rather than recovered from
            # hit_rate * n_scored, which is a float rounded back into a count.
            "scored_occurred": sum(1 for r in scored if r["outcome"] == "occurred"),
            "mean_points": round(sum(pts) / len(pts), 4) if pts else None,
            "sum_points": round(sum(pts), 4) if pts else None,
            "hit_rate": round(sum(1 for r in scored if r["outcome"] == "occurred") / len(scored), 4) if scored else None,
            "mean_p": round(sum(r["p"] for r in scored) / len(scored), 4) if scored else None,
            "ranked": len(scored) >= MIN_SCORED_TO_RANK,
        })
        if with_restated:
            out[-1]["restated"] = sum(1 for r in rs if is_restated(r))
    out.sort(key=lambda l: (-(l["mean_points"] if l["ranked"] and l["mean_points"] is not None else -99),
                            l["name"]))
    return out


# Ten-point bins. Wider bins hide a bias that turns on only at the top of the
# range, which is exactly where this corpus sits.
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def calibration(rows: list[dict]) -> dict:
    """Is the prior assessor right on average? A reliability table, computed free.

    THIS IS THE DIAGNOSTIC THAT DECIDES WHETHER THE BOARD MEANS ANYTHING. The
    score rule has expected value zero at every p ONLY IF p is the real
    probability. If the assessor runs high, every speaker scores negative and the
    board measures the assessor rather than the speaker. So the overall mean is
    reported next to zero, and a table shows where any gap comes from.

    A gap is not automatically the assessor's fault. The resolver counts a thing
    that happened LATE as not occurring, which is the right rule for a dated
    claim and does push the hit rate down against a prior that priced the event
    rather than the deadline.
    """
    scored = [r for r in rows if r["scored"]]
    table = []
    for lo, hi in BINS:
        b = [r for r in scored if lo <= r["p"] < hi]
        if not b:
            table.append({"bin": f"{lo:.1f}-{min(hi, 1.0):.1f}", "n": 0, "mean_p": None,
                          "hit_rate": None, "gap": None, "mean_points": None})
            continue
        mp = sum(r["p"] for r in b) / len(b)
        hr = sum(1 for r in b if r["outcome"] == "occurred") / len(b)
        table.append({"bin": f"{lo:.1f}-{min(hi, 1.0):.1f}", "n": len(b),
                      "mean_p": round(mp, 4), "hit_rate": round(hr, 4),
                      "gap": round(hr - mp, 4),
                      "mean_points": round(sum(r["points"] for r in b) / len(b), 4)})
    overall_p = sum(r["p"] for r in scored) / len(scored) if scored else None
    overall_hr = (sum(1 for r in scored if r["outcome"] == "occurred") / len(scored)) if scored else None
    return {
        "n": len(scored),
        "mean_p": round(overall_p, 4) if overall_p is not None else None,
        "hit_rate": round(overall_hr, 4) if overall_hr is not None else None,
        "gap": round(overall_hr - overall_p, 4) if scored else None,
        "bins": table,
        "reading": _reading(overall_hr - overall_p if scored else 0.0, len(scored)),
    }


def _reading(gap: float, n: int) -> str:
    # A binomial standard error on the hit rate, so a small corpus does not read
    # as a bias. 0.5 is the widest sd, which keeps this conservative.
    se = (0.25 / n) ** 0.5 if n else 1.0
    if abs(gap) < 1.96 * se:
        return (f"hit rate and mean p agree within noise (gap {gap:+.3f}, 1.96 se {1.96 * se:.3f}); "
                f"the board's mean should sit near zero")
    direction = "LOWER" if gap < 0 else "HIGHER"
    return (f"the hit rate is {direction} than the priors by {abs(gap):.3f}, beyond noise "
            f"(1.96 se {1.96 * se:.3f}). Every score carries that gap, so the board measures the "
            f"assessor as well as the speakers, and the overall mean is NOT a neutral zero")


def drop_stale_sidecars(sidecars: dict[str, dict], date_overrides: dict, superseded_ids: set, live_ids: set,
                        run: str, stage: str, dropped: list) -> dict[str, dict]:
    """Sidecars built under a date an override replaced, removed and named.

    A resolution or prior of an overridden transcript counts only if it records
    the override's date, which only a run over the re-extracted record does. One
    written before the override priced a claim dated by the upload, so it is
    stale, and it must not collide with, or stand in for, the fresh one. A
    sidecar of a superseded prediction that no live record replaced goes too.
    """
    out = {}
    for pid, obj in sidecars.items():
        ov = date_overrides.get(obj.get("transcript_id"))
        orphan = pid in superseded_ids and pid not in live_ids
        if orphan or (ov is not None and obj.get("statement_date") != ov["statement_date"]):
            dropped.append({"prediction_id": pid, "stage": stage, "run": run,
                            "transcript_id": obj.get("transcript_id"),
                            "sidecar_statement_date": obj.get("statement_date")})
            continue
        out[pid] = obj
    return out


def load_across(runs: list[Path], loader, drop: "set[tuple[Path, str]] | None" = None,
                dropped: "dict | None" = None, replace: "dict[tuple[Path, str], Path] | None" = None,
                replaced: "dict | None" = None) -> dict[str, dict]:
    """One loader applied to every run, merged by prediction_id.

    A prediction present in two runs is REFUSED, naming both, because letting the
    later run win would settle an outcome by argument order. Within one run the
    loaders already raise on a duplicate.

    `drop` names (run, prediction_id) sidecars a restatement manifest SUPERSEDES.
    They are left out, copied into `dropped` for the report, and each must exist:
    superseding a sidecar that is not there means the manifest describes other
    inputs than these, and that is refused rather than read as done.

    `replace` maps (run, prediction_id) sidecars a replacement manifest replaces to
    the run holding the replacement. They are left out and copied into `replaced`,
    each must exist, and the replacement must be the sidecar actually read for
    that prediction: dropping an old result whose replacement is missing would
    leave the prediction silently unresolved. A sidecar named by both manifests
    is refused, because only one of them can say why it went.
    """
    drop = {(Path(r).resolve(), pid) for r, pid in (drop or set())}
    replace = {(Path(r).resolve(), pid): Path(w).resolve() for (r, pid), w in (replace or {}).items()}
    read = {Path(x).resolve() for x in runs}
    elsewhere = sorted({str(r) for r, _ in drop} - {str(x) for x in read})
    if elsewhere:
        raise SystemExit(f"the restatement manifest supersedes sidecars in runs that are not being read: "
                         f"{elsewhere}")
    elsewhere = sorted({str(x) for (r, _), w in replace.items() for x in (r, w)} - {str(x) for x in read})
    if elsewhere:
        raise SystemExit(f"the replacement manifest names runs that are not being read: {elsewhere}")
    both = sorted(drop & replace.keys())
    if both:
        raise SystemExit("sidecars superseded by both the restatement manifest and the replacement manifest: "
                         + "; ".join(f"{pid} in {run}" for run, pid in both) + "; name each in one of them")
    out: dict[str, dict] = {}
    seen: dict[str, Path] = {}
    hit: set[tuple[Path, str]] = set()
    for run in runs:
        for pid, obj in loader(run).items():
            key = (Path(run).resolve(), pid)
            if key in drop or key in replace:
                hit.add(key)
                sink = dropped if key in drop else replaced
                if sink is not None:
                    sink[key] = obj
                continue
            if pid in out:
                raise SystemExit(f"prediction {pid} has sidecars in two runs: {seen[pid]} and {run}; "
                                 f"remove one before scoring, or name the one that supersedes the "
                                 f"other in the replacement manifest (the restatement manifest for a "
                                 f"restated cluster)")
            out[pid], seen[pid] = obj, run
    missing = drop - hit
    if missing:
        raise SystemExit("the restatement manifest supersedes sidecars that do not exist: "
                         + "; ".join(f"{pid} in {run}" for run, pid in sorted(missing)))
    missing = replace.keys() - hit
    if missing:
        raise SystemExit("the replacement manifest replaces sidecars that are not among those read: "
                         + "; ".join(f"{pid} in {run}" for run, pid in sorted(missing)))
    wrong = sorted({(pid, str(w), str(seen[pid]) if pid in out else None)
                    for (_, pid), w in replace.items() if pid not in out or Path(seen[pid]).resolve() != w},
                   key=lambda x: (x[0], x[1]))
    if wrong:
        raise SystemExit("the replacement manifest names replacements that are not the sidecar read: "
                         + "; ".join(f"{pid} should come from {w}, "
                                     + (f"but the one read is in {got}" if got else "and there is none there")
                                     for pid, w, got in wrong))
    return out


# ---------------------------------------------------------------------------
# Restatements
# ---------------------------------------------------------------------------

MANIFEST_KEYS = {"schema_version", "derived_from", "clusters"}
CLUSTER_KEYS = {"cluster_id", "leader_slug", "specific_member", "members", "resolution", "note"}
CLUSTER_REQUIRED = {"cluster_id", "leader_slug", "specific_member", "members"}
RESOLUTION_KEYS = {"run", "supersedes", "why"}


def read_restatements(path: Path, root: Path, runs: list[Path]) -> dict:
    """The manifest, checked for shape. Everything wrong is refused, never skipped.

    Refused here: an unknown key; a cluster with fewer than two members or a
    repeated member; a specific member that is not a member; a member in two
    clusters; a `resolution` whose run is not one of the scored runs, or whose
    `supersedes` names a non-member or the fresh sidecar itself.
    Refused later, against the data: an unknown prediction id, members of
    different people (`check_restatement_records`), and a specific member with no
    resolution or prior while another member has one (`check_specific_sidecars`).
    """
    doc = json.loads(Path(path).read_text())
    bad = sorted(set(doc) ^ MANIFEST_KEYS)
    if bad or doc.get("schema_version") != 1 or not isinstance(doc.get("clusters"), list):
        raise SystemExit(f"{path}: a restatement manifest carries exactly {sorted(MANIFEST_KEYS)} with "
                         f"schema_version 1 and a list of clusters; differs at {bad or 'schema_version/clusters'}")
    run_set = {Path(r).resolve() for r in runs}
    owner: dict[str, str] = {}
    ids: set[str] = set()
    for c in doc["clusters"]:
        cid = c.get("cluster_id")
        if set(c) - CLUSTER_KEYS or CLUSTER_REQUIRED - set(c):
            raise SystemExit(f"{path}: cluster {cid!r} has keys {sorted(c)}; required "
                             f"{sorted(CLUSTER_REQUIRED)}, allowed {sorted(CLUSTER_KEYS)}")
        if cid in ids:
            raise SystemExit(f"{path}: cluster id {cid} appears twice")
        ids.add(cid)
        m = c["members"]
        if not isinstance(m, list) or len(m) < 2 or len(set(m)) != len(m):
            raise SystemExit(f"{path}: cluster {cid} needs two or more distinct members, has {m}")
        if c["specific_member"] not in m:
            raise SystemExit(f"{path}: cluster {cid} names specific_member {c['specific_member']}, "
                             f"which is not among its members {m}")
        for pid in m:
            if pid in owner:
                raise SystemExit(f"{path}: prediction {pid} is a member of two clusters, "
                                 f"{owner[pid]} and {cid}; a prediction restates one event at most")
            owner[pid] = cid
        res = c.get("resolution")
        if res is None:
            continue
        if set(res) - RESOLUTION_KEYS or not res.get("run") or not res.get("supersedes") or not res.get("why"):
            raise SystemExit(f"{path}: cluster {cid}'s resolution needs run, a non-empty supersedes "
                             f"list and why; has {sorted(res)}")
        if (root / res["run"]).resolve() not in run_set:
            raise SystemExit(f"{path}: cluster {cid}'s resolution run {res['run']} is not one of the "
                             f"runs being scored")
        for s in res["supersedes"]:
            if set(s) != {"run", "prediction_id"} or s["prediction_id"] not in m:
                raise SystemExit(f"{path}: cluster {cid} supersedes {s}, which is not a member's "
                                 f"sidecar named by run and prediction_id")
            if (root / s["run"]).resolve() not in run_set:
                raise SystemExit(f"{path}: cluster {cid} supersedes a sidecar in {s['run']}, which is "
                                 f"not one of the runs being scored")
            if (root / s["run"]).resolve() == (root / res["run"]).resolve() \
                    and s["prediction_id"] == c["specific_member"]:
                raise SystemExit(f"{path}: cluster {cid} supersedes the very resolution it names")
    return doc


def superseded_keys(doc: dict, root: Path) -> set[tuple[Path, str]]:
    return {((root / s["run"]).resolve(), s["prediction_id"])
            for c in doc["clusters"] for s in (c.get("resolution") or {}).get("supersedes", [])}


def check_restatement_records(doc: dict, records: dict[str, dict]) -> None:
    unknown = sorted(pid for c in doc["clusters"] for pid in c["members"] if pid not in records)
    if unknown:
        raise SystemExit(f"the restatement manifest names {len(unknown)} prediction id(s) that are no "
                         f"accepted record in the corpora being scored: {unknown}")
    for c in doc["clusters"]:
        who = {pid: records[pid]["leader_slug"] for pid in c["members"]}
        if set(who.values()) != {c["leader_slug"]}:
            raise SystemExit(f"cluster {c['cluster_id']} is {c['leader_slug']}'s, but its members "
                             f"belong to {who}; a restatement is one person's")


def check_specific_sidecars(doc: dict, resolutions: dict, priors: dict, root: Path) -> None:
    """Never borrow another member's verdict, and never lose one silently."""
    for c in doc["clusters"]:
        spec, others = c["specific_member"], [m for m in c["members"] if m != c["specific_member"]]
        for stage, have in (("resolution", resolutions), ("prior", priors)):
            if spec not in have and any(m in have for m in others):
                raise SystemExit(
                    f"cluster {c['cluster_id']}: the specific member {spec} has no {stage} while "
                    f"{[m for m in others if m in have]} do; the merged prediction must be settled on "
                    f"its own {stage}, so give it one (and name it in the manifest) rather than "
                    f"borrowing another member's")
        res = c.get("resolution")
        if res is not None:
            fresh = R.load_sidecars(root / res["run"], "resolve")
            if spec not in fresh:
                raise SystemExit(f"cluster {c['cluster_id']}: the manifest says {spec}'s resolution is in "
                                 f"{res['run']}, and there is none there")


def restatement_report(doc: dict, path_rel: str, sha: str, joined: list[dict], resolutions: dict,
                       dropped: dict, root: Path) -> dict:
    by = {r["prediction_id"]: r for r in joined}
    clusters = []
    for c in doc["clusters"]:
        spec = c["specific_member"]
        row = by.get(spec)
        state = ("not_past_due" if row is None else "scored" if row["scored"]
                 else f"not_scored:{row['not_scored_because']}")
        outcomes = {m: resolutions[m]["outcome"] for m in c["members"] if m in resolutions}
        entry = {"cluster_id": c["cluster_id"], "leader_slug": c["leader_slug"], "specific_member": spec,
                 "members": list(c["members"]), "specific_member_state": state,
                 "points": row["points"] if row else None, "member_outcomes": outcomes,
                 "member_outcomes_disagree": len(set(outcomes.values())) > 1}
        if c.get("resolution"):
            entry["resolution"] = c["resolution"]
        clusters.append(entry)
    owner = {s["prediction_id"]: c["cluster_id"] for c in doc["clusters"]
             for s in (c.get("resolution") or {}).get("supersedes", [])}
    sup = [{"cluster_id": owner[pid], "run": rel(run, root), "prediction_id": pid, "outcome": obj.get("outcome")}
           for (run, pid), obj in sorted(dropped.items(), key=lambda kv: (owner[kv[0][1]], kv[0][1], str(kv[0][0])))]
    return {"manifest": path_rel, "manifest_sha256": sha, "derived_from": doc.get("derived_from"),
            "clusters": clusters, "superseded_resolutions": sup,
            "restated_rows": sum(1 for r in joined if is_restated(r))}


# ---------------------------------------------------------------------------
# Replacements
# ---------------------------------------------------------------------------
#
# A re-resolved or re-priced result is written into a NEW run: a run is the record
# of one pass, and an experiment clone may write only its own. The old run's
# sidecar for that prediction stays on disk, and two sidecars for one prediction
# stop the scorer (load_across). The restatement manifest lifts that only for a
# restated cluster's resolution. The replacement manifest is the general way
# past it (critique A1, rescue round 4): each entry names the stage, the
# prediction, the run whose sidecar is replaced, the run holding its
# replacement, and why. Anything it does not name still stops the scorer.

REPLACEMENT_MANIFEST_KEYS = {"schema_version", "replacements"}
REPLACEMENT_KEYS = {"stage", "prediction_id", "run", "replacement", "reason"}
# The stages load_across merges across runs that a re-run can produce. Criteria
# repairs also load across runs, and are not replaceable here until a re-run
# needs it.
REPLACEMENT_STAGES = ("resolve", "prior")


def read_replacements(path: Path, root: Path, runs: list[Path]) -> dict:
    """The manifest, checked for shape. Everything wrong is refused, never skipped.

    Refused here: a missing file; an unknown or missing key; a stage other than
    resolve or prior; an empty field; a run or replacement that is not one of
    the scored runs; a replacement equal to the run it replaces; the same
    (stage, prediction, run) twice; two replacements for one (stage,
    prediction); a chain, where a replacement is itself replaced.
    Refused later, against the data: an unknown prediction id (main), and a
    replaced sidecar or a replacement that is not there (load_across).
    """
    if not Path(path).is_file():
        raise SystemExit(f"replacement manifest {path} does not exist")
    doc = json.loads(Path(path).read_text())
    bad = sorted(set(doc) ^ REPLACEMENT_MANIFEST_KEYS)
    if bad or doc.get("schema_version") != 1 or not isinstance(doc.get("replacements"), list):
        raise SystemExit(f"{path}: a replacement manifest carries exactly {sorted(REPLACEMENT_MANIFEST_KEYS)} "
                         f"with schema_version 1 and a list of replacements; differs at "
                         f"{bad or 'schema_version/replacements'}")
    run_set = {Path(r).resolve() for r in runs}
    seen: set[tuple[str, str, Path]] = set()
    groups: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for e in doc["replacements"]:
        if not isinstance(e, dict) or set(e) != REPLACEMENT_KEYS:
            raise SystemExit(f"{path}: replacement {e!r} must carry exactly {sorted(REPLACEMENT_KEYS)}")
        empty = sorted(k for k in REPLACEMENT_KEYS if not (isinstance(e[k], str) and e[k].strip()))
        if empty:
            raise SystemExit(f"{path}: replacement {e!r} has no {empty}; each is a non-empty string")
        if e["stage"] not in REPLACEMENT_STAGES:
            raise SystemExit(f"{path}: replacement of {e['prediction_id']} names stage {e['stage']!r}; "
                             f"a replacement is one of {list(REPLACEMENT_STAGES)}")
        old, new = (root / e["run"]).resolve(), (root / e["replacement"]).resolve()
        for k, p in (("run", old), ("replacement", new)):
            if p not in run_set:
                raise SystemExit(f"{path}: replacement of {e['prediction_id']} names {k} {e[k]}, which is not "
                                 f"one of the runs being scored")
        if old == new:
            raise SystemExit(f"{path}: replacement of {e['prediction_id']} names {e['run']} as both the run "
                             f"replaced and the replacement")
        key = (e["stage"], e["prediction_id"], old)
        if key in seen:
            raise SystemExit(f"{path}: the {e['stage']} sidecar of {e['prediction_id']} in {e['run']} is "
                             f"replaced twice")
        seen.add(key)
        groups[(e["stage"], e["prediction_id"])].append(e)
    for (stage, pid), es in groups.items():
        olds = {(root / e["run"]).resolve() for e in es}
        news = {(root / e["replacement"]).resolve() for e in es}
        if olds & news:
            raise SystemExit(f"{path}: the {stage} sidecar of {pid} in {sorted(str(x) for x in olds & news)} is "
                             f"both replaced and a replacement, a chain; name the final sidecar as the "
                             f"replacement of every earlier one")
        if len(news) > 1:
            raise SystemExit(f"{path}: the {stage} sidecar of {pid} has two replacements, "
                             f"{sorted(str(x) for x in news)}; a prediction has one result per stage")
    return doc


def replacement_map(doc: dict, root: Path, stage: str) -> dict[tuple[Path, str], Path]:
    """(replaced run, prediction_id) -> replacement run, for one stage."""
    return {((root / e["run"]).resolve(), e["prediction_id"]): (root / e["replacement"]).resolve()
            for e in doc["replacements"] if e["stage"] == stage}


def replacement_report(doc: dict, path_rel: str, sha: str, replaced: dict[str, dict],
                       merged: dict[str, dict], root: Path) -> dict:
    """Every replaced sidecar, with what it said and what the replacement says."""
    field = {"resolve": "outcome", "prior": "p"}
    why = {(e["stage"], (root / e["run"]).resolve(), e["prediction_id"]): e for e in doc["replacements"]}
    out = []
    for stage in REPLACEMENT_STAGES:
        for (run, pid), obj in replaced[stage].items():
            e = why[(stage, run, pid)]
            out.append({"stage": stage, "prediction_id": pid, "run": rel(run, root),
                        "replacement": rel(root / e["replacement"], root), "reason": e["reason"],
                        "was": obj.get(field[stage]), "now": merged[stage][pid].get(field[stage])})
    out.sort(key=lambda x: (x["stage"], x["prediction_id"], x["run"]))
    return {"manifest": path_rel, "manifest_sha256": sha, "replaced_sidecars": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None,
                    help="a scoring config (predictions/scoring.json); replaces every flag below")
    ap.add_argument("--run", type=Path, action="append", default=None,
                    help="an experiment run directory; repeat it to read several runs as one. "
                         "A prediction with sidecars in two runs is refused")
    ap.add_argument("--predictions", type=Path, action="append", default=None,
                    help="a corpus directory; repeat it to score several corpora together")
    ap.add_argument("--index", type=Path, default=None, help="default data/predictions/index.json")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--min-lead-days", type=int, default=None, help=f"default {P2.MIN_LEAD_DAYS}")
    ap.add_argument("--trend", action="store_const", const=True, default=None,
                    help="include undated directional claims judged over the elapsed window")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--restatements", type=Path, default=None,
                    help="a restatement manifest; each cluster scores once, as its specific_member")
    ap.add_argument("--date-overrides", type=Path, default=None,
                    help=f"reviewed statement-date override file; default <data>/{L.DATE_OVERRIDES_FILE} when it exists")
    ap.add_argument("--replacements", type=Path, default=None,
                    help="a replacement manifest; each entry lets a sidecar in a newer run replace an older "
                         "run's sidecar for the same prediction")
    args = ap.parse_args(argv)
    flags = {"--run": args.run, "--predictions": args.predictions, "--index": args.index, "--as-of": args.as_of,
             "--min-lead-days": args.min_lead_days, "--trend": args.trend, "--out": args.out,
             "--restatements": args.restatements, "--date-overrides": args.date_overrides,
             "--replacements": args.replacements}
    if args.config is not None:
        mixed = [k for k, v in flags.items() if v is not None]
        if mixed:
            raise SystemExit(f"--config replaces {mixed}; pass one or the other")
        root, cfg = load_config(args.config)
        args.run = [root / r for r in cfg["runs"]]
        args.predictions = [root / p for p in cfg["predictions"]]
        args.index = root / cfg["index"]
        args.as_of, args.min_lead_days, args.trend = cfg["as_of"], cfg["min_lead_days"], cfg["trend"]
        args.out = root / cfg["out"]
        args.restatements = root / cfg["restatements"] if "restatements" in cfg else None
        args.replacements = root / cfg["replacements"] if "replacements" in cfg else None
        # A committed config names its override file, so staleness hashing covers
        # it. One that is silent while the production file exists is refused
        # rather than scored as if the overrides were not there.
        if "date_overrides" in cfg:
            args.date_overrides = root / cfg["date_overrides"]
        elif (root / L.DATE_OVERRIDES_FILE).exists():
            raise SystemExit(f"{args.config} names no date_overrides, but {root / L.DATE_OVERRIDES_FILE} exists; "
                             f'add "date_overrides": "{L.DATE_OVERRIDES_FILE}" so the scores read it')
    else:
        if not args.run or args.as_of is None:
            raise SystemExit("pass --config, or at least one --run and --as-of")
        args.predictions = args.predictions or [Path("data/predictions")]
        args.index = args.index or Path("data/predictions/index.json")
        args.min_lead_days = P2.MIN_LEAD_DAYS if args.min_lead_days is None else args.min_lead_days
        args.trend = bool(args.trend)
    root = args.predictions[0].resolve().parent
    settings = {"as_of": args.as_of, "trend": args.trend, "min_lead_days": args.min_lead_days,
                "predictions": [rel(p, root) for p in args.predictions],
                "runs": [rel(r, root) for r in args.run], "index": rel(args.index, root)}
    if args.restatements is not None:
        # Only when named, so a scoring run without a manifest writes exactly what it did before.
        settings["restatements"] = rel(args.restatements, root)
    if args.replacements is not None:
        # Only when named, for the same reason: absent, scores.json is byte-identical to before.
        settings["replacements"] = rel(args.replacements, root)
    ov_path, date_overrides = date_overrides_for(args.date_overrides, args.predictions)
    if ov_path is not None:
        # Only when used, so a scores.json computed without overrides is unchanged.
        settings["date_overrides"] = rel(ov_path, root)

    try:
        cutoff = dt.date.fromisoformat(args.as_of)
    except ValueError:
        raise SystemExit(f"--as-of {args.as_of!r} is not a YYYY-MM-DD date")

    # Statement-date overrides first: which records the override superseded must
    # be known before any sidecar is read, so stale sidecars are dropped before
    # the duplicate and window checks below. See drop_stale_sidecars.
    ov_in = date_overrides if ov_path is not None else None
    superseded: list[dict] = []
    loaded = P2.load(args.predictions, date_overrides=ov_in, superseded=superseded)
    live_ids = {r["prediction_id"] for r in loaded}
    live_tids = {r["transcript_id"] for r in loaded}
    sup_ids = {s["prediction_id"] for s in superseded}
    stale: list[dict] = []

    def fresh(loader, stage):
        if ov_path is None:
            return loader
        return lambda run: drop_stale_sidecars(loader(run), date_overrides, sup_ids, live_ids,
                                                     rel(run, root), stage, stale)

    manifest = read_restatements(args.restatements, root, args.run) if args.restatements is not None else None
    swaps = read_replacements(args.replacements, root, args.run) if args.replacements is not None else None
    if swaps is not None:
        unknown = sorted({e["prediction_id"] for e in swaps["replacements"]} - live_ids)
        if unknown:
            raise SystemExit(f"the replacement manifest names {len(unknown)} prediction id(s) that are no accepted "
                             f"record in the corpora being scored: {unknown}")
    dropped: dict = {}
    replaced: dict[str, dict] = {stage: {} for stage in REPLACEMENT_STAGES}
    resolutions = load_across(args.run, fresh(lambda run: R.load_sidecars(run, "resolve"), "resolve"),
                              drop=superseded_keys(manifest, root) if manifest else None, dropped=dropped,
                              replace=replacement_map(swaps, root, "resolve") if swaps else None,
                              replaced=replaced["resolve"])
    priors = load_across(args.run, fresh(lambda run: R.load_sidecars(run, "prior"), "prior"),
                         replace=replacement_map(swaps, root, "prior") if swaps else None,
                         replaced=replaced["prior"])
    restated: dict[str, str] = {}
    if manifest is not None:
        check_restatement_records(manifest, {r["prediction_id"]: r for r in loaded})
        check_specific_sidecars(manifest, resolutions, priors, root)
        restated = {m: c["specific_member"] for c in manifest["clusters"]
                    for m in c["members"] if m != c["specific_member"]}
    # A prior and a resolution of one prediction must describe ONE window, or the
    # points price one question and settle another. Every production prior records
    # the window it priced; a prior that records none has nothing to compare.
    split = sorted(pid for pid in resolutions.keys() & priors.keys() if "deadline" in priors[pid]
                   and priors[pid]["deadline"] != resolutions[pid].get("deadline"))
    if split:
        raise SystemExit(f"{len(split)} predictions were priced over a different window than they were "
                         f"resolved over: " + "; ".join(
                             f"{pid} prior {priors[pid].get('deadline')} resolution "
                             f"{resolutions[pid].get('deadline')}" for pid in split))
    # Resolved trend records keep the window their resolution judged; see select().
    rows = select(args.predictions, cutoff, args.min_lead_days, trend=args.trend, resolutions=resolutions,
                  date_overrides=ov_in)
    repairs = load_across(args.run, fresh(R.load_repairs, "criteria_repair"))
    applied, unrepairable = R.apply_repairs(rows, repairs)

    joined, why = join(rows, resolutions, priors, restated)
    index = json.loads(args.index.read_text())
    names = {l["slug"]: l["name"] for l in index["leaders"]}
    leaders = per_leader(joined, names, with_restated=manifest is not None)

    scored = [r for r in joined if r["scored"]]
    outcomes = collections.Counter(r["outcome"] for r in joined if r["outcome"])
    reasons = collections.Counter(r["unresolvable_reason"] for r in joined if r["unresolvable_reason"])
    conf = collections.Counter(r["resolution_confidence"] for r in joined if r["resolution_confidence"])
    nosrc = sum(1 for r in joined if r["outcome"] in ("occurred", "not_occurred") and not r["sources"])

    doc = {
        "as_of": args.as_of,
        "run_dir": settings["runs"][0],
        "run_dirs": settings["runs"],
        "settings": settings,
        "inputs_sha256": score_inputs_sha256(root, settings),
        "rule": {
            "clamp": PS.CLAMP,
            "min_scored_to_rank": MIN_SCORED_TO_RANK,
            "min_lead_days": args.min_lead_days,
            "baseline_only": "points = -log2(p) if it happened, else (p/(1-p))*log2(p)",
            "speaker_probability": "points = log2(q/p) if it happened, else log2((1-q)/(1-p))",
            "expected_points_at_every_p": 0.0,
        },
        "corpus": {
            "past_due": len(rows),
            "eligible": sum(1 for r in joined if r["flags"]["eligible"] and not is_restated(r)),
            "criteria_repairs_applied": applied,
            "criteria_unrepairable": unrepairable,
            "resolutions_present": len(resolutions),
            "priors_present": len(priors),
            "by_outcome": dict(outcomes),
            "unresolvable_reasons": dict(reasons),
            "resolution_confidence": dict(conf),
            "resolved_with_no_source": nosrc,
            "scored": len(scored),
            "not_scored_because": dict(why),
            "speaker_stated_q": sum(1 for r in joined if r["q"] is not None),
            "mean_points_all_scored": round(sum(r["points"] for r in scored) / len(scored), 4) if scored else None,
            "leaders_ranked": sum(1 for l in leaders if l["ranked"]),
        },
        "calibration": calibration(joined),
        "leaders": leaders,
        "predictions": joined,
    }
    if manifest is not None:
        doc["corpus"]["restated"] = sum(1 for r in joined if is_restated(r))
        doc["restatements"] = restatement_report(
            manifest, settings["restatements"], hashlib.sha256(args.restatements.read_bytes()).hexdigest(),
            joined, resolutions, dropped, root)
    if swaps is not None:
        doc["replacements"] = replacement_report(
            swaps, settings["replacements"], hashlib.sha256(args.replacements.read_bytes()).hexdigest(),
            replaced, {"resolve": resolutions, "prior": priors}, root)
    if ov_path is not None:
        doc["date_overrides"] = {
            "file": settings["date_overrides"],
            "entries": sorted(date_overrides),
            "superseded_records": sorted(superseded, key=lambda s: (s["transcript_id"], s["prediction_id"] or "")),
            "stale_sidecars_dropped": sorted(stale, key=lambda s: (s["prediction_id"], s["stage"], s["run"])),
            # Loaded, checked, and matching no record in any corpus read: reported, never silent.
            "entries_without_records": sorted(set(date_overrides) - live_tids
                                              - {s["transcript_id"] for s in superseded}),
        }
    out = args.out or (args.run[0] / "scores.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")

    c = doc["corpus"]
    print(f"{c['past_due']} past due -> {c['eligible']} eligible -> {c['resolutions_present']} resolved "
          f"-> {c['scored']} scored across {c['leaders_ranked']} ranked leaders")
    print(f"outcomes: {json.dumps(c['by_outcome'], sort_keys=True)}")
    print(f"unresolvable: {json.dumps(c['unresolvable_reasons'], sort_keys=True)}")
    print(f"not scored: {json.dumps(c['not_scored_because'], sort_keys=True)}")
    print(f"criteria repaired: {applied} applied, {unrepairable} unrepairable")
    if manifest is not None:
        rs = doc["restatements"]
        print(f"restatements: {len(rs['clusters'])} clusters, {rs['restated_rows']} past-due rows not scored "
              f"as restated, {len(rs['superseded_resolutions'])} resolution sidecars superseded")
        for x in rs["superseded_resolutions"]:
            print(f"  superseded: {x['prediction_id']} in {x['run']} ({x['outcome']}) by {x['cluster_id']}")
    if swaps is not None:
        rp = doc["replacements"]["replaced_sidecars"]
        print(f"replacements: {doc['replacements']['manifest']}, {len(rp)} sidecars replaced")
        for x in rp:
            print(f"  replaced: {x['stage']} {x['prediction_id']} in {x['run']} ({x['was']}) by "
                  f"{x['replacement']} ({x['now']}): {x['reason']}")
    if ov_path is not None:
        o = doc["date_overrides"]
        print(f"date overrides: {o['file']} ({len(o['entries'])} entries); superseded records "
              f"{[s['prediction_id'] for s in o['superseded_records']]}; stale sidecars dropped "
              f"{[(s['prediction_id'], s['stage'], s['run']) for s in o['stale_sidecars_dropped']]}; "
              f"entries without records {o['entries_without_records']}")
    if nosrc:
        print(f"WARNING: {nosrc} decided outcomes cite no source")
    cal = doc["calibration"]
    print(f"\nIS THE PRIOR ASSESSOR CALIBRATED?  n={cal['n']}  mean p {cal['mean_p']}  "
          f"hit rate {cal['hit_rate']}  gap {cal['gap']:+.3f}" if cal["n"] else "\nno scored predictions")
    if cal["n"]:
        print(f"  {cal['reading']}")
        print(f"  {'p bin':>9} {'n':>4} {'mean p':>7} {'hit':>6} {'gap':>7} {'points':>8}")
        for b in cal["bins"]:
            if b["n"]:
                print(f"  {b['bin']:>9} {b['n']:4} {b['mean_p']:7.2f} {b['hit_rate']:6.2f} "
                      f"{b['gap']:+7.2f} {b['mean_points']:+8.3f}")
    print(f"\n{'leader':28} {'n':>4} {'mean':>7} {'hit':>6} {'mean p':>7}")
    for l in leaders:
        if l["n_scored"]:
            flag = "" if l["ranked"] else "  (unranked)"
            print(f"{l['name'][:28]:28} {l['n_scored']:4} {l['mean_points']:+7.3f} "
                  f"{l['hit_rate']:6.2f} {l['mean_p']:7.2f}{flag}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
