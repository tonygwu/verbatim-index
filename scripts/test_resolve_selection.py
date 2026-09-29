#!/usr/bin/env python3
"""Which past-due records a resolve or prior pass spends model calls on.

Design 3.5 and critique A1 of the rescue round-4 root-cause review
(`predictions/_experiments/rescue-round4-20260929/rootcause/` in the data repo):
  - phase2-scoring-20260915 spent resolution calls on records the scorer can
    never score, because only an explicit `--eligible-only` skipped them. The
    default is now eligible only, and `--include-ineligible` opts out. Every
    record left out is counted by its reason, never dropped silently;
  - a re-run of named records (the trend regate, the second look) had no way to
    pick them: `--redo` re-runs every selected record. `--ids FILE` restricts a
    stage to the ids in the file, and an id the stage would not run is REFUSED
    with the reason, never skipped.

Runs the real `resolve_predictions.main` in `--dry-run` on a fixture corpus, so
no model is called, and the real `ineligible_reason` the scorer also uses.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True, check=True).stdout.strip())
sys.path.insert(0, str(ROOT / "scripts"))
import resolve_predictions as RP  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, slug="ada", *, said="2019-01-01", target="2020-12-31", spec="high"):
    return {
        "accepted": True, "leader_slug": slug, "prediction_id": pid, "transcript_id": f"{slug}/t1",
        "prediction": {"target_date": target, "specificity": spec, "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": f"claim {pid}", "resolution_criteria": "crit"},
        "source": {"statement_date": said, "quote": f"quote {pid}"},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def corpus(tmp: pathlib.Path) -> pathlib.Path:
    pred = tmp / "predictions"
    rows = {
        "ada": [rec("e1"), rec("e2"),
                rec("lead", said="2020-12-01"),               # 30 days before its deadline
                rec("low", spec="low"),                        # specificity below the floor
                rec("back", said="2021-06-01"),                # deadline before the statement
                rec("nodate", said=None),                      # stated deadline, no statement date
                rec("future", target="2099-12-31")],           # not past due at all
        "bob": [rec("b1", slug="bob")],
    }
    for slug, rs in rows.items():
        (pred / slug).mkdir(parents=True)
        (pred / slug / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs))
    return pred


def dry(pred: pathlib.Path, *extra: str) -> tuple[int | str, str, str]:
    """(exit, stdout, stderr) of a dry run. A SystemExit's message is the exit."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = RP.main(["--stage", "resolve", "--predictions", str(pred), "--out",
                          str(pred.parent / "run"), "--as-of", "2026-09-28", "--dry-run", *extra])
    except SystemExit as exc:
        rc = str(exc)
    return rc, out.getvalue(), err.getvalue()


