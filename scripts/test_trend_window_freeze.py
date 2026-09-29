#!/usr/bin/env python3
"""A trend record's window freezes at its first resolution (operator decision, 2026-09-27).

A trend record is an undated directional claim, basis "trend". Its window runs
from the statement date to the scoring as-of date, so before this rule every
as-of move reopened every trend record, and scoring it correctly would have
needed a fresh resolution and a fresh prior each time. Now the window end of a
RESOLVED trend record is the `deadline` written in its resolution sidecar, and
a later as-of does not move it. An unresolved trend record still runs to the
current as-of. A dated record is untouched.

This runs the real scorer (`score_predictions.main`) and the real selection
(`resolve_predictions.select` and its `--dry-run`) on a fixture corpus, never
source inspection. No model is called.
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
import resolve_predictions as RP  # noqa: E402
import score_predictions as SP  # noqa: E402

FAILED = []
FROZEN = "2026-09-14"


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        FAILED.append(label)


def rec(pid, *, target=None, claim="revenue will continue to grow", said="2019-01-01"):
    return {
        "accepted": True, "leader_slug": "ada", "prediction_id": pid, "transcript_id": "ada/t1",
        "prediction": {"target_date": target, "specificity": "high", "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": None,
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": claim, "resolution_criteria": "crit"},
        "source": {"statement_date": said, "quote": "q"},
        "confidence": {"probability": None},
        "consensus": {"status": "no_match", "exact_match": None},
    }


def resolution(pid, deadline, outcome="occurred"):
    return {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "resolve",
            "deadline": deadline, "as_of": deadline if deadline else FROZEN, "outcome": outcome,
            "confidence": "high", "sources": ["https://example.com"], "unresolvable_reason": None,
            "reasoning": "r"}


def prior(pid, deadline, p=0.6):
    return {"prediction_id": pid, "leader_slug": "ada", "transcript_id": "ada/t1", "stage": "prior",
            "deadline": deadline, "p": p, "p_raw": p, "clamped": False, "reference_class": "rc",
            "reasoning": "r"}


def corpus(tmp: pathlib.Path, resolutions: dict, priors: dict) -> pathlib.Path:
    pred = tmp / "predictions"
    (pred / "ada").mkdir(parents=True)
    rows = [rec("trend-resolved"), rec("trend-open"),
            rec("dated", target="2020-12-31", claim="it will ship")]
    (pred / "ada" / "t1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (pred / "index.json").write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada"}]}))
    run = pred / "_experiments" / "run"
    for stage, objs in (("resolutions", resolutions), ("priors", priors)):
        (run / stage / "ada").mkdir(parents=True)
        for pid, obj in objs.items():
            (run / stage / "ada" / f"{pid}.json").write_text(json.dumps(obj))
    return pred


def score(pred: pathlib.Path, as_of: str) -> dict:
    out = pred.parent / f"scores-{as_of}.json"
    with contextlib.redirect_stdout(io.StringIO()):
        SP.main(["--predictions", str(pred), "--run", str(pred / "_experiments" / "run"),
                 "--index", str(pred / "index.json"), "--as-of", as_of, "--trend", "--out", str(out)])
    return {r["prediction_id"]: r for r in json.loads(out.read_text())["predictions"]}


def refusal(pred: pathlib.Path, as_of: str) -> str | None:
    try:
        score(pred, as_of)
    except SystemExit as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - a crash is not a named refusal
        return f"CRASH {type(exc).__name__}: {exc}"
    return None


def good_sidecars():
    return ({"trend-resolved": resolution("trend-resolved", FROZEN),
             "dated": resolution("dated", "2020-12-31", "not_occurred")},
            {"trend-resolved": prior("trend-resolved", FROZEN),
             "dated": prior("dated", "2020-12-31", 0.3)})


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        pred = corpus(pathlib.Path(t), *good_sidecars())
        at_frozen, later, much_later = score(pred, FROZEN), score(pred, "2026-09-28"), score(pred, "2027-06-30")

        print("a resolved trend record keeps the window its resolution judged")
        for label, s in (("as-of 2026-09-28", later), ("as-of 2027-06-30", much_later)):
            got = s["trend-resolved"]["deadline"]
            check(f"{label}: window end stays {FROZEN}", got == FROZEN, f"got {got}")
        check("its points do not change as the as-of moves",
              at_frozen["trend-resolved"]["points"] == later["trend-resolved"]["points"]
              == much_later["trend-resolved"]["points"] and later["trend-resolved"]["scored"],
              f"{[s['trend-resolved']['points'] for s in (at_frozen, later, much_later)]}")
        check("its basis text says the window is frozen, still starting 'trend'",
              later["trend-resolved"]["flags"]["basis"].startswith("trend")
              and "frozen" in later["trend-resolved"]["flags"]["basis"],
              later["trend-resolved"]["flags"]["basis"])

        print("an unresolved trend record still runs to the current as-of")
        for as_of, s in ((FROZEN, at_frozen), ("2026-09-28", later), ("2027-06-30", much_later)):
            got = s["trend-open"]["deadline"]
            check(f"as-of {as_of}: window end is the as-of", got == as_of, f"got {got}")

        print("a dated record is unaffected")
        check("its deadline is its target date at every as-of",
              {s["dated"]["deadline"] for s in (at_frozen, later, much_later)} == {"2020-12-31"})
        check("its points do not change",
              len({s["dated"]["points"] for s in (at_frozen, later, much_later)}) == 1
              and later["dated"]["scored"])

        print("select() hands every stage the frozen window, so nothing re-runs over a grown one")
        res = {"trend-resolved": resolution("trend-resolved", FROZEN)}
        try:
            rows = {r["prediction_id"]: r for r in
                    RP.select([pred], dt.date(2026, 9, 28), 60, trend=True, resolutions=res)}
            got = {k: r["_deadline"].isoformat() for k, r in rows.items()}
        except TypeError as exc:
            got = f"TypeError: {exc}"
        check("select(resolutions=...) keeps the resolved trend window and moves the open one",
              got == {"trend-resolved": FROZEN, "trend-open": "2026-09-28", "dated": "2020-12-31"},
              str(got))
        # The prior stage for a resolved-but-unpriced trend record must price the
        # window that was resolved, not the as-of of the day the prior runs.
        # --dry-run prints the first job's prompt, so leave that record the only job.
        priors_dir = pred / "_experiments" / "run" / "priors" / "ada"
        (priors_dir / "trend-resolved.json").unlink()
        (priors_dir / "trend-open.json").write_text(json.dumps(prior("trend-open", "2026-09-28")))
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            RP.main(["--stage", "prior", "--predictions", str(pred), "--out",
                     str(pred / "_experiments" / "run"), "--as-of", "2026-09-28", "--trend",
                     "--slug", "ada", "--dry-run"])
        prompt = buf.getvalue()
        check("the prior stage's prompt for it states the frozen window",
              "to run=1" in err.getvalue() and "trend-resolved" in prompt
              and FROZEN in prompt and "2026-09-28" not in prompt,
              f"stderr: {err.getvalue().strip()}")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            RP.main(["--stage", "resolve", "--predictions", str(pred), "--out",
                     str(pred / "_experiments" / "run"), "--as-of", "2026-09-28", "--trend",
                     "--slug", "ada", "--dry-run"])
        check("the resolve stage does not pick the resolved trend record again",
              "already done=2  to run=1" in err.getvalue(), err.getvalue().strip())

    print("a trend resolution with no usable deadline is refused, never read as the as-of")
    for bad in (None, "", "(no closing date this pipeline could read)"):
        with tempfile.TemporaryDirectory() as t:
            r, p = good_sidecars()
            r["trend-resolved"]["deadline"] = bad
            if bad is None:
                del r["trend-resolved"]["deadline"]
            p.pop("trend-resolved")
            why = refusal(corpus(pathlib.Path(t), r, p), "2026-09-28")
            check(f"deadline {bad!r}: refused, naming the prediction",
                  bool(why) and "trend-resolved" in why and not why.startswith("CRASH"), str(why))

    print("a prior priced over a different window than its resolution judged is refused")
    with tempfile.TemporaryDirectory() as t:
        r, p = good_sidecars()
        p["trend-resolved"]["deadline"] = "2026-09-20"
        why = refusal(corpus(pathlib.Path(t), r, p), "2026-09-28")
        check("refused, naming the prediction and both windows",
              bool(why) and "trend-resolved" in why and "2026-09-20" in why and FROZEN in why
              and not why.startswith("CRASH"), str(why))

    older_runs()
    replaced_windows()

    print(f"\n{'FAILED ' + str(len(FAILED)) if FAILED else 'all passed'}")
    return 1 if FAILED else 0


# ---------------------------------------------------------------------------
# The freeze holds across RUNS (both reviews of the round-4 funnel change)
# ---------------------------------------------------------------------------
#
# The first version froze a window only from the resolutions in the run a stage
# writes to (--out). `--ids` re-runs named records into a NEW run, so a trend
# record resolved in an older run was judged there up to the new as-of: on
# production, b489520cc1561d1e was resolved to 2026-09-14 in
# phase2-scoring-20260915, and a dry run with --ids into a fresh run at as-of
# 2026-09-29 built "Deadline: 2026-09-29 -- THIS IS A TREND WINDOW". The scorer
# then took both new sidecars through a replacement manifest and scored the grown
# window, or, at an as-of before it, dropped the record without a word.

NEW_AS_OF = "2026-09-29"


def scoring_config(pred: pathlib.Path, runs: list[str]) -> pathlib.Path:
    cfg = pred / "scoring.json"
    cfg.write_text(json.dumps({"as_of": "2026-09-28", "trend": True, "min_lead_days": 60,
                               "predictions": ["predictions"], "runs": runs,
                               "index": "predictions/index.json", "out": "predictions/scores.json"}))
    return cfg


def dry(pred: pathlib.Path, stage: str, *extra: str) -> tuple[str, str]:
    """(prompt, stderr) of a --dry-run into a NEW run; a refusal comes back as the stderr."""
    buf, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            RP.main(["--stage", stage, "--predictions", str(pred), "--out", str(pred / "_experiments" / "new"),
                     "--as-of", NEW_AS_OF, "--trend", "--dry-run", *extra])
    except SystemExit as exc:
        return "", f"REFUSED {exc}"
    except Exception as exc:  # noqa: BLE001 - a crash is not a named refusal
        return "", f"CRASH {type(exc).__name__}: {exc}"
    return buf.getvalue(), err.getvalue()


def deadline_line(prompt: str) -> str:
    return next((ln for ln in prompt.splitlines() if ln.startswith("Deadline:")), "(no Deadline line)")


def older_runs() -> None:
    print("--ids into a NEW run keeps the window of a resolution in an OLDER run")
    with tempfile.TemporaryDirectory() as t:
        pred = corpus(pathlib.Path(t), *good_sidecars())
        ids = pathlib.Path(t) / "ids.txt"
        ids.write_text("trend-resolved\n")
        scoring_config(pred, ["predictions/_experiments/run"])
        for stage in ("resolve", "prior"):
            prompt, err = dry(pred, stage, "--ids", str(ids))
            line = deadline_line(prompt)
            check(f"{stage}: the prompt judges the window its first resolution froze, {FROZEN}, "
                  f"not the new as-of", FROZEN in line and NEW_AS_OF not in line and "to run=1" in err,
                  f"{line} / {err.strip()[-300:]}")
        prompt, err = dry(pred, "resolve", "--ids", str(ids), "--scoring-config", str(pred / "nowhere.json"))
        check("an explicit --scoring-config that does not exist is refused, naming it",
              err.startswith("REFUSED") and "nowhere.json" in err, err[-300:])
        # load_scoring_config reads paths relative to the config's grandparent, so a
        # config at <tmp>/cfg/scoring.json names the same runs as the default one.
        (pred / "scoring.json").rename(pathlib.Path(t) / "cfg.json")
        (pathlib.Path(t) / "cfg").mkdir()
        (pathlib.Path(t) / "cfg.json").rename(pathlib.Path(t) / "cfg" / "scoring.json")
        prompt, err = dry(pred, "resolve", "--ids", str(ids), "--scoring-config",
                          str(pathlib.Path(t) / "cfg" / "scoring.json"))
        check("an explicit --scoring-config is read in place of the default",
              FROZEN in deadline_line(prompt) and NEW_AS_OF not in deadline_line(prompt),
              f"{deadline_line(prompt)} / {err.strip()[-300:]}")
        scoring_config(pred, ["predictions/_experiments/run", "predictions/_experiments/gone"])
        prompt, err = dry(pred, "resolve", "--ids", str(ids))
        check("a run the scoring config names that does not exist is refused, naming it",
              err.startswith("REFUSED") and "gone" in err, err[-300:])

        print("two runs that disagree about a trend record's window are refused, never picked between")
        two = pred / "_experiments" / "run2"
        (two / "resolutions" / "ada").mkdir(parents=True)
        (two / "resolutions" / "ada" / "trend-resolved.json").write_text(
            json.dumps(resolution("trend-resolved", "2026-09-20")))
        scoring_config(pred, ["predictions/_experiments/run", "predictions/_experiments/run2"])
        prompt, err = dry(pred, "resolve", "--ids", str(ids))
        check("refused, naming the prediction, both windows and both runs",
              err.startswith("REFUSED") and "trend-resolved" in err and FROZEN in err and "2026-09-20" in err
              and "run2" in err, err[-400:])
        # A DATED record resolved over two windows is not frozen by either; its
        # deadline comes from its own words. The statement-date override path writes
        # exactly that (16d47e6dbb109466 in production), so it must not refuse.
        (two / "resolutions" / "ada" / "trend-resolved.json").unlink()
        (two / "resolutions" / "ada" / "dated.json").write_text(json.dumps(resolution("dated", "2013-09-30")))
        ids.write_text("dated\n")
        prompt, err = dry(pred, "resolve", "--ids", str(ids))
        check("a dated record resolved over two different deadlines is not refused, and keeps its own",
              "2020-12-31" in deadline_line(prompt) and "to run=1" in err, f"{deadline_line(prompt)} / {err[-300:]}")


def score_runs(pred: pathlib.Path, as_of: str, runs: list[str], *extra: str) -> tuple[str | None, dict]:
    """(refusal or None, scores.json) from the real scorer over several runs."""
    out = pred.parent / f"scores-{as_of}-{len(FAILED)}-{len(extra)}.json"
    argv = ["--predictions", str(pred), "--index", str(pred / "index.json"), "--as-of", as_of, "--trend",
            "--out", str(out), *extra]
    for r in runs:
        argv += ["--run", str(pred / "_experiments" / r)]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            SP.main(argv)
    except SystemExit as exc:
        return str(exc), {}
    except Exception as exc:  # noqa: BLE001 - a crash is not a named refusal
        return f"CRASH {type(exc).__name__}: {exc}", {}
    return None, json.loads(out.read_text())


def replaced_windows() -> None:
    print("the scorer refuses a trend-row replacement whose window differs from the one it replaces")
    with tempfile.TemporaryDirectory() as t:
        pred = corpus(pathlib.Path(t), *good_sidecars())
        new = pred / "_experiments" / "new"
        for stage, obj in (("resolutions", resolution("trend-resolved", NEW_AS_OF, "not_occurred")),
                           ("priors", prior("trend-resolved", NEW_AS_OF, 0.4))):
            (new / stage / "ada").mkdir(parents=True)
            (new / stage / "ada" / "trend-resolved.json").write_text(json.dumps(obj))
        manifest = pred / "replacements.json"
        manifest.write_text(json.dumps({"schema_version": 1, "replacements": [
            {"stage": s, "prediction_id": "trend-resolved", "run": "predictions/_experiments/run",
             "replacement": "predictions/_experiments/new", "reason": "second look"} for s in ("resolve", "prior")]}))
        for as_of, what in ((NEW_AS_OF, "a grown window"), ("2026-09-28", "a window past the as-of, which "
                                                                          "would drop the record silently")):
            why, doc = score_runs(pred, as_of, ["run", "new"], "--replacements", str(manifest))
            row = {r["prediction_id"]: r for r in doc.get("predictions", [])}.get("trend-resolved")
            check(f"as-of {as_of}, {what}: refused, naming the prediction and both windows",
                  bool(why) and not why.startswith("CRASH") and "trend-resolved" in why and FROZEN in why
                  and NEW_AS_OF in why, str(why) if why else f"accepted; row deadline {row and row['deadline']}")

        print("a replacement that keeps the frozen window is scored, and the report shows both windows")
        for stage, obj in (("resolutions", resolution("trend-resolved", FROZEN, "not_occurred")),
                           ("priors", prior("trend-resolved", FROZEN, 0.4))):
            (new / stage / "ada" / "trend-resolved.json").write_text(json.dumps(obj))
        why, doc = score_runs(pred, NEW_AS_OF, ["run", "new"], "--replacements", str(manifest))
        row = {r["prediction_id"]: r for r in doc.get("predictions", [])}.get("trend-resolved") or {}
        check("accepted, scored on the replacement over the frozen window",
              why is None and row.get("deadline") == FROZEN and row.get("outcome") == "not_occurred"
              and row.get("scored"), str(why or row))
        rep = (doc.get("replacements") or {}).get("replaced_sidecars") or []
        check("replacement_report shows the deadline before and after for each replaced sidecar",
              [(x.get("stage"), x.get("deadline_was"), x.get("deadline_now")) for x in rep]
              == [("prior", FROZEN, FROZEN), ("resolve", FROZEN, FROZEN)], json.dumps(rep))

        print("a DATED record's replacement may change its window: only a trend window is frozen")
        for stage, obj in (("resolutions", resolution("dated", "2021-06-30", "occurred")),
                           ("priors", prior("dated", "2021-06-30", 0.5))):
            (new / stage / "ada" / "dated.json").write_text(json.dumps(obj))
        manifest.write_text(json.dumps({"schema_version": 1, "replacements": [
            {"stage": s, "prediction_id": p, "run": "predictions/_experiments/run",
             "replacement": "predictions/_experiments/new", "reason": "second look"}
            for s in ("resolve", "prior") for p in ("trend-resolved", "dated")]}))
        why, doc = score_runs(pred, NEW_AS_OF, ["run", "new"], "--replacements", str(manifest))
        rep = {(x["stage"], x["prediction_id"]): x for x in (doc.get("replacements") or {}).get("replaced_sidecars", [])}
        check("accepted, and the report says the dated record's window moved",
              why is None and (rep.get(("resolve", "dated")) or {}).get("deadline_was") == "2020-12-31"
              and (rep.get(("resolve", "dated")) or {}).get("deadline_now") == "2021-06-30",
              str(why or rep.get(("resolve", "dated"))))


if __name__ == "__main__":
    sys.exit(main())
