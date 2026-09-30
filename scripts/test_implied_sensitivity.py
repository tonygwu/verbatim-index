#!/usr/bin/env python3
"""Each person's score at half and double the implied windows (VD-6 (a); critique 1 point 1).

The implied-window length changes expected points, because the prior assessor
is not calibrated bin by bin, so the choice of window can move people. The
operator's decision is to publish the sensitivity: each person's score and rank
with every implied window halved and doubled, beside the board's own.

Halving or doubling a window changes the question, so neither the board's
resolutions nor its priors answer it: the sensitivity reads its OWN runs,
written by `resolve_predictions.py --implied-windows <sha> --implied-scale
half|double`, named in scoring.json under `implied_sensitivity`. Every other
row keeps the board's result. A sidecar missing at a scale is named, never
filled from another scale; a sidecar of another scale in a scale's run is
refused; and the runs are fingerprinted like the board's.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
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
import resolve_predictions as RP  # noqa: E402

FAILED = []
SHA = P2.implied_table_sha256()


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, slug, *, said="2021-03-01", target=None, cat="market_industry"):
    return {"accepted": True, "leader_slug": slug, "prediction_id": pid, "transcript_id": f"{slug}/t1",
            "prediction": {"target_date": target, "target_date_text": None, "horizon_years_inferred": None,
                           "specificity": "high", "subject_control": "external", "category": cat,
                           "prediction_type": "milestone", "horizon": "none", "normalized_claim": f"claim {pid}",
                           "resolution_criteria": "crit"},
            "source": {"statement_date": said, "quote": f"quote {pid}"},
            "confidence": {"probability": None}, "consensus": {"status": "no_match", "exact_match": None}}


def write(run, slug, pid, stage, deadline, scale=None, **kw):
    obj = {"prediction_id": pid, "leader_slug": slug, "transcript_id": f"{slug}/t1", "stage": stage, "deadline": deadline}
    if stage == "resolve":
        obj.update(outcome="occurred", confidence="high", unresolvable_reason=None, reasoning="r",
                   sources=[{"where": "u", "what_it_shows": "w", "date": None}])
    else:
        obj.update(p=0.5, p_raw=0.5, clamped=False, reference_class="rc", reasoning="r")
    if scale is not None:
        obj["implied_scale"] = scale
    obj.update(kw)
    fp = R.sidecar_path(run, stage, slug, pid)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(obj))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        corpus = root / "predictions"
        # Two people, each with two stated predictions (the board) and one implied
        # one (market_industry: 5 years from 2021-03-01, so 2026-03-01; half is 2023-08-31,
        # double 2031-03-01 and not due at the as-of).
        for slug in ("ada", "bob", "cat"):
            (corpus / slug).mkdir(parents=True)
            (corpus / slug / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
                rec(f"{slug}-s1", slug, target="2022-12-31"), rec(f"{slug}-s2", slug, target="2023-12-31"),
                rec(f"{slug}-i", slug))))
        (corpus / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada"},
                                                                    {"slug": "bob", "name": "Bob"},
                                                                    {"slug": "cat", "name": "Cat"}]}))
        run = corpus / "_experiments" / "board"
        half = corpus / "_experiments" / "half"
        dbl = corpus / "_experiments" / "double"
        for slug in ("ada", "bob", "cat"):
            for pid, dl in ((f"{slug}-s1", "2022-12-31"), (f"{slug}-s2", "2023-12-31"), (f"{slug}-i", "2026-03-01")):
                write(run, slug, pid, "resolve", dl)
                write(run, slug, pid, "prior", dl)
        half_dl = (dt.date(2021, 3, 1) + dt.timedelta(days=round(2.5 * 365.25))).isoformat()
        # At half the window, ada's implied claim had not yet happened: a miss.
        write(half, "ada", "ada-i", "resolve", half_dl, 0.5, outcome="not_occurred")
        write(half, "ada", "ada-i", "prior", half_dl, 0.5, p=0.3)
        write(half, "bob", "bob-i", "resolve", half_dl, 0.5)     # bob has no prior at half: named, not filled
        write(half, "cat", "cat-i", "prior", half_dl, 0.5)       # cat has no resolution at half: named, not filled
        cfg_path = corpus / "scoring.json"
        base = {"as_of": "2026-09-28", "trend": False, "min_lead_days": 60, "predictions": ["predictions"],
                "runs": ["predictions/_experiments/board"], "index": "predictions/index.json",
                "out": "predictions/scores.json", "implied_windows": SHA}
        sens = {"half": ["predictions/_experiments/half"], "double": ["predictions/_experiments/double"]}
        dbl.mkdir(parents=True)

        def score(**extra):
            cfg_path.write_text(json.dumps({**base, **extra}))
            out = corpus / "scores.json"
            if out.exists():
                out.unlink()
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"), "--config", str(cfg_path)],
                               capture_output=True, text=True)
            return p, (json.loads(out.read_text()) if p.returncode == 0 else {})

        p, doc = score()
        check("OFF: without the key there is no sensitivity block", p.returncode == 0 and "implied_sensitivity" not in doc,
              p.stderr[-300:])
        p, doc = score(implied_sensitivity=sens)
        check("ON: exits 0", p.returncode == 0, p.stderr[-500:])
        s = doc.get("implied_sensitivity", {})
        h, d2 = s.get("half", {}), s.get("double", {})
        check("HALF: ada's implied claim is judged at half its window, from the half run, and moves her score",
              h.get("leaders", {}).get("ada", {}).get("mean_points") is not None
              and h["leaders"]["ada"]["mean_points"] < doc["leaders"][0]["mean_points"]
              and h["leaders"]["ada"]["n_scored"] == 3, json.dumps(h.get("leaders")))
        check("HALF: bob's missing prior at half is named, never filled from the board",
              h.get("missing_prior") == ["bob-i"] and h["leaders"]["bob"]["n_scored"] == 2
              and h["leaders"]["bob"]["implied_missing"] == 1, json.dumps(h)[:500])
        check("HALF: cat's missing resolution at half is named, never borrowed from the board",
              h.get("missing_resolution") == ["cat-i"] and h["leaders"]["cat"]["n_scored"] == 2
              and h["leaders"]["cat"]["implied_missing"] == 1, json.dumps(h)[:500])
        check("DOUBLE: at double, the implied claims are not yet due, so each person keeps the stated two",
              d2.get("implied_past_due") == 0 and d2.get("leaders", {}).get("ada", {}).get("n_scored") == 2,
              json.dumps(d2)[:400])
        board = {l["slug"]: l for l in doc["leaders"]}
        check("BOARD: the board's own figures are unchanged by the sensitivity",
              board["ada"]["n_scored"] == 3 and board["bob"]["n_scored"] == 3 and board["cat"]["n_scored"] == 3,
              json.dumps(doc["leaders"]))
        # bob has 2 scored at half (his implied prior is missing), under the rank floor of 3.
        check("RANKS: each scale ranks the people beside the board's own rank, and one below the floor at a "
              "scale is unranked there",
              set(s.get("board_rank", {})) == {"ada", "bob", "cat"} and h["leaders"]["ada"]["rank"] == 1
              and h["leaders"]["bob"]["rank"] is None and h["leaders"]["bob"]["ranked"] is False,
              json.dumps(s.get("board_rank")) + json.dumps(h.get("leaders")))
        check("FRESH: scores.json is current", D.scores_staleness(corpus / "scores.json", cfg_path) is None,
              str(D.scores_staleness(corpus / "scores.json", cfg_path)))
        write(half, "ada", "ada-i", "prior", half_dl, 0.5, p=0.35)
        why = D.scores_staleness(corpus / "scores.json", cfg_path)
        check("FRESH: a sidecar in a sensitivity run is fingerprinted", why is not None and "input changed" in why, str(why))

        print("refused")
        write(half, "bob", "bob-i", "prior", half_dl)          # no scale tag: written for the board
        p, _ = score(implied_sensitivity=sens)
        check("REFUSE: a sidecar in the half run that was not written at half",
              p.returncode != 0 and "bob-i" in p.stderr and "0.5" in p.stderr, p.stderr[-400:])
        write(half, "bob", "bob-i", "prior", half_dl, 0.5)
        p, _ = score(implied_sensitivity={"half": ["predictions/_experiments/board"], "double": []})
        check("REFUSE: a board run named as a sensitivity run", p.returncode != 0 and "board" in p.stderr, p.stderr[-300:])
        cfg_path.write_text(json.dumps({**{k: v for k, v in base.items() if k != "implied_windows"},
                                        "implied_sensitivity": sens}))
        try:
            D.load_scoring_config(cfg_path)
            check("CONFIG: implied_sensitivity without implied_windows is refused", False)
        except SystemExit as e:
            check("CONFIG: implied_sensitivity without implied_windows is refused", "implied_windows" in str(e), str(e))
        for bad in ({"half": "x"}, {"third": []}, []):
            cfg_path.write_text(json.dumps({**base, "implied_sensitivity": bad}))
            try:
                D.load_scoring_config(cfg_path)
                check(f"CONFIG: implied_sensitivity {bad!r} is refused", False)
            except SystemExit as e:
                check(f"CONFIG: implied_sensitivity {bad!r} is refused", "implied_sensitivity" in str(e), str(e))

        print("the stage writes a sensitivity run")
        cfg_path.write_text(json.dumps(base))   # the stage reads the scoring config beside --predictions
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = RP.main(["--stage", "resolve", "--predictions", str(corpus), "--out", str(root / "dry"),
                          "--as-of", "2026-09-28", "--implied-windows", SHA, "--implied-scale", "half", "--dry-run"])
        sel = [l for l in err.getvalue().splitlines() if l.startswith("stage=resolve")]
        check("STAGE: --implied-scale half selects only the implied records, at half their windows",
              rc == 0 and sel and "to run=3" in sel[0] and "3 implied record(s) at 0.5x" in err.getvalue(),
              err.getvalue()[-500:])
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                RP.main(["--stage", "resolve", "--predictions", str(corpus), "--out", str(root / "dry"),
                         "--as-of", "2026-09-28", "--implied-scale", "half", "--dry-run"])
            check("STAGE: --implied-scale without --implied-windows is refused", False)
        except SystemExit as e:
            check("STAGE: --implied-scale without --implied-windows is refused", "--implied-windows" in str(e), str(e))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