def main() -> int:
    print("ineligible_reason names the first funnel stage that drops a record")
    base = {"eligible": False, "deadline_before_statement": False, "specificity_ok": True,
            "lead_days": 400, "lead_ok": True}
    cases = {"deadline_before_statement": dict(base, deadline_before_statement=True, lead_days=-10, lead_ok=False),
             "specificity": dict(base, specificity_ok=False, lead_days=30, lead_ok=False),
             "undated": dict(base, lead_days=None, lead_ok=False),
             "lead_under_floor": dict(base, lead_days=30, lead_ok=False)}
    for want, flags in cases.items():
        got = getattr(RP, "ineligible_reason", lambda *a: "MISSING ineligible_reason")("x", flags)
        check(f"{want}", got == want, f"got {got!r} from {flags}")
    check("an eligible record has no reason",
          getattr(RP, "ineligible_reason", lambda *a: "MISSING")("x", dict(base, eligible=True)) is None)
    for label, flags in (("flags marked ineligible that name no reason", dict(base)),
                         ("flags missing a key the rule reads", {"eligible": False})):
        try:
            got = RP.ineligible_reason("x", flags)
        except SystemExit as exc:
            got = f"REFUSED {exc}"
        except Exception as exc:  # noqa: BLE001 - a crash is not a named refusal
            got = f"CRASH {type(exc).__name__}: {exc}"
        check(f"REFUSE: {label}, naming the prediction", got.startswith("REFUSED") and "x" in got, got)

    with tempfile.TemporaryDirectory() as t:
        pred = corpus(pathlib.Path(t))

        print("the default runs eligible records only, and counts what it left out")
        rc, _, err = dry(pred)
        check("DEFAULT: 3 selected, all eligible (e1, e2, b1)",
              rc == 0 and "selected=3 (3 eligible)" in err, f"rc={rc} {err.strip()}")
        check("DEFAULT: the ineligible ones are counted by reason, never dropped silently",
              "left out 4 ineligible" in err and all(k in err for k in
                                                     ("deadline_before_statement", "specificity",
                                                      "undated", "lead_under_floor")), err.strip())
        rc2, _, err2 = dry(pred, "--eligible-only")
        check("DEFAULT: --eligible-only still parses and means the default",
              rc2 == 0 and "selected=3 (3 eligible)" in err2, f"rc={rc2} {err2.strip()}")

        print("--include-ineligible opts out")
        rc, _, err = dry(pred, "--include-ineligible")
        check("OPT OUT: every past-due record is selected, 7 of them, 3 eligible",
              rc == 0 and "selected=7 (3 eligible)" in err and "left out" not in err, f"rc={rc} {err.strip()}")
        rc, _, err = dry(pred, "--include-ineligible", "--eligible-only")
        check("OPT OUT: asking for both is refused rather than one silently winning",
              isinstance(rc, str) and "--include-ineligible" in rc and "--eligible-only" in rc, str(rc))

        print("--ids restricts a stage to named records")
        ids = pred.parent / "ids.txt"
        ids.write_text("e2\nb1\n")
        rc, out, err = dry(pred, "--ids", str(ids))
        check("IDS: only the named records are selected, in select()'s order, so e2 is the first job",
              rc == 0 and "selected=2 (2 eligible)" in err and "claim e2" in out and "claim e1" not in out,
              f"rc={rc} {err.strip()}")
        check("IDS: the named ids are what the dry run would run, and nothing else",
              "to run=2" in err, err.strip())
        ids.write_text("e2\nlead\nfuture\nnope\n")
        rc, _, _ = dry(pred, "--ids", str(ids))
        check("IDS: an id the stage would not run is REFUSED, each with its reason",
              isinstance(rc, str) and "lead" in rc and "lead_under_floor" in rc and "--include-ineligible" in rc
              and "future" in rc and "nope" in rc and "past due" in rc, str(rc))
        ids.write_text("lead\n")
        rc, _, err = dry(pred, "--ids", str(ids), "--include-ineligible")
        check("IDS: an ineligible id runs when the opt-out is given",
              rc == 0 and "selected=1 (0 eligible)" in err, f"rc={rc} {err.strip()}")
        ids.write_text("b1\n")
        rc, _, _ = dry(pred, "--ids", str(ids), "--slug", "ada")
        check("IDS: an id outside --slug is refused, naming the slug",
              isinstance(rc, str) and "b1" in rc and "bob" in rc, str(rc))
        for label, text in (("an empty file", "\n"), ("a repeated id", "e1\ne1\n"),
                            ("a line that is not one id", "e1 e2\n")):
            ids.write_text(text)
            rc, _, _ = dry(pred, "--ids", str(ids))
            check(f"IDS: {label} is refused", isinstance(rc, str) and "--ids" in rc, str(rc))
        rc, _, _ = dry(pred, "--ids", str(pred.parent / "missing.txt"))
        check("IDS: a file that does not exist is refused", isinstance(rc, str) and "missing.txt" in rc, str(rc))
        done = pred.parent / "run" / "resolutions" / "ada" / "e2.json"
        done.parent.mkdir(parents=True)
        done.write_text(json.dumps({"prediction_id": "e2", "outcome": "occurred"}))
        ids.write_text("e2\n")
        rc, _, err = dry(pred, "--ids", str(ids))
        check("IDS: a named id the run already resolved is SAID to be skipped, and --redo named",
              rc == 0 and "to run=0" in err and "['e2'] already have a resolve result" in err and "--redo" in err,
              f"rc={rc} {err.strip()}")

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
