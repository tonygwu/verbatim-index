#!/usr/bin/env python3
"""The predictions page under the 2026-09-29 policies.

One person, dora, with one record in each new state. Her scores.json is written
by the REAL scorer, with every new scoring.json key on, so the page and the
scorer cannot drift apart in this test. What the page must show:
  - an implied window on the card's Target: "judged over N, to <deadline>
    (implied window)", scored or not yet due (VD-6);
  - an early call on the card and in the score's explanation: "Called early",
    before or past its deadline (VD-5);
  - a record already public before it was said: Not testable, with the source;
  - a withdrawn prediction: its own bucket, the reason and the evidence, due or not;
  - a record under the lead floor: scored when the outcome-blind check calls it
    a forecast, Not testable and named an announcement when it does not (VD-7);
  - a claim screened out of implied windows: No deadline, and why;
  - each person's score and rank at half and double the implied windows.
Buckets still add up to the total.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n          {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def load(name: str, alias: str | None = None):
    spec = importlib.util.spec_from_file_location(alias or f"{name}_mod", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = load("test_predictions_site", "tps_for_policy")
L, A, P2, R = load("predictions_lib"), load("aggregate_predictions"), load("phase2_resolvability"), load("resolution_lib")
REL = R.POLICY_RELEASE[0]
AS_OF = "2026-09-28"


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        pred = td / "predictions"
        (pred / "dora").mkdir(parents=True)
        q = lambda sid: f"we will ship the {sid.replace('-', ' ')} widget"  # noqa: E731
        spec = [  # sid, srec kwargs
            ("imp-scored", dict(target=None, horizon="none", upload="20210301", claim="Acme will acquire Widgetco.")),
            ("imp-open", dict(target=None, horizon="none", claim="Acme will acquire Gizmoco.")),
            ("screened", dict(target=None, horizon="none", claim="If regulators approve, the merger will close.")),
            ("early-now", dict(target="2027-06", target_text="by mid 2027")),
            ("early-late", dict(target="2026-06", target_text="by mid 2026")),
            ("pub", dict(target="2025-12", target_text="by the end of 2025")),
            ("wd", dict(target="2025-11", target_text="by November")),
            ("wd-open", dict(target="2030", target_text="by 2030")),
            ("lead-fc", dict(target="2025-03-20", target_text="this month")),
            ("lead-ann", dict(target="2025-03-25", target_text="this month")),
            ("stated", dict(target="2025-10", target_text="by October")),
        ]
        recs = {sid: T.srec(L, sid, q(sid), **kw) for sid, kw in spec}
        for sid, r in recs.items():
            (pred / "dora" / f"{sid}.jsonl").write_text(L.serialise_lines([r]))
            (pred / "dora" / f"{sid}.meta.json").write_text(json.dumps(
                {"extract": {"status": "ok", "candidates_written": 1, "harness": "fable"},
                 "verify": {"status": "ok", "accepted": 1}}))
        people = {"dora": {"name": "Dora M", "company": "Co", "role": "CEO", "sector": "AI"}}
        (pred / "index.json").write_text(json.dumps(A.build_index(pred, people, None), indent=1, sort_keys=True))
        T.write_year_summaries(pred)
        roster = td / "roster.json"
        roster.write_text(json.dumps({"roster": [{"slug": "dora", "name": "Dora M", "role": "CEO", "company": "Co",
                                                   "sector": "AI"}]}))
        pid = {sid: r["prediction_id"] for sid, r in recs.items()}
        # The funnel's own deadlines, with the implied table on, so every sidecar judges the funnel's window.
        rows = [json.loads(json.dumps(r)) for r in recs.values()]
        P2.attach_deadlines(rows, derive=True, implied=1.0)
        dl = {sid: next(x["_deadline"] for x in rows if x["prediction_id"] == pid[sid]) for sid in recs}
        half = [json.loads(json.dumps(recs["imp-scored"]))]
        P2.attach_deadlines(half, derive=True, implied=0.5)

        def side(run, sid, stage, deadline, **kw):
            base = {"prediction_id": pid[sid], "leader_slug": "dora", "transcript_id": recs[sid]["transcript_id"],
                    "stage": stage, "deadline": deadline.isoformat(), "harness": "astra" if stage != "prior" else "fable",
                    "telemetry": {"requested_model": "m", "served_model": "m", "canonical_model": "claude-fable-5-1",
                                  "telemetry_models": ["claude-fable-5-1"]}}
            if stage == "resolve":
                base.update(outcome="occurred", confidence="high", unresolvable_reason=None, reasoning=f"r {sid}",
                            sources=[{"where": "https://example.com/e", "what_it_shows": "it", "date": "2025-12-01"}])
            elif stage == "prior":
                base.update(p=0.6, p_raw=0.6, clamped=False, reference_class="rc", reasoning="r")
            elif stage == "early":
                base.update(outcome="occurred", not_occurred_basis=None, early_called=True, confidence="high",
                            sources=[{"where": "https://example.com/early", "what_it_shows": "done", "date": "2026-05-01"}],
                            searched=["a", "b", "c"], already_public=None, reasoning=f"early {sid}", as_of="2026-09-01",
                            policy_release=REL)
            else:
                base.update(label="world_forecast", reason="r", policy_release=REL)
            base.update(kw)
            fp = R.sidecar_path(run, stage, "dora", pid[sid])
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps(base))

        board = pred / "_experiments" / "board"
        for sid in ("imp-scored", "pub", "wd", "lead-fc", "lead-ann", "stated"):
            side(board, sid, "resolve", dl[sid])
            side(board, sid, "prior", dl[sid])
        side(board, "pub", "resolve", dl["pub"], policy_release=REL, already_public={
            "date": "2025-02-20", "where": "https://example.com/already", "what_it_shows": "the launch date was set"})
        # A withdrawn prediction the resolver could not settle is Withdrawn, not Couldn't check:
        # the scorer's eligible-unresolvable split and the page's column must agree on it.
        side(board, "wd", "resolve", dl["wd"], outcome="unresolvable", unresolvable_reason="no_public_evidence",
             sources=[])
        for sid in ("early-now", "early-late"):
            side(board, sid, "early", dl[sid])
            side(board, sid, "prior", dl[sid])
        side(board, "lead-fc", "lead_test", dl["lead-fc"])
        side(board, "lead-ann", "lead_test", dl["lead-ann"], label="own_plan_announcement")
        hrun = pred / "_experiments" / "half"
        side(hrun, "imp-scored", "resolve", half[0]["_deadline"], outcome="not_occurred", implied_scale=0.5)
        side(hrun, "imp-scored", "prior", half[0]["_deadline"], implied_scale=0.5)
        (pred / "withdrawn_predictions.json").write_text(json.dumps({"schema_version": 1, "note": "n", "withdrawn": {
            pid[sid]: {"reason": "not_a_forecast", "detail": f"{sid} repeated the previous day's news.",
                       "evidence": ["https://example.com/news"], "transcript_id": recs[sid]["transcript_id"],
                       "decided_by": "operator", "decided_at_utc": "2026-09-30T07:10:44Z"} for sid in ("wd", "wd-open")}}))
        (pred / "scoring.json").write_text(json.dumps({
            "as_of": AS_OF, "trend": True, "min_lead_days": 60, "predictions": ["predictions"],
            "runs": ["predictions/_experiments/board"], "index": "predictions/index.json", "out": "predictions/scores.json",
            "implied_windows": P2.implied_table_sha256(), "policy_releases": ["legacy", REL], "early_calls": True,
            "lead_test": True, "withdrawn": "predictions/withdrawn_predictions.json",
            "implied_sensitivity": {"half": ["predictions/_experiments/half"], "double": []}}))
        p = subprocess.run([sys.executable, str(REPO / "scripts" / "score_predictions.py"), "--config",
                            str(pred / "scoring.json")], capture_output=True, text=True)
        check("SCORER: scores the fixture with every new key on", p.returncode == 0, p.stderr[-800:])
        if p.returncode:
            print(f"\n{len(FAILED)} failed")
            return 1
        out = td / "site" / "index.html"
        p = subprocess.run([sys.executable, str(REPO / "scripts" / "build_predictions_site.py"), "--data-date", "2026-09-30",
                            "--index", str(pred / "index.json"), "--predictions", str(pred), "--roster", str(roster),
                            "--membership", str(T.mem(roster)), "--out", str(out), "--scores", str(pred / "scores.json")],
                           capture_output=True, text=True, cwd=REPO)
        check("PAGE: builds", p.returncode == 0, (p.stdout + p.stderr)[-900:])
        if p.returncode:
            print(f"\n{len(FAILED)} failed")
            return 1
        page = out.read_text()
        if os.environ.get("VI_KEEP_POLICY_SITE"):
            # For driving the rendered page in a browser: check_predictions_site_ui.py --cards-only.
            shutil.copytree(out.parent, Path(os.environ["VI_KEEP_POLICY_SITE"]), dirs_exist_ok=True)
        pub = {r["transcript_id"].split("/")[1]: r for r in T.records(out)["dora"]}
        st = {sid: r["state"] for sid, r in pub.items()}
        row = T.embedded(page, "DATA")[0]
        want = {"imp-scored": "scored", "imp-open": "not_due", "screened": "no_deadline", "early-now": "scored",
                "early-late": "scored", "pub": "not_testable", "wd": "withdrawn", "wd-open": "withdrawn",
                "lead-fc": "scored", "lead-ann": "not_testable", "stated": "scored"}
        got = {sid: st[sid]["state"] for sid in want}
        check("STATES: each record carries the state its row, its window and the manifest give", got == want,
              json.dumps({k: (got[k], v) for k, v in want.items() if got[k] != v}))
        check("BUCKETS: the Predictions column counts those states, withdrawn in its own bucket, and adds up",
              row.get("buckets") == {"scored": 5, "not_due": 1, "no_deadline": 1, "not_testable": 2, "withdrawn": 2}
              and sum(row["buckets"].values()) == row["accepted"] == 11, json.dumps(row.get("buckets")))

        print("implied windows")
        check("TARGET: a scored implied record reads 'judged over 3 years, to 2024-03-01 (implied window)'",
              pub["imp-scored"]["target"].endswith("judged over 3 years, to 2024-03-01 (implied window)"),
              pub["imp-scored"]["target"])
        check("TARGET: a not-yet-due implied record shows its window too",
              pub["imp-open"]["target"].endswith(f"judged over 3 years, to {dl['imp-open']} (implied window)"),
              pub["imp-open"]["target"])
        check("TARGET: a record with a stated date shows no implied window", "implied" not in pub["stated"]["target"],
              pub["stated"]["target"])
        check("SCREEN: a conditional claim says why it has no window",
              "conditional" in st["screened"]["line"] and "window" in st["screened"]["line"], st["screened"]["line"])

        print("early calls")
        check("CARD: an early call before its deadline says so, and that it is checked again at the deadline",
              "Called early" in st["early-now"]["line"] and "2027-06-30" in st["early-now"]["line"]
              and "checked again" in st["early-now"]["line"], st["early-now"]["line"])
        check("CARD: the record carries the early_called flag for the card's badge",
              (pub["early-now"].get("outcome") or {}).get("early_called") is True
              and "called early" in page.lower(), json.dumps(pub["early-now"].get("outcome"))[:300])
        check("CARD: an early call past its deadline says the fresh check has not run yet",
              "Called early" in st["early-late"]["line"] and "fresh check" in st["early-late"]["line"],
              st["early-late"]["line"])
        check("EXPLANATION: the score's explanation says how many scores rest on early calls",
              "2 scored predictions were called early" in page, "not found")

        print("already public, withdrawn, lead test")
        check("CARD: already public before it was said, with the source and its date",
              st["pub"]["reason"] == "already_public" and "already public" in st["pub"]["line"]
              and "2025-02-20" in st["pub"]["line"] and "https://example.com/already" in json.dumps(pub["pub"]),
              st["pub"]["line"])
        check("CARD: a withdrawn prediction gives the reason and the detail, with the evidence on the record",
              "Withdrawn" in st["wd"]["line"] and "not a forecast" in st["wd"]["line"]
              and pub["wd"].get("withdrawn", {}).get("evidence") == ["https://example.com/news"], st["wd"]["line"])
        check("CARD: a withdrawn prediction not yet due is withdrawn too", st["wd-open"]["state"] == "withdrawn")
        check("CARD: under the floor, an announcement says so", st["lead-ann"]["reason"] == "lead_under_floor"
              and "announcement" in st["lead-ann"]["line"], st["lead-ann"]["line"])

        print("sensitivity")
        sens = row.get("sens") or {}
        check("ROW: the person's score and rank at half and double the implied windows ride on the row",
              set(sens) == {"half", "double"} and sens["half"]["mean_points"] is not None
              and sens["half"]["mean_points"] != row["score"], json.dumps(sens))
        check("ROW: the score cell's hover carries them", "at half the implied windows" in page)

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
