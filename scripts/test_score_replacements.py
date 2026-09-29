#!/usr/bin/env python3
"""A re-resolved or re-priced result in a NEW run may replace an old run's sidecar, by name.

Critique A1 of the rescue round-4 root-cause review: the re-run plan writes the
trend regate, the second look and the implied windows into a new run, and
`load_across` stops the scorer when one prediction has sidecars in two runs. The
restatement manifest could supersede a resolution only for a restated cluster.
The replacement manifest is the general form: each entry names the stage, the
prediction, the run whose sidecar is replaced, the run holding its replacement,
and why.

What this pins, end to end through `score_predictions.py`:
  - an UNLISTED duplicate still stops the scorer ("has sidecars in two runs"),
    with or without a manifest that lists other predictions;
  - a listed old sidecar is left out, the replacement is the one scored, and
    scores.json names every replaced sidecar with its run, replacement, reason
    and what it said before;
  - it REFUSES a replaced sidecar that is not there, a replacement that is not
    there, a run that is not being scored, a replacement run equal to the
    replaced run, a chain, a repeated entry, an unknown key or stage, an unknown
    prediction id, and a sidecar superseded by both this manifest and the
    restatement manifest;
  - the window check still holds: a fresh resolution over another window than
    its prior is refused;
  - `replacements` is an OPTIONAL scoring.json key: absent, scores.json carries
    no replacement field and is byte-identical to a run without the feature; named,
    the manifest's bytes are part of `inputs_sha256`, so editing it makes
    scores.json stale for data_sync and the deploy alike.
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


def rec(pid, slug="ada"):
    return {
        "accepted": True, "leader_slug": slug, "prediction_id": pid, "transcript_id": f"{slug}/t1",
        "prediction": {"target_date": "2020-12-31", "specificity": "high", "subject_control": "external",
                       "category": "company_business", "horizon": "explicit", "target_date_text": "x",
                       "horizon_years_inferred": None, "prediction_type": "binary_event",
                       "normalized_claim": f"claim {pid}", "resolution_criteria": "crit"},
        "source": {"statement_date": "2019-01-01", "quote": f"quote {pid}"},
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


def entry(pid, stage="resolve", run="run-a", replacement="run-new", reason="second look", **kw):
    return {"stage": stage, "prediction_id": pid, "run": run, "replacement": replacement, "reason": reason, **kw}


def manifest(path, entries, **top):
    path.write_text(json.dumps({"schema_version": 1, "replacements": entries, **top}))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        corpus = d / "predictions"
        (corpus / "ada").mkdir(parents=True)
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(rec(p)) + "\n" for p in ("p1", "p2", "p3")))
        index = corpus / "index.json"
        index.write_text(json.dumps({"leaders": [{"slug": "ada", "name": "Ada L"}]}))
        a, new = d / "run-a", d / "run-new"
        for pid in ("p1", "p2", "p3"):
            write(a, pid, "resolve")
            write(a, pid, "prior")
        # The second look flipped p1 to a miss; a fresh prior re-priced p2.
        write(new, "p1", "resolve", outcome="not_occurred", reasoning="second look")
        write(new, "p2", "prior", p=0.8, p_raw=0.8, reasoning="re-priced")

        def score(*extra, runs=(a, new), out):
            argv = [sys.executable, str(ROOT / "scripts" / "score_predictions.py"),
                    "--predictions", str(corpus), "--index", str(index), "--as-of", "2026-09-16",
                    "--min-lead-days", "60", "--out", str(out)]
            for r in runs:
                argv += ["--run", str(r)]
            return subprocess.run(argv + list(extra), capture_output=True, text=True)

        def refused(label, entries, needles, runs=(a, new), **top):
            n = len(FAILED) * 1000 + abs(hash(label)) % 1000
            mp = manifest(d / f"bad-{n}.json", entries, **top)
            out = d / f"out-{n}.json"
            p = score("--replacements", str(mp), runs=runs, out=out)
            check(label, p.returncode != 0 and not out.exists() and all(x in p.stderr for x in needles),
                  f"rc={p.returncode} {p.stderr[-500:]}")

        print("an unlisted duplicate still stops the scorer")
        dup = score(out=d / "dup.json")
        check("NO MANIFEST: two runs holding p1's resolution are refused, naming it and both runs",
              dup.returncode != 0 and "has sidecars in two runs" in dup.stderr and "p1" in dup.stderr
              and str(a) in dup.stderr and str(new) in dup.stderr, dup.stderr[-400:])
        refused("PARTIAL MANIFEST: listing p1 alone still refuses p2's unlisted prior in two runs",
                [entry("p1")], ["has sidecars in two runs", "p2"])

        print("a listed replacement is used, and the replaced sidecar is named")
        m = manifest(d / "m.json", [entry("p1"), entry("p2", stage="prior", reason="re-priced")])
        ok = score("--replacements", str(m), out=d / "ok.json")
        check("LISTED: exits 0", ok.returncode == 0, ok.stderr[-600:])
        doc = json.loads((d / "ok.json").read_text()) if ok.returncode == 0 else {}
        rows = {r["prediction_id"]: r for r in doc.get("predictions", [])}
        check("LISTED: p1 is scored on the replacement resolution",
              rows.get("p1", {}).get("outcome") == "not_occurred"
              and rows.get("p1", {}).get("resolution_reasoning") == "second look", str(rows.get("p1")))
        check("LISTED: p2 is scored on the replacement prior",
              rows.get("p2", {}).get("p") == 0.8 and rows.get("p2", {}).get("prior_reasoning") == "re-priced",
              str(rows.get("p2")))
        check("LISTED: p3, which no entry names, is untouched",
              rows.get("p3", {}).get("outcome") == "occurred" and rows.get("p3", {}).get("p") == 0.5)
        blk = doc.get("replacements", {})
        check("REPORT: scores.json names every replaced sidecar with run, replacement, reason, before and after, "
              "and the window each judged",
              blk.get("replaced_sidecars") == [
                  {"stage": "prior", "prediction_id": "p2", "run": "run-a", "replacement": "run-new",
                   "reason": "re-priced", "was": 0.5, "now": 0.8,
                   "deadline_was": "2020-12-31", "deadline_now": "2020-12-31"},
                  {"stage": "resolve", "prediction_id": "p1", "run": "run-a", "replacement": "run-new",
                   "reason": "second look", "was": "occurred", "now": "not_occurred",
                   "deadline_was": "2020-12-31", "deadline_now": "2020-12-31"}],
              json.dumps(blk.get("replaced_sidecars")))
        check("REPORT: the manifest path and its sha256 are recorded, and settings name it",
              blk.get("manifest") == "m.json" and len(blk.get("manifest_sha256") or "") == 64
              and doc.get("settings", {}).get("replacements") == "m.json", str(blk)[:300])
        check("REPORT: counts see one sidecar per prediction",
              doc.get("corpus", {}).get("resolutions_present") == 3 and doc.get("corpus", {}).get("priors_present") == 3,
              str(doc.get("corpus")))

        print("everything a replacement could get wrong is refused")
        refused("REFUSE: a replaced sidecar that is not there, naming it",
                [entry("p1"), entry("p2", stage="prior"), entry("p3", stage="prior", run="run-new", replacement="run-a")],
                ["p3", "run-new", "not among those read"])
        refused("REFUSE: a replacement that is not in its run, naming it",
                [entry("p1"), entry("p2", stage="prior"), entry("p3")], ["p3", "run-new", "there is none there"])
        refused("REFUSE: a run that is not being scored",
                [entry("p1", replacement="run-elsewhere"), entry("p2", stage="prior")], ["run-elsewhere", "not one of the runs being scored"])
        refused("REFUSE: a replacement run equal to the replaced run",
                [entry("p1", replacement="run-a"), entry("p2", stage="prior")], ["p1", "run-a", "as both the run replaced and the replacement"])
        refused("REFUSE: a chain (a sidecar that replaces one is itself replaced)",
                [entry("p1"), entry("p1", run="run-new", replacement="run-a"), entry("p2", stage="prior")],
                ["p1", "both replaced and a replacement, a chain"])
        refused("REFUSE: the same sidecar listed twice",
                [entry("p1"), entry("p1"), entry("p2", stage="prior")], ["p1", "replaced twice"])
        refused("REFUSE: an unknown key in an entry", [entry("p1", note="x"), entry("p2", stage="prior")], ["note", "must carry exactly"])
        refused("REFUSE: an entry with no reason", [entry("p1", reason=""), entry("p2", stage="prior")], ["has no ['reason']"])
        refused("REFUSE: a stage other than resolve or prior",
                [entry("p1", stage="criteria_repair"), entry("p2", stage="prior")], ["stage 'criteria_repair'"])
        refused("REFUSE: an unknown top-level key", [entry("p1"), entry("p2", stage="prior")], ["differs at ['extra']"], extra=1)
        write(new, "zz", "resolve")
        write(a, "zz", "resolve")
        refused("REFUSE: a prediction id that is no accepted record",
                [entry("p1"), entry("p2", stage="prior"), entry("zz")], ["zz", "no accepted record"])
        for f in (R.sidecar_path(new, "resolve", "ada", "zz"), R.sidecar_path(a, "resolve", "ada", "zz")):
            f.unlink()

        win = d / "run-win"
        write(win, "p1", "resolve", deadline="2021-06-30")
        refused("REFUSE: a replacement resolution over another window than its prior",
                [entry("p1", replacement="run-win")], ["p1", "priced over a different window"], runs=(a, win))

        rs = d / "restatements.json"
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(rec(p)) + "\n" for p in ("p1", "p2", "p3", "p4")))
        write(a, "p4", "resolve"); write(a, "p4", "prior")
        rs.write_text(json.dumps({"schema_version": 1, "derived_from": {"file": "f", "sha256": "0"}, "clusters": [
            {"cluster_id": "ada/c", "leader_slug": "ada", "specific_member": "p1", "members": ["p1", "p4"],
             "resolution": {"run": "run-new", "supersedes": [{"run": "run-a", "prediction_id": "p1"}], "why": "x"}}]}))
        both = manifest(d / "both.json", [entry("p1"), entry("p2", stage="prior")])
        p = score("--replacements", str(both), "--restatements", str(rs), out=d / "both-out.json")
        check("REFUSE: one sidecar superseded by both the restatement and the replacement manifest",
              p.returncode != 0 and "p1" in p.stderr
              and "both the restatement manifest and the replacement manifest" in p.stderr,
              p.stderr[-400:])
        (corpus / "ada" / "t1.jsonl").write_text("".join(json.dumps(rec(p)) + "\n" for p in ("p1", "p2", "p3")))
        for f in (R.sidecar_path(a, "resolve", "ada", "p4"), R.sidecar_path(a, "prior", "ada", "p4")):
            f.unlink()

        print("absent means today's behaviour; named, the manifest is fingerprinted")
        plain = score(runs=(a,), out=d / "plain.json")
        empty = score("--replacements", str(manifest(d / "empty.json", [])), runs=(a,), out=d / "empty.json.out")
        pd = json.loads((d / "plain.json").read_text()) if plain.returncode == 0 else {}
        ed = json.loads((d / "empty.json.out").read_text()) if empty.returncode == 0 else {}
        check("ABSENT: scores.json carries no replacement field anywhere",
              plain.returncode == 0 and "replacements" not in pd and "replacements" not in pd.get("settings", {}),
              plain.stderr[-300:] or str(sorted(pd)))
        same = {k: ed.get(k) == pd.get(k) for k in ("as_of", "rule", "calibration", "leaders", "predictions", "corpus")}
        check("EMPTY MANIFEST: every scored block is identical to no manifest at all",
              empty.returncode == 0 and all(same.values()), f"{empty.stderr[-300:]} {same}")

        cfg_path = corpus / "scoring.json"
        base_cfg = {"as_of": "2026-09-16", "trend": False, "min_lead_days": 60, "predictions": ["predictions"],
                    "runs": ["run-a", "run-new"], "index": "predictions/index.json", "out": "predictions/scores.json"}
        # In production the manifest lives under predictions/, because data_sync.py
        # regenerates scores.json from predictions/ and roster/ only.
        pm = corpus / "replacements.json"
        pm.write_text(m.read_text())
        cfg_path.write_text(json.dumps(dict(base_cfg, replacements="predictions/replacements.json")))
        run_cfg = lambda: subprocess.run([sys.executable, str(ROOT / "scripts" / "score_predictions.py"),
                                          "--config", str(cfg_path)], capture_output=True, text=True)
        c = run_cfg()
        cdoc = json.loads((corpus / "scores.json").read_text()) if c.returncode == 0 else {}
        check("CONFIG: an optional replacements key is read from scoring.json",
              c.returncode == 0 and cdoc.get("settings", {}).get("replacements") == "predictions/replacements.json"
              and {r["prediction_id"]: r for r in cdoc.get("predictions", [])}.get("p1", {}).get("outcome") == "not_occurred",
              c.stderr[-400:])
        check("CONFIG: 'replacements' is one of the optional config keys",
              "replacements" in D.OPTIONAL_CONFIG_KEYS, str(D.OPTIONAL_CONFIG_KEYS))
        def staleness():
            try:
                return D.scores_staleness(corpus / "scores.json", cfg_path)
            except SystemExit as exc:
                return f"REFUSED {exc}"
            except Exception as exc:  # noqa: BLE001 - reported as a failed check, not a crash of the test
                return f"REFUSED {type(exc).__name__}: {exc}"
        fresh = staleness()
        pm.write_text(pm.read_text().replace("second look", "second look, re-read"))
        stale = staleness()
        check("CONFIG: scores.json is fresh, then stale once the manifest's bytes change",
              fresh is None and stale is not None and not stale.startswith("REFUSED")
              and "input changed" in stale, f"{fresh!r} / {stale!r}")
        cfg_path.write_text(json.dumps(base_cfg))
        gone = staleness()
        check("CONFIG: dropping the key from scoring.json makes the old scores.json stale",
              gone is not None and "settings" in gone and not gone.startswith("REFUSED"), str(gone))
        cfg_path.write_text(json.dumps(dict(base_cfg, replacement="m.json")))
        typo = run_cfg()
        check("CONFIG: a misspelled key is refused", typo.returncode != 0 and "replacement" in typo.stderr,
              typo.stderr[-300:])
        cfg_path.write_text(json.dumps(dict(base_cfg, replacements="")))
        blank = run_cfg()
        check("CONFIG: an empty path is refused as a path, not as an unknown key",
              blank.returncode != 0 and "replacements must be a path" in blank.stderr, blank.stderr[-300:])
        cfg_path.write_text(json.dumps(dict(base_cfg, replacements="predictions/nowhere.json")))
        miss = run_cfg()
        check("CONFIG: a manifest that does not exist is refused, naming it",
              miss.returncode != 0 and "nowhere.json" in miss.stderr and "Traceback" not in miss.stderr,
              miss.stderr[-300:])
        # Review 0 item 4 and review 1 item 7 of the round-4 funnel change: a
        # manifest outside predictions/ scored here and then failed data_sync.py
        # with a raw FileNotFoundError, because the scratch tree it regenerates in
        # holds only predictions/ and roster/. Refused by name instead.
        for bad in ("m.json", "predictions/../m.json", "/abs/predictions/m.json", "predictions"):
            cfg_path.write_text(json.dumps(dict(base_cfg, replacements=bad)))
            out = run_cfg()
            check(f"CONFIG: a manifest path outside predictions/ ({bad!r}) is refused by name",
                  out.returncode != 0 and "must lie under predictions/" in out.stderr and bad in out.stderr
                  and "Traceback" not in out.stderr, out.stderr[-300:])
            got = staleness()
            check(f"CONFIG: scores_staleness refuses it the same way ({bad!r}), not with a raw error",
                  str(got).startswith("REFUSED") and "must lie under predictions/" in str(got)
                  and "FileNotFoundError" not in str(got), str(got)[-300:])

    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
