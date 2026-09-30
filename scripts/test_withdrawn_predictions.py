#!/usr/bin/env python3
"""Single predictions withdrawn by the operator (predictions/withdrawn_predictions.json).

The per-transcript exclusion list withdraws a whole recording. This manifest
withdraws ONE prediction while the rest of its transcript stays, in the shape
the coordinator committed on data main (6e0ced71):

  {"schema_version": 1, "note": str, "withdrawn": {prediction_id: {"reason",
   "detail", "evidence": [http(s) urls], "transcript_id": "slug/source",
   "decided_by", "decided_at_utc": "YYYY-MM-DDTHH:MM:SSZ"}}}

What this pins:
  - the loader refuses an unknown prediction_id, a transcript_id that does not
    hold that prediction, a missing or an unknown key, anything but http(s)
    evidence and a malformed stamp, as the statement-date override loader does;
  - aggregate_predictions reads it only when told (--withdrawn), counts the
    withdrawn per person, and fingerprints it, so index_staleness sees an edit;
  - the scorer reads it only behind the optional scoring.json key `withdrawn`:
    a withdrawn row reads `withdrawn:<reason>` whatever else is true of it, is
    not eligible, and scores.json carries every entry, due or not, for the page;
    the manifest's bytes are part of inputs_sha256.
The first real entry, fixtured here only: Ellison's Buddy Media "prediction"
(2203621a4e46691a), reason not_a_forecast.
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
import data_clone_workflow as D  # noqa: E402
import predictions_lib as L  # noqa: E402
import resolution_lib as R  # noqa: E402

FAILED = []
PID = "2203621a4e46691a"
ENTRY = {
    "reason": "not_a_forecast",
    "detail": "Ellison at D10 on 2012-05-30 repeated the previous day's news: AllThingsD reported the deal as "
              "agreed on 2012-05-29.",
    "evidence": [
        "https://allthingsd.com/20120529/salesforce-set-to-snap-up-facebook-friend-buddy-media-for-more-than-800-million/",
        "https://allthingsd.com/20120530/oracle-ceo-larry-ellison-live-at-d10/",
        "https://www.salesforce.com/news/press-releases/2012/06/04/salesforce-com-signs-definitive-agreement-to-acquire-buddy-media/"],
    "transcript_id": "larry-ellison/ray-captain-fstuvv",
    "decided_by": "operator",
    "decided_at_utc": "2026-09-30T07:10:44Z",
}


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def manifest(entries=None, **top):
    doc = {"schema_version": 1, "note": "withdrawn by the operator", "withdrawn": {PID: ENTRY} if entries is None else entries}
    doc.update(top)
    return doc


def rec(pid, tid="larry-ellison/ray-captain-fstuvv", target="2013-12-31", accepted=True):
    slug = tid.split("/")[0]
    return {"accepted": accepted, "leader_slug": slug, "prediction_id": pid, "transcript_id": tid,
            "prediction": {"target_date": target, "target_date_text": None, "horizon_years_inferred": None,
                           "specificity": "high", "subject_control": "external", "category": "company_business",
                           "prediction_type": "binary_event", "horizon": "none",
                           "normalized_claim": "Salesforce will acquire Buddy Media.", "resolution_criteria": "crit"},
            "source": {"statement_date": "2012-05-30", "quote": "I think Salesforce is gonna buy body media"},
            "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None}}


def full(r):
    """The thin record, with the fields aggregate_predictions reads."""
    side = {"qualifies": True, "status": "ok", "agreement": True, "run_id": "run-x", "contract_id": "c" * 12,
            "served_model": "m", "requested_model": "m", "harness": "astra", "telemetry": {}}
    return {**r, "extraction": dict(side), "verification": dict(side, harness="fable"),
            "confidence": {"type": "none", "probability": None}}


def refused(label, doc, needle, records):
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "w.json"
        p.write_text(json.dumps(doc))
        try:
            L.load_withdrawn(p, records)
            check(label, False, "accepted")
        except L.PredictionError as e:
            check(label, needle in str(e), str(e))


def main() -> int:
    records = {PID: rec(PID), "keep": rec("keep"), "rej": rec("rej", accepted=False)}
    print("the loader, in the committed shape")
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "w.json"
        p.write_text(json.dumps(manifest()))
        got = L.load_withdrawn(p, records)
        check("LOAD: the committed shape loads, keyed by prediction_id", got == {PID: ENTRY}, str(got))
    refused("REFUSE: an unknown prediction_id", manifest({"nope": ENTRY}), "nope", records)
    refused("REFUSE: a rejected record is not a prediction to withdraw", manifest({"rej": ENTRY}), "rej", records)
    refused("REFUSE: a transcript_id that does not hold the prediction",
            manifest({PID: dict(ENTRY, transcript_id="larry-ellison/other")}), "larry-ellison/other", records)
    for k in ENTRY:
        refused(f"REFUSE: an entry missing {k}", manifest({PID: {x: v for x, v in ENTRY.items() if x != k}}), k, records)
    refused("REFUSE: an unknown key in an entry", manifest({PID: dict(ENTRY, note="x")}), "note", records)
    refused("REFUSE: an unknown top-level key", manifest(extra=1), "extra", records)
    refused("REFUSE: another schema_version", manifest(schema_version=2), "schema_version", records)
    refused("REFUSE: evidence that is not http(s)", manifest({PID: dict(ENTRY, evidence=["file:///x"])}), "evidence", records)
    refused("REFUSE: no evidence", manifest({PID: dict(ENTRY, evidence=[])}), "evidence", records)
    refused("REFUSE: a stamp that is not YYYY-MM-DDTHH:MM:SSZ",
            manifest({PID: dict(ENTRY, decided_at_utc="2026-09-30 07:10")}), "decided_at_utc", records)
    refused("REFUSE: a reason that is not a lower-case word", manifest({PID: dict(ENTRY, reason="Not a forecast")}),
            "reason", records)
    refused("REFUSE: an empty detail", manifest({PID: dict(ENTRY, detail=" ")}), "detail", records)

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        corpus = root / "predictions"
        for r in (full(rec(PID)), full(rec("keep")), full(rec("later", target="2031-12-31"))):
            d = corpus / r["leader_slug"]
            d.mkdir(parents=True, exist_ok=True)
            with (d / "ray-captain-fstuvv.jsonl").open("a") as fh:
                fh.write(json.dumps(r) + "\n")
        wf = corpus / "withdrawn_predictions.json"
        wf.write_text(json.dumps(manifest({PID: ENTRY, "later": ENTRY})))
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "larry-ellison", "name": "Larry E"}]}))
        run = corpus / "_experiments" / "run-a"
        for pid in (PID, "keep"):
            for stage, obj in (("resolve", {"outcome": "occurred", "confidence": "high", "unresolvable_reason": None,
                                             "reasoning": "r", "sources": [{"where": "u", "what_it_shows": "w",
                                                                            "date": None}]}),
                               ("prior", {"p": 0.5, "p_raw": 0.5, "clamped": False, "reference_class": "rc",
                                          "reasoning": "r"})):
                fp = R.sidecar_path(run, stage, "larry-ellison", pid)
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps({"prediction_id": pid, "leader_slug": "larry-ellison",
                                          "transcript_id": "larry-ellison/ray-captain-fstuvv", "stage": stage,
                                          "deadline": "2013-12-31", **obj}))
        cfg_path = corpus / "scoring.json"
        base = {"as_of": "2026-09-28", "trend": False, "min_lead_days": 60, "predictions": ["predictions"],
                "runs": ["predictions/_experiments/run-a"], "index": "predictions/index.json",
                "out": "predictions/scores.json"}

        def score(**extra):
            cfg_path.write_text(json.dumps({**base, **extra}))
            out = corpus / "scores.json"
            if out.exists():
                out.unlink()
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg_path)],
                               capture_output=True, text=True)
            return p, (json.loads(out.read_text()) if p.returncode == 0 else {})

        print("the scorer, behind the key `withdrawn`")
        p, off = score()
        rows = {x["prediction_id"]: x for x in off.get("predictions", [])}
        check("OFF: without the key the manifest is not read, and the prediction scores as before",
              p.returncode == 0 and rows.get(PID, {}).get("scored") is True and "withdrawn" not in off, p.stderr[-300:])
        p, doc = score(withdrawn="predictions/withdrawn_predictions.json")
        rows = {x["prediction_id"]: x for x in doc.get("predictions", [])}
        w = rows.get(PID, {})
        check("ON: a withdrawn prediction reads withdrawn:<reason>, though it was resolved, priced and eligible",
              p.returncode == 0 and w.get("not_scored_because") == "withdrawn:not_a_forecast" and not w.get("scored"),
              p.stderr[-300:] + json.dumps(w)[:300])
        check("ON: the row carries the reason, the detail and the evidence",
              w.get("withdrawn", {}).get("evidence") == ENTRY["evidence"] and w["withdrawn"]["reason"] == "not_a_forecast")
        check("ON: the other prediction of the same transcript still scores", rows.get("keep", {}).get("scored") is True)
        blk = doc.get("withdrawn", {})
        check("ON: scores.json carries every entry, due or not, with the manifest path and sha256",
              set(blk.get("entries", {})) == {PID, "later"} and blk.get("manifest") == "predictions/withdrawn_predictions.json"
              and len(blk.get("sha256", "")) == 64, json.dumps(blk)[:300])
        lead = {l["slug"]: l for l in doc.get("leaders", [])}.get("larry-ellison", {})
        check("ON: a withdrawn prediction is not counted eligible, and the person counts it",
              lead.get("eligible") == 1 and lead.get("withdrawn") == 1 and doc["corpus"].get("eligible") == 1,
              json.dumps(lead))
        check("FRESH: scores.json is current", D.scores_staleness(corpus / "scores.json", cfg_path) is None,
              str(D.scores_staleness(corpus / "scores.json", cfg_path)))
        wf.write_text(json.dumps(manifest({PID: dict(ENTRY, detail="edited")})))
        why = D.scores_staleness(corpus / "scores.json", cfg_path)
        check("FRESH: editing the manifest makes scores.json stale", why is not None and "input changed" in why, str(why))
        wf.write_text(json.dumps(manifest({PID: ENTRY, "nope": ENTRY})))
        p, _ = score(withdrawn="predictions/withdrawn_predictions.json")
        check("REFUSE: the scorer refuses a manifest naming an unknown prediction", p.returncode != 0 and "nope" in p.stderr,
              p.stderr[-300:])
        wf.write_text(json.dumps(manifest({PID: ENTRY, "later": ENTRY})))
        for bad in ("withdrawn.json", "../w.json", ""):
            cfg_path.write_text(json.dumps({**base, "withdrawn": bad}))
            try:
                D.load_scoring_config(cfg_path)
                check(f"CONFIG: withdrawn {bad!r} outside predictions/ is refused", False)
            except SystemExit as e:
                check(f"CONFIG: withdrawn {bad!r} outside predictions/ is refused", "withdrawn" in str(e), str(e))

        print("a withdrawn row the resolver could not settle")
        fp = R.sidecar_path(run, "resolve", "larry-ellison", PID)
        kept_res = fp.read_text()
        fp.write_text(json.dumps(dict(json.loads(kept_res), outcome="unresolvable", confidence="low",
                                      unresolvable_reason="no_public_evidence")))
        p, doc = score(withdrawn="predictions/withdrawn_predictions.json")
        w = {x["prediction_id"]: x for x in doc.get("predictions", [])}.get(PID, {})
        u = doc.get("corpus", {}).get("unresolvable_by_eligibility", {})
        check("SET ASIDE: a withdrawn row the resolver called unresolvable reads withdrawn, and neither half of "
              "unresolvable_by_eligibility counts it",
              p.returncode == 0 and w.get("not_scored_because") == "withdrawn:not_a_forecast"
              and u.get("eligible", {}).get("n") == 0 and u.get("not_eligible", {}).get("n") == 0,
              p.stderr[-300:] + json.dumps(u))
        fp.write_text(kept_res)

        print("aggregate_predictions, when told")
        def agg(*extra):
            out = root / f"index{len(extra)}.json"
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "aggregate_predictions.py"), "--predictions",
                                str(corpus), "--roster", str(roster), "--transcripts", str(tr), "--out", str(out),
                                *extra], capture_output=True, text=True, cwd=root)
            return p, (json.loads(out.read_text()) if p.returncode == 0 else {})
        roster = root / "roster.json"
        roster.write_text(json.dumps({"roster": [{"slug": "larry-ellison", "name": "Larry E"}]}))
        tr = root / "transcripts"
        (tr / "larry-ellison").mkdir(parents=True)
        (tr / "larry-ellison" / "ray-captain-fstuvv.json").write_text("{}")
        p0, plain = agg()
        p1, idx = agg("--withdrawn", str(wf))
        check("AGGREGATE: without --withdrawn the index carries no withdrawal field",
              p0.returncode == 0 and "withdrawn_sha256" not in plain and "withdrawn" not in plain["corpus"],
              p0.stderr[-400:])
        check("AGGREGATE: with it, the index counts the withdrawn per person and fingerprints the manifest",
              p1.returncode == 0 and idx.get("withdrawn_sha256") and idx["corpus"].get("withdrawn") == 2
              and {l["slug"]: l for l in idx["leaders"]}["larry-ellison"].get("withdrawn") == 2, p1.stderr[-400:])
        check("AGGREGATE: index_staleness accepts the index while the manifest is unchanged",
              D.index_staleness(idx, corpus, roster, [tr]) is None, str(D.index_staleness(idx, corpus, roster, [tr])))
        wf.write_text(json.dumps(manifest({PID: ENTRY})))
        why = D.index_staleness(idx, corpus, roster, [tr])
        check("AGGREGATE: index_staleness names an edited manifest", why is not None and "withdraw" in why, str(why))
        wf.write_text(json.dumps(manifest({"nope": ENTRY})))
        p2, _ = agg("--withdrawn", str(wf))
        check("AGGREGATE: an unknown prediction_id refuses the index", p2.returncode != 0 and "nope" in p2.stderr,
              p2.stderr[-300:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
