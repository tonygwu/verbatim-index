#!/usr/bin/env python3
"""The scorer under the 2026-09-29 policies, each behind an OPTIONAL scoring.json key.

Critique 3 A5 of the rescue round-4 design: landing a funnel policy in code
before its data would either block every clone's push or move the board with
nobody choosing to. So every new policy is an optional key, and absent means
exactly today's behaviour. This file pins, end to end through
score_predictions.py --config:
  - `implied_windows` names the implied table's sha256 (VD-6). The scorer judges
    records with no deadline over the table's window, refuses a config whose sha
    is not the table in the code, and never moves a trend record already
    resolved. A sidecar whose window is not the funnel's is a COUNTED per-row
    exclusion, `stale_sidecar:deadline_changed`, never a stop (A5), and the
    deploy refuses while any are counted (data_clone_workflow.scores_blockers);
  - `policy_releases` names the resolution-policy releases a board may carry. A
    sidecar written under a release the config does not name is refused, so a
    board never silently mixes two resolver policies (critique 3 A2); the counts
    per release and stage are reported;
  - a resolution that found the thing `already_public` before the statement is
    kept, reported, and not scored (operator, 2026-09-29);
  - with none of the keys, a sidecar-free corpus scores byte-identically to the
    code before this change (the production check is in the branch report).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import data_clone_workflow as D  # noqa: E402
import phase2_resolvability as P2  # noqa: E402
import resolution_lib as R  # noqa: E402

FAILED = []
REL = R.POLICY_RELEASE[0]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, *, said="2021-03-01", target=None, tdt=None, cat="market_industry", ctrl="external",
        claim=None, quote=None, spec="medium", basis="stated_in_page"):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "prediction": {"target_date": target, "target_date_text": tdt, "horizon_years_inferred": None,
                       "specificity": spec, "subject_control": ctrl, "category": cat, "prediction_type": "milestone",
                       "horizon": "none", "normalized_claim": claim or f"claim {pid}", "resolution_criteria": "crit"},
        "source": {"statement_date": said, "statement_date_basis": basis, "quote": quote or f"quote {pid}"},
        "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None},
    }


def write(run, pid, stage, deadline, **kw):
    if stage == "resolve":
        obj = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "resolve",
               "outcome": "occurred", "confidence": "high", "unresolvable_reason": None, "reasoning": "r",
               "sources": [{"where": "u", "what_it_shows": "w", "date": None}], "deadline": deadline}
    else:
        obj = {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "prior",
               "p": 0.5, "p_raw": 0.5, "clamped": False, "reference_class": "rc", "reasoning": "r",
               "deadline": deadline}
    obj.update(kw)
    fp = R.sidecar_path(run, stage, "ada", pid)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(obj))


def main() -> int:
    sha = P2.implied_table_sha256()
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        corpus = root / "predictions"
        (corpus / "ada").mkdir(parents=True)
        recs = [
            rec("dated", target="2022-12-31"),                              # a stated deadline
            rec("imp", claim="Level 4 trucks will be deployed commercially."),  # implied: 5 years -> 2026-03-01
            rec("impown", cat="company_business", ctrl="own"),               # implied: 1 year, own, no words
            rec("stale", quote="it will come soon"),                         # implied: 1 year -> 2022-03-01
            rec("trend", said="2019-01-15", claim="Margins will continue to go up.",
                cat="company_business", ctrl="own"),                          # a trend record, already resolved
            rec("pub", target="2023-06-30"),                                  # already public, exact date
            # The Buddy Media shape: dated by an upload years after the words, so a report
            # before the upload proves nothing about the speech. Reviewed, never excluded.
            rec("pubrev", said="2019-02-27", target="2022-02-27", basis="youtube_upload_date"),
            # A resolution under the release beside a prior priced on another prompt, and one beside
            # a prior priced on today's prompt (review 2026-09-30, item 3).
            rec("pairstale", target="2022-06-30", claim="Revenue will reach about 5 billion in 2022."),
            rec("pairok", target="2022-09-30"),
        ]
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        run = root / "predictions" / "_experiments" / "run-a"
        write(run, "dated", "resolve", "2022-12-31"); write(run, "dated", "prior", "2022-12-31")
        write(run, "imp", "resolve", "2026-03-01", outcome="not_occurred"); write(run, "imp", "prior", "2026-03-01", p=0.3)
        write(run, "stale", "resolve", "2023-03-01"); write(run, "stale", "prior", "2023-03-01")
        tflags = {"basis": "trend: trend over 5.0y since the statement", "trend": True}
        write(run, "trend", "resolve", "2024-02-01", funnel_flags=tflags)
        write(run, "trend", "prior", "2024-02-01", funnel_flags=tflags, p=0.6)
        write(run, "pub", "resolve", "2023-06-30", policy_release=REL,
              already_public={"date": "2021-02-20", "where": "https://example.com/deal", "what_it_shows": "agreed"})
        write(run, "pub", "prior", "2023-06-30")
        write(run, "pubrev", "resolve", "2022-02-27", policy_release=REL,
              already_public={"date": "2012-06-04", "where": "https://www.salesforce.com/news/press-releases/2012/06/04/",
                              "what_it_shows": "Salesforce signs a definitive agreement to acquire Buddy Media"})
        write(run, "pubrev", "prior", "2022-02-27")
        import resolve_predictions as RP  # noqa: E402
        today = {r["prediction_id"]: hashlib.sha256(R.build_prior_prompt(r, r["_deadline"]).encode()).hexdigest()
                 for r in RP.select(corpus, dt.date(2026, 9, 28), 60, trend=True)}
        write(run, "pairstale", "resolve", "2022-06-30", policy_release=REL)
        write(run, "pairstale", "prior", "2022-06-30", prompt_sha256="0" * 64)           # a legacy prior
        write(run, "pairok", "resolve", "2022-09-30", policy_release=REL)
        write(run, "pairok", "prior", "2022-09-30", prompt_sha256=today["pairok"], policy_release=REL)
        # A resolution under the release needs its prior priced on today's prompt, as a real prior run records.
        for pid, dl in (("pub", "2023-06-30"), ("pubrev", "2022-02-27")):
            write(run, pid, "prior", dl, prompt_sha256=today[pid])
        # An implied window sets no lower bound on when, so each implied record is under the
        # lead floor and the outcome-blind lead test decides it (VD-7 c; review 2026-09-30).
        for pid, dl in (("imp", "2026-03-01"), ("stale", "2022-03-01")):
            fp = R.sidecar_path(run, "lead_test", "ada", pid)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps({"prediction_id": pid, "leader_slug": "ada", "stage": "lead_test",
                                      "label": "world_forecast", "reason": "r", "policy_release": REL,
                                      "deadline": dl}))
        cfg_path = corpus / "scoring.json"
        base = {"as_of": "2026-09-28", "trend": True, "min_lead_days": 60, "predictions": ["predictions"],
                "runs": ["predictions/_experiments/run-a"], "index": "predictions/index.json",
                "out": "predictions/scores.json"}

        def score(**extra):
            cfg_path.write_text(json.dumps({**base, **extra}))
            out = corpus / "scores.json"
            if out.exists():
                out.unlink()
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg_path)],
                               capture_output=True, text=True)
            doc = json.loads(out.read_text()) if p.returncode == 0 else {}
            return p, doc

        print("policy_releases: a board never silently mixes resolver policies")
        p, _ = score()
        check("RELEASE: a sidecar under a release the config does not name is refused, naming it",
              p.returncode != 0 and REL in p.stderr and "policy_releases" in p.stderr, p.stderr[-400:])
        p, _ = score(policy_releases=["legacy", "resolution-1999-01-01"])
        check("RELEASE: a release id no code ever cut is refused in the config",
              p.returncode != 0 and "resolution-1999-01-01" in p.stderr, p.stderr[-400:])
        p, doc = score(policy_releases=["legacy", REL])
        check("RELEASE: named, the board is scored", p.returncode == 0, p.stderr[-600:])
        check("RELEASE: scores.json counts sidecars per stage and release",
              doc.get("policy_releases", {}).get("counts") == {"prior": {"legacy": 7, REL: 1},
                                                              "resolve": {"legacy": 4, REL: 4}},
              json.dumps(doc.get("policy_releases")))
        rows = {r["prediction_id"]: r for r in doc.get("predictions", [])}

        print("already public before the statement")
        pub = rows.get("pub", {})
        check("ALREADY PUBLIC: kept with its outcome and source, and not scored",
              pub.get("not_scored_because") == "already_public" and pub.get("outcome") == "occurred"
              and pub.get("already_public", {}).get("date") == "2021-02-20" and not pub.get("scored"), json.dumps(pub)[:400])
        check("ALREADY PUBLIC: counted by its reason", doc.get("corpus", {}).get("not_scored_because", {}).get("already_public") == 1,
              json.dumps(doc.get("corpus", {}).get("not_scored_because")))
        rv = rows.get("pubrev", {})
        check("REVIEW: against an upload date the report is kept and flagged for review, and the row still scores",
              rv.get("scored") is True and rv.get("already_public_review") is True
              and rv.get("already_public", {}).get("date") == "2012-06-04", json.dumps(rv)[:400])
        check("REVIEW: scores.json counts the rows sent to review",
              doc.get("corpus", {}).get("already_public_review") == ["pubrev"],
              json.dumps(doc.get("corpus", {}).get("already_public_review")))
        notes = D.scores_review_notes(doc)
        check("REVIEW: the deploy reports them, without refusing on them",
              notes and "pubrev" in notes[0] and not any("pubrev" in b for b in D.scores_blockers(doc)),
              str(notes) + str(D.scores_blockers(doc)))
        deploy = (ROOT / "scripts" / "deploy_predictions.sh").read_text()
        check("REVIEW: deploy_predictions.sh prints scores_review_notes", "D.scores_review_notes(" in deploy)

        print("a resolution under the release needs a prior that read today's prompt")
        ps = rows.get("pairstale", {})
        check("PAIRING: beside a prior priced on another prompt, the row is a stale sidecar, not a score",
              ps.get("not_scored_because") == "stale_sidecar:prior_prompt_changed" and not ps.get("scored"),
              json.dumps(ps)[:300])
        check("PAIRING: beside a prior priced on today's prompt, the row scores", rows.get("pairok", {}).get("scored"),
              json.dumps(rows.get("pairok"))[:300])
        st = [x for x in doc.get("corpus", {}).get("stale_sidecars", []) if x["prediction_id"] == "pairstale"]
        check("PAIRING: scores.json names both prompt hashes, and the deploy refuses",
              st == [{"prediction_id": "pairstale", "stage": "prior", "why": "prior_prompt_changed",
                      "sidecar_prompt_sha256": "0" * 64, "prompt_sha256": today["pairstale"]}]
              and any("stale" in b for b in D.scores_blockers(doc)), json.dumps(st))
        check("PAIRING: a legacy resolution beside a legacy prior is never checked, so today's board is unchanged",
              rows.get("dated", {}).get("scored") is True, json.dumps(rows.get("dated"))[:200])

        print("implied windows switched OFF: the records the funnel cannot date stay out")
        check("OFF: no implied row is past due, and no implied field is written",
              set(rows) == {"dated", "trend", "pub", "pubrev", "pairstale", "pairok"}
              and "implied" not in doc.get("rule", {})
              and not any("implied" in x["flags"] for x in doc.get("predictions", []))
              and all(x.get("why") == "prior_prompt_changed" for x in doc["corpus"].get("stale_sidecars", [])),
              f"{sorted(rows)} {doc.get('rule')}")
        trend_off = rows.get("trend", {}).get("points")

        print("implied windows switched ON")
        p, _ = score(policy_releases=["legacy", REL], implied_windows="0" * 64)
        check("SHA: a config naming another table is refused, naming both hashes",
              p.returncode != 0 and "0" * 12 in p.stderr and sha[:12] in p.stderr, p.stderr[-400:])
        p, doc = score(policy_releases=["legacy", REL], implied_windows=sha, lead_test=True)
        check("ON: exits 0", p.returncode == 0, p.stderr[-600:])
        rows = {r["prediction_id"]: r for r in doc.get("predictions", [])}
        imp = rows.get("imp", {})
        check("ON: a record with no deadline is judged over its implied window, and scores both ways",
              imp.get("deadline") == "2026-03-01" and imp.get("scored") and imp.get("outcome") == "not_occurred"
              and imp["flags"].get("implied", {}).get("row") == "claim: everything else", json.dumps(imp)[:500])
        check("ON: an implied record about the speaker's own company, with no words, is not a lead",
              rows.get("impown", {}).get("not_scored_because") == "not_eligible:lead_under_floor",
              json.dumps(rows.get("impown"))[:300])
        st = rows.get("stale", {})
        check("STALE: a sidecar judged over another window is a counted exclusion, not a stop",
              st.get("not_scored_because") == "stale_sidecar:deadline_changed" and not st.get("scored"),
              json.dumps(st)[:400])
        check("STALE: scores.json names it with both windows",
              [x for x in doc.get("corpus", {}).get("stale_sidecars", []) if x["prediction_id"] == "stale"] == [
                  {"prediction_id": "stale", "stage": "resolve", "sidecar_deadline": "2023-03-01", "deadline": "2022-03-01"},
                  {"prediction_id": "stale", "stage": "prior", "sidecar_deadline": "2023-03-01", "deadline": "2022-03-01"}],
              json.dumps(doc.get("corpus", {}).get("stale_sidecars")))
        check("STALE: the deploy refuses while any stale sidecar is counted",
              D.scores_blockers(doc) and "stale" in D.scores_blockers(doc)[0], str(D.scores_blockers(doc)))
        deploy = (ROOT / "scripts" / "deploy_predictions.sh").read_text()
        check("STALE: deploy_predictions.sh asks scores_blockers after the freshness check, and refuses on it",
              "D.scores_blockers(" in deploy and deploy.index("D.scores_blockers(") > deploy.index("D.scores_staleness(")
              and "REFUSING: scores.json" in deploy.split("D.scores_blockers(")[1][:400], "not wired")
        check("GRANDFATHER: the resolved trend record keeps its window and its points",
              rows.get("trend", {}).get("deadline") == "2024-02-01" and rows["trend"].get("points") == trend_off
              and trend_off is not None, json.dumps(rows.get("trend"))[:300])
        check("RULE: scores.json states the implied rule and the table it was judged by",
              doc.get("rule", {}).get("implied") == {"enabled": True, "table_sha256": sha},
              json.dumps(doc.get("rule", {}).get("implied")))
        check("SETTINGS: the key is part of the settings, so scores_staleness sees a change",
              doc.get("settings", {}).get("implied_windows") == sha)
        check("FRESH: scores.json is current against its config", D.scores_staleness(corpus / "scores.json", cfg_path) is None,
              str(D.scores_staleness(corpus / "scores.json", cfg_path)))
        (run / "resolutions" / "ada" / "stale.json").unlink()
        (run / "priors" / "ada" / "stale.json").unlink()
        p, doc = score(policy_releases=["legacy", REL], implied_windows=sha, lead_test=True)
        check("STALE: with the stale sidecars gone no window-stale row is left, and the deploy names only the "
              "prior-prompt one",
              p.returncode == 0 and [x["prediction_id"] for x in doc["corpus"].get("stale_sidecars", [])] == ["pairstale"]
              and all("pairstale" in b for b in D.scores_blockers(doc)),
              p.stderr[-300:])

        print("an already-public row the resolver could not settle")
        before = doc["corpus"]["unresolvable_by_eligibility"]
        fp = R.sidecar_path(run, "resolve", "ada", "pub")
        kept_pub = fp.read_text()
        fp.write_text(json.dumps(dict(json.loads(kept_pub), outcome="unresolvable", confidence="low",
                                      unresolvable_reason="no_public_evidence")))
        p, doc = score(policy_releases=["legacy", REL], implied_windows=sha, lead_test=True)
        pub = {r["prediction_id"]: r for r in doc.get("predictions", [])}.get("pub", {})
        check("SET ASIDE: an already-public row the resolver called unresolvable reads already_public, and "
              "unresolvable_by_eligibility does not count it",
              p.returncode == 0 and pub.get("not_scored_because") == "already_public"
              and doc["corpus"]["unresolvable_by_eligibility"] == before,
              p.stderr[-300:] + json.dumps(before) + json.dumps(doc.get("corpus", {}).get("unresolvable_by_eligibility")))
        fp.write_text(kept_pub)

        print("config validation")
        for k, v in (("implied_windows", "abc"), ("implied_windows", 1), ("policy_releases", "legacy"),
                     ("policy_releases", []), ("early_calls", False), ("lead_test", False),
                     ("early_calls", "true"), ("lead_test", 1)):
            cfg_path.write_text(json.dumps({**base, k: v}))
            try:
                D.load_scoring_config(cfg_path)
                check(f"CONFIG: {k}={v!r} is refused", False)
            except SystemExit as e:
                check(f"CONFIG: {k}={v!r} is refused", k in str(e), str(e))
        for k in ("early_calls", "lead_test"):
            cfg_path.write_text(json.dumps({**base, k: True}))
            try:
                D.load_scoring_config(cfg_path)
                check(f"CONFIG: {k}=True is accepted", True)
            except SystemExit as e:
                check(f"CONFIG: {k}=True is accepted", False, str(e))
        check("CONFIG: the new keys are optional keys", {"implied_windows", "policy_releases"} <= set(D.OPTIONAL_CONFIG_KEYS))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
