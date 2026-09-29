#!/usr/bin/env python3
"""A restated prediction scores ONCE, as its cluster's specific member.

Operator decisions, 2026-09-28 (data run `restatements-20260928/DECISIONS.md`):
a person who says the same thing on several days made one prediction, and the
merged prediction is dated at the EARLIEST member specific enough on its own.
The restatement manifest names each cluster's members and that `specific_member`.

What this pins, end to end through `score_predictions.py`:
  - the specific member scores with its OWN resolution, prior and statement
    date; every other member is a row with `not_scored_because`
    `restated:<specific_member>`, never dropped, and the accounting still adds
    up per person and for the corpus;
  - a restated row carries no outcome or p of its own in the scored fields, so
    no count of outcomes counts one event twice;
  - the specific member's lead time is its own: a late specific member is not
    rescued by an earlier member's eligibility;
  - it REFUSES an unknown prediction id, a member in two clusters, members of
    different people, and a specific member with no resolution (or no prior)
    while another member has one, since that would silently lose or borrow one;
  - a cluster may name a fresh resolution that SUPERSEDES named older sidecars.
    Without that entry the same prediction in two runs is still refused; with
    it the fresh one is used and the superseded ones are reported. A superseded
    sidecar that does not exist is refused, and a prior priced over a different
    window than the fresh resolution is still refused;
  - with no manifest the output carries no restatement field at all, and an
    empty manifest changes no score;
  - `--config` accepts an optional `restatements` key, and the manifest's bytes
    are part of `inputs_sha256`, so editing it makes scores.json stale.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import resolution_lib as R  # noqa: E402
import data_clone_workflow as D  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, slug="ada", said="2019-01-01", target="2020-12-31"):
    return {
        "accepted": True, "leader_slug": slug, "prediction_id": pid, "transcript_id": f"{slug}/t1",
        "prediction": {"target_date": target, "specificity": "high", "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": f"claim {pid}", "resolution_criteria": "crit"},
        "source": {"statement_date": said, "quote": f"quote {pid}"},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def write(run, pid, stage, slug="ada", **kw):
    if stage == "resolve":
        obj = {"prediction_id": pid, "leader_slug": slug, "transcript_id": f"{slug}/t1", "stage": "resolve",
               "outcome": "occurred", "confidence": "high", "unresolvable_reason": None, "reasoning": "r",
               "sources": [{"where": "u", "what_it_shows": "w", "date": None}], "deadline": "2020-12-31"}
    else:
        obj = {"prediction_id": pid, "leader_slug": slug, "transcript_id": f"{slug}/t1", "stage": "prior",
               "p": 0.5, "p_raw": 0.5, "clamped": False, "reference_class": "rc", "reasoning": "r",
               "deadline": "2020-12-31"}
    obj.update(kw)
    fp = R.sidecar_path(run, stage, slug, pid)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(obj))


def cluster(cid, specific, members, slug="ada", **kw):
    return {"cluster_id": cid, "leader_slug": slug, "specific_member": specific, "members": members, **kw}


def manifest(path, clusters):
    path.write_text(json.dumps({"schema_version": 1, "derived_from": {"file": "fixture", "sha256": "0"},
                                "clusters": clusters}))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        corpus = d / "predictions"
        (corpus / "ada").mkdir(parents=True)
        (corpus / "bob").mkdir()
        # p1 early and specific, p2 a later restatement, p3 unrelated. p4 is a late
        # restatement said 20 days before the deadline, so it alone is not eligible.
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
            rec("p1"), rec("p2", said="2019-06-01"), rec("p3"), rec("p4", said="2020-12-11"),
            rec("p5"), rec("p6", said="2019-03-01"))))
        (corpus / "bob" / "t1.jsonl").write_text(json.dumps(rec("b1", slug="bob")) + "\n")
        index = corpus / "index.json"
        index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}, {"slug": "bob", "name": "Bob B"}]}))
        a, fresh = d / "run-a", d / "run-fresh"
        for pid in ("p1", "p2", "p3", "p4", "p5", "p6"):
            write(a, pid, "resolve", outcome="not_occurred" if pid == "p2" else "occurred")
            write(a, pid, "prior")
        write(a, "b1", "resolve", slug="bob"); write(a, "b1", "prior", slug="bob")

        def score(*extra, runs=(a,), out):
            argv = [sys.executable, str(ROOT / "scripts" / "score_predictions.py"),
                    "--predictions", str(corpus), "--index", str(index), "--as-of", "2026-09-16",
                    "--min-lead-days", "60", "--out", str(out)]
            for r in runs:
                argv += ["--run", str(r)]
            return subprocess.run(argv + list(extra), capture_output=True, text=True)

        base = score(out=d / "base.json")
        check("NO MANIFEST: exits 0", base.returncode == 0, base.stderr[-600:])
        b = json.loads((d / "base.json").read_text()) if base.returncode == 0 else {}
        check("NO MANIFEST: the output carries no restatement field anywhere",
              "restatements" not in b and "restatements" not in b.get("settings", {})
              and "restated" not in b.get("corpus", {})
              and all("restated" not in l for l in b.get("leaders", [])), str(sorted(b)))

        m1 = manifest(d / "m1.json", [cluster("ada/one", "p1", ["p1", "p2"])])
        one = score("--restatements", str(m1), out=d / "one.json")
        check("CLUSTER: exits 0", one.returncode == 0, one.stderr[-600:])
        o = json.loads((d / "one.json").read_text()) if one.returncode == 0 else {}
        rows = {r["prediction_id"]: r for r in o.get("predictions", [])}
        check("CLUSTER: the specific member scores with its own resolution",
              rows.get("p1", {}).get("scored") is True and rows.get("p1", {})["outcome"] == "occurred", str(rows.get("p1")))
        check("CLUSTER: the other member is a row, not scored because restated:<specific_member>",
              rows.get("p2", {}).get("scored") is False
              and rows.get("p2", {}).get("not_scored_because") == "restated:p1", str(rows.get("p2")))
        check("CLUSTER: a restated row carries no outcome or p in the scored fields, and keeps its own for audit",
              rows.get("p2", {}).get("outcome") is None and rows.get("p2", {}).get("p") is None
              and rows.get("p2", {}).get("points") is None and rows.get("p2", {}).get("own_outcome") == "not_occurred",
              str(rows.get("p2")))
        c = o.get("corpus", {})
        check("CLUSTER: corpus accounting adds up: scored + every not-scored reason = past due",
              sum(c.get("not_scored_because", {}).values()) == c.get("past_due") and c.get("not_scored_because", {}).get("restated") == 1
              and c.get("restated") == 1, str(c))
        check("CLUSTER: outcome counts see one event once (p2's not_occurred is not counted)",
              c.get("by_outcome") == {"occurred": 6}, str(c.get("by_outcome")))
        ada = next((l for l in o.get("leaders", []) if l["slug"] == "ada"), {})
        check("CLUSTER: per person, scored + restated + other reasons = past due, and n_scored drops by one",
              ada.get("past_due") == 6 and ada.get("n_scored") == 4 and ada.get("restated") == 1
              and ada.get("eligible") == 4, str(ada))
        blk = o.get("restatements", {})
        check("CLUSTER: scores.json reports the manifest, its hash and each cluster's members",
              blk.get("manifest") and len(blk.get("manifest_sha256", "")) == 64
              and blk.get("clusters", [{}])[0].get("members") == ["p1", "p2"]
              and blk.get("clusters", [{}])[0].get("specific_member") == "p1"
              and o.get("settings", {}).get("restatements") == blk.get("manifest"), str(blk)[:400])
        check("CLUSTER: the member resolutions that disagree with the scored one are reported",
              blk.get("clusters", [{}])[0].get("member_outcomes") == {"p1": "occurred", "p2": "not_occurred"},
              str(blk.get("clusters")))

        # The specific member is the LATE one: its own 20-day lead makes it an
        # announcement, and p1's lead is not borrowed.
        m2 = manifest(d / "m2.json", [cluster("ada/late", "p4", ["p3", "p4"])])
        late = score("--restatements", str(m2), out=d / "late.json")
        lr = {r["prediction_id"]: r for r in json.loads((d / "late.json").read_text()).get("predictions", [])} if late.returncode == 0 else {}
        check("LEAD: the specific member's own statement date sets lead time; nothing is borrowed",
              lr.get("p4", {}).get("not_scored_because") == "not_eligible:lead_under_floor"
              and lr.get("p3", {}).get("not_scored_because") == "restated:p4", late.stderr[-400:] or str(lr.get("p4")))

        def refused(label, clusters, needle, runs=(a,)):
            mp = manifest(d / f"bad-{len(FAILED)}-{abs(hash(label))}.json", clusters)
            out = d / f"out-{abs(hash(label))}.json"
            p = score("--restatements", str(mp), runs=runs, out=out)
            check(label, p.returncode != 0 and not out.exists() and all(n in p.stderr for n in needle),
                  f"rc={p.returncode} {p.stderr[-500:]}")

        refused("REFUSE: an unknown prediction id, naming it", [cluster("ada/x", "p1", ["p1", "nope"])], ["nope"])
        refused("REFUSE: a member in two clusters, naming the member and both clusters",
                [cluster("ada/x", "p1", ["p1", "p2"]), cluster("ada/y", "p3", ["p3", "p2"])], ["p2", "ada/x", "ada/y"])
        refused("REFUSE: members of different people", [cluster("ada/x", "p1", ["p1", "b1"])], ["b1", "bob"])
        refused("REFUSE: a specific member that is not a member", [cluster("ada/x", "p3", ["p1", "p2"])], ["p3"])
        refused("REFUSE: a cluster of one", [cluster("ada/x", "p1", ["p1"])], ["ada/x"])
        # p5 and p6: strip p6's resolution in a run of its own so p5 (the specific) lacks one
        noresA = d / "run-nores"
        for pid in ("p1", "p2", "p3", "p4", "p6"):
            write(noresA, pid, "resolve"); write(noresA, pid, "prior")
        write(noresA, "p5", "prior")
        write(noresA, "b1", "resolve", slug="bob"); write(noresA, "b1", "prior", slug="bob")
        refused("REFUSE: the specific member has no resolution while another member has one",
                [cluster("ada/x", "p5", ["p5", "p6"])], ["p5", "p6", "resolution"], runs=(noresA,))
        noprA = d / "run-nopr"
        for pid in ("p1", "p2", "p3", "p4", "p6"):
            write(noprA, pid, "resolve"); write(noprA, pid, "prior")
        write(noprA, "p5", "resolve")
        write(noprA, "b1", "resolve", slug="bob"); write(noprA, "b1", "prior", slug="bob")
        refused("REFUSE: the specific member has no prior while another member has one",
                [cluster("ada/x", "p5", ["p5", "p6"])], ["p5", "p6", "prior"], runs=(noprA,))

        # ---- a fresh resolution that supersedes older ones ----
        write(fresh, "p1", "resolve", outcome="not_occurred", reasoning="fresh")
        dup = score("--restatements", str(m1), runs=(a, fresh), out=d / "dup.json")
        check("SUPERSEDE: without a resolution entry the same prediction in two runs is still refused",
              dup.returncode != 0 and "p1" in dup.stderr, dup.stderr[-300:])
        sup = [{"run": "run-a", "prediction_id": "p1"}, {"run": "run-a", "prediction_id": "p2"}]
        m3 = manifest(d / "m3.json", [cluster("ada/one", "p1", ["p1", "p2"],
                                              resolution={"run": "run-fresh", "supersedes": sup, "why": "disagree"})])
        ok = score("--restatements", str(m3), runs=(a, fresh), out=d / "sup.json")
        check("SUPERSEDE: with the entry the scorer exits 0", ok.returncode == 0, ok.stderr[-600:])
        s = json.loads((d / "sup.json").read_text()) if ok.returncode == 0 else {}
        sr = {r["prediction_id"]: r for r in s.get("predictions", [])}
        check("SUPERSEDE: the specific member is scored on the fresh resolution",
              sr.get("p1", {}).get("outcome") == "not_occurred" and sr.get("p1", {}).get("resolution_reasoning") == "fresh",
              str(sr.get("p1")))
        rep = s.get("restatements", {}).get("superseded_resolutions")
        check("SUPERSEDE: every superseded sidecar is reported with its run and old outcome",
              rep == [{"cluster_id": "ada/one", "outcome": "occurred", "prediction_id": "p1", "run": "run-a"},
                      {"cluster_id": "ada/one", "outcome": "not_occurred", "prediction_id": "p2", "run": "run-a"}],
              str(rep))
        check("SUPERSEDE: resolutions_present counts only what was used",
              s.get("corpus", {}).get("resolutions_present") == 6, str(s.get("corpus", {}).get("resolutions_present")))
        m4 = manifest(d / "m4.json", [cluster("ada/one", "p1", ["p1", "p2"], resolution={
            "run": "run-fresh", "supersedes": [{"run": "run-a", "prediction_id": "p1"},
                                               {"run": "run-fresh", "prediction_id": "p2"}], "why": "x"})])
        miss = score("--restatements", str(m4), runs=(a, fresh), out=d / "miss.json")
        check("SUPERSEDE: a superseded sidecar that does not exist is refused, naming it",
              miss.returncode != 0 and "p2" in miss.stderr and "run-fresh" in miss.stderr, miss.stderr[-400:])
        m5 = manifest(d / "m5.json", [cluster("ada/one", "p1", ["p1", "p2"], resolution={
            "run": "run-nowhere", "supersedes": sup, "why": "x"})])
        nw = score("--restatements", str(m5), runs=(a, fresh), out=d / "nw.json")
        check("SUPERSEDE: a resolution run that is not one of the scored runs is refused",
              nw.returncode != 0 and "run-nowhere" in nw.stderr, nw.stderr[-400:])
        win = d / "run-win"
        write(win, "p1", "resolve", deadline="2021-06-30")
        mw = manifest(d / "mw.json", [cluster("ada/one", "p1", ["p1", "p2"], resolution={
            "run": "run-win", "supersedes": [{"run": "run-a", "prediction_id": "p1"}], "why": "x"})])
        ww = score("--restatements", str(mw), runs=(a, win), out=d / "ww.json")
        check("SUPERSEDE: a prior priced over a different window than the fresh resolution is refused",
              ww.returncode != 0 and "p1" in ww.stderr and "window" in ww.stderr, ww.stderr[-400:])

        # ---- an empty manifest changes no score ----
        me = manifest(d / "me.json", [])
        emp = score("--restatements", str(me), out=d / "emp.json")
        e = json.loads((d / "emp.json").read_text()) if emp.returncode == 0 else {}
        def strip(doc):
            doc = json.loads(json.dumps(doc))
            extra = [doc.get("corpus", {}).pop("restated", None)] + [l.pop("restated", None) for l in doc.get("leaders", [])]
            return doc, extra
        e2, extra = strip(e)
        same = {k: (e2.get(k) == b.get(k)) for k in ("as_of", "rule", "calibration", "leaders", "predictions", "corpus", "run_dirs")}
        check("EMPTY MANIFEST: every block is identical to the no-manifest output, apart from restated counts of 0",
              emp.returncode == 0 and all(same.values()) and extra and all(x == 0 for x in extra),
              f"{emp.stderr[-300:]} {same} {extra}")

        # ---- --config ----
        data = d
        (data / "predictions" / "scoring.json").write_text(json.dumps({
            "as_of": "2026-09-16", "trend": False, "min_lead_days": 60, "predictions": ["predictions"],
            "runs": ["run-a"], "index": "predictions/index.json", "out": "predictions/scores.json",
            "restatements": "m1.json"}))
        cfgp = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"),
                               "--config", str(data / "predictions" / "scoring.json")], capture_output=True, text=True)
        cdoc = json.loads((data / "predictions" / "scores.json").read_text()) if cfgp.returncode == 0 else {}
        check("CONFIG: an optional restatements key is read from scoring.json",
              cfgp.returncode == 0 and cdoc.get("settings", {}).get("restatements") == "m1.json"
              and {r["prediction_id"]: r for r in cdoc.get("predictions", [])}.get("p2", {}).get("not_scored_because") == "restated:p1",
              cfgp.stderr[-400:])
        fresh_now = D.scores_staleness(data / "predictions" / "scores.json", data / "predictions" / "scoring.json")
        m1.write_text(json.dumps({"schema_version": 1, "derived_from": {"file": "f", "sha256": "0"}, "clusters": []}))
        stale = D.scores_staleness(data / "predictions" / "scores.json", data / "predictions" / "scoring.json")
        check("CONFIG: scores.json is fresh, then stale once the manifest's bytes change",
              fresh_now is None and stale is not None, f"{fresh_now!r} / {stale!r}")
        badk = json.loads((data / "predictions" / "scoring.json").read_text())
        badk["restatement"] = badk.pop("restatements")
        (data / "predictions" / "scoring.json").write_text(json.dumps(badk))
        typo = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"),
                               "--config", str(data / "predictions" / "scoring.json")], capture_output=True, text=True)
        check("CONFIG: a misspelled key is still refused", typo.returncode != 0 and "restatement" in typo.stderr,
              typo.stderr[-300:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
